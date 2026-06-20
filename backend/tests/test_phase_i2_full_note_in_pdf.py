"""Phase I.2 — Per-doctor PDF/CSV breakdown shows full visit note (not truncated)."""
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE}/api"

LONG_NOTE = (
    "I had a full-day training session with Dr. Doychinova and her entire team. "
    "There were seven team members participating, including the doctor herself, and "
    "they had dedicated the entire day to learning about the scanner workflow, "
    "ClinCheck handling, growth program economics, and how Invisalign cases compare "
    "to the practice's current bracket-based volume. We covered case selection, "
    "TPS service options, and arranged a peer-to-peer call for next month with a "
    "high-volume clinic from Sofia. The doctor specifically asked for additional "
    "training materials covering complex Class II cases and asked us to arrange a "
    "TBI Bank representative meeting to discuss patient financing options for "
    "future onboarded patients across the entire practice network."
)


def H(t):
    return {"Authorization": f"Bearer {t}"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _seed():
    requests.post(f"{API}/seed/init", timeout=30)


def test_pdf_breakdown_renders_full_note():
    _seed()
    tok = _login("tm1@field.io", "tm123")

    # Pick a doctor in scope
    docs = requests.get(f"{API}/doctors?limit=1", headers=H(tok), timeout=15).json()
    if isinstance(docs, dict):
        docs = docs.get("doctors") or docs.get("items") or []
    assert docs, "expected at least one doctor"
    doctor = docs[0]

    # Log a visit with a LONG free-text note (> 220 chars)
    today = datetime.now(timezone.utc).date().isoformat()
    visit = requests.post(
        f"{API}/visits",
        headers=H(tok),
        json={
            "doctor_id": doctor["id"],
            "visit_type": "In-person visit",
            "visit_date": today,
            "free_text_note": LONG_NOTE,
            "confirmed_topics": ["Invisalign pricing"],
            "confirmed_barriers": [],
            "sentiment": "Positive",
            "opportunity_state": "Advancing",
        },
        timeout=20,
    )
    assert visit.status_code == 200, visit.text
    body = visit.json()
    visit_id = (body.get("visit") or body).get("id")
    assert visit_id, f"could not parse visit id from {body}"

    try:
        # Generate the draft → should contain both note_excerpt (≤220 chars,
        # truncated) AND note_full (the entire note).
        gen = requests.post(f"{API}/reports/generate", headers=H(tok), timeout=30)
        assert gen.status_code == 200, gen.text
        draft = gen.json()
        br = (draft.get("content") or {}).get("doctor_breakdown") or []
        row = next((b for b in br if b.get("doctor_id") == doctor["id"]), None)
        assert row is not None, f"doctor breakdown missing for {doctor['id']}"
        assert row.get("note_full") == LONG_NOTE.strip(), "note_full must contain the full untruncated note"
        excerpt = row.get("note_excerpt") or ""
        assert len(excerpt) <= 220
        if len(LONG_NOTE) > 220:
            assert excerpt.endswith("…"), "excerpt should end with ellipsis when truncated"

        # Save the draft so we can hit the export endpoints
        saved = requests.post(
            f"{API}/reports",
            headers=H(tok),
            json={
                "week_start": draft["week_start"],
                "week_end": draft["week_end"],
                "auto_summary": draft.get("auto_summary"),
                "content": draft.get("content"),
            },
            timeout=20,
        )
        assert saved.status_code == 200, saved.text
        report_id = saved.json()["id"]

        try:
            # CSV must contain the full note text — pick a distinctive late-in-note phrase
            csv_resp = requests.get(
                f"{API}/reports/{report_id}/export",
                headers=H(tok),
                params={"format": "csv"},
                timeout=20,
            )
            assert csv_resp.status_code == 200
            csv_text = csv_resp.content.decode("utf-8", errors="ignore")
            # This phrase lives near the end of LONG_NOTE — would be cut by old 220-char truncation
            assert "TBI Bank representative meeting" in csv_text, (
                "CSV export must include the full note text, not the truncated excerpt"
            )

            # PDF must contain the full note text. Extract text via pdfplumber/pdfminer fallback.
            pdf_resp = requests.get(
                f"{API}/reports/{report_id}/export",
                headers=H(tok),
                params={"format": "pdf"},
                timeout=30,
            )
            assert pdf_resp.status_code == 200
            assert pdf_resp.headers.get("content-type", "").startswith("application/pdf")
            pdf_bytes = pdf_resp.content
            # Extract text from PDF (ReportLab compresses streams) and confirm
            # the late-in-note phrase is actually rendered, not just present in
            # raw bytes.
            from io import BytesIO
            from pdfminer.high_level import extract_text
            pdf_text = extract_text(BytesIO(pdf_bytes))
            assert "TBI Bank representative meeting" in pdf_text, "PDF must render the full note text"
            assert "financing options" in pdf_text, "PDF must render text past the old 220-char truncation"
        finally:
            requests.delete(f"{API}/reports/{report_id}", headers=H(tok), timeout=10)
    finally:
        # Best-effort cleanup of the visit
        requests.delete(f"{API}/visits/{visit_id}", headers=H(tok), timeout=10)


def test_old_reports_with_only_excerpt_still_export_cleanly():
    """Backwards compatibility: a report content payload that has only note_excerpt
    (i.e. saved before this fix) must still export — PDF/CSV fall back to excerpt."""
    _seed()
    tok = _login("tm1@field.io", "tm123")

    # Synthesize a saved report manually (POST /reports) with only note_excerpt
    today = datetime.now(timezone.utc).date()
    monday = (today - timedelta(days=today.weekday())).isoformat()
    sunday = (today - timedelta(days=today.weekday() - 6)).isoformat()
    fake = {
        "week_start": monday,
        "week_end": sunday,
        "auto_summary": "Phase I.2 backcompat test",
        "content": {
            "visits_completed": 1,
            "doctors_visited": 1,
            "topics_discussed": [],
            "barriers_heard": [],
            "promises_created": 0,
            "promises_completed": 0,
            "overdue_promises": 0,
            "sentiment_summary": {},
            "key_insights": [],
            "doctors_needing_attention": [],
            "doctor_breakdown": [
                {
                    "doctor_id": str(uuid.uuid4()),
                    "doctor_name": "Legacy Dr",
                    "visits_count": 1,
                    "topics": [],
                    "barriers": [],
                    "promises": [],
                    "sentiment": "Neutral",
                    # OLD-shape report: only excerpt, no full
                    "note_excerpt": "Legacy excerpt — old report stored before the full-note fix.",
                }
            ],
        },
    }
    saved = requests.post(f"{API}/reports", headers=H(tok), json=fake, timeout=20)
    assert saved.status_code == 200, saved.text
    report_id = saved.json()["id"]
    try:
        pdf = requests.get(
            f"{API}/reports/{report_id}/export",
            headers=H(tok),
            params={"format": "pdf"},
            timeout=20,
        )
        assert pdf.status_code == 200
        from io import BytesIO
        from pdfminer.high_level import extract_text
        text = extract_text(BytesIO(pdf.content))
        assert "Legacy excerpt" in text
    finally:
        requests.delete(f"{API}/reports/{report_id}", headers=H(tok), timeout=10)
