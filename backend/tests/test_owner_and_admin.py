"""Iter-13 backend tests: Owner role + admin user CRUD (edit/delete/reset-password) + manager_user_id."""
import os
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"

OWNER_EMAIL = "martennis89@gmail.com"
OWNER_PASS = "1234"


def _login(email, password, expect=200):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == expect, r.text
    if expect == 200:
        return r.json()["token"]
    return None


def H(t):
    return {"Authorization": f"Bearer {t}"}


class TestOwnerAndAdminMgmt:
    def setup_method(self):
        # Ensure demo seed exists for Admin role tests
        requests.post(f"{API}/seed/init", timeout=30)
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.admin = _login("admin@field.io", "admin123")

    def teardown_method(self):
        # Clean up any iter13_ users we created
        try:
            users = requests.get(f"{API}/users", headers=H(self.owner), timeout=10).json()
            for u in users:
                if "iter13" in (u.get("email") or "").lower():
                    requests.delete(f"{API}/users/{u['id']}", headers=H(self.owner), timeout=5)
        except Exception:
            pass

    def test_owner_login_works(self):
        assert self.owner is not None
        # Owner profile via /auth/me
        r = requests.get(f"{API}/auth/me", headers=H(self.owner), timeout=10)
        assert r.status_code == 200
        assert r.json()["role"] == "Owner"
        assert r.json()["email"] == OWNER_EMAIL

    def test_owner_can_access_admin_endpoints(self):
        r = requests.get(f"{API}/users", headers=H(self.owner), timeout=10)
        assert r.status_code == 200
        # Owner must appear in list
        emails = [u["email"] for u in r.json()]
        assert OWNER_EMAIL in emails

    def test_admin_cannot_create_owner(self):
        payload = {"full_name": "Iter13 Owner Try", "email": "iter13_owner_try@test.io", "password": "p1234", "role": "Owner"}
        r = requests.post(f"{API}/users", headers=H(self.admin), json=payload, timeout=10)
        assert r.status_code == 403, r.text

    def test_owner_can_create_admin_then_edit_delete(self):
        # Create
        r = requests.post(f"{API}/users", headers=H(self.owner), json={
            "full_name": "Iter13 Admin", "email": "iter13_admin@test.io", "password": "p1234", "role": "Admin",
        }, timeout=10)
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
        # Edit name + role to Manager
        r2 = requests.put(f"{API}/users/{uid}", headers=H(self.owner), json={
            "full_name": "Iter13 Renamed", "role": "Manager",
        }, timeout=10)
        assert r2.status_code == 200
        assert r2.json()["full_name"] == "Iter13 Renamed"
        assert r2.json()["role"] == "Manager"
        # Delete
        r3 = requests.delete(f"{API}/users/{uid}", headers=H(self.owner), timeout=10)
        assert r3.status_code == 200

    def test_admin_cannot_modify_owner(self):
        users = requests.get(f"{API}/users", headers=H(self.admin), timeout=10).json()
        owner_row = next(u for u in users if u["email"] == OWNER_EMAIL)
        r = requests.put(f"{API}/users/{owner_row['id']}", headers=H(self.admin), json={"full_name": "Hacked"}, timeout=10)
        assert r.status_code == 403
        r2 = requests.delete(f"{API}/users/{owner_row['id']}", headers=H(self.admin), timeout=10)
        assert r2.status_code == 403

    def test_password_reset_flow(self):
        # Owner creates a TM
        r = requests.post(f"{API}/users", headers=H(self.owner), json={
            "full_name": "Iter13 TM PW", "email": "iter13_tmpw@test.io", "password": "old1234", "role": "TM",
        }, timeout=10)
        uid = r.json()["id"]
        # Login with old password works
        _login("iter13_tmpw@test.io", "old1234")
        # Owner resets
        r2 = requests.put(f"{API}/users/{uid}", headers=H(self.owner), json={"password": "new9876"}, timeout=10)
        assert r2.status_code == 200
        # Old password rejected
        _login("iter13_tmpw@test.io", "old1234", expect=401)
        # New password works
        _login("iter13_tmpw@test.io", "new9876")

    def test_assign_tm_to_team_and_manager(self):
        # Get a team + manager from seed
        teams = requests.get(f"{API}/teams", headers=H(self.owner), timeout=10).json()
        users = requests.get(f"{API}/users", headers=H(self.owner), timeout=10).json()
        team = teams[0]
        manager = next(u for u in users if u["role"] == "Manager")
        # Create TM assigned to that team + manager
        r = requests.post(f"{API}/users", headers=H(self.owner), json={
            "full_name": "Iter13 Assigned TM",
            "email": "iter13_assigned@test.io",
            "password": "p1234",
            "role": "TM",
            "team_id": team["id"],
            "manager_user_id": manager["id"],
        }, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["team_id"] == team["id"]
        assert body["manager_user_id"] == manager["id"]
        # Reassign to no manager
        r2 = requests.put(f"{API}/users/{body['id']}", headers=H(self.owner), json={"manager_user_id": None}, timeout=10)
        assert r2.status_code == 200
        # Confirm null in fresh fetch
        users2 = requests.get(f"{API}/users", headers=H(self.owner), timeout=10).json()
        target = next(u for u in users2 if u["id"] == body["id"])
        assert target.get("manager_user_id") is None

    def test_cannot_self_delete(self):
        r = requests.delete(f"{API}/users/{requests.get(f'{API}/auth/me', headers=H(self.owner), timeout=10).json()['id']}",
                            headers=H(self.owner), timeout=10)
        assert r.status_code == 409

    def test_admin_can_disable_tm(self):
        """Bug fix verification: admin can deactivate a TM."""
        # Create a TM
        r = requests.post(f"{API}/users", headers=H(self.owner), json={
            "full_name": "Iter13 TM Disable", "email": "iter13_tmdis@test.io", "password": "p1234", "role": "TM",
        }, timeout=10)
        uid = r.json()["id"]
        # Admin deactivates
        r2 = requests.put(f"{API}/users/{uid}", headers=H(self.admin), json={"active_status": False}, timeout=10)
        assert r2.status_code == 200, r2.text
        # Login should now fail
        _login("iter13_tmdis@test.io", "p1234", expect=403)
