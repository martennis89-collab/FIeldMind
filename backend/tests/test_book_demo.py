"""Iter-21 backend tests: Book a demo via meeting (is_demo flag)."""
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


class TestBookDemo:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr Iter21_demobook",
            "clinic_name": "DemoBookClinic", "city": "Sofia",
            "doctor_type": "GP", "segment": "Active",
        }, timeout=10)
        self.doctor = r.json()

    def teardown_method(self):
        try:
            requests.delete(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10)
        except Exception:
            pass

    def test_book_demo_advances_pipeline_and_appears_in_demos(self):
        scheduled = _future_iso(5)
        r = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": scheduled,
            "duration_minutes": 45,
            "subject": "iter21 iTero demo",
            "is_demo": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["is_demo"] is True
        # Doctor stage should now be "Demo Booked"
        d = requests.get(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10).json()
        assert d.get("itero_stage") == "Demo Booked"
        # Stage history must record the auto-advance
        h = requests.get(f"{API}/doctors/{self.doctor['id']}/itero-stage-history",
                        headers=H(self.tm), timeout=10).json()
        assert any(x["to_stage"] == "Demo Booked" and x["auto"] is True for x in h)
        # Demos overview Booked bucket includes this doctor with the meeting date
        demos = requests.get(f"{API}/itero/demos", headers=H(self.tm), timeout=10).json()
        booked_ids = [x["doctor_id"] for x in demos["booked"]]
        assert self.doctor["id"] in booked_ids

    def test_non_demo_meeting_does_not_advance_stage(self):
        r = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(2),
            "subject": "iter21 plain meeting",
            "is_demo": False,
        }, timeout=15)
        assert r.status_code == 200
        d = requests.get(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10).json()
        # Stage stays None for a fresh doctor
        assert d.get("itero_stage") in (None, "None")
