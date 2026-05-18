"""audit_logs routes — extracted from server.py during Phase C0 refactor.

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


@api.get("/audit")
async def audit_logs(limit: int = 100, user=Depends(require_roles("Admin"))):
    logs = await db.audit_logs.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return logs

@api.get("/audit_logs")
async def audit_logs_filtered(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 200,
    user=Depends(require_roles("Admin")),
):
    """Filtered event ledger reader (spec §3.12 — Activity Event Ledger).
    Returns a plain list (newest first) so analytics callers can consume directly."""
    q: dict = {}
    if entity_type:
        q["entity_type"] = entity_type
    if entity_id:
        q["entity_id"] = entity_id
    if event_type:
        q["event_type"] = event_type
    logs = await db.audit_logs.find(q, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return logs
