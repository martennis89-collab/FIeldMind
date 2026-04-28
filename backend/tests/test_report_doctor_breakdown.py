"""Iter-14 backend tests: per-doctor breakdown in weekly reports + exports."""
import os
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


class TestReportDoctorBreakdown:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")

    def test_generate_includes_doctor_breakdown(self):
        r = requests.post(f"{API}/reports/generate", headers=H(self.tm), timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        c = body.get("content", {})
        assert "doctor_breakdown" in c
        breakdown = c["doctor_breakdown"]
        assert isinstance(breakdown, list)
        # Every breakdown row must carry at least these keys
        for row in breakdown:
            assert "doctor_id" in row
            assert "doctor_name" in row
            assert "visits_count" in row
            assert "topics" in row
            assert "barriers" in row
            assert "promises" in row

    def test_csv_export_contains_per_doctor_section(self):
        # Generate then save a report
        gen = requests.post(f"{API}/reports/generate", headers=H(self.tm), timeout=20).json()
        save = requests.post(f"{API}/reports", headers=H(self.tm), json={
            "week_start": gen["week_start"],
            "week_end": gen["week_end"],
            "auto_summary": gen["auto_summary"],
            "content": gen["content"],
            "notes_from_tm": "iter14 test",
        }, timeout=15)
        assert save.status_code == 200, save.text
        report_id = save.json()["id"]
        r = requests.get(f"{API}/reports/{report_id}/export?format=csv",
                         headers=H(self.tm), timeout=15)
        assert r.status_code == 200
        body = r.content.decode("utf-8")
        assert "Per-doctor visit breakdown" in body
        # Header line must be present
        assert "Doctor" in body and "Clinic" in body and "Topics" in body and "Promises" in body

    def test_pdf_export_still_returns_pdf(self):
        gen = requests.post(f"{API}/reports/generate", headers=H(self.tm), timeout=20).json()
        save = requests.post(f"{API}/reports", headers=H(self.tm), json={
            "week_start": gen["week_start"],
            "week_end": gen["week_end"],
            "auto_summary": gen["auto_summary"],
            "content": gen["content"],
            "notes_from_tm": "iter14 pdf",
        }, timeout=15).json()
        r = requests.get(f"{API}/reports/{save['id']}/export?format=pdf",
                         headers=H(self.tm), timeout=15)
        assert r.status_code == 200
        # PDF magic bytes
        assert r.content[:4] == b"%PDF"
