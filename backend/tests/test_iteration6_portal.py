"""Iteration 6 — Customer Self-Service Portal tests.

Covers: Reschedule, Cancel, Invalid token, Expired token, Admin smoke.
"""
import os
import time
from datetime import date, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://service-book-pro-4.preview.emergentagent.com"
SLUG = "demo-services"
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "service_scheduler"

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin@12345"


# ---------- helpers ----------
@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _find_two_open_slots(s, exclude_date=None, exclude_block=None):
    """Find two distinct (date, block) tuples in current or next month that are available."""
    today = date.today()
    # Current month, then next
    candidates = []
    for offset in (0, 1):
        y = today.year + ((today.month - 1 + offset) // 12)
        m = ((today.month - 1 + offset) % 12) + 1
        month = f"{y:04d}-{m:02d}"
        r = s.get(f"{BASE_URL}/api/public/business/{SLUG}/availability", params={"month": month})
        if r.status_code != 200:
            continue
        for day in r.json().get("days", []):
            if not day["is_working_day"]:
                continue
            for slot in day["slots"]:
                if slot["available"] and (day["date"], slot["time_block"]) != (exclude_date, exclude_block):
                    candidates.append((day["date"], slot["time_block"]))
                if len(candidates) >= 30:
                    break
    return candidates


def _book(s, slot_date, slot_block, name_suffix="portal"):
    payload = {
        "service_type": "Cleaning",
        "local_date": slot_date,
        "local_time_block": slot_block,
        "description": f"TEST_iter6 {name_suffix}",
        "customer": {
            "full_name": f"TEST_iter6 {name_suffix}",
            "email": f"test_iter6_{name_suffix}_{int(time.time()*1000)}@example.com",
            "phone": "+1 555-0000",
            "address": "1 Test St",
        },
    }
    r = s.post(f"{BASE_URL}/api/public/business/{SLUG}/appointments", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ============================================================
# Token validity
# ============================================================
class TestInvalidToken:
    def test_unknown_long_token_404(self, s):
        bad = "this-is-not-a-real-token-aaaaaaaaaaaaa"  # >16 chars
        r = s.get(f"{BASE_URL}/api/portal/{bad}")
        assert r.status_code == 404
        assert r.json()["detail"] == "Invalid or unknown link"

    def test_short_token_404(self, s):
        r = s.get(f"{BASE_URL}/api/portal/short")
        assert r.status_code == 404
        assert r.json()["detail"] == "Invalid or unknown link"

    def test_reschedule_invalid_token_404(self, s):
        bad = "this-is-not-a-real-token-aaaaaaaaaaaaa"
        r = s.post(f"{BASE_URL}/api/portal/{bad}/reschedule",
                   json={"local_date": "2030-01-01", "local_time_block": "09:00-11:00"})
        assert r.status_code == 404

    def test_cancel_invalid_token_404(self, s):
        bad = "this-is-not-a-real-token-aaaaaaaaaaaaa"
        r = s.post(f"{BASE_URL}/api/portal/{bad}/cancel", json={"reason": "x"})
        assert r.status_code == 404


# ============================================================
# Booking returns access_token
# ============================================================
class TestBookingToken:
    def test_booking_response_has_token(self, s):
        cands = _find_two_open_slots(s)
        assert cands, "no available slots"
        d, b = cands[0]
        out = _book(s, d, b, "tokfmt")
        assert "access_token" in out
        assert isinstance(out["access_token"], str)
        assert len(out["access_token"]) >= 16
        assert "portal_url" in out and out["portal_url"].endswith(f"/portal/{out['access_token']}")

    def test_portal_get_returns_appointment(self, s):
        cands = _find_two_open_slots(s)
        d, b = cands[0]
        out = _book(s, d, b, "portget")
        r = s.get(f"{BASE_URL}/api/portal/{out['access_token']}")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "confirmed"
        assert data["local_date"] == d
        assert data["local_time_block"] == b
        assert data["confirmation_code"] == out["confirmation_code"]


# ============================================================
# Reschedule
# ============================================================
class TestReschedule:
    def test_reschedule_happy_path(self, s):
        cands = _find_two_open_slots(s)
        assert len(cands) >= 2
        old_d, old_b = cands[0]
        out = _book(s, old_d, old_b, "resch_ok")
        token = out["access_token"]

        # Pick second slot, not equal to old
        new_d, new_b = next((d, b) for d, b in cands[1:] if (d, b) != (old_d, old_b))

        r = s.post(f"{BASE_URL}/api/portal/{token}/reschedule",
                   json={"local_date": new_d, "local_time_block": new_b})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "confirmed"
        assert data["local_date"] == new_d
        assert data["local_time_block"] == new_b

        # Old slot back to available
        ym = old_d[:7]
        r2 = s.get(f"{BASE_URL}/api/public/business/{SLUG}/availability", params={"month": ym})
        day = next(x for x in r2.json()["days"] if x["date"] == old_d)
        slot = next(sl for sl in day["slots"] if sl["time_block"] == old_b)
        assert slot["available"] is True

        # New slot unavailable
        ym2 = new_d[:7]
        r3 = s.get(f"{BASE_URL}/api/public/business/{SLUG}/availability", params={"month": ym2})
        day2 = next(x for x in r3.json()["days"] if x["date"] == new_d)
        slot2 = next(sl for sl in day2["slots"] if sl["time_block"] == new_b)
        assert slot2["available"] is False

    def test_reschedule_invalid_slot_422(self, s):
        cands = _find_two_open_slots(s)
        d, b = cands[0]
        out = _book(s, d, b, "resch_bad")
        token = out["access_token"]
        # Slot not in business schedule
        r = s.post(f"{BASE_URL}/api/portal/{token}/reschedule",
                   json={"local_date": d, "local_time_block": "03:15-04:15"})
        assert r.status_code == 422

    def test_reschedule_out_of_window_422(self, s):
        cands = _find_two_open_slots(s)
        d, b = cands[0]
        out = _book(s, d, b, "resch_oow")
        token = out["access_token"]
        # Far-future date outside current+next month window
        far = (date.today() + timedelta(days=120)).isoformat()
        r = s.post(f"{BASE_URL}/api/portal/{token}/reschedule",
                   json={"local_date": far, "local_time_block": "09:00-11:00"})
        assert r.status_code == 422

    def test_reschedule_collision_409(self, s):
        cands = _find_two_open_slots(s)
        assert len(cands) >= 2
        d1, b1 = cands[0]
        d2, b2 = cands[1]
        out_a = _book(s, d1, b1, "collA")
        out_b = _book(s, d2, b2, "collB")
        # A tries to reschedule onto B's slot
        r = s.post(f"{BASE_URL}/api/portal/{out_a['access_token']}/reschedule",
                   json={"local_date": d2, "local_time_block": b2})
        assert r.status_code == 409


# ============================================================
# Cancel
# ============================================================
class TestCancel:
    def test_cancel_happy_path_and_outbox(self, s, db):
        cands = _find_two_open_slots(s)
        d, b = cands[0]
        out = _book(s, d, b, "cancel_ok")
        token = out["access_token"]
        appt_id = out["id"]

        # Count existing outbox rows
        before_customer = db.email_outbox.count_documents({
            "appointment_id": appt_id, "template_key": "booking_cancellation_customer"
        }) if "appointment_id" in (db.email_outbox.find_one() or {}) else 0
        # Use to= filter instead since field may not exist:
        cust_email = None
        appt_doc = db.appointments.find_one({"_id": appt_id})
        cust_email = appt_doc["customer"]["email"]
        before_cust = db.email_outbox.count_documents(
            {"to": cust_email, "template_key": "booking_cancellation_customer"}
        )
        before_admin = db.email_outbox.count_documents(
            {"subject": {"$regex": "^\\[Cancelled by customer\\]"}}
        )

        r = s.post(f"{BASE_URL}/api/portal/{token}/cancel", json={"reason": "plans changed"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "cancelled"

        # Verify DB
        doc = db.appointments.find_one({"_id": appt_id})
        assert doc["status"] == "cancelled"
        assert doc["cancellation_reason"] == "plans changed"
        assert doc["cancelled_by"] == "customer"

        # Slot back to available
        ym = d[:7]
        r2 = s.get(f"{BASE_URL}/api/public/business/{SLUG}/availability", params={"month": ym})
        day = next(x for x in r2.json()["days"] if x["date"] == d)
        slot = next(sl for sl in day["slots"] if sl["time_block"] == b)
        assert slot["available"] is True

        # Outbox: customer cancellation email
        after_cust = db.email_outbox.count_documents(
            {"to": cust_email, "template_key": "booking_cancellation_customer"}
        )
        assert after_cust == before_cust + 1

        # Outbox: admin notification with subject starting [Cancelled by customer]
        after_admin = db.email_outbox.count_documents(
            {"subject": {"$regex": "^\\[Cancelled by customer\\]"}}
        )
        assert after_admin == before_admin + 1

    def test_cancel_idempotent(self, s, db):
        cands = _find_two_open_slots(s)
        d, b = cands[0]
        out = _book(s, d, b, "cancel_idem")
        token = out["access_token"]
        appt_id = out["id"]

        r1 = s.post(f"{BASE_URL}/api/portal/{token}/cancel", json={"reason": "first"})
        assert r1.status_code == 200
        cust_email = db.appointments.find_one({"_id": appt_id})["customer"]["email"]
        count1 = db.email_outbox.count_documents(
            {"to": cust_email, "template_key": "booking_cancellation_customer"}
        )
        admin_subj_count1 = db.email_outbox.count_documents(
            {"subject": {"$regex": "^\\[Cancelled by customer\\]"}, "body_html": {"$regex": cust_email}}
        )

        r2 = s.post(f"{BASE_URL}/api/portal/{token}/cancel", json={"reason": "second"})
        assert r2.status_code == 200
        assert r2.json()["status"] == "cancelled"
        count2 = db.email_outbox.count_documents(
            {"to": cust_email, "template_key": "booking_cancellation_customer"}
        )
        assert count2 == count1  # no duplicates

    def test_reschedule_after_cancel_409(self, s):
        cands = _find_two_open_slots(s)
        d, b = cands[0]
        out = _book(s, d, b, "resch_after_cancel")
        token = out["access_token"]
        rc = s.post(f"{BASE_URL}/api/portal/{token}/cancel", json={"reason": "x"})
        assert rc.status_code == 200
        d2, b2 = cands[1]
        r = s.post(f"{BASE_URL}/api/portal/{token}/reschedule",
                   json={"local_date": d2, "local_time_block": b2})
        assert r.status_code == 409
        assert "cancelled" in r.json()["detail"].lower()


# ============================================================
# Expired token
# ============================================================
class TestExpired:
    def test_expired_returns_410(self, s, db):
        cands = _find_two_open_slots(s)
        d, b = cands[0]
        out = _book(s, d, b, "expired")
        token = out["access_token"]
        appt_id = out["id"]

        # Directly set start_at_utc to past
        db.appointments.update_one(
            {"_id": appt_id}, {"$set": {"start_at_utc": "2020-01-01T00:00:00+00:00"}}
        )

        r = s.get(f"{BASE_URL}/api/portal/{token}")
        assert r.status_code == 410, r.text
        assert "expired" in r.json()["detail"].lower()

        r2 = s.post(f"{BASE_URL}/api/portal/{token}/reschedule",
                    json={"local_date": cands[1][0], "local_time_block": cands[1][1]})
        assert r2.status_code == 410

        r3 = s.post(f"{BASE_URL}/api/portal/{token}/cancel", json={"reason": "x"})
        assert r3.status_code == 410


# ============================================================
# Admin smoke (no regression)
# ============================================================
class TestAdminSmoke:
    def test_admin_login_and_list(self, s):
        r = s.post(f"{BASE_URL}/api/admin/auth/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        tok = r.json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        r2 = s.get(f"{BASE_URL}/api/admin/appointments", headers=h)
        assert r2.status_code == 200
        items = r2.json()["items"]
        # Find a non-cancelled appointment
        active = next((a for a in items if a["status"] != "cancelled"), None)
        if active:
            r3 = s.post(
                f"{BASE_URL}/api/admin/appointments/{active['_id'] if '_id' in active else active['id']}/status",
                headers=h, json={"status": "confirmed"},
            )
            assert r3.status_code == 200
