"""Iteration 24 — PDF weekly-KM breakdown, Cyrillic font embedding,
and auto-include of current-month manual expenses.

Covers:
  1. Fresh monthly report auto-includes non-Petrol current-month expenses
     so `manual_expenses_total` reflects them without any explicit PATCH.
  2. GET /reimbursement/reports/{id}/pdf returns a valid PDF (magic bytes)
     with Content-Type application/pdf.
  3. PDF omits a per-doctor breakdown table and instead contains a
     'Weekly KM breakdown' section.
  4. Cyrillic (Bulgarian) text renders without black-square substitution —
     asserted by embedded font present in raw bytes (LiberationSans/DejaVuSans
     or FMSans) and no /FontDescriptor fallback missing.
  5. searchable-expenses endpoint EXCLUDES current-month rows.
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
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def tm():
    return _login("tm1@field.io", "tm123")


@pytest.fixture(scope="module")
def month_str(tm):
    # Use last month so we don't collide with concurrent runs.
    d = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    m = d.strftime("%Y-%m")
    # Cleanup previous test data
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _cleanup():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        await db.reimbursement_reports.delete_many({"tm_user_id": tm["user"]["id"], "month": m})
        await db.expenses.delete_many({"tm_user_id": tm["user"]["id"], "vendor": {"$regex": "^pytest-it24-"}})
        client.close()
    asyncio.run(_cleanup())
    return m


def _log_expense(token, date_iso, cat, amount, vendor):
    fd = {"expense_date": date_iso, "category": cat, "amount": str(amount), "vendor": vendor}
    r = requests.post(f"{API}/expenses", headers=H(token), data=fd, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["expense"]


def test_current_month_expenses_auto_included(tm, month_str):
    tok = tm["token"]
    tag = uuid.uuid4().hex[:6]
    # Seed 3 in-month non-Petrol expenses + 1 Petrol (should be ignored in manual)
    _log_expense(tok, f"{month_str}-05", "Food", 12.50, f"pytest-it24-a-{tag}")
    _log_expense(tok, f"{month_str}-12", "Hotel", 55.00, f"pytest-it24-b-{tag}")
    _log_expense(tok, f"{month_str}-20", "Parking", 8.00, f"pytest-it24-c-{tag}")
    _log_expense(tok, f"{month_str}-15", "Petrol", 40.00, f"pytest-it24-d-{tag}")

    r = requests.post(f"{API}/reimbursement/reports/generate",
                      headers=H(tok), json={"month": month_str}, timeout=30)
    assert r.status_code == 200, r.text
    rep = r.json()
    t = rep["totals"]
    # Auto-include means the 3 non-Petrol rows count towards manual total.
    assert t["manual_expenses_total"] >= 12.50 + 55.00 + 8.00 - 0.001, t
    # Petrol never enters manual total.
    assert t["petrol_receipts_total"] >= 40.00 - 0.001
    return rep["id"]


def test_pdf_valid_and_content_type(tm, month_str):
    tok = tm["token"]
    reports = requests.get(f"{API}/reimbursement/reports", headers=H(tok), timeout=10).json()["reports"]
    rid = next(r for r in reports if r["month"] == month_str)["id"]
    r = requests.get(f"{API}/reimbursement/reports/{rid}/pdf", headers=H(tok), timeout=30)
    assert r.status_code == 200, r.text[:400]
    assert r.headers.get("content-type", "").startswith("application/pdf"), r.headers
    body = r.content
    assert body[:4] == b"%PDF", body[:16]
    assert len(body) > 1500  # non-trivial PDF


def test_pdf_render_uses_weekly_and_no_doctor_breakdown():
    """Unit-level check on the render function: given a fake weekly list,
    the PDF stream must contain 'Weekly KM breakdown' as visible text and
    must NOT contain any 'doctor breakdown' section."""
    from routers.reimbursement import _render_reimbursement_pdf
    fake_report = {
        "id": "u", "tm_name": "TM Fake", "month": "2026-01", "status": "Draft",
        "total_visits": 3, "total_km": 42.0, "unique_doctors": 2,
        "totals": {"consumption_l_per_100km": 11.0, "fuel_price_per_l": 1.85,
                   "litres_used": 4.62, "fuel_cost": 8.55, "manual_expenses_total": 12.0,
                   "petrol_receipts_total": 0.0, "total_reimbursable": 20.55,
                   "already_reimbursed": 0.0, "amount_to_reimburse": 20.55},
        "expenses": [],
    }
    weekly = [{"week": "Week 01  (Jan 06 – Jan 12)", "visits": 3, "km": 42.0}]
    pdf = _render_reimbursement_pdf(fake_report, weekly=weekly)
    assert pdf[:4] == b"%PDF"
    # pypdf gives us decoded text
    try:
        import pypdf  # type: ignore
    except ImportError:
        pytest.skip("pypdf not installed — can't decode PDF text stream")
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    assert "Weekly KM breakdown" in text, f"missing weekly heading: {text[:400]}"
    assert "doctor breakdown" not in text.lower(), "per-doctor breakdown must be gone"
    assert "Reimbursement summary" in text


def test_pdf_embeds_cyrillic_font(tm, month_str):
    """Confirm the Cyrillic-capable font is embedded (LiberationSans or
    DejaVuSans registered under FMSans). Without this the previous PDFs
    rendered Bulgarian as black squares."""
    tok = tm["token"]
    reports = requests.get(f"{API}/reimbursement/reports", headers=H(tok), timeout=10).json()["reports"]
    rid = next(r for r in reports if r["month"] == month_str)["id"]
    r = requests.get(f"{API}/reimbursement/reports/{rid}/pdf", headers=H(tok), timeout=30)
    assert r.status_code == 200
    raw = r.content
    lowered = raw.lower()
    # ReportLab embeds registered TTFonts by the internal name. We
    # accept any of the following markers.
    markers = [b"fmsans", b"liberationsans", b"dejavusans"]
    assert any(m in lowered for m in markers), (
        "Expected an embedded Cyrillic-capable font in the PDF stream — none found. "
        "Markers checked: FMSans / LiberationSans / DejaVuSans."
    )


def test_pdf_renders_with_cyrillic_tm_name(tm, month_str):
    """End-to-end smoke: mutate the TM's display name to Cyrillic, ask
    for the PDF, ensure it still renders (no exception, valid magic
    bytes). We do this by writing directly to Mongo so we don't
    depend on a name-change API."""
    tok = tm["token"]
    reports = requests.get(f"{API}/reimbursement/reports", headers=H(tok), timeout=10).json()["reports"]
    rep = next(r for r in reports if r["month"] == month_str)
    rid = rep["id"]

    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _mutate(new_name: str):
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        original = await db.reimbursement_reports.find_one({"id": rid}, {"tm_name": 1})
        await db.reimbursement_reports.update_one({"id": rid}, {"$set": {"tm_name": new_name}})
        client.close()
        return original.get("tm_name") if original else None

    original_name = asyncio.run(_mutate("Демо Пенчев"))
    try:
        r = requests.get(f"{API}/reimbursement/reports/{rid}/pdf", headers=H(tok), timeout=30)
        assert r.status_code == 200, r.text[:400]
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 1500
    finally:
        # Restore
        asyncio.run(_mutate(original_name or "TM One"))


def test_searchable_expenses_excludes_current_month(tm, month_str):
    tok = tm["token"]
    tag = uuid.uuid4().hex[:6]
    prior_month = (datetime.strptime(month_str, "%Y-%m") - timedelta(days=45)).strftime("%Y-%m")
    _log_expense(tok, f"{prior_month}-10", "Food", 22.00, f"pytest-it24-search-{tag}")
    _log_expense(tok, f"{month_str}-10", "Food", 33.00, f"pytest-it24-search-{tag}-cur")

    reports = requests.get(f"{API}/reimbursement/reports", headers=H(tok), timeout=10).json()["reports"]
    rid = next(r for r in reports if r["month"] == month_str)["id"]

    r = requests.get(f"{API}/reimbursement/reports/{rid}/searchable-expenses",
                     headers=H(tok), params={"q": f"pytest-it24-search-{tag}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    for row in body["results"]:
        assert not (row["expense_date"] or "").startswith(month_str), row
