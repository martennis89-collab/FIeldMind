"""Iteration-7 backend tests: editable Admin taxonomy."""
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


class TestTaxonomyEditable:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.admin = _login("admin@field.io", "admin123")
        self.tm = _login("tm1@field.io", "tm123")
        self.manager = _login("manager@field.io", "manager123")

    def test_public_taxonomy_returns_db_backed_groups(self):
        r = requests.get(f"{API}/taxonomy", headers=H(self.tm), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d.get("topics"), dict) and d["topics"]
        assert isinstance(d.get("barriers"), dict) and d["barriers"]
        # Sanity: each category maps to a list of strings
        for cat, terms in d["topics"].items():
            assert isinstance(terms, list)
            assert all(isinstance(t, str) for t in terms)

    def test_admin_list_terms(self):
        r = requests.get(f"{API}/admin/taxonomy", headers=H(self.admin), timeout=15)
        assert r.status_code == 200
        terms = r.json()["terms"]
        assert len(terms) > 30
        kinds = {t["kind"] for t in terms}
        assert kinds == {"topic", "barrier"}

    def test_tm_forbidden_on_admin_endpoints(self):
        r = requests.get(f"{API}/admin/taxonomy", headers=H(self.tm), timeout=10)
        assert r.status_code == 403
        r = requests.post(f"{API}/admin/taxonomy", headers=H(self.tm),
                          json={"kind": "topic", "category": "X", "term": "Y"}, timeout=10)
        assert r.status_code == 403

    def test_manager_forbidden(self):
        r = requests.get(f"{API}/admin/taxonomy", headers=H(self.manager), timeout=10)
        assert r.status_code == 403

    def test_create_update_delete_lifecycle(self):
        # Create
        payload = {"kind": "topic", "category": "TestCat", "term": "TEST_term_iter7"}
        # Cleanup any leftover
        existing = requests.get(f"{API}/admin/taxonomy", headers=H(self.admin)).json()["terms"]
        for t in existing:
            if t["term"].startswith("TEST_term_iter7"):
                requests.delete(f"{API}/admin/taxonomy/{t['id']}", headers=H(self.admin))
        r = requests.post(f"{API}/admin/taxonomy", headers=H(self.admin), json=payload, timeout=10)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]

        # Visible in public taxonomy
        d = requests.get(f"{API}/taxonomy", headers=H(self.tm)).json()
        assert "TEST_term_iter7" in d["topics"].get("TestCat", [])

        # Duplicate rejected
        dup = requests.post(f"{API}/admin/taxonomy", headers=H(self.admin), json=payload, timeout=10)
        assert dup.status_code == 409

        # Update
        upd = requests.put(f"{API}/admin/taxonomy/{tid}", headers=H(self.admin),
                           json={"term": "TEST_term_iter7_renamed", "category": "TestCat"}, timeout=10)
        assert upd.status_code == 200
        assert upd.json()["term"] == "TEST_term_iter7_renamed"

        # Empty term rejected
        bad = requests.put(f"{API}/admin/taxonomy/{tid}", headers=H(self.admin),
                           json={"term": "  "}, timeout=10)
        assert bad.status_code == 400

        # Delete
        rd = requests.delete(f"{API}/admin/taxonomy/{tid}", headers=H(self.admin), timeout=10)
        assert rd.status_code == 200
        # 404 on second delete
        rd2 = requests.delete(f"{API}/admin/taxonomy/{tid}", headers=H(self.admin), timeout=10)
        assert rd2.status_code == 404

    def test_create_validation(self):
        # Missing fields
        r = requests.post(f"{API}/admin/taxonomy", headers=H(self.admin),
                          json={"kind": "topic", "term": "X"}, timeout=10)
        assert r.status_code == 400
        # Bad kind
        r = requests.post(f"{API}/admin/taxonomy", headers=H(self.admin),
                          json={"kind": "garbage", "category": "C", "term": "T"}, timeout=10)
        assert r.status_code == 400
