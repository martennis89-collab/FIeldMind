"""Tests: PDF export of TM weekly report — content-type and non-empty bytes."""
import os
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


class TestReportPDFExport:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.created_doctor_ids = []

    def teardown_method(self):
        for did in self.created_doctor_ids:
            try:
                requests.delete(f"{API}/doctors/{did}", headers=H(self.tm), timeout=10)
            except Exception:
                pass

    def _mk_doctor(self, name):
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": name, "clinic_name": "PDFExportClinic", "city": "Sofia",
            "doctor_type": "GP", "segment": "Active",
        }, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        self.created_doctor_ids.append(d["id"])
        return d

    def _book_demo(self, doctor_id):
        when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        r = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": doctor_id, "scheduled_at": when, "duration_minutes": 30,
            "subject": "pdf export demo test", "is_demo": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        return r.json()

    def test_pdf_export_returns_pdf_bytes(self):
        d1 = self._mk_doctor("Dr PDFExportDemo")
        self._book_demo(d1["id"])

        gen = requests.post(f"{API}/reports/generate", headers=H(self.tm), timeout=20).json()
        save = requests.post(f"{API}/reports", headers=H(self.tm), json={**gen, "status": "Draft"}, timeout=15)
        assert save.status_code == 200, save.text
        rid = save.json()["id"]

        pdf = requests.get(f"{API}/reports/{rid}/export", headers=H(self.tm),
                           params={"format": "pdf"}, timeout=20)
        assert pdf.status_code == 200, pdf.text
        ct = pdf.headers.get("content-type", "").lower()
        assert "application/pdf" in ct, f"expected pdf content-type, got {ct}"
        assert len(pdf.content) > 500, f"PDF body too small: {len(pdf.content)} bytes"
        # PDF magic header
        assert pdf.content[:4] == b"%PDF", f"not a PDF, header={pdf.content[:8]!r}"

    def test_demos_booked_list_and_completed_list_shape(self):
        """Verify response schema for demos lists."""
        d1 = self._mk_doctor("Dr PDFExportSchema")
        m = self._book_demo(d1["id"])

        r = requests.post(f"{API}/reports/generate", headers=H(self.tm), timeout=20)
        assert r.status_code == 200
        c = r.json()["content"]
        assert isinstance(c.get("demos_booked_list"), list)
        assert isinstance(c.get("demos_completed_list"), list)
        # Verify a row is present and has required keys
        row = next((x for x in c["demos_booked_list"] if x["doctor_id"] == d1["id"]), None)
        assert row is not None
        for k in ("doctor_id", "doctor_name", "scheduled_at"):
            assert k in row, f"missing key {k} in demos_booked_list row: {row}"

        # Now complete the demo and verify it appears in completed list
        comp = requests.post(f"{API}/meetings/{m['id']}/complete-demo", headers=H(self.tm),
                             json={"interest_level": "Medium", "outcome_note": "schema test"},
                             timeout=15)
        assert comp.status_code == 200, comp.text

        r2 = requests.post(f"{API}/reports/generate", headers=H(self.tm), timeout=20)
        c2 = r2.json()["content"]
        crow = next((x for x in c2["demos_completed_list"] if x["doctor_id"] == d1["id"]), None)
        assert crow is not None
        assert c2["demos_completed"] >= 1
