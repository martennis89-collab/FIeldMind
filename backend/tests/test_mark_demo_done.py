"""Iter-22 backend tests: one-tap Mark demo done."""
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


def _future_iso(days=1):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class TestMarkDemoDone:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr Iter22_demodone",
            "clinic_name": "DemoDoneClinic", "city": "Sofia",
            "doctor_type": "GP", "segment": "Active",
        }, timeout=10)
        self.doctor = r.json()
        # Book a demo
        m = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(2),
            "subject": "iter22 demo",
            "is_demo": True,
        }, timeout=10).json()
        self.meeting = m

    def teardown_method(self):
        try:
            requests.delete(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10)
        except Exception:
            pass

    def test_mark_done_advances_pipeline_and_creates_visit(self):
        r = requests.post(f"{API}/meetings/{self.meeting['id']}/complete-demo",
                          headers=H(self.tm),
                          json={"interest_level": "High", "outcome_note": "iter22 strong interest"},
                          timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["meeting_id"] == self.meeting["id"]
        assert body["visit_id"]
        assert body.get("task_id") is None  # no next_step provided
        # Meeting must be Completed
        m2 = requests.get(f"{API}/meetings/{self.meeting['id']}", headers=H(self.tm), timeout=10).json()
        assert m2["status"] == "Completed"
        assert m2.get("visit_id") == body["visit_id"]
        # Pipeline stage advanced to Demo Completed
        d = requests.get(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10).json()
        assert d.get("itero_stage") == "Demo Completed"
        # Demos overview Completed bucket includes this doctor
        demos = requests.get(f"{API}/itero/demos", headers=H(self.tm), timeout=10).json()
        assert self.doctor["id"] in [x["doctor_id"] for x in demos["completed"]]
        # Already done -> 400 on a second call
        r2 = requests.post(f"{API}/meetings/{self.meeting['id']}/complete-demo",
                          headers=H(self.tm), json={"interest_level": "Medium"}, timeout=15)
        assert r2.status_code == 400

    def test_mark_done_creates_follow_up_task(self):
        future_due = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
        r = requests.post(f"{API}/meetings/{self.meeting['id']}/complete-demo",
                          headers=H(self.tm),
                          json={
                              "interest_level": "Medium",
                              "next_step": "iter22 send pricing proposal",
                              "next_step_due": future_due,
                          }, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["task_id"]
        # Task is open + visible on /tasks
        tasks = requests.get(f"{API}/tasks", headers=H(self.tm), timeout=10).json()
        match = next((t for t in tasks if t["id"] == body["task_id"]), None)
        assert match is not None
        assert match["task_title"] == "iter22 send pricing proposal"
        assert match["status"] == "Open"

    def test_non_demo_meeting_rejected(self):
        # Book a regular meeting (no is_demo)
        plain = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "scheduled_at": _future_iso(3),
            "subject": "iter22 plain",
            "is_demo": False,
        }, timeout=10).json()
        r = requests.post(f"{API}/meetings/{plain['id']}/complete-demo",
                          headers=H(self.tm), json={"interest_level": "Low"}, timeout=10)
        assert r.status_code == 400
        # Cleanup
        requests.delete(f"{API}/meetings/{plain['id']}", headers=H(self.tm), timeout=5)
