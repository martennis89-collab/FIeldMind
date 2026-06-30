"""clinical_patterns routes — extracted from server.py during Phase C0 refactor.

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
from models import ClinicalPatternCreate


@api.get("/clinical-patterns")
async def list_clinical_patterns(
    doctor_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    q: dict = {"deleted_at": None, **_company_query_for(user)}
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    if doctor_id:
        q["doctor_id"] = doctor_id
    return await db.clinical_patterns.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)

@api.post("/clinical-patterns")
async def create_clinical_pattern(body: ClinicalPatternCreate, user=Depends(get_current_user)):
    """Doctor-level conversation pattern. AI-suggested patterns must arrive here
    only AFTER the user confirms — the AI extraction endpoint returns suggestions,
    this endpoint persists them."""
    if user["role"] not in ("TM", "Manager", "Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    doctor = await db.doctors.find_one({"id": body.doctor_id}, {"_id": 0})
    if not doctor or not await _can_access_doctor(user, doctor):
        raise HTTPException(status_code=404, detail="Doctor not found")
    import uuid as _uuid_mod
    row = {
        "id": _uuid_mod.uuid4().hex,
        "doctor_id": body.doctor_id,
        "tm_user_id": user["id"],
        "team_id": user.get("team_id") or doctor.get("team_id"),
        "meeting_id": body.meeting_id,
        "case_type": body.case_type,
        "treatment_preference": body.treatment_preference,
        "treatment_strategy": body.treatment_strategy,
        "confidence_level": body.confidence_level,
        "barrier_type": body.barrier_type,
        "source": body.source,
        "company_id": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "deleted_at": None,
    }
    _stamp_company(row, user)
    await db.clinical_patterns.insert_one(row)
    await _audit(
        user, "create", "clinical_pattern", row["id"],
        new={"case_type": body.case_type, "barrier_type": body.barrier_type},
        event_type="clinical_pattern_created",
        track_type="Invisalign",
    )
    _strip_id(row)
    return row

@api.delete("/clinical-patterns/{pattern_id}")
async def delete_clinical_pattern(pattern_id: str, user=Depends(get_current_user)):
    p = await db.clinical_patterns.find_one({"id": pattern_id, "deleted_at": None}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Clinical pattern not found")
    _assert_same_company(user, p, detail="Clinical pattern not found", code=404)
    if p["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.clinical_patterns.update_one(
        {"id": pattern_id}, {"$set": {"deleted_at": _now_iso(), "updated_at": _now_iso()}}
    )
    await _audit(user, "delete", "clinical_pattern", pattern_id, prev=p)
    return {"ok": True, "id": pattern_id, "soft_deleted": True}
