"""Iteration-10 backend tests: tasks soft-delete + edit fields."""
import os
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


class TestTasksUX:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.tm2 = _login("tm2@field.io", "tm123")
        self.manager = _login("manager@field.io", "manager123")
        self.admin = _login("admin@field.io", "admin123")

    def _create_task(self, token=None):
        if token is None:
            token = self.tm
        # need a doctor I own
        ds = requests.get(f"{API}/doctors", headers=H(token), timeout=15).json()
        if isinstance(ds, dict):
            ds = ds.get("doctors", [])
        doc = ds[0]
        r = requests.post(f"{API}/tasks", headers=H(token), json={
            "doctor_id": doc["id"],
            "task_title": "Iter10 follow-up",
            "task_description": "Initial",
            "due_date": "2026-12-01",
            "priority": "Medium",
        }, timeout=10)
        assert r.status_code == 200, r.text
        return r.json()

    def test_soft_delete_excludes_from_list(self):
        t = self._create_task()
        d = requests.delete(f"{API}/tasks/{t['id']}", headers=H(self.tm), timeout=10)
        assert d.status_code == 200, d.text
        # subsequent list does not contain it
        rows = requests.get(f"{API}/tasks", headers=H(self.tm), timeout=10).json()
        assert all(x["id"] != t["id"] for x in rows)
        # doctor's tasks list also excludes
        dts = requests.get(f"{API}/doctors/{t['doctor_id']}/tasks", headers=H(self.tm), timeout=10).json()
        assert all(x["id"] != t["id"] for x in dts)
        # PUT on deleted task → 410
        u = requests.put(f"{API}/tasks/{t['id']}", headers=H(self.tm), json={"task_title": "x"}, timeout=10)
        assert u.status_code == 410

    def test_complete_sets_completed_at_then_reopen_clears_it(self):
        t = self._create_task()
        c = requests.put(f"{API}/tasks/{t['id']}", headers=H(self.tm), json={"status": "Completed"}, timeout=10)
        assert c.status_code == 200
        assert c.json()["status"] == "Completed"
        assert c.json()["completed_at"]
        r = requests.put(f"{API}/tasks/{t['id']}", headers=H(self.tm), json={"status": "Open"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["status"] == "Open"
        assert r.json().get("completed_at") in (None, "")

    def test_edit_title_description_due_priority(self):
        t = self._create_task()
        u = requests.put(f"{API}/tasks/{t['id']}", headers=H(self.tm), json={
            "task_title": "Iter10 EDITED",
            "task_description": "Updated description",
            "due_date": "2026-12-15",
            "priority": "High",
        }, timeout=10)
        assert u.status_code == 200, u.text
        d = u.json()
        assert d["task_title"] == "Iter10 EDITED"
        assert d["priority"] == "High"
        assert d["due_date"] == "2026-12-15"

    def test_reassign_doctor_validates_access(self):
        t = self._create_task()
        # tm2's doctor — shouldn't be reassignable by tm1
        ds2 = requests.get(f"{API}/doctors", headers=H(self.tm2), timeout=15).json()
        if isinstance(ds2, dict):
            ds2 = ds2.get("doctors", [])
        if not ds2:
            return  # tm2 has no doctors, nothing to assert
        bad_id = ds2[0]["id"]
        r = requests.put(f"{API}/tasks/{t['id']}", headers=H(self.tm), json={"doctor_id": bad_id}, timeout=10)
        assert r.status_code == 400

    def test_other_tm_cannot_delete(self):
        t = self._create_task()
        d = requests.delete(f"{API}/tasks/{t['id']}", headers=H(self.tm2), timeout=10)
        assert d.status_code == 403

    def test_idempotent_delete(self):
        t = self._create_task()
        requests.delete(f"{API}/tasks/{t['id']}", headers=H(self.tm), timeout=10)
        r = requests.delete(f"{API}/tasks/{t['id']}", headers=H(self.tm), timeout=10)
        assert r.status_code == 200
        assert r.json().get("already_deleted") is True
