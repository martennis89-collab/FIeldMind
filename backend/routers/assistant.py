"""assistant.py — shared "figure out what the TM wants and do it" logic.

Single source of truth for turning a free-text note (voice-transcribed or
typed) into an action inside FieldMind: log a visit, book a meeting, book an
iTero demo, or log a standalone personal/admin task. Used by BOTH the
Telegram integration (routers/telegram.py) and the in-app Quick Capture
voice flow (POST /assistant/execute below) — they call the exact same
function so the two integrations can never drift apart in behaviour.

_execute_smart_action always returns a dict with a "status" key:
  - "done"                — action performed; see per-action fields below.
  - "needs_clarification" — AI couldn't confidently resolve what to do
                             (usually a missing doctor or missing date/time
                             for a meeting request); "reason" explains why.
  - "error"                — something failed; "detail" has the reason.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import logging

from fastapi import Depends, HTTPException

from ai import extract_task_from_text
from server import api, get_current_user
from routers.visits import _transcribe_audio_bytes, create_visit, analyze_visit_note
from routers.meetings import create_meeting
from routers.tasks import create_task
from models import AnalyzeNoteRequest, VisitCreate, AIExtraction, MeetingCreate, TaskCreate

logger = logging.getLogger(__name__)


async def _create_standalone_task(user: dict, note_text: str, visit_analysis: dict) -> dict:
    """A note that doesn't name a doctor at all — e.g. "call Viktoria at TBI
    Bank about the marketing materials" — isn't a visit. Log it as a personal/
    admin task instead of erroring out asking for a doctor.
    """
    promises = [p for p in (visit_analysis.get("promises_detected") or []) if p.get("task_title")]
    if not promises:
        # The visit-analysis prompt is dental-context-heavy and may miss a
        # generic task — retry with the task-focused extractor.
        task_result = await extract_task_from_text(note_text)
        if task_result.get("task_title"):
            promises = [task_result]

    if not promises:
        return {
            "status": "needs_clarification",
            "reason": 'Got it, but I couldn\'t find an actionable task in that note. '
                      'Try being more specific, e.g. "Call Viktoria at TBI Bank about the marketing materials."',
        }

    today = datetime.now(timezone.utc).date()
    created_titles = []
    for p in promises[:3]:
        title = (p.get("task_title") or "").strip()
        if not title:
            continue
        due = p.get("suggested_due_date") or (today + timedelta(days=14)).isoformat()
        prio = p.get("priority") if p.get("priority") in ("Low", "Medium", "High") else "Medium"
        task_body = TaskCreate(
            doctor_id=None,
            task_title=title,
            task_description=p.get("task_description") or note_text[:400],
            due_date=due,
            priority=prio,
            created_from_ai=True,
            ai_confirmed=True,
            category="other",
        )
        try:
            await create_task(task_body, user=user)
            created_titles.append(title)
        except HTTPException as e:
            logger.warning("Standalone task creation failed: %s", e.detail)

    if not created_titles:
        return {"status": "error", "detail": "Something went wrong saving that task — nothing was saved."}
    return {"status": "done", "action": "task", "task_titles": created_titles}


async def _execute_smart_action(user: dict, note_text: str, doctor_id: str | None = None) -> dict:
    """Given a free-text note, figure out what the TM wants done and do it.

    `doctor_id`: optional — pass this when the caller already knows which
    doctor the note is about (e.g. Quick Capture opened from a doctor's
    profile page) to skip AI doctor-matching and bind directly.
    """
    note_text = (note_text or "").strip()
    if not note_text:
        return {"status": "error", "detail": "Empty note"}

    try:
        result = await analyze_visit_note(AnalyzeNoteRequest(note=note_text, doctor_id=doctor_id), user=user)
    except HTTPException as e:
        return {"status": "error", "detail": e.detail}
    except Exception:
        logger.exception("Smart action AI analysis failed")
        return {"status": "error", "detail": "Something went wrong analyzing that note — nothing was saved."}

    intent = result.get("intent") or "log_visit"
    resolved_doctor_id = result.get("doctor_id")
    doctor_name_heard = result.get("doctor_name_heard")
    newly_created_doctor_name = result.get("doctor_hint") if result.get("doctor_auto_created") else None
    doctor_name = newly_created_doctor_name or result.get("doctor_hint") or "the doctor"

    # No doctor named at all and not an explicit scheduling request -> personal task.
    if intent == "task" or (
        not resolved_doctor_id and not doctor_name_heard and intent not in ("book_meeting", "book_demo")
    ):
        return await _create_standalone_task(user, note_text, result)

    if intent in ("book_meeting", "book_demo"):
        if not resolved_doctor_id:
            return {"status": "needs_clarification", "reason": "Which doctor is this meeting with?"}
        scheduled_for = result.get("meeting_scheduled_for")
        if not scheduled_for:
            return {
                "status": "needs_clarification",
                "reason": "When should this be scheduled? Please include a specific date and time.",
            }
        try:
            meeting = await create_meeting(
                MeetingCreate(doctor_id=resolved_doctor_id, scheduled_at=scheduled_for, is_demo=(intent == "book_demo")),
                user=user,
            )
        except HTTPException as e:
            return {"status": "error", "detail": e.detail}
        return {
            "status": "done",
            "action": "demo" if intent == "book_demo" else "meeting",
            "doctor_name": doctor_name,
            "doctor_auto_created": bool(newly_created_doctor_name),
            "scheduled_at": scheduled_for,
            "meeting_id": meeting["id"],
        }

    # Default: log_visit.
    if not resolved_doctor_id:
        return {
            "status": "needs_clarification",
            "reason": "Couldn't find or add a doctor from that note — please mention who you visited.",
        }

    track_types = result.get("track_types") or []
    if "ITERO" in track_types and "INVISALIGN" not in track_types:
        track_type = "ITERO"
    elif "INVISALIGN" in track_types and "ITERO" not in track_types:
        track_type = "INVISALIGN"
    else:
        track_type = "BOTH"

    mentioned_date = result.get("visit_date_mentioned")
    visit_body = VisitCreate(
        doctor_id=resolved_doctor_id,
        # Every other visit_date in this codebase is a full timezone-aware ISO
        # datetime — give a bare "YYYY-MM-DD" a noon-UTC time component so
        # downstream naive/aware datetime math doesn't break.
        visit_date=f"{mentioned_date}T12:00:00+00:00" if mentioned_date else None,
        visit_type="In-person visit",
        track_type=track_type,
        free_text_note=note_text,
        confirmed_topics=result.get("topics") or [],
        confirmed_barriers=result.get("barriers") or [],
        sentiment=result.get("sentiment") or "Neutral",
        opportunity_state=result.get("opportunity_state") or "Unknown",
        next_step=result.get("suggested_next_action") or None,
        promises=[p for p in (result.get("promises_detected") or []) if p.get("task_title")],
        ai_extraction=AIExtraction(**result),
        itero_actions=result.get("itero_actions") or {},
        invisalign_actions=result.get("invisalign_actions") or {},
        commercial_actions=result.get("commercial_actions") or {},
    )
    try:
        saved = await create_visit(visit_body, user=user)
    except HTTPException as e:
        return {"status": "error", "detail": e.detail}

    return {
        "status": "done",
        "action": "visit",
        "doctor_name": doctor_name,
        "doctor_auto_created": bool(newly_created_doctor_name),
        "sentiment": result.get("sentiment") or "Neutral",
        "visit_date": mentioned_date,
        "n_promises": len(saved.get("created_tasks") or []),
        "visit_id": saved["visit"]["id"],
    }


@api.post("/assistant/execute")
async def execute_assistant_action(body: AnalyzeNoteRequest, user=Depends(get_current_user)):
    """HTTP entry point for the in-app Quick Capture voice flow — same
    engine Telegram uses, so a voice note does the same thing in either
    place: log a visit, book a meeting/demo, or log a personal task.
    """
    return await _execute_smart_action(user, body.note, doctor_id=body.doctor_id)
