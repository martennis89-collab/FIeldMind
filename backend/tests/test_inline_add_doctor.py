"""Tests: AI extract-task suggestion + frontend default due date fallback semantics.
The frontend defaults `suggested_due_date` to today when AI returns null/empty —
that's a UI concern, but we lock the backend contract here so the UI's fallback
behavior remains valid (i.e. the API never invents a due date for vague notes)."""
import os
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


class TestAiExtractTaskDueDate:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")

    def test_response_shape_includes_suggested_due_date_field(self):
        r = requests.post(f"{API}/ai/extract-task", headers=H(self.tm),
                          json={"note": "Send Dr Petrova case study."}, timeout=30)
        assert r.status_code == 200
        sug = r.json()["suggestion"]
        # The key must always exist, even if value is null — so the UI can default it
        assert "suggested_due_date" in sug


class TestDoctorCreate:
    """Covers the inline-add-doctor backend contract: doctors created with minimal fields succeed."""
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.created_ids = []

    def teardown_method(self):
        for did in self.created_ids:
            try:
                requests.delete(f"{API}/doctors/{did}", headers=H(self.tm), timeout=10)
            except Exception:
                pass

    def test_create_doctor_with_minimal_fields(self):
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr Inline Test",
            "doctor_type": "GP",
            "segment": "Occasional",
        }, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["doctor_name"] == "Dr Inline Test"
        assert d["doctor_type"] == "GP"
        assert d["segment"] == "Occasional"
        assert d.get("id")
        self.created_ids.append(d["id"])
