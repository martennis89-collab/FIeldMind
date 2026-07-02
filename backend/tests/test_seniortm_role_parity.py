"""
Iteration 20 — SeniorTM ≥ union(TM, Manager) role-parity verification.

Confirms:
  - SeniorTM can hit every endpoint currently guarded by require_roles("TM", ...)
  - SeniorTM can hit every endpoint currently guarded by require_roles("Manager", ...)
  - Inline-whitelist patched endpoints (ai_extract, doctors itero-stage, track-signals,
    clinical-patterns) no longer 403 for SeniorTM.
  - GET /api/expenses returns union(own + team) rows for SeniorTM.
  - TM and Manager regressions still work.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://territory-intel-8.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "senior": ("snr.demo.1782126329@field.io", "senior123"),
    "tm":     ("tm1@field.io", "tm123"),
    "manager":("manager@field.io", "manager123"),
    "admin":  ("admin@field.io", "admin123"),
}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def tokens():
    return {k: _login(*v) for k, v in CREDS.items()}


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- TM-scope endpoints SeniorTM must reach ----------
class TestSeniorTMOnTMScope:
    def test_get_doctors(self, tokens):
        r = requests.get(f"{API}/doctors", headers=_h(tokens["senior"]), timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_post_visit(self, tokens):
        # need a doctor id
        drs = requests.get(f"{API}/doctors", headers=_h(tokens["senior"]), timeout=15).json()
        if not drs:
            pytest.skip("no doctors for senior")
        payload = {
            "doctor_id": drs[0]["id"],
            "visit_date": "2026-01-15",
            "notes": "TEST_seniortm_visit",
            "outcome": "Positive",
        }
        r = requests.post(f"{API}/visits", headers=_h(tokens["senior"]), json=payload, timeout=15)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"

    def test_post_expense(self, tokens):
        data = {
            "expense_date": "2026-01-15",
            "category": "Petrol",
            "amount": "12.50",
            "notes": "TEST_seniortm_expense",
        }
        r = requests.post(f"{API}/expenses",
                          headers={"Authorization": f"Bearer {tokens['senior']}"},
                          data=data, timeout=15)
        assert r.status_code != 403, f"SeniorTM 403 on POST /expenses"
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"

    def test_post_task(self, tokens):
        drs = requests.get(f"{API}/doctors", headers=_h(tokens["senior"]), timeout=15).json()
        if not drs:
            pytest.skip("no doctors for senior")
        payload = {
            "doctor_id": drs[0]["id"],
            "task_title": "TEST_seniortm_task",
            "due_date": "2026-01-20",
        }
        r = requests.post(f"{API}/tasks", headers=_h(tokens["senior"]), json=payload, timeout=15)
        assert r.status_code != 403, f"SeniorTM 403 on POST /tasks"
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"

    def test_post_event(self, tokens):
        payload = {
            "title": "TEST_seniortm_event",
            "scheduled_at": "2026-02-01T10:00:00Z",
            "duration_minutes": 60,
            "location": "Test",
        }
        r = requests.post(f"{API}/events", headers=_h(tokens["senior"]), json=payload, timeout=15)
        assert r.status_code != 403, f"SeniorTM 403 on POST /events"
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"

    def test_report_generate(self, tokens):
        # weekly report — payload varies; try minimal
        r = requests.post(f"{API}/reports/generate", headers=_h(tokens["senior"]), json={}, timeout=30)
        # must NOT be 403
        assert r.status_code != 403, f"SeniorTM 403 on /reports/generate: {r.text[:300]}"

    def test_reimbursement_report_generate(self, tokens):
        r = requests.post(f"{API}/reimbursement/reports/generate",
                          headers=_h(tokens["senior"]), json={}, timeout=30)
        assert r.status_code != 403, f"SeniorTM 403 on /reimbursement/reports/generate: {r.text[:300]}"


# ---------- Manager-scope endpoints SeniorTM must reach ----------
class TestSeniorTMOnManagerScope:
    def test_metrics(self, tokens):
        # Manager-scope endpoint: POST /api/metrics/snapshots/run
        r = requests.post(f"{API}/metrics/snapshots/run", headers=_h(tokens["senior"]), timeout=30)
        assert r.status_code != 403, f"SeniorTM 403 on /metrics/snapshots/run: {r.text[:300]}"

    def test_create_user_subordinate(self, tokens):
        # Manager scope — POST /api/users
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "name": f"TEST_senior_sub_{suffix}",
            "email": f"TEST_senior_sub_{suffix}@field.io",
            "password": "temp1234",
            "role": "TM",
        }
        r = requests.post(f"{API}/users", headers=_h(tokens["senior"]), json=payload, timeout=15)
        # Must not be 403 — may fail with 400 for schema reasons but not forbidden
        assert r.status_code != 403, f"SeniorTM 403 on POST /users: {r.text[:300]}"
        if r.status_code in (200, 201):
            uid = r.json().get("id")
            # try update
            if uid:
                r2 = requests.put(f"{API}/users/{uid}",
                                  headers=_h(tokens["senior"]),
                                  json={"name": f"TEST_senior_sub_{suffix}_upd"},
                                  timeout=15)
                assert r2.status_code != 403, f"SeniorTM 403 on PUT /users/id: {r2.text[:300]}"


# ---------- Inline-whitelist patched endpoints ----------
class TestInlineWhitelistPatched:
    def test_ai_extract(self, tokens):
        payload = {"text": "Dr. Smith at ABC Clinic, phone 555-1234"}
        r = requests.post(f"{API}/ai/extract", headers=_h(tokens["senior"]), json=payload, timeout=30)
        assert r.status_code != 403, f"SeniorTM 403 on /ai/extract: {r.text[:300]}"

    def test_doctor_itero_stage(self, tokens):
        drs = requests.get(f"{API}/doctors", headers=_h(tokens["senior"]), timeout=15).json()
        if not drs:
            pytest.skip("no doctors")
        did = drs[0]["id"]
        payload = {"itero_stage": "Trial", "notes": "TEST_seniortm_itero"}
        r = requests.post(f"{API}/doctors/{did}/itero-stage",
                          headers=_h(tokens["senior"]), json=payload, timeout=15)
        assert r.status_code != 403, f"SeniorTM 403 on /doctors/{{id}}/itero-stage: {r.text[:300]}"

    def test_track_signals(self, tokens):
        r = requests.get(f"{API}/track-signals", headers=_h(tokens["senior"]), timeout=15)
        assert r.status_code != 403, f"SeniorTM 403 on /track-signals: {r.text[:300]}"

    def test_clinical_patterns(self, tokens):
        r = requests.get(f"{API}/clinical-patterns", headers=_h(tokens["senior"]), timeout=15)
        assert r.status_code != 403, f"SeniorTM 403 on /clinical-patterns: {r.text[:300]}"


# ---------- Expense scope union ----------
class TestExpenseUnion:
    def test_senior_sees_own_and_team(self, tokens):
        # create expense as tm1 (subordinate) — multipart form
        data = {
            "expense_date": "2026-01-16",
            "category": "Food",
            "amount": "9.99",
            "notes": "TEST_tm1_expense_for_union",
        }
        r_tm = requests.post(f"{API}/expenses",
                             headers={"Authorization": f"Bearer {tokens['tm']}"},
                             data=data, timeout=15)
        assert r_tm.status_code in (200, 201), r_tm.text
        tm_body = r_tm.json()
        tm_exp = tm_body.get("expense", tm_body)
        tm_exp_id = tm_exp.get("id")
        assert tm_exp_id, f"no id in expense response: {tm_body}"

        # senior should see it
        r = requests.get(f"{API}/expenses", headers=_h(tokens["senior"]), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("expenses") or rows.get("items") or rows.get("data") or []
        ids = {x.get("id") for x in rows}
        assert tm_exp_id in ids, f"SeniorTM does NOT see subordinate TM's expense — union broken. rows={len(rows)}"

        # and senior's own
        own_data = {"expense_date": "2026-01-16", "category": "Petrol", "amount": "5.0",
                    "notes": "TEST_senior_own_for_union"}
        r_own = requests.post(f"{API}/expenses",
                              headers={"Authorization": f"Bearer {tokens['senior']}"},
                              data=own_data, timeout=15)
        own_id = None
        if r_own.status_code in (200, 201):
            b = r_own.json()
            own_id = (b.get("expense") or b).get("id")
        r2 = requests.get(f"{API}/expenses", headers=_h(tokens["senior"]), timeout=15).json()
        if isinstance(r2, dict):
            r2 = r2.get("expenses") or r2.get("items") or r2.get("data") or []
        ids2 = {x.get("id") for x in r2}
        if own_id:
            assert own_id in ids2, "SeniorTM does not see own expense"


# ---------- Regression: TM & Manager unchanged ----------
class TestRegression:
    def test_tm_still_works(self, tokens):
        r = requests.get(f"{API}/doctors", headers=_h(tokens["tm"]), timeout=15)
        assert r.status_code == 200

        exp_data = {"expense_date": "2026-01-16", "category": "Petrol", "amount": "3.0",
                    "notes": "TEST_tm_reg"}
        r2 = requests.post(f"{API}/expenses",
                           headers={"Authorization": f"Bearer {tokens['tm']}"},
                           data=exp_data, timeout=15)
        assert r2.status_code in (200, 201), r2.text

    def test_manager_still_works(self, tokens):
        r = requests.post(f"{API}/metrics/snapshots/run",
                          headers=_h(tokens["manager"]), timeout=30)
        assert r.status_code != 403 and r.status_code < 500, r.text

        r2 = requests.get(f"{API}/expenses", headers=_h(tokens["manager"]), timeout=15)
        assert r2.status_code == 200, r2.text
