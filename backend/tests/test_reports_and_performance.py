"""Backend tests for Iteration-2 additions:
- /api/dashboard/manager/performance
- /api/reports/* (generate, create, update, submit, comment, list buckets)
"""
import os
import requests
import pytest

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "admin": ("admin@field.io", "admin123"),
    "manager": ("manager@field.io", "manager123"),
    "tm1": ("tm1@field.io", "tm123"),
    "tm2": ("tm2@field.io", "tm123"),
}


@pytest.fixture(scope="module")
def tokens():
    requests.post(f"{API}/seed/init", timeout=20)
    out = {}
    for k, (e, p) in CREDS.items():
        r = requests.post(f"{API}/auth/login", json={"email": e, "password": p}, timeout=15)
        assert r.status_code == 200, f"login {k} -> {r.status_code} {r.text}"
        out[k] = r.json()["token"]
    return out


def H(t):
    return {"Authorization": f"Bearer {t}"}


# ========= Manager performance =========
class TestManagerPerformance:
    EXPECTED_FIELDS = [
        "tm_id", "visits_month", "visits_target_month", "visits_vs_target",
        "avg_visits_per_day", "overdue_count", "completion_rate",
        "promises_total_30d", "promises_completed_30d",
        "high_priority_unvisited", "high_priority_unvisited_doctors",
        "sentiment_recent", "sentiment_prev", "sentiment_trend",
        "pct_visits_to_low_value", "flags", "insights",
    ]

    def test_manager_sees_team(self, tokens):
        r = requests.get(f"{API}/dashboard/manager/performance", headers=H(tokens["manager"]), timeout=20)
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        assert isinstance(rows, list) and len(rows) >= 1
        for row in rows:
            for f in self.EXPECTED_FIELDS:
                assert f in row, f"missing {f}"
            assert isinstance(row["high_priority_unvisited_doctors"], list)
            for fl in row["flags"]:
                for k in ["key", "severity", "label", "detail"]:
                    assert k in fl
            for ins in row["insights"]:
                for k in ["kind", "label", "detail"]:
                    assert k in ins

    def test_admin_sees_all(self, tokens):
        r = requests.get(f"{API}/dashboard/manager/performance", headers=H(tokens["admin"]), timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json()["rows"], list)

    def test_tm_forbidden(self, tokens):
        r = requests.get(f"{API}/dashboard/manager/performance", headers=H(tokens["tm1"]), timeout=10)
        assert r.status_code == 403


# ========= Reports =========
class TestReportGenerate:
    def test_tm_generate_draft_shape(self, tokens):
        r = requests.post(f"{API}/reports/generate", headers=H(tokens["tm1"]), timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["tm_user_id", "week_start", "week_end", "auto_summary", "content"]:
            assert k in d
        assert isinstance(d["auto_summary"], str) and len(d["auto_summary"]) > 0
        c = d["content"]
        for k in ["visits_completed", "doctors_visited", "topics_discussed",
                  "barriers_heard", "promises_created", "promises_completed",
                  "overdue_promises", "sentiment_summary", "key_insights",
                  "doctors_needing_attention"]:
            assert k in c, f"missing content field {k}"

    def test_manager_cannot_generate(self, tokens):
        r = requests.post(f"{API}/reports/generate", headers=H(tokens["manager"]), timeout=10)
        assert r.status_code == 403


def _draft_payload(tokens, who="tm1"):
    g = requests.post(f"{API}/reports/generate", headers=H(tokens[who]), timeout=20).json()
    return {
        "week_start": g["week_start"],
        "week_end": g["week_end"],
        "auto_summary": g["auto_summary"],
        "content": g["content"],
        "notes_from_tm": "",
    }


class TestReportCRUDFlow:
    def test_full_flow(self, tokens):
        # 1) Create draft
        payload = _draft_payload(tokens, "tm1")
        r = requests.post(f"{API}/reports", headers=H(tokens["tm1"]), json=payload, timeout=20)
        assert r.status_code == 200, r.text
        rep1 = r.json()
        assert rep1["status"] == "Draft"
        report_id = rep1["id"]

        # 2) Idempotent same-week create -> same id
        payload2 = dict(payload)
        payload2["auto_summary"] = "EDITED summary " + payload["auto_summary"][:40]
        r2 = requests.post(f"{API}/reports", headers=H(tokens["tm1"]), json=payload2, timeout=20)
        assert r2.status_code == 200
        rep2 = r2.json()
        assert rep2["id"] == report_id, "Same-week draft should be idempotent"
        assert rep2["auto_summary"].startswith("EDITED summary")

        # 3) Manager cannot create
        rmgr = requests.post(f"{API}/reports", headers=H(tokens["manager"]), json=payload, timeout=10)
        assert rmgr.status_code == 403

        # 4) Update via PUT (owner)
        upd = {"notes_from_tm": "TEST_notes from tm"}
        r3 = requests.put(f"{API}/reports/{report_id}", headers=H(tokens["tm1"]), json=upd, timeout=10)
        assert r3.status_code == 200
        assert r3.json()["notes_from_tm"] == "TEST_notes from tm"

        # 5) Other TM cannot update
        r4 = requests.put(f"{API}/reports/{report_id}", headers=H(tokens["tm2"]),
                          json={"notes_from_tm": "hack"}, timeout=10)
        assert r4.status_code == 403

        # 6) GET RBAC
        rg_owner = requests.get(f"{API}/reports/{report_id}", headers=H(tokens["tm1"]), timeout=10)
        assert rg_owner.status_code == 200
        rg_other_tm = requests.get(f"{API}/reports/{report_id}", headers=H(tokens["tm2"]), timeout=10)
        assert rg_other_tm.status_code == 403
        rg_mgr = requests.get(f"{API}/reports/{report_id}", headers=H(tokens["manager"]), timeout=10)
        assert rg_mgr.status_code == 200

        # 7) TM list - own only
        rlist = requests.get(f"{API}/reports", headers=H(tokens["tm1"]), timeout=10)
        assert rlist.status_code == 200
        ids = [x["id"] for x in rlist.json()["reports"] if "id" in x]
        assert report_id in ids
        # tm2 should not see tm1's report
        rlist2 = requests.get(f"{API}/reports", headers=H(tokens["tm2"]), timeout=10)
        ids2 = [x.get("id") for x in rlist2.json()["reports"]]
        assert report_id not in ids2

        # 8) Submit
        rs = requests.post(f"{API}/reports/{report_id}/submit", headers=H(tokens["tm1"]), timeout=10)
        assert rs.status_code == 200
        sub = rs.json()
        assert sub["status"] == "Submitted"
        assert sub.get("submitted_at")

        # 8b) Idempotent submit
        rs2 = requests.post(f"{API}/reports/{report_id}/submit", headers=H(tokens["tm1"]), timeout=10)
        assert rs2.status_code == 200
        assert rs2.json()["status"] == "Submitted"

        # 9) Cannot edit after submit
        ru = requests.put(f"{API}/reports/{report_id}", headers=H(tokens["tm1"]),
                          json={"notes_from_tm": "post-submit"}, timeout=10)
        assert ru.status_code == 400

        # 10) Manager submitted bucket includes it
        rb = requests.get(f"{API}/reports?bucket=submitted", headers=H(tokens["manager"]), timeout=10)
        assert rb.status_code == 200
        sub_ids = [x.get("id") for x in rb.json()["reports"]]
        assert report_id in sub_ids

        # 11) TM cannot post comment
        rc_tm = requests.post(f"{API}/reports/{report_id}/comment",
                              headers=H(tokens["tm2"]), json={"text": "hi"}, timeout=10)
        assert rc_tm.status_code == 403

        # 12) Manager posts comment -> Reviewed
        rc = requests.post(f"{API}/reports/{report_id}/comment",
                           headers=H(tokens["manager"]),
                           json={"text": "TEST_great work this week"}, timeout=10)
        assert rc.status_code == 200, rc.text
        d = rc.json()
        assert d["status"] == "Reviewed"
        assert any(c["text"] == "TEST_great work this week" for c in d.get("comments", []))


class TestReportBuckets:
    def test_pending_bucket_synthetic(self, tokens):
        # tm1 submitted (above), tm2 should appear as pending synthetic
        r = requests.get(f"{API}/reports?bucket=pending", headers=H(tokens["manager"]), timeout=10)
        assert r.status_code == 200
        rows = r.json()["reports"]
        # All should be synthetic with status Pending
        for row in rows:
            assert row.get("synthetic") is True
            assert row["status"] == "Pending"
            assert "tm_user_id" in row
            assert "week_start" in row

    def test_overdue_bucket_synthetic(self, tokens):
        r = requests.get(f"{API}/reports?bucket=overdue", headers=H(tokens["manager"]), timeout=10)
        assert r.status_code == 200
        rows = r.json()["reports"]
        for row in rows:
            assert row.get("synthetic") is True
            assert row["status"] == "Overdue"
