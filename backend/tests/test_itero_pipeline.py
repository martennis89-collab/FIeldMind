"""Iter-16 backend tests: iTero pipeline (stage CRUD + auto-advance + RBAC)."""
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


class TestIteroPipeline:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.tm2 = _login("tm2@field.io", "tm123")
        self.manager = _login("manager@field.io", "manager123")
        # Create a clean doctor for these tests
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr Iter16_pipeline",
            "clinic_name": "PipeClinic", "city": "Sofia",
            "doctor_type": "GP", "segment": "New",
        }, timeout=10)
        assert r.status_code == 200, r.text
        self.doctor = r.json()

    def teardown_method(self):
        try:
            requests.delete(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10)
        except Exception:
            pass

    def test_pipeline_endpoint_returns_grouped(self):
        r = requests.get(f"{API}/itero/pipeline", headers=H(self.tm), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("stages", "groups", "counts", "total"):
            assert k in body
        assert "Demo Discussed" in body["stages"]
        # Our brand-new doctor sits in 'None'
        none_ids = [c["id"] for c in body["groups"].get("None", [])]
        assert self.doctor["id"] in none_ids

    def test_explicit_stage_change_writes_history(self):
        r = requests.post(f"{API}/doctors/{self.doctor['id']}/itero-stage",
                          headers=H(self.tm), json={"stage": "Demo Booked", "note": "iter16 manual"}, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["from_stage"] == "None"
        assert body["to_stage"] == "Demo Booked"
        # History
        h = requests.get(f"{API}/doctors/{self.doctor['id']}/itero-stage-history",
                        headers=H(self.tm), timeout=10).json()
        assert any(x["to_stage"] == "Demo Booked" and x["auto"] is False for x in h)
        # Pipeline now reflects it
        p = requests.get(f"{API}/itero/pipeline", headers=H(self.tm), timeout=10).json()
        booked_ids = [c["id"] for c in p["groups"]["Demo Booked"]]
        assert self.doctor["id"] in booked_ids

    def test_visit_auto_advances_stage(self):
        # Log visit with itero contract_signed → stage should auto-jump to Contract Signed
        v = requests.post(f"{API}/visits", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "free_text_note": "iter16 contract signed in clinic.",
            "itero_actions": {"contract_signed": True, "contract_signed_date": "2026-04-15"},
        }, timeout=20)
        assert v.status_code == 200, v.text
        # Now pipeline should show this doctor under Contract Signed
        p = requests.get(f"{API}/itero/pipeline", headers=H(self.tm), timeout=10).json()
        signed = [c["id"] for c in p["groups"]["Contract Signed"]]
        assert self.doctor["id"] in signed
        # History has an auto entry
        h = requests.get(f"{API}/doctors/{self.doctor['id']}/itero-stage-history",
                        headers=H(self.tm), timeout=10).json()
        assert any(x["to_stage"] == "Contract Signed" and x["auto"] is True for x in h)

    def test_no_backward_auto_advance(self):
        # Set stage to Contract Signed
        requests.post(f"{API}/doctors/{self.doctor['id']}/itero-stage",
                     headers=H(self.tm), json={"stage": "Contract Signed"}, timeout=10)
        # Now log a visit with only demo_discussed — must NOT pull stage backward
        requests.post(f"{API}/visits", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "free_text_note": "iter16 dropped by for chat",
            "itero_actions": {"demo_discussed": True},
        }, timeout=20)
        d = requests.get(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10).json()
        assert d.get("itero_stage") == "Contract Signed"

    def test_lost_is_not_overwritten_by_auto(self):
        # Mark Lost explicitly
        requests.post(f"{API}/doctors/{self.doctor['id']}/itero-stage",
                     headers=H(self.tm), json={"stage": "Lost", "note": "competitor won"}, timeout=10)
        # Log a visit with demo_completed — must not auto-overwrite Lost
        requests.post(f"{API}/visits", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "free_text_note": "iter16 attempted re-engagement",
            "itero_actions": {"demo_completed": True},
        }, timeout=20)
        d = requests.get(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=10).json()
        assert d.get("itero_stage") == "Lost"

    def test_manager_sees_team_pipeline(self):
        # Move our doctor to Demo Completed
        requests.post(f"{API}/doctors/{self.doctor['id']}/itero-stage",
                     headers=H(self.tm), json={"stage": "Demo Completed"}, timeout=10)
        p = requests.get(f"{API}/itero/pipeline", headers=H(self.manager), timeout=10).json()
        # Manager should see our TM's doctor
        all_ids = []
        for col in p["groups"].values():
            all_ids.extend([c["id"] for c in col])
        assert self.doctor["id"] in all_ids

    def test_other_tm_cannot_set_stage(self):
        r = requests.post(f"{API}/doctors/{self.doctor['id']}/itero-stage",
                         headers=H(self.tm2), json={"stage": "Demo Booked"}, timeout=10)
        assert r.status_code == 404  # other TM can't see this doctor
