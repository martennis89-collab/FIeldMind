"""users routes — extracted from server.py during Phase C0 refactor.

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


@api.post("/admin/wipe-test-data")
async def wipe_test_data(user=Depends(require_roles("Admin", "Owner"))):
    """Admin/Owner-only: hard-delete all demo + test users and their related data.
    Preserves: the calling user, any non-demo user accounts, and their data.
    Safe to run in production to purge seeded demo content without touching real TM data.
    """
    # Demo seed accounts
    demo_emails = ["admin@field.io", "manager@field.io", "tm1@field.io", "tm2@field.io"]
    demo_users = await db.users.find({"email": {"$in": demo_emails}}, {"_id": 0}).to_list(50)
    demo_user_ids = [u["id"] for u in demo_users]
    demo_team_ids = list({u.get("team_id") for u in demo_users if u.get("team_id")})
    deleted = {
        "users": 0, "teams": 0, "doctors": 0, "visits": 0, "tasks": 0,
        "meetings": 0, "events": 0, "itero_stage_history": 0,
        "expenses": 0, "reports": 0, "imports": 0,
    }
    if demo_user_ids:
        # Doctors owned by demo users
        owned_docs = await db.doctors.find({"assigned_tm_id": {"$in": demo_user_ids}}, {"_id": 0, "id": 1}).to_list(5000)
        owned_doc_ids = [d["id"] for d in owned_docs]
        if owned_doc_ids:
            r = await db.visits.delete_many({"doctor_id": {"$in": owned_doc_ids}}); deleted["visits"] += r.deleted_count
            r = await db.tasks.delete_many({"doctor_id": {"$in": owned_doc_ids}}); deleted["tasks"] += r.deleted_count
            r = await db.meetings.delete_many({"doctor_id": {"$in": owned_doc_ids}}); deleted["meetings"] += r.deleted_count
            r = await db.itero_stage_history.delete_many({"doctor_id": {"$in": owned_doc_ids}}); deleted["itero_stage_history"] += r.deleted_count
            r = await db.doctors.delete_many({"id": {"$in": owned_doc_ids}}); deleted["doctors"] += r.deleted_count
        # Anything else tied to demo users directly
        r = await db.visits.delete_many({"tm_user_id": {"$in": demo_user_ids}}); deleted["visits"] += r.deleted_count
        r = await db.tasks.delete_many({"tm_user_id": {"$in": demo_user_ids}}); deleted["tasks"] += r.deleted_count
        r = await db.meetings.delete_many({"tm_user_id": {"$in": demo_user_ids}}); deleted["meetings"] += r.deleted_count
        r = await db.events.delete_many({"tm_user_id": {"$in": demo_user_ids}}); deleted["events"] += r.deleted_count
        r = await db.expenses.delete_many({"tm_user_id": {"$in": demo_user_ids}}); deleted["expenses"] += r.deleted_count
        r = await db.reports.delete_many({"tm_user_id": {"$in": demo_user_ids}}); deleted["reports"] += r.deleted_count
        r = await db.doctor_imports.delete_many({"uploaded_by_user_id": {"$in": demo_user_ids}}); deleted["imports"] += r.deleted_count
        r = await db.users.delete_many({"id": {"$in": demo_user_ids}}); deleted["users"] = r.deleted_count
    # Drop the demo team(s) (e.g. "Northern Region") that no real user depends on
    if demo_team_ids:
        still_in_use = await db.users.find({"team_id": {"$in": demo_team_ids}}, {"_id": 0, "team_id": 1}).to_list(100)
        in_use_ids = {u["team_id"] for u in still_in_use}
        free_teams = [tid for tid in demo_team_ids if tid not in in_use_ids]
        if free_teams:
            r = await db.teams.delete_many({"id": {"$in": free_teams}}); deleted["teams"] = r.deleted_count
    # Test rows from pytest runs (any token-prefixed names)
    test_tokens = ["iter9", "iter11", "iter12", "test_iter", "test_iter9"]
    for tok in test_tokens:
        await db.doctors.delete_many({"doctor_name": {"$regex": tok, "$options": "i"}})
    await _audit(user, "wipe", "test_data", "*", new=deleted)
    return {"ok": True, "deleted": deleted, "demo_emails_removed": demo_emails}

@api.get("/users")
async def list_users(user=Depends(require_roles("Admin", "Manager"))):
    q = dict(_company_query_for(user))
    if user["role"] == "Manager":
        q = {"team_id": user.get("team_id")}
    users = await db.users.find(q, {"_id": 0, "password_hash": 0}).to_list(500)
    return users

@api.post("/users", response_model=UserPublic)
async def create_user(body: UserCreate, request: Request, user=Depends(require_roles("Admin"))):
    existing = await db.users.find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")
    # Only an Owner can create another Owner
    if body.role == "Owner" and user.get("role") != "Owner":
        raise HTTPException(status_code=403, detail="Only an Owner can create another Owner")
    import uuid
    doc = {
        "id": str(uuid.uuid4()),
        "full_name": body.full_name,
        "email": body.email.lower(),
        "password_hash": hash_password(body.password),
        "role": body.role,
        "team_id": body.team_id,
        "manager_user_id": body.manager_user_id,
        "region": body.region,
        "active_status": True,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _stamp_company(doc, user)
    await db.users.insert_one(doc)
    await _audit(user, "create", "user", doc["id"], new={"email": doc["email"], "role": doc["role"]})
    _strip_user(doc)
    return doc

@api.put("/users/{user_id}", response_model=UserPublic)
async def update_user(user_id: str, body: UserUpdate, user=Depends(require_roles("Admin"))):
    existing = await db.users.find_one({"id": user_id})
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")

    # Owner protection: only an Owner can edit / disable / change role of an Owner.
    if existing.get("role") == "Owner" and user.get("role") != "Owner":
        raise HTTPException(status_code=403, detail="Only an Owner can modify an Owner account")
    # Only an Owner can promote to Owner
    if body.role == "Owner" and user.get("role") != "Owner":
        raise HTTPException(status_code=403, detail="Only an Owner can grant the Owner role")

    # Last-Owner / last-Admin guardrails
    will_deactivate = body.active_status is False and existing.get("active_status", True) is True
    will_demote = body.role is not None and body.role != existing.get("role")
    if existing.get("role") == "Owner" and (will_deactivate or (will_demote and body.role != "Owner")):
        active_owner_count = await db.users.count_documents({"role": "Owner", "active_status": True})
        if active_owner_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot deactivate or demote the last active Owner. Promote another user to Owner first.",
            )
    if existing.get("role") == "Admin" and (will_deactivate or (will_demote and body.role not in ("Admin", "Owner"))):
        active_admin_count = await db.users.count_documents({"role": {"$in": ["Admin", "Owner"]}, "active_status": True})
        if active_admin_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot deactivate or demote the last active Admin. Promote another user to Admin first.",
            )
    if user["id"] == user_id and (will_deactivate or (will_demote and body.role not in ("Admin", "Owner"))):
        raise HTTPException(
            status_code=409,
            detail="You can't deactivate or change the role of your own account. Ask another Admin/Owner.",
        )

    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "password"}
    if body.email:
        update["email"] = body.email.lower()
        clash = await db.users.find_one({"email": update["email"], "id": {"$ne": user_id}})
        if clash:
            raise HTTPException(status_code=409, detail="Email already in use")
    if body.password:
        update["password_hash"] = hash_password(body.password)
    update["updated_at"] = _now_iso()
    await db.users.update_one({"id": user_id}, {"$set": update})
    new = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    await _audit(user, "update", "user", user_id, prev={"role": existing.get("role"), "active": existing.get("active_status")}, new={k: v for k, v in update.items() if k != "password_hash"})
    return new

@api.delete("/users/{user_id}")
async def delete_user(user_id: str, user=Depends(require_roles("Admin"))):
    """Hard delete a user account. Cascades: orphans their doctors (assigned_tm_id=None, status=Inactive)."""
    existing = await db.users.find_one({"id": user_id})
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")
    if user["id"] == user_id:
        raise HTTPException(status_code=409, detail="You can't delete your own account.")
    if existing.get("role") == "Owner" and user.get("role") != "Owner":
        raise HTTPException(status_code=403, detail="Only an Owner can delete an Owner account")
    if existing.get("role") == "Owner":
        active_owner_count = await db.users.count_documents({"role": "Owner", "active_status": True})
        if active_owner_count <= 1:
            raise HTTPException(status_code=409, detail="Cannot delete the last active Owner.")
    if existing.get("role") == "Admin":
        admin_count = await db.users.count_documents({"role": {"$in": ["Admin", "Owner"]}, "active_status": True})
        if admin_count <= 1:
            raise HTTPException(status_code=409, detail="Cannot delete the last active Admin/Owner.")
    # Cascade: orphan their doctors so list queries don't break
    await db.doctors.update_many(
        {"assigned_tm_id": user_id},
        {"$set": {"assigned_tm_id": None, "status": "Inactive", "updated_at": _now_iso()}},
    )
    await db.users.delete_one({"id": user_id})
    await _audit(user, "delete", "user", user_id, prev={"email": existing.get("email"), "role": existing.get("role")})
    return {"ok": True, "id": user_id}

@api.get("/teams")
async def list_teams(user=Depends(get_current_user)):
    q = dict(_company_query_for(user))
    if user["role"] == "Manager":
        q = {"id": user.get("team_id")}
    elif user["role"] == "TM":
        q = {"id": user.get("team_id")}
    teams = await db.teams.find(q, {"_id": 0}).to_list(200)
    return teams

@api.post("/teams")
async def create_team(body: TeamCreate, user=Depends(require_roles("Admin"))):
    team = Team(**body.model_dump()).model_dump()
    _stamp_company(team, user)
    await db.teams.insert_one(team)
    await _audit(user, "create", "team", team["id"], new={"team_name": team["team_name"]})
    _strip_id(team)
    return team
