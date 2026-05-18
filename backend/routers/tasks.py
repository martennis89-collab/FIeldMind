"""tasks routes — extracted from server.py during Phase C0 refactor.

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


@api.get("/tasks")
async def list_tasks(
    bucket: Optional[str] = Query(None, description="overdue|today|week|upcoming|completed|open"),
    user=Depends(get_current_user),
):
    q = {}
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    # Exclude soft-deleted tasks
    q["$or"] = [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]
    today_d = datetime.now(timezone.utc).date()
    today = today_d.isoformat()
    if bucket == "overdue":
        q["status"] = {"$in": ["Open", "Overdue"]}
        q["due_date"] = {"$lt": today}
    elif bucket == "today":
        q["status"] = {"$in": ["Open", "Overdue"]}
        q["due_date"] = today
    elif bucket == "week":
        end = (today_d + timedelta(days=7)).isoformat()
        q["status"] = {"$in": ["Open", "Overdue"]}
        q["due_date"] = {"$gte": today, "$lte": end}
    elif bucket == "upcoming":
        end = (today_d + timedelta(days=7)).isoformat()
        q["status"] = {"$in": ["Open", "Overdue"]}
        q["due_date"] = {"$gt": end}
    elif bucket == "completed":
        q["status"] = "Completed"
    elif bucket == "open":
        q["status"] = {"$in": ["Open", "Overdue"]}
    tasks = await db.tasks.find(q, {"_id": 0}).sort("due_date", 1).to_list(500)
    # Auto-mark overdue (computed view, not destructive)
    for t in tasks:
        if t.get("status") == "Open" and t.get("due_date") and t["due_date"] < today:
            t["status"] = "Overdue"
    return tasks

@api.post("/tasks")
async def create_task(body: TaskCreate, user=Depends(get_current_user)):
    doctor = await db.doctors.find_one({"id": body.doctor_id}, {"_id": 0})
    if not doctor or not await _can_access_doctor(user, doctor):
        raise HTTPException(status_code=404, detail="Doctor not found")
    import uuid
    today_d = datetime.now(timezone.utc).date()
    # Spec §3.6 + §30: If no due_date provided, default to +3 BUSINESS days.
    due_date = body.due_date or _add_business_days(today_d, 3).isoformat()
    task = Task(
        id=str(uuid.uuid4()),
        doctor_id=body.doctor_id,
        tm_user_id=user["id"],
        team_id=user.get("team_id") or doctor.get("team_id"),
        visit_id=body.visit_id,
        task_title=body.task_title,
        task_description=body.task_description or "",
        due_date=due_date,
        priority=body.priority,
        category=body.category,
        created_from_ai=body.created_from_ai,
        # AI-suggested promises stay unconfirmed until the user confirms them.
        # Manual creates default to True (the user is the creator).
        ai_confirmed=body.ai_confirmed if not body.created_from_ai else bool(body.ai_confirmed),
    ).model_dump()
    await db.tasks.insert_one(task)
    await _audit(
        user, "create", "task", task["id"],
        new={"task_title": task["task_title"], "category": task["category"], "ai": task["created_from_ai"]},
        event_type="promise_created",
    )
    _strip_id(task)
    return task

@api.put("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskUpdate, user=Depends(get_current_user)):
    t = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if t.get("deleted_at"):
        raise HTTPException(status_code=410, detail="Task has been deleted")
    # access
    if user["role"] == "TM" and t.get("tm_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "Manager" and t.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    update = body.model_dump(exclude_none=True)
    # Validate doctor reassignment
    if "doctor_id" in update and update["doctor_id"] != t.get("doctor_id"):
        new_doc = await db.doctors.find_one({"id": update["doctor_id"]}, {"_id": 0})
        if not new_doc or not await _can_access_doctor(user, new_doc):
            raise HTTPException(status_code=400, detail="Target doctor not accessible")
    if update.get("status") == "Completed":
        update["completed_at"] = _now_iso()
    elif update.get("status") in ("Open", "Overdue") and t.get("completed_at"):
        update["completed_at"] = None
    update["updated_at"] = _now_iso()
    await db.tasks.update_one({"id": task_id}, {"$set": update})
    # Pick the right named event for analytics §3.12
    became_completed = (update.get("status") == "Completed") and (t.get("status") != "Completed")
    named_event = "promise_completed" if became_completed else "promise_updated"
    await _audit(user, "update", "task", task_id, prev=t, new=update, event_type=named_event)
    new = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    return new

@api.delete("/tasks/{task_id}")
async def delete_task(task_id: str, user=Depends(get_current_user)):
    """Soft-delete: marks the task with deleted_at. Audit logged.

    TM may delete their own; Manager may delete within their team; Admin any.
    """
    t = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if t.get("deleted_at"):
        return {"ok": True, "id": task_id, "already_deleted": True}
    if user["role"] == "TM" and t.get("tm_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "Manager" and t.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    now = _now_iso()
    await db.tasks.update_one({"id": task_id}, {"$set": {
        "deleted_at": now,
        "deleted_by": user["id"],
        "updated_at": now,
    }})
    await _audit(user, "delete", "task", task_id, prev=t, event_type="promise_deleted")
    return {"ok": True, "id": task_id}
