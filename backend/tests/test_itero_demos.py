"""Iter-20 backend tests: /api/itero/demos buckets + RBAC."""
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


class TestIteroDemos:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.manager = _login("manager@field.io", "manager123")
        # Create a fresh doctor for these tests
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr Iter20_demos",
            "clinic_name": "DemoClinic", "city": "Sofia",
            "doctor_type": "GP", "segment": "Active",
        }, timeout=10)
        self.doctor = r.json()

    def teardown_method(self):
        try:
            requests.delete(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10)
        except Exception:
            pass

    def _log_visit(self, **itero_actions):
        return requests.post(f"{API}/visits", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "free_text_note": "iter20 demo signal",
            "itero_actions": itero_actions,
        }, timeout=20)

    def test_booked_appears(self):
        future = (datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat()
        r = self._log_visit(demo_booked=True, demo_booked_date=future)
        assert r.status_code == 200
        d = requests.get(f"{API}/itero/demos", headers=H(self.tm), timeout=10).json()
        assert d["counts"]["booked"] >= 1
        ids = [x["doctor_id"] for x in d["booked"]]
        assert self.doctor["id"] in ids
        match = next(x for x in d["booked"] if x["doctor_id"] == self.doctor["id"])
        assert match["booked_date"].startswith(future)

    def test_completed_within_30d(self):
        past = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
        r1 = self._log_visit(demo_booked=True, demo_booked_date=future, demo_completed=True, demo_completed_date=past)
        assert r1.status_code == 200
        d = requests.get(f"{API}/itero/demos", headers=H(self.tm), timeout=10).json()
        completed_ids = [x["doctor_id"] for x in d["completed"]]
        assert self.doctor["id"] in completed_ids
        # Once completed, must not also appear in booked
        booked_ids = [x["doctor_id"] for x in d["booked"]]
        assert self.doctor["id"] not in booked_ids

    def test_lost_bucket(self):
        # First put a demo signal, then mark stage Lost
        self._log_visit(demo_discussed=True, demo_booked=True,
                        demo_booked_date=(datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat())
        r = requests.post(f"{API}/doctors/{self.doctor['id']}/itero-stage",
                          headers=H(self.tm), json={"stage": "Lost", "note": "iter20"}, timeout=10)
        assert r.status_code == 200
        d = requests.get(f"{API}/itero/demos", headers=H(self.tm), timeout=10).json()
        lost_ids = [x["doctor_id"] for x in d["lost"]]
        assert self.doctor["id"] in lost_ids
        # Should NOT appear in booked once Lost
        booked_ids = [x["doctor_id"] for x in d["booked"]]
        assert self.doctor["id"] not in booked_ids

    def test_manager_sees_team_demos(self):
        future = (datetime.now(timezone.utc) + timedelta(days=4)).date().isoformat()
        self._log_visit(demo_booked=True, demo_booked_date=future)
        d = requests.get(f"{API}/itero/demos", headers=H(self.manager), timeout=10).json()
        booked_ids = [x["doctor_id"] for x in d["booked"]]
        assert self.doctor["id"] in booked_ids
