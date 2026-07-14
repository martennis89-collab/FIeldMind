"""Iter19: SeniorTM event creation bug + regression across TM/Manager/Admin."""
import os
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def _hdr(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _mk_event_body(km=None, title="Iter19 Event"):
    starts = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    ends = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()
    body = {"title": title, "scheduled_at": starts, "ends_at": ends, "location": "HQ"}
    if km is not None:
        body["km"] = km
    return body


def test_senior_tm_create_event_with_km():
    tok = _login("snr.demo.1782126329@field.io", "senior123")
    body = _mk_event_body(km=42.5, title="SeniorTM Iter19 Event")
    r = requests.post(f"{API}/events", json=body, headers=_hdr(tok), timeout=30)
    assert r.status_code == 200, f"SeniorTM POST /events expected 200, got {r.status_code} {r.text}"
    d = r.json()
    assert d.get("id")
    assert d["title"] == body["title"]
    assert d["scheduled_at"] == body["scheduled_at"]
    assert d.get("km") == 42.5, f"km not persisted: {d.get('km')}"
    # verify GET
    g = requests.get(f"{API}/events/{d['id']}", headers=_hdr(tok), timeout=30)
    assert g.status_code == 200
    assert g.json().get("km") == 42.5


def test_tm_create_event_regression():
    tok = _login("tm1@field.io", "tm123")
    r = requests.post(f"{API}/events", json=_mk_event_body(title="TM Iter19"), headers=_hdr(tok), timeout=30)
    assert r.status_code == 200, r.text


def test_manager_create_event_regression():
    tok = _login("manager@field.io", "manager123")
    r = requests.post(f"{API}/events", json=_mk_event_body(title="Mgr Iter19"), headers=_hdr(tok), timeout=30)
    assert r.status_code == 200, r.text


def test_admin_create_event_regression():
    tok = _login("admin@field.io", "admin123")
    r = requests.post(f"{API}/events", json=_mk_event_body(title="Admin Iter19"), headers=_hdr(tok), timeout=30)
    assert r.status_code == 200, r.text
