"""Phase Audit P2 — security hardening regression tests.

Covers:
  - Brute-force login throttling (HTTP 429 after N failures, clears on success)
  - Owner cross-company-read audit row written via _audit
  - AI error string sanitisation (no key leakage)
  - JWT secret is env-only (no fallback default)
  - /reports/generate per-user rate limit (HTTP 429)
"""
from __future__ import annotations
import os
import sys
import time
import importlib
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

# Load backend .env so MONGO_URL / DB_NAME / JWT_SECRET are visible when
# pytest is invoked from a path other than /app/backend.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv("/app/frontend/.env")
# Make sure we can import the live `auth` module sitting next to server.py.
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def H(token):
    return {"Authorization": f"Bearer {token}"}


def _mongo():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


class TestBruteForceLogin:
    """5 wrong-password attempts within the lockout window must return HTTP 429."""

    def setup_method(self):
        # Use the seeded Owner — we never send the correct password so the
        # account itself is unaffected.
        self.email = "martennis89@gmail.com"
        self.bad_password = "definitely-not-right-1234"
        # Wipe any pre-existing attempts for a clean baseline.
        db = _mongo()
        db.login_attempts.delete_many(
            {"identifier": {"$regex": f"email:{self.email}$"}}
        )

    def teardown_method(self):
        db = _mongo()
        db.login_attempts.delete_many(
            {"identifier": {"$regex": f"email:{self.email}$"}}
        )

    def test_locks_out_after_five_failures(self):
        # 5 wrong attempts -> still 401
        for i in range(5):
            r = requests.post(
                f"{API}/auth/login",
                json={"email": self.email, "password": self.bad_password},
                timeout=10,
            )
            assert r.status_code == 401, f"attempt {i + 1} expected 401, got {r.status_code}"
        # 6th attempt -> 429
        r = requests.post(
            f"{API}/auth/login",
            json={"email": self.email, "password": self.bad_password},
            timeout=10,
        )
        assert r.status_code == 429, f"6th attempt expected 429, got {r.status_code}"
        body = r.json().get("detail", "")
        assert "Too many" in body or "try again" in body.lower()

    def test_success_clears_counter(self):
        # Burn 3 attempts (under the limit) ...
        for _ in range(3):
            requests.post(
                f"{API}/auth/login",
                json={"email": self.email, "password": self.bad_password},
                timeout=10,
            )
        # ... then a successful login should wipe the counter (both the
        # email-only key and the current IP+email key).
        r = requests.post(
            f"{API}/auth/login",
            json={"email": self.email, "password": "1234"},
            timeout=10,
        )
        assert r.status_code == 200, f"login expected 200, got {r.status_code}: {r.text}"
        db = _mongo()
        leftover = list(db.login_attempts.find(
            {"identifier": {"$regex": f"email:{self.email}$"}}
        ))
        # Behavioural assertion: no leftover row must still be "locked out"
        # (i.e. count >= LOGIN_MAX_FAILURES). Individual IP+email rows may
        # persist when the K8s ingress load-balances requests across pods
        # with different source IPs — the successful login only clears the
        # ip+email key seen by the auth backend on THAT specific request.
        # The email-only key (which is the true lockout signal) MUST be gone.
        email_only = [d for d in leftover if d["identifier"] == f"email:{self.email}"]
        assert email_only == [], f"email-only counter should be wiped, got: {email_only}"
        assert all(d.get("count", 0) < 5 for d in leftover), (
            f"no leftover should still exceed lockout threshold, got: {leftover}"
        )


class TestJwtSecretEnvOnly:
    """auth.py must fail loud if JWT_SECRET is not provided — no fallback.

    Implemented as a static-source check because auth.py calls load_dotenv()
    at import time, which would re-populate the env var even after we pop it.
    """

    def test_jwt_secret_has_no_fallback(self):
        import re
        src = (Path(__file__).resolve().parents[1] / "auth.py").read_text()
        # Must read from os.environ[...] (fails fast) and NOT use .get() with a default.
        assert 'os.environ["JWT_SECRET"]' in src, \
            "auth.py must read JWT_SECRET via os.environ[...] (no fallback)."
        assert not re.search(r"os\.environ\.get\(\s*['\"]JWT_SECRET['\"]\s*,", src), \
            "JWT_SECRET must NOT have a fallback default in auth.py."


class TestAiErrorSanitisation:
    """ai.py must redact key-like substrings before exposing exception text."""

    def test_sanitiser_redacts_known_patterns(self):
        from ai import _sanitise_ai_error
        e = RuntimeError("AuthenticationError api_key=sk-emergent-1234567890abcdef")
        out = _sanitise_ai_error(e)
        assert "sk-emergent-1234567890abcdef" not in out
        assert "<redacted>" in out
        assert out.startswith("RuntimeError")

    def test_sanitiser_redacts_emergent_key_value(self, monkeypatch):
        # Pretend the key is a specific string and confirm it gets nuked even
        # when it doesn't match the generic patterns.
        import ai
        monkeypatch.setattr(ai, "EMERGENT_KEY", "super-secret-key-payload")
        e = RuntimeError("call failed with key super-secret-key-payload")
        out = ai._sanitise_ai_error(e)
        assert "super-secret-key-payload" not in out
        assert "<redacted>" in out

    def test_sanitiser_redacts_jwt_shape(self):
        from ai import _sanitise_ai_error
        jwt_like = "eyJabc.eyJabcdefghij.signature1234567890"
        e = RuntimeError(f"Bad token {jwt_like}")
        out = _sanitise_ai_error(e)
        assert jwt_like not in out


class TestOwnerCrossCompanyReadAudit:
    """Owner reading a doctor from a different company must produce one
    audit_logs row per (owner, target_company, day)."""

    def setup_method(self):
        # Sign in as the Owner.
        r = requests.post(
            f"{API}/auth/login",
            json={"email": "martennis89@gmail.com", "password": "1234"},
            timeout=10,
        )
        assert r.status_code == 200
        self.owner_token = r.json()["token"]
        self.owner_id = r.json()["user"]["id"]
        self.owner_company = r.json()["user"].get("company_id")
        db = _mongo()
        # Pick a doctor that lives in a DIFFERENT company than the Owner.
        self.target_doctor = db.doctors.find_one(
            {"company_id": {"$ne": self.owner_company, "$exists": True}}
        )
        if not self.target_doctor:
            # Materialise a tiny fixture company + doctor we can read.
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat()
            db.companies.insert_one({
                "id": "xc-test-company-1",
                "name": "Cross-Company Test Co",
                "created_at": now_iso,
            })
            db.doctors.insert_one({
                "id": "xc-test-doctor-1",
                "doctor_name": "Dr. Cross Company",
                "clinic_name": "XC Clinic",
                "city": "Nowhere",
                "company_id": "xc-test-company-1",
                "team_id": None,
                "assigned_tm_id": None,
                "segment": "New",
                "created_at": now_iso,
            })
            self.target_doctor = db.doctors.find_one({"id": "xc-test-doctor-1"})
        # Clean any pre-existing audit rows for this day so the test is deterministic.
        from datetime import datetime, timezone
        day = datetime.now(timezone.utc).date().isoformat()
        idem_prefix = f"owner_xc_read|{self.owner_id}|"
        db.audit_logs.delete_many({"idempotency_key": {"$regex": f"^{idem_prefix}.*\\|{day}\\|doctor$"}})

    def test_records_one_audit_row_per_day(self):
        if not self.target_doctor:
            pytest.skip("No cross-company doctor available to exercise this path.")
        # First read — should write the audit row.
        r1 = requests.get(
            f"{API}/doctors/{self.target_doctor['id']}",
            headers=H(self.owner_token),
            timeout=10,
        )
        assert r1.status_code == 200, f"expected 200, got {r1.status_code}: {r1.text}"
        # Second read — idempotency must dedupe.
        r2 = requests.get(
            f"{API}/doctors/{self.target_doctor['id']}",
            headers=H(self.owner_token),
            timeout=10,
        )
        assert r2.status_code == 200
        # Give Mongo a beat to flush the upsert.
        time.sleep(0.3)
        db = _mongo()
        from datetime import datetime, timezone
        day = datetime.now(timezone.utc).date().isoformat()
        rows = list(db.audit_logs.find({
            "event_type": "owner_cross_company_read",
            "user_id": self.owner_id,
            "idempotency_key": {"$regex": f"\\|{day}\\|doctor$"},
        }))
        assert len(rows) == 1, f"expected exactly 1 cross-company audit row for today, got {len(rows)}: {[r.get('idempotency_key') for r in rows]}"
        row = rows[0]
        assert row.get("event_type") == "owner_cross_company_read"
        nv = row.get("new_value") or {}
        assert nv.get("target_company_id") == self.target_doctor.get("company_id")
        assert nv.get("owner_company_id") == self.owner_company


class TestReportsGenerateRateLimit:
    """A TM that hammers /reports/generate must hit 429 after the limit."""

    def setup_method(self):
        # Sign in as a real TM. We seed via Owner -> demo seed.
        r = requests.post(
            f"{API}/auth/login",
            json={"email": "tm1@field.io", "password": "tm123"},
            timeout=10,
        )
        if r.status_code != 200:
            pytest.skip(f"TM credentials not available: {r.status_code}")
        self.tm_token = r.json()["token"]

    def test_429_after_limit(self):
        # The default REPORT_GEN_LIMIT is 20 per 60s. Send 21 quick hits.
        seen_429 = False
        for i in range(25):
            r = requests.post(
                f"{API}/reports/generate", headers=H(self.tm_token), timeout=10
            )
            if r.status_code == 429:
                seen_429 = True
                assert "Too many" in r.text or "Retry-After" in dict(r.headers).keys() or r.headers.get("Retry-After")
                break
            assert r.status_code == 200, f"hit {i + 1} expected 200, got {r.status_code}: {r.text[:120]}"
        assert seen_429, "expected at least one 429 within 25 consecutive calls"
