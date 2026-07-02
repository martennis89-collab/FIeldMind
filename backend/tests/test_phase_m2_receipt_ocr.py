"""Phase M2 — OCR receipt extraction extended-category coverage.

Covers:
  1. /api/expenses accepts the M1 category set (Hotel/Parking/Tolls/Other).
  2. /api/expenses/extract returns the extended shape and accepts the new
     category_hint values.
  3. Rejects invalid categories with 400.
"""
from __future__ import annotations
import io
import os
import sys
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
    assert r.status_code == 200, f"{email} login: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def tm_token():
    return _login("tm1@field.io", "tm123")["token"]


# 1×1 transparent PNG — smallest legal image payload the endpoints will accept.
_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.parametrize("cat", ["Hotel", "Parking", "Tolls", "Other"])
def test_expense_accepts_m1_categories(tm_token, cat):
    fd = {
        "expense_date": "2025-01-15",
        "category": cat,
        "amount": "12.50",
        "vendor": f"pytest-{cat}",
    }
    r = requests.post(f"{API}/expenses", headers=H(tm_token), data=fd, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["expense"]["category"] == cat


def test_expense_rejects_unknown_category(tm_token):
    fd = {
        "expense_date": "2025-01-15",
        "category": "Spa",  # not in the whitelist
        "amount": "12.50",
    }
    r = requests.post(f"{API}/expenses", headers=H(tm_token), data=fd, timeout=10)
    assert r.status_code == 400
    assert "category" in r.json().get("detail", "").lower()


def test_extract_receipt_shape(tm_token):
    """Endpoint returns the extended shape (all keys present). No LLM call
    guarantee — an empty/1-pixel image should degrade to nulls, but the
    contract must hold."""
    files = {"receipt": ("pixel.png", io.BytesIO(_PIXEL_PNG), "image/png")}
    r = requests.post(f"{API}/expenses/extract", headers=H(tm_token), files=files, timeout=45)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "extracted" in j and "duplicate_of" in j
    ex = j["extracted"]
    for k in ("amount", "currency", "expense_date", "vendor", "category_hint", "confidence", "notes"):
        assert k in ex, f"missing key {k} in extracted payload"
    # category_hint must be null or one of the whitelisted values.
    assert ex["category_hint"] in (None, "Petrol", "Food", "Hotel", "Parking", "Tolls", "Other")
