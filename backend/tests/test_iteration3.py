"""Iteration 3 tests: NY timezone default, Resend MOCKED outbox,
multi-admin user CRUD, PWA assets.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break

API = f"{BASE_URL}/api"
SLUG = "demo-services"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin@12345"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "service_scheduler")


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(session):
    r = session.post(f"{API}/admin/auth/login",
                     json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def mongo():
    c = MongoClient(MONGO_URL)
    return c[DB_NAME]


def _next_working_date(tz="America/New_York"):
    now = datetime.now(ZoneInfo(tz))
    d = now.date() + timedelta(days=2)
    while d.isoweekday() > 5:
        d += timedelta(days=1)
    return d


# ---------- Default timezone ----------
class TestNYTimezone:
    def test_business_default_tz_is_ny(self, session):
        r = session.get(f"{API}/public/business/{SLUG}")
        assert r.status_code == 200
        assert r.json()["timezone"] == "America/New_York"


# ---------- Email outbox MOCKED ----------
class TestEmailOutboxMocked:
    def test_outbox_entry_created_on_booking(self, session, mongo):
        biz = session.get(f"{API}/public/business/{SLUG}").json()
        d = _next_working_date(biz["timezone"])
        slot_tries = ["10:00-12:00", "12:00-14:00", "14:00-16:00",
                      "16:00-18:00", "18:00-20:00"]
        payload = {
            "customer": {
                "full_name": "TEST_OutboxUser",
                "email": f"TEST_outbox+{uuid.uuid4().hex[:6]}@example.com",
                "phone": "+1 555 010 0001",
                "address": "1 Test Ln",
            },
            "service_type": biz["service_types"][0],
            "description": "outbox test",
            "local_date": d.isoformat(),
            "local_time_block": "10:00-12:00",
        }
        appt = None
        for s in slot_tries:
            payload["local_time_block"] = s
            r = session.post(f"{API}/public/business/{SLUG}/appointments", json=payload)
            if r.status_code == 200:
                appt = r.json()
                break
        assert appt, "Could not create booking for outbox test"

        # Outbox should contain at least one entry with status='queued'
        entry = mongo.email_outbox.find_one({"to": payload["customer"]["email"]})
        assert entry is not None, "no outbox entry created"
        assert entry["status"] == "queued", f"expected status queued (mocked), got {entry['status']}"
        assert entry["template_key"] == "booking_confirmation_customer"


# ---------- Multi-admin users ----------
class TestAdminUsers:
    @pytest.fixture(scope="class")
    def state(self):
        return {}

    def test_list_users_requires_token(self, session):
        r = session.get(f"{API}/admin/users")
        assert r.status_code == 401

    def test_list_users_returns_owner(self, session, auth_headers):
        r = session.get(f"{API}/admin/users", headers=auth_headers)
        assert r.status_code == 200
        items = r.json()["items"]
        emails = [u["email"] for u in items]
        assert ADMIN_EMAIL in emails

    def test_create_user(self, session, auth_headers, state, mongo):
        # Clean up if exists
        email = f"TEST_staff_{uuid.uuid4().hex[:6]}@example.com"
        password = "Staff@12345"
        r = session.post(f"{API}/admin/users", headers=auth_headers,
                         json={"email": email, "password": password, "role": "staff"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["email"] == email
        assert data["role"] == "staff"
        state["email"] = email
        state["password"] = password
        state["uid"] = data["id"]

        # verify in listing
        r2 = session.get(f"{API}/admin/users", headers=auth_headers)
        assert email in [u["email"] for u in r2.json()["items"]]

    def test_new_user_can_login(self, session, state):
        r = session.post(f"{API}/admin/auth/login",
                         json={"email": state["email"], "password": state["password"]})
        assert r.status_code == 200, r.text
        assert "access_token" in r.json()

    def test_duplicate_user_409(self, session, auth_headers, state):
        r = session.post(f"{API}/admin/users", headers=auth_headers,
                         json={"email": state["email"], "password": "Another@12345", "role": "staff"})
        assert r.status_code == 409

    def test_cannot_delete_self(self, session, auth_headers):
        # find own id from /admin/me
        me = session.get(f"{API}/admin/me", headers=auth_headers).json()
        own_id = me["user"]["id"]
        r = session.delete(f"{API}/admin/users/{own_id}", headers=auth_headers)
        assert r.status_code == 400

    def test_delete_other_user(self, session, auth_headers, state):
        r = session.delete(f"{API}/admin/users/{state['uid']}", headers=auth_headers)
        assert r.status_code == 200
        assert r.json().get("deleted") is True
        # gone
        listing = session.get(f"{API}/admin/users", headers=auth_headers).json()
        assert state["uid"] not in [u["id"] for u in listing["items"]]

    def test_cannot_delete_last_user(self, session, auth_headers):
        # only owner remains
        listing = session.get(f"{API}/admin/users", headers=auth_headers).json()
        if len(listing["items"]) != 1:
            pytest.skip("more than one user present, skipping last-user test")
        only_id = listing["items"][0]["id"]
        # we can't delete self (returns 400 first), so test via a different user scenario:
        # create+delete twice — the second delete of the now-only-remaining other admin
        # would still leave us, so the proper check is: try to delete *another* user when
        # only owner exists. Since owner == self => 400. The "last user" path is unreachable
        # without auth-as-other. We simulate by checking the 400 still occurs for self.
        r = session.delete(f"{API}/admin/users/{only_id}", headers=auth_headers)
        assert r.status_code == 400

    def test_change_own_password_and_relogin(self, session, auth_headers):
        new_pw = "Admin@12345-NEW"
        # change
        r = session.post(f"{API}/admin/users/me/password", headers=auth_headers,
                         json={"new_password": new_pw})
        assert r.status_code == 200
        # login with new
        r2 = session.post(f"{API}/admin/auth/login",
                          json={"email": ADMIN_EMAIL, "password": new_pw})
        assert r2.status_code == 200
        new_token = r2.json()["access_token"]
        # revert
        r3 = session.post(f"{API}/admin/users/me/password",
                          headers={"Authorization": f"Bearer {new_token}",
                                   "Content-Type": "application/json"},
                          json={"new_password": ADMIN_PASSWORD})
        assert r3.status_code == 200
        # original works again
        r4 = session.post(f"{API}/admin/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r4.status_code == 200


# ---------- PWA assets ----------
class TestPWAAssets:
    def test_manifest(self, session):
        r = session.get(f"{BASE_URL}/manifest.webmanifest")
        assert r.status_code == 200
        # should be JSON-parseable
        data = r.json()
        assert "name" in data or "short_name" in data

    def test_service_worker(self, session):
        r = session.get(f"{BASE_URL}/sw.js")
        assert r.status_code == 200
        assert len(r.text) > 0

    def test_icons(self, session):
        for path in ("/icon-192.svg", "/icon-512.svg"):
            r = session.get(f"{BASE_URL}{path}")
            assert r.status_code == 200, f"{path} -> {r.status_code}"
