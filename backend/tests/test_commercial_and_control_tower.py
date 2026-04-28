"""Iteration-3 backend tests: commercial actions + manager control-tower endpoints."""
import os
import requests
import pytest

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "admin": ("admin@field.io", "admin123"),
    "manager": ("manager@field.io", "manager123"),
    "tm1": ("tm1@field.io", "tm123"),
    "tm2": ("tm2@field.io", "tm123"),
}

COMMERCIAL_KEYS = [
    "demo_discussed", "demo_booked", "demo_booked_date", "demo_completed", "demo_completed_date",
    "boost_discussed", "trade_in_discussed", "trade_in_interest",
    "growth_program_explained", "proposal_discussed", "proposal_sent",
    "proposal_sent_date", "proposal_follow_up_done",
]


@pytest.fixture(scope="module")
def tokens():
    requests.post(f"{API}/seed/init", timeout=30)
    out = {}
    for k, (e, p) in CREDS.items():
        r = requests.post(f"{API}/auth/login", json={"email": e, "password": p}, timeout=15)
        assert r.status_code == 200, f"login {k} -> {r.status_code} {r.text}"
        out[k] = r.json()["token"]
    return out


def H(t):
    return {"Authorization": f"Bearer {t}"}


# ========= Manager Commercial Dashboard =========
class TestManagerCommercial:
    def test_shape(self, tokens):
        r = requests.get(f"{API}/dashboard/manager/commercial", headers=H(tokens["manager"]), timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["demo_funnel", "proposal_funnel", "pricing_coverage", "drop_offs", "barriers_by_stage"]:
            assert k in d, f"missing {k}"
        df = d["demo_funnel"]
        for k in ["discussed", "booked", "completed", "booking_rate", "completion_rate"]:
            assert k in df, f"demo_funnel missing {k}"
        pf = d["proposal_funnel"]
        for k in ["discussed", "sent", "followed_up", "follow_up_rate", "avg_days_since_proposal"]:
            assert k in pf, f"proposal_funnel missing {k}"
        pc = d["pricing_coverage"]
        for k in ["boost_pct", "trade_in_pct", "growth_pct", "no_boost", "no_trade_in", "no_growth"]:
            assert k in pc, f"pricing_coverage missing {k}"
        assert isinstance(d["drop_offs"], list)
        bs = d["barriers_by_stage"]
        for k in ["pre_demo", "post_demo", "post_proposal"]:
            assert k in bs, f"barriers_by_stage missing {k}"

    def test_admin_ok(self, tokens):
        r = requests.get(f"{API}/dashboard/manager/commercial", headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200

    def test_tm_forbidden(self, tokens):
        r = requests.get(f"{API}/dashboard/manager/commercial", headers=H(tokens["tm1"]), timeout=10)
        assert r.status_code == 403

    def test_seed_demo_funnel_values(self, tokens):
        """Per agent_to_agent_context_note: 4 discussed / 3 booked / 2 completed (seeded)."""
        r = requests.get(f"{API}/dashboard/manager/commercial", headers=H(tokens["manager"]), timeout=20)
        d = r.json()["demo_funnel"]
        assert d["discussed"] >= d["booked"] >= d["completed"]
        assert d["discussed"] >= 1


# ========= Manager Interventions =========
class TestManagerInterventions:
    def test_shape(self, tokens):
        r = requests.get(f"{API}/dashboard/manager/interventions", headers=H(tokens["manager"]), timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        for bucket in ["critical", "at_risk", "high_opportunity"]:
            assert bucket in d
            assert isinstance(d[bucket], list)
            for item in d[bucket]:
                for k in ["doctor_id", "doctor_name", "tm_id", "tm_name",
                          "segment", "issue", "suggested_action"]:
                    assert k in item, f"intervention missing {k} in {bucket}"

    def test_tm_forbidden(self, tokens):
        r = requests.get(f"{API}/dashboard/manager/interventions", headers=H(tokens["tm1"]), timeout=10)
        assert r.status_code == 403


# ========= Manager Performance (new fields) =========
class TestManagerPerformanceExtended:
    NEW_FIELDS = [
        "execution_quality_score", "execution_quality_label", "high_priority_visited_pct",
        "total_high_priority", "demos_booked", "demos_completed", "demos_pending",
        "demo_completion_rate", "proposals_sent", "proposals_unfollowed",
        "proposal_followup_rate", "coaching",
    ]

    def test_new_fields(self, tokens):
        r = requests.get(f"{API}/dashboard/manager/performance", headers=H(tokens["manager"]), timeout=20)
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert len(rows) >= 1
        for row in rows:
            for f in self.NEW_FIELDS:
                assert f in row, f"missing {f}"
            assert 0 <= row["execution_quality_score"] <= 100
            assert row["execution_quality_label"] in ("Low", "Medium", "High")
            c = row["coaching"]
            for k in ["strengths", "weaknesses", "suggestions"]:
                assert k in c and isinstance(c[k], list)

    def test_sorted_worst_first(self, tokens):
        r = requests.get(f"{API}/dashboard/manager/performance", headers=H(tokens["manager"]), timeout=20)
        rows = r.json()["rows"]
        scores = [row["execution_quality_score"] for row in rows]
        assert scores == sorted(scores), "should be sorted asc (worst first)"


# ========= Visits analyze + CRUD with commercial_actions =========
class TestVisitsCommercialActions:
    def test_analyze_returns_commercial(self, tokens):
        payload = {
            "note": (
                "Visited Dr Sharma. Discussed X-imaging growth program and Boost pricing. "
                "Scheduled demo for next Thursday. Mentioned trade-in; she is interested. "
                "Plan to send proposal after the demo."
            )
        }
        r = requests.post(f"{API}/visits/analyze", headers=H(tokens["tm1"]), json=payload, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        ca = d.get("commercial_actions")
        assert ca is not None, f"commercial_actions missing in analyze response: {d}"
        for k in COMMERCIAL_KEYS:
            assert k in ca, f"commercial_actions missing key {k}"

    def test_create_visit_persists_commercial(self, tokens):
        # Fetch a doctor owned by tm1
        rd = requests.get(f"{API}/doctors", headers=H(tokens["tm1"]), timeout=15)
        assert rd.status_code == 200
        docs = rd.json()
        if isinstance(docs, dict):
            docs = docs.get("doctors", [])
        assert docs, "no doctors"
        doc_id = docs[0]["id"]

        ca = {
            "demo_discussed": True,
            "demo_booked": True,
            "demo_booked_date": "2026-01-20",
            "demo_completed": False,
            "demo_completed_date": None,
            "boost_discussed": True,
            "trade_in_discussed": True,
            "trade_in_interest": True,
            "growth_program_explained": True,
            "proposal_discussed": True,
            "proposal_sent": False,
            "proposal_sent_date": None,
            "proposal_follow_up_done": False,
        }
        payload = {
            "doctor_id": doc_id,
            "free_text_note": "TEST_iter3 visit with commercial actions",
            "confirmed_topics": ["TEST_topic"],
            "confirmed_barriers": [],
            "sentiment": "Positive",
            "ai_extraction": {
                "topics_discussed": ["TEST_topic"],
                "barriers": [],
                "sentiment": "Positive",
                "summary": "TEST_iter3",
                "commercial_actions": ca,
            },
            "commercial_actions": ca,
        }
        r = requests.post(f"{API}/visits", headers=H(tokens["tm1"]), json=payload, timeout=20)
        assert r.status_code == 200, r.text
        resp = r.json()
        visit = resp.get("visit", resp)
        assert visit.get("commercial_actions")
        for k in COMMERCIAL_KEYS:
            assert k in visit["commercial_actions"], f"missing {k} in created visit"
        assert visit["commercial_actions"]["demo_booked"] is True

        # GET and verify persistence
        rg = requests.get(f"{API}/visits/{visit['id']}", headers=H(tokens["tm1"]), timeout=10)
        assert rg.status_code == 200
        vg_raw = rg.json()
        vg = vg_raw.get("visit", vg_raw)
        assert vg["commercial_actions"]["demo_booked"] is True
        assert vg["commercial_actions"]["boost_discussed"] is True
        # ai_extraction preservation
        assert vg.get("ai_extraction", {}).get("commercial_actions", {}).get("growth_program_explained") is True


# ========= Doctors enriched with commercial_state =========
class TestDoctorsEnriched:
    COMMERCIAL_STATE_KEYS = [
        "demo_discussed", "demo_booked", "demo_completed",
        "demo_booked_date", "demo_completed_date",
        "boost_discussed", "trade_in_discussed", "trade_in_interest",
        "growth_program_explained", "proposal_discussed", "proposal_sent",
        "proposal_sent_date", "proposal_follow_up_done", "days_since_proposal",
        "demo_pending", "proposal_unfollowed",
    ]

    def test_list_has_commercial_state(self, tokens):
        r = requests.get(f"{API}/doctors", headers=H(tokens["manager"]), timeout=20)
        assert r.status_code == 200
        raw = r.json()
        docs = raw if isinstance(raw, list) else raw.get("doctors", [])
        assert docs
        found = 0
        for d in docs:
            if "commercial_state" in d:
                found += 1
                for k in self.COMMERCIAL_STATE_KEYS:
                    assert k in d["commercial_state"], f"doctor list missing {k}"
                break
        assert found > 0, "no doctor had commercial_state on list"

    def test_detail_has_commercial_state(self, tokens):
        r = requests.get(f"{API}/doctors", headers=H(tokens["manager"]), timeout=15)
        raw = r.json()
        docs = raw if isinstance(raw, list) else raw.get("doctors", [])
        doc_id = docs[0]["id"]
        r2 = requests.get(f"{API}/doctors/{doc_id}", headers=H(tokens["manager"]), timeout=15)
        assert r2.status_code == 200
        d = r2.json()
        assert "commercial_state" in d
        for k in self.COMMERCIAL_STATE_KEYS:
            assert k in d["commercial_state"]


# ========= Report includes demo/proposal counts =========
class TestReportCommercialCounts:
    def test_generate_contains_counts(self, tokens):
        r = requests.post(f"{API}/reports/generate", headers=H(tokens["tm1"]), timeout=30)
        assert r.status_code == 200
        c = r.json()["content"]
        for k in ["demos_discussed", "demos_booked", "demos_completed",
                  "proposals_sent", "proposals_followed_up"]:
            assert k in c, f"report content missing {k}"
        assert isinstance(r.json()["auto_summary"], str) and len(r.json()["auto_summary"]) > 0
