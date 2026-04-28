"""Iteration-9 backend tests: doctor import + admin user management."""
import io
import os
import requests
from openpyxl import Workbook

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _make_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestDoctorImport:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.tm2 = _login("tm2@field.io", "tm123")
        self.manager = _login("manager@field.io", "manager123")
        self.admin = _login("admin@field.io", "admin123")

    def teardown_method(self):
        # Best-effort cleanup so the seeded baseline (10 doctors) is preserved for other tests.
        try:
            docs = requests.get(f"{API}/doctors", headers=H(self.admin), timeout=15).json()
            if isinstance(docs, dict):
                docs = docs.get("doctors", [])
            for d in docs:
                name = (d.get("doctor_name") or "").lower()
                if any(tok in name for tok in ("iter9", "test_iter9", "xlsx")):
                    requests.delete(f"{API}/doctors/{d['id']}", headers=H(self.admin), timeout=5)
        except Exception:
            pass

    def test_template_csv_and_xlsx(self):
        rc = requests.get(f"{API}/doctors/import/template?format=csv", headers=H(self.tm), timeout=10)
        assert rc.status_code == 200
        assert rc.headers["content-type"].startswith("text/csv")
        body = rc.content.decode("utf-8")
        assert "first_name" in body and "last_name" in body
        assert "Smile Clinic" in body
        rx = requests.get(f"{API}/doctors/import/template?format=xlsx", headers=H(self.tm), timeout=10)
        assert rx.status_code == 200
        assert rx.content[:2] == b"PK"   # ZIP-based xlsx

    def test_preview_then_commit_csv(self):
        csv = (
            "doctor_name,clinic_name,city,region,doctor_type,segment,general_notes\n"
            "Dr Test_iter9_alpha,Iter9 Alpha Clinic,Sofia,Sofia,Ortho,Active,Test note\n"
            "Dr Test_iter9_beta,Iter9 Beta Clinic,Plovdiv,South,GP,Engaged,\n"
        ).encode("utf-8")
        # preview
        rp = requests.post(f"{API}/doctors/import/preview", headers=H(self.tm),
                           files={"file": ("import.csv", csv, "text/csv")}, timeout=15)
        assert rp.status_code == 200, rp.text
        prev = rp.json()
        assert prev["row_count"] == 2
        assert prev["suggested_mapping"]["doctor_name"] == "doctor_name"
        # commit
        body = {
            "filename": prev["filename"],
            "mapping": prev["suggested_mapping"],
            "rows": prev["rows"],
            "duplicate_strategy": "skip",
        }
        rc = requests.post(f"{API}/doctors/import/commit", headers=H(self.tm), json=body, timeout=15)
        assert rc.status_code == 200, rc.text
        d = rc.json()
        assert d["created_count"] >= 2
        assert d["failed_count"] == 0
        # Doctors visible to TM
        rl = requests.get(f"{API}/doctors", headers=H(self.tm), timeout=15).json()
        names = [doc["doctor_name"] for doc in (rl if isinstance(rl, list) else rl.get("doctors", []))]
        assert any("iter9_alpha" in (n or "").lower() for n in names)

    def test_dedupe_skip(self):
        csv = (
            "doctor_name,clinic_name,city,region,doctor_type,segment\n"
            "Dr Iter9_dup,DupClinic,DupCity,X,GP,Active\n"
        ).encode("utf-8")
        # first import → created
        prev = requests.post(f"{API}/doctors/import/preview", headers=H(self.tm),
                             files={"file": ("import.csv", csv, "text/csv")}, timeout=15).json()
        body = {"filename": prev["filename"], "mapping": prev["suggested_mapping"],
                "rows": prev["rows"], "duplicate_strategy": "skip"}
        first = requests.post(f"{API}/doctors/import/commit", headers=H(self.tm), json=body, timeout=15).json()
        assert first["created_count"] == 1
        # second import same data → skipped
        prev2 = requests.post(f"{API}/doctors/import/preview", headers=H(self.tm),
                              files={"file": ("import.csv", csv, "text/csv")}, timeout=15).json()
        body2 = {"filename": prev2["filename"], "mapping": prev2["suggested_mapping"],
                 "rows": prev2["rows"], "duplicate_strategy": "skip"}
        second = requests.post(f"{API}/doctors/import/commit", headers=H(self.tm), json=body2, timeout=15).json()
        assert second["skipped_count"] == 1
        assert second["created_count"] == 0

    def test_validation_rejects_missing_name(self):
        csv = (
            "doctor_name,clinic_name,city\n"
            ",ClinicX,SomewhereCity\n"      # missing name
            "Dr Iter9_valid,ClinicY,Cityvalid\n"
        ).encode("utf-8")
        prev = requests.post(f"{API}/doctors/import/preview", headers=H(self.tm),
                             files={"file": ("x.csv", csv, "text/csv")}, timeout=15).json()
        body = {"filename": prev["filename"], "mapping": prev["suggested_mapping"],
                "rows": prev["rows"], "duplicate_strategy": "skip"}
        r = requests.post(f"{API}/doctors/import/commit", headers=H(self.tm), json=body, timeout=15)
        d = r.json()
        assert d["failed_count"] >= 1
        assert d["created_count"] >= 1

    def test_xlsx_upload(self):
        wb = _make_xlsx([
            ["doctor_name", "clinic_name", "city", "segment"],
            ["Dr Iter9_xlsx", "XlsxClinic", "Plovdiv", "Engaged"],
        ])
        rp = requests.post(f"{API}/doctors/import/preview", headers=H(self.tm),
                           files={"file": ("import.xlsx", wb,
                                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                           timeout=20)
        assert rp.status_code == 200, rp.text
        assert rp.json()["row_count"] == 1

    def test_manager_cannot_import(self):
        csv = b"doctor_name\nDr X\n"
        r = requests.post(f"{API}/doctors/import/preview", headers=H(self.manager),
                          files={"file": ("x.csv", csv, "text/csv")}, timeout=10)
        assert r.status_code == 403

    def test_admin_must_pick_tm(self):
        csv = b"doctor_name\nDr Iter9_admin\n"
        prev = requests.post(f"{API}/doctors/import/preview", headers=H(self.admin),
                             files={"file": ("x.csv", csv, "text/csv")}, timeout=10).json()
        body = {"filename": prev["filename"], "mapping": prev["suggested_mapping"],
                "rows": prev["rows"], "duplicate_strategy": "skip"}
        r = requests.post(f"{API}/doctors/import/commit", headers=H(self.admin), json=body, timeout=10)
        assert r.status_code == 400  # missing assigned_tm_id
        # with valid TM
        users = requests.get(f"{API}/users", headers=H(self.admin), timeout=10).json()
        target = next(u for u in users if u["email"] == "tm1@field.io")
        body["assigned_tm_id"] = target["id"]
        r2 = requests.post(f"{API}/doctors/import/commit", headers=H(self.admin), json=body, timeout=15)
        assert r2.status_code == 200, r2.text

    def test_admin_can_view_import_history(self):
        r = requests.get(f"{API}/admin/doctor-imports", headers=H(self.admin), timeout=10)
        assert r.status_code == 200
        assert "imports" in r.json()
        # TM cannot
        rt = requests.get(f"{API}/admin/doctor-imports", headers=H(self.tm), timeout=10)
        assert rt.status_code == 403

    def test_first_last_name_merge(self):
        """CSV with separate first_name/last_name columns should be merged into doctor_name."""
        csv = (
            "first_name,last_name,clinic_name,city,segment\n"
            "Maria,Iter9_split,SplitClinic,Sofia,New\n"
            "Petar,Iter9_split2,SplitClinic2,Plovdiv,Active\n"
        ).encode("utf-8")
        rp = requests.post(f"{API}/doctors/import/preview", headers=H(self.tm),
                           files={"file": ("split.csv", csv, "text/csv")}, timeout=15)
        assert rp.status_code == 200, rp.text
        prev = rp.json()
        sm = prev["suggested_mapping"]
        # auto-mapping should bind first_name & last_name
        assert sm.get("first_name") == "first_name"
        assert sm.get("last_name") == "last_name"
        body = {"filename": prev["filename"], "mapping": sm,
                "rows": prev["rows"], "duplicate_strategy": "skip"}
        rc = requests.post(f"{API}/doctors/import/commit", headers=H(self.tm), json=body, timeout=15)
        assert rc.status_code == 200, rc.text
        d = rc.json()
        assert d["created_count"] == 2
        assert d["failed_count"] == 0
        # Verify merged doctor_name visible
        rl = requests.get(f"{API}/doctors", headers=H(self.tm), timeout=15).json()
        docs = rl if isinstance(rl, list) else rl.get("doctors", [])
        names = [doc["doctor_name"] for doc in docs]
        assert any("Maria Iter9_split" == n for n in names), names

    def test_new_segment_accepted(self):
        """'New' must be accepted by import + create flows."""
        csv = (
            "doctor_name,clinic_name,city,segment\n"
            "Dr Iter9_newseg,NewSegClinic,Burgas,New\n"
        ).encode("utf-8")
        prev = requests.post(f"{API}/doctors/import/preview", headers=H(self.tm),
                             files={"file": ("ns.csv", csv, "text/csv")}, timeout=15).json()
        body = {"filename": prev["filename"], "mapping": prev["suggested_mapping"],
                "rows": prev["rows"], "duplicate_strategy": "skip"}
        rc = requests.post(f"{API}/doctors/import/commit", headers=H(self.tm), json=body, timeout=15)
        assert rc.status_code == 200, rc.text
        d = rc.json()
        assert d["created_count"] == 1
        assert d["failed_count"] == 0
        # Check segment persisted as 'New'
        rl = requests.get(f"{API}/doctors", headers=H(self.tm), timeout=15).json()
        docs = rl if isinstance(rl, list) else rl.get("doctors", [])
        match = next((doc for doc in docs if "iter9_newseg" in (doc.get("doctor_name") or "").lower()), None)
        assert match is not None
        assert match.get("segment") == "New"

    def test_manual_add_new_segment(self):
        """POST /api/doctors with segment='New' should succeed."""
        r = requests.post(f"{API}/doctors", headers=H(self.tm), json={
            "doctor_name": "Dr Iter9_manualnew",
            "clinic_name": "ManualNewClinic",
            "city": "Varna",
            "segment": "New",
            "doctor_type": "GP",
        }, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json().get("segment") == "New"




class TestUserManagement:
    """Existing endpoints regression — ensure RBAC still holds and deactivation blocks login."""

    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.admin = _login("admin@field.io", "admin123")
        self.manager = _login("manager@field.io", "manager123")
        self.tm = _login("tm1@field.io", "tm123")

    def teardown_method(self):
        try:
            users = requests.get(f"{API}/users", headers=H(self.admin), timeout=10).json()
            for u in users:
                if u["email"].startswith("iter9_"):
                    # Hard-deactivate (we have no DELETE /users; deactivation is sufficient)
                    requests.put(f"{API}/users/{u['id']}", headers=H(self.admin),
                                 json={"active_status": False, "email": f"deleted_{u['id'][:8]}@field.io"},
                                 timeout=5)
        except Exception:
            pass

    def test_only_admin_can_create_user(self):
        payload = {"full_name": "Iter9 New TM", "email": "iter9_new@field.io", "password": "pw123", "role": "TM"}
        # Manager forbidden
        r = requests.post(f"{API}/users", headers=H(self.manager), json=payload, timeout=10)
        assert r.status_code == 403
        # TM forbidden
        r2 = requests.post(f"{API}/users", headers=H(self.tm), json=payload, timeout=10)
        assert r2.status_code == 403
        # Admin OK
        r3 = requests.post(f"{API}/users", headers=H(self.admin), json=payload, timeout=10)
        assert r3.status_code == 200, r3.text
        new_id = r3.json()["id"]

        # Admin can deactivate
        r4 = requests.put(f"{API}/users/{new_id}", headers=H(self.admin),
                          json={"active_status": False}, timeout=10)
        assert r4.status_code == 200
        # Deactivated user cannot log in
        r5 = requests.post(f"{API}/auth/login", json={"email": "iter9_new@field.io", "password": "pw123"}, timeout=10)
        assert r5.status_code in (401, 403), r5.text

    def test_manager_cannot_edit(self):
        users = requests.get(f"{API}/users", headers=H(self.admin), timeout=10).json()
        target = next(u for u in users if u["email"] == "tm1@field.io")
        r = requests.put(f"{API}/users/{target['id']}", headers=H(self.manager),
                         json={"region": "Test"}, timeout=10)
        assert r.status_code == 403
