"""Phase O.4 supplemental: RBAC on toggle + submit validation still
requires receipts on LINKED expenses.
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
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def tm():
    return _login("tm1@field.io", "tm123")


@pytest.fixture(scope="module")
def admin():
    return _login("admin@field.io", "admin123")


@pytest.fixture(scope="module")
def month_str(tm):
    d = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    m = d.strftime("%Y-%m")
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _cleanup():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        await db.expenses.delete_many({"tm_user_id": tm["user"]["id"], "vendor": {"$regex": "^pytest-o4rbac-"}})
        await db.reimbursement_reports.delete_many({"tm_user_id": tm["user"]["id"], "month": m})
        client.close()
    asyncio.run(_cleanup())
    return m


def _log_expense(token, month, cat, amount, vendor):
    fd = {"expense_date": f"{month}-14", "category": cat, "amount": str(amount), "vendor": vendor}
    r = requests.post(f"{API}/expenses", headers=H(token), data=fd, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["expense"]


def _generate(token, month):
    r = requests.post(f"{API}/reimbursement/reports/generate", headers=H(token),
                     json={"month": month}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def test_submit_blocks_when_linked_expense_missing_receipt(tm, month_str):
    """Regression: _validate_submittable still requires receipts on LINKED expenses."""
    tok = tm["token"]
    tag = uuid.uuid4().hex[:6]
    e = _log_expense(tok, month_str, "Food", 22.00, f"pytest-o4rbac-nofile-{tag}")

    rep = _generate(tok, month_str)
    rid = rep["id"]

    # Link it (opt-in)
    r = requests.patch(f"{API}/reimbursement/reports/{rid}/expenses/{e['id']}",
                       headers=H(tok), json={"included": True}, timeout=10)
    assert r.status_code == 200

    # Ensure fuel price is set (unrelated blocker)
    requests.patch(f"{API}/reimbursement/reports/{rid}", headers=H(tok),
                   json={"fuel_price_per_l": 1.5}, timeout=10)

    # Submit — must be blocked because linked expense has no receipt.
    s = requests.post(f"{API}/reimbursement/reports/{rid}/submit", headers=H(tok), timeout=10)
    assert s.status_code == 400
    assert "no receipt" in s.json()["detail"].lower()


def test_admin_can_toggle_any_report(tm, admin, month_str):
    tok = tm["token"]
    atok = admin["token"]
    tag = uuid.uuid4().hex[:6]
    e = _log_expense(tok, month_str, "Hotel", 11.00, f"pytest-o4rbac-admin-{tag}")

    reports = requests.get(f"{API}/reimbursement/reports", headers=H(tok), timeout=10).json()["reports"]
    rid = next(r for r in reports if r["month"] == month_str)["id"]

    r = requests.patch(f"{API}/reimbursement/reports/{rid}/expenses/{e['id']}",
                       headers=H(atok), json={"included": True}, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["included_expense_count"] >= 1
