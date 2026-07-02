"""track_signals routes — extracted from server.py during Phase C0 refactor.

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
from models import INVISALIGN_SIGNAL_TYPES, ITERO_SIGNAL_TYPES, TrackSignalCreate


@api.get("/track-signals")
async def list_track_signals(
    doctor_id: Optional[str] = None,
    track_type: Optional[str] = None,
    signal_type: Optional[str] = None,
    since: Optional[str] = None,  # YYYY-MM-DD
    user=Depends(get_current_user),
):
    q: dict = {"deleted_at": None, **_company_query_for(user)}
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    if doctor_id:
        q["doctor_id"] = doctor_id
    if track_type in ("iTero", "Invisalign"):
        q["track_type"] = track_type
    if signal_type:
        q["signal_type"] = signal_type
    if since:
        q["signal_date"] = {"$gte": since}
    rows = await db.track_signals.find(q, {"_id": 0}).sort("signal_date", -1).to_list(5000)
    return rows

@api.post("/track-signals")
async def create_track_signal(body: TrackSignalCreate, user=Depends(get_current_user)):
    """Manual TrackSignal creation — for when a user adds a signal outside the
    visit-log flow (rare, but supported). RBAC restricted to TMs & above."""
    if user["role"] not in ("TM", "SeniorTM", "Manager", "Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    doctor = await db.doctors.find_one({"id": body.doctor_id}, {"_id": 0})
    if not doctor or not await _can_access_doctor(user, doctor):
        raise HTTPException(status_code=404, detail="Doctor not found")
    if body.track_type == "iTero" and body.signal_type not in ITERO_SIGNAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown iTero signal_type: {body.signal_type}")
    if body.track_type == "Invisalign" and body.signal_type not in INVISALIGN_SIGNAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown Invisalign signal_type: {body.signal_type}")
    sid = await _insert_track_signal(
        doctor=doctor,
        visit_id=body.meeting_id,
        track_type=body.track_type,
        signal_type=body.signal_type,
        signal_value=body.signal_value,
        signal_status=body.signal_status,
        signal_date=body.signal_date,
        source=body.source,
        user=user,
    )
    return {"ok": True, "id": sid}

@api.delete("/track-signals/{signal_id}")
async def delete_track_signal(signal_id: str, user=Depends(get_current_user)):
    s = await db.track_signals.find_one({"id": signal_id, "deleted_at": None}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Track signal not found")
    _assert_same_company(user, s, detail="Track signal not found", code=404)
    if s["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.track_signals.update_one(
        {"id": signal_id}, {"$set": {"deleted_at": _now_iso(), "updated_at": _now_iso()}}
    )
    await _audit(user, "delete", "track_signal", signal_id, prev=s)
    return {"ok": True, "id": signal_id, "soft_deleted": True}
