"""Iteration 4 — strict iTero/Invisalign separation tests."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://territory-intel-8.preview.emergentagent.com").rstrip("/")


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    requests.post(f"{BASE_URL}/api/seed/init", timeout=30)
    return _login("admin@field.io", "admin123")


@pytest.fixture(scope="module")
def manager_token():
    return _login("manager@field.io", "manager123")


@pytest.fixture(scope="module")
def tm_token():
    return _login("tm1@field.io", "tm123")


def H(t):
    return {"Authorization": f"Bearer {t}"}


# ---------- Manager iTero ----------
class TestManagerItero:
    def test_manager_itero_shape(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/manager/itero", headers=H(manager_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("demo_funnel", "scanner_interest", "top_concerns", "drop_offs", "by_tm"):
            assert k in data, f"missing {k}"
        for k in ("discussed", "booked", "completed", "pending", "booking_rate", "completion_rate"):
            assert k in data["demo_funnel"], f"demo_funnel missing {k}"
        for k in ("High", "Medium", "Low", "None"):
            assert k in data["scanner_interest"], f"scanner_interest missing {k}"
        assert isinstance(data["by_tm"], list)

    def test_tm_forbidden_manager_itero(self, tm_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/manager/itero", headers=H(tm_token), timeout=20)
        assert r.status_code == 403


# ---------- Manager Invisalign ----------
class TestManagerInvisalign:
    def test_manager_invisalign_shape(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/manager/invisalign", headers=H(manager_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("coverage", "confidence", "affordability", "barriers_by_segment", "growth_opportunities"):
            assert k in data, f"missing {k}"
        for k in ("growth_program_pct", "certification_pct", "tps_pct", "p2p_pct", "training_pct", "no_growth"):
            assert k in data["coverage"], f"coverage missing {k}"
        assert "clinical" in data["confidence"] and "business" in data["confidence"]
        for level in ("High", "Medium", "Low", "Unknown"):
            assert level in data["confidence"]["clinical"]
        assert "low_clinical_doctors" in data["confidence"]
        assert "low_business_doctors" in data["confidence"]
        for k in ("Confident", "Neutral", "Concerned", "Unknown"):
            assert k in data["affordability"]

    def test_tm_forbidden_manager_invisalign(self, tm_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/manager/invisalign", headers=H(tm_token), timeout=20)
        assert r.status_code == 403


# ---------- Manager Cross-Sell ----------
class TestManagerCrossSell:
    def test_cross_sell_shape(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/manager/cross-sell", headers=H(manager_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("invisalign_strong_no_itero", "itero_present_low_invisalign", "high_opportunity_both"):
            assert k in data, f"missing {k}"
            assert isinstance(data[k], list)
        all_items = data["invisalign_strong_no_itero"] + data["itero_present_low_invisalign"] + data["high_opportunity_both"]
        if all_items:
            it = all_items[0]
            for k in ("id", "doctor_name", "segment", "reason", "suggested_action", "score"):
                assert k in it, f"item missing {k}"

    def test_tm_forbidden_cross_sell(self, tm_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/manager/cross-sell", headers=H(tm_token), timeout=20)
        assert r.status_code == 403


# ---------- TM iTero ----------
class TestTmItero:
    def test_tm_itero_shape(self, tm_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/tm/itero", headers=H(tm_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("demo_funnel", "scanner_interest", "follow_ups", "high_interest_doctors"):
            assert k in data, f"missing {k}"
        assert isinstance(data["follow_ups"], list)

    def test_manager_forbidden_tm_itero(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/tm/itero", headers=H(manager_token), timeout=20)
        assert r.status_code == 403

    def test_admin_forbidden_tm_itero(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/tm/itero", headers=H(admin_token), timeout=20)
        assert r.status_code == 403


# ---------- TM Invisalign ----------
class TestTmInvisalign:
    def test_tm_invisalign_shape(self, tm_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/tm/invisalign", headers=H(tm_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("totals", "growth_program_explained_count", "certification_interest_doctors",
                  "needs_tps_p2p_training", "confidence_barriers"):
            assert k in data, f"missing {k}"

    def test_manager_forbidden_tm_invisalign(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/dashboard/tm/invisalign", headers=H(manager_token), timeout=20)
        assert r.status_code == 403


# ---------- Visits persist track_type & action blocks ----------
class TestVisitsTrackPersistence:
    def _doctor_for_tm(self, tm_token):
        r = requests.get(f"{BASE_URL}/api/doctors", headers=H(tm_token), timeout=20)
        assert r.status_code == 200
        doctors = r.json()
        assert doctors, "TM has no doctors"
        return doctors[0]["id"]

    def test_create_visit_persists_track_and_actions(self, tm_token):
        doctor_id = self._doctor_for_tm(tm_token)
        payload = {
            "doctor_id": doctor_id,
            "visit_type": "In-person visit",
            "track_type": "BOTH",
            "free_text_note": "TEST_iter4 persistence",
            "confirmed_topics": [], "confirmed_barriers": [],
            "sentiment": "Positive", "opportunity_state": "Advancing",
            "next_step": "follow up",
            "itero_actions": {
                "demo_discussed": True, "demo_booked": True, "demo_completed": False,
                "demo_booked_date": "2026-01-15", "demo_completed_date": None,
                "scanner_interest_level": "High", "scanner_concerns": ["price"],
            },
            "invisalign_actions": {
                "growth_program_explained": True, "certification_interest": True,
                "tps_discussed": True, "p2p_suggested": True, "staff_training_needed": True,
                "clinical_confidence": "Low", "business_confidence": "Medium",
                "patient_affordability_perception": "Concerned",
            },
            "commercial_actions": {
                "boost_discussed": True, "trade_in_discussed": False, "trade_in_interest": False,
                "proposal_discussed": True, "proposal_sent": False, "proposal_sent_date": None,
                "proposal_follow_up_done": False,
            },
            "promises": [],
        }
        r = requests.post(f"{BASE_URL}/api/visits", json=payload, headers=H(tm_token), timeout=20)
        assert r.status_code == 200, r.text
        v = r.json()["visit"]
        assert v["track_type"] == "BOTH"
        assert v["itero_actions"]["scanner_interest_level"] == "High"
        assert v["invisalign_actions"]["clinical_confidence"] == "Low"
        assert v["commercial_actions"]["boost_discussed"] is True

        # Verify via GET
        r2 = requests.get(f"{BASE_URL}/api/visits?doctor_id={doctor_id}", headers=H(tm_token), timeout=20)
        assert r2.status_code == 200
        found = next((x for x in r2.json() if x["id"] == v["id"]), None)
        assert found is not None
        assert found["track_type"] == "BOTH"
        assert found["invisalign_actions"]["p2p_suggested"] is True

    def test_invisalign_only_visit_does_not_affect_itero_funnel(self, tm_token, manager_token):
        # Snapshot
        before = requests.get(f"{BASE_URL}/api/dashboard/manager/itero", headers=H(manager_token), timeout=20).json()["demo_funnel"]
        doctor_id = self._doctor_for_tm(tm_token)
        payload = {
            "doctor_id": doctor_id,
            "visit_type": "Phone call",
            "track_type": "INVISALIGN",
            "free_text_note": "TEST_iter4 invisalign-only",
            "confirmed_topics": [], "confirmed_barriers": [],
            "sentiment": "Neutral", "opportunity_state": "Unknown",
            "next_step": "n/a",
            "itero_actions": {
                "demo_discussed": False, "demo_booked": False, "demo_completed": False,
                "demo_booked_date": None, "demo_completed_date": None,
                "scanner_interest_level": "None", "scanner_concerns": [],
            },
            "invisalign_actions": {
                "growth_program_explained": True, "certification_interest": False,
                "tps_discussed": False, "p2p_suggested": False, "staff_training_needed": False,
                "clinical_confidence": "Medium", "business_confidence": "Medium",
                "patient_affordability_perception": "Neutral",
            },
            "commercial_actions": {},
            "promises": [],
        }
        r = requests.post(f"{BASE_URL}/api/visits", json=payload, headers=H(tm_token), timeout=20)
        assert r.status_code == 200
        after = requests.get(f"{BASE_URL}/api/dashboard/manager/itero", headers=H(manager_token), timeout=20).json()["demo_funnel"]
        # Counts should not increase from an INVISALIGN-only visit with all itero false
        assert after["discussed"] == before["discussed"], f"funnel changed: {before} -> {after}"
        assert after["booked"] == before["booked"]
        assert after["completed"] == before["completed"]


# ---------- Doctors enriched with itero_state / invisalign_state ----------
class TestDoctorEnrichment:
    def test_list_doctors_enriched_states(self, tm_token):
        r = requests.get(f"{BASE_URL}/api/doctors", headers=H(tm_token), timeout=20)
        assert r.status_code == 200
        doctors = r.json()
        assert doctors
        d = doctors[0]
        assert "itero_state" in d, "itero_state missing"
        assert "invisalign_state" in d, "invisalign_state missing"
        for k in ("demo_discussed", "demo_booked", "demo_completed", "demo_pending",
                  "demo_booked_date", "demo_completed_date", "scanner_interest_level",
                  "scanner_concerns", "has_itero_activity"):
            assert k in d["itero_state"], f"itero_state missing {k}"
        for k in ("growth_program_explained", "certification_interest", "tps_discussed",
                  "p2p_suggested", "staff_training_needed", "clinical_confidence",
                  "business_confidence", "patient_affordability_perception", "has_invisalign_activity"):
            assert k in d["invisalign_state"], f"invisalign_state missing {k}"

    def test_get_doctor_detail_enriched(self, tm_token):
        doctors = requests.get(f"{BASE_URL}/api/doctors", headers=H(tm_token), timeout=20).json()
        did = doctors[0]["id"]
        r = requests.get(f"{BASE_URL}/api/doctors/{did}", headers=H(tm_token), timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "itero_state" in d and "invisalign_state" in d


# ---------- AI analyze ----------
class TestAiAnalyze:
    def test_analyze_dual_track(self, tm_token):
        note = "Demoed iTero today, doctor wants P2P training and clinical confidence is low"
        r = requests.post(f"{BASE_URL}/api/visits/analyze", json={"note": note}, headers=H(tm_token), timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        tts = data.get("track_types") or []
        assert "ITERO" in tts and "INVISALIGN" in tts, f"track_types={tts}"
        ia = data.get("itero_actions") or {}
        inv = data.get("invisalign_actions") or {}
        assert ia.get("demo_discussed") is True, f"itero_actions={ia}"
        assert inv.get("p2p_suggested") is True, f"invisalign_actions={inv}"
        assert inv.get("clinical_confidence") == "Low", f"clinical_confidence={inv.get('clinical_confidence')}"
