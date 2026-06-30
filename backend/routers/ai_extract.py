"""ai_extract routes — extracted from server.py during Phase C0 refactor.

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
from models import *  # noqa: F401,F403,F405 — all models are exported under their original names


class ExtractTaskBody(BaseModel):
    note: str
    doctor_id: Optional[str] = None  # optional: pre-bind suggestion to a known doctor


@api.post("/ai/extract-task")
async def extract_task(body: ExtractTaskBody, user=Depends(get_current_user)):
    """Extract a single structured task suggestion from a quick voice/typed note.
    The user reviews and confirms before the task is actually created."""
    if user["role"] not in ("TM", "Manager", "Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="Note is empty")

    # Pull doctor names that the user can reach so the model can softly bind a doctor
    doc_q = await _doctor_query_for(user)
    docs = await db.doctors.find(doc_q, {"_id": 0, "id": 1, "doctor_name": 1, "clinic_name": 1, "city": 1}).to_list(2000)
    name_to_id = {d["doctor_name"]: d["id"] for d in docs if d.get("doctor_name")}
    suggestion = await ai_extract_task(note, doctor_names=list(name_to_id.keys()))

    # Resolve doctor_hint -> doctor_id
    if not body.doctor_id and suggestion.get("doctor_hint"):
        suggestion["doctor_id"] = name_to_id.get(suggestion["doctor_hint"])
    elif body.doctor_id:
        suggestion["doctor_id"] = body.doctor_id

    return {"suggestion": suggestion, "raw_note": note}
