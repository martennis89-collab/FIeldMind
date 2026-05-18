"""search routes — extracted from server.py during Phase C0 refactor.

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


@api.get("/search")
async def search(q: str, user=Depends(get_current_user)):
    if not q or len(q) < 2:
        return {"doctors": [], "visits": [], "tasks": []}
    base = await _doctor_query_for(user)
    rgx = {"$regex": q, "$options": "i"}
    docs_q = {**base, "$or": [{"doctor_name": rgx}, {"clinic_name": rgx}, {"city": rgx}]}
    doctors = await db.doctors.find(docs_q, {"_id": 0}).to_list(50)

    visit_q = {"$or": [
        {"free_text_note": rgx},
        {"confirmed_topics": rgx},
        {"confirmed_barriers": rgx},
        {"next_step": rgx},
    ]}
    if user["role"] == "TM":
        visit_q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        visit_q["team_id"] = user.get("team_id")
    visits = await db.visits.find(visit_q, {"_id": 0}).sort("visit_date", -1).to_list(50)

    task_q = {"$or": [{"task_title": rgx}, {"task_description": rgx}]}
    if user["role"] == "TM":
        task_q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        task_q["team_id"] = user.get("team_id")
    tasks = await db.tasks.find(task_q, {"_id": 0}).to_list(50)

    return {"doctors": doctors, "visits": visits, "tasks": tasks}
