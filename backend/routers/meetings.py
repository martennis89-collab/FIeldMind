"""meetings routes — extracted from server.py during Phase C0 refactor.

This module imports the shared `api` APIRouter + helpers from server.py and re-registers
its handlers on it. Behaviour is byte-for-byte identical to pre-refactor.
"""
from __future__ import annotations
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta, date
import io
import os
import logging
import uuid

from fastapi import Depends, HTTPException, Request, Query, UploadFile, File, Form
from pydantic import BaseModel

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
from models import *  # noqa: F401,F403 — all models are exported under their original names


@api.post("/meetings", response_model=Meeting)
async def create_meeting(body: MeetingCreate, user=Depends(get_current_user)):
    if user["role"] != "TM":
        raise HTTPException(status_code=403, detail="Only TMs can book meetings")
    doctor = await db.doctors.find_one({"id": body.doctor_id}, {"_id": 0})
    if not doctor or not await _can_access_doctor(user, doctor):
        raise HTTPException(status_code=404, detail="Doctor not found")
    import uuid
    m = Meeting(
        id=str(uuid.uuid4()),
        doctor_id=body.doctor_id,
        doctor_name=doctor.get("doctor_name", ""),
        clinic_name=doctor.get("clinic_name"),
        city=doctor.get("city"),
        tm_user_id=user["id"],
        tm_name=user.get("full_name", ""),
        team_id=user.get("team_id") or doctor.get("team_id"),
        scheduled_at=body.scheduled_at,
        duration_minutes=body.duration_minutes or 30,
        subject=body.subject,
        is_demo=body.is_demo,
        status="Scheduled",
    ).model_dump()
    _stamp_company(m, user)
    await db.meetings.insert_one(m)
    await _audit(user, "create", "meeting", m["id"],
                 new={"doctor_id": body.doctor_id, "scheduled_at": body.scheduled_at, "is_demo": body.is_demo})

    # If this meeting is an iTero demo, auto-advance the doctor's pipeline stage to "Demo Booked"
    if body.is_demo:
        current = doctor.get("itero_stage") or "None"
        if current != "Lost" and ITERO_STAGE_RANK.get("Demo Booked", 0) > ITERO_STAGE_RANK.get(current, 0):
            now = _now_iso()
            await db.doctors.update_one(
                {"id": body.doctor_id},
                {"$set": {"itero_stage": "Demo Booked", "itero_stage_updated_at": now,
                          "itero_stage_updated_by": user["id"], "updated_at": now}},
            )
            await db.itero_stage_history.insert_one({
                "id": str(uuid.uuid4()),
                "doctor_id": body.doctor_id,
                "from_stage": current,
                "to_stage": "Demo Booked",
                "by_user_id": user["id"],
                "by_user_name": user.get("full_name", ""),
                "note": "Auto-advanced from booked iTero demo",
                "auto": True,
                "at": now,
                "company_id": _company_id_for(user),
            })
    return m

@api.get("/meetings")
async def list_meetings(
    when: Optional[str] = Query(None, description="upcoming | past | all"),
    user=Depends(get_current_user),
):
    q: dict = dict(_company_query_for(user))
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    # Admin/Owner sees all
    now = _now_iso()
    # Exclude soft-deleted meetings everywhere we list them.
    q["deleted_at"] = None
    if when == "upcoming":
        q["scheduled_at"] = {"$gte": now}
        q["status"] = "Scheduled"
    elif when == "past":
        q["$or"] = [{"scheduled_at": {"$lt": now}}, {"status": {"$in": ["Completed", "Cancelled"]}}]
    rows = await db.meetings.find(q, {"_id": 0}).sort("scheduled_at", 1).to_list(2000)
    return rows

@api.get("/meetings/{meeting_id}", response_model=Meeting)
async def get_meeting(meeting_id: str, user=Depends(get_current_user)):
    m = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    if not m or m.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Meeting not found")
    if user["role"] == "TM" and m["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "Manager" and m.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return m

@api.put("/meetings/{meeting_id}", response_model=Meeting)
async def update_meeting(meeting_id: str, body: MeetingUpdate, user=Depends(get_current_user)):
    m = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if m["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    update["updated_at"] = _now_iso()
    await db.meetings.update_one({"id": meeting_id}, {"$set": update})
    new = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    await _audit(user, "update", "meeting", meeting_id, new=update)
    return new

@api.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str, user=Depends(get_current_user)):
    m = await db.meetings.find_one({"id": meeting_id, "deleted_at": None}, {"_id": 0})
    if not m:
        # also try without the deleted_at filter for backward-compat (old rows have no field)
        m = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
        if not m or m.get("deleted_at"):
            raise HTTPException(status_code=404, detail="Meeting not found")
    if m["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    now = _now_iso()
    await db.meetings.update_one(
        {"id": meeting_id},
        {"$set": {"deleted_at": now, "updated_at": now, "status": "Cancelled"}},
    )
    await _audit(
        user, "delete", "meeting", meeting_id,
        prev=m, new={"deleted_at": now},
        event_type="meeting_deleted",
        track_type=m.get("track_type") or "General",
    )
    return {"ok": True, "id": meeting_id, "soft_deleted": True}

class CompleteDemoBody(BaseModel):
    interest_level: Literal["None", "Low", "Medium", "High"] = "Medium"
    outcome_note: Optional[str] = None
    next_step: Optional[str] = None  # if provided, creates a follow-up task
    next_step_due: Optional[str] = None  # ISO date for the task due_date


@api.post("/meetings/{meeting_id}/complete-demo")
async def complete_demo_meeting(meeting_id: str, body: CompleteDemoBody, user=Depends(get_current_user)):
    """One-tap completion for a booked iTero demo. Marks the meeting Completed,
    creates a lightweight visit (so the doctor lands in 'Demo Completed' on Demos overview),
    auto-advances the pipeline stage, and optionally creates a follow-up task.
    """
    m = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not m.get("is_demo"):
        raise HTTPException(status_code=400, detail="Only iTero-demo meetings can be marked done this way")
    if m["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if m.get("status") == "Completed":
        raise HTTPException(status_code=400, detail="Demo already completed")

    today_iso = _now_iso()
    today_date = today_iso[:10]
    note = (body.outcome_note or f"iTero demo completed. Interest: {body.interest_level}.").strip()

    # Build a lightweight visit record
    visit_id = str(uuid.uuid4())
    visit_doc = {
        "id": visit_id,
        "doctor_id": m["doctor_id"],
        "tm_user_id": user["id"],
        "team_id": m.get("team_id"),
        "track_type": "iTero",
        "visit_date": today_iso,
        "visit_type": "Demo session",
        "free_text_note": note,
        "ai_extracted_tags": {},
        "confirmed_topics": [],
        "confirmed_barriers": [],
        "sentiment": None,
        "itero_actions": {
            "demo_completed": True,
            "demo_completed_date": today_date,
            "scanner_interest_level": body.interest_level,
            "scanner_concerns": [],
        },
        "invisalign_actions": {},
        "commercial_actions": {},
        "meeting_id": meeting_id,
        "created_at": today_iso,
        "updated_at": today_iso,
    }
    _stamp_company(visit_doc, user)
    await db.visits.insert_one(visit_doc)
    await _audit(user, "create", "visit", visit_id, new={"doctor_id": m["doctor_id"], "from": "demo-complete"})

    # Mark meeting Completed and link the visit
    await db.meetings.update_one(
        {"id": meeting_id},
        {"$set": {"status": "Completed", "visit_id": visit_id, "updated_at": today_iso}},
    )

    # Auto-advance the pipeline stage forward
    class _IA:
        def model_dump(self): return {"demo_completed": True}
    class _CA:
        def model_dump(self): return {}
    await _auto_advance_itero_stage(m["doctor_id"], _IA(), _CA(), user)

    # Optional follow-up task
    task_id = None
    if body.next_step and body.next_step.strip():
        task_id = str(uuid.uuid4())
        await db.tasks.insert_one({
            "id": task_id,
            "doctor_id": m["doctor_id"],
            "tm_user_id": user["id"],
            "team_id": m.get("team_id"),
            "company_id": _company_id_for(user) or m.get("company_id"),
            "task_title": body.next_step.strip(),
            "task_description": "",
            "due_date": body.next_step_due or None,
            "priority": "Medium",
            "status": "Open",
            "promise_kind": "Follow-up",
            "source": "demo-complete",
            "source_visit_id": visit_id,
            "created_at": today_iso,
            "updated_at": today_iso,
        })
        await _audit(user, "create", "task", task_id, new={"task_title": body.next_step.strip(), "doctor_id": m["doctor_id"]})

    return {"ok": True, "meeting_id": meeting_id, "visit_id": visit_id, "task_id": task_id}

class CompleteMeetingBody(BaseModel):
    outcome_note: Optional[str] = None


@api.post("/meetings/{meeting_id}/complete")
async def complete_meeting(meeting_id: str, body: CompleteMeetingBody, user=Depends(get_current_user)):
    """One-tap completion for any meeting. Sets status=Completed.
    For demo meetings this is a thin wrapper that delegates to /complete-demo
    (so the pipeline auto-advance to 'Demo Completed' still happens).
    For regular meetings it just marks them done — no pipeline change.
    """
    m = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if m["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if m.get("status") == "Completed":
        raise HTTPException(status_code=400, detail="Meeting already completed")
    if m.get("is_demo"):
        # Delegate so the iTero pipeline still auto-advances to "Demo Completed"
        return await complete_demo_meeting(
            meeting_id,
            CompleteDemoBody(
                interest_level="Medium",
                outcome_note=body.outcome_note or None,
            ),
            user,
        )
    now = _now_iso()
    update = {"status": "Completed", "updated_at": now}
    if body.outcome_note and body.outcome_note.strip():
        # Persist the note on the meeting subject if provided so it isn't lost
        existing_subj = (m.get("subject") or "").strip()
        suffix = body.outcome_note.strip()
        update["subject"] = f"{existing_subj} — {suffix}" if existing_subj else suffix
    await db.meetings.update_one({"id": meeting_id}, {"$set": update})
    await _audit(user, "complete", "meeting", meeting_id, new={"status": "Completed"})
    return {"ok": True, "meeting_id": meeting_id, "is_demo": False}
