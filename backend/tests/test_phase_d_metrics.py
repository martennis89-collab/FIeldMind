"""Phase D — Metric Registry + V1 metrics + Field Execution Index — accuracy tests.

Each test class:
  1. Creates a fresh TM in the default company.
  2. Seeds a known set of tasks / track_signals / meetings / reports for that TM.
  3. Calls the live metric endpoint and asserts EXACT numerator / denominator / value.

We never assert against the seeded shared demo TMs because their data fluctuates as
other tests run. Each test creates and tears down its own user.
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


def _iso(dt):
    return dt.isoformat()


def _create_isolated_tm(owner_token: str, email_suffix: str):
    """Create a fresh TM, assign them to the default company, log them in.
    Returns (user_dict, token).
    """
    admin = _login("admin@field.io", "admin123")
    requests.post(f"{API}/seed/init", timeout=30)
    email = f"phaseD.tm.{email_suffix}.{uuid.uuid4().hex[:6]}@example.com"
    u = requests.post(f"{API}/users", headers=H(admin), json={
        "full_name": f"PhaseD TM {email_suffix}",
        "email": email,
        "password": "pw1234",
        "role": "TM",
    }, timeout=10)
    assert u.status_code == 200, u.text
    user = u.json()
    # Login as the new TM
    tok = _login(email, "pw1234")
    return user, tok


def _cleanup_user(owner_token: str, user_id: str):
    """Delete the user + any data they created so DB stays clean."""
    db = _mongo()
    # Drop all rows belonging to this TM across the relevant collections.
    for coll in ("tasks", "meetings", "visits", "track_signals", "clinical_patterns",
                 "reports", "events", "metric_snapshots"):
        db[coll].delete_many({"tm_user_id": user_id})
    # Audit / scope_id for snapshots
    db.metric_snapshots.delete_many({"scope_id": user_id})
    # User itself
    try:
        requests.delete(f"{API}/users/{user_id}", headers=H(owner_token), timeout=10)
    except Exception:
        pass


# ============================================================
# REGISTRY
# ============================================================
class TestRegistry:
    def test_registry_lists_v1_metrics(self):
        owner = _login(OWNER_EMAIL, OWNER_PASS)
        r = requests.get(f"{API}/metrics/registry", headers=H(owner), timeout=10)
        assert r.status_code == 200, r.text
        slugs = {m["slug"] for m in r.json()}
        for must in (
            "promise_completion_rate",
            "overdue_promise_rate",
            "itero_demo_discussed_to_booked_rate",
            "itero_demo_booked_to_completed_rate",
            "meeting_to_visit_followthrough_rate",
            "weekly_report_submission_rate",
        ):
            assert must in slugs, f"registry missing metric {must}"


# ============================================================
# PROMISE METRICS
# ============================================================
class TestPromiseMetrics:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.user, self.token = _create_isolated_tm(self.owner, "promises")

    def teardown_method(self):
        _cleanup_user(self.owner, self.user["id"])

    def test_promise_completion_rate_exact(self):
        """Seed 10 promises with due_date in window: 6 Completed, 4 Open. Expect 6/10 = 0.6."""
        db = _mongo()
        cid = self.user["company_id"]
        now = datetime.now(timezone.utc).isoformat()
        for i in range(10):
            db.tasks.insert_one({
                "id": uuid.uuid4().hex,
                "tm_user_id": self.user["id"],
                "company_id": cid,
                "doctor_id": "phaseD_doc",
                "task_title": f"phaseD task {i}",
                "due_date": _today_iso(),
                "status": "Completed" if i < 6 else "Open",
                "completed_at": now if i < 6 else None,
                "created_at": now, "updated_at": now,
                "deleted_at": None, "category": "other",
            })
        r = requests.get(f"{API}/metrics/tm/{self.user['id']}/promise_completion_rate",
                         headers=H(self.token), timeout=10)
        # Fall back to listing all metrics and finding the promise one
        all_m = requests.get(f"{API}/metrics/me", headers=H(self.token), timeout=10).json()
        m = next(x for x in all_m if x["slug"] == "promise_completion_rate")
        assert m["denominator"] == 10
        assert m["numerator"] == 6
        assert m["value"] == 0.6
        assert m["sufficient_data"] is True

    def test_promise_completion_insufficient_data(self):
        """Seed only 2 promises — below min_data_points=5. Expect value=None and message."""
        db = _mongo()
        cid = self.user["company_id"]
        now = datetime.now(timezone.utc).isoformat()
        for i in range(2):
            db.tasks.insert_one({
                "id": uuid.uuid4().hex, "tm_user_id": self.user["id"], "company_id": cid,
                "doctor_id": "phaseD_doc", "task_title": "x", "due_date": _today_iso(),
                "status": "Open", "created_at": now, "updated_at": now,
                "deleted_at": None, "category": "other",
            })
        all_m = requests.get(f"{API}/metrics/me", headers=H(self.token), timeout=10).json()
        m = next(x for x in all_m if x["slug"] == "promise_completion_rate")
        assert m["sufficient_data"] is False
        assert m["value"] is None, "value must be None when insufficient (no fake scores)"
        assert m["message"] and "Not enough data yet" in m["message"]

    def test_overdue_promise_rate_exact(self):
        """Seed 8 open promises: 3 overdue, 5 future. Expect 3/8 = 0.375."""
        db = _mongo()
        cid = self.user["company_id"]
        now = datetime.now(timezone.utc).isoformat()
        past = (_today() - timedelta(days=2)).isoformat()
        future = (_today() + timedelta(days=10)).isoformat()
        for i in range(8):
            db.tasks.insert_one({
                "id": uuid.uuid4().hex, "tm_user_id": self.user["id"], "company_id": cid,
                "doctor_id": "phaseD_doc", "task_title": "x",
                "due_date": past if i < 3 else future,
                "status": "Open", "created_at": now, "updated_at": now,
                "deleted_at": None, "category": "other",
            })
        all_m = requests.get(f"{API}/metrics/me", headers=H(self.token), timeout=10).json()
        m = next(x for x in all_m if x["slug"] == "overdue_promise_rate")
        assert m["denominator"] == 8
        assert m["numerator"] == 3
        assert abs(m["value"] - 0.375) < 1e-6


# ============================================================
# iTero PIPELINE METRICS
# ============================================================
class TestIteroPipelineMetrics:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.user, self.token = _create_isolated_tm(self.owner, "itero")

    def teardown_method(self):
        _cleanup_user(self.owner, self.user["id"])

    def _seed_signal(self, doctor_id, signal_type):
        db = _mongo()
        cid = self.user["company_id"]
        db.track_signals.insert_one({
            "id": uuid.uuid4().hex,
            "doctor_id": doctor_id,
            "tm_user_id": self.user["id"],
            "company_id": cid,
            "track_type": "iTero",
            "signal_type": signal_type,
            "signal_date": _today_iso(),
            "source": "Manual",
            "deleted_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    def test_discussed_to_booked_rate(self):
        """6 doctors discussed; 3 booked. Expect 3/6 = 0.5."""
        for i in range(6):
            self._seed_signal(f"phaseD_doc_{i}", "demo_discussed")
        for i in range(3):
            self._seed_signal(f"phaseD_doc_{i}", "demo_booked")
        all_m = requests.get(f"{API}/metrics/me", headers=H(self.token), timeout=10).json()
        m = next(x for x in all_m if x["slug"] == "itero_demo_discussed_to_booked_rate")
        # Denominator = distinct doctors with discussed OR booked = 6
        # Numerator = distinct doctors with booked = 3
        assert m["denominator"] == 6, m
        assert m["numerator"] == 3
        assert m["value"] == 0.5

    def test_booked_to_completed_rate(self):
        """4 doctors booked; 1 of those also completed → 1/4 = 0.25."""
        for i in range(4):
            self._seed_signal(f"phaseD_doc_{i}", "demo_booked")
        self._seed_signal("phaseD_doc_0", "demo_completed")
        all_m = requests.get(f"{API}/metrics/me", headers=H(self.token), timeout=10).json()
        m = next(x for x in all_m if x["slug"] == "itero_demo_booked_to_completed_rate")
        assert m["denominator"] == 4
        assert m["numerator"] == 1
        assert m["value"] == 0.25


# ============================================================
# MEETING + REPORT METRICS
# ============================================================
class TestMeetingAndReportMetrics:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.user, self.token = _create_isolated_tm(self.owner, "mtg")

    def teardown_method(self):
        _cleanup_user(self.owner, self.user["id"])

    def test_meeting_to_visit_followthrough_rate(self):
        """5 completed meetings; 3 linked to a visit → 3/5 = 0.6."""
        db = _mongo()
        cid = self.user["company_id"]
        now = datetime.now(timezone.utc).isoformat()
        for i in range(5):
            db.meetings.insert_one({
                "id": uuid.uuid4().hex,
                "tm_user_id": self.user["id"],
                "company_id": cid,
                "doctor_id": "phaseD_doc",
                "scheduled_at": now,
                "status": "Completed",
                "visit_id": (uuid.uuid4().hex if i < 3 else None),
                "updated_at": now,
                "deleted_at": None,
            })
        all_m = requests.get(f"{API}/metrics/me", headers=H(self.token), timeout=10).json()
        m = next(x for x in all_m if x["slug"] == "meeting_to_visit_followthrough_rate")
        assert m["denominator"] == 5
        assert m["numerator"] == 3
        assert m["value"] == 0.6

    def test_weekly_report_submission_rate(self):
        """4 weeks expected; 3 submitted → 3/4 = 0.75."""
        db = _mongo()
        cid = self.user["company_id"]
        now_iso = datetime.now(timezone.utc).isoformat()
        for i in range(3):
            db.reports.insert_one({
                "id": uuid.uuid4().hex,
                "tm_user_id": self.user["id"],
                "company_id": cid,
                "status": "Submitted",
                "submitted_at": now_iso,
                "week_start": (_today() - timedelta(days=7 * (i + 1))).isoformat(),
            })
        all_m = requests.get(f"{API}/metrics/me", headers=H(self.token), timeout=10).json()
        m = next(x for x in all_m if x["slug"] == "weekly_report_submission_rate")
        assert m["denominator"] == 4
        assert m["numerator"] == 3
        assert m["value"] == 0.75


# ============================================================
# FIELD EXECUTION INDEX
# ============================================================
class TestFieldExecutionIndex:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.user, self.token = _create_isolated_tm(self.owner, "fei")

    def teardown_method(self):
        _cleanup_user(self.owner, self.user["id"])

    def test_fei_returns_not_enough_when_empty(self):
        """Brand-new TM with zero data — FEI must be None, never a fake score."""
        fei = requests.get(f"{API}/metrics/me/fei", headers=H(self.token), timeout=10).json()
        assert fei["fei"] is None
        assert fei["sufficient_data"] is False
        assert fei["message"]
        assert "Not enough data yet" in fei["message"]

    def test_fei_combines_components_weighted(self):
        """Seed only promise_completion_rate (the highest-weight component, 0.25):
        6/10 → 60% raw → 60.0 component score → weighted-avg with itself = 60.0.
        FEI must equal 60.0 (single contributing component)."""
        db = _mongo()
        cid = self.user["company_id"]
        now = datetime.now(timezone.utc).isoformat()
        for i in range(10):
            db.tasks.insert_one({
                "id": uuid.uuid4().hex, "tm_user_id": self.user["id"], "company_id": cid,
                "doctor_id": "phaseD_doc", "task_title": "x", "due_date": _today_iso(),
                "status": "Completed" if i < 6 else "Open",
                "completed_at": now if i < 6 else None,
                "created_at": now, "updated_at": now,
                "deleted_at": None, "category": "other",
            })
        fei = requests.get(f"{API}/metrics/me/fei", headers=H(self.token), timeout=10).json()
        # Two components have enough data: promise_completion_rate (denom=10) AND
        # overdue_promise_rate (denom=4 open tasks — BELOW min=5, so insufficient).
        # Therefore only promise_completion_rate contributes → fei == 60.0.
        assert fei["fei"] == 60.0, fei
        assert fei["sufficient_data"] is True
        assert fei["label"] == "Medium"
        comp = next(c for c in fei["components"] if c["slug"] == "promise_completion_rate")
        assert comp["value_0_100"] == 60.0


# ============================================================
# SNAPSHOTS + RBAC
# ============================================================
class TestSnapshotsAndRBAC:
    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.admin = _login("admin@field.io", "admin123")
        self.user, self.token = _create_isolated_tm(self.owner, "snap")

    def teardown_method(self):
        _cleanup_user(self.owner, self.user["id"])

    def test_admin_can_run_snapshot_for_one_tm(self):
        # Seed enough data so at least one metric is sufficient
        db = _mongo()
        cid = self.user["company_id"]
        now = datetime.now(timezone.utc).isoformat()
        for i in range(10):
            db.tasks.insert_one({
                "id": uuid.uuid4().hex, "tm_user_id": self.user["id"], "company_id": cid,
                "doctor_id": "x", "task_title": "x", "due_date": _today_iso(),
                "status": "Completed" if i < 5 else "Open",
                "completed_at": now if i < 5 else None,
                "created_at": now, "updated_at": now,
                "deleted_at": None, "category": "other",
            })
        r = requests.post(f"{API}/metrics/snapshots/run", headers=H(self.admin),
                         params={"tm_id": self.user["id"]}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["snapshots_created"] >= 1
        # Listing should now return the snapshot
        snaps = requests.get(f"{API}/metrics/snapshots", headers=H(self.admin),
                             params={"tm_id": self.user["id"]}, timeout=10).json()
        assert isinstance(snaps, list)
        assert any(s.get("slug") == "promise_completion_rate" for s in snaps)

    def test_tm_cannot_read_another_tms_metrics(self):
        other_user, other_tok = _create_isolated_tm(self.owner, "other")
        try:
            r = requests.get(f"{API}/metrics/tm/{self.user['id']}", headers=H(other_tok), timeout=10)
            assert r.status_code == 403
        finally:
            _cleanup_user(self.owner, other_user["id"])
