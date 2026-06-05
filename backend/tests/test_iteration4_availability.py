"""
Iteration 4 — Targeted QA: Availability Management ONLY.

Six admin verbs to verify:
  1. Block a full day
  2. Unblock a full day
  3. Block an individual time slot
  4. Unblock an individual time slot
  5. View all blocked days (GET /api/admin/availability-overrides + UI section)
  6. View all blocked time slots (GET + UI section)

Plus:
  - Customer calendar immediately reflects blocks
  - Validation (422 missing slot field, 401 no token, 404 unknown id)
  - Smoke: a booking on a non-blocked date+slot still succeeds
"""

import os
import datetime as dt
import requests
import pytest

def _resolve_base_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        # fallback: read from frontend/.env so pytest CLI works without exported env
        try:
            with open("/app/frontend/.env") as f:
                for ln in f:
                    if ln.startswith("REACT_APP_BACKEND_URL="):
                        v = ln.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    if not v:
        raise RuntimeError("REACT_APP_BACKEND_URL not configured")
    return v.rstrip("/")


BASE_URL = _resolve_base_url()
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin@12345"
BIZ_SLUG = "demo-services"


# ---------- shared fixtures ----------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(session):
    r = session.post(
        f"{BASE_URL}/api/admin/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


def _future_monday_iso():
    """Return YYYY-MM-DD for a Monday ~14 days out (working weekday in seed)."""
    today = dt.date.today()
    d = today + dt.timedelta(days=14)
    while d.weekday() != 0:  # 0 = Monday
        d += dt.timedelta(days=1)
    return d.isoformat()


def _month_of(date_iso: str) -> str:
    return date_iso[:7]


# ---------- 1 & 2: Block / Unblock a FULL DAY ----------
class TestBlockUnblockDay:
    def test_block_day_then_calendar_reflects_and_unblock(self, session, auth_headers):
        target = _future_monday_iso()
        month = _month_of(target)

        # baseline: ensure date is currently working
        r0 = session.get(
            f"{BASE_URL}/api/public/business/{BIZ_SLUG}/availability?month={month}"
        )
        assert r0.status_code == 200, r0.text
        baseline = r0.json()
        days_by_date = {d["date"]: d for d in baseline.get("days", [])}
        assert target in days_by_date, f"target {target} not in month payload"
        assert days_by_date[target]["is_working_day"] is True, (
            "Test precondition: target Monday should be a working day"
        )

        # BLOCK the full day
        r1 = session.post(
            f"{BASE_URL}/api/admin/availability-overrides",
            headers=auth_headers,
            json={"scope": "day", "local_date": target, "action": "block",
                  "reason": "TEST_iter4 block-day"},
        )
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert "id" in body and isinstance(body["id"], str) and body["id"]
        assert body["scope"] == "day"
        assert body["local_date"] == target
        assert body["action"] == "block"
        ov_id = body["id"]

        # Customer calendar must immediately reflect the block (no caching staleness)
        r2 = session.get(
            f"{BASE_URL}/api/public/business/{BIZ_SLUG}/availability?month={month}"
        )
        assert r2.status_code == 200, r2.text
        days = {d["date"]: d for d in r2.json().get("days", [])}
        assert days[target]["is_working_day"] is False, (
            f"Blocked day {target} still shows is_working_day=true"
        )

        # UNBLOCK via DELETE
        r3 = session.delete(
            f"{BASE_URL}/api/admin/availability-overrides/{ov_id}",
            headers=auth_headers,
        )
        assert r3.status_code == 200, r3.text
        assert r3.json() == {"deleted": True}

        # Calendar returns to working-day true
        r4 = session.get(
            f"{BASE_URL}/api/public/business/{BIZ_SLUG}/availability?month={month}"
        )
        assert r4.status_code == 200, r4.text
        days = {d["date"]: d for d in r4.json().get("days", [])}
        assert days[target]["is_working_day"] is True, (
            "Unblocked day did not return to is_working_day=true"
        )


# ---------- 3 & 4: Block / Unblock a SINGLE SLOT ----------
class TestBlockUnblockSlot:
    def test_block_slot_targets_only_that_slot_and_unblock(self, session, auth_headers):
        target = _future_monday_iso()
        # pick a future Tuesday so it doesn't collide with the day-test target
        target_date = (dt.date.fromisoformat(target) + dt.timedelta(days=1)).isoformat()
        month = _month_of(target_date)

        # discover an existing slot label on that date
        rb = session.get(
            f"{BASE_URL}/api/public/business/{BIZ_SLUG}/availability?month={month}"
        )
        assert rb.status_code == 200, rb.text
        day_info = next(d for d in rb.json()["days"] if d["date"] == target_date)
        slots = day_info.get("slots", [])
        assert slots, f"No slots returned for {target_date}: {day_info}"
        # use the first slot's label
        slot_label = slots[0]["time_block"]
        other_labels = [s["time_block"] for s in slots[1:]] if len(slots) > 1 else []

        # BLOCK the slot
        r1 = session.post(
            f"{BASE_URL}/api/admin/availability-overrides",
            headers=auth_headers,
            json={
                "scope": "slot",
                "local_date": target_date,
                "local_time_block": slot_label,
                "action": "block",
                "reason": "TEST_iter4 block-slot",
            },
        )
        assert r1.status_code == 200, r1.text
        ov = r1.json()
        assert ov["scope"] == "slot"
        assert ov["local_time_block"] == slot_label
        assert ov["id"]
        ov_id = ov["id"]

        # Customer calendar: only that slot is available=false, others remain true
        r2 = session.get(
            f"{BASE_URL}/api/public/business/{BIZ_SLUG}/availability?month={month}"
        )
        assert r2.status_code == 200
        day_info2 = next(d for d in r2.json()["days"] if d["date"] == target_date)
        slot_map = {s["time_block"]: s for s in day_info2["slots"]}
        assert slot_map[slot_label]["available"] is False, (
            f"Blocked slot {slot_label} still available"
        )
        for lbl in other_labels:
            assert slot_map[lbl]["available"] is True, (
                f"Non-blocked slot {lbl} unexpectedly became unavailable"
            )

        # UNBLOCK
        r3 = session.delete(
            f"{BASE_URL}/api/admin/availability-overrides/{ov_id}",
            headers=auth_headers,
        )
        assert r3.status_code == 200, r3.text
        assert r3.json() == {"deleted": True}

        r4 = session.get(
            f"{BASE_URL}/api/public/business/{BIZ_SLUG}/availability?month={month}"
        )
        day_info3 = next(d for d in r4.json()["days"] if d["date"] == target_date)
        slot_map3 = {s["time_block"]: s for s in day_info3["slots"]}
        assert slot_map3[slot_label]["available"] is True, (
            "Slot did not return to available=true after unblock"
        )


# ---------- 5 & 6: List overrides ----------
class TestListOverrides:
    def test_list_contains_day_and_slot_scopes(self, session, auth_headers):
        target_day = _future_monday_iso()
        # use a far-out Friday for slot to avoid collisions
        slot_date = (dt.date.fromisoformat(target_day) + dt.timedelta(days=4)).isoformat()

        # create two overrides
        rb = session.get(
            f"{BASE_URL}/api/public/business/{BIZ_SLUG}/availability?month={_month_of(slot_date)}"
        )
        slot_day = next(d for d in rb.json()["days"] if d["date"] == slot_date)
        slot_label = slot_day["slots"][0]["time_block"]

        a = session.post(
            f"{BASE_URL}/api/admin/availability-overrides",
            headers=auth_headers,
            json={"scope": "day", "local_date": target_day, "action": "block",
                  "reason": "TEST_iter4 list-day"},
        )
        b = session.post(
            f"{BASE_URL}/api/admin/availability-overrides",
            headers=auth_headers,
            json={"scope": "slot", "local_date": slot_date, "local_time_block": slot_label,
                  "action": "block", "reason": "TEST_iter4 list-slot"},
        )
        assert a.status_code == 200 and b.status_code == 200
        a_id, b_id = a.json()["id"], b.json()["id"]

        try:
            r = session.get(
                f"{BASE_URL}/api/admin/availability-overrides", headers=auth_headers
            )
            assert r.status_code == 200, r.text
            items = r.json().get("items", [])
            assert isinstance(items, list)
            day_items = [
                i for i in items if i["scope"] == "day" and i["action"] == "block"
            ]
            slot_items = [
                i for i in items if i["scope"] == "slot" and i["action"] == "block"
            ]
            assert any(i["id"] == a_id for i in day_items), (
                "Created day-scope block not present in list"
            )
            assert any(i["id"] == b_id for i in slot_items), (
                "Created slot-scope block not present in list"
            )
            # _id must be excluded
            assert all("_id" not in i for i in items), "Mongo _id leaked in API response"
        finally:
            session.delete(
                f"{BASE_URL}/api/admin/availability-overrides/{a_id}",
                headers=auth_headers,
            )
            session.delete(
                f"{BASE_URL}/api/admin/availability-overrides/{b_id}",
                headers=auth_headers,
            )


# ---------- Validation ----------
class TestValidation:
    def test_slot_scope_missing_time_block_returns_422(self, session, auth_headers):
        r = session.post(
            f"{BASE_URL}/api/admin/availability-overrides",
            headers=auth_headers,
            json={"scope": "slot", "local_date": "2026-08-03", "action": "block"},
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"

    def test_post_without_token_returns_401(self, session):
        r = session.post(
            f"{BASE_URL}/api/admin/availability-overrides",
            json={"scope": "day", "local_date": "2026-08-03", "action": "block"},
        )
        assert r.status_code == 401, (
            f"expected 401 without bearer token, got {r.status_code} {r.text}"
        )

    def test_delete_nonexistent_id_returns_404(self, session, auth_headers):
        r = session.delete(
            f"{BASE_URL}/api/admin/availability-overrides/does-not-exist-xyz",
            headers=auth_headers,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text}"


# ---------- Smoke: booking on a non-blocked slot still succeeds ----------
class TestBookingSmoke:
    def test_create_booking_on_open_slot(self, session, auth_headers):
        # pick a future Wednesday far ahead to maximise chance of a free slot
        d = dt.date.today() + dt.timedelta(days=30)
        while d.weekday() != 2:  # Wed
            d += dt.timedelta(days=1)
        date_iso = d.isoformat()
        month = _month_of(date_iso)
        r = session.get(
            f"{BASE_URL}/api/public/business/{BIZ_SLUG}/availability?month={month}"
        )
        assert r.status_code == 200
        day = next(d_ for d_ in r.json()["days"] if d_["date"] == date_iso)
        avail = [s for s in day["slots"] if s["available"]]
        if not avail:
            pytest.skip("No available slot on chosen smoke-test date")
        slot = avail[0]["time_block"]

        # fetch services / service_types for booking payload
        sv = session.get(f"{BASE_URL}/api/public/business/{BIZ_SLUG}")
        assert sv.status_code == 200
        biz = sv.json()
        service_types = biz.get("service_types") or []
        if not service_types:
            pytest.skip("No service_types configured")
        # service_types entries may be strings or dicts
        first = service_types[0]
        service_type = first if isinstance(first, str) else (
            first.get("key") or first.get("name") or first.get("id")
        )

        payload = {
            "service_type": service_type,
            "local_date": date_iso,
            "local_time_block": slot,
            "customer": {
                "full_name": "TEST_iter4 Smoke",
                "email": "test_iter4@example.com",
                "phone": "+15551234567",
                "address": "123 Test Street, Testville, NY 10001",
            },
        }
        bk = session.post(
            f"{BASE_URL}/api/public/business/{BIZ_SLUG}/appointments", json=payload
        )
        assert bk.status_code in (200, 201), f"booking failed: {bk.status_code} {bk.text}"
        body = bk.json()
        assert body.get("id") or body.get("_id") or body.get("appointment_id"), body
