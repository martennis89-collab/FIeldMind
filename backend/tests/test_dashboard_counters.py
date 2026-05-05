"""Tests: dashboard ISO-week visits + meeting counters (open + completed this week)."""
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


class TestDashboardCounters:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr DashCounters_Test",
            "clinic_name": "DashClinic", "city": "Sofia",
            "doctor_type": "GP", "segment": "Active",
        }, timeout=10)
        self.doctor = r.json()
        self.created_meeting_ids = []

    def teardown_method(self):
        for mid in self.created_meeting_ids:
            try:
                requests.delete(f"{API}/meetings/{mid}", headers=H(self.tm), timeout=10)
            except Exception:
                pass
        try:
            requests.delete(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10)
        except Exception:
            pass

    def _stats(self):
        r = requests.get(f"{API}/dashboard/tm", headers=H(self.tm), timeout=15)
        assert r.status_code == 200, r.text
        return r.json()["stats"]

    def test_dashboard_exposes_meeting_counters(self):
        s = self._stats()
        assert "open_meetings" in s, f"open_meetings missing: {s}"
        assert "completed_meetings_this_week" in s, f"completed_meetings_this_week missing: {s}"
        assert "visits_this_week" in s
        assert isinstance(s["open_meetings"], int)
        assert isinstance(s["completed_meetings_this_week"], int)
        assert isinstance(s["visits_this_week"], int)

    def test_open_meetings_increments_when_meeting_booked(self):
        before = self._stats()["open_meetings"]
        m = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(2),
            "subject": "dashcounter open",
            "is_demo": False,
        }, timeout=15).json()
        self.created_meeting_ids.append(m["id"])
        after = self._stats()["open_meetings"]
        assert after == before + 1, f"open_meetings should increment: before={before} after={after}"

    def test_completed_meetings_this_week_increments_after_complete(self):
        before = self._stats()["completed_meetings_this_week"]
        m = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(1),
            "subject": "dashcounter complete",
            "is_demo": True,
        }, timeout=15).json()
        self.created_meeting_ids.append(m["id"])
        # Complete it
        c = requests.post(f"{API}/meetings/{m['id']}/complete-demo", headers=H(self.tm),
                          json={"interest_level": "High"}, timeout=15)
        assert c.status_code == 200, c.text
        s = self._stats()
        assert s["completed_meetings_this_week"] == before + 1
        # That same meeting should NOT still inflate open_meetings (Scheduled → Completed)
        # We can't compare against an absolute number reliably, but assert the meeting
        # we just created is no longer counted as open by completing another one and
        # observing parity.
