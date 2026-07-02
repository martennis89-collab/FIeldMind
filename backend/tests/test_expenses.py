"""Iteration-8 backend tests: expense tracking module."""
import io
import os
import requests
from PIL import Image, ImageDraw

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _make_jpeg(text="Test receipt"):
    img = Image.new("RGB", (300, 400), color=(245, 245, 245))
    d = ImageDraw.Draw(img)
    d.text((20, 20), text, fill=(0, 0, 0))
    d.rectangle([20, 60, 280, 380], outline=(0, 0, 0))
    d.text((30, 100), "Total: USD 42.50", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return buf.getvalue()


class TestExpensesEndToEnd:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.tm2 = _login("tm2@field.io", "tm123")
        self.manager = _login("manager@field.io", "manager123")
        self.admin = _login("admin@field.io", "admin123")

    # ----- creation -----
    def test_create_expense_no_receipt(self):
        r = requests.post(f"{API}/expenses",
                          headers=H(self.tm),
                          data={"expense_date": "2026-04-10", "category": "Food", "amount": "12.5", "vendor": "Cafe"},
                          timeout=15)
        assert r.status_code == 200, r.text
        exp = r.json()["expense"]
        assert exp["category"] == "Food"
        assert exp["amount"] == 12.5
        assert exp["status"] == "Draft"
        assert exp["currency"] == "EUR"
        assert exp.get("receipt_image_id") is None

    def test_currency_is_forced_to_eur(self):
        # client tries to send a different currency — server forces EUR
        r = requests.post(f"{API}/expenses",
                          headers=H(self.tm),
                          data={"expense_date": "2026-04-10", "category": "Food", "amount": "5", "currency": "USD"},
                          timeout=10)
        assert r.status_code == 200
        assert r.json()["expense"]["currency"] == "EUR"

    def test_create_with_receipt_and_dedupe(self):
        img = _make_jpeg("Petrol")
        r1 = requests.post(f"{API}/expenses",
                           headers=H(self.tm),
                           data={"expense_date": "2026-04-11", "category": "Petrol", "amount": "30"},
                           files={"receipt": ("r.jpg", img, "image/jpeg")},
                           timeout=30)
        assert r1.status_code == 200, r1.text
        eid = r1.json()["expense"]["id"]
        # duplicate (same image bytes) → stored but flagged with a non-null duplicate_of
        r2 = requests.post(f"{API}/expenses",
                           headers=H(self.tm),
                           data={"expense_date": "2026-04-11", "category": "Petrol", "amount": "30"},
                           files={"receipt": ("r.jpg", img, "image/jpeg")},
                           timeout=30)
        assert r2.status_code == 200
        assert r2.json().get("duplicate_of") is not None

        # download receipt
        rg = requests.get(f"{API}/expenses/{eid}/receipt", headers=H(self.tm), timeout=15)
        assert rg.status_code == 200
        assert rg.headers["content-type"].startswith("image/")
        assert len(rg.content) > 100

    def test_role_restrictions_on_create(self):
        r = requests.post(f"{API}/expenses",
                          headers=H(self.manager),
                          data={"expense_date": "2026-04-10", "category": "Food", "amount": "10"},
                          timeout=10)
        assert r.status_code == 403

    def test_invalid_inputs(self):
        r = requests.post(f"{API}/expenses",
                          headers=H(self.tm),
                          data={"expense_date": "bad", "category": "Food", "amount": "1"},
                          timeout=10)
        assert r.status_code == 400
        r = requests.post(f"{API}/expenses",
                          headers=H(self.tm),
                          data={"expense_date": "2026-04-10", "category": "Travel", "amount": "1"},
                          timeout=10)
        assert r.status_code == 400
        r = requests.post(f"{API}/expenses",
                          headers=H(self.tm),
                          data={"expense_date": "2026-04-10", "category": "Food", "amount": "-5"},
                          timeout=10)
        assert r.status_code == 400

    # ----- list / summary -----
    def test_list_and_summary_scoping(self):
        # TM creates one in 2026-05
        requests.post(f"{API}/expenses",
                      headers=H(self.tm),
                      data={"expense_date": "2026-05-04", "category": "Food", "amount": "9"},
                      timeout=10)
        # TM scope
        r = requests.get(f"{API}/expenses?month=2026-05", headers=H(self.tm), timeout=10).json()
        assert all(e.get("tm_user_id") for e in r["expenses"])
        # Manager sees same team
        rm = requests.get(f"{API}/expenses?month=2026-05", headers=H(self.manager), timeout=10).json()
        assert len(rm["expenses"]) >= 1
        assert all(e.get("team_id") for e in rm["expenses"])
        # Summary
        s = requests.get(f"{API}/expenses/summary?month=2026-05", headers=H(self.tm), timeout=10).json()
        assert s["month"] == "2026-05"
        assert s["count"] >= 1
        assert s["by_status"]["Draft"] >= 1

    # ----- update / delete -----
    def test_update_only_when_draft(self):
        cr = requests.post(f"{API}/expenses",
                           headers=H(self.tm),
                           data={"expense_date": "2026-06-01", "category": "Food", "amount": "5"},
                           timeout=10).json()
        eid = cr["expense"]["id"]
        # update OK
        u = requests.put(f"{API}/expenses/{eid}", headers=H(self.tm), json={"amount": 6.5, "vendor": "Updated"}, timeout=10)
        assert u.status_code == 200, u.text
        assert u.json()["amount"] == 6.5
        # invalid category (Pydantic rejects Literal value with 422; route validates with 400)
        u2 = requests.put(f"{API}/expenses/{eid}", headers=H(self.tm), json={"category": "Travel"}, timeout=10)
        assert u2.status_code in (400, 422)
        # other TM cannot update
        ux = requests.put(f"{API}/expenses/{eid}", headers=H(self.tm2), json={"amount": 1}, timeout=10)
        assert ux.status_code == 403
        # delete OK
        d = requests.delete(f"{API}/expenses/{eid}", headers=H(self.tm), timeout=10)
        assert d.status_code == 200

    # ----- submit / approve / reject -----
    def test_submit_month_locks_drafts(self):
        # create two drafts in 2026-07
        for amt in (10, 20):
            requests.post(f"{API}/expenses", headers=H(self.tm),
                          data={"expense_date": "2026-07-15", "category": "Food", "amount": str(amt)}, timeout=10)
        s = requests.post(f"{API}/expenses/submit-month", headers=H(self.tm), json={"month": "2026-07"}, timeout=10)
        assert s.status_code == 200, s.text
        assert s.json()["submitted"] >= 2
        # Cannot edit after submit
        listed = requests.get(f"{API}/expenses?month=2026-07", headers=H(self.tm), timeout=10).json()["expenses"]
        any_submitted = next(e for e in listed if e["status"] == "Submitted")
        u = requests.put(f"{API}/expenses/{any_submitted['id']}", headers=H(self.tm), json={"amount": 99}, timeout=10)
        assert u.status_code == 409

    def test_approve_endpoint_removed(self):
        # The approve/reject endpoints are gone in this version
        cr = requests.post(f"{API}/expenses", headers=H(self.tm),
                           data={"expense_date": "2026-08-02", "category": "Petrol", "amount": "55"}, timeout=10).json()
        eid = cr["expense"]["id"]
        a = requests.post(f"{API}/expenses/{eid}/approve", headers=H(self.manager), timeout=10)
        assert a.status_code in (404, 405)
        rj = requests.post(f"{API}/expenses/{eid}/reject", headers=H(self.manager), timeout=10)
        assert rj.status_code in (404, 405)

    def test_team_summary(self):
        # Seed a couple of expenses across two TMs in the same month
        for amt in (12, 18):
            requests.post(f"{API}/expenses", headers=H(self.tm),
                          data={"expense_date": "2026-10-04", "category": "Food", "amount": str(amt)}, timeout=10)
        requests.post(f"{API}/expenses", headers=H(self.tm),
                      data={"expense_date": "2026-10-08", "category": "Petrol", "amount": "40"}, timeout=10)
        requests.post(f"{API}/expenses", headers=H(self.tm2),
                      data={"expense_date": "2026-10-08", "category": "Food", "amount": "9"}, timeout=10)

        r = requests.get(f"{API}/expenses/team-summary?month=2026-10", headers=H(self.manager), timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["month"] == "2026-10"
        assert d["currency"] == "EUR"
        assert d["count"] >= 4
        assert d["grand_total"] >= 79.0
        names = [t["tm_name"] for t in d["by_tm"]]
        assert any(n for n in names)
        # TMs cannot read team summary
        rt = requests.get(f"{API}/expenses/team-summary?month=2026-10", headers=H(self.tm), timeout=10)
        assert rt.status_code == 403

    def test_receipts_zip_download(self):
        # Two expenses with receipts in 2026-11 by tm1
        for i, vendor in enumerate(["Shell", "Cafe"]):
            img = _make_jpeg(f"Receipt {i}-{vendor}")
            requests.post(f"{API}/expenses", headers=H(self.tm),
                          data={"expense_date": "2026-11-05", "category": "Petrol" if i == 0 else "Food", "amount": str(20 + i), "vendor": vendor},
                          files={"receipt": (f"r{i}.jpg", img, "image/jpeg")},
                          timeout=30)
        r = requests.get(f"{API}/expenses/receipts.zip?month=2026-11", headers=H(self.manager), timeout=20)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        assert r.content[:2] == b"PK"   # ZIP magic bytes
        assert "attachment" in r.headers.get("content-disposition", "")
        assert len(r.content) > 500
        # 404 when no receipts
        r2 = requests.get(f"{API}/expenses/receipts.zip?month=1999-01", headers=H(self.manager), timeout=10)
        assert r2.status_code == 404
        # TM CAN access their own receipts (new feature Feb 2026 —
        # `Download my report` button). Backend auto-scopes to tm_user_id.
        r3 = requests.get(f"{API}/expenses/receipts.zip?month=2026-11", headers=H(self.tm), timeout=10)
        assert r3.status_code in (200, 404), f"TM own-report should be 200 or 404 (no data), got {r3.status_code}"

    def test_submit_month_validation(self):
        r = requests.post(f"{API}/expenses/submit-month", headers=H(self.tm),
                          json={"month": "bad"}, timeout=10)
        assert r.status_code == 400
        r = requests.post(f"{API}/expenses/submit-month", headers=H(self.manager),
                          json={"month": "2026-04"}, timeout=10)
        assert r.status_code == 403

    # ----- OCR extract endpoint (smoke; don't assert AI content) -----
    def test_extract_endpoint_smoke(self):
        img = _make_jpeg("Smoke")
        r = requests.post(f"{API}/expenses/extract",
                          headers=H(self.tm),
                          files={"receipt": ("r.jpg", img, "image/jpeg")},
                          timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "extracted" in d
        assert set(d["extracted"].keys()) >= {"amount", "currency", "expense_date", "vendor", "category_hint", "confidence"}
        # duplicate hint (None for first call)
        assert "duplicate_of" in d

    def test_extract_requires_tm(self):
        img = _make_jpeg("Manager")
        r = requests.post(f"{API}/expenses/extract",
                          headers=H(self.manager),
                          files={"receipt": ("r.jpg", img, "image/jpeg")},
                          timeout=10)
        assert r.status_code == 403
