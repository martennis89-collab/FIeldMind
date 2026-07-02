"""Doctor duplicate-prevention — title-agnostic (Dr / Dr. / Doctor / no-prefix)
name matching so TM / SeniorTM can't accidentally create parallel profiles
for the same doctor.

Covers:
  1. `normalize_person_name` unit tests.
  2. POST /doctors returns 409 with the existing doctor id when a duplicate
     name is submitted with or without a "Dr" prefix.
  3. Different cities are treated as different doctors.
  4. Cleanup after each test to keep the collection idempotent.
"""
from __future__ import annotations
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv("/app/frontend/.env")
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from _deps import normalize_person_name, normalize_city_key  # noqa: E402

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=10)
    assert r.status_code == 200, f"{email} login: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def tm_token():
    return _login("tm1@field.io", "tm123")["token"]


# ----------- Unit tests for the normalizer -----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Dr John Smith", "john smith"),
        ("dr. john smith", "john smith"),
        ("DR JOHN SMITH", "john smith"),
        ("Doctor John Smith", "john smith"),
        ("Prof. Dr. John Smith", "john smith"),      # stacked titles
        ("  John   Smith  ", "john smith"),          # whitespace collapse
        ("Ján Škrabáček", "jan skrabacek"),          # accent fold
        ("Dr.Jane", "dr.jane"),                       # no space after Dr → not a title
        ("Mr Smith", "smith"),
        ("Mrs. Elena Petrova", "elena petrova"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_person_name(raw, expected):
    assert normalize_person_name(raw) == expected


def test_normalize_city_key_folds_accents():
    assert normalize_city_key("Sofía") == "sofia"
    assert normalize_city_key("  Plovdiv  ") == "plovdiv"
    assert normalize_city_key(None) == ""


# ----------- API-level dedupe -----------

_created_ids: list[str] = []


def _create(token, name, city=None, expected=200):
    body = {"doctor_name": name, "doctor_type": "GP", "segment": "Occasional"}
    if city:
        body["city"] = city
    r = requests.post(f"{API}/doctors", headers=H(token), json=body, timeout=10)
    assert r.status_code == expected, f"expected {expected}, got {r.status_code}: {r.text}"
    if r.status_code == 200:
        _created_ids.append(r.json()["id"])
    return r


def teardown_module(module):
    tok = _login("admin@field.io", "admin123")["token"]
    for did in _created_ids:
        try:
            requests.delete(f"{API}/doctors/{did}", headers=H(tok), timeout=5)
        except Exception:
            pass


def test_duplicate_with_dr_prefix_blocked(tm_token):
    tag = uuid.uuid4().hex[:8]
    name = f"Ivan Petrov {tag}"
    r1 = _create(tm_token, name, city="Sofia")
    original_id = r1.json()["id"]
    # Now the same name with "Dr" prefix.
    r2 = _create(tm_token, f"Dr {name}", city="Sofia", expected=409)
    detail = r2.json()["detail"]
    assert detail["code"] == "DUPLICATE_DOCTOR"
    assert detail["existing_id"] == original_id


def test_duplicate_prefix_variants_all_blocked(tm_token):
    tag = uuid.uuid4().hex[:8]
    name = f"Maria Ivanova {tag}"
    r1 = _create(tm_token, name, city="Plovdiv")
    original_id = r1.json()["id"]
    for variant in [f"Dr. {name}", f"DR {name}", f"Doctor {name}", f"Prof. {name}", f"  {name.upper()}  "]:
        r = _create(tm_token, variant, city="Plovdiv", expected=409)
        assert r.json()["detail"]["existing_id"] == original_id, f"variant '{variant}' did not dedupe"


def test_same_name_different_city_allowed(tm_token):
    tag = uuid.uuid4().hex[:8]
    name = f"Petar Stoyanov {tag}"
    _create(tm_token, name, city="Sofia")
    # Same person's name in a different city is treated as a different profile.
    _create(tm_token, f"Dr {name}", city="Varna", expected=200)


def test_duplicate_when_no_city_on_either_side(tm_token):
    tag = uuid.uuid4().hex[:8]
    name = f"Elena Georgieva {tag}"
    _create(tm_token, name)  # no city
    r = _create(tm_token, f"Dr. {name}", expected=409)
    assert r.json()["detail"]["code"] == "DUPLICATE_DOCTOR"
