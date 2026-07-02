"""Phase M1 — Monthly Reimbursement Report backend regression."""
from __future__ import annotations
import os
import time
import sys
from pathlib import Path
import pytest
import requests
from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_DIR / ".env")
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def H(t):
    return {"Authorization": f"Bearer {t}"}


def login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=10)
    assert r.status_code == 200, f"{email} login: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def actors():
    tm = login("tm1@field.io", "tm123")
    senior = login("snr.demo.1782126329@field.io", "senior123")
    owner = login("martennis89@gmail.com", "1234")
    # Ensure tm1 reports to the senior TM so scope tests pass.
    requests.patch(
        f"{API}/users/{tm['user']['id']}",
        headers=H(owner["token"]),
        json={"manager_user_id": senior["user"]["id"]},
        timeout=10,
    )
    return {"tm": tm, "senior": senior, "owner": owner}


@pytest.fixture(scope="module")
def month_str():
    # Use last month so ambient data doesn't collide with today's fixtures.
    from datetime import datetime, timezone, timedelta
    d = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    return d.strftime("%Y-%m")


@pytest.fixture(scope="module")
def visited_doctors(actors, month_str):
    """Ensure the TM has ≥1 visit in the target month by seeding via API."""
    tok = actors["tm"]["token"]
    # Grab a doctor assigned to the TM.
    r = requests.get(f"{API}/doctors", headers=H(tok), timeout=10)
    body = r.json()
    if isinstance(body, list):
        docs = body
    elif isinstance(body, dict):
        docs = body.get("doctors") or body.get("items") or []
    else:
        docs = []
    if not docs:
        pytest.skip("No doctors available for TM to visit")
    d1 = docs[0]
    # Seed a couple of visits inside the target month.
    for i in range(2):
        requests.post(
            f"{API}/visits",
            headers=H(tok),
            json={"doctor_id": d1["id"], "visit_date": f"{month_str}-15T10:0{i}:00Z", "note": "reimbursement seed"},
            timeout=15,
        )
    return [d1]


def test_generate_report(actors, month_str, visited_doctors):
    tok = actors["tm"]["token"]
    r = requests.post(f"{API}/reimbursement/reports/generate", headers=H(tok), json={"month": month_str}, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "Draft"
    assert j["month"] == month_str
    assert j["total_visits"] >= 2
    assert isinstance(j["doctor_breakdown"], list) and len(j["doctor_breakdown"]) >= 1
    # Since KM likely missing, expect at least one MissingKM row.
    missing = [d for d in j["doctor_breakdown"] if d["match_status"] == "MissingKM"]
    assert len(missing) >= 1
    # Second generation returns the SAME report (dedupe).
    r2 = requests.post(f"{API}/reimbursement/reports/generate", headers=H(tok), json={"month": month_str}, timeout=30)
    assert r2.status_code == 200 and r2.json()["id"] == j["id"]


def test_missing_km_flow_and_submit(actors, month_str, visited_doctors):
    tok = actors["tm"]["token"]
    # Fetch the draft
    r = requests.get(f"{API}/reimbursement/reports?month={month_str}", headers=H(tok), timeout=10)
    report = r.json()["reports"][0]
    report_id = report["id"]
    # 1) Trying to submit without KM must 400.
    r_bad = requests.post(f"{API}/reimbursement/reports/{report_id}/submit", headers=H(tok), timeout=10)
    assert r_bad.status_code == 400
    # 2) Fill KM for every missing doctor.
    for d in report["doctor_breakdown"]:
        if d["match_status"] == "MissingKM":
            r_km = requests.post(f"{API}/doctor-km", headers=H(tok),
                                 json={"doctor_id": d["doctor_id"], "km_per_visit": 12.5}, timeout=10)
            assert r_km.status_code == 200, r_km.text
    # 3) Refresh breakdown
    r_ref = requests.post(f"{API}/reimbursement/reports/{report_id}/refresh-breakdown", headers=H(tok), timeout=10)
    assert r_ref.status_code == 200
    assert all(d["match_status"] == "Matched" for d in r_ref.json()["doctor_breakdown"])
    # 4) Still needs fuel price → submit 400
    r_bad2 = requests.post(f"{API}/reimbursement/reports/{report_id}/submit", headers=H(tok), timeout=10)
    assert r_bad2.status_code == 400
    # 5) Set fuel price
    r_price = requests.patch(f"{API}/reimbursement/reports/{report_id}", headers=H(tok),
                             json={"fuel_price_per_l": 1.85}, timeout=10)
    assert r_price.status_code == 200
    assert r_price.json()["totals"]["fuel_cost"] is not None
    # 6) Submit succeeds
    r_ok = requests.post(f"{API}/reimbursement/reports/{report_id}/submit", headers=H(tok), timeout=10)
    assert r_ok.status_code == 200, r_ok.text
    assert r_ok.json()["status"] == "Submitted"
    # 7) TM cannot edit after submit
    r_lock = requests.patch(f"{API}/reimbursement/reports/{report_id}", headers=H(tok),
                            json={"fuel_price_per_l": 2.0}, timeout=10)
    assert r_lock.status_code == 403


def test_senior_review_and_pdf(actors, month_str):
    stok = actors["senior"]["token"]
    ttok = actors["tm"]["token"]
    # SeniorTM sees the submitted report in their scope.
    r = requests.get(f"{API}/reimbursement/reports?month={month_str}", headers=H(stok), timeout=10)
    assert r.status_code == 200
    reports = [rep for rep in r.json()["reports"] if rep["tm_user_id"] == actors["tm"]["user"]["id"]]
    assert reports, "SeniorTM should see the TM's submitted report"
    report_id = reports[0]["id"]
    # Request changes without comment → 400
    r_bad = requests.post(f"{API}/reimbursement/reports/{report_id}/request-changes", headers=H(stok),
                          json={"comment": ""}, timeout=10)
    assert r_bad.status_code == 400
    # Request changes with comment → 200
    r_rc = requests.post(f"{API}/reimbursement/reports/{report_id}/request-changes", headers=H(stok),
                        json={"comment": "please double-check tolls"}, timeout=10)
    assert r_rc.status_code == 200
    assert r_rc.json()["status"] == "Changes Requested"
    # TM can now edit again
    r_edit = requests.patch(f"{API}/reimbursement/reports/{report_id}", headers=H(ttok),
                            json={"fuel_price_per_l": 1.90}, timeout=10)
    assert r_edit.status_code == 200
    # Resubmit
    requests.post(f"{API}/reimbursement/reports/{report_id}/submit", headers=H(ttok), timeout=10)
    # Senior approves
    r_ok = requests.post(f"{API}/reimbursement/reports/{report_id}/approve", headers=H(stok), timeout=10)
    assert r_ok.status_code == 200 and r_ok.json()["status"] == "Approved"
    # Mark paid
    r_paid = requests.post(f"{API}/reimbursement/reports/{report_id}/mark-paid", headers=H(stok), timeout=10)
    assert r_paid.status_code == 200 and r_paid.json()["status"] == "Paid"
    # PDF download
    r_pdf = requests.get(f"{API}/reimbursement/reports/{report_id}/pdf", headers=H(stok), timeout=15)
    assert r_pdf.status_code == 200
    assert r_pdf.content[:5] == b"%PDF-"
    assert "attachment" in r_pdf.headers.get("content-disposition", "")


def test_rbac_tm_cannot_see_other_tm_reports(actors, month_str):
    tok = actors["tm"]["token"]
    r = requests.get(f"{API}/reimbursement/reports", headers=H(tok), timeout=10)
    assert r.status_code == 200
    ids = {rep["tm_user_id"] for rep in r.json()["reports"]}
    assert ids <= {actors["tm"]["user"]["id"]}, f"TM leaked other TM reports: {ids}"


def test_tm_can_add_missing_km_but_not_overwrite(actors):
    tok = actors["tm"]["token"]
    r = requests.get(f"{API}/doctors", headers=H(tok), timeout=10)
    body = r.json()
    docs = body if isinstance(body, list) else (body.get("doctors") or body.get("items") or [])
    if not docs:
        pytest.skip("no doctors")
    d = docs[0]
    # First upsert always allowed (or overwrites via SeniorTM).
    # Ensure existing then attempt TM overwrite → 403.
    stok = actors["senior"]["token"]
    requests.post(f"{API}/doctor-km", headers=H(stok), json={"doctor_id": d["id"], "km_per_visit": 22.0}, timeout=10)
    r_bad = requests.post(f"{API}/doctor-km", headers=H(tok), json={"doctor_id": d["id"], "km_per_visit": 99.0}, timeout=10)
    assert r_bad.status_code == 403, r_bad.text
