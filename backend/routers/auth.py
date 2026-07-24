"""auth routes — extracted from server.py during Phase C0 refactor.

This module imports the shared `api` APIRouter + helpers from server.py and re-registers
its handlers on it. Behaviour is byte-for-byte identical to pre-refactor.
"""
from __future__ import annotations
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo, available_timezones
import hashlib
import io
import os
import logging
import secrets
import uuid

from fastapi import Depends, HTTPException, Request, Query, UploadFile, File, Form
from pydantic import BaseModel, EmailStr

from emails import send_password_reset_email

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

class ForgotPasswordBody(BaseModel):
    email: EmailStr


_GENERIC_RESET_RESPONSE = {"ok": True, "detail": "If that email is registered, we've sent a reset link."}


@api.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordBody, request: Request):
    """Always returns the same generic response regardless of whether the
    email exists — an account-enumeration guard, same principle as the
    login-lockout treating unknown emails like failed attempts."""
    email = body.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not user.get("active_status", True):
        return _GENERIC_RESET_RESPONSE

    # Cooldown — don't let a repeat submit spam the inbox or the rate-limited
    # Resend account. One outstanding link per user per 60s is plenty.
    recent = await db.password_resets.find_one(
        {"user_id": user["id"]}, sort=[("created_at", -1)]
    )
    if recent and recent.get("created_at") and recent["created_at"] > _now_iso_minus(60):
        return _GENERIC_RESET_RESPONSE

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    await db.password_resets.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        # Store a hash, not the raw token — a DB leak alone shouldn't hand
        # out usable reset links. SHA-256 (not bcrypt) because this needs an
        # exact-match lookup by value, and the token already has 256 bits of
        # its own entropy from secrets.token_urlsafe — no need for a slow,
        # salted KDF the way a human-chosen password does.
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "used_at": None,
    })
    await send_password_reset_email(email, user.get("full_name", ""), token)
    await _audit(user, "request_password_reset", "user", user["id"],
                 ip=request.client.host if request.client else None)
    return _GENERIC_RESET_RESPONSE


def _now_iso_minus(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


class ResetPasswordBody(BaseModel):
    token: str
    new_password: str


@api.post("/auth/reset-password")
async def reset_password(body: ResetPasswordBody):
    if len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="New password must be at least 4 characters")
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    rec = await db.password_resets.find_one({"token_hash": token_hash})
    now_iso = _now_iso()
    if not rec or rec.get("used_at") or rec["expires_at"] < now_iso:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    await db.users.update_one(
        {"id": rec["user_id"]},
        {"$set": {"password_hash": hash_password(body.new_password), "updated_at": _now_iso()}},
    )
    await db.password_resets.update_one({"id": rec["id"]}, {"$set": {"used_at": now_iso}})
    user = await db.users.find_one({"id": rec["user_id"]}, {"_id": 0})
    if user:
        await _audit(user, "reset_password", "user", rec["user_id"])
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
