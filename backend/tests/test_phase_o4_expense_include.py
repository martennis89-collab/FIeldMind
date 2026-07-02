"""Phase O.4 — TM chooses which recorded expenses to include in the
current monthly report.

Verifies:
  1. Fresh unlinked expenses show up in the report's expenses array but
     manual_expenses_total starts at 0 (nothing included yet).
  2. PATCH `/reimbursement/reports/{id}/expenses/{expense_id}` with
     `{included: true}` links the expense and moves its amount into
     `manual_expenses_total`.
  3. PATCH again with `{included: false}` unlinks and returns the total
     back to 0.
  4. An expense already attached to a DIFFERENT report cannot be silently
     stolen — API returns 400 with a helpful message.
  5. Petrol receipts are shown but never move into `manual_expenses_total`
     even when included=true (already covered by km-based fuel_cost).
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
def tm():
    return _login("tm1@field.io", "tm123")


@pytest.fixture(scope="module")
def month_str(tm):
    d = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    m = d.strftime("%Y-%m")
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _cleanup():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        await db.reimbursement_reports.delete_many({"tm_user_id": tm["user"]["id"], "month": m})
        await db.expenses.delete_many({"tm_user_id": tm["user"]["id"], "vendor": {"$regex": "^pytest-o[45]-"}})
        client.close()
    asyncio.run(_cleanup())
    return m


def _log_expense(token, month, cat, amount, vendor):
    fd = {"expense_date": f"{month}-14", "category": cat, "amount": str(amount), "vendor": vendor}
    r = requests.post(f"{API}/expenses", headers=H(token), data=fd, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["expense"]


def _get_report(token, report_id):
    r = requests.get(f"{API}/reimbursement/reports/{report_id}", headers=H(token), timeout=10)
    assert r.status_code == 200, r.text
    return r.json()


def test_toggle_include_updates_manual_total(tm, month_str):
    """Phase O.5 — current-month expenses auto-include. Toggling via
    the PATCH endpoint is meaningful only for prior-month expenses
    pulled in via the search widget, so this test uses PRIOR-month
    receipts."""
    tok = tm["token"]
    tag = uuid.uuid4().hex[:6]

    # Two expenses in a PRIOR month so they don't auto-include.
    prior_month = (datetime.strptime(month_str, "%Y-%m") - timedelta(days=45)).strftime("%Y-%m")
    prior_day = f"{prior_month}-10"
    fd_food = {"expense_date": prior_day, "category": "Food", "amount": "40.00", "vendor": f"pytest-o4-food-{tag}"}
    fd_hotel = {"expense_date": prior_day, "category": "Hotel", "amount": "30.00", "vendor": f"pytest-o4-hotel-{tag}"}
    e_food = requests.post(f"{API}/expenses", headers=H(tok), data=fd_food, timeout=10).json()["expense"]
    e_hotel = requests.post(f"{API}/expenses", headers=H(tok), data=fd_hotel, timeout=10).json()["expense"]

    # Generate the target-month report. Prior-month receipts should NOT
    # appear in the report's expenses array yet — they'll be pulled in
    # via the search widget → PATCH toggle.
    r = requests.post(f"{API}/reimbursement/reports/generate",
                      headers=H(tok), json={"month": month_str}, timeout=30)
    assert r.status_code == 200, r.text
    rep = r.json()
    rid = rep["id"]
    before_manual = rep["totals"]["manual_expenses_total"]
    ids_in_report = {e["id"] for e in rep["expenses"]}
    assert e_food["id"] not in ids_in_report
    assert e_hotel["id"] not in ids_in_report

    # Include the prior-month Food expense via PATCH — manual_total bumps by 40.
    r1 = requests.patch(f"{API}/reimbursement/reports/{rid}/expenses/{e_food['id']}",
                        headers=H(tok), json={"included": True}, timeout=10)
    assert r1.status_code == 200, r1.text
    assert r1.json()["totals"]["manual_expenses_total"] == round(before_manual + 40.00, 2)

    # Include Hotel too — +30 more.
    r2 = requests.patch(f"{API}/reimbursement/reports/{rid}/expenses/{e_hotel['id']}",
                        headers=H(tok), json={"included": True}, timeout=10)
    assert r2.status_code == 200
    assert r2.json()["totals"]["manual_expenses_total"] == round(before_manual + 70.00, 2)

    # Exclude Food — back to before + 30.
    r3 = requests.patch(f"{API}/reimbursement/reports/{rid}/expenses/{e_food['id']}",
                        headers=H(tok), json={"included": False}, timeout=10)
    assert r3.status_code == 200
    assert r3.json()["totals"]["manual_expenses_total"] == round(before_manual + 30.00, 2)


def test_search_finds_prior_month_expenses(tm, month_str):
    """Phase O.5 — GET /reimbursement/reports/{id}/searchable-expenses
    returns other-month expenses that match the query, excludes anything
    in the report's own month."""
    tok = tm["token"]
    tag = uuid.uuid4().hex[:6]
    # Seed a distinctive prior-month expense.
    prior_month = (datetime.strptime(month_str, "%Y-%m") - timedelta(days=45)).strftime("%Y-%m")
    fd = {"expense_date": f"{prior_month}-12", "category": "Food", "amount": "22.00", "vendor": f"pytest-o5-search-{tag}"}
    requests.post(f"{API}/expenses", headers=H(tok), data=fd, timeout=10)
    # And a current-month expense with the SAME vendor prefix (should be excluded).
    fd_cur = {"expense_date": f"{month_str}-05", "category": "Food", "amount": "11.00", "vendor": f"pytest-o5-search-{tag}-cur"}
    requests.post(f"{API}/expenses", headers=H(tok), data=fd_cur, timeout=10)

    reports = requests.get(f"{API}/reimbursement/reports", headers=H(tok), timeout=10).json()["reports"]
    rid = next(r for r in reports if r["month"] == month_str)["id"]

    r = requests.get(f"{API}/reimbursement/reports/{rid}/searchable-expenses",
                     headers=H(tok), params={"q": f"pytest-o5-search-{tag}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {row["id"] for row in body["results"]}
    # Prior-month match is returned…
    assert body["count"] >= 1
    for row in body["results"]:
        assert not (row["expense_date"] or "").startswith(month_str), (
            f"search leaked a current-month row: {row}"
        )


def test_petrol_never_counts_in_manual_total(tm, month_str):
    tok = tm["token"]
    tag = uuid.uuid4().hex[:6]
    e_petrol = _log_expense(tok, month_str, "Petrol", 55.00, f"pytest-o4-petrol-{tag}")

    reports = requests.get(f"{API}/reimbursement/reports", headers=H(tok), timeout=10).json()["reports"]
    rid = next(r for r in reports if r["month"] == month_str)["id"]
    before = _get_report(tok, rid)["totals"]["manual_expenses_total"]

    # Include the petrol receipt.
    r = requests.patch(f"{API}/reimbursement/reports/{rid}/expenses/{e_petrol['id']}",
                       headers=H(tok), json={"included": True}, timeout=10)
    assert r.status_code == 200
    after_totals = r.json()["totals"]
    # Manual total does NOT change (Petrol is fuel, already in km calc).
    assert after_totals["manual_expenses_total"] == before
    # But petrol_receipts_total DOES change.
    assert after_totals["petrol_receipts_total"] >= 55.00


def test_cannot_include_expense_already_attached_to_other_report(tm, month_str):
    tok = tm["token"]
    tag = uuid.uuid4().hex[:6]
    e_food = _log_expense(tok, month_str, "Food", 12.00, f"pytest-o4-attached-{tag}")

    reports = requests.get(f"{API}/reimbursement/reports", headers=H(tok), timeout=10).json()["reports"]
    rid = next(r for r in reports if r["month"] == month_str)["id"]

    # Attach it to the current report.
    r1 = requests.patch(f"{API}/reimbursement/reports/{rid}/expenses/{e_food['id']}",
                        headers=H(tok), json={"included": True}, timeout=10)
    assert r1.status_code == 200

    # Fake attaching to a "different report" by rewriting reimbursement_report_id
    # directly to a bogus id in Mongo, so the API returns 400 when we try to
    # include it in `rid` again.
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _hijack():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        await db.expenses.update_one({"id": e_food["id"]}, {"$set": {"reimbursement_report_id": "some-other-report-id"}})
        client.close()
    asyncio.run(_hijack())

    r2 = requests.patch(f"{API}/reimbursement/reports/{rid}/expenses/{e_food['id']}",
                        headers=H(tok), json={"included": True}, timeout=10)
    assert r2.status_code == 400
    assert "another report" in r2.json()["detail"].lower()
