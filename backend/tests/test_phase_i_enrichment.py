"""Phase I — Insight & Intervention enrichment (scope_name, tm_name, doctor_name) tests."""
import os
import uuid
import requests

from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _mongo():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_demo():
    """Idempotent demo seed — gives us admin/manager/tm1 with real cards & rows."""
    requests.post(f"{API}/seed/init", timeout=30)


def test_insights_team_includes_scope_name_for_managers():
    """/insights/team must enrich every card with a readable `scope_name` (TM full_name)."""
    _seed_demo()
    mgr = _login("manager@field.io", "manager123")
    r = requests.get(f"{API}/insights/team", headers=H(mgr), timeout=15)
    assert r.status_code == 200, r.text
    cards = r.json()
    assert isinstance(cards, list)
    if not cards:
        # If no cards exist yet, trigger generation
        requests.post(f"{API}/insights/generate", headers=H(mgr), timeout=60)
        r = requests.get(f"{API}/insights/team", headers=H(mgr), timeout=15)
        cards = r.json()
    assert len(cards) > 0, "expected at least one team insight card after generation"
    # Every card MUST carry the `scope_name` key (None is allowed when scope is non-TM)
    for c in cards:
        assert "scope_name" in c, f"card missing scope_name field: {c.get('id')}"
    # At least ONE card should have a populated scope_name from a real TM
    with_name = [c for c in cards if c.get("scope_name")]
    assert with_name, "expected at least one card with a populated scope_name"
    # Sanity: scope_name should not equal scope_id (it must be the full_name)
    sample = with_name[0]
    assert sample["scope_name"] != sample["scope_id"]


def test_insights_company_returns_wrapped_payload_with_scope_names():
    """/insights/company must wrap cards under {cards, by_severity, by_category, total} and enrich them."""
    _seed_demo()
    admin = _login("admin@field.io", "admin123")
    r = requests.get(f"{API}/insights/company", headers=H(admin), timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, dict) and "cards" in data and "by_severity" in data
    for c in data["cards"]:
        assert "scope_name" in c


def test_interventions_list_includes_tm_name_and_doctor_name():
    """`GET /interventions` must enrich every row with readable tm_name + doctor_name keys."""
    _seed_demo()
    mgr_tok = _login("manager@field.io", "manager123")

    # Ensure at least one intervention exists by creating one
    me_r = requests.get(f"{API}/auth/me", headers=H(mgr_tok), timeout=10)
    assert me_r.status_code == 200
    tm_r = requests.get(f"{API}/users", headers=H(mgr_tok), timeout=10)
    tms = [u for u in tm_r.json() if u["role"] == "TM"]
    assert tms, "expected at least one TM in demo seed"
    tm = tms[0]

    create = requests.post(
        f"{API}/interventions",
        headers=H(mgr_tok),
        json={
            "tm_user_id": tm["id"],
            "issue_title": f"PhaseI test {uuid.uuid4().hex[:6]}",
            "severity": "Medium",
            "track_type": "General",
        },
        timeout=15,
    )
    assert create.status_code == 200, create.text
    new = create.json()
    # Single-row create response is already enriched
    assert "tm_name" in new and new["tm_name"] == tm["full_name"]
    assert "doctor_name" in new and new["doctor_name"] is None

    # List response is enriched too
    listing = requests.get(
        f"{API}/interventions?include_dismissed=true&include_completed=true",
        headers=H(mgr_tok),
        timeout=15,
    )
    assert listing.status_code == 200
    rows = listing.json()
    assert any(r["id"] == new["id"] for r in rows)
    target = next(r for r in rows if r["id"] == new["id"])
    assert target["tm_name"] == tm["full_name"]
    assert "doctor_name" in target

    # Cleanup
    requests.delete(f"{API}/interventions/{new['id']}", headers=H(mgr_tok), timeout=10)


def test_intervention_create_with_doctor_id_populates_doctor_name():
    """Phase I: optional doctor picker — when a doctor is linked, doctor_name comes back."""
    _seed_demo()
    mgr_tok = _login("manager@field.io", "manager123")

    # Pick any doctor in scope
    docs = requests.get(f"{API}/doctors?limit=1", headers=H(mgr_tok), timeout=15).json()
    if isinstance(docs, dict):
        docs = docs.get("doctors") or docs.get("items") or []
    assert docs, "expected at least one doctor in demo seed"
    doc = docs[0]

    # Pick a TM
    tms = [u for u in requests.get(f"{API}/users", headers=H(mgr_tok), timeout=10).json() if u["role"] == "TM"]
    tm = tms[0]

    create = requests.post(
        f"{API}/interventions",
        headers=H(mgr_tok),
        json={
            "tm_user_id": tm["id"],
            "doctor_id": doc["id"],
            "issue_title": f"PhaseI doctor-linked {uuid.uuid4().hex[:6]}",
            "severity": "Low",
            "track_type": "iTero",
        },
        timeout=15,
    )
    assert create.status_code == 200, create.text
    body = create.json()
    assert body["doctor_id"] == doc["id"]
    assert body["doctor_name"] == doc["doctor_name"]
    assert body["tm_name"] == tm["full_name"]

    # PUT updates also re-enrich
    upd = requests.put(
        f"{API}/interventions/{body['id']}",
        headers=H(mgr_tok),
        json={"manager_note": "updated by Phase I test"},
        timeout=15,
    )
    assert upd.status_code == 200
    assert upd.json()["doctor_name"] == doc["doctor_name"]
    assert upd.json()["tm_name"] == tm["full_name"]

    requests.delete(f"{API}/interventions/{body['id']}", headers=H(mgr_tok), timeout=10)


def test_intervention_create_with_unknown_doctor_returns_404():
    """Cross-company isolation: unknown doctor_id → 404, no row written."""
    _seed_demo()
    mgr_tok = _login("manager@field.io", "manager123")
    tms = [u for u in requests.get(f"{API}/users", headers=H(mgr_tok), timeout=10).json() if u["role"] == "TM"]
    tm = tms[0]

    r = requests.post(
        f"{API}/interventions",
        headers=H(mgr_tok),
        json={
            "tm_user_id": tm["id"],
            "doctor_id": "00000000-0000-0000-0000-000000000000",
            "issue_title": "should fail",
            "severity": "Low",
        },
        timeout=15,
    )
    assert r.status_code == 404, r.text


def test_create_from_insight_accepts_doctor_id_override():
    """Phase I: /interventions/from-insight/{id} must honor doctor_id override and enrich the response."""
    _seed_demo()
    mgr_tok = _login("manager@field.io", "manager123")

    # Ensure at least one insight card exists
    cards = requests.get(f"{API}/insights/team", headers=H(mgr_tok), timeout=15).json()
    if not cards:
        requests.post(f"{API}/insights/generate", headers=H(mgr_tok), timeout=60)
        cards = requests.get(f"{API}/insights/team", headers=H(mgr_tok), timeout=15).json()
    assert cards, "expected at least one insight card"
    card = cards[0]

    docs = requests.get(f"{API}/doctors?limit=1", headers=H(mgr_tok), timeout=15).json()
    if isinstance(docs, dict):
        docs = docs.get("doctors") or docs.get("items") or []
    assert docs
    doc = docs[0]

    r = requests.post(
        f"{API}/interventions/from-insight/{card['id']}",
        headers=H(mgr_tok),
        json={"doctor_id": doc["id"], "manager_note": "linked via Phase I test"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    inter = r.json()
    assert inter["doctor_id"] == doc["id"]
    assert inter["doctor_name"] == doc["doctor_name"]
    assert inter["created_from_insight"] is True
    requests.delete(f"{API}/interventions/{inter['id']}", headers=H(mgr_tok), timeout=10)


def test_tm_cannot_create_intervention():
    """RBAC unchanged: TM still cannot create interventions even with the new doctor_id field."""
    _seed_demo()
    tm_tok = _login("tm1@field.io", "tm123")
    r = requests.post(
        f"{API}/interventions",
        headers=H(tm_tok),
        json={"issue_title": "should fail", "severity": "Low"},
        timeout=10,
    )
    assert r.status_code == 403, r.text
