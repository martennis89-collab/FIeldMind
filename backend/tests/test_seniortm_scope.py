"""Senior TM scope.

A Senior TM sees themselves and the TMs who report to them — nobody else.
Every user here deliberately shares one team_id, because team_id used to be
the boundary and that was wider than the role: it exposed peer Senior TMs and
TMs who report to somebody else.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"

PASSWORD = "scope-pass-123"


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email}: {r.text}"
    return r.json()["token"]


def _mk_user(admin_tok, role, team_id, manager_user_id=None):
    email = f"scope.{uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{API}/users", headers=H(admin_tok), timeout=20, json={
        "full_name": f"Scope {role}", "email": email, "password": PASSWORD,
        "role": role, "team_id": team_id, "manager_user_id": manager_user_id,
    })
    assert r.status_code == 200, r.text
    tok = _login(email, PASSWORD)
    me = requests.get(f"{API}/auth/me", headers=H(tok), timeout=15).json()
    return me["id"], tok


def _mk_event(tok, title):
    when = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    r = requests.post(f"{API}/events", headers=H(tok), timeout=20,
                      json={"title": title, "scheduled_at": when, "duration_minutes": 60})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _mk_expense(tok, amount="25"):
    r = requests.post(f"{API}/expenses", headers=H(tok), timeout=20,
                      data={"expense_date": "2027-01-05", "category": "Food", "amount": amount})
    assert r.status_code == 200, r.text
    return r.json()["expense"]["id"]


requests.post(f"{API}/seed/init", timeout=60)
ADMIN = _login("admin@field.io", "admin123")
TEAM_ID = requests.get(
    f"{API}/auth/me", headers=H(_login("tm1@field.io", "tm123")), timeout=15
).json().get("team_id")

SENIOR_A_ID, SENIOR_A = _mk_user(ADMIN, "SeniorTM", TEAM_ID)
SENIOR_B_ID, SENIOR_B = _mk_user(ADMIN, "SeniorTM", TEAM_ID)
TM_MINE_ID, TM_MINE = _mk_user(ADMIN, "TM", TEAM_ID, manager_user_id=SENIOR_A_ID)
TM_THEIRS_ID, TM_THEIRS = _mk_user(ADMIN, "TM", TEAM_ID, manager_user_id=SENIOR_B_ID)


def test_calendar_events_exclude_other_seniors_people():
    """A Senior TM had no branch in GET /events at all, so they fell through
    to the bare company scope and saw every event in the business."""
    mine = _mk_event(TM_MINE, "Reports to me")
    theirs = _mk_event(TM_THEIRS, "Reports to the other senior")
    peer = _mk_event(SENIOR_B, "The other senior's own")

    rows = requests.get(f"{API}/events", headers=H(SENIOR_A),
                        params={"when": "all"}, timeout=20).json()
    ids = {e["id"] for e in rows}
    assert mine in ids, "own sub-team's event missing"
    assert theirs not in ids, "saw a TM who reports to another Senior TM"
    assert peer not in ids, "saw a peer Senior TM's own event"


def test_visits_drilldown_cannot_escape_subteam():
    """?tm_user_id= used to overwrite the Senior TM's own-id filter outright,
    and unlike Manager there is no team_id left to constrain it."""
    ok = requests.get(f"{API}/visits", headers=H(SENIOR_A),
                      params={"tm_user_id": TM_MINE_ID}, timeout=20)
    assert ok.status_code == 200, ok.text

    outside = requests.get(f"{API}/visits", headers=H(SENIOR_A),
                           params={"tm_user_id": TM_THEIRS_ID}, timeout=20)
    assert outside.status_code == 403, outside.text

    peer = requests.get(f"{API}/visits", headers=H(SENIOR_A),
                        params={"tm_user_id": SENIOR_B_ID}, timeout=20)
    assert peer.status_code == 403, peer.text


def test_expense_edit_rights_follow_the_subteam_not_the_team():
    """Guards the edit rights a Senior TM was given over their team's
    expenses: sharing a team_id must not be enough to earn them."""
    mine = _mk_expense(TM_MINE)
    theirs = _mk_expense(TM_THEIRS)

    ok = requests.put(f"{API}/expenses/{mine}", headers=H(SENIOR_A),
                      json={"amount": 26}, timeout=20)
    assert ok.status_code == 200, ok.text

    outside = requests.put(f"{API}/expenses/{theirs}", headers=H(SENIOR_A),
                           json={"amount": 26}, timeout=20)
    assert outside.status_code == 403, outside.text
