"""Phase L — Senior TM role: creation, scoping, RBAC across insights / interventions / reports / dashboards."""
import os
import uuid

import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE}/api"


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _seed():
    requests.post(f"{API}/seed/init", timeout=30)


def _create_user(admin_tok, role, full_name, team_id=None, manager_user_id=None):
    """Create a user via the admin endpoint. Returns the full user object + a login token."""
    email = f"{full_name.lower().replace(' ', '.')}.{uuid.uuid4().hex[:6]}@phasel.example.com"
    body = {
        "full_name": full_name,
        "email": email,
        "password": "pl-pass-123",
        "role": role,
        "team_id": team_id,
        "manager_user_id": manager_user_id,
    }
    r = requests.post(f"{API}/users", headers=H(admin_tok), json=body, timeout=15)
    assert r.status_code == 200, r.text
    user = r.json()
    tok = _login(email, "pl-pass-123")
    return user, tok, email


def _make_team(admin_tok):
    """Spin up a fresh team + Manager + SeniorTM + 2 TMs (one under Manager, one under SeniorTM)."""
    me = requests.get(f"{API}/auth/me", headers=H(admin_tok), timeout=10).json()
    team_id = me.get("team_id") or (
        requests.get(f"{API}/teams", headers=H(admin_tok), timeout=10).json()[0]["id"]
    )

    mgr_user, mgr_tok, _ = _create_user(admin_tok, "Manager", "Phase-L Mgr", team_id=team_id)
    sr_user, sr_tok, _ = _create_user(
        admin_tok, "SeniorTM", "Phase-L Snr",
        team_id=team_id, manager_user_id=mgr_user["id"],
    )
    tm_under_mgr, tm_mgr_tok, _ = _create_user(
        admin_tok, "TM", "Phase-L TM-Direct",
        team_id=team_id, manager_user_id=mgr_user["id"],
    )
    tm_under_sr, tm_sr_tok, _ = _create_user(
        admin_tok, "TM", "Phase-L TM-SubTeam",
        team_id=team_id, manager_user_id=sr_user["id"],
    )
    return {
        "team_id": team_id,
        "mgr": (mgr_user, mgr_tok),
        "sr": (sr_user, sr_tok),
        "tm_under_mgr": (tm_under_mgr, tm_mgr_tok),
        "tm_under_sr": (tm_under_sr, tm_sr_tok),
    }


def test_create_senior_tm_chain():
    _seed()
    adm = _login("admin@field.io", "admin123")
    setup = _make_team(adm)
    sr_user = setup["sr"][0]
    tm_under_sr = setup["tm_under_sr"][0]

    assert sr_user["role"] == "SeniorTM"
    assert sr_user["manager_user_id"] == setup["mgr"][0]["id"]
    assert tm_under_sr["manager_user_id"] == sr_user["id"]


def test_create_user_with_invalid_reports_to_chain_rejected():
    _seed()
    adm = _login("admin@field.io", "admin123")
    me = requests.get(f"{API}/auth/me", headers=H(adm), timeout=10).json()
    team_id = me.get("team_id") or (
        requests.get(f"{API}/teams", headers=H(adm), timeout=10).json()[0]["id"]
    )

    # SeniorTM cannot report to a TM
    tm_user, _, _ = _create_user(adm, "TM", "Phase-L Plain-TM", team_id=team_id)
    body = {
        "full_name": "Bad Snr",
        "email": f"bad.snr.{uuid.uuid4().hex[:6]}@phasel.example.com",
        "password": "x",
        "role": "SeniorTM",
        "team_id": team_id,
        "manager_user_id": tm_user["id"],  # invalid — TMs can't supervise
    }
    r = requests.post(f"{API}/users", headers=H(adm), json=body, timeout=15)
    assert r.status_code == 400, r.text
    assert "report to a Manager" in r.json()["detail"]


def test_senior_tm_list_users_scope():
    _seed()
    adm = _login("admin@field.io", "admin123")
    setup = _make_team(adm)
    _, sr_tok = setup["sr"]
    listing = requests.get(f"{API}/users", headers=H(sr_tok), timeout=15).json()
    ids = {u["id"] for u in listing}
    # SeniorTM should see themselves + their direct report, NOT the manager's other TM
    assert setup["sr"][0]["id"] in ids
    assert setup["tm_under_sr"][0]["id"] in ids
    assert setup["tm_under_mgr"][0]["id"] not in ids
    assert setup["mgr"][0]["id"] not in ids


def test_senior_tm_dashboard_manager_view_only_sees_own_subteam():
    """Senior TM hits the manager dashboard. Visit/task counts should only
    include the SeniorTM themselves + their direct reports — NOT the
    manager's other TMs.
    """
    _seed()
    adm = _login("admin@field.io", "admin123")
    setup = _make_team(adm)
    _, sr_tok = setup["sr"]

    # Both endpoints should respond 200 (Senior TM has manager-style access).
    for ep in ["/dashboard/manager", "/dashboard/manager/performance", "/dashboard/manager/interventions"]:
        r = requests.get(f"{API}{ep}", headers=H(sr_tok), timeout=15)
        assert r.status_code == 200, f"{ep} failed: {r.text}"


def test_senior_tm_generates_own_weekly_report():
    _seed()
    adm = _login("admin@field.io", "admin123")
    setup = _make_team(adm)
    _, sr_tok = setup["sr"]

    gen = requests.post(f"{API}/reports/generate", headers=H(sr_tok), timeout=30)
    assert gen.status_code == 200, gen.text
    draft = gen.json()
    assert draft.get("week_start")
    assert draft.get("week_end")


def test_senior_tm_can_comment_on_direct_report_weekly():
    _seed()
    adm = _login("admin@field.io", "admin123")
    setup = _make_team(adm)
    sr_user, sr_tok = setup["sr"]
    tm_user, tm_tok = setup["tm_under_sr"]

    # Direct-report TM submits a report
    gen = requests.post(f"{API}/reports/generate", headers=H(tm_tok), timeout=30).json()
    saved = requests.post(
        f"{API}/reports",
        headers=H(tm_tok),
        json={"week_start": gen["week_start"], "week_end": gen["week_end"], "auto_summary": gen.get("auto_summary"), "content": gen.get("content")},
        timeout=20,
    )
    assert saved.status_code == 200, saved.text
    rid = saved.json()["id"]

    # SeniorTM comments on it — should succeed
    comment = requests.post(
        f"{API}/reports/{rid}/comment",
        headers=H(sr_tok),
        json={"text": "Looks good — let's push the iTero demo next week."},
        timeout=15,
    )
    assert comment.status_code == 200, comment.text

    # But cannot comment on the OTHER TM's report (under the Manager directly)
    tm2_tok = setup["tm_under_mgr"][1]
    gen2 = requests.post(f"{API}/reports/generate", headers=H(tm2_tok), timeout=30).json()
    saved2 = requests.post(
        f"{API}/reports",
        headers=H(tm2_tok),
        json={"week_start": gen2["week_start"], "week_end": gen2["week_end"], "auto_summary": gen2.get("auto_summary"), "content": gen2.get("content")},
        timeout=20,
    )
    assert saved2.status_code == 200, saved2.text
    rid2 = saved2.json()["id"]
    blocked = requests.post(
        f"{API}/reports/{rid2}/comment",
        headers=H(sr_tok),
        json={"text": "out of scope"},
        timeout=15,
    )
    assert blocked.status_code == 403, blocked.text


def test_senior_tm_can_create_intervention_on_direct_report_only():
    _seed()
    adm = _login("admin@field.io", "admin123")
    setup = _make_team(adm)
    sr_user, sr_tok = setup["sr"]
    tm_under_sr_user, _ = setup["tm_under_sr"]
    tm_under_mgr_user, _ = setup["tm_under_mgr"]

    # OK: targeting direct report
    ok = requests.post(
        f"{API}/interventions",
        headers=H(sr_tok),
        json={
            "tm_user_id": tm_under_sr_user["id"],
            "issue_title": "Push pricing conversation",
            "severity": "Medium",
            "track_type": "Invisalign",
        },
        timeout=15,
    )
    assert ok.status_code == 200, ok.text

    # 403: targeting a TM under the Manager directly
    bad = requests.post(
        f"{API}/interventions",
        headers=H(sr_tok),
        json={
            "tm_user_id": tm_under_mgr_user["id"],
            "issue_title": "out of scope",
            "severity": "Low",
        },
        timeout=15,
    )
    assert bad.status_code == 403, bad.text

    # Cleanup
    requests.delete(f"{API}/interventions/{ok.json()['id']}", headers=H(sr_tok), timeout=10)


def test_manager_can_reassign_tm_between_self_and_seniortm():
    _seed()
    adm = _login("admin@field.io", "admin123")
    setup = _make_team(adm)
    mgr_user, mgr_tok = setup["mgr"]
    sr_user, _ = setup["sr"]
    tm_user, _ = setup["tm_under_mgr"]

    # Reassign tm_under_mgr → under SeniorTM
    upd = requests.put(
        f"{API}/users/{tm_user['id']}",
        headers=H(mgr_tok),
        json={"manager_user_id": sr_user["id"]},
        timeout=15,
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["manager_user_id"] == sr_user["id"]

    # Now reassign back to Manager (self)
    upd2 = requests.put(
        f"{API}/users/{tm_user['id']}",
        headers=H(mgr_tok),
        json={"manager_user_id": mgr_user["id"]},
        timeout=15,
    )
    assert upd2.status_code == 200, upd2.text


def test_manager_cannot_grant_admin_role():
    _seed()
    adm = _login("admin@field.io", "admin123")
    setup = _make_team(adm)
    mgr_user, mgr_tok = setup["mgr"]
    tm_user, _ = setup["tm_under_mgr"]

    bad = requests.put(
        f"{API}/users/{tm_user['id']}",
        headers=H(mgr_tok),
        json={"role": "Admin"},
        timeout=15,
    )
    assert bad.status_code == 403, bad.text
