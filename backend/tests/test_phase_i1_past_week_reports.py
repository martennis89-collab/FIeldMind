"""Phase I.1 — Past-week report generation (current + 1 week back + 2 weeks back)."""
import os
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE}/api"


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


def _seed():
    requests.post(f"{API}/seed/init", timeout=30)


def _monday(anchor):
    return (anchor - timedelta(days=anchor.weekday())).date()


def test_generate_current_week_no_param():
    _seed()
    tok = _login("tm1@field.io", "tm123")
    r = requests.post(f"{API}/reports/generate", headers=H(tok), timeout=30)
    assert r.status_code == 200, r.text
    draft = r.json()
    today = datetime.now(timezone.utc)
    expected_mon = _monday(today).isoformat()
    assert draft["week_start"] == expected_mon


def test_generate_one_week_back():
    _seed()
    tok = _login("tm1@field.io", "tm123")
    anchor = datetime.now(timezone.utc) - timedelta(days=7)
    r = requests.post(
        f"{API}/reports/generate",
        headers=H(tok),
        params={"week_start": anchor.date().isoformat()},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["week_start"] == _monday(anchor).isoformat()


def test_generate_two_weeks_back():
    _seed()
    tok = _login("tm1@field.io", "tm123")
    anchor = datetime.now(timezone.utc) - timedelta(days=14)
    r = requests.post(
        f"{API}/reports/generate",
        headers=H(tok),
        params={"week_start": anchor.date().isoformat()},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["week_start"] == _monday(anchor).isoformat()


def test_generate_three_weeks_back_rejected():
    _seed()
    tok = _login("tm1@field.io", "tm123")
    anchor = datetime.now(timezone.utc) - timedelta(days=21)
    r = requests.post(
        f"{API}/reports/generate",
        headers=H(tok),
        params={"week_start": anchor.date().isoformat()},
        timeout=30,
    )
    assert r.status_code == 400, r.text
    assert "2 weeks" in r.json()["detail"].lower()


def test_generate_future_rejected():
    _seed()
    tok = _login("tm1@field.io", "tm123")
    anchor = datetime.now(timezone.utc) + timedelta(days=14)
    r = requests.post(
        f"{API}/reports/generate",
        headers=H(tok),
        params={"week_start": anchor.date().isoformat()},
        timeout=30,
    )
    assert r.status_code == 400, r.text


def test_generate_invalid_date_rejected():
    _seed()
    tok = _login("tm1@field.io", "tm123")
    r = requests.post(
        f"{API}/reports/generate",
        headers=H(tok),
        params={"week_start": "not-a-date"},
        timeout=30,
    )
    assert r.status_code == 400


def test_non_tm_still_blocked():
    _seed()
    tok = _login("manager@field.io", "manager123")
    r = requests.post(f"{API}/reports/generate", headers=H(tok), timeout=15)
    assert r.status_code == 403


def test_can_save_past_week_draft_via_post_reports():
    """End-to-end: generate a past-week draft, save it, list /reports/me — it should appear."""
    _seed()
    tok = _login("tm1@field.io", "tm123")
    anchor = datetime.now(timezone.utc) - timedelta(days=7)
    gen = requests.post(
        f"{API}/reports/generate",
        headers=H(tok),
        params={"week_start": anchor.date().isoformat()},
        timeout=30,
    ).json()

    save = requests.post(
        f"{API}/reports",
        headers=H(tok),
        json={
            "week_start": gen["week_start"],
            "week_end": gen["week_end"],
            "auto_summary": gen.get("auto_summary"),
            "content": gen.get("content"),
            "notes_from_tm": "Phase I.1 past-week test",
        },
        timeout=30,
    )
    assert save.status_code == 200, save.text
    saved = save.json()
    assert saved["week_start"] == gen["week_start"]

    listing = requests.get(f"{API}/reports", headers=H(tok), timeout=15).json()
    rows = listing.get("reports", []) if isinstance(listing, dict) else listing
    assert any(r["id"] == saved["id"] for r in rows)

    # Cleanup
    requests.delete(f"{API}/reports/{saved['id']}", headers=H(tok), timeout=10)
