"""events routes — extracted from server.py during Phase C0 refactor.

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
    # ai
    ai_analyze_note,
    ai_extract_task,
    # seed
    seed_demo,
    seed_owner,
)
from models import *  # noqa: F401,F403 — all models are exported under their original names


@api.post("/events", response_model=Event)
async def create_event(body: EventCreate, user=Depends(get_current_user)):
    if user["role"] not in ("TM", "Manager", "Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    # Resolve start, end, and duration so all three stay in sync.
    starts = body.scheduled_at
    ends = body.ends_at
    duration = body.duration_minutes or 60
    try:
        start_dt = datetime.fromisoformat(starts.replace("Z", "+00:00"))
        if ends:
            end_dt = datetime.fromisoformat(ends.replace("Z", "+00:00"))
            if end_dt <= start_dt:
                raise HTTPException(status_code=400, detail="End must be after start")
            duration = max(int((end_dt - start_dt).total_seconds() // 60), 1)
        else:
            end_dt = start_dt + timedelta(minutes=duration)
            ends = end_dt.isoformat()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date/time")
    e = Event(
        id=str(uuid.uuid4()),
        title=body.title.strip(),
        tm_user_id=user["id"],
        tm_name=user.get("full_name", ""),
        team_id=user.get("team_id"),
        scheduled_at=starts,
        ends_at=ends,
        duration_minutes=duration,
        location=body.location,
        notes=body.notes,
        status="Scheduled",
    ).model_dump()
    await db.events.insert_one(e)
    await _audit(user, "create", "event", e["id"], new={"title": e["title"], "scheduled_at": e["scheduled_at"], "ends_at": e["ends_at"]})
    return e

@api.get("/events")
async def list_events(
    when: Optional[str] = Query(None, description="upcoming | past | all"),
    user=Depends(get_current_user),
):
    q: dict = {}
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    now = _now_iso()
    if when == "upcoming":
        q["scheduled_at"] = {"$gte": now}
        q["status"] = "Scheduled"
    elif when == "past":
        q["$or"] = [{"scheduled_at": {"$lt": now}}, {"status": {"$in": ["Done", "Cancelled"]}}]
    rows = await db.events.find(q, {"_id": 0}).sort("scheduled_at", 1).to_list(2000)
    return rows

@api.get("/events/{event_id}", response_model=Event)
async def get_event(event_id: str, user=Depends(get_current_user)):
    e = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not e:
        raise HTTPException(status_code=404, detail="Event not found")
    if user["role"] == "TM" and e["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "Manager" and e.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return e

@api.put("/events/{event_id}", response_model=Event)
async def update_event(event_id: str, body: EventUpdate, user=Depends(get_current_user)):
    e = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not e:
        raise HTTPException(status_code=404, detail="Event not found")
    if e["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    # Keep starts/ends/duration consistent if any of them was changed.
    has_time_change = any(k in update for k in ("scheduled_at", "ends_at", "duration_minutes"))
    if has_time_change:
        starts = update.get("scheduled_at", e.get("scheduled_at"))
        ends = update.get("ends_at", e.get("ends_at"))
        duration = update.get("duration_minutes", e.get("duration_minutes") or 60)
        try:
            start_dt = datetime.fromisoformat(starts.replace("Z", "+00:00"))
            # If user supplied a new ends_at, recompute duration; else recompute ends_at from duration.
            if "ends_at" in update or (ends and "scheduled_at" in update and "duration_minutes" not in update):
                end_dt = datetime.fromisoformat(ends.replace("Z", "+00:00"))
                if end_dt <= start_dt:
                    raise HTTPException(status_code=400, detail="End must be after start")
                duration = max(int((end_dt - start_dt).total_seconds() // 60), 1)
            else:
                end_dt = start_dt + timedelta(minutes=duration)
                ends = end_dt.isoformat()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid date/time")
        update["scheduled_at"] = starts
        update["ends_at"] = ends
        update["duration_minutes"] = duration
    update["updated_at"] = _now_iso()
    await db.events.update_one({"id": event_id}, {"$set": update})
    new = await db.events.find_one({"id": event_id}, {"_id": 0})
    await _audit(user, "update", "event", event_id, new=update)
    return new

@api.delete("/events/{event_id}")
async def delete_event(event_id: str, user=Depends(get_current_user)):
    e = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not e:
        raise HTTPException(status_code=404, detail="Event not found")
    if e["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.events.delete_one({"id": event_id})
    await _audit(user, "delete", "event", event_id, prev=e)
    return {"ok": True, "id": event_id}
