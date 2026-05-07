"""Tests: /api/meetings/{id}/complete — generic meeting completion (non-demo + demo delegation)."""
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


class TestCompleteMeeting:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr CompleteMeeting_Test",
            "clinic_name": "CMClinic", "city": "Sofia",
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

    def _book(self, is_demo=False):
        m = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(2),
            "subject": ("complete demo" if is_demo else "complete meeting") + " test",
            "is_demo": is_demo,
        }, timeout=15).json()
        self.created_meeting_ids.append(m["id"])
        return m

    def test_complete_nondemo_marks_status_only(self):
        m = self._book(is_demo=False)
        r = requests.post(f"{API}/meetings/{m['id']}/complete", headers=H(self.tm),
                          json={}, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_demo"] is False
        # Verify state
        meet = requests.get(f"{API}/meetings/{m['id']}", headers=H(self.tm), timeout=10).json()
        assert meet["status"] == "Completed"
        # Doctor's iTero stage should NOT have advanced (non-demo)
        doc = requests.get(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10).json()
        assert doc.get("itero_stage") in (None, "None")

    def test_complete_demo_via_generic_endpoint_still_advances_pipeline(self):
        m = self._book(is_demo=True)
        # Use the generic /complete endpoint — it must delegate to /complete-demo
        r = requests.post(f"{API}/meetings/{m['id']}/complete", headers=H(self.tm),
                          json={"outcome_note": "all good"}, timeout=15)
        assert r.status_code == 200, r.text
        # iTero stage should be Demo Completed (auto-advance still fires)
        doc = requests.get(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10).json()
        assert doc.get("itero_stage") == "Demo Completed", f"expected Demo Completed, got {doc.get('itero_stage')}"
        # Meeting is Completed
        meet = requests.get(f"{API}/meetings/{m['id']}", headers=H(self.tm), timeout=10).json()
        assert meet["status"] == "Completed"

    def test_complete_already_completed_rejected(self):
        m = self._book(is_demo=False)
        r1 = requests.post(f"{API}/meetings/{m['id']}/complete", headers=H(self.tm),
                           json={}, timeout=10)
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/meetings/{m['id']}/complete", headers=H(self.tm),
                           json={}, timeout=10)
        assert r2.status_code == 400
        assert "already completed" in r2.text.lower()

    def test_complete_other_tms_meeting_forbidden(self):
        m = self._book(is_demo=False)
        tm2 = _login("tm2@field.io", "tm123")
        r = requests.post(f"{API}/meetings/{m['id']}/complete", headers=H(tm2),
                          json={}, timeout=10)
        assert r.status_code == 403

    def test_outcome_note_appended_to_subject(self):
        m = self._book(is_demo=False)
        r = requests.post(f"{API}/meetings/{m['id']}/complete", headers=H(self.tm),
                          json={"outcome_note": "discussed Q3 plans"}, timeout=10)
        assert r.status_code == 200
        meet = requests.get(f"{API}/meetings/{m['id']}", headers=H(self.tm), timeout=10).json()
        assert "discussed Q3 plans" in (meet.get("subject") or "")
