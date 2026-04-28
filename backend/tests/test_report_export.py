"""Iteration-6 backend tests: weekly report PDF/CSV export."""
import os
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _ensure_saved_report(token):
    requests.post(f"{API}/seed/init", timeout=30)
    draft = requests.post(f"{API}/reports/generate", headers=_headers(token), timeout=30).json()
    saved = requests.post(f"{API}/reports", headers=_headers(token), json=draft, timeout=15).json()
    return saved["id"], saved


class TestReportExport:
    def setup_method(self):
        self.tm_token = _login("tm1@field.io", "tm123")
        self.mgr_token = _login("manager@field.io", "manager123")
        self.report_id, _ = _ensure_saved_report(self.tm_token)

    def test_export_pdf(self):
        r = requests.get(
            f"{API}/reports/{self.report_id}/export",
            params={"format": "pdf"},
            headers=_headers(self.tm_token),
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 800
        assert "attachment" in r.headers.get("content-disposition", "")

    def test_export_csv(self):
        r = requests.get(
            f"{API}/reports/{self.report_id}/export",
            params={"format": "csv"},
            headers=_headers(self.tm_token),
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/csv")
        body = r.content.decode("utf-8")
        assert "Field,Value" in body
        assert "Auto summary" in body

    def test_export_invalid_format(self):
        r = requests.get(
            f"{API}/reports/{self.report_id}/export",
            params={"format": "xml"},
            headers=_headers(self.tm_token),
            timeout=10,
        )
        assert r.status_code == 400

    def test_export_requires_auth(self):
        r = requests.get(
            f"{API}/reports/{self.report_id}/export",
            params={"format": "pdf"},
            timeout=10,
        )
        assert r.status_code == 401

    def test_manager_can_export_team_report(self):
        r = requests.get(
            f"{API}/reports/{self.report_id}/export",
            params={"format": "pdf"},
            headers=_headers(self.mgr_token),
            timeout=20,
        )
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_other_tm_forbidden(self):
        tm2 = _login("tm2@field.io", "tm123")
        r = requests.get(
            f"{API}/reports/{self.report_id}/export",
            params={"format": "pdf"},
            headers=_headers(tm2),
            timeout=10,
        )
        assert r.status_code == 403
