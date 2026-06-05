"""Iteration 7 — Service Area Management end-to-end tests.

Covers:
  - PATCH /api/admin/business with service_area
  - GET /api/admin/business + GET /api/public/business/{slug} expose service_area
  - Booking with policy='block' (city/zip/county matches + out-of-area rejection)
  - Booking with policy='manual_approval' creates pending+needs_approval
  - Admin listing flags needs_approval
  - POST /api/admin/appointments/{id}/status promotes pending -> confirmed
  - Pending booking reserves slot (partial unique index)
  - Empty service area = no restriction
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
SLUG = "demo-services"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin@12345"


# --------- helpers / fixtures ---------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/admin/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


def _patch_service_area(headers, cities=None, zips=None, counties=None, policy="block"):
    body = {
        "service_area": {
            "cities": cities or [],
            "zip_codes": zips or [],
            "counties": counties or [],
            "out_of_area_policy": policy,
        }
    }
    r = requests.patch(f"{BASE_URL}/api/admin/business", headers=headers, json=body, timeout=15)
    assert r.status_code == 200, f"patch failed {r.status_code} {r.text}"
    return r.json()


def _pick_free_slot():
    """Return (date, time_block) from public availability skipping booked ones."""
    today = datetime.utcnow().date()
    for delta in range(0, 60):
        d = (today + timedelta(days=delta)).isoformat()
        r = requests.get(
            f"{BASE_URL}/api/public/business/{SLUG}/availability",
            params={"date": d},
            timeout=15,
        )
        if r.status_code != 200:
            continue
        data = r.json()
        slots = data.get("slots", [])
        for s in slots:
            if s.get("available"):
                return d, s["time_block"]
    raise RuntimeError("No free slot found in 60-day window")


def _book(customer_extra=None, expect_status=None):
    date, tb = _pick_free_slot()
    cust = {
        "full_name": "TEST_iter7 Customer",
        "email": f"test_iter7_{uuid.uuid4().hex[:8]}@example.com",
        "phone": "555-123-4567",
        "address": "123 Main St",
    }
    if customer_extra:
        cust.update(customer_extra)
    payload = {
        "customer": cust,
        "service_type": "Repair",
        "description": "iter7 test",
        "local_date": date,
        "local_time_block": tb,
    }
    r = requests.post(
        f"{BASE_URL}/api/public/business/{SLUG}/appointments", json=payload, timeout=20
    )
    return r, date, tb


# --------- 1. admin config persists ---------
class TestAdminConfig:
    def test_patch_and_get_service_area(self, admin_headers):
        cities = ["New York", "Brooklyn"]
        zips = ["10001", "10010"]
        counties = ["New York County"]
        _patch_service_area(admin_headers, cities, zips, counties, "block")

        r = requests.get(f"{BASE_URL}/api/admin/business", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        sa = r.json().get("service_area", {})
        assert sa.get("cities") == cities
        assert sa.get("zip_codes") == zips
        assert sa.get("counties") == counties
        assert sa.get("out_of_area_policy") == "block"

    def test_public_business_exposes_service_area(self):
        r = requests.get(f"{BASE_URL}/api/public/business/{SLUG}", timeout=15)
        assert r.status_code == 200
        sa = r.json().get("service_area", {})
        assert "New York" in sa.get("cities", [])
        assert "10001" in sa.get("zip_codes", [])
        assert "New York County" in sa.get("counties", [])
        assert sa.get("out_of_area_policy") == "block"


# --------- 2. policy = block ---------
class TestPolicyBlock:
    def test_setup_block(self, admin_headers):
        _patch_service_area(
            admin_headers,
            cities=["New York", "Brooklyn"],
            zips=["10001", "10010"],
            counties=["New York County"],
            policy="block",
        )

    def test_out_of_area_blocks_422(self):
        r, _, _ = _book({"city": "Boston"})
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"
        assert "service area" in r.text.lower()

    def test_city_match_case_insensitive(self):
        r, _, _ = _book({"city": "new YORK"})
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        body = r.json()
        assert body["status"] == "confirmed"
        assert body.get("needs_approval") is False

    def test_zip_match(self):
        # city mismatching but zip in list
        r, _, _ = _book({"city": "boston", "zip": "10001"})
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        body = r.json()
        assert body["status"] == "confirmed"

    def test_county_match_case_insensitive(self):
        r, _, _ = _book({"city": "Far Away", "zip": "99999", "county": "new york county"})
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        assert r.json()["status"] == "confirmed"


# --------- 3. policy = manual_approval ---------
class TestPolicyManualApproval:
    pending_id = None
    pending_slot = None

    def test_setup_manual(self, admin_headers):
        _patch_service_area(
            admin_headers,
            cities=["New York", "Brooklyn"],
            zips=["10001"],
            counties=["New York County"],
            policy="manual_approval",
        )

    def test_out_of_area_creates_pending(self):
        r, date, tb = _book({"city": "Chicago", "zip": "60601"})
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        body = r.json()
        assert body["status"] == "pending"
        assert body["needs_approval"] is True
        TestPolicyManualApproval.pending_id = body["id"]
        TestPolicyManualApproval.pending_slot = (date, tb)

    def test_admin_listing_shows_needs_approval(self, admin_headers):
        assert TestPolicyManualApproval.pending_id, "no pending id"
        r = requests.get(f"{BASE_URL}/api/admin/appointments", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        # Different versions may return list or {items: [...]}
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", r.json().get("appointments", []))
        match = [a for a in items if a.get("id") == TestPolicyManualApproval.pending_id]
        assert match, "pending appt not in admin listing"
        a = match[0]
        assert a["status"] == "pending"
        assert a.get("needs_approval") is True

    def test_slot_hold_409_second_attempt(self):
        # Try booking SAME slot with a different customer that IS in-area
        assert TestPolicyManualApproval.pending_slot
        date, tb = TestPolicyManualApproval.pending_slot
        payload = {
            "customer": {
                "full_name": "TEST_iter7 OtherCustomer",
                "email": f"test_iter7_other_{uuid.uuid4().hex[:6]}@example.com",
                "phone": "555-999-0000",
                "address": "1 Main",
                "city": "New York",
            },
            "service_type": "Repair",
            "description": "collision",
            "local_date": date,
            "local_time_block": tb,
        }
        r = requests.post(
            f"{BASE_URL}/api/public/business/{SLUG}/appointments", json=payload, timeout=15
        )
        assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text}"
        assert "slot" in r.text.lower()

    def test_admin_promote_pending_to_confirmed(self, admin_headers):
        assert TestPolicyManualApproval.pending_id
        r = requests.post(
            f"{BASE_URL}/api/admin/appointments/{TestPolicyManualApproval.pending_id}/status",
            headers=admin_headers,
            json={"status": "confirmed"},
            timeout=15,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        # Verify persisted
        rl = requests.get(f"{BASE_URL}/api/admin/appointments", headers=admin_headers, timeout=15)
        items = rl.json() if isinstance(rl.json(), list) else rl.json().get("items", rl.json().get("appointments", []))
        match = [a for a in items if a.get("id") == TestPolicyManualApproval.pending_id]
        assert match and match[0]["status"] == "confirmed"


# --------- 4. empty service area ---------
class TestEmptyServiceArea:
    def test_empty_allows_anything(self, admin_headers):
        _patch_service_area(admin_headers, cities=[], zips=[], counties=[], policy="block")
        r, _, _ = _book({"city": "SomeRandomCity", "zip": "00000", "county": "NoCounty"})
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        body = r.json()
        assert body["status"] == "confirmed"
        assert body.get("needs_approval") is False


# --------- 5. regression smoke ---------
class TestRegressionSmoke:
    def test_admin_login(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=10,
        )
        assert r.status_code == 200

    def test_public_availability(self):
        d = datetime.utcnow().date().isoformat()
        r = requests.get(
            f"{BASE_URL}/api/public/business/{SLUG}/availability",
            params={"date": d},
            timeout=10,
        )
        assert r.status_code == 200
        assert "slots" in r.json()

    def test_public_business_endpoint(self):
        r = requests.get(f"{BASE_URL}/api/public/business/{SLUG}", timeout=10)
        assert r.status_code == 200
        assert r.json().get("slug") == SLUG


# --------- 6. teardown: restore empty service area + block ---------
class TestZRestore:
    def test_restore_defaults(self, admin_headers):
        _patch_service_area(admin_headers, cities=[], zips=[], counties=[], policy="block")
        r = requests.get(f"{BASE_URL}/api/admin/business", headers=admin_headers, timeout=15)
        sa = r.json().get("service_area", {})
        assert sa.get("cities") == []
        assert sa.get("zip_codes") == []
        assert sa.get("counties") == []
        assert sa.get("out_of_area_policy") == "block"
