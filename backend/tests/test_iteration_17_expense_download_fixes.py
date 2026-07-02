"""Iteration 17 — Expense ZIP download bug fix + TM 'Download my report' feature.

Covers the review request in iteration 17:
  BUG FIX A: SeniorTM Team view: /api/expenses/receipts.zip returns 200 with
             Content-Disposition attachment; filename="expense-report_YYYY-MM.zip".
  BUG FIX B: 404 case for month=1999-01 with body {"detail":"No expenses to export"}.
  BUG FIX C: Response is application/zip AND has Content-Length header set.
  NEW FEATURE: TM (role=TM) can now call /api/expenses/receipts.zip and get
               only their own expenses (auto-scoped to tm_user_id=user.id).
  RBAC:      A TM passing ?tm_user_id=<other tm>&... still only gets their own.
  SeniorTM personal: ?personal=true forces q.tm_user_id=user.id.
  REGRESSION: SeniorTM Team view with explicit tm_user_id still filters.
"""
import io
import os
import time
import zipfile
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
assert BASE, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE}/api"

CURRENT_MONTH = datetime.now(timezone.utc).strftime("%Y-%m")
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def H(t): return {"Authorization": f"Bearer {t}"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email}: {r.text}"
    return r.json()["token"]


def _me(tok):
    r = requests.get(f"{API}/auth/me", headers=H(tok), timeout=15)
    assert r.status_code == 200
    return r.json()


# Ensure the demo seed exists.
requests.post(f"{API}/seed/init", timeout=60)

SR_TOK = _login("snr.demo.1782126329@field.io", "senior123")
SR_ME = _me(SR_TOK)
TM_TOK = _login("tm1@field.io", "tm123")
TM_ME = _me(TM_TOK)
TM2_TOK = _login("tm2@field.io", "tm123")
TM2_ME = _me(TM2_TOK)


def _seed_expense(tok, vendor):
    """Post a plain expense (no receipt) so tests don't depend on ambient state."""
    data = {
        "expense_date": TODAY, "category": "Food", "amount": "5.55",
        "vendor": vendor, "notes": "iter17",
    }
    r = requests.post(f"{API}/expenses", headers=H(tok), data=data, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["expense"]


# ============================== BUG FIX A ==============================
def test_bugfix_a_seniortm_receipts_zip_returns_200_with_content_disposition():
    _seed_expense(SR_TOK, f"iter17-a-{int(time.time())}")
    r = requests.get(
        f"{API}/expenses/receipts.zip",
        headers=H(SR_TOK), params={"month": CURRENT_MONTH}, timeout=60,
    )
    assert r.status_code == 200, r.text
    ct = r.headers.get("Content-Type", "")
    cd = r.headers.get("Content-Disposition", "")
    assert "application/zip" in ct.lower(), f"content-type: {ct}"
    assert "attachment" in cd.lower(), f"content-disposition missing attachment: {cd}"
    assert f'filename="expense-report_{CURRENT_MONTH}' in cd, cd


# ============================== BUG FIX B (404 empty month) =====================
def test_bugfix_b_empty_month_returns_404_with_json_detail():
    r = requests.get(
        f"{API}/expenses/receipts.zip",
        headers=H(SR_TOK), params={"month": "1999-01"}, timeout=20,
    )
    assert r.status_code == 404, f"expected 404 got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body.get("detail") == "No expenses to export", body


# ============================== BUG FIX C (streaming + headers) =================
def test_bugfix_c_content_type_zip_and_content_length_present():
    _seed_expense(SR_TOK, f"iter17-c-{int(time.time())}")
    r = requests.get(
        f"{API}/expenses/receipts.zip",
        headers=H(SR_TOK), params={"month": CURRENT_MONTH}, timeout=60,
    )
    assert r.status_code == 200
    assert r.headers.get("Content-Type", "").lower().startswith("application/zip")
    # StreamingResponse with explicit Content-Length header set by the router.
    assert r.headers.get("Content-Length"), "Content-Length header should be present"
    assert int(r.headers["Content-Length"]) > 0


# ============================== NEW FEATURE: TM download ====================
def test_new_feature_tm_can_download_own_report():
    _seed_expense(TM_TOK, f"iter17-tm-own-{int(time.time())}")
    r = requests.get(
        f"{API}/expenses/receipts.zip",
        headers=H(TM_TOK), params={"month": CURRENT_MONTH}, timeout=60,
    )
    assert r.status_code == 200, r.text
    assert "application/zip" in r.headers.get("Content-Type", "").lower()
    cd = r.headers.get("Content-Disposition", "")
    assert 'filename="expense-report_' in cd, cd
    # ZIP contains at least one PDF, and every PDF starts with %PDF- magic
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert names, "ZIP should contain at least one PDF"
    for n in names:
        assert n.endswith(".pdf")
        data = zf.read(n)
        assert data[:5] == b"%PDF-", f"{n} not a PDF (starts {data[:8]!r})"


# ============================== RBAC: TM cannot leak other TMs =================
def test_rbac_tm_cannot_download_another_tm_via_query_param():
    # Seed one expense for tm2, then have tm1 request tm2's data via query param.
    _seed_expense(TM2_TOK, f"iter17-tm2only-{int(time.time())}")
    _seed_expense(TM_TOK, f"iter17-tm1only-{int(time.time())}")

    r = requests.get(
        f"{API}/expenses/receipts.zip",
        headers=H(TM_TOK),
        params={"month": CURRENT_MONTH, "tm_user_id": TM2_ME["id"]},
        timeout=60,
    )
    # Must NOT return tm2's expenses. Either backend ignores the query param
    # and returns tm1's own rows (200) OR forbids it (403). Both are RBAC-safe.
    assert r.status_code in (200, 403), r.status_code
    if r.status_code == 200:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        # Filename prefix inside the ZIP is <tm_name>/... — must be tm1 only.
        tm1_name_slug = TM_ME["full_name"].replace(" ", "_")
        tm2_name_slug = TM2_ME["full_name"].replace(" ", "_")
        assert any(n.startswith(tm1_name_slug + "/") for n in names), names
        assert not any(n.startswith(tm2_name_slug + "/") for n in names), (
            f"tm1 leaked tm2's PDFs: {names}"
        )


# ============================== SeniorTM personal =============================
def test_seniortm_personal_true_scopes_to_own():
    _seed_expense(SR_TOK, f"iter17-sr-personal-{int(time.time())}")
    r = requests.get(
        f"{API}/expenses/receipts.zip",
        headers=H(SR_TOK),
        params={"month": CURRENT_MONTH, "personal": "true"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    sr_slug = SR_ME["full_name"].replace(" ", "_")
    for n in names:
        assert n.startswith(sr_slug + "/"), f"personal=true leaked non-self PDF: {n}"


# ============================== REGRESSION: per-TM filter ======================
def test_regression_seniortm_team_view_specific_tm_filter():
    # SeniorTM downloads a specific TM sub-team member? snr.demo has team_id;
    # we don't have a guaranteed sub-team TM ID here. Instead we test the
    # SeniorTM downloading themselves via the explicit tm_user_id path — the
    # backend accepts tm_user_id if it belongs to the sub-team (self is always
    # in the sub-team set).
    _seed_expense(SR_TOK, f"iter17-regression-{int(time.time())}")
    r = requests.get(
        f"{API}/expenses/receipts.zip",
        headers=H(SR_TOK),
        params={"month": CURRENT_MONTH, "tm_user_id": SR_ME["id"]},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    sr_slug = SR_ME["full_name"].replace(" ", "_")
    for n in names:
        assert n.startswith(sr_slug + "/"), f"tm_user_id filter leaked: {n}"


# ============================== CORS expose_headers ========================
def test_cors_exposes_content_disposition():
    """The whole point of the frontend fix: JS must be able to read the header."""
    _seed_expense(SR_TOK, f"iter17-cors-{int(time.time())}")
    # Simulate a browser preflight/actual: send Origin header.
    r = requests.get(
        f"{API}/expenses/receipts.zip",
        headers={**H(SR_TOK), "Origin": BASE},
        params={"month": CURRENT_MONTH}, timeout=60,
    )
    assert r.status_code == 200
    # The response must include Access-Control-Expose-Headers with Content-Disposition
    exposed = r.headers.get("Access-Control-Expose-Headers", "")
    assert "Content-Disposition" in exposed, (
        f"CORS expose_headers missing Content-Disposition: {exposed!r}"
    )
