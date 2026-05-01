"""Tests: TM weekly report correctly aggregates iTero demos (booked + completed)."""
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


def _future_iso(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class TestReportDemos:
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
            "doctor_name": name,
            "clinic_name": "ReportDemoClinic", "city": "Sofia",
            "doctor_type": "GP", "segment": "Active",
        }, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        self.created_doctor_ids.append(d["id"])
        return d

    def _book_demo(self, doctor_id, when):
        r = requests.post(f"{API}/meetings", headers=H(self.tm), json={
            "doctor_id": doctor_id,
            "scheduled_at": when,
            "duration_minutes": 30,
            "subject": "report-demo test",
            "is_demo": True,
        }, timeout=15)
        assert r.status_code == 200, r.text
        return r.json()

    def test_weekly_report_counts_booked_demos_from_meetings(self):
        d1 = self._mk_doctor("Dr ReportDemo_BookOnly")
        self._book_demo(d1["id"], _future_iso(2))

        r = requests.post(f"{API}/reports/generate", headers=H(self.tm), timeout=20)
        assert r.status_code == 200, r.text
        draft = r.json()
        c = draft["content"]
        assert c["demos_booked"] >= 1, f"expected demos_booked>=1, got {c['demos_booked']}"
        # The booked list must include our doctor
        booked_ids = [x["doctor_id"] for x in (c.get("demos_booked_list") or [])]
        assert d1["id"] in booked_ids
        # Per-doctor breakdown has a row for that doctor with demos_booked_count>=1
        row = next((x for x in c["doctor_breakdown"] if x["doctor_id"] == d1["id"]), None)
        assert row is not None, "doctor_breakdown should include doctor with booked demo even without a visit"
        assert row["demos_booked_count"] >= 1

    def test_weekly_report_counts_completed_demos_from_meetings(self):
        d1 = self._mk_doctor("Dr ReportDemo_Completed")
        m = self._book_demo(d1["id"], _future_iso(1))
        # Complete the demo
        comp = requests.post(f"{API}/meetings/{m['id']}/complete-demo", headers=H(self.tm),
                             json={"interest_level": "High", "outcome_note": "test complete"}, timeout=15)
        assert comp.status_code == 200, comp.text

        r = requests.post(f"{API}/reports/generate", headers=H(self.tm), timeout=20)
        assert r.status_code == 200, r.text
        c = r.json()["content"]
        assert c["demos_completed"] >= 1, f"expected demos_completed>=1, got {c['demos_completed']}"
        completed_ids = [x["doctor_id"] for x in (c.get("demos_completed_list") or [])]
        assert d1["id"] in completed_ids
        row = next((x for x in c["doctor_breakdown"] if x["doctor_id"] == d1["id"]), None)
        assert row is not None
        assert row["demos_completed_count"] >= 1

    def test_weekly_report_csv_export_contains_demo_rows(self):
        d1 = self._mk_doctor("Dr ReportDemo_CSV")
        self._book_demo(d1["id"], _future_iso(4))

        # Save the report first to get a report id
        gen = requests.post(f"{API}/reports/generate", headers=H(self.tm), timeout=20).json()
        save = requests.post(f"{API}/reports", headers=H(self.tm), json={
            **gen, "status": "Draft"
        }, timeout=15)
        assert save.status_code == 200, save.text
        rid = save.json()["id"]

        csv_r = requests.get(f"{API}/reports/{rid}/export", headers=H(self.tm),
                             params={"format": "csv"}, timeout=15)
        assert csv_r.status_code == 200
        body = csv_r.text
        assert "iTero demos booked this week" in body
        assert "Dr ReportDemo_CSV" in body
