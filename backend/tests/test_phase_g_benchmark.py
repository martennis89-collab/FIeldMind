"""Phase G — Benchmark Cohort infrastructure + privacy guardrails — 15 tests.

Verifies:
  • Opt-out / inactive companies are excluded from cohorts.
  • Cohort `benchmark_available` toggles correctly at the minimum-count threshold.
  • Aggregation never returns PII (no company / TM / doctor names, no notes).
  • Non-Owner roles cannot access cohort management.
  • `/api/benchmark/status` returns ONLY safe status, never values.
  • No public benchmark comparison endpoint exists in Phase G.
"""
import os
import uuid
import requests

from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"
OWNER_EMAIL = "martennis89@gmail.com"
OWNER_PASS = "1234"


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _mongo():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _make_company(owner_token: str, opt_in: bool = True, active: bool = True, **extra) -> dict:
    slug = f"phaseG_{uuid.uuid4().hex[:8]}"
    body = {
        "company_name": f"PhaseG Test {slug}",
        "slug": slug,
        "country": "Bulgaria",
        "team_size_category": "1-5",
        "sales_motion": "dental/orthodontic field team",
        "account_type": "doctors/clinics",
        "industry": "dental/orthodontic field team",
        **extra,
    }
    r = requests.post(f"{API}/companies", headers=H(owner_token), json=body, timeout=10)
    assert r.status_code == 200, r.text
    c = r.json()
    # Force opt_in + active_status via direct PUT (POST auto-sets opt_in=False).
    if opt_in or not active:
        requests.put(f"{API}/companies/{c['id']}", headers=H(owner_token), json={
            "benchmark_opt_in": opt_in,
            "active_status": "Active" if active else "Inactive",
        }, timeout=10)
        c = requests.get(f"{API}/companies/{c['id']}", headers=H(owner_token), timeout=10).json()
    return c


def _cleanup_companies(owner_token: str, *cids):
    for cid in cids:
        try:
            requests.post(f"{API}/companies/{cid}/deactivate",
                          headers=H(owner_token), timeout=5)
        except Exception:
            pass


def _make_cohort(owner_token: str, **fields) -> dict:
    body = {
        "cohort_name": f"PhaseG cohort {uuid.uuid4().hex[:6]}",
        "country": "Bulgaria",
        "team_size_category": "1-5",
        "sales_motion": "dental/orthodontic field team",
        "minimum_company_count": 3,  # easy threshold for tests
        **fields,
    }
    r = requests.post(f"{API}/benchmark/cohorts", headers=H(owner_token), json=body, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()


# ============================================================
# 1, 2, 3 — eligibility
# ============================================================
class TestCompanyEligibility:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.cohort = _make_cohort(self.owner)

    def teardown_method(self):
        _mongo().benchmark_cohorts.delete_one({"id": self.cohort["id"]})

    def test_1_opt_out_company_excluded(self):
        c = _make_company(self.owner, opt_in=False)
        try:
            r = requests.post(f"{API}/benchmark/cohorts/{self.cohort['id']}/refresh",
                              headers=H(self.owner), timeout=10).json()
            # Excluded → count does not include this opt-out company.
            # The seeded default company also has opt_in=False, so count should equal 0 (or
            # whatever opted-in companies already exist).
            db = _mongo()
            counted = db.companies.count_documents({
                "benchmark_opt_in": True, "active_status": "Active",
                "country": "Bulgaria", "team_size_category": "1-5",
                "sales_motion": "dental/orthodontic field team",
            })
            assert r["current_company_count"] == counted, \
                f"opt-out company leaked into cohort count (cohort={r['current_company_count']}, opted-in={counted})"
        finally:
            _cleanup_companies(self.owner, c["id"])

    def test_2_opt_in_company_counted(self):
        c = _make_company(self.owner, opt_in=True, active=True)
        try:
            before = requests.post(f"{API}/benchmark/cohorts/{self.cohort['id']}/refresh",
                                   headers=H(self.owner), timeout=10).json()
            # Already counted by setup_method refresh? Add another and ensure delta = 1.
            c2 = _make_company(self.owner, opt_in=True, active=True)
            try:
                after = requests.post(f"{API}/benchmark/cohorts/{self.cohort['id']}/refresh",
                                      headers=H(self.owner), timeout=10).json()
                assert after["current_company_count"] == before["current_company_count"] + 1
            finally:
                _cleanup_companies(self.owner, c2["id"])
        finally:
            _cleanup_companies(self.owner, c["id"])

    def test_3_inactive_company_excluded(self):
        # Build it active first, count, then deactivate, count again.
        c = _make_company(self.owner, opt_in=True, active=True)
        try:
            r1 = requests.post(f"{API}/benchmark/cohorts/{self.cohort['id']}/refresh",
                               headers=H(self.owner), timeout=10).json()
            # Deactivate
            requests.post(f"{API}/companies/{c['id']}/deactivate",
                          headers=H(self.owner), timeout=5)
            r2 = requests.post(f"{API}/benchmark/cohorts/{self.cohort['id']}/refresh",
                               headers=H(self.owner), timeout=10).json()
            assert r2["current_company_count"] == r1["current_company_count"] - 1
        finally:
            # already deactivated
            pass


# ============================================================
# 4, 5 — minimum threshold + availability
# ============================================================
class TestThresholdAndAvailability:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        # Threshold = 100 — guaranteed NOT met by the default seeded data.
        self.cohort = _make_cohort(self.owner, minimum_company_count=100)

    def teardown_method(self):
        _mongo().benchmark_cohorts.delete_one({"id": self.cohort["id"]})

    def test_4_below_threshold_marks_unavailable(self):
        r = requests.post(f"{API}/benchmark/cohorts/{self.cohort['id']}/refresh",
                          headers=H(self.owner), timeout=10).json()
        assert r["benchmark_available"] is False, r

    def test_5_at_or_above_threshold_marks_available(self):
        # Lower the threshold to 1 — guaranteed met (every seed has ≥ 1 opted-in company
        # once we make one in setup).
        c = _make_company(self.owner, opt_in=True, active=True)
        try:
            requests.put(f"{API}/benchmark/cohorts/{self.cohort['id']}", headers=H(self.owner),
                         json={"minimum_company_count": 1}, timeout=10)
            r = requests.post(f"{API}/benchmark/cohorts/{self.cohort['id']}/refresh",
                              headers=H(self.owner), timeout=10).json()
            assert r["benchmark_available"] is True
            assert r["current_company_count"] >= 1
        finally:
            _cleanup_companies(self.owner, c["id"])


# ============================================================
# 6, 7, 14 — privacy guardrails
# ============================================================
class TestPrivacyGuardrails:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.admin_tok = _login("admin@field.io", "admin123")
        self.tm_tok = _login("tm1@field.io", "tm123")

    def test_6_raw_notes_not_used(self):
        """The aggregation engine and the status endpoint must NEVER expose raw notes.
        We check the public surface — every endpoint a non-Owner can call."""
        body = requests.get(f"{API}/benchmark/status", headers=H(self.tm_tok), timeout=10).json()
        forbidden_keys = (
            "free_text_note", "note", "raw_note", "comment",
            "doctor_name", "doctor_id", "tm_name", "manager_name",
            "company_name", "price", "discount", "revenue", "contract_value", "deal_value",
        )
        body_str = str(body).lower()
        for k in forbidden_keys:
            assert k not in body_str, f"forbidden field `{k}` leaked into /benchmark/status"

    def test_7_company_names_not_in_status_or_cohort_status(self):
        # /benchmark/status (TM)
        st = requests.get(f"{API}/benchmark/status", headers=H(self.tm_tok), timeout=10).json()
        assert "company_name" not in str(st).lower()
        # /benchmark/cohorts/{id}/status (Owner)
        co = requests.post(f"{API}/benchmark/cohorts", headers=H(self.owner), json={
            "cohort_name": "PhaseG privacy cohort",
            "team_size_category": "1-5",
            "minimum_company_count": 1,
        }, timeout=10).json()
        try:
            cs = requests.get(f"{API}/benchmark/cohorts/{co['id']}/status",
                              headers=H(self.owner), timeout=10).json()
            assert "company_name" not in cs, "Owner status response leaked company_name"
            # The response IS allowed to contain cohort_name, but NOT individual company names.
        finally:
            _mongo().benchmark_cohorts.delete_one({"id": co["id"]})

    def test_14_status_returns_safe_keys_only(self):
        st = requests.get(f"{API}/benchmark/status", headers=H(self.tm_tok), timeout=10).json()
        allowed_keys = {
            "company_benchmark_opt_in",
            "eligible_for_benchmarking",
            "matched_cohort_count",
            "benchmark_available",
            "reason_if_unavailable",
        }
        extra = set(st.keys()) - allowed_keys
        assert not extra, f"/benchmark/status leaked extra keys: {extra}"


# ============================================================
# 8, 9, 10, 11 — RBAC
# ============================================================
class TestBenchmarkRBAC:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.admin_tok = _login("admin@field.io", "admin123")
        self.mgr_tok = _login("manager@field.io", "manager123")
        self.tm_tok = _login("tm1@field.io", "tm123")

    def test_8_tm_cannot_access_cohort_endpoints(self):
        r = requests.get(f"{API}/benchmark/cohorts", headers=H(self.tm_tok), timeout=10)
        assert r.status_code == 403
        r2 = requests.post(f"{API}/benchmark/cohorts", headers=H(self.tm_tok),
                          json={"cohort_name": "x", "minimum_company_count": 5}, timeout=10)
        assert r2.status_code == 403

    def test_9_manager_cannot_manage_cohorts(self):
        r = requests.get(f"{API}/benchmark/cohorts", headers=H(self.mgr_tok), timeout=10)
        assert r.status_code == 403
        r2 = requests.post(f"{API}/benchmark/cohorts", headers=H(self.mgr_tok),
                           json={"cohort_name": "x", "minimum_company_count": 5}, timeout=10)
        assert r2.status_code == 403

    def test_10_admin_cannot_see_other_company_benchmark_values(self):
        """Admin only sees /benchmark/status (their own company). They cannot list cohorts."""
        r = requests.get(f"{API}/benchmark/cohorts", headers=H(self.admin_tok), timeout=10)
        assert r.status_code == 403
        # /benchmark/status is allowed and returns ONLY their own company's opt-in state.
        st = requests.get(f"{API}/benchmark/status", headers=H(self.admin_tok), timeout=10).json()
        assert "company_benchmark_opt_in" in st
        # The default company is opt-in=False per Phase C spec.
        assert st["company_benchmark_opt_in"] is False

    def test_11_owner_can_manage_cohorts(self):
        c = requests.post(f"{API}/benchmark/cohorts", headers=H(self.owner), json={
            "cohort_name": f"phaseG owner mgmt {uuid.uuid4().hex[:6]}",
            "minimum_company_count": 5,
        }, timeout=10)
        assert c.status_code == 200, c.text
        cid = c.json()["id"]
        # Owner can refresh, edit, list
        assert requests.post(f"{API}/benchmark/cohorts/{cid}/refresh",
                             headers=H(self.owner), timeout=10).status_code == 200
        assert requests.put(f"{API}/benchmark/cohorts/{cid}", headers=H(self.owner),
                            json={"cohort_name": "renamed"}, timeout=10).status_code == 200
        lst = requests.get(f"{API}/benchmark/cohorts", headers=H(self.owner), timeout=10).json()
        assert any(x["id"] == cid for x in lst)
        _mongo().benchmark_cohorts.delete_one({"id": cid})


# ============================================================
# 12, 13 — metric / cohort gating
# ============================================================
class TestMetricGating:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)

    def test_12_non_benchmark_eligible_metric_blocked(self):
        """`weekly_report_submission_rate` is intentionally NOT benchmark_eligible.
        The aggregation helper must refuse to compute it."""
        # We test the helper directly (no public aggregation endpoint exists yet in Phase G).
        from metrics.benchmark import _safe_benchmark_metric
        assert _safe_benchmark_metric("weekly_report_submission_rate") is False
        assert _safe_benchmark_metric("promise_completion_rate") is True
        assert _safe_benchmark_metric("itero_demo_booked_to_completed_rate") is True
        # FEI / unknown slugs must also be blocked.
        assert _safe_benchmark_metric("field_execution_index") is False
        assert _safe_benchmark_metric("totally_invented_metric") is False

    def test_13_too_small_cohort_returns_unavailable(self):
        # Threshold 999 — guaranteed unreachable.
        c = requests.post(f"{API}/benchmark/cohorts", headers=H(self.owner), json={
            "cohort_name": f"phaseG tiny {uuid.uuid4().hex[:6]}",
            "minimum_company_count": 999,
        }, timeout=10).json()
        try:
            status = requests.get(f"{API}/benchmark/cohorts/{c['id']}/status",
                                  headers=H(self.owner), timeout=10).json()
            assert status["benchmark_available"] is False
            # Refreshing doesn't change that
            after = requests.post(f"{API}/benchmark/cohorts/{c['id']}/refresh",
                                  headers=H(self.owner), timeout=10).json()
            assert after["benchmark_available"] is False
        finally:
            _mongo().benchmark_cohorts.delete_one({"id": c["id"]})


# ============================================================
# 15 — no public benchmark comparison endpoint
# ============================================================
class TestNoExternalBenchmarkEndpoint:
    def test_15_no_external_benchmark_dashboard_or_comparison_endpoint(self):
        """Phase G is infrastructure-only. None of the obvious 'benchmark comparison'
        endpoints may respond 200 (must be 404 or 405)."""
        owner = _login(OWNER_EMAIL, OWNER_PASS)
        admin = _login("admin@field.io", "admin123")
        tm = _login("tm1@field.io", "tm123")
        for tok in (owner, admin, tm):
            for path in (
                "/benchmark",
                "/benchmark/compare",
                "/benchmark/values",
                "/benchmark/dashboard",
                "/benchmark/aggregate",
                "/benchmark/results",
                "/companies/compare",
                "/dashboard/benchmark",
            ):
                r = requests.get(f"{API}{path}", headers=H(tok), timeout=5)
                assert r.status_code in (403, 404, 405), \
                    f"{path} unexpectedly responded {r.status_code} for token={tok[:10]}…"
