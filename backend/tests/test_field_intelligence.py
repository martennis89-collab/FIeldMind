"""End-to-end backend tests for Field Intelligence Platform."""
import os
import requests
import pytest
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "admin": ("admin@field.io", "admin123"),
    "manager": ("manager@field.io", "manager123"),
    "tm1": ("tm1@field.io", "tm123"),
    "tm2": ("tm2@field.io", "tm123"),
}


@pytest.fixture(scope="module")
def tokens():
    # Ensure seed
    requests.post(f"{API}/seed/init", timeout=20)
    out = {}
    for k, (e, p) in CREDS.items():
        r = requests.post(f"{API}/auth/login", json={"email": e, "password": p}, timeout=15)
        assert r.status_code == 200, f"login {k} -> {r.status_code} {r.text}"
        out[k] = r.json()["token"]
    return out


def H(t): return {"Authorization": f"Bearer {t}"}


# -------- Seed --------
class TestSeed:
    def test_seed_idempotent(self):
        r = requests.post(f"{API}/seed/init", timeout=20)
        assert r.status_code == 200
        body = r.json()
        # already seeded once previously, should now skip
        assert body.get("skipped") is True or "created" in body


# -------- Auth --------
class TestAuth:
    def test_login_and_me(self, tokens):
        for k, tok in tokens.items():
            r = requests.get(f"{API}/auth/me", headers=H(tok), timeout=10)
            assert r.status_code == 200
            data = r.json()
            assert data["email"] == CREDS[k][0]
            assert "password_hash" not in data

    def test_login_invalid(self):
        r = requests.post(f"{API}/auth/login", json={"email": "admin@field.io", "password": "wrong"}, timeout=10)
        assert r.status_code == 401

    def test_no_token(self):
        r = requests.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 401


# -------- Doctors RBAC --------
class TestDoctorsRBAC:
    def test_admin_sees_all(self, tokens):
        r = requests.get(f"{API}/doctors", headers=H(tokens["admin"]), timeout=15)
        assert r.status_code == 200
        assert len(r.json()) == 10

    def test_manager_sees_team(self, tokens):
        r = requests.get(f"{API}/doctors", headers=H(tokens["manager"]), timeout=15)
        assert r.status_code == 200
        assert len(r.json()) == 10  # team has all

    def test_tm1_sees_own(self, tokens):
        r = requests.get(f"{API}/doctors", headers=H(tokens["tm1"]), timeout=15)
        assert r.status_code == 200
        docs = r.json()
        assert len(docs) == 5
        # enrichment fields
        d0 = docs[0]
        for f in ["last_visit_date", "days_since_last_visit", "visits_this_quarter",
                  "open_promises", "overdue_promises", "top_topics", "top_barriers",
                  "current_sentiment", "sentiment_trend", "cadence_status",
                  "visit_priority_score", "visit_priority_label", "suggested_next_action"]:
            assert f in d0, f"missing field {f}"

    def test_tm2_sees_own(self, tokens):
        r = requests.get(f"{API}/doctors", headers=H(tokens["tm2"]), timeout=15)
        assert r.status_code == 200
        assert len(r.json()) == 5

    def test_tm_cannot_access_other_tm_doctor(self, tokens):
        # find tm2 doctor
        r2 = requests.get(f"{API}/doctors", headers=H(tokens["tm2"]), timeout=15)
        tm2_doc_id = r2.json()[0]["id"]
        r = requests.get(f"{API}/doctors/{tm2_doc_id}", headers=H(tokens["tm1"]), timeout=10)
        assert r.status_code == 404

    def test_tm_cannot_update_other_tm_doctor(self, tokens):
        r2 = requests.get(f"{API}/doctors", headers=H(tokens["tm2"]), timeout=15)
        tm2_doc_id = r2.json()[0]["id"]
        r = requests.put(f"{API}/doctors/{tm2_doc_id}", headers=H(tokens["tm1"]),
                         json={"general_notes": "hacked"}, timeout=10)
        assert r.status_code == 404

    def test_filters(self, tokens):
        r = requests.get(f"{API}/doctors?segment=Expert", headers=H(tokens["admin"]), timeout=15)
        assert r.status_code == 200
        for d in r.json():
            assert d["segment"] == "Expert"
        r = requests.get(f"{API}/doctors?city=Sofia", headers=H(tokens["admin"]), timeout=15)
        assert r.status_code == 200
        for d in r.json():
            assert d["city"] == "Sofia"


# -------- AI extraction + visits --------
class TestVisitsAI:
    def test_analyze(self, tokens):
        note = "Doctor says Invisalign too expensive. Wants growth programs info. Promised to send certification info next week."
        r = requests.post(f"{API}/visits/analyze", headers=H(tokens["tm1"]),
                          json={"note": note}, timeout=60)
        assert r.status_code == 200
        data = r.json()
        for k in ["summary", "topics", "barriers", "sentiment", "opportunity_state",
                  "promises_detected", "suggested_next_action", "market_signals", "privacy_warnings"]:
            assert k in data
        # sanity: should detect at least 1 promise OR topic
        assert isinstance(data["topics"], list)
        assert isinstance(data["promises_detected"], list)

    def test_create_visit_creates_tasks_and_preserves_note(self, tokens):
        # tm1 first doctor
        rd = requests.get(f"{API}/doctors", headers=H(tokens["tm1"]), timeout=15)
        doc_id = rd.json()[0]["id"]
        original_note = "TEST_NOTE: doctor concerned about pricing; promised to send pricing FAQ."
        payload = {
            "doctor_id": doc_id,
            "visit_type": "Phone call",
            "free_text_note": original_note,
            "confirmed_topics": ["Invisalign pricing"],
            "confirmed_barriers": ["Patient affordability concern"],
            "sentiment": "Neutral",
            "opportunity_state": "Stuck",
            "next_step": "Send pricing FAQ",
            "promises": [{"task_title": "TEST_send pricing FAQ", "task_description": "FAQ doc", "priority": "High"}],
        }
        r = requests.post(f"{API}/visits", headers=H(tokens["tm1"]), json=payload, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["visit"]["free_text_note"] == original_note
        assert len(body["created_tasks"]) == 1
        assert body["created_tasks"][0]["task_title"] == "TEST_send pricing FAQ"
        # verify it appears in doctor visits
        r2 = requests.get(f"{API}/doctors/{doc_id}/visits", headers=H(tokens["tm1"]), timeout=10)
        assert r2.status_code == 200
        assert any(v["free_text_note"] == original_note for v in r2.json())


# -------- Tasks --------
class TestTasks:
    def test_buckets(self, tokens):
        for b in ["overdue", "today", "week", "completed", "open"]:
            r = requests.get(f"{API}/tasks?bucket={b}", headers=H(tokens["tm1"]), timeout=10)
            assert r.status_code == 200
            assert isinstance(r.json(), list)

    def test_complete_task(self, tokens):
        # create a quick task by creating a visit with a promise
        rd = requests.get(f"{API}/doctors", headers=H(tokens["tm1"]), timeout=15)
        doc_id = rd.json()[0]["id"]
        payload = {
            "doctor_id": doc_id,
            "free_text_note": "TEST_complete",
            "promises": [{"task_title": "TEST_complete_task", "priority": "Low"}],
        }
        r = requests.post(f"{API}/visits", headers=H(tokens["tm1"]), json=payload, timeout=20)
        assert r.status_code == 200
        task_id = r.json()["created_tasks"][0]["id"]
        r2 = requests.put(f"{API}/tasks/{task_id}", headers=H(tokens["tm1"]),
                          json={"status": "Completed"}, timeout=10)
        assert r2.status_code == 200
        assert r2.json()["status"] == "Completed"
        assert r2.json()["completed_at"] is not None


# -------- Dashboards --------
class TestDashboards:
    def test_tm_dashboard(self, tokens):
        r = requests.get(f"{API}/dashboard/tm", headers=H(tokens["tm1"]), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "stats" in d and "top_priorities" in d
        for k in ["open_promises", "overdue_promises", "due_today", "visits_this_week"]:
            assert k in d["stats"]
        # sorted desc by score
        scores = [p["visit_priority_score"] for p in d["top_priorities"]]
        assert scores == sorted(scores, reverse=True)

    def test_manager_dashboard(self, tokens):
        r = requests.get(f"{API}/dashboard/manager", headers=H(tokens["manager"]), timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ["by_tm", "top_topics", "top_barriers", "sentiment_distribution",
                  "market_pulse", "under_visited_high_segment"]:
            assert k in d

    def test_manager_dashboard_forbidden_for_tm(self, tokens):
        r = requests.get(f"{API}/dashboard/manager", headers=H(tokens["tm1"]), timeout=10)
        assert r.status_code == 403


# -------- Search --------
class TestSearch:
    def test_search(self, tokens):
        r = requests.get(f"{API}/search?q=price", headers=H(tokens["tm1"]), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "doctors" in d and "visits" in d and "tasks" in d


# -------- Audit & Users --------
class TestAdmin:
    def test_audit_admin_only(self, tokens):
        r = requests.get(f"{API}/audit", headers=H(tokens["admin"]), timeout=10)
        assert r.status_code == 200
        r2 = requests.get(f"{API}/audit", headers=H(tokens["tm1"]), timeout=10)
        assert r2.status_code == 403

    def test_create_user_admin_only(self, tokens):
        new_email = f"TEST_user_{int(time.time())}@field.io"
        body = {"full_name": "TEST User", "email": new_email, "password": "test1234", "role": "TM"}
        r = requests.post(f"{API}/users", headers=H(tokens["admin"]), json=body, timeout=10)
        assert r.status_code == 200
        assert r.json()["email"] == new_email.lower()
        # non-admin
        r2 = requests.post(f"{API}/users", headers=H(tokens["tm1"]), json=body, timeout=10)
        assert r2.status_code == 403
