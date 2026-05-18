"""taxonomy routes — extracted from server.py during Phase C0 refactor.

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


@api.get("/taxonomy")
async def taxonomy(user=Depends(get_current_user)):
    topics, barriers = await _read_taxonomy_groups()
    return {
        "topics": topics,
        "barriers": barriers,
        "sentiments": ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"],
        "opportunity_states": ["Blocked", "Stuck", "Advancing", "Unknown"],
        "visit_types": ["In-person visit", "Phone call", "Online meeting", "Event conversation", "Training/session", "Other"],
        "segments": ["New", "Lapsed", "Occasional", "Active", "Engaged", "Expert"],
        "cadence": DEFAULT_CADENCE,
    }

@api.get("/admin/taxonomy")
async def admin_list_taxonomy(user=Depends(require_roles("Admin"))):
    await _ensure_taxonomy_seeded()
    rows = await db.taxonomy_terms.find({}, {"_id": 0}).sort([("kind", 1), ("category", 1), ("term", 1)]).to_list(2000)
    return {"terms": rows}

@api.post("/admin/taxonomy")
async def admin_create_taxonomy(body: dict, user=Depends(require_roles("Admin"))):
    import uuid
    kind = (body.get("kind") or "").lower().strip()
    category = (body.get("category") or "").strip()
    term = (body.get("term") or "").strip()
    if kind not in ("topic", "barrier"):
        raise HTTPException(status_code=400, detail="kind must be 'topic' or 'barrier'")
    if not category or not term:
        raise HTTPException(status_code=400, detail="category and term are required")
    dup = await db.taxonomy_terms.find_one({"kind": kind, "term": term})
    if dup:
        raise HTTPException(status_code=409, detail="Term already exists")
    doc = {"id": str(uuid.uuid4()), "kind": kind, "category": category,
           "term": term, "active": True, "created_at": _now_iso(), "updated_at": _now_iso()}
    _stamp_company(doc, user)
    await db.taxonomy_terms.insert_one(doc)
    await _audit(user, "create", "taxonomy_term", doc["id"], new={"kind": kind, "category": category, "term": term})
    doc.pop("_id", None)
    return doc

@api.put("/admin/taxonomy/{term_id}")
async def admin_update_taxonomy(term_id: str, body: dict, user=Depends(require_roles("Admin"))):
    existing = await db.taxonomy_terms.find_one({"id": term_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Term not found")
    update = {}
    for field in ("category", "term"):
        v = body.get(field)
        if v is not None:
            v = str(v).strip()
            if not v:
                raise HTTPException(status_code=400, detail=f"{field} cannot be empty")
            update[field] = v
    if "active" in body:
        update["active"] = bool(body["active"])
    if not update:
        return existing
    if "term" in update and update["term"] != existing["term"]:
        dup = await db.taxonomy_terms.find_one({"kind": existing["kind"], "term": update["term"], "id": {"$ne": term_id}})
        if dup:
            raise HTTPException(status_code=409, detail="Term already exists")
    update["updated_at"] = _now_iso()
    await db.taxonomy_terms.update_one({"id": term_id}, {"$set": update})
    await _audit(user, "update", "taxonomy_term", term_id, prev=existing, new=update)
    fresh = await db.taxonomy_terms.find_one({"id": term_id}, {"_id": 0})
    return fresh

@api.delete("/admin/taxonomy/{term_id}")
async def admin_delete_taxonomy(term_id: str, user=Depends(require_roles("Admin"))):
    existing = await db.taxonomy_terms.find_one({"id": term_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Term not found")
    await db.taxonomy_terms.delete_one({"id": term_id})
    await _audit(user, "delete", "taxonomy_term", term_id, prev=existing)
    return {"ok": True, "id": term_id}
