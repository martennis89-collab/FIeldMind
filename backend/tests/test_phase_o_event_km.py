"""Phase O — Event KM in monthly reimbursement report.

Verifies:
  1. A TM's events inside the target month appear in `event_breakdown`.
  2. Missing event KM blocks submission with a clear 400.
  3. Setting event.km via PUT /events/{id} and refreshing the report bumps
     total_km and moves the row to Matched.
"""
from __future__ import annotations
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv("/app/frontend/.env")
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=10)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def tm_token():
    return _login("tm1@field.io", "tm123")["token"]


@pytest.fixture(scope="module")
def month_str():
    # Use last month.
    d = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    m = d.strftime("%Y-%m")
    # Wipe any pre-existing reimbursement report + events for this month so
    # the test is idempotent across runs.
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    tm_user = _login("tm1@field.io", "tm123")["user"]

    async def _cleanup():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        await db.reimbursement_reports.delete_many({"tm_user_id": tm_user["id"], "month": m})
        # Delete pytest-seeded events for this month.
        await db.events.delete_many({"tm_user_id": tm_user["id"], "title": {"$regex": "^pytest-event-"}})
        client.close()
    try:
        asyncio.run(_cleanup())
    except Exception:
        pass
    return m


def test_event_km_flow(tm_token, month_str):
    # 1) TM logs one event inside the target month, no km supplied yet.
    tag = uuid.uuid4().hex[:6]
    r_ev = requests.post(f"{API}/events", headers=H(tm_token), json={
        "title": f"pytest-event-{tag}",
        "scheduled_at": f"{month_str}-14T09:00:00Z",
        "duration_minutes": 120,
        "location": "Sofia Tech Park",
    }, timeout=10)
    assert r_ev.status_code == 200, r_ev.text
    event_id = r_ev.json()["id"]

    # 2) Generate the reimbursement report — event should appear in breakdown as MissingKM.
    r_gen = requests.post(f"{API}/reimbursement/reports/generate", headers=H(tm_token),
                          json={"month": month_str}, timeout=30)
    assert r_gen.status_code == 200, r_gen.text
    rep = r_gen.json()
    report_id = rep["id"]
    events = rep.get("event_breakdown", [])
    ours = next((e for e in events if e["event_id"] == event_id), None)
    assert ours is not None, f"event {event_id} not in event_breakdown: {events}"
    assert ours["match_status"] == "MissingKM"
    assert ours["km"] is None

    # 3) Fill in fuel price + doctor KM if any missing (to isolate event-km validation).
    for d in rep.get("doctor_breakdown", []):
        if d["match_status"] == "MissingKM":
            requests.post(f"{API}/doctor-km", headers=H(tm_token),
                          json={"doctor_id": d["doctor_id"], "km_per_visit": 10.0}, timeout=10)
    requests.patch(f"{API}/reimbursement/reports/{report_id}", headers=H(tm_token),
                   json={"fuel_price_per_l": 1.90}, timeout=10)

    # 4) Submit MUST 400 because event KM is missing.
    r_bad = requests.post(f"{API}/reimbursement/reports/{report_id}/submit", headers=H(tm_token), timeout=10)
    assert r_bad.status_code == 400, r_bad.text
    assert "event" in r_bad.json()["detail"].lower()

    # 5) Set the event km via PUT /events/{id}.
    r_upd = requests.put(f"{API}/events/{event_id}", headers=H(tm_token),
                         json={"km": 47.5}, timeout=10)
    assert r_upd.status_code == 200, r_upd.text
    assert r_upd.json()["km"] == 47.5

    # 6) Refresh breakdown — event now Matched, total_km includes 47.5.
    r_ref = requests.post(f"{API}/reimbursement/reports/{report_id}/refresh-breakdown",
                          headers=H(tm_token), timeout=10)
    assert r_ref.status_code == 200
    refreshed = r_ref.json()
    ours2 = next((e for e in refreshed["event_breakdown"] if e["event_id"] == event_id), None)
    assert ours2 is not None and ours2["match_status"] == "Matched"
    assert ours2["km"] == 47.5
    assert refreshed["events_total_km"] >= 47.5
    assert refreshed["total_km"] == round(refreshed["doctor_total_km"] + refreshed["events_total_km"], 2)

    # 7) Submit now succeeds.
    r_ok = requests.post(f"{API}/reimbursement/reports/{report_id}/submit", headers=H(tm_token), timeout=10)
    assert r_ok.status_code == 200, r_ok.text
    assert r_ok.json()["status"] == "Submitted"
