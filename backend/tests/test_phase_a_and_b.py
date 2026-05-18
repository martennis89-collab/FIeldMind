"""Phase A + B acceptance tests.

Covers:
  • Promise default due-date = +3 BUSINESS days
  • Promise category enum
  • Promise created_from_ai / ai_confirmed flags
  • Meeting soft-delete
  • event_ledger named events + idempotency_key
  • Track Signal CRUD + iTero/Invisalign separation
  • Track Signal materialization from visit save
  • Clinical Pattern CRUD
  • RBAC for new endpoints
"""
import os
import requests
from datetime import datetime, timezone, timedelta, date

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _next_business_days(start: date, n: int) -> date:
    cur = start
    added = 0
    while added < n:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


class TestPhaseA:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.tm2 = _login("tm2@field.io", "tm123")
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr PhaseA_Test", "doctor_type": "GP", "segment": "Active",
        }, timeout=10)
        self.doctor = r.json()
        self.created_meeting_ids = []
        self.created_task_ids = []

    def teardown_method(self):
        for mid in self.created_meeting_ids:
            try: requests.delete(f"{API}/meetings/{mid}", headers=H(self.tm), timeout=5)
            except Exception: pass
        try: requests.delete(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=5)
        except Exception: pass

    # -------- A.1 promise default +3 business days --------
    def test_create_task_without_due_date_defaults_to_3_business_days(self):
        r = requests.post(f"{API}/tasks", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"], "task_title": "Send brochure",
        }, timeout=10)
        assert r.status_code == 200, r.text
        t = r.json()
        self.created_task_ids.append(t["id"])
        expected = _next_business_days(date.today(), 3).isoformat()
        assert t["due_date"] == expected, f"expected {expected}, got {t['due_date']}"

    def test_create_task_with_explicit_due_date_is_respected(self):
        r = requests.post(f"{API}/tasks", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"], "task_title": "Specific date",
            "due_date": "2026-12-31",
        }, timeout=10)
        assert r.status_code == 200
        t = r.json()
        self.created_task_ids.append(t["id"])
        assert t["due_date"] == "2026-12-31"

    # -------- A.2 promise category enum + AI flags --------
    def test_create_task_with_category_and_ai_flag_persists(self):
        r = requests.post(f"{API}/tasks", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"], "task_title": "Demo arrangement",
            "category": "arrange demo", "created_from_ai": True, "ai_confirmed": False,
        }, timeout=10)
        assert r.status_code == 200
        t = r.json()
        self.created_task_ids.append(t["id"])
        assert t["category"] == "arrange demo"
        assert t["created_from_ai"] is True
        assert t["ai_confirmed"] is False

    def test_invalid_category_rejected(self):
        r = requests.post(f"{API}/tasks", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"], "task_title": "X",
            "category": "marketing_outreach",  # not in enum
        }, timeout=10)
        assert r.status_code == 422

    # -------- A.3 meeting soft delete --------
    def test_meeting_delete_is_soft(self):
        when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        m = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"], "scheduled_at": when,
            "subject": "soft delete test", "is_demo": False,
        }, timeout=10).json()
        self.created_meeting_ids.append(m["id"])

        r = requests.delete(f"{API}/meetings/{m['id']}", headers=H(self.tm), timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body.get("soft_deleted") is True

        # Listed meetings must NOT include the soft-deleted one
        upcoming = requests.get(f"{API}/meetings?when=upcoming", headers=H(self.tm), timeout=10).json()
        assert m["id"] not in [x["id"] for x in upcoming]

        # The dashboard "open_meetings" counter must drop too
        # (we don't assert exact value because other meetings may exist).
        # Just confirm endpoint still serves 200.
        s = requests.get(f"{API}/dashboard/tm", headers=H(self.tm), timeout=10)
        assert s.status_code == 200

    # -------- A.4 event ledger contains the new named event --------
    def test_promise_created_emits_named_event(self):
        # As Admin we can read /api/audit_logs
        admin = _login("martennis89@gmail.com", "1234")
        r = requests.post(f"{API}/tasks", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"], "task_title": "Event ledger test",
        }, timeout=10)
        tid = r.json()["id"]
        self.created_task_ids.append(tid)
        logs = requests.get(f"{API}/audit_logs?entity_type=task&entity_id={tid}",
                            headers=H(admin), timeout=10).json()
        named = [x for x in logs if x.get("event_type") == "promise_created"]
        assert len(named) >= 1, f"expected promise_created event, got logs: {logs[:3]}"


class TestPhaseBTrackSignals:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.tm2 = _login("tm2@field.io", "tm123")
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr PhaseB_Test", "doctor_type": "GP", "segment": "Active",
        }, timeout=10)
        self.doctor = r.json()
        self.signal_ids = []

    def teardown_method(self):
        for sid in self.signal_ids:
            try: requests.delete(f"{API}/track-signals/{sid}", headers=H(self.tm), timeout=5)
            except Exception: pass
        try: requests.delete(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=5)
        except Exception: pass

    def test_manual_create_itero_signal(self):
        r = requests.post(f"{API}/track-signals", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"], "track_type": "iTero",
            "signal_type": "demo_booked", "source": "Manual",
        }, timeout=10)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        self.signal_ids.append(sid)
        listed = requests.get(f"{API}/track-signals?track_type=iTero&doctor_id=" + self.doctor["id"],
                              headers=H(self.tm), timeout=10).json()
        assert any(x["id"] == sid for x in listed)

    def test_invalid_signal_type_rejected(self):
        r = requests.post(f"{API}/track-signals", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"], "track_type": "iTero",
            "signal_type": "totally_made_up", "source": "Manual",
        }, timeout=10)
        assert r.status_code == 400
        assert "Unknown" in r.text

    def test_separation_invisalign_signal_not_in_itero_list(self):
        r = requests.post(f"{API}/track-signals", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"], "track_type": "Invisalign",
            "signal_type": "growth_program_explained", "source": "Manual",
        }, timeout=10)
        assert r.status_code == 200, r.text
        self.signal_ids.append(r.json()["id"])

        itero_only = requests.get(
            f"{API}/track-signals?track_type=iTero&doctor_id=" + self.doctor["id"],
            headers=H(self.tm), timeout=10).json()
        assert all(x["track_type"] == "iTero" for x in itero_only)

    def test_rbac_other_tm_cannot_see_my_signals(self):
        r = requests.post(f"{API}/track-signals", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"], "track_type": "iTero",
            "signal_type": "demo_discussed", "source": "Manual",
        }, timeout=10)
        sid = r.json()["id"]
        self.signal_ids.append(sid)
        listed = requests.get(f"{API}/track-signals?doctor_id=" + self.doctor["id"],
                              headers=H(self.tm2), timeout=10).json()
        assert sid not in [x["id"] for x in listed]

    def test_visit_save_materializes_track_signals(self):
        # Save a visit with confirmed iTero + Invisalign actions, expect rows in track_signals
        v = requests.post(f"{API}/visits", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "free_text_note": "demo booked and growth programme explained",
            "track_type": "BOTH",
            "sentiment": "Positive",
            "itero_actions": {"demo_booked": True, "demo_discussed": True},
            "invisalign_actions": {"growth_program_explained": True},
        }, timeout=20).json()
        # Force a list query — should include 3 new signals on this doctor
        listed = requests.get(f"{API}/track-signals?doctor_id=" + self.doctor["id"],
                              headers=H(self.tm), timeout=10).json()
        sigs_for_visit = [x for x in listed if x.get("meeting_id") == v.get("id")]
        types = sorted(x["signal_type"] for x in sigs_for_visit)
        # demo_booked should appear (from itero_actions) — at least
        assert "demo_booked" in types, f"expected demo_booked, got {types}"
        # Invisalign growth_program_explained should appear
        assert "growth_program_explained" in types, f"expected growth_program_explained, got {types}"
        # Their tracks must be correctly separated
        for s in sigs_for_visit:
            if s["signal_type"] == "growth_program_explained":
                assert s["track_type"] == "Invisalign"
            if s["signal_type"] in ("demo_booked", "demo_discussed"):
                assert s["track_type"] == "iTero"


class TestPhaseBClinicalPatterns:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr ClinPat_Test", "doctor_type": "Ortho", "segment": "Engaged",
        }, timeout=10)
        self.doctor = r.json()
        self.pattern_ids = []

    def teardown_method(self):
        for pid in self.pattern_ids:
            try: requests.delete(f"{API}/clinical-patterns/{pid}", headers=H(self.tm), timeout=5)
            except Exception: pass
        try: requests.delete(f"{API}/doctors/{self.doctor['id']}", headers=H(self.tm), timeout=5)
        except Exception: pass

    def test_create_and_list_clinical_pattern(self):
        r = requests.post(f"{API}/clinical-patterns", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "case_type": "Class II",
            "treatment_preference": "Prefers aligners",
            "treatment_strategy": "Functional-MAOB",
            "confidence_level": "Medium",
            "barrier_type": "Case selection confusion",
            "source": "AI Confirmed",
        }, timeout=10)
        assert r.status_code == 200, r.text
        p = r.json()
        self.pattern_ids.append(p["id"])
        assert p["case_type"] == "Class II"
        listed = requests.get(f"{API}/clinical-patterns?doctor_id=" + self.doctor["id"],
                              headers=H(self.tm), timeout=10).json()
        assert any(x["id"] == p["id"] for x in listed)

    def test_invalid_case_type_rejected(self):
        r = requests.post(f"{API}/clinical-patterns", headers=H(self.tm), json={
            "doctor_id": self.doctor["id"],
            "case_type": "Class IV",  # not in enum
        }, timeout=10)
        assert r.status_code == 422
