"""Iter-15 backend tests: Meeting CRUD + visit auto-link."""
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


def _future_iso(hours=24):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class TestMeetings:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.tm2 = _login("tm2@field.io", "tm123")
        self.manager = _login("manager@field.io", "manager123")
        # Pick a doctor TM1 owns
        docs = requests.get(f"{API}/doctors", headers=H(self.tm), timeout=10).json()
        self.doctor = docs[0]

    def teardown_method(self):
        # Clean any meetings created by these tests
        try:
            owner = _login("martennis89@gmail.com", "1234")
            meetings = requests.get(f"{API}/meetings?when=all", headers=H(owner), timeout=10).json()
            for m in meetings:
                if (m.get("subject") or "").startswith("iter15"):
                    requests.delete(f"{API}/meetings/{m['id']}", headers=H(owner), timeout=5)
        except Exception:
            pass

    def test_tm_create_and_list(self):
        r = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(48),
            "duration_minutes": 30,
            "subject": "iter15 demo",
        }, timeout=10)
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["doctor_name"]
        assert m["status"] == "Scheduled"
        # Upcoming list contains it
        rl = requests.get(f"{API}/meetings?when=upcoming", headers=H(self.tm), timeout=10).json()
        assert any(x["id"] == m["id"] for x in rl)

    def test_manager_cannot_create(self):
        r = requests.post(f"{API}/meetings", headers=H(self.manager), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(48),
            "subject": "iter15 mgr try",
        }, timeout=10)
        assert r.status_code == 403

    def test_other_tm_cannot_book_for_doctor(self):
        r = requests.post(f"{API}/meetings", headers=H(self.tm2), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(48),
            "subject": "iter15 other",
        }, timeout=10)
        assert r.status_code == 404, r.text  # doctor not visible to tm2

    def test_cancel_delete(self):
        m = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(72),
            "subject": "iter15 cancel",
        }, timeout=10).json()
        d = requests.delete(f"{API}/meetings/{m['id']}", headers=H(self.tm), timeout=10)
        assert d.status_code == 200
        # Gone
        r = requests.get(f"{API}/meetings/{m['id']}", headers=H(self.tm), timeout=10)
        assert r.status_code == 404

    def test_logging_visit_with_meeting_id_completes_meeting(self):
        m = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(2),
            "subject": "iter15 link",
        }, timeout=10).json()
        # Log a visit with the meeting_id
        v = requests.post(f"{API}/visits", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "free_text_note": "iter15 quick visit note",
            "meeting_id": m["id"],
        }, timeout=15)
        assert v.status_code == 200, v.text
        # Meeting should now be Completed and linked
        m2 = requests.get(f"{API}/meetings/{m['id']}", headers=H(self.tm), timeout=10).json()
        assert m2["status"] == "Completed"
        assert m2.get("visit_id")
