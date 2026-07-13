"""Iteration 25 retest — HIGH-priority Cyrillic PDF filename header fix.

Verifies that GET /api/reimbursement/reports/{id}/pdf now succeeds with a
Cyrillic tm_name (no more UnicodeEncodeError 500), returns application/pdf
with %PDF- magic, and Content-Disposition contains BOTH filename= (ASCII
fallback) and filename*=UTF-8'' (RFC 5987) segments.
"""
from __future__ import annotations
import os
import sys
import asyncio
from pathlib import Path
from urllib.parse import unquote

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
def report_id(tm):
    tok = tm["token"]
    # Pick or create any report we can use.
    reports = requests.get(f"{API}/reimbursement/reports", headers=H(tok), timeout=10).json()["reports"]
    if reports:
        return reports[0]["id"]
    # Fall back to generating one for last month.
    from datetime import datetime, timezone, timedelta
    d = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    m = d.strftime("%Y-%m")
    r = requests.post(f"{API}/reimbursement/reports/generate",
                      headers=H(tok), json={"month": m}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _mutate_tm_name(rid: str, new_name: str) -> str | None:
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    original = await db.reimbursement_reports.find_one({"id": rid}, {"tm_name": 1})
    await db.reimbursement_reports.update_one({"id": rid}, {"$set": {"tm_name": new_name}})
    client.close()
    return original.get("tm_name") if original else None


def test_pdf_with_cyrillic_tm_name_returns_200_and_rfc5987_header(tm, report_id):
    """Reproduces iter24 HIGH bug. tm_name=Cyrillic must NOT crash."""
    tok = tm["token"]
    original = asyncio.run(_mutate_tm_name(report_id, "Демо Пенчев"))
    try:
        r = requests.get(f"{API}/reimbursement/reports/{report_id}/pdf",
                         headers=H(tok), timeout=30)
        # 1) Status
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"
        # 2) Content-Type
        ct = r.headers.get("content-type", "")
        assert ct.startswith("application/pdf"), f"unexpected CT: {ct}"
        # 3) PDF magic bytes
        assert r.content[:4] == b"%PDF", r.content[:16]
        assert len(r.content) > 1500
        # 4) Content-Disposition has BOTH filename= and filename*=UTF-8''
        cd = r.headers.get("content-disposition", "")
        assert cd, "missing Content-Disposition header"
        assert "filename=" in cd, f"missing ASCII filename= : {cd}"
        assert "filename*=UTF-8''" in cd, f"missing RFC5987 filename*=UTF-8'' : {cd}"
        # 5) The UTF-8 star form, once percent-decoded, must contain the Cyrillic name
        star = cd.split("filename*=UTF-8''", 1)[1].strip().strip('"').rstrip(";")
        decoded = unquote(star)
        assert "Демо" in decoded and "Пенчев" in decoded, (
            f"filename* did not encode the Cyrillic name: raw={star!r} decoded={decoded!r}"
        )
        # 6) ASCII fallback filename= must not contain any non-ASCII bytes
        ascii_seg = cd.split("filename=", 1)[1].split(";", 1)[0].strip().strip('"')
        assert all(ord(c) < 128 for c in ascii_seg), f"ASCII fallback has non-ASCII: {ascii_seg!r}"
    finally:
        asyncio.run(_mutate_tm_name(report_id, original or "TM One"))


def test_pdf_with_ascii_tm_name_still_works(tm, report_id):
    """Regression: ASCII tm_name path must still return 200 + proper headers."""
    tok = tm["token"]
    original = asyncio.run(_mutate_tm_name(report_id, "TM Regression"))
    try:
        r = requests.get(f"{API}/reimbursement/reports/{report_id}/pdf",
                         headers=H(tok), timeout=30)
        assert r.status_code == 200, r.text[:400]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
        cd = r.headers.get("content-disposition", "")
        assert "filename=" in cd and "filename*=UTF-8''" in cd, cd
        # Both should encode the ASCII name
        assert "TM_Regression" in cd or "TM Regression" in cd, cd
    finally:
        asyncio.run(_mutate_tm_name(report_id, original or "TM One"))
