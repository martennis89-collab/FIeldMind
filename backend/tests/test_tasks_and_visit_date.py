"""Iter-17 backend tests: standalone task create + visit_date custom."""
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


class TestTasksAndVisitDate:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.doctor = requests.get(f"{API}/doctors", headers=H(self.tm), timeout=10).json()[0]

    def test_standalone_task_create(self):
        """TM can create a task directly without logging a visit first."""
        r = requests.post(f"{API}/tasks", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "task_title": "iter17 standalone task",
            "task_description": "Send pricing PDF",
            "due_date": "2026-04-30",
            "priority": "High",
        }, timeout=10)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["task_title"] == "iter17 standalone task"
        assert t["status"] == "Open"
        assert t["priority"] == "High"
        # Cleanup
        requests.delete(f"{API}/tasks/{t['id']}", headers=H(self.tm), timeout=5)

    def test_complete_then_reopen_task(self):
        r = requests.post(f"{API}/tasks", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "task_title": "iter17 complete cycle",
            "due_date": "2026-04-30",
            "priority": "Medium",
        }, timeout=10).json()
        # Complete
        c = requests.put(f"{API}/tasks/{r['id']}", headers=H(self.tm), json={"status": "Completed"}, timeout=10)
        assert c.status_code == 200
        assert c.json()["status"] == "Completed"
        # Reopen
        ro = requests.put(f"{API}/tasks/{r['id']}", headers=H(self.tm), json={"status": "Open"}, timeout=10)
        assert ro.status_code == 200
        assert ro.json()["status"] == "Open"
        requests.delete(f"{API}/tasks/{r['id']}", headers=H(self.tm), timeout=5)

    def test_visit_with_custom_date(self):
        """Visit_date sent in body must be persisted (e.g. for catch-up logging)."""
        backdate = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        r = requests.post(f"{API}/visits", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "free_text_note": "iter17 backdated visit",
            "visit_date": backdate,
        }, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        v = body.get("visit") or body  # endpoint returns {visit, created_tasks}
        # Visit date should be roughly the requested date (compare day component)
        saved = v.get("visit_date") or ""
        assert saved.startswith(backdate[:10]), f"Expected {backdate[:10]} got {saved}"
