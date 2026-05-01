"""Tests: self-service password change endpoint."""
import os
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    return r


def H(t):
    return {"Authorization": f"Bearer {t}"}


class TestChangePassword:
    EMAIL = "tm2@field.io"
    ORIGINAL = "tm123"

    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        # Ensure starting from the seed password (may have been left in another state by a failed run)
        # If current password is not the seed one, we can't recover — skip that edge case.
        r = _login(self.EMAIL, self.ORIGINAL)
        assert r.status_code == 200, f"expected {self.EMAIL} to login with seed password, got {r.text}"
        self.token = r.json()["token"]

    def teardown_method(self):
        # Best-effort revert so the seed credentials remain valid for other tests
        r = _login(self.EMAIL, "newpass123")
        if r.status_code == 200:
            tk = r.json()["token"]
            requests.post(
                f"{API}/auth/change-password", headers=H(tk),
                json={"current_password": "newpass123", "new_password": self.ORIGINAL},
                timeout=10,
            )

    def test_requires_auth(self):
        r = requests.post(f"{API}/auth/change-password",
                          json={"current_password": "x", "new_password": "abcdef"}, timeout=10)
        assert r.status_code in (401, 403)

    def test_wrong_current_password_rejected(self):
        r = requests.post(f"{API}/auth/change-password", headers=H(self.token),
                          json={"current_password": "wrong-password", "new_password": "newpass123"},
                          timeout=10)
        assert r.status_code == 400
        assert "incorrect" in r.text.lower()

    def test_new_password_too_short_rejected(self):
        r = requests.post(f"{API}/auth/change-password", headers=H(self.token),
                          json={"current_password": self.ORIGINAL, "new_password": "12"},
                          timeout=10)
        assert r.status_code == 400
        assert "4 characters" in r.text

    def test_same_password_rejected(self):
        # Use a long current password that also meets the length rule so the comparison is the failing check.
        # First change to a known long password, then try to re-set the same value.
        r1 = requests.post(f"{API}/auth/change-password", headers=H(self.token),
                           json={"current_password": self.ORIGINAL, "new_password": "temp-password-999"},
                           timeout=10)
        assert r1.status_code == 200, r1.text
        # Re-login to invalidate the stale token and fetch a fresh one (not strictly required, existing token still works)
        new_token = _login(self.EMAIL, "temp-password-999").json()["token"]
        r2 = requests.post(f"{API}/auth/change-password", headers=H(new_token),
                           json={"current_password": "temp-password-999", "new_password": "temp-password-999"},
                           timeout=10)
        assert r2.status_code == 400
        assert "different" in r2.text.lower()
        # Revert so teardown's "newpass123" branch isn't required
        requests.post(f"{API}/auth/change-password", headers=H(new_token),
                      json={"current_password": "temp-password-999", "new_password": self.ORIGINAL},
                      timeout=10)

    def test_valid_change_allows_login_with_new_password(self):
        r = requests.post(f"{API}/auth/change-password", headers=H(self.token),
                          json={"current_password": self.ORIGINAL, "new_password": "newpass123"},
                          timeout=10)
        assert r.status_code == 200, r.text
        # New password works
        assert _login(self.EMAIL, "newpass123").status_code == 200
        # Old password is rejected
        assert _login(self.EMAIL, self.ORIGINAL).status_code == 401
