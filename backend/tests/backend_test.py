"""End-to-end backend tests for the Service Business Scheduler.

Covers:
- Public business + availability + appointment creation
- Validation errors (422) and conflict (409)
- Admin auth (success / failure / missing token)
- Admin appointments listing/filtering, cancel, CSV export
- Availability overrides CRUD
- Business / email-templates updates
- Tenant 401 on missing token, 404 on unknown slug
"""
from __future__ import annotations

import calendar
import io
import os
import csv
import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from datetime import datetime

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to frontend/.env value parsing (testing env)
    from pathlib import Path
    env_path = Path("/app/frontend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
                break

API = f"{BASE_URL}/api"
SLUG = "demo-services"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin@12345"
TZ = "America/Chicago"


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(session):
    r = session.post(
        f"{API}/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def business(session):
    r = session.get(f"{API}/public/business/{SLUG}")
    assert r.status_code == 200, r.text
    return r.json()


def _next_working_date(tz=TZ):
    """Pick a date >= today+2 that is a weekday (Mon-Fri) within this/next month allowed window."""
    now = datetime.now(ZoneInfo(tz))
    d = now.date() + timedelta(days=2)
    # ensure we stay within current+next month
    end_month_y = now.year + (1 if now.month == 12 else 0)
    end_month_m = 1 if now.month == 12 else now.month + 1
    last = date(end_month_y, end_month_m, calendar.monthrange(end_month_y, end_month_m)[1])
    while d.isoweekday() > 5:  # skip Sat(6)/Sun(7)
        d += timedelta(days=1)
    assert d <= last, "no working day within window"
    return d


def _next_weekend_date(tz=TZ):
    now = datetime.now(ZoneInfo(tz))
    d = now.date() + timedelta(days=1)
    while d.isoweekday() <= 5:
        d += timedelta(days=1)
    return d


def _make_customer(prefix="TEST_"):
    return {
        "full_name": f"{prefix}Tester {uuid.uuid4().hex[:6]}",
        "email": f"test+{uuid.uuid4().hex[:6]}@example.com",
        "phone": "+1 555 010 2020",
        "address": "123 Test St, Testville",
    }


# ---------- Public API ----------
class TestPublicAPI:
    def test_root(self, session):
        r = session.get(f"{API}/")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_public_business_ok(self, session):
        r = session.get(f"{API}/public/business/{SLUG}")
        assert r.status_code == 200
        b = r.json()
        assert b["slug"] == SLUG
        assert "availability" in b
        assert "service_types" in b and isinstance(b["service_types"], list)

    def test_public_business_404(self, session):
        r = session.get(f"{API}/public/business/non-existent-slug")
        assert r.status_code == 404

    def test_public_availability_current_month(self, session, business):
        now = datetime.now(ZoneInfo(business["timezone"]))
        month = f"{now.year:04d}-{now.month:02d}"
        r = session.get(f"{API}/public/business/{SLUG}/availability", params={"month": month})
        assert r.status_code == 200
        data = r.json()
        assert data["month"] == month
        assert "days" in data and len(data["days"]) >= 28

    def test_public_availability_invalid_month_format(self, session):
        r = session.get(f"{API}/public/business/{SLUG}/availability", params={"month": "bad"})
        assert r.status_code == 422

    def test_public_availability_outside_window(self, session, business):
        now = datetime.now(ZoneInfo(business["timezone"]))
        y, m = now.year, now.month
        # 3 months ahead
        for _ in range(3):
            m += 1
            if m > 12:
                m = 1
                y += 1
        r = session.get(f"{API}/public/business/{SLUG}/availability", params={"month": f"{y:04d}-{m:02d}"})
        assert r.status_code == 422


# ---------- Booking creation + 409 + 422 ----------
class TestBookingFlow:
    @pytest.fixture(scope="class")
    def booking_state(self):
        # shared mutable state across tests
        return {}

    def test_create_appointment_success(self, session, business, booking_state):
        d = _next_working_date(business["timezone"])
        # pick first 2h slot 10:00-12:00 (default)
        payload = {
            "customer": _make_customer(),
            "service_type": business["service_types"][0],
            "description": "Test booking from pytest",
            "local_date": d.isoformat(),
            "local_time_block": "10:00-12:00",
        }
        r = session.post(f"{API}/public/business/{SLUG}/appointments", json=payload)
        # If 10:00-12:00 already booked from a prior run, try 12:00-14:00 etc.
        if r.status_code == 409:
            for tb in ("12:00-14:00", "14:00-16:00", "16:00-18:00", "18:00-20:00"):
                payload["local_time_block"] = tb
                r = session.post(f"{API}/public/business/{SLUG}/appointments", json=payload)
                if r.status_code == 200:
                    break
        assert r.status_code == 200, f"booking failed: {r.status_code} {r.text}"
        data = r.json()
        assert data["status"] == "confirmed"
        assert len(data["confirmation_code"]) == 8
        booking_state["code"] = data["confirmation_code"]
        booking_state["id"] = data["id"]
        booking_state["date"] = payload["local_date"]
        booking_state["time_block"] = payload["local_time_block"]
        booking_state["service"] = payload["service_type"]

    def test_get_appointment_by_code(self, session, booking_state):
        code = booking_state["code"]
        r = session.get(f"{API}/public/appointments/{code}")
        assert r.status_code == 200
        d = r.json()
        assert d["confirmation_code"] == code
        assert d["status"] == "confirmed"
        assert d["local_date"] == booking_state["date"]

    def test_duplicate_booking_returns_409(self, session, business, booking_state):
        payload = {
            "customer": _make_customer(),
            "service_type": booking_state["service"],
            "description": "dup",
            "local_date": booking_state["date"],
            "local_time_block": booking_state["time_block"],
        }
        r = session.post(f"{API}/public/business/{SLUG}/appointments", json=payload)
        assert r.status_code == 409, f"expected 409 got {r.status_code}: {r.text}"

    def test_booking_outside_window_returns_422(self, session, business):
        now = datetime.now(ZoneInfo(business["timezone"]))
        y, m = now.year, now.month
        for _ in range(3):
            m += 1
            if m > 12:
                m = 1
                y += 1
        far_date = date(y, m, 15).isoformat()
        payload = {
            "customer": _make_customer(),
            "service_type": business["service_types"][0],
            "description": "far",
            "local_date": far_date,
            "local_time_block": "10:00-12:00",
        }
        r = session.post(f"{API}/public/business/{SLUG}/appointments", json=payload)
        assert r.status_code == 422, f"got {r.status_code}: {r.text}"

    def test_booking_weekend_returns_409(self, session, business):
        weekend = _next_weekend_date(business["timezone"]).isoformat()
        payload = {
            "customer": _make_customer(),
            "service_type": business["service_types"][0],
            "description": "weekend",
            "local_date": weekend,
            "local_time_block": "10:00-12:00",
        }
        r = session.post(f"{API}/public/business/{SLUG}/appointments", json=payload)
        assert r.status_code == 409, f"got {r.status_code}: {r.text}"

    def test_booking_invalid_service_returns_422(self, session, business):
        d = _next_working_date(business["timezone"]).isoformat()
        payload = {
            "customer": _make_customer(),
            "service_type": "NotARealService_zzzz",
            "description": "x",
            "local_date": d,
            "local_time_block": "10:00-12:00",
        }
        r = session.post(f"{API}/public/business/{SLUG}/appointments", json=payload)
        assert r.status_code == 422


# ---------- Admin auth ----------
class TestAdminAuth:
    def test_login_success(self, session):
        r = session.post(f"{API}/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        d = r.json()
        assert "access_token" in d and d["business"]["slug"] == SLUG

    def test_login_wrong_password(self, session):
        r = session.post(f"{API}/admin/auth/login", json={"email": ADMIN_EMAIL, "password": "WRONG"})
        assert r.status_code == 401

    def test_admin_me_requires_token(self, session):
        r = session.get(f"{API}/admin/me")
        assert r.status_code == 401

    def test_admin_appointments_requires_token(self, session):
        r = session.get(f"{API}/admin/appointments")
        assert r.status_code == 401


# ---------- Admin appointments + cancel + CSV ----------
class TestAdminAppointments:
    def test_list_appointments(self, session, auth_headers):
        r = session.get(f"{API}/admin/appointments", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data and isinstance(data["items"], list)

    def test_list_with_filters(self, session, auth_headers):
        r = session.get(
            f"{API}/admin/appointments",
            headers=auth_headers,
            params={"status": "confirmed", "q": "TEST_"},
        )
        assert r.status_code == 200

    def test_cancel_appointment_and_slot_reopens(self, session, auth_headers, business):
        # Create a fresh appointment first to cancel
        d = _next_working_date(business["timezone"]).isoformat()
        slot = "18:00-20:00"
        payload = {
            "customer": _make_customer(),
            "service_type": business["service_types"][0],
            "description": "to be cancelled",
            "local_date": d,
            "local_time_block": slot,
        }
        # Avoid hitting unique constraint from previous runs by retrying with different slots
        slots_try = [slot, "16:00-18:00", "14:00-16:00", "12:00-14:00"]
        appt_id = None
        for s in slots_try:
            payload["local_time_block"] = s
            r = session.post(f"{API}/public/business/{SLUG}/appointments", json=payload)
            if r.status_code == 200:
                appt_id = r.json()["id"]
                slot = s
                break
        assert appt_id, "could not create appointment for cancel test"

        # Cancel
        r = session.post(
            f"{API}/admin/appointments/{appt_id}/cancel",
            headers=auth_headers,
            json={"reason": "test"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

        # Verify slot is bookable again (partial unique index ignores cancelled)
        new_payload = {
            "customer": _make_customer(),
            "service_type": business["service_types"][0],
            "description": "rebook",
            "local_date": d,
            "local_time_block": slot,
        }
        r2 = session.post(f"{API}/public/business/{SLUG}/appointments", json=new_payload)
        assert r2.status_code == 200, f"slot did not re-open: {r2.status_code} {r2.text}"

    def test_export_csv(self, session, auth_headers):
        r = session.get(f"{API}/admin/appointments/export.csv", headers=auth_headers)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        rdr = csv.reader(io.StringIO(r.text))
        rows = list(rdr)
        assert rows, "empty csv"
        headers = rows[0]
        for col in ("confirmation_code", "status", "local_date", "local_time_block", "service_type"):
            assert col in headers
        assert len(rows) >= 2, "expected at least one data row"


# ---------- Admin availability + overrides ----------
class TestAdminAvailability:
    def test_update_availability_persists(self, session, auth_headers):
        # Save original
        biz = session.get(f"{API}/admin/business", headers=auth_headers).json()
        original = biz["availability"]

        new_avail = {"working_days": [1, 2, 3, 4, 5], "day_start": "09:00", "day_end": "18:00", "block_minutes": 60}
        r = session.patch(f"{API}/admin/business/availability", headers=auth_headers, json=new_avail)
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["day_start"] == "09:00"
        assert got["block_minutes"] == 60

        # public reflects
        pub = session.get(f"{API}/public/business/{SLUG}").json()
        assert pub["availability"]["day_start"] == "09:00"

        # restore
        r2 = session.patch(f"{API}/admin/business/availability", headers=auth_headers, json=original)
        assert r2.status_code == 200

    def test_override_block_and_delete(self, session, auth_headers, business):
        # Pick a future weekday in current/next month
        d = _next_working_date(business["timezone"]).isoformat()
        body = {"scope": "slot", "local_date": d, "local_time_block": "10:00-12:00", "action": "block", "reason": "TEST"}
        r = session.post(f"{API}/admin/availability-overrides", headers=auth_headers, json=body)
        assert r.status_code == 200, r.text
        oid = r.json()["id"]

        # Check public availability shows that slot as unavailable
        now = datetime.now(ZoneInfo(business["timezone"]))
        month = f"{now.year:04d}-{now.month:02d}"
        if d[:7] != month:
            month = d[:7]
        av = session.get(f"{API}/public/business/{SLUG}/availability", params={"month": month}).json()
        day = next((x for x in av["days"] if x["date"] == d), None)
        assert day is not None
        slot = next((s for s in day["slots"] if s["time_block"] == "10:00-12:00"), None)
        if slot:  # if day is working
            assert slot["available"] is False

        # Booking that slot should now 409
        payload = {
            "customer": _make_customer(),
            "service_type": business["service_types"][0],
            "description": "blocked",
            "local_date": d,
            "local_time_block": "10:00-12:00",
        }
        rb = session.post(f"{API}/public/business/{SLUG}/appointments", json=payload)
        assert rb.status_code == 409

        # Delete override
        rd = session.delete(f"{API}/admin/availability-overrides/{oid}", headers=auth_headers)
        assert rd.status_code == 200
        # Verify gone
        listing = session.get(f"{API}/admin/availability-overrides", headers=auth_headers).json()
        assert all(o["id"] != oid for o in listing["items"])


# ---------- Admin business + templates ----------
class TestAdminBusinessAndTemplates:
    def test_update_business_and_reflect_public(self, session, auth_headers):
        new_name = f"TEST_Demo {uuid.uuid4().hex[:4]}"
        r = session.patch(
            f"{API}/admin/business",
            headers=auth_headers,
            json={"name": new_name, "contact_phone": "+1 555 999 0001"},
        )
        assert r.status_code == 200
        # public reflects
        pub = session.get(f"{API}/public/business/{SLUG}").json()
        assert pub["name"] == new_name
        assert pub["contact_phone"] == "+1 555 999 0001"
        # restore name
        session.patch(f"{API}/admin/business", headers=auth_headers, json={"name": "Demo Service Co."})

    def test_update_templates(self, session, auth_headers):
        body = {
            "booking_confirmation_customer": {
                "subject": "TEST subject {{customer_name}}",
                "body_html": "<p>TEST body {{confirmation_code}}</p>",
            }
        }
        r = session.patch(f"{API}/admin/business/email-templates", headers=auth_headers, json=body)
        assert r.status_code == 200
        d = r.json()
        assert d["booking_confirmation_customer"]["subject"].startswith("TEST subject")

        # GET reflects
        g = session.get(f"{API}/admin/business/email-templates", headers=auth_headers).json()
        assert g["booking_confirmation_customer"]["subject"].startswith("TEST subject")
