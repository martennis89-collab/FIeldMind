"""Tests: /api/itero/demo-breakdown — clickable-tile drill-down with week & all-time scope."""
import os
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _future_iso(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class TestIteroDemoBreakdown:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        # Create a dedicated doctor for this test so counts are predictable
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr DemoBreakdown_Test",
            "clinic_name": "BreakdownClinic", "city": "Sofia",
            "doctor_type": "GP", "segment": "Active",
        }, timeout=10)
        self.doctor = r.json()

    def teardown_method(self):
        try:
            requests.delete(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10)
        except Exception:
            pass

    def test_scope_validation(self):
        r = requests.get(f"{API}/itero/demo-breakdown?scope=bogus", headers=H(self.tm), timeout=10)
        assert r.status_code == 400

    def test_week_counts_booked_demo_meeting(self):
        # Book a demo meeting — is_demo=True, created_at is now (this week)
        r = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(3),
            "subject": "breakdown-test demo",
            "is_demo": True,
        }, timeout=15)
        assert r.status_code == 200, r.text

        b = requests.get(f"{API}/itero/demo-breakdown?scope=week", headers=H(self.tm), timeout=10).json()
        # Must include our doctor in booked
        booked_docs = [x["doctor_id"] for x in b["booked"]]
        assert self.doctor["id"] in booked_docs
        assert b["counts"]["booked"] >= 1

    def test_complete_demo_adds_to_completed_bucket(self):
        # Book then complete
        m = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(1),
            "subject": "breakdown-test complete",
            "is_demo": True,
        }, timeout=15).json()
        c = requests.post(f"{API}/meetings/{m['id']}/complete-demo", headers=H(self.tm), json={
            "interest_level": "High",
        }, timeout=15)
        assert c.status_code == 200, c.text

        b = requests.get(f"{API}/itero/demo-breakdown?scope=week", headers=H(self.tm), timeout=10).json()
        completed_docs = [x["doctor_id"] for x in b["completed"]]
        assert self.doctor["id"] in completed_docs
        assert b["counts"]["completed"] >= 1

        # The meeting-derived visit must NOT also cause a duplicate count
        matching = [x for x in b["completed"] if x["doctor_id"] == self.doctor["id"]]
        assert len(matching) == 1, f"expected dedup between meeting + generated visit, got {len(matching)} rows: {matching}"

    def test_all_scope_is_superset_of_week(self):
        # Book a demo, then inspect both scopes
        requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(2),
            "subject": "breakdown-test allscope",
            "is_demo": True,
        }, timeout=15)
        week = requests.get(f"{API}/itero/demo-breakdown?scope=week", headers=H(self.tm), timeout=10).json()
        all_ = requests.get(f"{API}/itero/demo-breakdown?scope=all", headers=H(self.tm), timeout=10).json()
        assert all_["counts"]["booked"] >= week["counts"]["booked"]
        assert all_["week_start"] is None and all_["week_end"] is None
        assert week["week_start"] is not None

    def test_tm_scoping_is_respected(self):
        # TM2 should not see TM1's doctor in their breakdown
        tm2 = _login("tm2@field.io", "tm123")
        requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(2),
            "subject": "breakdown-test isolation",
            "is_demo": True,
        }, timeout=15)
        b2 = requests.get(f"{API}/itero/demo-breakdown?scope=all", headers=H(tm2), timeout=10).json()
        assert self.doctor["id"] not in [x["doctor_id"] for x in b2["booked"]]
