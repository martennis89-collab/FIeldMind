"""Phase F — Intervention entity tests (15 tests, per spec)."""
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


def _create_isolated_user(role: str, email_suffix: str, team_id: str | None = None):
    admin = _login("admin@field.io", "admin123")
    requests.post(f"{API}/seed/init", timeout=30)
    email = f"phaseF.{role.lower()}.{email_suffix}.{uuid.uuid4().hex[:6]}@example.com"
    u = requests.post(f"{API}/users", headers=H(admin), json={
        "full_name": f"PhaseF {role} {email_suffix}",
        "email": email, "password": "pw1234", "role": role,
    }, timeout=10).json()
    if team_id:
        _mongo().users.update_one({"id": u["id"]}, {"$set": {"team_id": team_id}})
        u["team_id"] = team_id
    return u, _login(email, "pw1234")


def _cleanup(owner_token: str, *user_ids: str):
    db = _mongo()
    for uid in user_ids:
        for coll in ("interventions", "insight_cards", "tasks", "meetings", "visits"):
            # Soft-delete may not apply for the test rows; hard-clean is fine in tests
            db[coll].delete_many({"$or": [{"tm_user_id": uid}, {"manager_id": uid}, {"scope_id": uid}]})
        try:
            requests.delete(f"{API}/users/{uid}", headers=H(owner_token), timeout=10)
        except Exception:
            pass


def _seed_insight_card(tm_user, severity="High"):
    db = _mongo()
    cid = uuid.uuid4().hex
    db.insight_cards.insert_one({
        "id": cid,
        "company_id": tm_user["company_id"],
        "team_id": tm_user.get("team_id"),
        "tm_user_id": tm_user["id"],
        "scope_type": "TM",
        "scope_id": tm_user["id"],
        "severity": severity,
        "category": "iTero Execution",
        "title": "iTero demo discussions are not converting to bookings",
        "body": "PhaseF test insight.",
        "related_metric_slug": "itero_demo_discussed_to_booked_rate",
        "metric_value": 0.20,
        "suggested_action": "Review doctors where iTero demo was discussed but not booked.",
        "status": "New",
        "dedup_key": f"insight:{tm_user['id']}:phaseF:{uuid.uuid4().hex[:6]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return cid


class TestInterventionCreation:
    """Tests 1-3, 15: create paths + insight card preservation."""

    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        # Reuse seeded users — they share team_id_1 in the default seed.
        self.mgr = _login("manager@field.io", "manager123")
        self.tm1 = _login("tm1@field.io", "tm123")
        u = requests.get(f"{API}/users", headers=H(self.mgr), timeout=10).json()
        self.tm1_user = next(x for x in u if x["email"] == "tm1@field.io")
        self.mgr_user = next(x for x in u if x["email"] == "manager@field.io")

    def teardown_method(self):
        _mongo().interventions.delete_many({"manager_id": self.mgr_user["id"]})

    def test_1_create_intervention_from_insight(self):
        card_id = _seed_insight_card(self.tm1_user, severity="High")
        r = requests.post(
            f"{API}/interventions/from-insight/{card_id}",
            headers=H(self.mgr),
            json={"manager_note": "Pair with TM tomorrow", "due_date": "2026-12-31"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        i = r.json()
        assert i["insight_card_id"] == card_id
        assert i["created_from_insight"] is True
        assert i["tm_user_id"] == self.tm1_user["id"]
        assert i["track_type"] == "iTero"        # auto-derived from slug
        assert i["severity"] == "High"
        assert i["manager_note"] == "Pair with TM tomorrow"
        assert i["due_date"] == "2026-12-31"
        assert i["status"] == "Open"
        # Audit row created
        audit = requests.get(f"{API}/audit_logs", headers=H(_login("admin@field.io", "admin123")),
                            params={"event_type": "intervention_created", "entity_id": i["id"]},
                            timeout=10).json()
        assert len(audit) >= 1

    def test_2_intervention_links_to_insight_card_id(self):
        card_id = _seed_insight_card(self.tm1_user, severity="Medium")
        i = requests.post(f"{API}/interventions/from-insight/{card_id}",
                          headers=H(self.mgr), json={}, timeout=10).json()
        # Fetch by GET — link survives
        got = requests.get(f"{API}/interventions/{i['id']}", headers=H(self.mgr), timeout=10).json()
        assert got["insight_card_id"] == card_id

    def test_3_manager_can_create_manual_intervention(self):
        r = requests.post(f"{API}/interventions", headers=H(self.mgr), json={
            "tm_user_id": self.tm1_user["id"],
            "track_type": "Invisalign",
            "severity": "Medium",
            "issue_title": "Manual issue",
            "issue_description": "Test description",
            "suggested_action": "Do this",
            "due_date": "2026-12-31",
        }, timeout=10)
        assert r.status_code == 200, r.text
        i = r.json()
        assert i["insight_card_id"] is None
        assert i["created_from_insight"] is False
        assert i["track_type"] == "Invisalign"

    def test_15_insight_card_preserved_after_intervention_creation(self):
        card_id = _seed_insight_card(self.tm1_user, severity="High")
        # Initial status
        db = _mongo()
        before = db.insight_cards.find_one({"id": card_id}, {"_id": 0})
        assert before["status"] == "New"
        requests.post(f"{API}/interventions/from-insight/{card_id}",
                      headers=H(self.mgr), json={}, timeout=10)
        # Card still exists (not deleted), now Seen
        after = db.insight_cards.find_one({"id": card_id}, {"_id": 0})
        assert after is not None
        assert after["status"] == "Seen"
        assert after["seen_at"] is not None
        # The original metric data and body are intact
        assert after["body"] == before["body"]
        assert after["metric_value"] == before["metric_value"]


class TestInterventionRBAC:
    """Tests 4, 5, 6, 7, 8: role and company isolation."""

    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.admin_tok = _login("admin@field.io", "admin123")
        self.mgr = _login("manager@field.io", "manager123")
        self.tm1 = _login("tm1@field.io", "tm123")
        self.tm2 = _login("tm2@field.io", "tm123")
        users = requests.get(f"{API}/users", headers=H(self.admin_tok), timeout=10).json()
        self.tm1_user = next(x for x in users if x["email"] == "tm1@field.io")
        self.tm2_user = next(x for x in users if x["email"] == "tm2@field.io")
        # Create one intervention for TM1
        self.inter_tm1 = requests.post(f"{API}/interventions", headers=H(self.mgr), json={
            "tm_user_id": self.tm1_user["id"], "issue_title": "TM1 issue",
            "severity": "High", "track_type": "iTero",
        }, timeout=10).json()

    def teardown_method(self):
        _mongo().interventions.delete_many({"id": self.inter_tm1["id"]})

    def test_4_manager_sees_team_interventions(self):
        rows = requests.get(f"{API}/interventions", headers=H(self.mgr), timeout=10).json()
        assert any(r["id"] == self.inter_tm1["id"] for r in rows)
        # All visible rows are inside manager's team
        assert all(r.get("team_id") == self.tm1_user.get("team_id") for r in rows)

    def test_5_tm_sees_interventions_assigned_to_them(self):
        rows = requests.get(f"{API}/interventions", headers=H(self.tm1), timeout=10).json()
        assert any(r["id"] == self.inter_tm1["id"] for r in rows)
        assert all(r["tm_user_id"] == self.tm1_user["id"] for r in rows)

    def test_6_tm_cannot_delete_manager_intervention(self):
        r = requests.delete(f"{API}/interventions/{self.inter_tm1['id']}",
                            headers=H(self.tm1), timeout=10)
        assert r.status_code == 403
        # TM also cannot complete / dismiss
        r2 = requests.post(f"{API}/interventions/{self.inter_tm1['id']}/complete",
                           headers=H(self.tm1), timeout=10)
        assert r2.status_code == 403

    def test_7_admin_can_see_company_interventions(self):
        rows = requests.get(f"{API}/interventions", headers=H(self.admin_tok), timeout=10).json()
        assert any(r["id"] == self.inter_tm1["id"] for r in rows)
        assert all(r.get("company_id") == self.tm1_user.get("company_id") for r in rows)

    def test_8_cross_company_access_blocked(self):
        # Create a separate company + TM
        slug = f"phaseF_{uuid.uuid4().hex[:6]}"
        c = requests.post(f"{API}/companies", headers=H(self.owner), json={
            "company_name": "PhaseF Other Co", "slug": slug,
            "country": "X", "team_size_category": "1-5", "sales_motion": "other",
        }, timeout=10).json()
        u = requests.post(f"{API}/users", headers=H(self.admin_tok), json={
            "full_name": "PhaseF cross-co TM",
            "email": f"phaseF.cross.{slug}@example.com",
            "password": "pw1234", "role": "TM",
        }, timeout=10).json()
        _mongo().users.update_one({"id": u["id"]}, {"$set": {"company_id": c["id"]}})
        cross_tok = _login(u["email"], "pw1234")
        try:
            # Cross-company TM list returns empty
            rows = requests.get(f"{API}/interventions", headers=H(cross_tok), timeout=10).json()
            assert rows == []
            # Direct GET on the default-company intervention → 404
            r = requests.get(f"{API}/interventions/{self.inter_tm1['id']}",
                             headers=H(cross_tok), timeout=10)
            assert r.status_code == 404
        finally:
            requests.delete(f"{API}/users/{u['id']}", headers=H(self.owner), timeout=5)
            requests.post(f"{API}/companies/{c['id']}/deactivate",
                          headers=H(self.owner), timeout=5)


class TestInterventionTransitions:
    """Tests 9, 10, 11, 12: status transitions + soft delete + event ledger."""

    def setup_method(self):
        self.owner = _login(OWNER_EMAIL, OWNER_PASS)
        self.admin_tok = _login("admin@field.io", "admin123")
        self.mgr = _login("manager@field.io", "manager123")
        users = requests.get(f"{API}/users", headers=H(self.admin_tok), timeout=10).json()
        self.tm1_user = next(x for x in users if x["email"] == "tm1@field.io")

    def _create(self):
        return requests.post(f"{API}/interventions", headers=H(self.mgr), json={
            "tm_user_id": self.tm1_user["id"], "issue_title": "Test",
            "severity": "Medium", "track_type": "General",
        }, timeout=10).json()

    def test_9_mark_in_progress(self):
        i = self._create()
        r = requests.post(f"{API}/interventions/{i['id']}/in-progress",
                          headers=H(self.mgr), timeout=10).json()
        assert r["status"] == "In Progress"
        _mongo().interventions.delete_one({"id": i["id"]})

    def test_10_mark_completed_sets_completed_at(self):
        i = self._create()
        r = requests.post(f"{API}/interventions/{i['id']}/complete",
                          headers=H(self.mgr), timeout=10).json()
        assert r["status"] == "Completed"
        assert r["completed_at"] is not None
        _mongo().interventions.delete_one({"id": i["id"]})

    def test_11_dismiss_sets_dismissed_at(self):
        i = self._create()
        r = requests.post(f"{API}/interventions/{i['id']}/dismiss",
                          headers=H(self.mgr), timeout=10).json()
        assert r["status"] == "Dismissed"
        assert r["dismissed_at"] is not None
        _mongo().interventions.delete_one({"id": i["id"]})

    def test_12_delete_soft_deletes(self):
        i = self._create()
        r = requests.delete(f"{API}/interventions/{i['id']}", headers=H(self.mgr), timeout=10)
        assert r.status_code == 200
        # Row still in DB, deleted_at set
        row = _mongo().interventions.find_one({"id": i["id"]}, {"_id": 0})
        assert row is not None
        assert row["deleted_at"] is not None
        # Hidden from list
        rows = requests.get(f"{API}/interventions", headers=H(self.mgr), timeout=10).json()
        assert not any(r["id"] == i["id"] for r in rows)
        _mongo().interventions.delete_one({"id": i["id"]})

    def test_13_event_ledger_records_lifecycle(self):
        i = self._create()
        requests.post(f"{API}/interventions/{i['id']}/in-progress", headers=H(self.mgr), timeout=10)
        requests.post(f"{API}/interventions/{i['id']}/complete", headers=H(self.mgr), timeout=10)
        events = requests.get(f"{API}/audit_logs", headers=H(self.admin_tok),
                              params={"entity_id": i["id"]}, timeout=10).json()
        event_types = {e["event_type"] for e in events}
        assert "intervention_created" in event_types
        assert "intervention_in_progress" in event_types
        assert "intervention_completed" in event_types
        _mongo().interventions.delete_one({"id": i["id"]})

    def test_14_intervention_tab_filters(self):
        i_open = self._create()
        i_done = self._create()
        requests.post(f"{API}/interventions/{i_done['id']}/complete",
                      headers=H(self.mgr), timeout=10)
        i_dis = self._create()
        requests.post(f"{API}/interventions/{i_dis['id']}/dismiss",
                      headers=H(self.mgr), timeout=10)

        # Default: open + in-progress + completed
        rows = requests.get(f"{API}/interventions", headers=H(self.mgr), timeout=10).json()
        ids = {r["id"] for r in rows}
        assert i_open["id"] in ids
        assert i_done["id"] in ids
        assert i_dis["id"] not in ids
        # include_dismissed brings dismissed back
        rows = requests.get(f"{API}/interventions?include_dismissed=true",
                            headers=H(self.mgr), timeout=10).json()
        assert {r["id"] for r in rows} >= {i_open["id"], i_done["id"], i_dis["id"]}
        # Explicit status filter
        only_completed = requests.get(f"{API}/interventions?status=Completed",
                                      headers=H(self.mgr), timeout=10).json()
        assert any(r["id"] == i_done["id"] for r in only_completed)
        assert not any(r["id"] == i_open["id"] for r in only_completed)
        for x in (i_open, i_done, i_dis):
            _mongo().interventions.delete_one({"id": x["id"]})
