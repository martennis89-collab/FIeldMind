"""Iteration 21 — Backend regression for:
  BUG 1: SeniorTM can PATCH their own Draft reimbursement (fuel_price_per_l).
  BUG 2: /api/expenses/receipts.zip returns valid ZIP (PK magic, application/zip,
          Content-Length>0, filename) for TM / SeniorTM (personal & sub-team) / Admin.
  FEATURE 3: DELETE /api/reimbursement/reports/{id} — owner-status matrix.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

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
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def actors():
    tm = _login("tm1@field.io", "tm123")
    senior = _login("snr.demo.1782126329@field.io", "senior123")
    admin = _login("admin@field.io", "admin123")
    owner = _login("martennis89@gmail.com", "1234")
    # Ensure tm1 reports to senior (idempotent)
    requests.put(
        f"{API}/users/{tm['user']['id']}",
        headers=H(owner["token"]),
        json={"manager_user_id": senior["user"]["id"]},
        timeout=10,
    )
    return {"tm": tm, "senior": senior, "admin": admin, "owner": owner}


@pytest.fixture(scope="module")
def last_month():
    d = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    return d.strftime("%Y-%m")


# ---------- helpers ----------
def _wipe_report(tm_user_id: str, month: str):
    """Delete any existing reimbursement_report for TM+month (idempotency)."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        await db.reimbursement_reports.delete_many({"tm_user_id": tm_user_id, "month": month})
        client.close()

    try:
        asyncio.run(_run())
    except Exception as e:
        print(f"cleanup err: {e}")


def _generate_report(token: str, month: str) -> dict:
    r = requests.post(
        f"{API}/reimbursement/reports/generate",
        headers=H(token),
        json={"month": month},
        timeout=30,
    )
    assert r.status_code == 200, f"generate: {r.status_code} {r.text}"
    return r.json()


# =========================================================
# BUG 1 — SeniorTM edits own Draft; TM regression
# =========================================================
class TestBug1SeniorTMEdit:
    def test_seniortm_can_patch_own_draft_fuel_price(self, actors, last_month):
        stok = actors["senior"]["token"]
        s_uid = actors["senior"]["user"]["id"]
        _wipe_report(s_uid, last_month)
        rep = _generate_report(stok, last_month)
        rid = rep["id"]
        assert rep["status"] == "Draft"
        assert rep["tm_user_id"] == s_uid

        r = requests.patch(
            f"{API}/reimbursement/reports/{rid}",
            headers=H(stok),
            json={"fuel_price_per_l": 1.77},
            timeout=10,
        )
        assert r.status_code == 200, f"SeniorTM own PATCH: {r.status_code} {r.text}"
        j = r.json()
        assert j["fuel_price_per_l"] == 1.77
        # GET verifies persistence
        g = requests.get(f"{API}/reimbursement/reports/{rid}", headers=H(stok), timeout=10)
        assert g.status_code == 200
        assert g.json()["fuel_price_per_l"] == 1.77

    def test_seniortm_can_patch_already_reimbursed(self, actors, last_month):
        stok = actors["senior"]["token"]
        s_uid = actors["senior"]["user"]["id"]
        # Reuse the report from previous test (or regenerate if missing)
        lst = requests.get(f"{API}/reimbursement/reports?month={last_month}", headers=H(stok), timeout=10).json()["reports"]
        mine = [r for r in lst if r["tm_user_id"] == s_uid]
        if not mine:
            rid = _generate_report(stok, last_month)["id"]
        else:
            rid = mine[0]["id"]
        r = requests.patch(
            f"{API}/reimbursement/reports/{rid}",
            headers=H(stok),
            json={"already_reimbursed": 25.0},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json()["already_reimbursed"] == 25.0

    def test_seniortm_cannot_patch_other_tm_report(self, actors, last_month):
        """SeniorTM shouldn't be able to PATCH TM's Draft using is_tm_scope path."""
        stok = actors["senior"]["token"]
        ttok = actors["tm"]["token"]
        t_uid = actors["tm"]["user"]["id"]
        _wipe_report(t_uid, last_month)
        tm_rep = _generate_report(ttok, last_month)
        rid = tm_rep["id"]
        r = requests.patch(
            f"{API}/reimbursement/reports/{rid}",
            headers=H(stok),
            json={"fuel_price_per_l": 2.0},
            timeout=10,
        )
        assert r.status_code == 403, f"SeniorTM patching TM's report: expected 403 got {r.status_code} {r.text}"

    def test_tm_regression_can_still_patch_own_draft(self, actors, last_month):
        ttok = actors["tm"]["token"]
        t_uid = actors["tm"]["user"]["id"]
        lst = requests.get(f"{API}/reimbursement/reports?month={last_month}", headers=H(ttok), timeout=10).json()["reports"]
        mine = [r for r in lst if r["tm_user_id"] == t_uid]
        if not mine:
            rid = _generate_report(ttok, last_month)["id"]
        else:
            rid = mine[0]["id"]
        r = requests.patch(
            f"{API}/reimbursement/reports/{rid}",
            headers=H(ttok),
            json={"fuel_price_per_l": 1.65},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json()["fuel_price_per_l"] == 1.65


# =========================================================
# BUG 2 — Expense receipts.zip valid ZIP for all roles
# =========================================================
class TestBug2ReceiptsZip:
    @pytest.fixture(scope="class", autouse=True)
    def _seed_expenses(self, actors, last_month):
        """Seed at least one expense for TM and SeniorTM in `last_month` so the
        receipts.zip endpoint returns 200 (it 404s on empty result-set)."""
        for who in ("tm", "senior"):
            tok = actors[who]["token"]
            files = {"receipt": ("r.jpg", b"\xff\xd8\xff\xe0seed-jpeg-bytes", "image/jpeg")}
            data = {
                "expense_date": f"{last_month}-15",
                "category": "Petrol",
                "amount": "42.10",
                "vendor": f"ZIP-SEED-{who}",
            }
            requests.post(f"{API}/expenses", headers=H(tok), files=files, data=data, timeout=20)
        return True

    def _assert_zip_response(self, r, ctx=""):
        assert r.status_code == 200, f"{ctx}: {r.status_code} {r.text[:300]}"
        ctype = r.headers.get("content-type", "")
        assert "application/zip" in ctype, f"{ctx}: bad content-type {ctype}"
        clen = r.headers.get("content-length")
        assert clen is not None and int(clen) > 0, f"{ctx}: bad content-length {clen}"
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd and "expense-report_" in cd and cd.endswith('.zip"'), (
            f"{ctx}: bad content-disposition {cd}"
        )
        assert r.content[:4] == b"PK\x03\x04", f"{ctx}: bad ZIP magic {r.content[:8]!r}"

    def test_tm_receipts_zip(self, actors, last_month):
        tok = actors["tm"]["token"]
        r = requests.get(
            f"{API}/expenses/receipts.zip?month={last_month}",
            headers=H(tok),
            timeout=60,
        )
        if r.status_code == 404:
            pytest.skip("TM has no expenses last month")
        self._assert_zip_response(r, ctx="TM")

    def test_seniortm_receipts_zip_subteam(self, actors, last_month):
        tok = actors["senior"]["token"]
        r = requests.get(
            f"{API}/expenses/receipts.zip?month={last_month}",
            headers=H(tok),
            timeout=60,
        )
        if r.status_code == 404:
            pytest.skip("SeniorTM sub-team has no expenses last month")
        self._assert_zip_response(r, ctx="SeniorTM sub-team")

    def test_seniortm_receipts_zip_personal(self, actors, last_month):
        tok = actors["senior"]["token"]
        r = requests.get(
            f"{API}/expenses/receipts.zip?personal=true&month={last_month}",
            headers=H(tok),
            timeout=60,
        )
        if r.status_code == 404:
            pytest.skip("SeniorTM has no personal expenses last month")
        self._assert_zip_response(r, ctx="SeniorTM personal")

    def test_seniortm_receipts_zip_specific_tm(self, actors, last_month):
        tok = actors["senior"]["token"]
        sub_tm_id = actors["tm"]["user"]["id"]
        r = requests.get(
            f"{API}/expenses/receipts.zip?tm_user_id={sub_tm_id}&month={last_month}",
            headers=H(tok),
            timeout=60,
        )
        if r.status_code == 404:
            pytest.skip("Sub-TM has no expenses last month")
        self._assert_zip_response(r, ctx="SeniorTM ?tm_user_id=")

    def test_admin_receipts_zip(self, actors, last_month):
        tok = actors["admin"]["token"]
        r = requests.get(
            f"{API}/expenses/receipts.zip?month={last_month}",
            headers=H(tok),
            timeout=60,
        )
        if r.status_code == 404:
            pytest.skip("No expenses last month for admin scope")
        self._assert_zip_response(r, ctx="Admin")


# =========================================================
# FEATURE 3 — DELETE reimbursement report matrix
# =========================================================
class TestFeature3DeleteReport:
    def test_tm_can_delete_own_draft(self, actors, last_month):
        ttok = actors["tm"]["token"]
        t_uid = actors["tm"]["user"]["id"]
        _wipe_report(t_uid, last_month)
        rep = _generate_report(ttok, last_month)
        rid = rep["id"]
        assert rep["status"] == "Draft"
        r = requests.delete(f"{API}/reimbursement/reports/{rid}", headers=H(ttok), timeout=15)
        assert r.status_code == 200, f"delete draft: {r.status_code} {r.text}"
        assert r.json().get("ok") is True
        # verify gone
        g = requests.get(f"{API}/reimbursement/reports/{rid}", headers=H(ttok), timeout=10)
        assert g.status_code in (403, 404), f"post-delete GET: {g.status_code}"

    def test_seniortm_can_delete_own_draft(self, actors, last_month):
        stok = actors["senior"]["token"]
        s_uid = actors["senior"]["user"]["id"]
        _wipe_report(s_uid, last_month)
        rep = _generate_report(stok, last_month)
        rid = rep["id"]
        r = requests.delete(f"{API}/reimbursement/reports/{rid}", headers=H(stok), timeout=15)
        assert r.status_code == 200, r.text

    def test_tm_cannot_delete_submitted(self, actors, last_month):
        """Set a TM report to Submitted, TM DELETE should 403."""
        ttok = actors["tm"]["token"]
        t_uid = actors["tm"]["user"]["id"]
        _wipe_report(t_uid, last_month)
        rep = _generate_report(ttok, last_month)
        rid = rep["id"]
        # Force status Submitted directly in DB (avoid full submit validation)
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient

        async def _set_submitted():
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = client[os.environ["DB_NAME"]]
            await db.reimbursement_reports.update_one({"id": rid}, {"$set": {"status": "Submitted"}})
            client.close()

        asyncio.run(_set_submitted())
        r = requests.delete(f"{API}/reimbursement/reports/{rid}", headers=H(ttok), timeout=15)
        assert r.status_code == 403, f"submitted delete by TM: {r.status_code} {r.text}"
        # Admin can delete regardless
        atok = actors["admin"]["token"]
        # Admin scope requires same company. Try admin first, else owner.
        r2 = requests.delete(f"{API}/reimbursement/reports/{rid}", headers=H(atok), timeout=15)
        if r2.status_code == 404:
            otok = actors["owner"]["token"]
            r2 = requests.delete(f"{API}/reimbursement/reports/{rid}", headers=H(otok), timeout=15)
        assert r2.status_code == 200, f"admin/owner delete submitted: {r2.status_code} {r2.text}"

    def test_owner_can_delete_any_status(self, actors, last_month):
        ttok = actors["tm"]["token"]
        otok = actors["owner"]["token"]
        t_uid = actors["tm"]["user"]["id"]
        _wipe_report(t_uid, last_month)
        rep = _generate_report(ttok, last_month)
        rid = rep["id"]
        # Force Approved
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient

        async def _set_approved():
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = client[os.environ["DB_NAME"]]
            await db.reimbursement_reports.update_one({"id": rid}, {"$set": {"status": "Approved"}})
            client.close()

        asyncio.run(_set_approved())
        r = requests.delete(f"{API}/reimbursement/reports/{rid}", headers=H(otok), timeout=15)
        assert r.status_code == 200, f"owner delete approved: {r.status_code} {r.text}"

    def test_delete_unlinks_expenses(self, actors, last_month):
        """Create a report, link an expense via DB, delete, verify expense is unlinked."""
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient

        ttok = actors["tm"]["token"]
        t_uid = actors["tm"]["user"]["id"]
        _wipe_report(t_uid, last_month)
        rep = _generate_report(ttok, last_month)
        rid = rep["id"]

        # Find an existing expense for this TM (or skip)
        async def _link_exp():
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = client[os.environ["DB_NAME"]]
            exp = await db.expenses.find_one({"tm_user_id": t_uid})
            if exp:
                await db.expenses.update_one({"id": exp["id"]}, {"$set": {"reimbursement_report_id": rid}})
                client.close()
                return exp["id"]
            client.close()
            return None

        exp_id = asyncio.run(_link_exp())
        if not exp_id:
            pytest.skip("No expense to test expense-unlink")

        r = requests.delete(f"{API}/reimbursement/reports/{rid}", headers=H(ttok), timeout=15)
        assert r.status_code == 200, r.text

        async def _check():
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = client[os.environ["DB_NAME"]]
            e = await db.expenses.find_one({"id": exp_id})
            client.close()
            return e

        e = asyncio.run(_check())
        assert e is not None, "expense should still exist"
        assert e.get("reimbursement_report_id") in (None, ""), (
            f"expense still linked: {e.get('reimbursement_report_id')}"
        )

    def test_delete_nonexistent_returns_404(self, actors):
        atok = actors["admin"]["token"]
        r = requests.delete(f"{API}/reimbursement/reports/does-not-exist-xyz", headers=H(atok), timeout=10)
        assert r.status_code == 404, f"expected 404 got {r.status_code} {r.text}"
