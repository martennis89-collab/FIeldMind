"""auth routes — extracted from server.py during Phase C0 refactor.

This module imports the shared `api` APIRouter + helpers from server.py and re-registers
its handlers on it. Behaviour is byte-for-byte identical to pre-refactor.
"""
from __future__ import annotations
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo, available_timezones
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
    assert_not_locked_out,
    record_failed_login,
    clear_login_attempts,
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
from models import LoginRequest, LoginResponse, UserPublic


@api.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request):
    ip = request.client.host if request.client else None
    email = (body.email or "").lower().strip()
    # P2 brute-force guard — short-circuit before the bcrypt verify burns CPU.
    await assert_not_locked_out(ip, email)
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        await record_failed_login(ip, email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.get("active_status", True):
        # Treat deactivated-account hits as failed attempts so a deactivated
        # user can't be used as a probing oracle for valid emails.
        await record_failed_login(ip, email)
        raise HTTPException(status_code=403, detail="User is deactivated")
    await clear_login_attempts(ip, email)
    token = create_token(user["id"], user["role"], user["email"])
    _strip_user(user)
    await _audit(user, "login", "user", user["id"], ip=ip)
    return {"token": token, "user": user}

@api.get("/auth/me", response_model=UserPublic)
async def me(user=Depends(get_current_user)):
    return _strip_user(user)

@api.post("/auth/logout")
async def logout(request: Request, user=Depends(get_current_user)):
    await _audit(user, "logout", "user", user["id"], ip=request.client.host if request.client else None)
    return {"ok": True}

class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@api.post("/auth/change-password")
async def change_password(body: ChangePasswordBody, user=Depends(get_current_user)):
    """Self-service password change — any authenticated user can reset their own password."""
    if len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="New password must be at least 4 characters")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one")
    # Re-fetch to get the current password_hash (get_current_user strips it)
    full = await db.users.find_one({"id": user["id"]})
    if not full or not verify_password(body.current_password, full.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"password_hash": hash_password(body.new_password), "updated_at": _now_iso()}},
    )
    await _audit(user, "change_password", "user", user["id"])
    return {"ok": True}

class TimezoneUpdateBody(BaseModel):
    timezone: str


_VALID_TIMEZONES = available_timezones()


@api.put("/auth/timezone", response_model=UserPublic)
async def update_my_timezone(body: TimezoneUpdateBody, user=Depends(get_current_user)):
    """Self-service — any authenticated user sets their own IANA timezone.

    This is the reference used to resolve "today"/"tomorrow"/etc. when the AI
    parses a visit note or meeting request, so it works correctly no matter
    what country the user is dictating from. The frontend auto-populates this
    from the browser on first login; users can also change it manually in
    Account settings.
    """
    tz = body.timezone.strip()
    if tz not in _VALID_TIMEZONES:
        raise HTTPException(status_code=400, detail="Unrecognised timezone")
    await db.users.update_one({"id": user["id"]}, {"$set": {"timezone": tz, "updated_at": _now_iso()}})
    updated = await db.users.find_one({"id": user["id"]})
    return _strip_user(updated)

@api.post("/seed/init")
async def seed_init():
    if os.environ.get("ENABLE_DEMO_SEED", "").lower() not in ("1", "true", "yes"):
        raise HTTPException(status_code=404, detail="Not found")
    report = await seed_demo(db)
    # Phase C — stamp company_id on the freshly seeded demo rows.
    try:
        from server import _ensure_default_company_and_backfill
        c = await _ensure_default_company_and_backfill()
        report["company_backfill"] = c.get("backfilled", {})
    except Exception:
        pass
    return report
