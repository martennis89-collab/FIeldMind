"""Iteration 16 — SeniorTM expenses bug fixes.

Covers:
  BUG 1: Senior TM should see sub-team TM expenses in team-summary and /api/expenses list.
  BUG 2: Senior TM should be able to POST /api/expenses (Draft) and submit-month.
  BUG 3: /api/expenses/receipts.zip returns ZIP of PDF-per-expense with embedded receipt image.
  Regressions: Manager team-summary + receipts.zip, plain TM own-only expenses.
"""
import io
import os
import uuid
import zipfile
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
assert BASE, "REACT_APP_BACKEND_URL must be set (frontend/.env)"
API = f"{BASE}/api"

CURRENT_MONTH = datetime.now(timezone.utc).strftime("%Y-%m")
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email} failed: {r.text}"
    return r.json()["token"]


def _seed():
    requests.post(f"{API}/seed/init", timeout=60)


def _me(tok):
    r = requests.get(f"{API}/auth/me", headers=H(tok), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _create_user(admin_tok, role, full_name, team_id=None, manager_user_id=None):
    email = f"{full_name.lower().replace(' ', '.')}.{uuid.uuid4().hex[:6]}@iter16.example.com"
    body = {
        "full_name": full_name, "email": email, "password": "iter16-pass",
        "role": role, "team_id": team_id, "manager_user_id": manager_user_id,
    }
    r = requests.post(f"{API}/users", headers=H(admin_tok), json=body, timeout=20)
    assert r.status_code == 200, r.text
    tok = _login(email, "iter16-pass")
    return r.json(), tok


# 20x20 red PNG (valid, decodable by PIL/reportlab)
PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000001400000014080200000002eb8a5a"
    "0000001b49444154789c63fccf403e60a240efa8e651cda39a473553413300229c"
    "01273584d09e0000000049454e44ae426082"
)


def _post_expense(tok, amount=12.34, with_receipt=True, category="Petrol", vendor="TestVendor"):
    files = {}
    if with_receipt:
        files["receipt"] = ("r.png", io.BytesIO(PNG_1x1), "image/png")
    data = {
        "expense_date": TODAY, "category": category,
        "amount": str(amount), "vendor": vendor, "notes": "iter16",
    }
    r = requests.post(f"{API}/expenses", headers=H(tok), data=data,
                      files=files or None, timeout=30)
    return r


# --- Fixture-ish shared setup at module level ---
_seed()
ADMIN = _login("admin@field.io", "admin123")
SR_TOK = _login("snr.demo.1782126329@field.io", "senior123")
SR_ME = _me(SR_TOK)
SR_ID = SR_ME["id"]
SR_TEAM = SR_ME.get("team_id")

# Create a fresh TM whose manager_user_id == SeniorTM (this reproduces BUG 1).
SUBTEAM_TM, SUBTEAM_TM_TOK = _create_user(
    ADMIN, "TM", "Iter16 SubteamTM",
    team_id=SR_TEAM, manager_user_id=SR_ID,
)


# ============================== BUG 1 ==============================
def test_bug1_seniortm_sees_subteam_tm_expense_in_team_summary():
    r = _post_expense(SUBTEAM_TM_TOK, amount=42.0, vendor="SubteamTM-Vendor")
    assert r.status_code == 200, r.text

    # SeniorTM team-summary should include the sub-team TM
    ts = requests.get(f"{API}/expenses/team-summary",
                      headers=H(SR_TOK), params={"month": CURRENT_MONTH}, timeout=20)
    assert ts.status_code == 200, ts.text
    body = ts.json()
    tm_ids = [row["tm_user_id"] for row in body.get("by_tm", [])]
    assert SUBTEAM_TM["id"] in tm_ids, f"sub-team TM missing from team-summary: {tm_ids}"
    assert body["grand_total"] > 0


def test_bug1_seniortm_list_default_scope_includes_subteam_and_self():
    # SeniorTM also posts one of their own
    r = _post_expense(SR_TOK, amount=7.5, vendor="SR-Own-Vendor")
    assert r.status_code == 200, r.text
    lst = requests.get(f"{API}/expenses",
                       headers=H(SR_TOK), params={"month": CURRENT_MONTH}, timeout=20)
    assert lst.status_code == 200, lst.text
    tm_ids = {row["tm_user_id"] for row in lst.json()["expenses"]}
    assert SR_ID in tm_ids, "SeniorTM own id missing from default scope"
    assert SUBTEAM_TM["id"] in tm_ids, "Subteam TM missing from default scope"


def test_bug1_seniortm_list_personal_only_returns_self():
    lst = requests.get(f"{API}/expenses",
                       headers=H(SR_TOK),
                       params={"month": CURRENT_MONTH, "personal": "true"},
                       timeout=20)
    assert lst.status_code == 200, lst.text
    tm_ids = {row["tm_user_id"] for row in lst.json()["expenses"]}
    assert tm_ids <= {SR_ID}, f"personal=true leaked others: {tm_ids}"


# ============================== BUG 2 ==============================
def test_bug2_seniortm_can_post_expense_draft():
    r = _post_expense(SR_TOK, amount=15.0, vendor="SR-Bug2")
    assert r.status_code == 200, r.text
    exp = r.json()["expense"]
    assert exp["status"] == "Draft"
    assert exp["tm_user_id"] == SR_ID
    assert exp["amount"] == 15.0


def test_bug2_seniortm_can_submit_month():
    # Ensure at least one draft exists
    _post_expense(SR_TOK, amount=3.14, vendor="SR-Submit")
    r = requests.post(f"{API}/expenses/submit-month",
                      headers=H(SR_TOK), json={"month": CURRENT_MONTH}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["submitted"] >= 1


# ============================== BUG 3 ==============================
def test_bug3_receipts_zip_is_pdf_per_expense():
    r = requests.get(f"{API}/expenses/receipts.zip",
                     headers=H(SR_TOK), params={"month": CURRENT_MONTH}, timeout=60)
    assert r.status_code == 200, r.text
    ct = r.headers.get("Content-Type", "")
    cd = r.headers.get("Content-Disposition", "")
    assert "application/zip" in ct, f"wrong content-type: {ct}"
    assert "expense-report_" in cd, f"wrong filename: {cd}"

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert len(names) >= 1
    all_sizes = []
    for name in names:
        assert name.endswith(".pdf"), f"non-pdf in zip: {name}"
        data = zf.read(name)
        assert data[:5] == b"%PDF-", f"not a PDF: {name} starts with {data[:8]!r}"
        all_sizes.append(len(data))
    baseline_max = max(all_sizes)

    # Verify separately with a REAL sized phone-camera-ish image that PDFs
    # materially grow when the image is embedded (BUG 3 acceptance criterion).
    from PIL import Image as _PIL
    big = io.BytesIO()
    _PIL.new("RGB", (800, 800), color="blue").save(big, format="JPEG")
    files = {"receipt": ("big.jpg", big.getvalue(), "image/jpeg")}
    rp = requests.post(f"{API}/expenses", headers=H(SR_TOK), files=files, data={
        "expense_date": TODAY, "category": "Food", "amount": "9.99",
        "vendor": "Iter16-BigImg", "notes": "iter16",
    }, timeout=30)
    assert rp.status_code == 200, rp.text
    r2 = requests.get(f"{API}/expenses/receipts.zip",
                      headers=H(SR_TOK), params={"month": CURRENT_MONTH}, timeout=60)
    assert r2.status_code == 200
    zf2 = zipfile.ZipFile(io.BytesIO(r2.content))
    big_pdf = [zf2.read(n) for n in zf2.namelist() if "BigImg" in n]
    assert big_pdf, "big-image PDF not in ZIP"
    assert len(big_pdf[0]) > baseline_max, (
        f"PDF with embedded phone image ({len(big_pdf[0])}) is not materially "
        f"larger than metadata-only PDFs (max was {baseline_max})"
    )


# ============================== REGRESSION ==============================
def test_regression_manager_team_summary_and_receipts_zip():
    mgr_tok = _login("manager@field.io", "manager123")
    ts = requests.get(f"{API}/expenses/team-summary",
                      headers=H(mgr_tok), params={"month": CURRENT_MONTH}, timeout=20)
    assert ts.status_code == 200
    # Manager can call receipts.zip (may 404 if no team expenses this month — accept both)
    zr = requests.get(f"{API}/expenses/receipts.zip",
                      headers=H(mgr_tok), params={"month": CURRENT_MONTH}, timeout=60)
    assert zr.status_code in (200, 404), zr.text
    if zr.status_code == 200:
        assert "application/zip" in zr.headers.get("Content-Type", "")
        zf = zipfile.ZipFile(io.BytesIO(zr.content))
        for name in zf.namelist():
            assert name.endswith(".pdf")


def test_regression_plain_tm_only_sees_own_expenses():
    tm_tok = _login("tm1@field.io", "tm123")
    tm_me = _me(tm_tok)
    # Ensure a draft
    _post_expense(tm_tok, amount=2.22, vendor="RegressTM")
    lst = requests.get(f"{API}/expenses",
                       headers=H(tm_tok), params={"month": CURRENT_MONTH}, timeout=20)
    assert lst.status_code == 200
    tm_ids = {row["tm_user_id"] for row in lst.json()["expenses"]}
    assert tm_ids <= {tm_me["id"]}, f"TM sees others' expenses: {tm_ids}"
    # Submit-month still works
    r = requests.post(f"{API}/expenses/submit-month",
                      headers=H(tm_tok), json={"month": CURRENT_MONTH}, timeout=20)
    assert r.status_code == 200
