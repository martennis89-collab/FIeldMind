"""visits routes — extracted from server.py during Phase C0 refactor.

This module imports the shared `api` APIRouter + helpers from server.py and re-registers
its handlers on it. Behaviour is byte-for-byte identical to pre-refactor.
"""
from __future__ import annotations
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta, date
import os
import logging
import uuid

from fastapi import Depends, HTTPException, Request, Query, UploadFile, File, Form
from pydantic import BaseModel

# Domain vocabulary to bias ElevenLabs Scribe toward — acronyms/product names it
# otherwise tends to mishear (e.g. "TPS" -> "GPS"). Extend this list as more
# mis-transcriptions turn up in real Telegram/in-app voice notes.
_DOMAIN_KEYTERMS = [
    "TPS", "Treatment Planning Services",
    "iTero", "iTero Element", "iTero Lens",
    "Invisalign", "ClinCheck", "SmartTrack", "Vivera",
]

# Pull every shared symbol the handlers reference. The router file is imported AFTER
# server.py finishes initialising all of these so the names are guaranteed to exist.
from server import (
    api,
    db,
    app,
    DEFAULT_CADENCE,
    # auth
    get_current_user,
    require_roles,
    hash_password,
    verify_password,
    create_token,
    # helpers
    _now_iso,
    _audit,
    _strip_id,
    _strip_user,
    _doctor_query_for,
    _can_access_doctor,
    _cadence_status,
    _priority_score,
    _priority_label,
    _enrich_doctor,
    _aggregate_itero,
    _aggregate_invisalign,
    _aggregate_commercial,
    _suggested_reason,
    _visit_track_type,
    _insert_track_signal,
    _materialize_track_signals_from_visit,
    _signal_to_stage,
    _auto_advance_itero_stage,
    _market_pulse,
    _ensure_taxonomy_seeded,
    _read_taxonomy_groups,
    _track_filter_visits,
    _build_report_draft,
    _month_of,
    _expense_visible_to,
    _add_business_days,
    _company_id_for,
    _company_query_for,
    _apply_company_scope,
    _same_company,
    _assert_same_company,
    _stamp_company,
    ENFORCE_COMPANY_ISOLATION,
    # ai
    ai_analyze_note,
    ai_extract_task,
    # seed
    seed_demo,
    seed_owner,
)
from models import AnalyzeNoteRequest, CommercialActions, InvisalignActions, IteroActions, VisitCreate


@api.post("/visits/analyze")
async def analyze_visit_note(body: AnalyzeNoteRequest, user=Depends(get_current_user)):
    from routers.doctors import _resolve_or_create_doctor

    doctors = None
    if not body.doctor_id:
        # No doctor picked yet (e.g. voice-first capture) — let the AI try to match
        # one from the note against the caller's own scoped roster.
        doc_q = await _doctor_query_for(user)
        doctors = await db.doctors.find(doc_q, {"_id": 0, "id": 1, "doctor_name": 1}).to_list(2000)
    result = await ai_analyze_note(body.note, session_id=f"analyze-{user['id']}", doctors=doctors)

    # Nothing on the roster matched, but a name was heard — auto-create/resolve
    # so logging a visit is just as friction-free in the app as via Telegram,
    # for reps who never touch the bot. Same duplicate-safe logic either way.
    if not result.get("doctor_id") and result.get("doctor_name_heard"):
        resolved = await _resolve_or_create_doctor(user, result["doctor_name_heard"])
        if resolved:
            result["doctor_id"] = resolved["id"]
            result["doctor_hint"] = resolved["doctor_name"]
            result["doctor_auto_created"] = resolved.get("_was_created", False)

    return result

async def _transcribe_audio_bytes(raw: bytes, filename: str, content_type: str) -> str:
    """Shared ElevenLabs Scribe call — used by the HTTP upload endpoint below and
    by the Telegram voice-note webhook (routers/telegram.py). Raises HTTPException
    on failure so both callers get consistent error handling."""
    import httpx

    if not os.environ.get("ELEVENLABS_API_KEY"):
        raise HTTPException(status_code=503, detail="Transcription service not configured")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio file")
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file exceeds 25 MB limit")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.elevenlabs.io/v1/speech-to-text",
                headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
                # keyterms (vocabulary biasing) is only supported on scribe_v2 —
                # confirmed against the live API, since the public docs incorrectly
                # implied v1 support.
                data={
                    "model_id": "scribe_v2",
                    "keyterms": _DOMAIN_KEYTERMS,
                },
                files={"file": (filename, raw, content_type or "audio/webm")},
            )
            resp.raise_for_status()
            data = resp.json()
        return (data.get("text", "") or "").strip()
    except HTTPException:
        raise
    except Exception:
        logging.exception("ElevenLabs transcription failed")
        raise HTTPException(status_code=502, detail="Transcription service unavailable")


@api.post("/visits/transcribe")
async def transcribe_visit_audio(audio: UploadFile = File(...), user=Depends(get_current_user)):
    """Transcribe an uploaded audio clip (TM voice memo) into text using ElevenLabs Scribe.

    Accepts a multipart upload with field name 'audio'. Supported formats: webm, mp3, m4a, wav, mp4, mpga, mpeg.
    Max 25 MB. Returns {text: str}.
    """
    raw = await audio.read()
    text = await _transcribe_audio_bytes(raw, audio.filename or "voice.webm", audio.content_type)
    await _audit(user, "transcribe", "visit", "audio", new={"chars": len(text)})
    return {"text": text}

@api.post("/visits")
async def create_visit(body: VisitCreate, user=Depends(get_current_user)):
    doctor = await db.doctors.find_one({"id": body.doctor_id}, {"_id": 0})
    if not doctor or not await _can_access_doctor(user, doctor):
        raise HTTPException(status_code=404, detail="Doctor not found")
    vdate = body.visit_date or _now_iso()
    visit = {
        "id": str(uuid.uuid4()),
        "doctor_id": body.doctor_id,
        "tm_user_id": user["id"],
        "team_id": user.get("team_id") or doctor.get("team_id"),
        "visit_date": vdate,
        "visit_type": body.visit_type,
        "track_type": body.track_type or "BOTH",
        "free_text_note": body.free_text_note,
        "confirmed_topics": body.confirmed_topics,
        "confirmed_barriers": body.confirmed_barriers,
        "sentiment": body.sentiment,
        "opportunity_state": body.opportunity_state,
        "next_step": body.next_step,
        "ai_extraction": body.ai_extraction.model_dump() if body.ai_extraction else None,
        "itero_actions": body.itero_actions.model_dump() if body.itero_actions else IteroActions().model_dump(),
        "invisalign_actions": body.invisalign_actions.model_dump() if body.invisalign_actions else InvisalignActions().model_dump(),
        "commercial_actions": body.commercial_actions.model_dump() if body.commercial_actions else CommercialActions().model_dump(),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _stamp_company(visit, user)
    await db.visits.insert_one(visit)
    # Spec §3.12 — named event
    await _audit(
        user, "create", "visit", visit["id"],
        new={"doctor_id": body.doctor_id, "sentiment": body.sentiment},
        event_type="meeting_logged",
        track_type=_visit_track_type(body),
    )

    # Auto-advance iTero pipeline stage based on the latest visit's signals.
    await _auto_advance_itero_stage(body.doctor_id, body.itero_actions, body.commercial_actions, user)

    # PHASE B — Materialize confirmed Track Signals from the visit payload.
    # The user confirmed these checkboxes in the UI, so source = "AI Confirmed"
    # when there was an ai_extraction, else "Manual".
    src_label = "AI Confirmed" if body.ai_extraction else "Manual"
    await _materialize_track_signals_from_visit(
        visit=visit, doctor=doctor, body=body, source=src_label, user=user
    )

    # Auto-link meeting -> Completed when visit logged from a booked meeting
    if body.meeting_id:
        m = await db.meetings.find_one({"id": body.meeting_id, "tm_user_id": user["id"]}, {"_id": 0})
        if m and m.get("status") == "Scheduled":
            await db.meetings.update_one(
                {"id": body.meeting_id},
                {"$set": {"status": "Completed", "visit_id": visit["id"], "updated_at": _now_iso()}},
            )

    # auto-create tasks from confirmed promises
    created_tasks = []
    today = datetime.now(timezone.utc).date()
    for p in (body.promises or []):
        due = p.suggested_due_date
        if not due:
            # Spec §3.6 default — +3 business days when AI didn't propose one
            due = _add_business_days(today, 3).isoformat()
        task = {
            "id": str(uuid.uuid4()),
            "doctor_id": body.doctor_id,
            "tm_user_id": user["id"],
            "team_id": visit["team_id"],
            "visit_id": visit["id"],
            "task_title": p.task_title,
            "task_description": p.task_description or "",
            "due_date": due,
            "priority": p.priority,
            "status": "Open",
            "created_from_ai": True,
            # The user confirmed this AI suggestion by saving the visit → ai_confirmed=True
            "ai_confirmed": True,
            "category": "other",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "completed_at": None,
        }
        _stamp_company(task, user)
        await db.tasks.insert_one(task)
        await _audit(
            user, "create", "task", task["id"],
            new={"task_title": task["task_title"], "ai": True},
            event_type="promise_created",
        )
        _strip_id(task)
        created_tasks.append(task)

    _strip_id(visit)
    return {"visit": visit, "created_tasks": created_tasks}

@api.get("/visits")
async def list_visits(
    doctor_id: Optional[str] = None,
    tm_user_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    q = dict(_company_query_for(user))
    if user["role"] in ("TM", "SeniorTM"):
        q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    if doctor_id:
        q["doctor_id"] = doctor_id
    if tm_user_id and user["role"] in ("Admin", "Manager", "SeniorTM"):
        q["tm_user_id"] = tm_user_id
    visits = await db.visits.find(q, {"_id": 0}).sort("visit_date", -1).to_list(500)
    return visits
