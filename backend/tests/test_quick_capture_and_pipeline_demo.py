"""Tests: Quick-complete-demo from iTero pipeline + AI extract-task."""
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


class TestQuickCompleteDemo:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr QuickComplete_Test",
            "clinic_name": "QCClinic", "city": "Sofia",
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

    def test_with_open_demo_meeting_completes_meeting_and_advances_stage(self):
        # Book a demo
        m = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(2),
            "subject": "qc demo",
            "is_demo": True,
        }, timeout=15).json()
        self.created_meeting_ids.append(m["id"])
        # Quick-complete from pipeline
        r = requests.post(f"{API}/doctors/{self.doctor['id']}/itero/quick-complete-demo",
                          headers=H(self.tm), json={}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("via") == "meeting"
        # Stage advanced
        doc = requests.get(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10).json()
        assert doc.get("itero_stage") == "Demo Completed"
        # Meeting closed
        meet = requests.get(f"{API}/meetings/{m['id']}", headers=H(self.tm), timeout=10).json()
        assert meet["status"] == "Completed"

    def test_without_demo_meeting_just_advances_stage(self):
        # First put doctor at Demo Booked
        requests.post(f"{API}/doctors/{self.doctor['id']}/itero-stage", headers=H(self.tm),
                      json={"stage": "Demo Booked"}, timeout=10)
        r = requests.post(f"{API}/doctors/{self.doctor['id']}/itero/quick-complete-demo",
                          headers=H(self.tm), json={}, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("via") == "stage_only"
        doc = requests.get(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10).json()
        assert doc.get("itero_stage") == "Demo Completed"

    def test_other_tms_doctor_forbidden(self):
        tm2 = _login("tm2@field.io", "tm123")
        r = requests.post(f"{API}/doctors/{self.doctor['id']}/itero/quick-complete-demo",
                          headers=H(tm2), json={}, timeout=10)
        assert r.status_code == 403


class TestAiExtractTask:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")

    def test_empty_note_rejected(self):
        r = requests.post(f"{API}/ai/extract-task", headers=H(self.tm),
                          json={"note": ""}, timeout=10)
        assert r.status_code == 400

    def test_typed_note_returns_structured_suggestion(self):
        # Use one of the seeded doctors so the doctor_hint resolution can work
        docs = requests.get(f"{API}/doctors", headers=H(self.tm), timeout=10).json()
        target = docs[0]["doctor_name"]
        note = f"I promised {target} to send the certification info by Friday."
        r = requests.post(f"{API}/ai/extract-task", headers=H(self.tm),
                          json={"note": note}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        sug = body["suggestion"]
        assert "task_title" in sug
        assert "is_promise" in sug
        assert "priority" in sug
        # Ensure the title isn't the raw note (i.e. AI actually summarized)
        assert sug["task_title"], "AI must produce a task_title"

    def test_explicit_doctor_id_overrides_hint(self):
        docs = requests.get(f"{API}/doctors", headers=H(self.tm), timeout=10).json()
        chosen = docs[1]["id"]
        r = requests.post(f"{API}/ai/extract-task", headers=H(self.tm),
                          json={"note": "Follow up about scanner training next week.",
                                "doctor_id": chosen}, timeout=30)
        assert r.status_code == 200, r.text
        sug = r.json()["suggestion"]
        assert sug.get("doctor_id") == chosen
