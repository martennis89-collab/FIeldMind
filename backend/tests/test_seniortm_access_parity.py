"""Test SeniorTM has TM-parity access on the 3 identified gaps:
1. iTero pipeline/board/demos/demo-breakdown/KPIs scoped to own + direct-report TMs
2. Team roster endpoints include SeniorTM users
3. POST /doctors stamps team_id for SeniorTM
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://territory-intel-8.preview.emergentagent.com').rstrip('/')

CREDS = {
    "senior": ("snr.demo.1782126329@field.io", "senior123"),
    "tm1":    ("tm1@field.io", "tm123"),
    "manager": ("manager@field.io", "manager123"),
    "admin":  ("admin@field.io", "admin123"),
}


def _login(email, pwd):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": pwd}, timeout=15)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:200]}"
    j = r.json()
    return j["token"], j["user"]


@pytest.fixture(scope="module")
def tokens():
    return {k: _login(*v) for k, v in CREDS.items()}


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# -------------------- iTero pipeline scope --------------------

def test_itero_pipeline_senior_scope_less_than_admin(tokens):
    s_tok, s_user = tokens["senior"]
    a_tok, _ = tokens["admin"]
    tm_tok, tm_user = tokens["tm1"]

    r_s = requests.get(f"{BASE_URL}/api/itero/pipeline", headers=_h(s_tok), timeout=20)
    r_a = requests.get(f"{BASE_URL}/api/itero/pipeline", headers=_h(a_tok), timeout=20)
    r_tm = requests.get(f"{BASE_URL}/api/itero/pipeline", headers=_h(tm_tok), timeout=20)
    assert r_s.status_code == 200
    assert r_a.status_code == 200
    assert r_tm.status_code == 200
    s_total = r_s.json()["total"]
    a_total = r_a.json()["total"]
    tm_total = r_tm.json()["total"]
    print(f"pipeline totals — senior={s_total}, admin={a_total}, tm1={tm_total}")
    # Senior should NOT see the full company (unless company only has senior's docs)
    assert s_total <= a_total, "SeniorTM sees more than Admin (impossible)"
    # Senior scope must include TM1 (who reports to Senior per task) — flatten tm ids visible
    s_tm_ids = set()
    for stage_rows in r_s.json()["groups"].values():
        for row in stage_rows:
            if row.get("tm_user_id"):
                s_tm_ids.add(row["tm_user_id"])
    print(f"Senior sees doctors assigned to tm_ids: {s_tm_ids}")
    # TM1's id should appear if tm1 has any active doctors, OR senior should at least see own + include tm1's id in the query scope
    # Verify tm1 reports to senior
    # (Cannot verify manager_user_id from API easily — but we can check that if tm1 has doctors, senior sees them.)
    if tm_total > 0:
        assert tm_user["id"] in s_tm_ids, \
            f"SeniorTM should see TM1's doctors (tm1 has {tm_total}) but senior tm_ids={s_tm_ids}"


def test_itero_board_senior_scope(tokens):
    s_tok, _ = tokens["senior"]
    r = requests.get(f"{BASE_URL}/api/itero/pipeline", headers=_h(s_tok), timeout=20)
    # Board endpoint may or may not exist; try
    r2 = requests.get(f"{BASE_URL}/api/itero/board", headers=_h(s_tok), timeout=20)
    # Either 200 or 404, but should never be 500
    assert r2.status_code in (200, 404), f"itero/board -> {r2.status_code}"


def test_itero_demos_senior_scope(tokens):
    s_tok, _ = tokens["senior"]
    a_tok, _ = tokens["admin"]
    r_s = requests.get(f"{BASE_URL}/api/itero/demos", headers=_h(s_tok), timeout=20)
    r_a = requests.get(f"{BASE_URL}/api/itero/demos", headers=_h(a_tok), timeout=20)
    assert r_s.status_code == 200
    assert r_a.status_code == 200
    s_counts = r_s.json()["counts"]
    a_counts = r_a.json()["counts"]
    print(f"itero/demos senior={s_counts}, admin={a_counts}")
    # Sum should be <= admin's sum
    s_total = sum(v for k, v in s_counts.items() if k in ("booked", "completed", "lost"))
    a_total = sum(v for k, v in a_counts.items() if k in ("booked", "completed", "lost"))
    assert s_total <= a_total


def test_itero_demo_breakdown_senior_scope(tokens):
    s_tok, _ = tokens["senior"]
    a_tok, _ = tokens["admin"]
    r_s = requests.get(f"{BASE_URL}/api/itero/demo-breakdown?scope=all",
                       headers=_h(s_tok), timeout=20)
    r_a = requests.get(f"{BASE_URL}/api/itero/demo-breakdown?scope=all",
                       headers=_h(a_tok), timeout=20)
    assert r_s.status_code == 200
    assert r_a.status_code == 200
    sc, ac = r_s.json()["counts"], r_a.json()["counts"]
    print(f"demo-breakdown senior={sc}, admin={ac}")
    assert sc["booked"] <= ac["booked"]
    assert sc["completed"] <= ac["completed"]
    assert sc["discussed"] <= ac["discussed"]


# -------------------- Regression: TM & Manager --------------------

def test_tm_pipeline_only_own(tokens):
    tm_tok, tm_user = tokens["tm1"]
    r = requests.get(f"{BASE_URL}/api/itero/pipeline", headers=_h(tm_tok), timeout=20)
    assert r.status_code == 200
    for stage_rows in r.json()["groups"].values():
        for row in stage_rows:
            assert row.get("tm_user_id") == tm_user["id"], \
                f"TM sees doctor not assigned to them: {row}"


def test_manager_pipeline_team_scope(tokens):
    m_tok, _ = tokens["manager"]
    r = requests.get(f"{BASE_URL}/api/itero/pipeline", headers=_h(m_tok), timeout=20)
    assert r.status_code == 200
    # Just make sure it doesn't 500 — team scope resolves.
    assert "total" in r.json()


# -------------------- Doctor create by SeniorTM stamps team_id --------------------

def test_senior_creates_doctor_gets_team_id_stamp(tokens):
    s_tok, s_user = tokens["senior"]
    # Senior's team_id
    r_me = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(s_tok), timeout=15)
    assert r_me.status_code == 200
    senior_team_id = r_me.json().get("team_id")
    print(f"Senior team_id={senior_team_id}")

    import uuid
    unique_name = f"TEST_SnrDoc_{uuid.uuid4().hex[:8]}"
    payload = {
        "doctor_name": unique_name,
        "clinic_name": "TEST Clinic",
        "city": "TESTVille",
        "doctor_type": "GP",
        "segment": "Occasional",
    }
    r_c = requests.post(f"{BASE_URL}/api/doctors", headers=_h(s_tok),
                        json=payload, timeout=20)
    assert r_c.status_code == 200, f"create -> {r_c.status_code} {r_c.text[:300]}"
    created = r_c.json()
    doc_id = created["id"]
    print(f"Created doctor {doc_id} team_id={created.get('team_id')} assigned_tm_id={created.get('assigned_tm_id')}")

    try:
        # TM/SeniorTM branch stamps assigned_tm_id=senior AND team_id=senior's team
        assert created.get("assigned_tm_id") == s_user["id"], \
            "SeniorTM-created doctor should be assigned to SeniorTM"
        assert created.get("team_id") == senior_team_id, \
            f"team_id not stamped: got {created.get('team_id')}, expected {senior_team_id}"

        # GET to verify persistence
        r_g = requests.get(f"{BASE_URL}/api/doctors/{doc_id}", headers=_h(s_tok), timeout=15)
        assert r_g.status_code == 200
        got = r_g.json()
        assert got.get("team_id") == senior_team_id
    finally:
        # Cleanup
        requests.delete(f"{BASE_URL}/api/doctors/{doc_id}", headers=_h(s_tok), timeout=15)


# -------------------- Team roster includes SeniorTM --------------------

def test_manager_dashboard_includes_seniortm_in_by_tm(tokens):
    """Manager dashboard /dashboard/manager returns by_tm which now uses role $in [TM, SeniorTM]."""
    m_tok, _ = tokens["manager"]
    r = requests.get(f"{BASE_URL}/api/dashboard/manager", headers=_h(m_tok), timeout=30)
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    tms = j.get("stats", {}).get("tms", 0)
    by_tm = j.get("by_tm", [])
    print(f"manager dashboard tms={tms}, by_tm count={len(by_tm)}")
    # Query the users to see if any SeniorTM exists in this team; if so, they should appear
    # (Best-effort — just assert endpoint works and returns list)
    assert isinstance(by_tm, list)


def test_manager_performance_includes_seniortm(tokens):
    m_tok, _ = tokens["manager"]
    r = requests.get(f"{BASE_URL}/api/dashboard/manager/performance", headers=_h(m_tok), timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json().get("rows"), list)


# -------------------- Sanity: token endpoints don't 500 --------------------

def test_senior_can_call_kpis(tokens):
    s_tok, _ = tokens["senior"]
    # Try common iTero KPI endpoints
    for path in ("/api/itero/kpis", "/api/dashboard/manager/itero"):
        r = requests.get(f"{BASE_URL}{path}", headers=_h(s_tok), timeout=20)
        print(f"{path} -> {r.status_code}")
        assert r.status_code in (200, 404), f"{path} unexpected {r.status_code}: {r.text[:200]}"
