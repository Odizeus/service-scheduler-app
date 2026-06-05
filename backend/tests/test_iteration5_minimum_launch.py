"""Iteration 5 - Minimum Launch Finish.

Covers ONLY:
  1. Business Settings (PATCH /api/admin/business, validation, public exposure)
  2. Appointment Statuses (POST /api/admin/appointments/{id}/status, filter)
  3. Cancellation Workflow (reason, keep_slot_blocked override, email_outbox, idempotency)
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

# resolve REACT_APP_BACKEND_URL
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    fe_env = Path("/app/frontend/.env")
    for line in fe_env.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break
assert BASE_URL, "REACT_APP_BACKEND_URL not configured"

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "service_scheduler"
SLUG = "demo-services"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin@12345"


# ------------------------- fixtures -------------------------
@pytest.fixture(scope="session")
def token():
    r = requests.post(
        f"{BASE_URL}/api/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def H(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session", autouse=True)
def restore_business_name(H):
    """Snapshot Identity fields before tests, restore after suite."""
    snap = requests.get(f"{BASE_URL}/api/admin/business", headers=H, timeout=20).json()
    yield
    restore = {
        "name": "Demo Service Co.",
        "contact_phone": snap.get("contact_phone", ""),
        "contact_email": snap.get("contact_email", ""),
        "website": snap.get("website", ""),
        "timezone": snap.get("timezone", "America/New_York"),
        "address": snap.get("address", {}),
        "service_types": snap.get("service_types", []),
    }
    requests.patch(f"{BASE_URL}/api/admin/business", headers=H, json=restore, timeout=20)


def _next_working_date_iso(offset_days=14):
    """Pick a Mon-Fri date offset_days out, within the current/next month window."""
    d = date.today() + timedelta(days=offset_days)
    while d.isoweekday() > 5:
        d += timedelta(days=1)
    return d.isoformat()


def _pick_available_slot(slug, ymd):
    """Get any available slot on a date from the public availability endpoint."""
    month = ymd[:7]
    r = requests.get(f"{BASE_URL}/api/public/business/{slug}/availability", params={"month": month}, timeout=20)
    r.raise_for_status()
    for day in r.json().get("days", []):
        if day["date"] == ymd:
            for s in day["slots"]:
                if s["available"]:
                    return s["time_block"]
    return None


def _create_appt(H, ymd, slot, name_prefix="TEST_iter5"):
    body = {
        "customer": {
            "full_name": f"{name_prefix} {uuid.uuid4().hex[:6]}",
            "email": f"test+{uuid.uuid4().hex[:6]}@example.com",
            "phone": "+1 555 010 2000",
            "address": "123 Test St, Town",
        },
        "service_type": "Repair",  # may be replaced below
        "description": "iter5 smoke",
        "local_date": ymd,
        "local_time_block": slot,
    }
    biz = requests.get(f"{BASE_URL}/api/public/business/{SLUG}", timeout=20).json()
    body["service_type"] = biz["service_types"][0]
    r = requests.post(f"{BASE_URL}/api/public/business/{SLUG}/appointments", json=body, timeout=20)
    assert r.status_code == 200, f"create appt failed: {r.status_code} {r.text}"
    return r.json()


# ===================== 1. BUSINESS SETTINGS =====================
class TestBusinessSettings:
    def test_patch_persists_all_fields(self, H):
        payload = {
            "name": "Acme Garage Doors",
            "contact_phone": "+1 (555) 999-0001",
            "contact_email": "hi@acme.test",
            "address": {"street": "1 Main", "city": "Townsville", "state": "CA", "zip": "94000", "country": "US"},
            "website": "https://acme.example.com",
            "timezone": "America/Los_Angeles",
            "service_types": ["Repair", "Installation", "Maintenance", "Inspection"],
        }
        r = requests.patch(f"{BASE_URL}/api/admin/business", headers=H, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        # GET admin
        g = requests.get(f"{BASE_URL}/api/admin/business", headers=H, timeout=20).json()
        assert g["name"] == "Acme Garage Doors"
        assert g["contact_phone"] == payload["contact_phone"]
        assert g["contact_email"] == payload["contact_email"]
        assert g["website"] == payload["website"]
        assert g["timezone"] == "America/Los_Angeles"
        assert "Inspection" in g["service_types"]
        # GET public
        p = requests.get(f"{BASE_URL}/api/public/business/{SLUG}", timeout=20).json()
        for k in ("name", "contact_phone", "contact_email", "website", "timezone", "service_types"):
            assert p[k] == g[k], f"public[{k}] mismatch"
        assert p["address"]["city"] == "Townsville"

    def test_invalid_timezone_returns_422(self, H):
        r = requests.patch(f"{BASE_URL}/api/admin/business", headers=H,
                           json={"timezone": "Bogus/Zone"}, timeout=20)
        assert r.status_code == 422, r.text

    def test_website_without_scheme_is_prefixed(self, H):
        r = requests.patch(f"{BASE_URL}/api/admin/business", headers=H,
                           json={"website": "acme.test"}, timeout=20)
        assert r.status_code == 200
        g = requests.get(f"{BASE_URL}/api/admin/business", headers=H, timeout=20).json()
        assert g["website"] == "https://acme.test"
        # restore to a clean valid url for downstream tests
        requests.patch(f"{BASE_URL}/api/admin/business", headers=H,
                       json={"website": "https://acme.example.com",
                             "timezone": "America/New_York"}, timeout=20)

    def test_booking_email_outbox_uses_live_business_name(self, H):
        # Set name to Acme Garage Doors first
        requests.patch(f"{BASE_URL}/api/admin/business", headers=H,
                       json={"name": "Acme Garage Doors"}, timeout=20)
        ymd = _next_working_date_iso(21)
        slot = _pick_available_slot(SLUG, ymd)
        if not slot:
            pytest.skip("no available slot for outbox test")
        appt = _create_appt(H, ymd, slot, name_prefix="TEST_iter5_outbox")

        async def _check():
            cli = AsyncIOMotorClient(MONGO_URL)
            try:
                db = cli[DB_NAME]
                cur = db.email_outbox.find({"template_key": "booking_confirmation_customer"})\
                    .sort("created_at", -1).limit(5)
                rows = [r async for r in cur]
                assert rows, "no email_outbox rows for booking_confirmation_customer"
                # find one matching this confirmation_code if rendered in body, else most-recent
                latest = rows[0]
                body = (latest.get("body_html") or "") + " " + (latest.get("subject") or "")
                assert "Acme Garage Doors" in body, f"live business name not in latest email: {body[:300]}"
                assert "Demo Service Co." not in body, "hardcoded Demo Service Co. leaked into email"
            finally:
                cli.close()

        asyncio.get_event_loop().run_until_complete(_check())


# ===================== 2. APPOINTMENT STATUSES =====================
class TestAppointmentStatuses:
    @pytest.fixture(scope="class")
    def appt(self, H):
        ymd = _next_working_date_iso(28)
        slot = _pick_available_slot(SLUG, ymd)
        if not slot:
            pytest.skip("no slot available")
        return _create_appt(H, ymd, slot, name_prefix="TEST_iter5_status")

    @pytest.mark.parametrize("status", ["pending", "confirmed", "completed", "no_show"])
    def test_status_transitions(self, H, appt, status):
        r = requests.post(f"{BASE_URL}/api/admin/appointments/{appt['id']}/status",
                          headers=H, json={"status": status}, timeout=20)
        assert r.status_code == 200, f"{status}: {r.status_code} {r.text}"
        assert r.json()["status"] == status
        # verify persistence
        g = requests.get(f"{BASE_URL}/api/admin/appointments/{appt['id']}", headers=H, timeout=20).json()
        assert g["status"] == status

    def test_status_cancelled_rejected(self, H, appt):
        r = requests.post(f"{BASE_URL}/api/admin/appointments/{appt['id']}/status",
                          headers=H, json={"status": "cancelled"}, timeout=20)
        assert r.status_code == 400

    @pytest.mark.parametrize("status", ["pending", "confirmed", "cancelled", "completed", "no_show"])
    def test_status_filter(self, H, status):
        r = requests.get(f"{BASE_URL}/api/admin/appointments",
                         headers=H, params={"status": status}, timeout=20)
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["status"] == status


# ===================== 3. CANCELLATION WORKFLOW =====================
class TestCancellationWorkflow:
    def test_cancel_reopen_slot(self, H):
        ymd = _next_working_date_iso(35)
        slot = _pick_available_slot(SLUG, ymd)
        if not slot:
            pytest.skip("no slot available")
        appt = _create_appt(H, ymd, slot, name_prefix="TEST_iter5_cancel_reopen")
        r = requests.post(f"{BASE_URL}/api/admin/appointments/{appt['id']}/cancel",
                          headers=H, json={"reason": "TEST_iter5 customer requested", "keep_slot_blocked": False},
                          timeout=20)
        assert r.status_code == 200
        # slot should be available again
        avail_slot = _pick_available_slot(SLUG, ymd)
        avail_list = requests.get(f"{BASE_URL}/api/public/business/{SLUG}/availability",
                                  params={"month": ymd[:7]}, timeout=20).json()
        day = next((d for d in avail_list["days"] if d["date"] == ymd), None)
        target = next((s for s in day["slots"] if s["time_block"] == slot), None)
        assert target and target["available"] is True, f"slot should be reopened, got {target}"

    def test_cancel_keep_blocked_creates_override(self, H):
        ymd = _next_working_date_iso(42)
        slot = _pick_available_slot(SLUG, ymd)
        if not slot:
            pytest.skip("no slot available")
        appt = _create_appt(H, ymd, slot, name_prefix="TEST_iter5_cancel_block")
        REASON = "TEST_iter5 crew unavailable"
        r = requests.post(f"{BASE_URL}/api/admin/appointments/{appt['id']}/cancel",
                          headers=H, json={"reason": REASON, "keep_slot_blocked": True}, timeout=20)
        assert r.status_code == 200
        # availability should show slot=False
        avail_list = requests.get(f"{BASE_URL}/api/public/business/{SLUG}/availability",
                                  params={"month": ymd[:7]}, timeout=20).json()
        day = next((d for d in avail_list["days"] if d["date"] == ymd), None)
        target = next((s for s in day["slots"] if s["time_block"] == slot), None)
        assert target and target["available"] is False, f"slot should be blocked, got {target}"
        # override should be listed
        ov = requests.get(f"{BASE_URL}/api/admin/availability-overrides",
                          headers=H, params={"from": ymd, "to": ymd}, timeout=20).json()
        match = [o for o in ov["items"]
                 if o.get("scope") == "slot" and o.get("action") == "block"
                 and o.get("local_date") == ymd and o.get("local_time_block") == slot
                 and REASON in (o.get("reason") or "")]
        assert match, f"override not found. items={ov['items']}"

    def test_cancellation_email_in_outbox(self, H):
        ymd = _next_working_date_iso(49)
        slot = _pick_available_slot(SLUG, ymd)
        if not slot:
            pytest.skip("no slot available")
        appt = _create_appt(H, ymd, slot, name_prefix="TEST_iter5_cancel_email")
        REASON = "TEST_iter5 email reason text"
        requests.post(f"{BASE_URL}/api/admin/appointments/{appt['id']}/cancel",
                      headers=H, json={"reason": REASON, "keep_slot_blocked": False}, timeout=20)

        async def _check():
            cli = AsyncIOMotorClient(MONGO_URL)
            try:
                db = cli[DB_NAME]
                cur = db.email_outbox.find({"template_key": "booking_cancellation_customer"})\
                    .sort("created_at", -1).limit(5)
                rows = [r async for r in cur]
                assert rows, "no cancellation email enqueued"
                latest = rows[0]
                blob = (latest.get("body_html") or "") + " " + (latest.get("subject") or "")
                # current business name (we set 'Acme Garage Doors' above OR it could still be that)
                biz = requests.get(f"{BASE_URL}/api/admin/business", headers=H).json()
                assert biz["name"] in blob, f"business name '{biz['name']}' not in cancellation email"
                assert REASON in blob, f"reason not in cancellation email body: {blob[:400]}"
            finally:
                cli.close()
        asyncio.get_event_loop().run_until_complete(_check())

    def test_recancel_is_idempotent(self, H):
        ymd = _next_working_date_iso(56)
        slot = _pick_available_slot(SLUG, ymd)
        if not slot:
            pytest.skip("no slot available")
        appt = _create_appt(H, ymd, slot, name_prefix="TEST_iter5_idemp")
        REASON = "TEST_iter5 idempotency"
        r1 = requests.post(f"{BASE_URL}/api/admin/appointments/{appt['id']}/cancel",
                           headers=H, json={"reason": REASON, "keep_slot_blocked": True}, timeout=20)
        assert r1.status_code == 200
        r2 = requests.post(f"{BASE_URL}/api/admin/appointments/{appt['id']}/cancel",
                           headers=H, json={"reason": REASON, "keep_slot_blocked": True}, timeout=20)
        assert r2.status_code == 200
        assert r2.json()["status"] == "cancelled"
        # ensure only ONE override for this slot
        ov = requests.get(f"{BASE_URL}/api/admin/availability-overrides",
                          headers=H, params={"from": ymd, "to": ymd}, timeout=20).json()
        match = [o for o in ov["items"]
                 if o.get("scope") == "slot" and o.get("local_time_block") == slot]
        assert len(match) == 1, f"override duplicated on re-cancel: {match}"

        # ensure NO second cancellation email was queued for this appointment
        async def _count_emails():
            cli = AsyncIOMotorClient(MONGO_URL)
            try:
                db = cli[DB_NAME]
                cust_email = (await db.appointments.find_one({"_id": appt["id"]}))["customer"]["email"]
                n = await db.email_outbox.count_documents({
                    "template_key": "booking_cancellation_customer",
                    "to": cust_email,
                })
                return n
            finally:
                cli.close()
        n = asyncio.get_event_loop().run_until_complete(_count_emails())
        assert n == 1, f"expected exactly 1 cancellation email for appt, got {n}"
