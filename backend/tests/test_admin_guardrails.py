"""Iter-10 follow-up: Admin user-management guardrails (no last-admin lockout, no self-deactivate)."""
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


class TestAdminGuardrails:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.admin = _login("admin@field.io", "admin123")
        # Track ids to clean up
        self.created_user_ids = []

    def teardown_method(self):
        for uid in self.created_user_ids:
            try:
                requests.put(f"{API}/users/{uid}", headers=H(self.admin),
                             json={"active_status": False, "email": f"deleted_{uid[:8]}@field.io"},
                             timeout=5)
            except Exception:
                pass

    def _admin_id(self):
        users = requests.get(f"{API}/users", headers=H(self.admin), timeout=10).json()
        return next(u["id"] for u in users if u["email"] == "admin@field.io")

    def test_last_admin_cannot_be_deactivated(self):
        admin_id = self._admin_id()
        r = requests.put(f"{API}/users/{admin_id}", headers=H(self.admin),
                         json={"active_status": False}, timeout=10)
        assert r.status_code == 409
        assert "last active Admin" in r.json()["detail"]
        # Also can't be demoted
        r2 = requests.put(f"{API}/users/{admin_id}", headers=H(self.admin),
                          json={"role": "TM"}, timeout=10)
        assert r2.status_code == 409

    def test_self_deactivation_blocked_even_when_other_admins_exist(self):
        # Create a backup admin
        cr = requests.post(f"{API}/users", headers=H(self.admin), json={
            "full_name": "Iter10 Backup Admin",
            "email": "iter10_backup_admin@field.io",
            "password": "pw1234",
            "role": "Admin",
        }, timeout=10)
        assert cr.status_code == 200, cr.text
        backup_id = cr.json()["id"]
        self.created_user_ids.append(backup_id)

        admin_id = self._admin_id()
        # Self-deactivate is still blocked even with a backup admin
        r = requests.put(f"{API}/users/{admin_id}", headers=H(self.admin),
                         json={"active_status": False}, timeout=10)
        assert r.status_code == 409
        assert "your own account" in r.json()["detail"]
        # Self-demote also blocked
        r2 = requests.put(f"{API}/users/{admin_id}", headers=H(self.admin),
                          json={"role": "TM"}, timeout=10)
        assert r2.status_code == 409

        # But the backup CAN be deactivated by the primary admin
        r3 = requests.put(f"{API}/users/{backup_id}", headers=H(self.admin),
                          json={"active_status": False}, timeout=10)
        assert r3.status_code == 200, r3.text
        assert r3.json()["active_status"] is False
