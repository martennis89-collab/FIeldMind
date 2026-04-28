"""Iter-12 backend tests: TM can self-delete doctors + bulk-delete + RBAC."""
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


def _create_doctor(token, name, city="DelTestCity"):
    r = requests.post(f"{API}/doctors", headers=H(token), json={
        "doctor_name": name, "clinic_name": "DelTestClinic", "city": city,
        "doctor_type": "GP", "segment": "New",
    }, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()


class TestDoctorDeleteRBAC:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.tm2 = _login("tm2@field.io", "tm123")
        self.admin = _login("admin@field.io", "admin123")
        self.manager = _login("manager@field.io", "manager123")

    def test_tm_can_delete_own_doctor(self):
        d = _create_doctor(self.tm, "Dr Iter12_owndelete")
        r = requests.delete(f"{API}/doctors/{d['id']}", headers=H(self.tm), timeout=10)
        assert r.status_code == 200, r.text
        # Confirm gone
        rl = requests.get(f"{API}/doctors", headers=H(self.tm), timeout=10).json()
        ids = [x["id"] for x in (rl if isinstance(rl, list) else rl.get("doctors", []))]
        assert d["id"] not in ids

    def test_tm_cannot_delete_other_tm_doctor(self):
        d = _create_doctor(self.tm, "Dr Iter12_otherown")
        # tm2 attempts deletion
        r = requests.delete(f"{API}/doctors/{d['id']}", headers=H(self.tm2), timeout=10)
        assert r.status_code in (403, 404), r.text  # 404 if tm2 can't see it; 403 if they can
        # Doctor still exists
        admin_list = requests.get(f"{API}/doctors", headers=H(self.admin), timeout=10).json()
        ids = [x["id"] for x in (admin_list if isinstance(admin_list, list) else admin_list.get("doctors", []))]
        assert d["id"] in ids
        # Cleanup
        requests.delete(f"{API}/doctors/{d['id']}", headers=H(self.admin), timeout=10)

    def test_manager_cannot_delete(self):
        d = _create_doctor(self.tm, "Dr Iter12_mgrnodelete")
        r = requests.delete(f"{API}/doctors/{d['id']}", headers=H(self.manager), timeout=10)
        assert r.status_code == 403
        # Cleanup
        requests.delete(f"{API}/doctors/{d['id']}", headers=H(self.admin), timeout=10)

    def test_bulk_delete_tm_scoped(self):
        a = _create_doctor(self.tm, "Dr Iter12_bulk_a")
        b = _create_doctor(self.tm, "Dr Iter12_bulk_b")
        c_other = _create_doctor(self.tm2, "Dr Iter12_bulk_c_other")  # not owned by tm1
        r = requests.post(f"{API}/doctors/bulk-delete",
                          headers=H(self.tm),
                          json={"ids": [a["id"], b["id"], c_other["id"]]}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["deleted_count"] == 2
        assert set(d["deleted_ids"]) == {a["id"], b["id"]}
        assert c_other["id"] in d["skipped_ids"]
        # Cleanup the other-TM doctor we created
        requests.delete(f"{API}/doctors/{c_other['id']}", headers=H(self.admin), timeout=10)

    def test_bulk_delete_validation(self):
        r = requests.post(f"{API}/doctors/bulk-delete", headers=H(self.tm), json={"ids": []}, timeout=10)
        assert r.status_code == 400
        r2 = requests.post(f"{API}/doctors/bulk-delete", headers=H(self.tm), json={}, timeout=10)
        assert r2.status_code == 400
