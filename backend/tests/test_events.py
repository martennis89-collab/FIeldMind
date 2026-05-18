"""Iter-18 backend tests: generic events alongside meetings."""
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


def _future_iso(hours=24):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class TestEvents:
    def setup_method(self):
        requests.post(f"{API}/seed/init", timeout=30)
        self.tm = _login("tm1@field.io", "tm123")
        self.tm2 = _login("tm2@field.io", "tm123")
        self.manager = _login("manager@field.io", "manager123")

    def teardown_method(self):
        try:
            owner = _login("martennis89@gmail.com", "1234")
            for ev in requests.get(f"{API}/events?when=all", headers=H(owner), timeout=10).json():
                if (ev.get("title") or "").startswith("iter18"):
                    requests.delete(f"{API}/events/{ev['id']}", headers=H(owner), timeout=5)
        except Exception:
            pass

    def test_create_list_update_delete(self):
        starts = _future_iso(72)
        ends = (datetime.now(timezone.utc) + timedelta(hours=72 + 2)).isoformat()
        r = requests.post(f"{API}/events", headers=H(self.tm), json={
            "title": "iter18 Internal training",
            "scheduled_at": starts,
            "ends_at": ends,
            "location": "Sofia office",
            "notes": "Bring laptop",
        }, timeout=10)
        assert r.status_code == 200, r.text
        e = r.json()
        assert e["title"] == "iter18 Internal training"
        assert e["status"] == "Scheduled"
        # Duration must reflect end - start (~120 min)
        assert 115 <= e["duration_minutes"] <= 125
        assert e.get("ends_at")
        # List upcoming
        rl = requests.get(f"{API}/events?when=upcoming", headers=H(self.tm), timeout=10).json()
        assert any(x["id"] == e["id"] for x in rl)
        # Update -> mark Done
        ru = requests.put(f"{API}/events/{e['id']}", headers=H(self.tm), json={"status": "Done"}, timeout=10)
        assert ru.status_code == 200 and ru.json()["status"] == "Done"
        # Past list now sees it
        rp = requests.get(f"{API}/events?when=past", headers=H(self.tm), timeout=10).json()
        assert any(x["id"] == e["id"] for x in rp)
        # Delete
        rd = requests.delete(f"{API}/events/{e['id']}", headers=H(self.tm), timeout=10)
        assert rd.status_code == 200

    def test_end_must_be_after_start(self):
        starts = _future_iso(48)
        ends = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()  # before start
        r = requests.post(f"{API}/events", headers=H(self.tm), json={
            "title": "iter18 invalid", "scheduled_at": starts, "ends_at": ends,
        }, timeout=10)
        assert r.status_code == 400

    def test_other_tm_cannot_see_or_modify(self):
        e = requests.post(f"{API}/events", headers=H(self.tm), json={
            "title": "iter18 private", "scheduled_at": _future_iso(48),
        }, timeout=10).json()
        # tm2 cannot fetch
        r = requests.get(f"{API}/events/{e['id']}", headers=H(self.tm2), timeout=10)
        assert r.status_code == 403
        # tm2 cannot delete
        r2 = requests.delete(f"{API}/events/{e['id']}", headers=H(self.tm2), timeout=10)
        assert r2.status_code == 403
        # cleanup
        requests.delete(f"{API}/events/{e['id']}", headers=H(self.tm), timeout=10)

    def test_manager_sees_team_events(self):
        e = requests.post(f"{API}/events", headers=H(self.tm), json={
            "title": "iter18 team event", "scheduled_at": _future_iso(48),
        }, timeout=10).json()
        rl = requests.get(f"{API}/events?when=upcoming", headers=H(self.manager), timeout=10).json()
        assert any(x["id"] == e["id"] for x in rl)
        requests.delete(f"{API}/events/{e['id']}", headers=H(self.tm), timeout=10)
