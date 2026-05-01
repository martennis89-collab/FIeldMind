"""Tests: /api/itero/demos exposes event counts alongside unique-doctor counts."""
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


class TestIteroDemosEventCounts:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr DemoEvents_Test",
            "clinic_name": "EventsClinic", "city": "Sofia",
            "doctor_type": "GP", "segment": "Active",
        }, timeout=10)
        self.doctor = r.json()

    def teardown_method(self):
        try:
            requests.delete(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10)
        except Exception:
            pass

    def _book_and_complete(self):
        m = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(1),
            "subject": "events-test",
            "is_demo": True,
        }, timeout=15).json()
        c = requests.post(f"{API}/meetings/{m['id']}/complete-demo", headers=H(self.tm),
                          json={"interest_level": "High"}, timeout=15)
        assert c.status_code == 200, c.text
        return m

    def test_counts_expose_booked_and_completed_events(self):
        r = requests.get(f"{API}/itero/demos", headers=H(self.tm), timeout=10).json()
        assert "booked_events" in r["counts"]
        assert "completed_events" in r["counts"]
        # Baseline — our fresh doctor has no events yet
        assert isinstance(r["counts"]["completed_events"], int)

    def test_two_completed_demos_on_same_doctor_yield_two_events_one_row(self):
        # First completed demo
        self._book_and_complete()
        # Second completed demo on same doctor
        self._book_and_complete()

        r = requests.get(f"{API}/itero/demos", headers=H(self.tm), timeout=10).json()
        matching = [x for x in r["completed"] if x["doctor_id"] == self.doctor["id"]]
        assert len(matching) == 1, "expected one row per doctor even with multiple events"
        assert matching[0]["completed_events"] >= 2, f"expected >=2 completed events, got {matching[0]}"
        # The aggregate events count must include both events
        assert r["counts"]["completed_events"] >= r["counts"]["completed"]
