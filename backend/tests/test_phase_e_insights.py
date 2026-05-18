"""Phase E — Insight Cards + Advisory Layer — accuracy tests.

Each test class creates an isolated fresh TM (or pair of TMs) inside the default
company, seeds known data, generates insights, and asserts EXACT card content + RBAC.
"""
import os
import uuid
import requests
from datetime import datetime, timezone, timedelta

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


def _today():
    return datetime.now(timezone.utc).date()


def _today_iso():
    return _today().isoformat()


def _create_isolated_tm(owner_token: str, email_suffix: str, team_id: str | None = None):
    admin = _login("admin@field.io", "admin123")
    requests.post(f"{API}/seed/init", timeout=30)
    email = f"phaseE.tm.{email_suffix}.{uuid.uuid4().hex[:6]}@example.com"
    u = requests.post(f"{API}/users", headers=H(admin), json={
        "full_name": f"PhaseE TM {email_suffix}", "email": email, "password": "pw1234", "role": "TM",
    }, timeout=10)
    assert u.status_code == 200, u.text
    user = u.json()
    if team_id:
        _mongo().users.update_one({"id": user["id"]}, {"$set": {"team_id": team_id}})
        user["team_id"] = team_id
    return user, _login(email, "pw1234")


def _cleanup(owner_token: str, user_id: str):
    db = _mongo()
    for coll in ("tasks", "meetings", "visits", "track_signals", "clinical_patterns",
                 "reports", "events", "metric_snapshots", "insight_cards"):
        db[coll].delete_many({"$or": [{"tm_user_id": user_id}, {"scope_id": user_id}]})
    try:
        requests.delete(f"{API}/users/{user_id}", headers=H(owner_token), timeout=10)
    except Exception:
        pass


def _seed_promises(user, completed: int, open_due_today: int, overdue: int = 0):
    db = _mongo()
    cid = user["company_id"]
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    past = (_today() - timedelta(days=2)).isoformat()
    for _ in range(completed):
        rows.append({"status": "Completed", "due_date": _today_iso(), "completed_at": now})
    for _ in range(open_due_today):
        rows.append({"status": "Open", "due_date": _today_iso()})
    for _ in range(overdue):
        rows.append({"status": "Open", "due_date": past})
    for r in rows:
        db.tasks.insert_one({
            "id": uuid.uuid4().hex, "tm_user_id": user["id"], "company_id": cid,
            "doctor_id": "phaseE_doc", "task_title": "x",
            "created_at": now, "updated_at": now, "deleted_at": None, "category": "other",
            **r,
        })


def _seed_signal(user, doctor_id, signal_type):
    db = _mongo()
    db.track_signals.insert_one({
        "id": uuid.uuid4().hex, "doctor_id": doctor_id,
        "tm_user_id": user["id"], "company_id": user["company_id"],
        "track_type": "iTero", "signal_type": signal_type,
        "signal_date": _today_iso(), "source": "Manual", "deleted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


# ============================================================
# 1–2 — Generation gating (only with sufficient metric data)
# ============================================================
class TestInsightGeneration:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.user, self.token = _create_isolated_tm(self.owner, "gen")

    def teardown_method(self):
        _cleanup(self.owner, self.user["id"])

    def test_no_fake_insights_when_no_data(self):
        """Brand-new TM with zero data — /generate must NOT produce any cards."""
        r = requests.post(f"{API}/insights/generate", headers=H(self.token), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["cards_generated"] == 0
        # Endpoint /me must be empty
        cards = requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json()
        assert cards == []

    def test_low_promise_completion_creates_high_severity(self):
        """3 completed / 10 total → 30% → High severity card on promise_completion_rate."""
        _seed_promises(self.user, completed=3, open_due_today=7)
        gen = requests.post(f"{API}/insights/generate", headers=H(self.token), timeout=15).json()
        assert gen["cards_generated"] >= 1
        cards = requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json()
        pc = [c for c in cards if c["related_metric_slug"] == "promise_completion_rate"]
        assert pc, f"no promise_completion_rate card found: {[c['related_metric_slug'] for c in cards]}"
        c = pc[0]
        assert c["severity"] == "High"
        assert c["category"] == "Promise Discipline"
        assert "Promise completion is weak" in c["title"]
        assert abs(c["metric_value"] - 0.3) < 1e-6
        assert "close" in c["suggested_action"].lower() or "open commitments" in c["suggested_action"].lower()

    def test_high_overdue_promise_creates_high_severity(self):
        """4 overdue / 10 open → 40% → High severity overdue_promise_rate card."""
        _seed_promises(self.user, completed=0, open_due_today=6, overdue=4)
        requests.post(f"{API}/insights/generate", headers=H(self.token), timeout=15)
        cards = requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json()
        op = [c for c in cards if c["related_metric_slug"] == "overdue_promise_rate"]
        assert op, "missing overdue_promise_rate insight"
        c = op[0]
        assert c["severity"] == "High"
        assert c["category"] == "Promise Discipline"
        assert abs(c["metric_value"] - 0.4) < 1e-6

    def test_low_itero_discussed_to_booked_creates_card(self):
        """6 discussed / 1 booked → 1/6 ≈ 0.166 → High severity."""
        for i in range(6):
            _seed_signal(self.user, f"phaseE_doc_{i}", "demo_discussed")
        _seed_signal(self.user, "phaseE_doc_0", "demo_booked")
        requests.post(f"{API}/insights/generate", headers=H(self.token), timeout=15)
        cards = requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json()
        match = [c for c in cards if c["related_metric_slug"] == "itero_demo_discussed_to_booked_rate"]
        assert match, "missing iTero discussed→booked card"
        c = match[0]
        assert c["severity"] == "High"
        assert c["category"] == "iTero Execution"
        assert "not converting" in c["title"].lower()

    def test_low_itero_booked_to_completed_creates_card(self):
        """4 booked / 0 completed → 0/4 → High severity."""
        for i in range(4):
            _seed_signal(self.user, f"phaseE_doc_{i}", "demo_booked")
        requests.post(f"{API}/insights/generate", headers=H(self.token), timeout=15)
        cards = requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json()
        match = [c for c in cards if c["related_metric_slug"] == "itero_demo_booked_to_completed_rate"]
        assert match, "missing iTero booked→completed card"
        c = match[0]
        assert c["severity"] == "High"
        assert "not being completed" in c["title"].lower()
        assert c["metric_value"] == 0.0

    def test_low_weekly_report_submission_creates_card(self):
        """2 reports / 4 weeks expected → 50% → still triggers (Medium severity)."""
        db = _mongo()
        cid = self.user["company_id"]
        now_iso = datetime.now(timezone.utc).isoformat()
        for i in range(2):
            db.reports.insert_one({
                "id": uuid.uuid4().hex, "tm_user_id": self.user["id"], "company_id": cid,
                "status": "Submitted", "submitted_at": now_iso,
                "week_start": (_today() - timedelta(days=7 * (i + 1))).isoformat(),
            })
        requests.post(f"{API}/insights/generate", headers=H(self.token), timeout=15)
        cards = requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json()
        match = [c for c in cards if c["related_metric_slug"] == "weekly_report_submission_rate"]
        assert match, "missing weekly_report_submission_rate card"
        c = match[0]
        assert c["severity"] in ("Medium", "High")
        assert "report" in c["title"].lower()

    def test_low_fei_creates_field_execution_advisory(self):
        """Seed strongly negative data → FEI well below 50 → 'Field Execution Index is low' (High severity)."""
        # 3 completed + 7 overdue (Open with past due_date) → promise_completion 0.30, overdue_rate 1.0
        # Normalised: 30 (weight 0.25) + 0 (weight 0.15) → FEI = 7.5/0.40 = 18.75 → High severity.
        _seed_promises(self.user, completed=3, open_due_today=0, overdue=7)
        requests.post(f"{API}/insights/generate", headers=H(self.token), timeout=15)
        cards = requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json()
        fei = [c for c in cards if c["related_metric_slug"] == "field_execution_index"]
        assert fei, "missing field_execution_index advisory card"
        c = fei[0]
        assert c["category"] == "Field Execution"
        assert c["severity"] == "High", f"expected High, got {c['severity']} (metric_value={c['metric_value']})"
        assert "low" in c["title"].lower()

    def test_idempotent_generation(self):
        """Re-running /generate the same day must NOT create duplicate cards."""
        _seed_promises(self.user, completed=3, open_due_today=7)
        r1 = requests.post(f"{API}/insights/generate", headers=H(self.token), timeout=15).json()
        cards_after_1 = len(requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json())
        r2 = requests.post(f"{API}/insights/generate", headers=H(self.token), timeout=15).json()
        cards_after_2 = len(requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json())
        assert cards_after_1 == cards_after_2, "insights duplicated on second generate"


# ============================================================
# 3–6 — RBAC + company isolation
# ============================================================
class TestInsightRBAC:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.admin = _login("admin@field.io", "admin123")
        self.user_a, self.token_a = _create_isolated_tm(self.owner, "rbac_a")
        self.user_b, self.token_b = _create_isolated_tm(self.owner, "rbac_b")
        # Seed strongly negative data → guaranteed High severity card for A
        _seed_promises(self.user_a, completed=2, open_due_today=8)
        requests.post(f"{API}/insights/generate", headers=H(self.admin), timeout=20)

    def teardown_method(self):
        _cleanup(self.owner, self.user_a["id"])
        _cleanup(self.owner, self.user_b["id"])

    def test_tm_sees_only_own_insights(self):
        a = requests.get(f"{API}/insights/me", headers=H(self.token_a), timeout=10).json()
        b = requests.get(f"{API}/insights/me", headers=H(self.token_b), timeout=10).json()
        assert all(c["scope_id"] == self.user_a["id"] for c in a)
        # B has no data so should see nothing
        assert all(c["scope_id"] == self.user_b["id"] for c in b)
        assert any(c["scope_id"] == self.user_a["id"] for c in a)  # A actually got at least 1 card
        # B must NOT see A's cards
        assert not any(c["scope_id"] == self.user_a["id"] for c in b)

    def test_admin_sees_company_rollup_including_tm_cards(self):
        body = requests.get(f"{API}/insights/company", headers=H(self.admin), timeout=10).json()
        assert "by_severity" in body
        assert "by_category" in body
        assert isinstance(body["cards"], list)
        # Admin must see at least the cards we generated for user_a
        assert any(c["scope_id"] == self.user_a["id"] for c in body["cards"])
        assert body["total"] == len(body["cards"])

    def test_normal_tm_cannot_call_company_endpoint(self):
        r = requests.get(f"{API}/insights/company", headers=H(self.token_a), timeout=10)
        assert r.status_code == 403

    def test_cross_company_tm_cannot_read_default_company_insights(self):
        # Create a TM in a brand new company
        import uuid as _u
        slug = f"phaseE_{_u.uuid4().hex[:6]}"
        c = requests.post(f"{API}/companies", headers=H(self.owner), json={
            "company_name": "PhaseE Other Co", "slug": slug,
            "country": "X", "team_size_category": "1-5", "sales_motion": "other",
        }, timeout=10).json()
        admin = _login("admin@field.io", "admin123")
        u = requests.post(f"{API}/users", headers=H(admin), json={
            "full_name": "PhaseE other TM",
            "email": f"phaseE.cross.{slug}@example.com",
            "password": "pw1234", "role": "TM",
        }, timeout=10).json()
        _mongo().users.update_one({"id": u["id"]}, {"$set": {"company_id": c["id"]}})
        tok = _login(u["email"], "pw1234")
        try:
            cards = requests.get(f"{API}/insights/me", headers=H(tok), timeout=10).json()
            assert cards == []
        finally:
            requests.delete(f"{API}/users/{u['id']}", headers=H(self.owner), timeout=5)
            requests.post(f"{API}/companies/{c['id']}/deactivate", headers=H(self.owner), timeout=5)


# ============================================================
# 7–8 — Resolve + Dismiss
# ============================================================
class TestInsightActions:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.user, self.token = _create_isolated_tm(self.owner, "actions")
        _seed_promises(self.user, completed=2, open_due_today=8)
        requests.post(f"{API}/insights/generate", headers=H(self.token), timeout=15)

    def teardown_method(self):
        _cleanup(self.owner, self.user["id"])

    def test_resolve_marks_resolved(self):
        cards = requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json()
        assert cards
        cid = cards[0]["id"]
        r = requests.post(f"{API}/insights/{cid}/resolve", headers=H(self.token), timeout=10).json()
        assert r["status"] == "Resolved"
        assert r["resolved_at"]
        # Card should be excluded from default listing
        remaining = requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json()
        assert all(c["id"] != cid for c in remaining)
        # Include flag should bring it back
        with_resolved = requests.get(f"{API}/insights/me?include_resolved=true",
                                     headers=H(self.token), timeout=10).json()
        assert any(c["id"] == cid for c in with_resolved)

    def test_dismiss_marks_dismissed(self):
        cards = requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json()
        assert cards
        cid = cards[0]["id"]
        r = requests.post(f"{API}/insights/{cid}/dismiss", headers=H(self.token), timeout=10).json()
        assert r["status"] == "Dismissed"
        assert r["dismissed_at"]
        # History preserved
        db = _mongo()
        doc = db.insight_cards.find_one({"id": cid}, {"_id": 0})
        assert doc is not None
        assert doc["status"] == "Dismissed"

    def test_seen_marks_seen(self):
        cards = requests.get(f"{API}/insights/me", headers=H(self.token), timeout=10).json()
        assert cards
        cid = cards[0]["id"]
        r = requests.post(f"{API}/insights/{cid}/seen", headers=H(self.token), timeout=10).json()
        assert r["status"] == "Seen"
        assert r["seen_at"]
