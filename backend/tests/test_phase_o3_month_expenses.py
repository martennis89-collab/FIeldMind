"""Phase O.3 — Reimbursement monthly report auto-includes ALL expenses
logged in the report's month (not just ones linked via
`reimbursement_report_id`), and exposes reconciliation totals:
  - petrol_receipts_total
  - expenses_recorded_total
  - variance_vs_km_fuel

User request: "monthly report should also include the recorded expenses
for that same month … and of course the calculation of total expenses
recorded for that month minus the actual recorded expense from visiting
kilometres."
"""
from __future__ import annotations
import io
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
    # Use last month.
    d = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    m = d.strftime("%Y-%m")
    # Fresh state: nuke any prior report + any pytest-tagged expenses for this month.
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _cleanup():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        await db.reimbursement_reports.delete_many({"tm_user_id": tm["user"]["id"], "month": m})
        await db.expenses.delete_many({"tm_user_id": tm["user"]["id"], "vendor": {"$regex": "^pytest-o3-"}})
        client.close()
    asyncio.run(_cleanup())
    return m


def _log_expense(token, month, cat, amount, vendor):
    day = f"{month}-15"  # inside the target month
    fd = {"expense_date": day, "category": cat, "amount": str(amount), "vendor": vendor}
    r = requests.post(f"{API}/expenses", headers=H(token), data=fd, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["expense"]


def test_report_includes_all_month_expenses_and_variance(tm, month_str):
    tok = tm["token"]

    # Log 3 expenses WITHOUT linking them to any report:
    #  - a Petrol receipt (€60)
    #  - a Food receipt (€25)
    #  - a Parking receipt (€8)
    petrol = _log_expense(tok, month_str, "Petrol", 60.00, f"pytest-o3-petrol-{uuid.uuid4().hex[:6]}")
    food = _log_expense(tok, month_str, "Food", 25.00, f"pytest-o3-food-{uuid.uuid4().hex[:6]}")
    parking = _log_expense(tok, month_str, "Parking", 8.00, f"pytest-o3-parking-{uuid.uuid4().hex[:6]}")

    # Sanity: none of these were linked to a reimbursement report.
    for e in (petrol, food, parking):
        assert not e.get("reimbursement_report_id")

    # Generate the monthly report. It must sweep in the 3 expenses above
    # even though they were never linked via reimbursement_report_id.
    r = requests.post(f"{API}/reimbursement/reports/generate",
                      headers=H(tok), json={"month": month_str}, timeout=30)
    assert r.status_code == 200, r.text
    rep = r.json()
    report_id = rep["id"]

    expenses = rep.get("expenses", [])
    vendor_names = {e.get("vendor") for e in expenses}
    for target in (petrol, food, parking):
        assert target["vendor"] in vendor_names, (
            f"expected vendor {target['vendor']!r} in report expenses, got {vendor_names}"
        )

    totals = rep["totals"]
    # New reconciliation fields
    assert "petrol_receipts_total" in totals
    assert "expenses_recorded_total" in totals
    assert "variance_vs_km_fuel" in totals

    # Numeric assertions
    assert totals["petrol_receipts_total"] >= 60.00
    # Non-fuel manual total should include food+parking (33.00 minimum)
    assert totals["manual_expenses_total"] >= 33.00
    # All recorded = petrol + non-fuel
    assert abs(totals["expenses_recorded_total"] - (totals["petrol_receipts_total"] + totals["manual_expenses_total"])) < 0.01

    # Variance is null until a fuel_price is set (fuel_cost is None otherwise).
    if totals.get("fuel_cost") is None:
        assert totals["variance_vs_km_fuel"] is None
    else:
        assert totals["variance_vs_km_fuel"] == round(totals["expenses_recorded_total"] - totals["fuel_cost"], 2)

    # Set a fuel price so fuel_cost is computed, then re-verify variance.
    requests.patch(f"{API}/reimbursement/reports/{report_id}",
                   headers=H(tok), json={"fuel_price_per_l": 1.80}, timeout=10)
    r2 = requests.get(f"{API}/reimbursement/reports/{report_id}", headers=H(tok), timeout=10)
    assert r2.status_code == 200
    t2 = r2.json()["totals"]
    assert t2["fuel_cost"] is not None
    assert t2["variance_vs_km_fuel"] == round(t2["expenses_recorded_total"] - t2["fuel_cost"], 2)


def test_expenses_outside_month_are_excluded(tm, month_str):
    tok = tm["token"]
    # Log an expense in a DIFFERENT month.
    other_month_day = f"{(datetime.strptime(month_str, '%Y-%m') - timedelta(days=45)).strftime('%Y-%m-%d')}"
    tag = uuid.uuid4().hex[:6]
    fd = {"expense_date": other_month_day, "category": "Food", "amount": "99.00", "vendor": f"pytest-o3-food-outside-{tag}"}
    r = requests.post(f"{API}/expenses", headers=H(tok), data=fd, timeout=10)
    assert r.status_code == 200, r.text

    # Fetch the report; the out-of-month expense must NOT appear.
    reports = requests.get(f"{API}/reimbursement/reports", headers=H(tok), timeout=10).json()["reports"]
    ours = next((rr for rr in reports if rr["month"] == month_str), None)
    assert ours is not None
    detail = requests.get(f"{API}/reimbursement/reports/{ours['id']}", headers=H(tok), timeout=10).json()
    vendors = {e.get("vendor") for e in detail["expenses"]}
    assert f"pytest-o3-food-outside-{tag}" not in vendors, "out-of-month expense leaked into the monthly report"
