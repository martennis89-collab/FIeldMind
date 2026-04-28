"""Iter-10 follow-up: TM can manually add a single doctor via POST /doctors."""
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


class TestManualDoctorAdd:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.admin = _login("admin@field.io", "admin123")
        self.created_ids = []

    def teardown_method(self):
        for cid in self.created_ids:
            try:
                requests.delete(f"{API}/doctors/{cid}", headers=H(self.admin), timeout=5)
            except Exception:
                pass

    def test_tm_can_create_doctor_self_assigned(self):
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr Iter10_manual",
            "clinic_name": "Manual Practice",
            "city": "Sofia",
            "doctor_type": "Ortho",
            "segment": "Active",
            "general_notes": "Added manually by TM",
        }, timeout=10)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["doctor_name"] == "Dr Iter10_manual"
        assert doc["doctor_type"] == "Ortho"
        assert doc["segment"] == "Active"
        # auto-assigned to the calling TM
        users = requests.get(f"{API}/users", headers=H(self.admin), timeout=10).json()
        tm1 = next(u for u in users if u["email"] == "tm1@field.io")
        assert doc["assigned_tm_id"] == tm1["id"]
        assert doc["team_id"] == tm1["team_id"]
        self.created_ids.append(doc["id"])

    def test_required_field(self):
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={"clinic_name": "x"}, timeout=10)
        # Pydantic missing-field → 422
        assert r.status_code in (400, 422)

    def test_invalid_segment_rejected(self):
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr Iter10_bad_seg",
            "segment": "VIP",   # not in allowed Literal values
        }, timeout=10)
        assert r.status_code in (400, 422)
