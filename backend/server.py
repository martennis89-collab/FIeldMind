"""Field Intelligence Platform — main FastAPI server.

All routes are prefixed with /api.
"""
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Query, UploadFile, File, Form
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
import uuid
from typing import List, Optional, Literal
from pydantic import BaseModel

from auth import (
    hash_password,
    verify_password,
    create_token,
    get_current_user,
    require_roles,
    set_db as auth_set_db,
)
from models import (
    UserCreate,
    UserUpdate,
    UserPublic,
    LoginRequest,
    LoginResponse,
    TeamCreate,
    Team,
    DoctorCreate,
    DoctorUpdate,
    Doctor,
    VisitCreate,
    Visit,
    AnalyzeNoteRequest,
    TaskCreate,
    TaskUpdate,
    Task,
    AIExtraction,
    CommercialActions,
    IteroActions,
    InvisalignActions,
    WeeklyReport,
    ReportCreate,
    ReportUpdate,
    ReportContent,
    ReportComment,
    ExpenseUpdate,
    Meeting,
    MeetingCreate,
    MeetingUpdate,
    Event,
    EventCreate,
    EventUpdate,
    IteroStage,
    IteroStageUpdate,
    ITERO_STAGE_RANK,
)
from ai import analyze_note as ai_analyze_note
from seed import seed_demo, seed_owner

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---------- Mongo ----------
mongo_url = os.environ["MONGO_URL"]
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ["DB_NAME"]]
auth_set_db(db)

app = FastAPI(title="Field Intelligence Platform")
api = APIRouter(prefix="/api")

# Cadence defaults (days)
DEFAULT_CADENCE = {"New": 30, "Lapsed": 90, "Occasional": 60, "Active": 45, "Engaged": 30, "Expert": 21}


# ---------- helpers ----------
def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _strip_id(d):
    if isinstance(d, dict):
        d.pop("_id", None)
    return d


def _strip_user(u):
    _strip_id(u)
    if u:
        u.pop("password_hash", None)
    return u


async def _audit(user, action_type, entity_type, entity_id=None, prev=None, new=None, ip=None):
    doc = {
        "id": __import__("uuid").uuid4().hex,
        "user_id": user["id"] if user else None,
        "user_email": user["email"] if user else None,
        "action_type": action_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "timestamp": _now_iso(),
        "previous_value": prev,
        "new_value": new,
        "ip": ip,
    }
    await db.audit_logs.insert_one(doc)


async def _doctor_query_for(user) -> dict:
    """Return base mongo query enforcing access scope."""
    if user["role"] == "Admin":
        return {}
    if user["role"] == "Manager":
        return {"team_id": user.get("team_id")}
    # TM
    return {"assigned_tm_id": user["id"]}


async def _can_access_doctor(user, doctor) -> bool:
    if not doctor:
        return False
    if user["role"] == "Admin":
        return True
    if user["role"] == "Manager":
        return doctor.get("team_id") == user.get("team_id")
    return doctor.get("assigned_tm_id") == user["id"]


def _cadence_status(days_since: Optional[int], segment: str) -> str:
    if days_since is None:
        return "Critical"  # never visited
    target = DEFAULT_CADENCE.get(segment, 45)
    if days_since <= target:
        return "Good"
    if days_since <= target * 1.2:
        return "Due Soon"
    if days_since <= target * 1.6:
        return "Overdue"
    return "Critical"


def _priority_score(doctor, last_visit_date, days_since, open_promises, overdue_promises, sentiment, opportunity, top_topics):
    score = 0
    # segment importance
    seg = doctor.get("segment", "Occasional")
    score += {"New": 8, "Lapsed": 12, "Occasional": 5, "Active": 15, "Engaged": 25, "Expert": 35}.get(seg, 10)
    # cadence
    target = DEFAULT_CADENCE.get(seg, 45)
    if days_since is None:
        score += 25
    else:
        ratio = days_since / max(target, 1)
        if ratio > 1:
            score += min(int((ratio - 1) * 30), 30)
    # promises
    score += min(open_promises * 4, 12)
    score += min(overdue_promises * 8, 24)
    # sentiment negative weight
    if sentiment in ("Negative", "Very Negative"):
        score += 12
    # opportunity
    if opportunity == "Advancing":
        score += 10
    elif opportunity == "Stuck":
        score += 6
    # certification / event interest topics
    high_signal_topics = {"Certification interest", "Event invitation", "Peer-to-peer", "iTero demo"}
    if any(t in high_signal_topics for t in (top_topics or [])):
        score += 8
    return max(0, min(score, 100))


def _priority_label(score: int) -> str:
    if score >= 75:
        return "Critical"
    if score >= 55:
        return "High"
    if score >= 30:
        return "Medium"
    return "Low"


async def _enrich_doctor(doctor: dict) -> dict:
    """Add computed fields to a doctor dict."""
    doc_id = doctor["id"]
    # last visit
    last_visit = await db.visits.find_one(
        {"doctor_id": doc_id}, {"_id": 0}, sort=[("visit_date", -1)]
    )
    last_visit_date = last_visit["visit_date"] if last_visit else None
    days_since = None
    if last_visit_date:
        try:
            d = datetime.fromisoformat(last_visit_date.replace("Z", "+00:00"))
            days_since = (datetime.now(timezone.utc) - d).days
        except Exception:
            days_since = None

    # quarter visit count
    quarter_start = datetime.now(timezone.utc) - timedelta(days=90)
    visit_count_q = await db.visits.count_documents(
        {"doctor_id": doc_id, "visit_date": {"$gte": quarter_start.isoformat()}}
    )

    # tasks
    open_promises = await db.tasks.count_documents(
        {"doctor_id": doc_id, "status": {"$in": ["Open", "Overdue"]}}
    )
    today = datetime.now(timezone.utc).date().isoformat()
    overdue_promises = await db.tasks.count_documents(
        {
            "doctor_id": doc_id,
            "status": {"$in": ["Open", "Overdue"]},
            "due_date": {"$lt": today},
        }
    )

    # last 5 visits for top topics/barriers/sentiment trend
    recent = await db.visits.find(
        {"doctor_id": doc_id}, {"_id": 0}
    ).sort("visit_date", -1).to_list(10)

    topic_counts: dict = {}
    barrier_counts: dict = {}
    sentiments: list = []
    for v in recent:
        for t in (v.get("confirmed_topics") or []):
            topic_counts[t] = topic_counts.get(t, 0) + 1
        for b in (v.get("confirmed_barriers") or []):
            barrier_counts[b] = barrier_counts.get(b, 0) + 1
        if v.get("sentiment"):
            sentiments.append(v["sentiment"])

    top_topics = [t for t, _ in sorted(topic_counts.items(), key=lambda x: -x[1])[:3]]
    top_barriers = [b for b, _ in sorted(barrier_counts.items(), key=lambda x: -x[1])[:3]]
    current_sentiment = sentiments[0] if sentiments else None

    sentiment_map = {"Very Negative": 1, "Negative": 2, "Neutral": 3, "Positive": 4, "Very Positive": 5}
    sentiment_trend = "stable"
    if len(sentiments) >= 2:
        recent_score = sum(sentiment_map.get(s, 3) for s in sentiments[:2]) / 2
        older_score = sum(sentiment_map.get(s, 3) for s in sentiments[2:5]) / max(len(sentiments[2:5]), 1) if len(sentiments) > 2 else recent_score
        if recent_score > older_score + 0.4:
            sentiment_trend = "improving"
        elif recent_score < older_score - 0.4:
            sentiment_trend = "declining"

    cadence = _cadence_status(days_since, doctor.get("segment", "Occasional"))
    score = _priority_score(
        doctor, last_visit_date, days_since, open_promises, overdue_promises,
        current_sentiment, last_visit.get("opportunity_state") if last_visit else None,
        top_topics,
    )

    # Commercial state derived across all visits for this doctor
    commercial = _aggregate_commercial(recent)
    itero_visits = [v for v in recent if v.get("track_type", "BOTH") in ("ITERO", "BOTH")]
    invisalign_visits = [v for v in recent if v.get("track_type", "BOTH") in ("INVISALIGN", "BOTH")]
    itero_state = _aggregate_itero(itero_visits)
    invisalign_state = _aggregate_invisalign(invisalign_visits)

    enriched = {
        **doctor,
        "last_visit_date": last_visit_date,
        "days_since_last_visit": days_since,
        "visits_this_quarter": visit_count_q,
        "open_promises": open_promises,
        "overdue_promises": overdue_promises,
        "current_sentiment": current_sentiment,
        "sentiment_trend": sentiment_trend,
        "top_topics": top_topics,
        "top_barriers": top_barriers,
        "cadence_status": cadence,
        "cadence_target_days": DEFAULT_CADENCE.get(doctor.get("segment", "Occasional"), 45),
        "visit_priority_score": score,
        "visit_priority_label": _priority_label(score),
        "suggested_next_action": last_visit.get("next_step") if last_visit else None,
        "commercial_state": commercial,
        "itero_state": itero_state,
        "invisalign_state": invisalign_state,
    }
    return enriched


def _aggregate_itero(visits: list) -> dict:
    """Track iTero-only state: demo funnel + scanner interest/concerns."""
    state = {
        "demo_discussed": False,
        "demo_booked": False,
        "demo_completed": False,
        "demo_booked_date": None,
        "demo_completed_date": None,
        "demo_pending": False,
        "scanner_interest_level": "None",
        "scanner_concerns": [],
        "has_itero_activity": False,
    }
    interest_rank = {"None": 0, "Low": 1, "Medium": 2, "High": 3}
    best_rank = 0
    concerns_set: set = set()
    for v in visits or []:
        ia = v.get("itero_actions") or {}
        # Backward-compat: some old visits stored demo_* on commercial_actions
        legacy = v.get("commercial_actions") or {}
        for k in ("demo_discussed", "demo_booked", "demo_completed"):
            if ia.get(k) or legacy.get(k):
                state[k] = True
                state["has_itero_activity"] = True
        for k in ("demo_booked_date", "demo_completed_date"):
            d = ia.get(k) or legacy.get(k)
            if d and not state[k]:
                state[k] = d
        sil = ia.get("scanner_interest_level") or "None"
        if interest_rank.get(sil, 0) > best_rank:
            best_rank = interest_rank[sil]
            state["scanner_interest_level"] = sil
        for c in (ia.get("scanner_concerns") or []):
            concerns_set.add(c)
    state["scanner_concerns"] = list(concerns_set)[:8]
    state["demo_pending"] = state["demo_booked"] and not state["demo_completed"]
    return state


def _aggregate_invisalign(visits: list) -> dict:
    """Track Invisalign-only state: growth/certification/TPS/P2P/training/confidence."""
    state = {
        "growth_program_explained": False,
        "certification_interest": False,
        "tps_discussed": False,
        "p2p_suggested": False,
        "staff_training_needed": False,
        "clinical_confidence": "Unknown",
        "business_confidence": "Unknown",
        "patient_affordability_perception": "Unknown",
        "has_invisalign_activity": False,
    }
    conf_rank = {"Unknown": 0, "Low": 1, "Medium": 2, "High": 3}
    aff_rank = {"Unknown": 0, "Concerned": 1, "Neutral": 2, "Confident": 3}
    best_clin = 0
    best_biz = 0
    best_aff = 0
    for v in visits or []:
        inv = v.get("invisalign_actions") or {}
        legacy = v.get("commercial_actions") or {}
        # Booleans
        for k in ("growth_program_explained", "certification_interest", "tps_discussed",
                  "p2p_suggested", "staff_training_needed"):
            if inv.get(k) or legacy.get(k):
                state[k] = True
                state["has_invisalign_activity"] = True
        # Confidence (take latest highest-known)
        cc = inv.get("clinical_confidence")
        if cc and conf_rank.get(cc, 0) > best_clin:
            best_clin = conf_rank[cc]
            state["clinical_confidence"] = cc
            state["has_invisalign_activity"] = True
        bc = inv.get("business_confidence")
        if bc and conf_rank.get(bc, 0) > best_biz:
            best_biz = conf_rank[bc]
            state["business_confidence"] = bc
            state["has_invisalign_activity"] = True
        ap = inv.get("patient_affordability_perception")
        if ap and aff_rank.get(ap, 0) > best_aff:
            best_aff = aff_rank[ap]
            state["patient_affordability_perception"] = ap
            state["has_invisalign_activity"] = True
    return state


def _aggregate_commercial(visits: list) -> dict:
    """Aggregate commercial actions across a doctor's visit list. Returns derived state."""
    state = {
        "demo_discussed": False, "demo_booked": False, "demo_completed": False,
        "demo_booked_date": None, "demo_completed_date": None,
        "boost_discussed": False, "trade_in_discussed": False, "trade_in_interest": False,
        "growth_program_explained": False,
        "proposal_discussed": False, "proposal_sent": False, "proposal_sent_date": None,
        "proposal_follow_up_done": False,
        "days_since_proposal": None,
        "demo_pending": False,           # booked but not completed
        "proposal_unfollowed": False,    # sent but no follow-up
    }
    latest_proposal_sent = None
    proposal_follow_up_after = False
    for v in visits or []:
        ca = v.get("commercial_actions") or {}
        for k in ("demo_discussed", "demo_booked", "demo_completed",
                  "boost_discussed", "trade_in_discussed", "trade_in_interest",
                  "growth_program_explained", "proposal_discussed", "proposal_sent",
                  "proposal_follow_up_done"):
            if ca.get(k):
                state[k] = True
        if ca.get("demo_booked_date") and not state["demo_booked_date"]:
            state["demo_booked_date"] = ca.get("demo_booked_date")
        if ca.get("demo_completed_date") and not state["demo_completed_date"]:
            state["demo_completed_date"] = ca.get("demo_completed_date")
        if ca.get("proposal_sent_date"):
            d = ca.get("proposal_sent_date")
            if (latest_proposal_sent is None) or d > latest_proposal_sent:
                latest_proposal_sent = d
                proposal_follow_up_after = bool(ca.get("proposal_follow_up_done"))
        if ca.get("proposal_follow_up_done"):
            proposal_follow_up_after = True

    state["proposal_sent_date"] = latest_proposal_sent
    if latest_proposal_sent:
        try:
            d = datetime.fromisoformat(latest_proposal_sent)
            state["days_since_proposal"] = (datetime.now(timezone.utc).date() - d.date()).days
        except Exception:
            state["days_since_proposal"] = None
    state["demo_pending"] = state["demo_booked"] and not state["demo_completed"]
    state["proposal_unfollowed"] = state["proposal_sent"] and not proposal_follow_up_after
    return state


# ====================================================
# AUTH
# ====================================================
@api.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request):
    user = await db.users.find_one({"email": body.email.lower()})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.get("active_status", True):
        raise HTTPException(status_code=403, detail="User is deactivated")
    token = create_token(user["id"], user["role"], user["email"])
    _strip_user(user)
    await _audit(user, "login", "user", user["id"], ip=request.client.host if request.client else None)
    return {"token": token, "user": user}


@api.get("/auth/me", response_model=UserPublic)
async def me(user=Depends(get_current_user)):
    return _strip_user(user)


@api.post("/auth/logout")
async def logout(request: Request, user=Depends(get_current_user)):
    await _audit(user, "logout", "user", user["id"], ip=request.client.host if request.client else None)
    return {"ok": True}


# ====================================================
# SEED (open — but idempotent + safe; no-op if admin already exists)
# ====================================================
@api.post("/seed/init")
async def seed_init():
    report = await seed_demo(db)
    return report


@api.post("/admin/wipe-test-data")
async def wipe_test_data(user=Depends(require_roles("Owner"))):
    """Owner-only: hard-delete all demo + test users and their related data.
    Preserves: the calling Owner, any non-demo user accounts, and their data.
    """
    # Demo seed accounts
    demo_emails = ["admin@field.io", "manager@field.io", "tm1@field.io", "tm2@field.io"]
    demo_users = await db.users.find({"email": {"$in": demo_emails}}, {"_id": 0}).to_list(50)
    demo_user_ids = [u["id"] for u in demo_users]
    deleted = {"users": 0, "doctors": 0, "visits": 0, "tasks": 0, "expenses": 0, "reports": 0, "imports": 0}
    if demo_user_ids:
        # Doctors owned by demo users
        owned_docs = await db.doctors.find({"assigned_tm_id": {"$in": demo_user_ids}}, {"_id": 0, "id": 1}).to_list(5000)
        owned_doc_ids = [d["id"] for d in owned_docs]
        if owned_doc_ids:
            r1 = await db.visits.delete_many({"doctor_id": {"$in": owned_doc_ids}}); deleted["visits"] += r1.deleted_count
            r2 = await db.tasks.delete_many({"doctor_id": {"$in": owned_doc_ids}}); deleted["tasks"] += r2.deleted_count
            r3 = await db.doctors.delete_many({"id": {"$in": owned_doc_ids}}); deleted["doctors"] += r3.deleted_count
        # Anything else tied to demo users
        r4 = await db.visits.delete_many({"tm_user_id": {"$in": demo_user_ids}}); deleted["visits"] += r4.deleted_count
        r5 = await db.tasks.delete_many({"tm_user_id": {"$in": demo_user_ids}}); deleted["tasks"] += r5.deleted_count
        r6 = await db.expenses.delete_many({"tm_user_id": {"$in": demo_user_ids}}); deleted["expenses"] = r6.deleted_count
        r7 = await db.reports.delete_many({"tm_user_id": {"$in": demo_user_ids}}); deleted["reports"] = r7.deleted_count
        r8 = await db.doctor_imports.delete_many({"uploaded_by_user_id": {"$in": demo_user_ids}}); deleted["imports"] = r8.deleted_count
        r9 = await db.users.delete_many({"id": {"$in": demo_user_ids}}); deleted["users"] = r9.deleted_count
    # Test rows from pytest runs (any token-prefixed names)
    test_tokens = ["iter9", "iter11", "iter12", "test_iter", "test_iter9"]
    for tok in test_tokens:
        # Doctors
        await db.doctors.delete_many({"doctor_name": {"$regex": tok, "$options": "i"}})
    await _audit(user, "wipe", "test_data", "*", new=deleted)
    return {"ok": True, "deleted": deleted, "demo_emails_removed": demo_emails}


# ====================================================
# USERS (admin)
# ====================================================
@api.get("/users")
async def list_users(user=Depends(require_roles("Admin", "Manager"))):
    q = {}
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


# ====================================================
# TEAMS
# ====================================================
@api.get("/teams")
async def list_teams(user=Depends(get_current_user)):
    q = {}
    if user["role"] == "Manager":
        q = {"id": user.get("team_id")}
    elif user["role"] == "TM":
        q = {"id": user.get("team_id")}
    teams = await db.teams.find(q, {"_id": 0}).to_list(200)
    return teams


@api.post("/teams")
async def create_team(body: TeamCreate, user=Depends(require_roles("Admin"))):
    team = Team(**body.model_dump()).model_dump()
    await db.teams.insert_one(team)
    await _audit(user, "create", "team", team["id"], new={"team_name": team["team_name"]})
    _strip_id(team)
    return team


# ====================================================
# DOCTORS
# ====================================================
@api.get("/doctors")
async def list_doctors(
    segment: Optional[str] = None,
    city: Optional[str] = None,
    cadence: Optional[str] = None,
    sentiment: Optional[str] = None,
    assigned_tm_id: Optional[str] = None,
    q: Optional[str] = None,
    user=Depends(get_current_user),
):
    base = await _doctor_query_for(user)
    if segment:
        base["segment"] = segment
    if city:
        base["city"] = city
    if assigned_tm_id and user["role"] in ("Admin", "Manager"):
        base["assigned_tm_id"] = assigned_tm_id
    if q:
        base["$or"] = [
            {"doctor_name": {"$regex": q, "$options": "i"}},
            {"clinic_name": {"$regex": q, "$options": "i"}},
            {"city": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.doctors.find(base, {"_id": 0}).to_list(500)
    enriched = [await _enrich_doctor(d) for d in docs]
    if cadence:
        enriched = [d for d in enriched if d["cadence_status"] == cadence]
    if sentiment:
        enriched = [d for d in enriched if d.get("current_sentiment") == sentiment]
    enriched.sort(key=lambda d: d["visit_priority_score"], reverse=True)
    return enriched


@api.post("/doctors")
async def create_doctor(body: DoctorCreate, user=Depends(require_roles("Admin", "Manager", "TM"))):
    doc = Doctor(**body.model_dump()).model_dump()
    if user["role"] == "TM":
        # TM creates a doctor for themselves
        doc["assigned_tm_id"] = user["id"]
        doc["team_id"] = user.get("team_id")
    elif user["role"] == "Manager" and not doc.get("team_id"):
        doc["team_id"] = user.get("team_id")
    await db.doctors.insert_one(doc)
    await _audit(user, "create", "doctor", doc["id"], new={"doctor_name": doc["doctor_name"]})
    _strip_id(doc)
    return await _enrich_doctor(doc)


# ====================================================
# DOCTOR IMPORT (xlsx / csv)
# ====================================================
@api.get("/doctors/import/template")
async def download_doctor_template(format: str = "xlsx", user=Depends(get_current_user)):
    """Downloadable template with sample row. CSV or XLSX."""
    from fastapi.responses import Response
    from imports import build_template_csv, build_template_xlsx

    fmt = (format or "xlsx").lower()
    if fmt == "csv":
        body = build_template_csv()
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="doctor_import_template.csv"'},
        )
    if fmt == "xlsx":
        body = build_template_xlsx()
        return Response(
            content=body,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="doctor_import_template.xlsx"'},
        )
    raise HTTPException(status_code=400, detail="format must be 'csv' or 'xlsx'")


@api.post("/doctors/import/preview")
async def preview_doctor_import(file: UploadFile = File(...), user=Depends(require_roles("Admin", "TM"))):
    """Parse an uploaded sheet, return detected columns + suggested mapping + sample rows.

    The frontend then sends these rows back through `/doctors/import/commit` after the user
    confirms / edits the column mapping.
    """
    from imports import parse_upload, auto_map_headers, TARGET_FIELDS

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds 5 MB limit")
    parsed = parse_upload(file.filename or "", raw)
    headers = parsed["headers"]
    rows = parsed["rows"]
    if not headers or not rows:
        raise HTTPException(status_code=400, detail="No data rows detected")
    if len(rows) > 5000:
        raise HTTPException(status_code=413, detail="Too many rows (max 5000) — split your file")
    suggested = auto_map_headers(headers)
    return {
        "filename": file.filename,
        "headers": headers,
        "row_count": len(rows),
        "sample_rows": rows[:5],
        "rows": rows,
        "suggested_mapping": suggested,
        "target_fields": TARGET_FIELDS,
    }


@api.post("/doctors/import/commit")
async def commit_doctor_import(body: dict, user=Depends(require_roles("Admin", "TM"))):
    """Commit a previewed import.

    Body:
      filename: str
      mapping: {target_field -> source_header}  (source can be None)
      rows: [{header: cell, ...}]
      duplicate_strategy: "skip" | "update" | "import"   (default "skip")
      assigned_tm_id: optional (Admin only — overrides default TM)
    """
    import uuid
    from imports import validate_and_project

    filename = (body or {}).get("filename") or "upload"
    mapping = (body or {}).get("mapping") or {}
    rows = (body or {}).get("rows") or []
    strategy = ((body or {}).get("duplicate_strategy") or "skip").lower()
    if strategy not in ("skip", "update", "import"):
        raise HTTPException(status_code=400, detail="duplicate_strategy must be 'skip', 'update', or 'import'")

    # Determine assigned TM
    assigned_tm_id = (body or {}).get("assigned_tm_id")
    if user["role"] == "TM":
        assigned_tm_id = user["id"]
    elif user["role"] == "Admin":
        if not assigned_tm_id:
            raise HTTPException(status_code=400, detail="assigned_tm_id is required for Admin imports")

    target_user = await db.users.find_one({"id": assigned_tm_id, "role": "TM"}, {"_id": 0})
    if not target_user:
        raise HTTPException(status_code=400, detail="Target TM not found")
    target_team_id = target_user.get("team_id")

    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail="No rows provided")
    if len(rows) > 5000:
        raise HTTPException(status_code=413, detail="Too many rows (max 5000)")

    validated = validate_and_project(rows, mapping)

    # Pre-fetch existing doctors for this TM for duplicate detection
    existing_docs = await db.doctors.find(
        {"assigned_tm_id": assigned_tm_id},
        {"_id": 0, "id": 1, "doctor_name": 1, "clinic_name": 1, "city": 1},
    ).to_list(5000)

    def key1(name, city):
        return f"{(name or '').strip().lower()}|{(city or '').strip().lower()}"

    def key2(clinic, city):
        return f"{(clinic or '').strip().lower()}|{(city or '').strip().lower()}"

    name_city = {key1(d.get("doctor_name"), d.get("city")): d for d in existing_docs}
    clinic_city = {key2(d.get("clinic_name"), d.get("city")): d for d in existing_docs if d.get("clinic_name")}

    created = []
    updated = []
    skipped = []
    failed = []
    now = _now_iso()
    for v in validated:
        if v["errors"]:
            failed.append({"row_index": v["row_index"], "errors": v["errors"]})
            continue
        p = v["projected"]
        # find duplicate
        dup = None
        if p.get("doctor_name") and p.get("city"):
            dup = name_city.get(key1(p["doctor_name"], p["city"]))
        if not dup and p.get("clinic_name") and p.get("city"):
            dup = clinic_city.get(key2(p["clinic_name"], p["city"]))

        doc_payload = {
            "doctor_name": p["doctor_name"],
            "clinic_name": p.get("clinic_name"),
            "city": p.get("city"),
            "region": p.get("region"),
            "doctor_type": p.get("doctor_type") or "GP",
            "segment": p.get("segment") or "Occasional",
            "general_notes": p.get("general_notes"),
        }

        if dup:
            if strategy == "skip":
                skipped.append({"row_index": v["row_index"], "doctor_name": p["doctor_name"], "duplicate_id": dup["id"], "reason": "duplicate"})
                continue
            if strategy == "update":
                # keep existing id, refresh fields
                upd = {k: vv for k, vv in doc_payload.items() if vv is not None}
                upd["updated_at"] = now
                await db.doctors.update_one({"id": dup["id"]}, {"$set": upd})
                updated.append({"row_index": v["row_index"], "doctor_id": dup["id"], "doctor_name": p["doctor_name"]})
                continue
            # strategy == "import": fall through and create a fresh row

        new_id = str(uuid.uuid4())
        new_doc = {
            "id": new_id,
            **doc_payload,
            "assigned_tm_id": assigned_tm_id,
            "team_id": target_team_id,
            "status": "Active",
            "created_at": now,
            "updated_at": now,
        }
        await db.doctors.insert_one(new_doc)
        created.append({"row_index": v["row_index"], "doctor_id": new_id, "doctor_name": p["doctor_name"]})
        # Update local indexes so duplicates inside the same import are caught
        if p.get("doctor_name") and p.get("city"):
            name_city[key1(p["doctor_name"], p["city"])] = {"id": new_id, **doc_payload}
        if p.get("clinic_name") and p.get("city"):
            clinic_city[key2(p["clinic_name"], p["city"])] = {"id": new_id, **doc_payload}

    import_id = str(uuid.uuid4())
    summary = {
        "id": import_id,
        "filename": filename,
        "uploaded_by_user_id": user["id"],
        "uploaded_by_email": user.get("email"),
        "assigned_tm_id": assigned_tm_id,
        "assigned_tm_name": target_user.get("full_name"),
        "row_count": len(rows),
        "created_count": len(created),
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "duplicate_strategy": strategy,
        "details": {"created": created, "updated": updated, "skipped": skipped, "failed": failed},
        "created_at": now,
    }
    await db.doctor_imports.insert_one(summary)
    summary.pop("_id", None)
    await _audit(user, "import", "doctors", import_id, new={
        "row_count": len(rows), "created": len(created), "updated": len(updated),
        "skipped": len(skipped), "failed": len(failed),
    })
    return summary


@api.get("/admin/doctor-imports")
async def list_doctor_imports(limit: int = 50, user=Depends(require_roles("Admin"))):
    rows = await db.doctor_imports.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"imports": rows}


@api.get("/doctors/{doctor_id}")
async def get_doctor(doctor_id: str, user=Depends(get_current_user)):
    doc = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doc or not await _can_access_doctor(user, doc):
        raise HTTPException(status_code=404, detail="Doctor not found")
    return await _enrich_doctor(doc)


@api.put("/doctors/{doctor_id}")
async def update_doctor(doctor_id: str, body: DoctorUpdate, user=Depends(require_roles("Admin", "Manager", "TM"))):
    existing = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not existing or not await _can_access_doctor(user, existing):
        raise HTTPException(status_code=404, detail="Doctor not found")
    if user["role"] == "TM":
        # TM may only update general_notes / status
        allowed = {k: v for k, v in body.model_dump(exclude_none=True).items() if k in ("general_notes", "status")}
        update = allowed
    else:
        update = body.model_dump(exclude_none=True)
    update["updated_at"] = _now_iso()
    await db.doctors.update_one({"id": doctor_id}, {"$set": update})
    new = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    await _audit(user, "update", "doctor", doctor_id, prev=existing, new=new)
    return await _enrich_doctor(new)


@api.delete("/doctors/{doctor_id}")
async def delete_doctor(doctor_id: str, user=Depends(require_roles("Admin", "TM"))):
    existing = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Doctor not found")
    # TM can only delete doctors assigned to them
    if user["role"] == "TM" and existing.get("assigned_tm_id") != user["id"]:
        raise HTTPException(status_code=403, detail="You can only delete your own doctors")
    await db.doctors.delete_one({"id": doctor_id})
    # Cascade-clean owned visits & tasks so they don't orphan
    await db.visits.delete_many({"doctor_id": doctor_id})
    await db.tasks.update_many(
        {"doctor_id": doctor_id, "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]},
        {"$set": {"deleted_at": _now_iso(), "deleted_by": user["id"]}},
    )
    await _audit(user, "delete", "doctor", doctor_id, prev=existing)
    return {"ok": True, "id": doctor_id}


@api.post("/doctors/bulk-delete")
async def bulk_delete_doctors(body: dict, user=Depends(require_roles("Admin", "TM"))):
    """Delete multiple doctors in one go. TM can only delete doctors assigned to them."""
    ids = (body or {}).get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids must be a non-empty list")
    if len(ids) > 1000:
        raise HTTPException(status_code=400, detail="Too many ids (max 1000)")
    q = {"id": {"$in": ids}}
    if user["role"] == "TM":
        q["assigned_tm_id"] = user["id"]
    existing = await db.doctors.find(q, {"_id": 0}).to_list(1000)
    deletable_ids = [d["id"] for d in existing]
    if not deletable_ids:
        return {"deleted_count": 0, "deleted_ids": [], "skipped_ids": ids}
    await db.doctors.delete_many({"id": {"$in": deletable_ids}})
    await db.visits.delete_many({"doctor_id": {"$in": deletable_ids}})
    await db.tasks.update_many(
        {"doctor_id": {"$in": deletable_ids}, "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]},
        {"$set": {"deleted_at": _now_iso(), "deleted_by": user["id"]}},
    )
    for d in existing:
        await _audit(user, "delete", "doctor", d["id"], prev=d)
    skipped = [i for i in ids if i not in deletable_ids]
    return {"deleted_count": len(deletable_ids), "deleted_ids": deletable_ids, "skipped_ids": skipped}


@api.get("/doctors/{doctor_id}/visits")
async def get_doctor_visits(doctor_id: str, user=Depends(get_current_user)):
    doc = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doc or not await _can_access_doctor(user, doc):
        raise HTTPException(status_code=404, detail="Doctor not found")
    visits = await db.visits.find({"doctor_id": doctor_id}, {"_id": 0}).sort("visit_date", -1).to_list(200)
    return visits


@api.get("/doctors/{doctor_id}/tasks")
async def get_doctor_tasks(doctor_id: str, user=Depends(get_current_user)):
    doc = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doc or not await _can_access_doctor(user, doc):
        raise HTTPException(status_code=404, detail="Doctor not found")
    tasks = await db.tasks.find({
        "doctor_id": doctor_id,
        "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}],
    }, {"_id": 0}).sort("due_date", 1).to_list(200)
    return tasks


@api.get("/doctors/{doctor_id}/prepare")
async def prepare_visit(doctor_id: str, user=Depends(get_current_user)):
    doc = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doc or not await _can_access_doctor(user, doc):
        raise HTTPException(status_code=404, detail="Doctor not found")
    enriched = await _enrich_doctor(doc)
    visits = await db.visits.find({"doctor_id": doctor_id}, {"_id": 0}).sort("visit_date", -1).to_list(3)
    open_tasks = await db.tasks.find(
        {"doctor_id": doctor_id, "status": {"$in": ["Open", "Overdue"]},
         "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]}, {"_id": 0}
    ).sort("due_date", 1).to_list(50)
    today = datetime.now(timezone.utc).date().isoformat()
    overdue = [t for t in open_tasks if t.get("due_date") and t["due_date"] < today]
    talking_points = []
    if enriched.get("top_barriers"):
        talking_points.append(f"Address main barrier: {enriched['top_barriers'][0]}")
    if enriched.get("top_topics"):
        talking_points.append(f"Continue topic: {enriched['top_topics'][0]}")
    if overdue:
        talking_points.append(f"Resolve overdue promise: {overdue[0]['task_title']}")
    return {
        "doctor": enriched,
        "recent_visits": visits,
        "open_promises": open_tasks,
        "overdue_promises": overdue,
        "talking_points": talking_points,
        "suggested_reason": _suggested_reason(enriched, overdue),
    }


def _suggested_reason(enriched, overdue):
    if overdue:
        return f"Overdue promise needs resolution: {overdue[0]['task_title']}"
    if enriched["cadence_status"] in ("Overdue", "Critical"):
        return f"{enriched['segment']} doctor overdue by ~{(enriched['days_since_last_visit'] or 0) - enriched['cadence_target_days']} days"
    if enriched.get("current_sentiment") in ("Negative", "Very Negative"):
        return "Negative sentiment unresolved — visit to recover relationship"
    if "Certification interest" in (enriched.get("top_topics") or []):
        return "Doctor showed certification interest — close the loop"
    return "Routine check-in based on segment cadence"


# ====================================================
# VISITS
# ====================================================
@api.post("/visits/analyze")
async def analyze_visit_note(body: AnalyzeNoteRequest, user=Depends(get_current_user)):
    result = await ai_analyze_note(body.note, session_id=f"analyze-{user['id']}")
    return result


@api.post("/visits/transcribe")
async def transcribe_visit_audio(audio: UploadFile = File(...), user=Depends(get_current_user)):
    """Transcribe an uploaded audio clip (TM voice memo) into text using OpenAI Whisper.

    Accepts a multipart upload with field name 'audio'. Supported formats: webm, mp3, m4a, wav, mp4, mpga, mpeg.
    Max 25 MB (Whisper limit). Returns {text: str}.
    """
    import io
    from emergentintegrations.llm.openai import OpenAISpeechToText

    if not os.environ.get("EMERGENT_LLM_KEY"):
        raise HTTPException(status_code=503, detail="Transcription service not configured")

    # Read into memory and validate size
    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio file")
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file exceeds 25 MB limit")

    filename = audio.filename or "voice.webm"
    # Wrap bytes so the SDK can read it as a file-like with a .name attribute
    buf = io.BytesIO(raw)
    buf.name = filename

    try:
        stt = OpenAISpeechToText(api_key=os.environ["EMERGENT_LLM_KEY"])
        response = await stt.transcribe(file=buf, model="whisper-1", response_format="json")
        text = getattr(response, "text", "") or ""
    except Exception:
        logging.exception("Whisper transcription failed")
        raise HTTPException(status_code=502, detail="Transcription service unavailable")

    await _audit(user, "transcribe", "visit", "audio", new={"chars": len(text)})
    return {"text": text.strip()}


@api.post("/visits")
async def create_visit(body: VisitCreate, user=Depends(get_current_user)):
    doctor = await db.doctors.find_one({"id": body.doctor_id}, {"_id": 0})
    if not doctor or not await _can_access_doctor(user, doctor):
        raise HTTPException(status_code=404, detail="Doctor not found")
    import uuid
    vdate = body.visit_date or _now_iso()
    visit = {
        "id": str(uuid.uuid4()),
        "doctor_id": body.doctor_id,
        "tm_user_id": user["id"],
        "team_id": user.get("team_id") or doctor.get("team_id"),
        "visit_date": vdate,
        "visit_type": body.visit_type,
        "track_type": body.track_type or "BOTH",
        "free_text_note": body.free_text_note,
        "confirmed_topics": body.confirmed_topics,
        "confirmed_barriers": body.confirmed_barriers,
        "sentiment": body.sentiment,
        "opportunity_state": body.opportunity_state,
        "next_step": body.next_step,
        "ai_extraction": body.ai_extraction.model_dump() if body.ai_extraction else None,
        "itero_actions": body.itero_actions.model_dump() if body.itero_actions else IteroActions().model_dump(),
        "invisalign_actions": body.invisalign_actions.model_dump() if body.invisalign_actions else InvisalignActions().model_dump(),
        "commercial_actions": body.commercial_actions.model_dump() if body.commercial_actions else CommercialActions().model_dump(),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.visits.insert_one(visit)
    await _audit(user, "create", "visit", visit["id"], new={"doctor_id": body.doctor_id, "sentiment": body.sentiment})

    # Auto-advance iTero pipeline stage based on the latest visit's signals.
    await _auto_advance_itero_stage(body.doctor_id, body.itero_actions, body.commercial_actions, user)

    # Auto-link meeting -> Completed when visit logged from a booked meeting
    if body.meeting_id:
        m = await db.meetings.find_one({"id": body.meeting_id, "tm_user_id": user["id"]}, {"_id": 0})
        if m and m.get("status") == "Scheduled":
            await db.meetings.update_one(
                {"id": body.meeting_id},
                {"$set": {"status": "Completed", "visit_id": visit["id"], "updated_at": _now_iso()}},
            )

    # auto-create tasks from confirmed promises
    created_tasks = []
    today = datetime.now(timezone.utc).date()
    for p in (body.promises or []):
        due = p.suggested_due_date
        if not due:
            due = (today + timedelta(days=3)).isoformat()
        task = {
            "id": str(uuid.uuid4()),
            "doctor_id": body.doctor_id,
            "tm_user_id": user["id"],
            "team_id": visit["team_id"],
            "visit_id": visit["id"],
            "task_title": p.task_title,
            "task_description": p.task_description or "",
            "due_date": due,
            "priority": p.priority,
            "status": "Open",
            "created_from_ai": True,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "completed_at": None,
        }
        await db.tasks.insert_one(task)
        _strip_id(task)
        created_tasks.append(task)

    _strip_id(visit)
    return {"visit": visit, "created_tasks": created_tasks}


@api.get("/visits")
async def list_visits(
    doctor_id: Optional[str] = None,
    tm_user_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    q = {}
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    if doctor_id:
        q["doctor_id"] = doctor_id
    if tm_user_id and user["role"] in ("Admin", "Manager"):
        q["tm_user_id"] = tm_user_id
    visits = await db.visits.find(q, {"_id": 0}).sort("visit_date", -1).to_list(500)
    return visits


# ====================================================
# ITERO PIPELINE
# ====================================================
def _signal_to_stage(itero_actions, commercial_actions) -> str:
    """Pick the most-advanced iTero stage signalled by a visit's actions."""
    ia = itero_actions.model_dump() if itero_actions and hasattr(itero_actions, "model_dump") else (itero_actions or {})
    ca = commercial_actions.model_dump() if commercial_actions and hasattr(commercial_actions, "model_dump") else (commercial_actions or {})
    if ia.get("contract_signed"):
        return "Contract Signed"
    if ia.get("contract_sent"):
        return "Contract Sent"
    if ca.get("proposal_sent"):
        return "Proposal Sent"
    if ia.get("demo_completed") or ca.get("demo_completed"):
        return "Demo Completed"
    if ia.get("demo_booked") or ca.get("demo_booked"):
        return "Demo Booked"
    if ia.get("demo_discussed") or ca.get("demo_discussed"):
        return "Demo Discussed"
    return "None"


async def _auto_advance_itero_stage(doctor_id: str, itero_actions, commercial_actions, user):
    """Advance the doctor's iTero stage if the visit signals a more-advanced stage.
    Lost is terminal — never auto-overwritten. Stages only move forward, never backward.
    """
    target = _signal_to_stage(itero_actions, commercial_actions)
    if target == "None":
        return
    doc = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doc:
        return
    current = doc.get("itero_stage") or "None"
    if current == "Lost":
        return  # do not auto-advance over Lost
    if ITERO_STAGE_RANK.get(target, 0) <= ITERO_STAGE_RANK.get(current, 0):
        return
    now = _now_iso()
    await db.doctors.update_one(
        {"id": doctor_id},
        {"$set": {"itero_stage": target, "itero_stage_updated_at": now,
                  "itero_stage_updated_by": user["id"], "updated_at": now}},
    )
    await db.itero_stage_history.insert_one({
        "id": str(uuid.uuid4()),
        "doctor_id": doctor_id,
        "from_stage": current,
        "to_stage": target,
        "by_user_id": user["id"],
        "by_user_name": user.get("full_name", ""),
        "note": "Auto-advanced from visit log",
        "auto": True,
        "at": now,
    })


@api.post("/doctors/{doctor_id}/itero-stage")
async def set_itero_stage(doctor_id: str, body: IteroStageUpdate, user=Depends(get_current_user)):
    doc = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doc or not await _can_access_doctor(user, doc):
        raise HTTPException(status_code=404, detail="Doctor not found")
    if user["role"] not in ("TM", "Manager", "Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    current = doc.get("itero_stage") or "None"
    now = _now_iso()
    await db.doctors.update_one(
        {"id": doctor_id},
        {"$set": {"itero_stage": body.stage, "itero_stage_updated_at": now,
                  "itero_stage_updated_by": user["id"], "updated_at": now}},
    )
    await db.itero_stage_history.insert_one({
        "id": str(uuid.uuid4()),
        "doctor_id": doctor_id,
        "from_stage": current,
        "to_stage": body.stage,
        "by_user_id": user["id"],
        "by_user_name": user.get("full_name", ""),
        "note": (body.note or None),
        "auto": False,
        "at": now,
    })
    await _audit(user, "stage_change", "doctor", doctor_id,
                 prev={"itero_stage": current}, new={"itero_stage": body.stage, "note": body.note})
    return {"ok": True, "doctor_id": doctor_id, "from_stage": current, "to_stage": body.stage}


@api.get("/itero/pipeline")
async def itero_pipeline(user=Depends(get_current_user)):
    """Return doctors grouped by iTero stage. Scope:
    - TM: only own
    - Manager: full team (all TMs in their team)
    - Admin/Owner: all
    """
    q: dict = {"status": "Active"}
    if user["role"] == "TM":
        q["assigned_tm_id"] = user["id"]
    elif user["role"] == "Manager":
        team_id = user.get("team_id")
        team_tms = await db.users.find({"team_id": team_id, "role": "TM"}, {"_id": 0, "id": 1}).to_list(500)
        q["assigned_tm_id"] = {"$in": [t["id"] for t in team_tms]}
    docs = await db.doctors.find(q, {"_id": 0}).to_list(5000)

    # Augment with TM name + last visit
    tm_ids = list({d.get("assigned_tm_id") for d in docs if d.get("assigned_tm_id")})
    tm_lookup = {}
    if tm_ids:
        tms = await db.users.find({"id": {"$in": tm_ids}}, {"_id": 0, "id": 1, "full_name": 1}).to_list(500)
        tm_lookup = {t["id"]: t.get("full_name", "") for t in tms}
    last_visit_lookup: dict = {}
    if docs:
        pipeline = [
            {"$match": {"doctor_id": {"$in": [d["id"] for d in docs]}}},
            {"$sort": {"visit_date": -1}},
            {"$group": {"_id": "$doctor_id", "last": {"$first": "$visit_date"}}},
        ]
        async for row in db.visits.aggregate(pipeline):
            last_visit_lookup[row["_id"]] = row.get("last")

    stages = ["None", "Demo Discussed", "Demo Booked", "Demo Completed",
              "Proposal Sent", "Contract Sent", "Contract Signed", "Lost"]
    grouped: dict = {s: [] for s in stages}
    today = datetime.now(timezone.utc).date()
    for d in docs:
        stage = d.get("itero_stage") or "None"
        if stage not in grouped:
            stage = "None"
        last = last_visit_lookup.get(d["id"])
        days_since = None
        if last:
            try:
                lv = datetime.fromisoformat(last.replace("Z", "+00:00")).date()
                days_since = (today - lv).days
            except Exception:
                days_since = None
        grouped[stage].append({
            "id": d["id"],
            "doctor_name": d.get("doctor_name", ""),
            "clinic_name": d.get("clinic_name"),
            "city": d.get("city"),
            "segment": d.get("segment"),
            "tm_user_id": d.get("assigned_tm_id"),
            "tm_name": tm_lookup.get(d.get("assigned_tm_id"), ""),
            "stage": stage,
            "stage_updated_at": d.get("itero_stage_updated_at"),
            "last_visit_date": last,
            "days_since_last_visit": days_since,
        })

    # Sort each column: stage_updated_at desc; if equal, last visit desc
    def _sort_key(c):
        return (c.get("stage_updated_at") or "", c.get("last_visit_date") or "")
    for s in grouped:
        grouped[s].sort(key=_sort_key, reverse=True)

    counts = {s: len(grouped[s]) for s in stages}
    return {"stages": stages, "groups": grouped, "counts": counts, "total": sum(counts.values())}


@api.get("/doctors/{doctor_id}/itero-stage-history")
async def itero_stage_history(doctor_id: str, user=Depends(get_current_user)):
    doc = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doc or not await _can_access_doctor(user, doc):
        raise HTTPException(status_code=404, detail="Doctor not found")
    rows = await db.itero_stage_history.find({"doctor_id": doctor_id}, {"_id": 0}).sort("at", -1).to_list(200)
    return rows


@api.get("/itero/demos")
async def itero_demos(user=Depends(get_current_user)):
    """List doctors with demo signals, bucketed by Booked / Completed / Lost.
    - Booked: latest visit shows demo_booked_date AND demo not yet completed.
    - Completed: any visit recorded a demo_completed_date in the last 30d.
    - Lost: doctor stage is Lost AND had any demo signal historically.
    Scope: TM=own, Manager=team, Admin/Owner=all (mirror of /itero/pipeline).
    """
    # Scope doctors
    doctor_q = {"status": "Active"}
    if user["role"] == "TM":
        doctor_q["assigned_tm_id"] = user["id"]
    elif user["role"] == "Manager":
        team_id = user.get("team_id")
        team_tms = await db.users.find({"team_id": team_id, "role": "TM"}, {"_id": 0, "id": 1}).to_list(500)
        doctor_q["assigned_tm_id"] = {"$in": [t["id"] for t in team_tms]}
    docs = await db.doctors.find(doctor_q, {"_id": 0}).to_list(5000)
    if not docs:
        return {"booked": [], "completed": [], "lost": [], "counts": {"booked": 0, "completed": 0, "lost": 0}}
    doc_map = {d["id"]: d for d in docs}

    visits = await db.visits.find(
        {"doctor_id": {"$in": list(doc_map.keys())}},
        {"_id": 0}
    ).sort("visit_date", -1).to_list(20000)

    # Walk newest -> oldest; first encountered booked/completed dates win.
    demos: dict = {}
    for v in visits:
        ia = v.get("itero_actions") or {}
        ca = v.get("commercial_actions") or {}  # legacy fallback
        d = demos.setdefault(v["doctor_id"], {})
        bd = ia.get("demo_booked_date") or ca.get("demo_booked_date")
        if bd and not d.get("booked_date"):
            d["booked_date"] = bd
        cd = ia.get("demo_completed_date") or ca.get("demo_completed_date")
        if cd and not d.get("completed_date"):
            d["completed_date"] = cd
        # Track that this doctor had ANY demo signal (even just demo_discussed)
        if any([
            ia.get("demo_discussed"), ia.get("demo_booked"), ia.get("demo_completed"),
            ca.get("demo_discussed"), ca.get("demo_booked"), ca.get("demo_completed"),
            bd, cd,
        ]):
            d["had_demo_signal"] = True

    # Merge in meetings flagged as iTero demos.
    demo_meetings = await db.meetings.find(
        {"doctor_id": {"$in": list(doc_map.keys())}, "is_demo": True},
        {"_id": 0},
    ).sort("scheduled_at", -1).to_list(5000)
    for mt in demo_meetings:
        d = demos.setdefault(mt["doctor_id"], {})
        d["had_demo_signal"] = True
        # Completed (visit logged from it) → counts as completed_date if more recent than visit-derived one.
        if mt.get("status") == "Completed":
            cd = (mt.get("updated_at") or mt.get("scheduled_at") or "")[:10]
            if cd and (not d.get("completed_date") or d["completed_date"] < cd):
                d["completed_date"] = cd
        # Scheduled → upcoming booked. Use scheduled_at if no future booked_date already known.
        if mt.get("status") == "Scheduled":
            sd = (mt.get("scheduled_at") or "")[:10]
            if sd and (not d.get("booked_date") or d["booked_date"] < sd):
                d["booked_date"] = sd

    today = datetime.now(timezone.utc).date()
    booked, completed, lost = [], [], []
    for did, d in demos.items():
        doc = doc_map[did]
        stage = doc.get("itero_stage") or "None"
        row = {
            "doctor_id": did,
            "doctor_name": doc.get("doctor_name"),
            "clinic_name": doc.get("clinic_name"),
            "city": doc.get("city"),
            "segment": doc.get("segment"),
            "tm_user_id": doc.get("assigned_tm_id"),
            "stage": stage,
            "booked_date": d.get("booked_date"),
            "completed_date": d.get("completed_date"),
        }
        if stage == "Lost" and d.get("had_demo_signal"):
            lost.append(row)
            continue
        # Completed in last 30 days (even if doctor already advanced past)
        if d.get("completed_date"):
            try:
                cdate = datetime.fromisoformat(d["completed_date"][:10]).date()
                if (today - cdate).days <= 30:
                    completed.append(row)
                    continue
            except Exception:
                completed.append(row)
                continue
        # Booked but not yet completed -> upcoming
        if d.get("booked_date") and not d.get("completed_date"):
            booked.append(row)

    booked.sort(key=lambda x: x.get("booked_date") or "")  # soonest first
    completed.sort(key=lambda x: x.get("completed_date") or "", reverse=True)
    lost.sort(key=lambda x: (x.get("completed_date") or x.get("booked_date") or ""), reverse=True)

    # TM name enrichment
    tm_ids = list({r["tm_user_id"] for sub in (booked, completed, lost) for r in sub if r.get("tm_user_id")})
    if tm_ids:
        tms = await db.users.find({"id": {"$in": tm_ids}}, {"_id": 0, "id": 1, "full_name": 1}).to_list(500)
        tm_lookup = {t["id"]: t.get("full_name", "") for t in tms}
        for sub in (booked, completed, lost):
            for r in sub:
                r["tm_name"] = tm_lookup.get(r["tm_user_id"], "")

    return {
        "booked": booked,
        "completed": completed,
        "lost": lost,
        "counts": {"booked": len(booked), "completed": len(completed), "lost": len(lost)},
    }


# ====================================================
# MEETINGS  (lightweight scheduler; not a calendar integration)
# ====================================================
@api.post("/meetings", response_model=Meeting)
async def create_meeting(body: MeetingCreate, user=Depends(get_current_user)):
    if user["role"] != "TM":
        raise HTTPException(status_code=403, detail="Only TMs can book meetings")
    doctor = await db.doctors.find_one({"id": body.doctor_id}, {"_id": 0})
    if not doctor or not await _can_access_doctor(user, doctor):
        raise HTTPException(status_code=404, detail="Doctor not found")
    import uuid
    m = Meeting(
        id=str(uuid.uuid4()),
        doctor_id=body.doctor_id,
        doctor_name=doctor.get("doctor_name", ""),
        clinic_name=doctor.get("clinic_name"),
        city=doctor.get("city"),
        tm_user_id=user["id"],
        tm_name=user.get("full_name", ""),
        team_id=user.get("team_id") or doctor.get("team_id"),
        scheduled_at=body.scheduled_at,
        duration_minutes=body.duration_minutes or 30,
        subject=body.subject,
        is_demo=body.is_demo,
        status="Scheduled",
    ).model_dump()
    await db.meetings.insert_one(m)
    await _audit(user, "create", "meeting", m["id"],
                 new={"doctor_id": body.doctor_id, "scheduled_at": body.scheduled_at, "is_demo": body.is_demo})

    # If this meeting is an iTero demo, auto-advance the doctor's pipeline stage to "Demo Booked"
    if body.is_demo:
        current = doctor.get("itero_stage") or "None"
        if current != "Lost" and ITERO_STAGE_RANK.get("Demo Booked", 0) > ITERO_STAGE_RANK.get(current, 0):
            now = _now_iso()
            await db.doctors.update_one(
                {"id": body.doctor_id},
                {"$set": {"itero_stage": "Demo Booked", "itero_stage_updated_at": now,
                          "itero_stage_updated_by": user["id"], "updated_at": now}},
            )
            await db.itero_stage_history.insert_one({
                "id": str(uuid.uuid4()),
                "doctor_id": body.doctor_id,
                "from_stage": current,
                "to_stage": "Demo Booked",
                "by_user_id": user["id"],
                "by_user_name": user.get("full_name", ""),
                "note": "Auto-advanced from booked iTero demo",
                "auto": True,
                "at": now,
            })
    return m


@api.get("/meetings")
async def list_meetings(
    when: Optional[str] = Query(None, description="upcoming | past | all"),
    user=Depends(get_current_user),
):
    q: dict = {}
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    # Admin/Owner sees all
    now = _now_iso()
    if when == "upcoming":
        q["scheduled_at"] = {"$gte": now}
        q["status"] = "Scheduled"
    elif when == "past":
        q["$or"] = [{"scheduled_at": {"$lt": now}}, {"status": {"$in": ["Completed", "Cancelled"]}}]
    rows = await db.meetings.find(q, {"_id": 0}).sort("scheduled_at", 1).to_list(2000)
    return rows


@api.get("/meetings/{meeting_id}", response_model=Meeting)
async def get_meeting(meeting_id: str, user=Depends(get_current_user)):
    m = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if user["role"] == "TM" and m["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "Manager" and m.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return m


@api.put("/meetings/{meeting_id}", response_model=Meeting)
async def update_meeting(meeting_id: str, body: MeetingUpdate, user=Depends(get_current_user)):
    m = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if m["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    update["updated_at"] = _now_iso()
    await db.meetings.update_one({"id": meeting_id}, {"$set": update})
    new = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    await _audit(user, "update", "meeting", meeting_id, new=update)
    return new


@api.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str, user=Depends(get_current_user)):
    m = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if m["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.meetings.delete_one({"id": meeting_id})
    await _audit(user, "delete", "meeting", meeting_id, prev=m)
    return {"ok": True, "id": meeting_id}


class CompleteDemoBody(BaseModel):
    interest_level: Literal["None", "Low", "Medium", "High"] = "Medium"
    outcome_note: Optional[str] = None
    next_step: Optional[str] = None  # if provided, creates a follow-up task
    next_step_due: Optional[str] = None  # ISO date for the task due_date


@api.post("/meetings/{meeting_id}/complete-demo")
async def complete_demo_meeting(meeting_id: str, body: CompleteDemoBody, user=Depends(get_current_user)):
    """One-tap completion for a booked iTero demo. Marks the meeting Completed,
    creates a lightweight visit (so the doctor lands in 'Demo Completed' on Demos overview),
    auto-advances the pipeline stage, and optionally creates a follow-up task.
    """
    m = await db.meetings.find_one({"id": meeting_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not m.get("is_demo"):
        raise HTTPException(status_code=400, detail="Only iTero-demo meetings can be marked done this way")
    if m["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if m.get("status") == "Completed":
        raise HTTPException(status_code=400, detail="Demo already completed")

    today_iso = _now_iso()
    today_date = today_iso[:10]
    note = (body.outcome_note or f"iTero demo completed. Interest: {body.interest_level}.").strip()

    # Build a lightweight visit record
    visit_id = str(uuid.uuid4())
    visit_doc = {
        "id": visit_id,
        "doctor_id": m["doctor_id"],
        "tm_user_id": user["id"],
        "team_id": m.get("team_id"),
        "track_type": "iTero",
        "visit_date": today_iso,
        "visit_type": "Demo session",
        "free_text_note": note,
        "ai_extracted_tags": {},
        "confirmed_topics": [],
        "confirmed_barriers": [],
        "sentiment": None,
        "itero_actions": {
            "demo_completed": True,
            "demo_completed_date": today_date,
            "scanner_interest_level": body.interest_level,
            "scanner_concerns": [],
        },
        "invisalign_actions": {},
        "commercial_actions": {},
        "meeting_id": meeting_id,
        "created_at": today_iso,
        "updated_at": today_iso,
    }
    await db.visits.insert_one(visit_doc)
    await _audit(user, "create", "visit", visit_id, new={"doctor_id": m["doctor_id"], "from": "demo-complete"})

    # Mark meeting Completed and link the visit
    await db.meetings.update_one(
        {"id": meeting_id},
        {"$set": {"status": "Completed", "visit_id": visit_id, "updated_at": today_iso}},
    )

    # Auto-advance the pipeline stage forward
    class _IA:
        def model_dump(self): return {"demo_completed": True}
    class _CA:
        def model_dump(self): return {}
    await _auto_advance_itero_stage(m["doctor_id"], _IA(), _CA(), user)

    # Optional follow-up task
    task_id = None
    if body.next_step and body.next_step.strip():
        task_id = str(uuid.uuid4())
        await db.tasks.insert_one({
            "id": task_id,
            "doctor_id": m["doctor_id"],
            "tm_user_id": user["id"],
            "team_id": m.get("team_id"),
            "task_title": body.next_step.strip(),
            "task_description": "",
            "due_date": body.next_step_due or None,
            "priority": "Medium",
            "status": "Open",
            "promise_kind": "Follow-up",
            "source": "demo-complete",
            "source_visit_id": visit_id,
            "created_at": today_iso,
            "updated_at": today_iso,
        })
        await _audit(user, "create", "task", task_id, new={"task_title": body.next_step.strip(), "doctor_id": m["doctor_id"]})

    return {"ok": True, "meeting_id": meeting_id, "visit_id": visit_id, "task_id": task_id}


# ====================================================
# EVENTS  (generic agenda items, no doctor link)
# ====================================================
@api.post("/events", response_model=Event)
async def create_event(body: EventCreate, user=Depends(get_current_user)):
    if user["role"] not in ("TM", "Manager", "Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    # Resolve start, end, and duration so all three stay in sync.
    starts = body.scheduled_at
    ends = body.ends_at
    duration = body.duration_minutes or 60
    try:
        start_dt = datetime.fromisoformat(starts.replace("Z", "+00:00"))
        if ends:
            end_dt = datetime.fromisoformat(ends.replace("Z", "+00:00"))
            if end_dt <= start_dt:
                raise HTTPException(status_code=400, detail="End must be after start")
            duration = max(int((end_dt - start_dt).total_seconds() // 60), 1)
        else:
            end_dt = start_dt + timedelta(minutes=duration)
            ends = end_dt.isoformat()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date/time")
    e = Event(
        id=str(uuid.uuid4()),
        title=body.title.strip(),
        tm_user_id=user["id"],
        tm_name=user.get("full_name", ""),
        team_id=user.get("team_id"),
        scheduled_at=starts,
        ends_at=ends,
        duration_minutes=duration,
        location=body.location,
        notes=body.notes,
        status="Scheduled",
    ).model_dump()
    await db.events.insert_one(e)
    await _audit(user, "create", "event", e["id"], new={"title": e["title"], "scheduled_at": e["scheduled_at"], "ends_at": e["ends_at"]})
    return e


@api.get("/events")
async def list_events(
    when: Optional[str] = Query(None, description="upcoming | past | all"),
    user=Depends(get_current_user),
):
    q: dict = {}
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    now = _now_iso()
    if when == "upcoming":
        q["scheduled_at"] = {"$gte": now}
        q["status"] = "Scheduled"
    elif when == "past":
        q["$or"] = [{"scheduled_at": {"$lt": now}}, {"status": {"$in": ["Done", "Cancelled"]}}]
    rows = await db.events.find(q, {"_id": 0}).sort("scheduled_at", 1).to_list(2000)
    return rows


@api.get("/events/{event_id}", response_model=Event)
async def get_event(event_id: str, user=Depends(get_current_user)):
    e = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not e:
        raise HTTPException(status_code=404, detail="Event not found")
    if user["role"] == "TM" and e["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "Manager" and e.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return e


@api.put("/events/{event_id}", response_model=Event)
async def update_event(event_id: str, body: EventUpdate, user=Depends(get_current_user)):
    e = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not e:
        raise HTTPException(status_code=404, detail="Event not found")
    if e["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    # Keep starts/ends/duration consistent if any of them was changed.
    has_time_change = any(k in update for k in ("scheduled_at", "ends_at", "duration_minutes"))
    if has_time_change:
        starts = update.get("scheduled_at", e.get("scheduled_at"))
        ends = update.get("ends_at", e.get("ends_at"))
        duration = update.get("duration_minutes", e.get("duration_minutes") or 60)
        try:
            start_dt = datetime.fromisoformat(starts.replace("Z", "+00:00"))
            # If user supplied a new ends_at, recompute duration; else recompute ends_at from duration.
            if "ends_at" in update or (ends and "scheduled_at" in update and "duration_minutes" not in update):
                end_dt = datetime.fromisoformat(ends.replace("Z", "+00:00"))
                if end_dt <= start_dt:
                    raise HTTPException(status_code=400, detail="End must be after start")
                duration = max(int((end_dt - start_dt).total_seconds() // 60), 1)
            else:
                end_dt = start_dt + timedelta(minutes=duration)
                ends = end_dt.isoformat()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid date/time")
        update["scheduled_at"] = starts
        update["ends_at"] = ends
        update["duration_minutes"] = duration
    update["updated_at"] = _now_iso()
    await db.events.update_one({"id": event_id}, {"$set": update})
    new = await db.events.find_one({"id": event_id}, {"_id": 0})
    await _audit(user, "update", "event", event_id, new=update)
    return new


@api.delete("/events/{event_id}")
async def delete_event(event_id: str, user=Depends(get_current_user)):
    e = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not e:
        raise HTTPException(status_code=404, detail="Event not found")
    if e["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.events.delete_one({"id": event_id})
    await _audit(user, "delete", "event", event_id, prev=e)
    return {"ok": True, "id": event_id}


# ====================================================
# TASKS
# ====================================================
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
    task = Task(
        id=str(uuid.uuid4()),
        doctor_id=body.doctor_id,
        tm_user_id=user["id"],
        team_id=user.get("team_id") or doctor.get("team_id"),
        visit_id=body.visit_id,
        task_title=body.task_title,
        task_description=body.task_description or "",
        due_date=body.due_date or (today_d + timedelta(days=3)).isoformat(),
        priority=body.priority,
        created_from_ai=body.created_from_ai,
    ).model_dump()
    await db.tasks.insert_one(task)
    await _audit(user, "create", "task", task["id"], new={"task_title": task["task_title"]})
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
    await _audit(user, "update", "task", task_id, prev=t, new=update)
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
    await _audit(user, "delete", "task", task_id, prev=t)
    return {"ok": True, "id": task_id}


# ====================================================
# DASHBOARDS
# ====================================================
@api.get("/dashboard/tm")
async def tm_dashboard(user=Depends(get_current_user)):
    if user["role"] not in ("TM", "Admin", "Manager"):
        raise HTTPException(status_code=403, detail="Forbidden")
    doc_q = await _doctor_query_for(user)
    docs = await db.doctors.find(doc_q, {"_id": 0}).to_list(500)
    enriched = [await _enrich_doctor(d) for d in docs]
    enriched.sort(key=lambda d: d["visit_priority_score"], reverse=True)

    today = datetime.now(timezone.utc).date().isoformat()
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    task_q = {}
    if user["role"] == "TM":
        task_q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        task_q["team_id"] = user.get("team_id")
    overdue = await db.tasks.count_documents({**task_q, "status": {"$in": ["Open", "Overdue"]}, "due_date": {"$lt": today}})
    due_today = await db.tasks.count_documents({**task_q, "status": {"$in": ["Open", "Overdue"]}, "due_date": today})
    open_total = await db.tasks.count_documents({**task_q, "status": {"$in": ["Open", "Overdue"]}})

    visit_q = {}
    if user["role"] == "TM":
        visit_q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        visit_q["team_id"] = user.get("team_id")
    visits_week = await db.visits.count_documents({**visit_q, "visit_date": {"$gte": week_start}})

    priorities = enriched[:8]
    overdue_doctors = [d for d in enriched if d["overdue_promises"] > 0][:6]

    return {
        "user": _strip_user(user),
        "stats": {
            "open_promises": open_total,
            "overdue_promises": overdue,
            "due_today": due_today,
            "visits_this_week": visits_week,
            "doctors_total": len(enriched),
        },
        "top_priorities": priorities,
        "overdue_doctors": overdue_doctors,
    }


@api.get("/dashboard/manager")
async def manager_dashboard(user=Depends(require_roles("Manager", "Admin"))):
    team_q = {} if user["role"] == "Admin" else {"team_id": user.get("team_id")}
    docs = await db.doctors.find(team_q, {"_id": 0}).to_list(1000)
    visits = await db.visits.find(team_q, {"_id": 0}).sort("visit_date", -1).to_list(2000)
    tasks = await db.tasks.find(team_q, {"_id": 0}).to_list(2000)
    users = await db.users.find({**({"team_id": user.get("team_id")} if user["role"] == "Manager" else {}), "role": "TM"}, {"_id": 0, "password_hash": 0}).to_list(200)

    today = datetime.now(timezone.utc).date().isoformat()
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    month_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    visits_week = [v for v in visits if v["visit_date"] >= week_start]
    visits_month = [v for v in visits if v["visit_date"] >= month_start]

    # by TM
    by_tm: dict = {}
    for u in users:
        by_tm[u["id"]] = {"tm_id": u["id"], "name": u["full_name"], "visits_week": 0, "visits_month": 0, "doctors": 0, "overdue": 0}
    for v in visits_week:
        if v["tm_user_id"] in by_tm:
            by_tm[v["tm_user_id"]]["visits_week"] += 1
    for v in visits_month:
        if v["tm_user_id"] in by_tm:
            by_tm[v["tm_user_id"]]["visits_month"] += 1
    for d in docs:
        if d.get("assigned_tm_id") in by_tm:
            by_tm[d["assigned_tm_id"]]["doctors"] += 1
    for t in tasks:
        if t.get("status") in ("Open", "Overdue") and t.get("due_date") and t["due_date"] < today:
            if t["tm_user_id"] in by_tm:
                by_tm[t["tm_user_id"]]["overdue"] += 1

    # top topics & barriers (last 30 days)
    topic_counts: dict = {}
    barrier_counts: dict = {}
    sentiment_counts: dict = {}
    op_counts: dict = {}
    sentiment_by_segment: dict = {}
    for v in visits_month:
        for t in v.get("confirmed_topics") or []:
            topic_counts[t] = topic_counts.get(t, 0) + 1
        for b in v.get("confirmed_barriers") or []:
            barrier_counts[b] = barrier_counts.get(b, 0) + 1
        s = v.get("sentiment") or "Neutral"
        sentiment_counts[s] = sentiment_counts.get(s, 0) + 1
        op = v.get("opportunity_state") or "Unknown"
        op_counts[op] = op_counts.get(op, 0) + 1

    # sentiment by segment
    doc_seg = {d["id"]: d.get("segment", "Occasional") for d in docs}
    for v in visits_month:
        seg = doc_seg.get(v["doctor_id"], "Occasional")
        sentiment_by_segment.setdefault(seg, {"Very Negative": 0, "Negative": 0, "Neutral": 0, "Positive": 0, "Very Positive": 0})
        sentiment_by_segment[seg][v.get("sentiment", "Neutral")] = sentiment_by_segment[seg].get(v.get("sentiment", "Neutral"), 0) + 1

    top_topics = [{"name": k, "count": v} for k, v in sorted(topic_counts.items(), key=lambda x: -x[1])[:8]]
    top_barriers = [{"name": k, "count": v} for k, v in sorted(barrier_counts.items(), key=lambda x: -x[1])[:8]]

    # Under-visited high-segment doctors
    enriched = [await _enrich_doctor(d) for d in docs]
    under_visited = [
        d for d in enriched
        if d["segment"] in ("Engaged", "Expert") and d["cadence_status"] in ("Overdue", "Critical")
    ][:8]

    market_pulse = _market_pulse(top_barriers, top_topics, sentiment_counts)

    return {
        "stats": {
            "visits_week": len(visits_week),
            "visits_month": len(visits_month),
            "doctors": len(docs),
            "tms": len(users),
            "overdue_promises": sum(b["overdue"] for b in by_tm.values()),
        },
        "by_tm": list(by_tm.values()),
        "top_topics": top_topics,
        "top_barriers": top_barriers,
        "sentiment_distribution": sentiment_counts,
        "opportunity_distribution": op_counts,
        "sentiment_by_segment": sentiment_by_segment,
        "under_visited_high_segment": under_visited,
        "market_pulse": market_pulse,
    }


def _market_pulse(top_barriers, top_topics, sentiment_counts):
    if not top_barriers and not top_topics:
        return "Not enough data yet — log more visits to surface patterns."
    parts = []
    if top_barriers:
        parts.append("Top barriers: " + ", ".join(b["name"] for b in top_barriers[:3]))
    if top_topics:
        parts.append("Most-discussed topics: " + ", ".join(t["name"] for t in top_topics[:3]))
    total = sum(sentiment_counts.values()) or 1
    pos = (sentiment_counts.get("Positive", 0) + sentiment_counts.get("Very Positive", 0)) / total
    neg = (sentiment_counts.get("Negative", 0) + sentiment_counts.get("Very Negative", 0)) / total
    if pos > 0.5:
        parts.append("Sentiment leans positive overall.")
    elif neg > 0.4:
        parts.append("Negative sentiment is elevated — investigate.")
    else:
        parts.append("Sentiment is mixed/neutral.")
    return " ".join(parts)


# ====================================================
# SEARCH
# ====================================================
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


# ====================================================
# TAXONOMY
# ====================================================
TOPICS_DEFAULT = {
    "Clinical": ["Case selection confidence", "ClinCheck understanding", "Clinical confidence", "Complex case discussion", "Extraction cases", "Retained teeth", "Predictability concerns"],
    "Product": ["Invisalign pricing", "iTero value", "3D face scan", "SmileView", "SmileVideo", "iTero demo", "Digital workflow", "Align Digital Platform"],
    "Business": ["Business confidence", "Patient affordability perception", "Lead generation concerns", "Marketing", "Time constraints", "Case acceptance", "Growth programs awareness", "Discount/program awareness"],
    "Programs": ["Peer-to-peer", "TPS service", "Certification interest", "Event invitation", "Staff training", "Doctor education", "Clinical support"],
    "Platform": ["Docloc benefits", "Practice App", "Case Assessment", "Prospect", "Invisalign options", "Virtual care"],
}
BARRIERS_DEFAULT = {
    "Pricing": ["Patient affordability concern", "Doctor margin concern", "Perceived unfair pricing", "Does not understand growth programs", "Discount confusion", "Thinks Invisalign is too expensive"],
    "Clinical": ["Low clinical confidence", "Unsure aligners work", "Complex case uncertainty", "Extraction case concern", "Retained teeth concern", "Predictability concern", "ClinCheck confidence issue"],
    "Business": ["Low business confidence", "Does not know how to present Invisalign", "Afraid patients will reject price", "Low case acceptance confidence", "Low patient demand belief"],
    "Operational": ["Lack of time", "Staff not trained", "Workflow complexity", "Too many steps", "Does not use digital tools consistently"],
    "Competition": ["Prefers braces", "Uses other aligner system", "Believes braces are more profitable", "Negative past aligner experience"],
}


async def _ensure_taxonomy_seeded():
    """Idempotent: if the taxonomy_terms collection is empty, populate from defaults."""
    import uuid
    count = await db.taxonomy_terms.count_documents({})
    if count > 0:
        return
    docs = []
    now = _now_iso()
    for cat, items in TOPICS_DEFAULT.items():
        for term in items:
            docs.append({"id": str(uuid.uuid4()), "kind": "topic", "category": cat,
                         "term": term, "active": True, "created_at": now, "updated_at": now})
    for cat, items in BARRIERS_DEFAULT.items():
        for term in items:
            docs.append({"id": str(uuid.uuid4()), "kind": "barrier", "category": cat,
                         "term": term, "active": True, "created_at": now, "updated_at": now})
    if docs:
        await db.taxonomy_terms.insert_many(docs)


async def _read_taxonomy_groups():
    """Return {topics: {cat: [term, ...]}, barriers: {cat: [term, ...]}} from DB."""
    await _ensure_taxonomy_seeded()
    rows = await db.taxonomy_terms.find({"active": True}, {"_id": 0}).to_list(2000)
    topics: dict = {}
    barriers: dict = {}
    for r in rows:
        bucket = topics if r["kind"] == "topic" else barriers
        bucket.setdefault(r["category"], []).append(r["term"])
    # stable ordering: alpha within each category
    for d in (topics, barriers):
        for k in d:
            d[k] = sorted(d[k])
    return topics, barriers


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


# ----- Admin: editable taxonomy CRUD -----
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



# ====================================================
# TM PERFORMANCE (manager view)
# ====================================================
def _week_bounds(now=None):
    n = now or datetime.now(timezone.utc)
    monday = (n - timedelta(days=n.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return monday, sunday


def _classify_flags(perf: dict) -> List[dict]:
    flags = []
    target = perf["visits_target_month"] or 1
    if perf["visits_month"] < 0.5 * target:
        flags.append({"key": "low_activity", "severity": "danger", "label": "Low visit activity",
                      "detail": f"Logged {perf['visits_month']} visits vs target ~{target} (last 30d)"})
    if perf["overdue_count"] >= 5:
        flags.append({"key": "high_overdue", "severity": "danger", "label": "High overdue tasks",
                      "detail": f"{perf['overdue_count']} promises past due"})
    elif perf["overdue_count"] >= 2:
        flags.append({"key": "rising_overdue", "severity": "warning", "label": "Rising overdue tasks",
                      "detail": f"{perf['overdue_count']} promises past due"})
    cr = perf["completion_rate"]
    if perf["promises_total_30d"] >= 3 and cr < 0.4:
        flags.append({"key": "poor_followup", "severity": "danger", "label": "Poor follow-up discipline",
                      "detail": f"Only {int(cr*100)}% of promises completed in 30d"})
    if perf["high_priority_unvisited"] >= 3:
        flags.append({"key": "avoiding_priority", "severity": "warning", "label": "Avoidance of high-priority doctors",
                      "detail": f"{perf['high_priority_unvisited']} high-priority doctors not visited in 30d"})
    return flags


def _classify_insights(perf: dict) -> List[dict]:
    insights = []
    cr = perf["completion_rate"]
    if perf["promises_total_30d"] >= 3 and cr >= 0.8:
        insights.append({"kind": "positive", "label": "Strong follow-up habits",
                         "detail": f"{int(cr*100)}% promises completed in 30d"})
    elif perf["promises_total_30d"] >= 3 and cr < 0.4:
        insights.append({"kind": "negative", "label": "Weak follow-up habits",
                         "detail": f"Only {int(cr*100)}% promises completed in 30d"})
    if perf["pct_visits_to_low_value"] >= 0.55 and perf["visits_month"] >= 4:
        insights.append({"kind": "negative", "label": "Over-visiting low-value doctors",
                         "detail": f"{int(perf['pct_visits_to_low_value']*100)}% of visits to Occasional segment"})
    if perf["high_priority_unvisited"] >= 3:
        insights.append({"kind": "negative", "label": "Under-visiting high-opportunity doctors",
                         "detail": f"{perf['high_priority_unvisited']} high-priority doctors not visited in 30d"})
    if perf["sentiment_trend"] == "improving":
        insights.append({"kind": "positive", "label": "Sentiment trending up",
                         "detail": "Recent visits feel more positive than the prior period"})
    elif perf["sentiment_trend"] == "declining":
        insights.append({"kind": "negative", "label": "Sentiment trending down",
                         "detail": "Recent visits feel more negative than the prior period"})
    return insights


@api.get("/dashboard/manager/performance")
async def manager_performance(user=Depends(require_roles("Manager", "Admin"))):
    team_q = {} if user["role"] == "Admin" else {"team_id": user.get("team_id")}
    user_q = {**({"team_id": user.get("team_id")} if user["role"] == "Manager" else {}), "role": "TM"}
    tms = await db.users.find(user_q, {"_id": 0, "password_hash": 0}).to_list(500)
    docs = await db.doctors.find(team_q, {"_id": 0}).to_list(2000)
    visits = await db.visits.find(team_q, {"_id": 0}).to_list(5000)
    tasks = await db.tasks.find(team_q, {"_id": 0}).to_list(5000)

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    month_start = (now - timedelta(days=30)).isoformat()
    prev_month_start = (now - timedelta(days=60)).isoformat()

    sentiment_score = {"Very Negative": 1, "Negative": 2, "Neutral": 3, "Positive": 4, "Very Positive": 5}

    rows = []
    for tm in tms:
        my_docs = [d for d in docs if d.get("assigned_tm_id") == tm["id"]]
        my_visits = [v for v in visits if v.get("tm_user_id") == tm["id"]]
        my_visits_30 = [v for v in my_visits if v.get("visit_date", "") >= month_start]
        my_visits_prev = [v for v in my_visits if prev_month_start <= v.get("visit_date", "") < month_start]
        my_tasks = [t for t in tasks if t.get("tm_user_id") == tm["id"]]
        my_tasks_30 = [t for t in my_tasks if t.get("created_at", "") >= month_start]

        # target ≈ Σ 30/cadence(seg) over assigned doctors
        target = 0.0
        for d in my_docs:
            target += 30.0 / max(DEFAULT_CADENCE.get(d.get("segment", "Occasional"), 45), 1)
        target_int = max(int(round(target)), 1)

        avg_per_day = round(len(my_visits_30) / 30.0, 2)
        overdue_count = sum(1 for t in my_tasks if t.get("status") in ("Open", "Overdue") and t.get("due_date") and t["due_date"] < today)
        completed_30 = sum(1 for t in my_tasks if t.get("status") == "Completed" and (t.get("completed_at") or "") >= month_start)
        promises_total_30 = max(len(my_tasks_30), completed_30)
        completion_rate = round(completed_30 / promises_total_30, 2) if promises_total_30 else 0.0

        # sentiment (last 30 vs previous 30)
        sent_recent_vals = [sentiment_score.get(v.get("sentiment", "Neutral"), 3) for v in my_visits_30]
        sent_prev_vals = [sentiment_score.get(v.get("sentiment", "Neutral"), 3) for v in my_visits_prev]
        sent_recent = round(sum(sent_recent_vals) / len(sent_recent_vals), 2) if sent_recent_vals else None
        sent_prev = round(sum(sent_prev_vals) / len(sent_prev_vals), 2) if sent_prev_vals else None
        if sent_recent is None or sent_prev is None:
            sent_trend = "stable"
        elif sent_recent > sent_prev + 0.3:
            sent_trend = "improving"
        elif sent_recent < sent_prev - 0.3:
            sent_trend = "declining"
        else:
            sent_trend = "stable"

        # high-priority unvisited (priority>=55, not visited in 30d)
        recently_visited_ids = {v["doctor_id"] for v in my_visits_30}
        enriched_my = [await _enrich_doctor(d) for d in my_docs]
        high_pri_unvisited = [d for d in enriched_my if d["visit_priority_score"] >= 55 and d["id"] not in recently_visited_ids]

        # over-visit low-value (Occasional segment) ratio
        occ_visits = sum(1 for v in my_visits_30 if next((d for d in my_docs if d["id"] == v["doctor_id"]), {}).get("segment") == "Occasional")
        pct_low = round(occ_visits / len(my_visits_30), 2) if my_visits_30 else 0.0

        perf = {
            "tm_id": tm["id"],
            "tm_name": tm["full_name"],
            "tm_email": tm["email"],
            "doctors": len(my_docs),
            "visits_month": len(my_visits_30),
            "visits_target_month": target_int,
            "visits_vs_target": round((len(my_visits_30) / target_int), 2) if target_int else 0,
            "avg_visits_per_day": avg_per_day,
            "overdue_count": overdue_count,
            "completion_rate": completion_rate,
            "promises_total_30d": promises_total_30,
            "promises_completed_30d": completed_30,
            "high_priority_unvisited": len(high_pri_unvisited),
            "high_priority_unvisited_doctors": [
                {"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"], "score": d["visit_priority_score"]}
                for d in high_pri_unvisited[:5]
            ],
            "sentiment_recent": sent_recent,
            "sentiment_prev": sent_prev,
            "sentiment_trend": sent_trend,
            "pct_visits_to_low_value": pct_low,
        }
        # high-priority visited %
        total_high_priority = len([d for d in enriched_my if d["visit_priority_score"] >= 55])
        if total_high_priority > 0:
            visited_high = total_high_priority - len(high_pri_unvisited)
            perf["high_priority_visited_pct"] = round(visited_high / total_high_priority, 2)
        else:
            perf["high_priority_visited_pct"] = None
        perf["total_high_priority"] = total_high_priority

        # demo + proposal performance using enriched commercial_state
        demos_completed = sum(1 for d in enriched_my if d["commercial_state"]["demo_completed"])
        demos_booked = sum(1 for d in enriched_my if d["commercial_state"]["demo_booked"])
        demos_pending = sum(1 for d in enriched_my if d["commercial_state"]["demo_pending"])
        proposals_sent = sum(1 for d in enriched_my if d["commercial_state"]["proposal_sent"])
        proposals_unfollowed = sum(1 for d in enriched_my if d["commercial_state"]["proposal_unfollowed"])
        perf["demos_booked"] = demos_booked
        perf["demos_completed"] = demos_completed
        perf["demos_pending"] = demos_pending
        perf["demo_completion_rate"] = round(demos_completed / demos_booked, 2) if demos_booked else 0.0
        perf["proposals_sent"] = proposals_sent
        perf["proposals_unfollowed"] = proposals_unfollowed
        perf["proposal_followup_rate"] = round((proposals_sent - proposals_unfollowed) / proposals_sent, 2) if proposals_sent else 0.0

        # Execution Quality Score = blended score Low/Medium/High
        eqs = 0.0
        eqs += min(perf["visits_vs_target"], 1.5) * 30
        eqs += (perf["completion_rate"] or 0) * 30
        if perf["high_priority_visited_pct"] is not None:
            eqs += perf["high_priority_visited_pct"] * 25
        else:
            eqs += 12
        # penalty for overdue
        eqs -= min(perf["overdue_count"], 6) * 2
        # penalty for proposals_unfollowed
        eqs -= min(perf["proposals_unfollowed"], 4) * 3
        eqs = max(0, min(round(eqs), 100))
        perf["execution_quality_score"] = eqs
        perf["execution_quality_label"] = "High" if eqs >= 65 else "Medium" if eqs >= 40 else "Low"

        perf["flags"] = _classify_flags(perf)
        perf["insights"] = _classify_insights(perf)
        perf["coaching"] = _coaching_for(perf)
        rows.append(perf)

    rows.sort(key=lambda r: (r["execution_quality_score"], -len(r["flags"])))
    return {"rows": rows}


def _coaching_for(perf: dict) -> dict:
    strengths, weaknesses, suggestions = [], [], []
    if perf["completion_rate"] >= 0.7 and perf["promises_total_30d"] >= 3:
        strengths.append("Strong follow-up discipline")
    if perf["visits_vs_target"] >= 0.9:
        strengths.append("Hitting visit cadence target")
    if perf.get("high_priority_visited_pct") is not None and perf["high_priority_visited_pct"] >= 0.7:
        strengths.append("Covering high-priority doctors well")
    if perf.get("demos_booked", 0) >= 1 and perf.get("demo_completion_rate", 0) >= 0.7:
        strengths.append("Closes the loop on demos")

    if perf["completion_rate"] < 0.4 and perf["promises_total_30d"] >= 3:
        weaknesses.append("Weak follow-up discipline")
        suggestions.append("Block 30 min/day for promise closure before adding new commitments.")
    if perf["high_priority_unvisited"] >= 3:
        weaknesses.append("Avoiding high-value doctors")
        suggestions.append("Pair with manager on next 2 high-priority visits.")
    if perf["pct_visits_to_low_value"] >= 0.55 and perf["visits_month"] >= 4:
        weaknesses.append("Over-visiting low-value doctors")
        suggestions.append("Reallocate ~30% of Occasional-segment visits toward Engaged/Expert.")
    if perf.get("demos_pending", 0) >= 2:
        weaknesses.append("Demos booked but not completed")
        suggestions.append("Confirm/reschedule pending demos this week.")
    if perf.get("proposals_unfollowed", 0) >= 2:
        weaknesses.append("Proposals sent without follow-up")
        suggestions.append("Schedule follow-up call within 5 days of every proposal.")
    if perf["sentiment_trend"] == "declining":
        weaknesses.append("Sentiment declining recently")
        suggestions.append("Investigate barriers from last 5 visits and surface pattern.")
    if not weaknesses and not strengths:
        weaknesses.append("Not enough activity to coach yet")
    return {"strengths": strengths, "weaknesses": weaknesses, "suggestions": suggestions}


# ====================================================
# COMMERCIAL FUNNEL (manager view)
# ====================================================
@api.get("/dashboard/manager/commercial")
async def manager_commercial(user=Depends(require_roles("Manager", "Admin"))):
    team_q = {} if user["role"] == "Admin" else {"team_id": user.get("team_id")}
    docs = await db.doctors.find(team_q, {"_id": 0}).to_list(2000)
    enriched = [await _enrich_doctor(d) for d in docs]
    total = len(enriched) or 1

    demo_discussed = sum(1 for d in enriched if d["commercial_state"]["demo_discussed"])
    demo_booked = sum(1 for d in enriched if d["commercial_state"]["demo_booked"])
    demo_completed = sum(1 for d in enriched if d["commercial_state"]["demo_completed"])
    proposal_discussed = sum(1 for d in enriched if d["commercial_state"]["proposal_discussed"])
    proposal_sent = sum(1 for d in enriched if d["commercial_state"]["proposal_sent"])
    proposal_followed = sum(1 for d in enriched if d["commercial_state"]["proposal_sent"] and not d["commercial_state"]["proposal_unfollowed"])

    boost = sum(1 for d in enriched if d["commercial_state"]["boost_discussed"])
    trade_in = sum(1 for d in enriched if d["commercial_state"]["trade_in_discussed"])
    growth = sum(1 for d in enriched if d["commercial_state"]["growth_program_explained"])

    days_since = [d["commercial_state"]["days_since_proposal"] for d in enriched if d["commercial_state"]["days_since_proposal"] is not None]
    avg_days_since_proposal = round(sum(days_since) / len(days_since), 1) if days_since else None

    booking_rate = round(demo_booked / demo_discussed, 2) if demo_discussed else 0.0
    completion_rate_demo = round(demo_completed / demo_booked, 2) if demo_booked else 0.0
    follow_up_rate = round(proposal_followed / proposal_sent, 2) if proposal_sent else 0.0

    drop_offs = []
    if demo_booked and completion_rate_demo < 0.5:
        drop_offs.append({"key": "low_demo_completion", "label": "Low demo completion rate",
                          "detail": f"Only {int(completion_rate_demo*100)}% of booked demos were completed"})
    if proposal_sent and follow_up_rate < 0.6:
        drop_offs.append({"key": "low_proposal_followup", "label": "Low proposal follow-up rate",
                          "detail": f"Only {int(follow_up_rate*100)}% of proposals had follow-up"})
    if avg_days_since_proposal is not None and avg_days_since_proposal > 14:
        drop_offs.append({"key": "stale_proposals", "label": "Proposals are aging",
                          "detail": f"Average {avg_days_since_proposal} days since proposal sent"})

    # Pricing context gaps lists
    no_boost = [{"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"], "assigned_tm_id": d.get("assigned_tm_id")}
                for d in enriched if not d["commercial_state"]["boost_discussed"]][:20]
    no_trade_in = [{"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"], "assigned_tm_id": d.get("assigned_tm_id")}
                   for d in enriched if not d["commercial_state"]["trade_in_discussed"]][:20]
    no_growth = [{"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"], "assigned_tm_id": d.get("assigned_tm_id")}
                 for d in enriched if not d["commercial_state"]["growth_program_explained"]][:20]

    # Barriers by stage
    visits = await db.visits.find(team_q, {"_id": 0}).to_list(5000)
    doc_state = {d["id"]: d["commercial_state"] for d in enriched}
    pre_demo: dict = {}
    post_demo: dict = {}
    post_proposal: dict = {}
    for v in visits:
        cs = doc_state.get(v["doctor_id"]) or {}
        bucket = "pre_demo"
        if cs.get("proposal_sent"):
            bucket = "post_proposal"
        elif cs.get("demo_completed"):
            bucket = "post_demo"
        target_dict = pre_demo if bucket == "pre_demo" else post_demo if bucket == "post_demo" else post_proposal
        for b in v.get("confirmed_barriers", []):
            target_dict[b] = target_dict.get(b, 0) + 1
    def top(d):
        return [{"name": k, "count": v} for k, v in sorted(d.items(), key=lambda x: -x[1])[:6]]

    return {
        "totals": {"doctors": len(enriched)},
        "demo_funnel": {
            "discussed": demo_discussed,
            "booked": demo_booked,
            "completed": demo_completed,
            "booking_rate": booking_rate,
            "completion_rate": completion_rate_demo,
        },
        "proposal_funnel": {
            "discussed": proposal_discussed,
            "sent": proposal_sent,
            "followed_up": proposal_followed,
            "follow_up_rate": follow_up_rate,
            "avg_days_since_proposal": avg_days_since_proposal,
        },
        "pricing_coverage": {
            "boost_pct": round(boost / total, 2),
            "trade_in_pct": round(trade_in / total, 2),
            "growth_pct": round(growth / total, 2),
            "no_boost": no_boost,
            "no_trade_in": no_trade_in,
            "no_growth": no_growth,
        },
        "drop_offs": drop_offs,
        "barriers_by_stage": {
            "pre_demo": top(pre_demo),
            "post_demo": top(post_demo),
            "post_proposal": top(post_proposal),
        },
    }


# ====================================================
# INTERVENTION (manager)
# ====================================================
@api.get("/dashboard/manager/interventions")
async def manager_interventions(stale_proposal_days: int = 7, user=Depends(require_roles("Manager", "Admin"))):
    team_q = {} if user["role"] == "Admin" else {"team_id": user.get("team_id")}
    docs = await db.doctors.find(team_q, {"_id": 0}).to_list(2000)
    enriched = [await _enrich_doctor(d) for d in docs]
    user_q = {**({"team_id": user.get("team_id")} if user["role"] == "Manager" else {}), "role": "TM"}
    tms = await db.users.find(user_q, {"_id": 0, "password_hash": 0}).to_list(500)
    tm_name = {t["id"]: t["full_name"] for t in tms}

    today = datetime.now(timezone.utc).date()

    critical = []
    at_risk = []
    high_opportunity = []

    for d in enriched:
        cs = d["commercial_state"]
        # CRITICAL
        if cs["proposal_sent"] and cs["days_since_proposal"] is not None and cs["days_since_proposal"] > stale_proposal_days and not cs["proposal_follow_up_done"]:
            critical.append({
                "doctor_id": d["id"], "doctor_name": d["doctor_name"], "tm_id": d.get("assigned_tm_id"),
                "tm_name": tm_name.get(d.get("assigned_tm_id"), "—"), "segment": d["segment"],
                "issue": f"Proposal sent {cs['days_since_proposal']}d ago — no follow-up yet",
                "suggested_action": "Schedule a follow-up call/visit this week",
                "score": d["visit_priority_score"],
            })
        if cs["demo_booked"] and not cs["demo_completed"]:
            critical.append({
                "doctor_id": d["id"], "doctor_name": d["doctor_name"], "tm_id": d.get("assigned_tm_id"),
                "tm_name": tm_name.get(d.get("assigned_tm_id"), "—"), "segment": d["segment"],
                "issue": "Demo booked but not completed",
                "suggested_action": "Confirm or reschedule the demo",
                "score": d["visit_priority_score"],
            })
        if d["segment"] in ("Engaged", "Expert") and (d["days_since_last_visit"] is None or d["days_since_last_visit"] > d["cadence_target_days"] * 1.5):
            critical.append({
                "doctor_id": d["id"], "doctor_name": d["doctor_name"], "tm_id": d.get("assigned_tm_id"),
                "tm_name": tm_name.get(d.get("assigned_tm_id"), "—"), "segment": d["segment"],
                "issue": f"High-segment doctor ({d['segment']}) not visited in {d['days_since_last_visit'] or '∞'}d",
                "suggested_action": "Plan a visit this week",
                "score": d["visit_priority_score"],
            })
        # AT-RISK
        if d["sentiment_trend"] == "declining":
            at_risk.append({
                "doctor_id": d["id"], "doctor_name": d["doctor_name"], "tm_id": d.get("assigned_tm_id"),
                "tm_name": tm_name.get(d.get("assigned_tm_id"), "—"), "segment": d["segment"],
                "issue": "Sentiment trending down",
                "suggested_action": "Address recent barriers in next visit",
                "score": d["visit_priority_score"],
            })
        if d["overdue_promises"] >= 2:
            at_risk.append({
                "doctor_id": d["id"], "doctor_name": d["doctor_name"], "tm_id": d.get("assigned_tm_id"),
                "tm_name": tm_name.get(d.get("assigned_tm_id"), "—"), "segment": d["segment"],
                "issue": f"{d['overdue_promises']} overdue promises piling up",
                "suggested_action": "Close commitments before adding new ones",
                "score": d["visit_priority_score"],
            })
        # HIGH-OPPORTUNITY
        if cs["demo_completed"]:
            try:
                done = cs.get("demo_completed_date")
                if done:
                    d_done = datetime.fromisoformat(done).date()
                    if (today - d_done).days <= 30 and not cs["proposal_sent"]:
                        high_opportunity.append({
                            "doctor_id": d["id"], "doctor_name": d["doctor_name"], "tm_id": d.get("assigned_tm_id"),
                            "tm_name": tm_name.get(d.get("assigned_tm_id"), "—"), "segment": d["segment"],
                            "issue": "Demo completed recently — proposal not yet sent",
                            "suggested_action": "Send a tailored proposal within the week",
                            "score": d["visit_priority_score"],
                        })
            except Exception:
                pass
        if d["current_sentiment"] in ("Positive", "Very Positive") and (cs["boost_discussed"] or cs["growth_program_explained"]) and not cs["proposal_sent"]:
            high_opportunity.append({
                "doctor_id": d["id"], "doctor_name": d["doctor_name"], "tm_id": d.get("assigned_tm_id"),
                "tm_name": tm_name.get(d.get("assigned_tm_id"), "—"), "segment": d["segment"],
                "issue": "Strong engagement + pricing context discussed — no follow-up yet",
                "suggested_action": "Move to proposal or book demo",
                "score": d["visit_priority_score"],
            })

    # de-duplicate by doctor + issue
    def dedup(items):
        seen = set()
        out = []
        for it in items:
            k = (it["doctor_id"], it["issue"])
            if k in seen:
                continue
            seen.add(k)
            out.append(it)
        return sorted(out, key=lambda x: -x["score"])

    return {
        "critical": dedup(critical),
        "at_risk": dedup(at_risk),
        "high_opportunity": dedup(high_opportunity),
    }


# ====================================================
# iTero TRACK DASHBOARDS
# ====================================================
def _track_filter_visits(track: str):
    """Return mongo filter for visits scoped to a track."""
    if track == "ITERO":
        return {"track_type": {"$in": ["ITERO", "BOTH"]}}
    if track == "INVISALIGN":
        return {"track_type": {"$in": ["INVISALIGN", "BOTH"]}}
    return {}


@api.get("/dashboard/manager/itero")
async def manager_itero(user=Depends(require_roles("Manager", "Admin"))):
    team_q = {} if user["role"] == "Admin" else {"team_id": user.get("team_id")}
    docs = await db.doctors.find(team_q, {"_id": 0}).to_list(2000)
    enriched = [await _enrich_doctor(d) for d in docs]

    discussed = sum(1 for d in enriched if d["itero_state"]["demo_discussed"])
    booked = sum(1 for d in enriched if d["itero_state"]["demo_booked"])
    completed = sum(1 for d in enriched if d["itero_state"]["demo_completed"])
    pending = sum(1 for d in enriched if d["itero_state"]["demo_pending"])
    booking_rate = round(booked / discussed, 2) if discussed else 0.0
    completion_rate = round(completed / booked, 2) if booked else 0.0

    interest_buckets: dict = {"High": 0, "Medium": 0, "Low": 0, "None": 0}
    concerns_counts: dict = {}
    for d in enriched:
        s = d["itero_state"]
        interest_buckets[s["scanner_interest_level"]] = interest_buckets.get(s["scanner_interest_level"], 0) + 1
        for c in s["scanner_concerns"]:
            concerns_counts[c] = concerns_counts.get(c, 0) + 1
    top_concerns = [{"name": k, "count": v} for k, v in sorted(concerns_counts.items(), key=lambda x: -x[1])[:6]]

    drop_offs = []
    if booked and completion_rate < 0.5:
        drop_offs.append({"key": "low_demo_completion", "label": "Low demo completion rate",
                          "detail": f"Only {int(completion_rate*100)}% of booked demos were completed"})
    if discussed and booking_rate < 0.5:
        drop_offs.append({"key": "low_demo_booking", "label": "Low demo booking rate",
                          "detail": f"Only {int(booking_rate*100)}% of demos discussed got booked"})
    if pending >= 2:
        drop_offs.append({"key": "demos_pending", "label": "Demos booked but not completed",
                          "detail": f"{pending} demos awaiting completion"})

    # TM performance in demos (track-restricted)
    by_tm = {}
    visits = await db.visits.find({**team_q, **_track_filter_visits("ITERO")}, {"_id": 0}).to_list(5000)
    for v in visits:
        ia = v.get("itero_actions") or {}
        legacy = v.get("commercial_actions") or {}
        if not (ia.get("demo_discussed") or legacy.get("demo_discussed") or ia.get("demo_booked") or legacy.get("demo_booked") or ia.get("demo_completed") or legacy.get("demo_completed")):
            continue
        tm = v["tm_user_id"]
        b = by_tm.setdefault(tm, {"tm_id": tm, "demos_discussed": 0, "demos_booked": 0, "demos_completed": 0})
        if ia.get("demo_discussed") or legacy.get("demo_discussed"):
            b["demos_discussed"] += 1
        if ia.get("demo_booked") or legacy.get("demo_booked"):
            b["demos_booked"] += 1
        if ia.get("demo_completed") or legacy.get("demo_completed"):
            b["demos_completed"] += 1
    user_q = {**({"team_id": user.get("team_id")} if user["role"] == "Manager" else {}), "role": "TM"}
    tms = await db.users.find(user_q, {"_id": 0, "password_hash": 0}).to_list(500)
    name_map = {t["id"]: t["full_name"] for t in tms}
    tm_perf = [{**v, "tm_name": name_map.get(v["tm_id"], "—")} for v in by_tm.values()]
    tm_perf.sort(key=lambda r: -r["demos_completed"])

    return {
        "demo_funnel": {"discussed": discussed, "booked": booked, "completed": completed,
                        "pending": pending, "booking_rate": booking_rate, "completion_rate": completion_rate},
        "scanner_interest": interest_buckets,
        "top_concerns": top_concerns,
        "drop_offs": drop_offs,
        "by_tm": tm_perf,
        "totals": {"doctors": len(enriched)},
    }


@api.get("/dashboard/manager/invisalign")
async def manager_invisalign(user=Depends(require_roles("Manager", "Admin"))):
    team_q = {} if user["role"] == "Admin" else {"team_id": user.get("team_id")}
    docs = await db.doctors.find(team_q, {"_id": 0}).to_list(2000)
    enriched = [await _enrich_doctor(d) for d in docs]
    total = len(enriched) or 1

    counts = {
        "growth_program_explained": 0, "certification_interest": 0, "tps_discussed": 0,
        "p2p_suggested": 0, "staff_training_needed": 0,
    }
    clin_buckets = {"High": 0, "Medium": 0, "Low": 0, "Unknown": 0}
    biz_buckets = {"High": 0, "Medium": 0, "Low": 0, "Unknown": 0}
    aff_buckets = {"Confident": 0, "Neutral": 0, "Concerned": 0, "Unknown": 0}
    barriers_by_segment: dict = {}
    growth_opportunities = []

    for d in enriched:
        s = d["invisalign_state"]
        for k in counts.keys():
            if s.get(k):
                counts[k] += 1
        clin_buckets[s["clinical_confidence"]] = clin_buckets.get(s["clinical_confidence"], 0) + 1
        biz_buckets[s["business_confidence"]] = biz_buckets.get(s["business_confidence"], 0) + 1
        aff_buckets[s["patient_affordability_perception"]] = aff_buckets.get(s["patient_affordability_perception"], 0) + 1
        seg = d.get("segment", "Occasional")
        bs = barriers_by_segment.setdefault(seg, {})
        for b in (d.get("top_barriers") or []):
            bs[b] = bs.get(b, 0) + 1
        # Growth opportunities — Invisalign-leaning signals
        if d["current_sentiment"] in ("Positive", "Very Positive") and (s["certification_interest"] or s["growth_program_explained"]):
            growth_opportunities.append({
                "id": d["id"], "doctor_name": d["doctor_name"], "segment": seg,
                "reason": "Positive sentiment + interested in certification/growth program",
                "score": d["visit_priority_score"],
            })
        elif s["staff_training_needed"] and d["segment"] in ("Active", "Engaged", "Expert"):
            growth_opportunities.append({
                "id": d["id"], "doctor_name": d["doctor_name"], "segment": seg,
                "reason": "Asked for staff training — book TPS",
                "score": d["visit_priority_score"],
            })

    # Doctors lacking growth program explanation (gap)
    no_growth = [{"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"]}
                 for d in enriched if not d["invisalign_state"]["growth_program_explained"]][:20]
    low_clin_conf = [{"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"]}
                     for d in enriched if d["invisalign_state"]["clinical_confidence"] == "Low"][:20]
    low_biz_conf = [{"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"]}
                    for d in enriched if d["invisalign_state"]["business_confidence"] == "Low"][:20]

    # Barriers by segment normalised to top 5 each
    segment_barriers = {}
    for seg, bs in barriers_by_segment.items():
        segment_barriers[seg] = [{"name": k, "count": v} for k, v in sorted(bs.items(), key=lambda x: -x[1])[:5]]

    return {
        "totals": {"doctors": total},
        "coverage": {
            "growth_program_pct": round(counts["growth_program_explained"] / total, 2),
            "certification_pct": round(counts["certification_interest"] / total, 2),
            "tps_pct": round(counts["tps_discussed"] / total, 2),
            "p2p_pct": round(counts["p2p_suggested"] / total, 2),
            "training_pct": round(counts["staff_training_needed"] / total, 2),
            "no_growth": no_growth,
        },
        "confidence": {
            "clinical": clin_buckets,
            "business": biz_buckets,
            "low_clinical_doctors": low_clin_conf,
            "low_business_doctors": low_biz_conf,
        },
        "affordability": aff_buckets,
        "barriers_by_segment": segment_barriers,
        "growth_opportunities": sorted(growth_opportunities, key=lambda x: -x["score"])[:10],
    }


@api.get("/dashboard/manager/cross-sell")
async def manager_cross_sell(user=Depends(require_roles("Manager", "Admin"))):
    team_q = {} if user["role"] == "Admin" else {"team_id": user.get("team_id")}
    docs = await db.doctors.find(team_q, {"_id": 0}).to_list(2000)
    enriched = [await _enrich_doctor(d) for d in docs]

    inv_strong_no_itero = []
    itero_low_invisalign = []
    high_both = []
    for d in enriched:
        i = d["itero_state"]
        v = d["invisalign_state"]
        # Invisalign strong + no iTero activity
        if (v["growth_program_explained"] or v["certification_interest"] or d["segment"] in ("Engaged", "Expert")) and not i["has_itero_activity"]:
            inv_strong_no_itero.append({
                "id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"],
                "reason": "Strong Invisalign engagement — no iTero discussion yet",
                "suggested_action": "Introduce iTero scanner — start with demo discussion",
                "score": d["visit_priority_score"],
            })
        # iTero present but low Invisalign usage
        if i["has_itero_activity"] and (v["clinical_confidence"] == "Low" or not v["growth_program_explained"]):
            itero_low_invisalign.append({
                "id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"],
                "reason": "Has iTero traction but Invisalign confidence/usage is low",
                "suggested_action": "Book P2P or TPS to grow Invisalign side",
                "score": d["visit_priority_score"],
            })
        # High opportunity for both
        if d["current_sentiment"] in ("Positive", "Very Positive") and i["demo_completed"] and v["growth_program_explained"]:
            high_both.append({
                "id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"],
                "reason": "Positive on both tracks — demo completed AND growth program explained",
                "suggested_action": "Move both tracks to proposal stage",
                "score": d["visit_priority_score"],
            })

    def s(x): return sorted(x, key=lambda i: -i["score"])
    return {
        "invisalign_strong_no_itero": s(inv_strong_no_itero)[:20],
        "itero_present_low_invisalign": s(itero_low_invisalign)[:20],
        "high_opportunity_both": s(high_both)[:20],
    }


@api.get("/dashboard/tm/itero")
async def tm_itero(user=Depends(get_current_user)):
    if user["role"] != "TM":
        raise HTTPException(status_code=403, detail="TM only")
    docs = await db.doctors.find({"assigned_tm_id": user["id"]}, {"_id": 0}).to_list(500)
    enriched = [await _enrich_doctor(d) for d in docs]
    # demos awaiting follow-up
    follow_ups = []
    for d in enriched:
        s = d["itero_state"]
        if s["demo_pending"]:
            follow_ups.append({"id": d["id"], "doctor_name": d["doctor_name"],
                               "issue": "Demo booked — confirm and complete",
                               "suggested_action": "Confirm or reschedule the demo this week",
                               "score": d["visit_priority_score"]})
        elif s["demo_completed"] and s.get("demo_completed_date"):
            try:
                ddone = datetime.fromisoformat(s["demo_completed_date"]).date()
                if (datetime.now(timezone.utc).date() - ddone).days <= 14:
                    follow_ups.append({"id": d["id"], "doctor_name": d["doctor_name"],
                                       "issue": "Demo completed recently — drive next step",
                                       "suggested_action": "Send follow-up materials / book a check-in",
                                       "score": d["visit_priority_score"]})
            except Exception:
                pass
    discussed = sum(1 for d in enriched if d["itero_state"]["demo_discussed"])
    booked = sum(1 for d in enriched if d["itero_state"]["demo_booked"])
    completed = sum(1 for d in enriched if d["itero_state"]["demo_completed"])
    interest = {"High": 0, "Medium": 0, "Low": 0, "None": 0}
    for d in enriched:
        interest[d["itero_state"]["scanner_interest_level"]] = interest.get(d["itero_state"]["scanner_interest_level"], 0) + 1
    high_interest_doctors = [{"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"]}
                             for d in enriched if d["itero_state"]["scanner_interest_level"] in ("Medium", "High")][:10]
    return {
        "demo_funnel": {"discussed": discussed, "booked": booked, "completed": completed},
        "scanner_interest": interest,
        "follow_ups": sorted(follow_ups, key=lambda x: -x["score"])[:20],
        "high_interest_doctors": high_interest_doctors,
    }


@api.get("/dashboard/tm/invisalign")
async def tm_invisalign(user=Depends(get_current_user)):
    if user["role"] != "TM":
        raise HTTPException(status_code=403, detail="TM only")
    docs = await db.doctors.find({"assigned_tm_id": user["id"]}, {"_id": 0}).to_list(500)
    enriched = [await _enrich_doctor(d) for d in docs]
    cert_interest = [{"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"]}
                     for d in enriched if d["invisalign_state"]["certification_interest"]][:15]
    needs_tps_p2p = [{"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"],
                      "reason": "TPS discussed" if d["invisalign_state"]["tps_discussed"] else "P2P suggested" if d["invisalign_state"]["p2p_suggested"] else "Staff training needed"}
                     for d in enriched if d["invisalign_state"]["tps_discussed"] or d["invisalign_state"]["p2p_suggested"] or d["invisalign_state"]["staff_training_needed"]][:15]
    confidence_barriers = [{"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"],
                            "issue": "Low clinical confidence" if d["invisalign_state"]["clinical_confidence"] == "Low" else "Low business confidence"}
                           for d in enriched if d["invisalign_state"]["clinical_confidence"] == "Low" or d["invisalign_state"]["business_confidence"] == "Low"][:15]
    growth_explained = sum(1 for d in enriched if d["invisalign_state"]["growth_program_explained"])
    return {
        "totals": {"doctors": len(enriched)},
        "growth_program_explained_count": growth_explained,
        "certification_interest_doctors": cert_interest,
        "needs_tps_p2p_training": needs_tps_p2p,
        "confidence_barriers": confidence_barriers,
    }


# ====================================================
# WEEKLY REPORTS
# ====================================================
async def _build_report_draft(tm_user, week_start_iso: str, week_end_iso: str) -> dict:
    tm_id = tm_user["id"]
    visits = await db.visits.find({
        "tm_user_id": tm_id,
        "visit_date": {"$gte": week_start_iso, "$lte": week_end_iso + "T23:59:59"}
    }, {"_id": 0}).to_list(2000)
    tasks_created = await db.tasks.find({
        "tm_user_id": tm_id,
        "created_at": {"$gte": week_start_iso, "$lte": week_end_iso + "T23:59:59"}
    }, {"_id": 0}).to_list(2000)
    tasks_completed = await db.tasks.find({
        "tm_user_id": tm_id,
        "status": "Completed",
        "completed_at": {"$gte": week_start_iso, "$lte": week_end_iso + "T23:59:59"}
    }, {"_id": 0}).to_list(2000)
    today = datetime.now(timezone.utc).date().isoformat()
    overdue = await db.tasks.count_documents({
        "tm_user_id": tm_id,
        "status": {"$in": ["Open", "Overdue"]},
        "due_date": {"$lt": today},
    })

    doctor_ids = {v["doctor_id"] for v in visits}
    topic_counts: dict = {}
    barrier_counts: dict = {}
    sentiment_counts: dict = {}
    for v in visits:
        for t in v.get("confirmed_topics", []):
            topic_counts[t] = topic_counts.get(t, 0) + 1
        for b in v.get("confirmed_barriers", []):
            barrier_counts[b] = barrier_counts.get(b, 0) + 1
        s = v.get("sentiment") or "Neutral"
        sentiment_counts[s] = sentiment_counts.get(s, 0) + 1
    top_topics = [k for k, _ in sorted(topic_counts.items(), key=lambda x: -x[1])[:6]]
    top_barriers = [k for k, _ in sorted(barrier_counts.items(), key=lambda x: -x[1])[:6]]

    # doctors needing attention next week
    my_docs = await db.doctors.find({"assigned_tm_id": tm_id}, {"_id": 0}).to_list(500)
    enriched = [await _enrich_doctor(d) for d in my_docs]
    enriched.sort(key=lambda d: d["visit_priority_score"], reverse=True)
    needing = [
        {"id": d["id"], "doctor_name": d["doctor_name"], "segment": d["segment"],
         "reason": (d.get("suggested_next_action") or _suggested_reason(d, [])), "score": d["visit_priority_score"]}
        for d in enriched if d["visit_priority_score"] >= 55
    ][:6]

    # auto summary
    parts = []
    parts.append(f"{len(visits)} visit{'s' if len(visits)!=1 else ''} across {len(doctor_ids)} doctor{'s' if len(doctor_ids)!=1 else ''} this week.")
    if top_barriers:
        parts.append("Most-heard barriers: " + ", ".join(top_barriers[:3]) + ".")
    if top_topics:
        parts.append("Most-discussed topics: " + ", ".join(top_topics[:3]) + ".")
    parts.append(f"{len(tasks_created)} promise{'s' if len(tasks_created)!=1 else ''} created, {len(tasks_completed)} completed, {overdue} overdue.")
    if needing:
        parts.append(f"{len(needing)} high-priority doctor{'s' if len(needing)!=1 else ''} need attention next week.")

    insights = []
    if overdue >= 3:
        insights.append(f"⚠️ {overdue} overdue promises — close these before adding new commitments.")
    if len(tasks_created) > 0:
        completion_pct = int((len(tasks_completed) / max(len(tasks_created), 1)) * 100)
        if completion_pct >= 80:
            insights.append(f"✓ Strong follow-up week — {completion_pct}% of new promises closed.")
        elif completion_pct < 40 and len(tasks_created) >= 3:
            insights.append(f"⚠️ Low closure rate — only {completion_pct}% of new promises closed.")
    if top_barriers and "Patient affordability concern" in top_barriers:
        insights.append("Affordability concern keeps coming up — consider growth-program coaching next week.")
    if needing:
        insights.append(f"Plan visits to: {', '.join([n['doctor_name'] for n in needing[:3]])}.")

    # Commercial momentum from this week's visits
    demos_discussed = sum(1 for v in visits if (v.get("commercial_actions") or {}).get("demo_discussed"))
    demos_booked = sum(1 for v in visits if (v.get("commercial_actions") or {}).get("demo_booked"))
    demos_completed = sum(1 for v in visits if (v.get("commercial_actions") or {}).get("demo_completed"))
    proposals_sent = sum(1 for v in visits if (v.get("commercial_actions") or {}).get("proposal_sent"))
    proposals_followed = sum(1 for v in visits if (v.get("commercial_actions") or {}).get("proposal_follow_up_done"))
    if demos_completed:
        insights.append(f"✓ {demos_completed} demo{'s' if demos_completed != 1 else ''} completed this week.")
    if proposals_sent and not proposals_followed:
        insights.append(f"⚠️ {proposals_sent} proposal{'s' if proposals_sent != 1 else ''} sent — schedule follow-ups.")

    # Per-doctor breakdown for the week — one row per doctor visited
    doctor_lookup = {d["id"]: d for d in (await db.doctors.find({"id": {"$in": list(doctor_ids)}}, {"_id": 0}).to_list(2000))}
    # Tasks created this week, grouped by doctor
    tasks_by_doctor: dict = {}
    for tk in tasks_created:
        tasks_by_doctor.setdefault(tk.get("doctor_id"), []).append(tk)
    # Aggregate visits per doctor
    visits_by_doctor: dict = {}
    for v in visits:
        visits_by_doctor.setdefault(v["doctor_id"], []).append(v)
    breakdown = []
    for did, vs in visits_by_doctor.items():
        d = doctor_lookup.get(did) or {}
        # Sort visits chronologically
        vs.sort(key=lambda x: x.get("visit_date", ""))
        last_visit = vs[-1]
        topics_set = []
        barriers_set = []
        sentiments = []
        for v in vs:
            for t in v.get("confirmed_topics", []):
                if t not in topics_set:
                    topics_set.append(t)
            for b in v.get("confirmed_barriers", []):
                if b not in barriers_set:
                    barriers_set.append(b)
            s = v.get("sentiment")
            if s:
                sentiments.append(s)
        # Use last sentiment as latest indicator
        latest_sentiment = sentiments[-1] if sentiments else "—"
        # Promises this week tied to this doctor
        d_tasks = tasks_by_doctor.get(did, [])
        promise_titles = [t.get("task_title") for t in d_tasks if t.get("task_title")]
        # Pull a short note excerpt from the last visit (truncated)
        note = (last_visit.get("free_text_note") or "").strip()
        if len(note) > 220:
            note = note[:217] + "…"
        breakdown.append({
            "doctor_id": did,
            "doctor_name": d.get("doctor_name") or "—",
            "clinic_name": d.get("clinic_name"),
            "city": d.get("city"),
            "segment": d.get("segment"),
            "visits_count": len(vs),
            "last_visit_date": last_visit.get("visit_date", "")[:10],
            "topics": topics_set[:5],
            "barriers": barriers_set[:5],
            "sentiment": latest_sentiment,
            "promises_count": len(promise_titles),
            "promises": promise_titles[:5],
            "note_excerpt": note,
        })
    # Sort by visit count desc, then last visit desc
    breakdown.sort(key=lambda x: (-x["visits_count"], x["last_visit_date"]), reverse=False)
    breakdown.sort(key=lambda x: (-x["visits_count"], x["last_visit_date"] or ""), reverse=True)

    content = {
        "visits_completed": len(visits),
        "doctors_visited": len(doctor_ids),
        "topics_discussed": top_topics,
        "barriers_heard": top_barriers,
        "promises_created": len(tasks_created),
        "promises_completed": len(tasks_completed),
        "overdue_promises": overdue,
        "sentiment_summary": sentiment_counts,
        "key_insights": insights,
        "doctors_needing_attention": needing,
        "doctor_breakdown": breakdown,
        "notes_from_tm": "",
        "demos_discussed": demos_discussed,
        "demos_booked": demos_booked,
        "demos_completed": demos_completed,
        "proposals_sent": proposals_sent,
        "proposals_followed_up": proposals_followed,
    }
    return {
        "tm_user_id": tm_id,
        "tm_name": tm_user["full_name"],
        "team_id": tm_user.get("team_id"),
        "week_start": week_start_iso,
        "week_end": week_end_iso,
        "auto_summary": " ".join(parts),
        "content": content,
        "notes_from_tm": "",
    }


@api.post("/reports/generate")
async def generate_report(user=Depends(get_current_user)):
    if user["role"] != "TM":
        # Admin/Manager can preview their own (no-op)
        raise HTTPException(status_code=403, detail="Only TMs generate reports")
    monday, sunday = _week_bounds()
    draft = await _build_report_draft(user, monday.date().isoformat(), sunday.date().isoformat())
    return draft


@api.post("/reports")
async def create_report(body: ReportCreate, user=Depends(get_current_user)):
    if user["role"] != "TM":
        raise HTTPException(status_code=403, detail="Only TMs create reports")
    # Reuse existing draft for the same week if any
    existing = await db.reports.find_one({
        "tm_user_id": user["id"],
        "week_start": body.week_start,
        "status": "Draft",
    }, {"_id": 0})
    if existing:
        update = {
            "auto_summary": body.auto_summary,
            "content": body.content.model_dump(),
            "notes_from_tm": body.notes_from_tm,
            "updated_at": _now_iso(),
        }
        await db.reports.update_one({"id": existing["id"]}, {"$set": update})
        new = await db.reports.find_one({"id": existing["id"]}, {"_id": 0})
        return new

    doc = WeeklyReport(
        tm_user_id=user["id"],
        tm_name=user["full_name"],
        team_id=user.get("team_id"),
        week_start=body.week_start,
        week_end=body.week_end,
        status="Draft",
        auto_summary=body.auto_summary,
        content=body.content,
        notes_from_tm=body.notes_from_tm,
    ).model_dump()
    await db.reports.insert_one(doc)
    await _audit(user, "create", "report", doc["id"], new={"week_start": body.week_start})
    _strip_id(doc)
    return doc


@api.put("/reports/{report_id}")
async def update_report(report_id: str, body: ReportUpdate, user=Depends(get_current_user)):
    r = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if r["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if r["status"] != "Draft":
        raise HTTPException(status_code=400, detail="Cannot edit a submitted report")
    update = body.model_dump(exclude_none=True)
    if "content" in update and update["content"] is not None:
        # already a dict from model_dump
        pass
    update["updated_at"] = _now_iso()
    await db.reports.update_one({"id": report_id}, {"$set": update})
    new = await db.reports.find_one({"id": report_id}, {"_id": 0})
    return new


@api.post("/reports/{report_id}/submit")
async def submit_report(report_id: str, user=Depends(get_current_user)):
    r = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if r["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if r["status"] == "Submitted":
        return r
    await db.reports.update_one({"id": report_id}, {"$set": {
        "status": "Submitted",
        "submitted_at": _now_iso(),
        "updated_at": _now_iso(),
    }})
    await _audit(user, "update", "report", report_id, prev={"status": r["status"]}, new={"status": "Submitted"})
    return await db.reports.find_one({"id": report_id}, {"_id": 0})


@api.post("/reports/{report_id}/comment")
async def comment_report(report_id: str, body: dict, user=Depends(require_roles("Manager", "Admin"))):
    r = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if user["role"] == "Manager" and r.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty comment")
    import uuid
    comment = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "user_name": user["full_name"],
        "text": text[:1000],
        "created_at": _now_iso(),
    }
    await db.reports.update_one({"id": report_id}, {
        "$push": {"comments": comment},
        "$set": {"status": "Reviewed", "reviewed_at": _now_iso(), "updated_at": _now_iso()},
    })
    await _audit(user, "update", "report", report_id, new={"comment_added": True})
    return await db.reports.find_one({"id": report_id}, {"_id": 0})


@api.get("/reports")
async def list_reports(
    bucket: Optional[str] = Query(None, description="submitted|pending|overdue|all|mine"),
    user=Depends(get_current_user),
):
    """Reports listing.

    - TM: sees own reports (all statuses).
    - Manager/Admin: sees team reports. `bucket` can be:
        - submitted: status in (Submitted, Reviewed)
        - pending: TMs in scope who have NOT submitted for current week (synthesized rows with status=Pending)
        - overdue: TMs in scope who did NOT submit for previous week (synthesized rows with status=Overdue)
        - all: submitted+reviewed reports for the team
    """
    if user["role"] == "TM":
        q = {"tm_user_id": user["id"]}
        reports = await db.reports.find(q, {"_id": 0}).sort("week_start", -1).to_list(200)
        return {"reports": reports}

    team_q = {} if user["role"] == "Admin" else {"team_id": user.get("team_id")}
    user_q = {**({"team_id": user.get("team_id")} if user["role"] == "Manager" else {}), "role": "TM"}
    tms = await db.users.find(user_q, {"_id": 0, "password_hash": 0}).to_list(500)

    monday, sunday = _week_bounds()
    cur_week_start = monday.date().isoformat()
    prev_monday = monday - timedelta(days=7)
    prev_week_start = prev_monday.date().isoformat()
    prev_week_end = (prev_monday + timedelta(days=6)).date().isoformat()

    if bucket == "pending":
        # current week, not submitted
        submitted = await db.reports.find({**team_q, "week_start": cur_week_start, "status": {"$in": ["Submitted", "Reviewed"]}}, {"_id": 0}).to_list(500)
        submitted_ids = {r["tm_user_id"] for r in submitted}
        result = []
        for tm in tms:
            if tm["id"] in submitted_ids:
                continue
            result.append({
                "synthetic": True,
                "tm_user_id": tm["id"],
                "tm_name": tm["full_name"],
                "tm_email": tm["email"],
                "team_id": tm.get("team_id"),
                "week_start": cur_week_start,
                "week_end": sunday.date().isoformat(),
                "status": "Pending",
            })
        return {"reports": result}

    if bucket == "overdue":
        # previous week, not submitted
        submitted = await db.reports.find({**team_q, "week_start": prev_week_start, "status": {"$in": ["Submitted", "Reviewed"]}}, {"_id": 0}).to_list(500)
        submitted_ids = {r["tm_user_id"] for r in submitted}
        result = []
        for tm in tms:
            if tm["id"] in submitted_ids:
                continue
            result.append({
                "synthetic": True,
                "tm_user_id": tm["id"],
                "tm_name": tm["full_name"],
                "tm_email": tm["email"],
                "team_id": tm.get("team_id"),
                "week_start": prev_week_start,
                "week_end": prev_week_end,
                "status": "Overdue",
            })
        return {"reports": result}

    # default & "submitted" & "all": real reports for team
    q = {**team_q}
    if bucket == "submitted":
        q["status"] = {"$in": ["Submitted", "Reviewed"]}
    reports = await db.reports.find(q, {"_id": 0}).sort("submitted_at", -1).to_list(500)
    return {"reports": reports}


@api.get("/reports/{report_id}")
async def get_report(report_id: str, user=Depends(get_current_user)):
    r = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if user["role"] == "TM" and r["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "Manager" and r.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return r


@api.get("/reports/{report_id}/export")
async def export_report(report_id: str, format: str = "pdf", user=Depends(get_current_user)):
    """Export a weekly report as CSV or PDF. RBAC mirrors GET /reports/{id}."""
    r = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if user["role"] == "TM" and r["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "Manager" and r.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    fmt = (format or "pdf").lower()
    if fmt not in ("csv", "pdf"):
        raise HTTPException(status_code=400, detail="format must be 'csv' or 'pdf'")

    from fastapi.responses import Response
    safe_name = (r.get("tm_name") or "report").replace(" ", "_")
    base = f"weekly_report_{safe_name}_{r.get('week_start','')}"
    await _audit(user, "export", "report", report_id, new={"format": fmt})

    if fmt == "csv":
        import csv
        import io as _io
        buf = _io.StringIO()
        w = csv.writer(buf)
        c = r.get("content", {}) or {}
        w.writerow(["Field", "Value"])
        w.writerow(["TM", r.get("tm_name", "")])
        w.writerow(["Week start", r.get("week_start", "")])
        w.writerow(["Week end", r.get("week_end", "")])
        w.writerow(["Status", r.get("status", "")])
        w.writerow(["Auto summary", r.get("auto_summary", "")])
        w.writerow([])
        w.writerow(["Metric", "Value"])
        for k in ["visits_completed", "doctors_visited", "promises_created", "promises_completed",
                 "overdue_promises", "demos_discussed", "demos_booked", "demos_completed",
                 "proposals_sent", "proposals_followed_up"]:
            w.writerow([k.replace("_", " ").title(), c.get(k, 0)])
        w.writerow([])
        w.writerow(["Top topics", ", ".join(c.get("topics_discussed", []) or [])])
        w.writerow(["Top barriers", ", ".join(c.get("barriers_heard", []) or [])])
        sent = c.get("sentiment_summary", {}) or {}
        w.writerow(["Sentiment", "; ".join(f"{k}: {v}" for k, v in sent.items())])
        w.writerow([])
        w.writerow(["Key insights"])
        for line in (c.get("key_insights", []) or []):
            w.writerow([line])
        w.writerow([])
        w.writerow(["Doctors needing attention", "Segment", "Reason", "Score"])
        for d in (c.get("doctors_needing_attention", []) or []):
            w.writerow([d.get("doctor_name", ""), d.get("segment", ""), d.get("reason", ""), d.get("score", "")])
        w.writerow([])
        # Per-doctor breakdown
        w.writerow(["Per-doctor visit breakdown"])
        w.writerow(["Doctor", "Clinic", "City", "Segment", "Visits", "Last visit", "Sentiment", "Topics", "Barriers", "Promises", "Latest note"])
        for d in (c.get("doctor_breakdown", []) or []):
            w.writerow([
                d.get("doctor_name", ""),
                d.get("clinic_name", "") or "",
                d.get("city", "") or "",
                d.get("segment", "") or "",
                d.get("visits_count", 0),
                d.get("last_visit_date", "") or "",
                d.get("sentiment", "") or "",
                "; ".join(d.get("topics", []) or []),
                "; ".join(d.get("barriers", []) or []),
                "; ".join(d.get("promises", []) or []),
                d.get("note_excerpt", "") or "",
            ])
        w.writerow([])
        w.writerow(["TM notes", c.get("notes_from_tm", "") or r.get("notes_from_tm", "")])
        if r.get("manager_comment"):
            w.writerow(["Manager comment", r["manager_comment"]])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{base}.csv"'},
        )

    # PDF via reportlab
    import io as _io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, ListFlowable, ListItem,
    )

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Weekly Report — {r.get('tm_name','')}",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Eyebrow", parent=styles["Normal"],
                              fontSize=8, textColor=colors.HexColor("#7A8980"),
                              spaceAfter=2, leading=10))
    styles.add(ParagraphStyle(name="H1", parent=styles["Title"], fontSize=22,
                              textColor=colors.HexColor("#274035"), leading=26, spaceAfter=8))
    styles.add(ParagraphStyle(name="H2", parent=styles["Heading2"], fontSize=12,
                              textColor=colors.HexColor("#274035"), spaceBefore=10, spaceAfter=4))
    styles.add(ParagraphStyle(name="Body", parent=styles["Normal"], fontSize=10, leading=14))
    styles.add(ParagraphStyle(name="Muted", parent=styles["Normal"], fontSize=9,
                              textColor=colors.HexColor("#5A6B62"), leading=12))

    flow = []
    flow.append(Paragraph("FIELDMIND · WEEKLY FIELD REPORT", styles["Eyebrow"]))
    flow.append(Paragraph(r.get("tm_name", "Report"), styles["H1"]))
    flow.append(Paragraph(
        f"{r.get('week_start','')} → {r.get('week_end','')}  ·  Status: {r.get('status','Draft')}",
        styles["Muted"],
    ))
    flow.append(Spacer(1, 6))

    if r.get("auto_summary"):
        flow.append(Paragraph("Auto summary", styles["H2"]))
        flow.append(Paragraph(r["auto_summary"], styles["Body"]))

    c = r.get("content", {}) or {}
    flow.append(Paragraph("Activity", styles["H2"]))
    metrics = [
        ["Visits completed", c.get("visits_completed", 0), "Doctors visited", c.get("doctors_visited", 0)],
        ["Promises created", c.get("promises_created", 0), "Promises completed", c.get("promises_completed", 0)],
        ["Overdue promises", c.get("overdue_promises", 0), "Demos completed", c.get("demos_completed", 0)],
        ["Demos discussed", c.get("demos_discussed", 0), "Demos booked", c.get("demos_booked", 0)],
        ["Proposals sent", c.get("proposals_sent", 0), "Proposals followed-up", c.get("proposals_followed_up", 0)],
    ]
    t = Table(metrics, colWidths=[45 * mm, 25 * mm, 50 * mm, 25 * mm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#274035")),
        ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#F4F1EA")),
        ("BACKGROUND", (3, 0), (3, -1), colors.HexColor("#F4F1EA")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2DDD2")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2DDD2")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(t)

    if c.get("topics_discussed"):
        flow.append(Paragraph("Top topics", styles["H2"]))
        flow.append(Paragraph(", ".join(c["topics_discussed"]), styles["Body"]))
    if c.get("barriers_heard"):
        flow.append(Paragraph("Top barriers", styles["H2"]))
        flow.append(Paragraph(", ".join(c["barriers_heard"]), styles["Body"]))

    sent = c.get("sentiment_summary") or {}
    if sent:
        flow.append(Paragraph("Sentiment mix", styles["H2"]))
        flow.append(Paragraph(" · ".join(f"{k}: {v}" for k, v in sent.items()), styles["Body"]))

    if c.get("key_insights"):
        flow.append(Paragraph("Key insights", styles["H2"]))
        items = [ListItem(Paragraph(line, styles["Body"]), leftIndent=8) for line in c["key_insights"]]
        flow.append(ListFlowable(items, bulletType="bullet", start="•"))

    if c.get("doctors_needing_attention"):
        flow.append(Paragraph("Doctors needing attention next week", styles["H2"]))
        rows = [["Doctor", "Segment", "Reason", "Score"]]
        for d in c["doctors_needing_attention"]:
            rows.append([d.get("doctor_name", ""), d.get("segment", ""),
                         d.get("reason", ""), str(d.get("score", ""))])
        att = Table(rows, colWidths=[45 * mm, 25 * mm, 70 * mm, 15 * mm])
        att.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#274035")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E2DDD2")),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2DDD2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#FDFBF7"), colors.white]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        flow.append(att)

    # Per-doctor breakdown — what was discussed at each doctor this week
    breakdown = c.get("doctor_breakdown") or []
    if breakdown:
        flow.append(Paragraph("Per-doctor breakdown", styles["H2"]))
        for d in breakdown:
            head_bits = [Paragraph(f"<b>{d.get('doctor_name','—')}</b>", styles["Body"])]
            sub_bits = []
            if d.get("clinic_name"):
                sub_bits.append(d["clinic_name"])
            if d.get("city"):
                sub_bits.append(d["city"])
            if d.get("segment"):
                sub_bits.append(d["segment"])
            sub_bits.append(f"{d.get('visits_count', 0)} visit{'s' if d.get('visits_count', 0) != 1 else ''}")
            if d.get("last_visit_date"):
                sub_bits.append(f"last {d['last_visit_date']}")
            if d.get("sentiment") and d["sentiment"] != "—":
                sub_bits.append(f"sentiment: {d['sentiment']}")
            head_bits.append(Paragraph(" · ".join(sub_bits), styles["Muted"]))
            if d.get("topics"):
                head_bits.append(Paragraph("<b>Topics:</b> " + ", ".join(d["topics"]), styles["Body"]))
            if d.get("barriers"):
                head_bits.append(Paragraph("<b>Barriers:</b> " + ", ".join(d["barriers"]), styles["Body"]))
            if d.get("promises"):
                head_bits.append(Paragraph("<b>Promises:</b> " + "; ".join(d["promises"]), styles["Body"]))
            if d.get("note_excerpt"):
                head_bits.append(Paragraph(f"<i>{d['note_excerpt']}</i>", styles["Muted"]))
            for elem in head_bits:
                flow.append(elem)
            flow.append(Spacer(1, 6))

    notes = (c.get("notes_from_tm") or r.get("notes_from_tm") or "").strip()
    if notes:
        flow.append(Paragraph("TM notes", styles["H2"]))
        flow.append(Paragraph(notes.replace("\n", "<br/>"), styles["Body"]))

    if r.get("manager_comment"):
        flow.append(Paragraph("Manager comment", styles["H2"]))
        flow.append(Paragraph(r["manager_comment"].replace("\n", "<br/>"), styles["Body"]))

    doc.build(flow)
    pdf_bytes = buf.getvalue()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{base}.pdf"'},
    )



# ====================================================
# AUDIT
# ====================================================
@api.get("/audit")
async def audit_logs(limit: int = 100, user=Depends(require_roles("Admin"))):
    logs = await db.audit_logs.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return logs


# ====================================================
# EXPENSES
# ====================================================
def _month_of(date_iso: str) -> str:
    """Extract YYYY-MM from a YYYY-MM-DD string. Falls back to current month on parse error."""
    try:
        return date_iso[:7]
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m")


def _strip_id(doc):
    if doc and "_id" in doc:
        doc.pop("_id", None)
    return doc


async def _expense_visible_to(user, exp: dict) -> bool:
    if user["role"] == "Admin":
        return True
    if user["role"] == "Manager":
        return exp.get("team_id") == user.get("team_id")
    return exp.get("tm_user_id") == user["id"]


@api.post("/expenses")
async def create_expense(
    expense_date: str = Form(...),
    category: str = Form(...),
    amount: float = Form(...),
    vendor: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    receipt: Optional[UploadFile] = File(None),
    user=Depends(get_current_user),
):
    """Create an expense. Optional receipt upload stored in GridFS. TM only."""
    if user["role"] != "TM":
        raise HTTPException(status_code=403, detail="Only TMs can log expenses")
    if category not in ("Petrol", "Food"):
        raise HTTPException(status_code=400, detail="category must be 'Petrol' or 'Food'")
    if amount < 0:
        raise HTTPException(status_code=400, detail="amount must be non-negative")
    try:
        datetime.strptime(expense_date, "%Y-%m-%d")
    except Exception:
        raise HTTPException(status_code=400, detail="expense_date must be YYYY-MM-DD")

    image_id = None
    image_mime = None
    image_hash = None
    duplicate_of = None
    if receipt is not None:
        raw = await receipt.read()
        if raw:
            if len(raw) > 8 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Receipt image exceeds 8 MB limit")
            from expenses_ai import hash_receipt
            image_hash = hash_receipt(raw)
            # Duplicate check (same TM, same hash, not Rejected)
            existing_dup = await db.expenses.find_one(
                {"tm_user_id": user["id"], "receipt_hash": image_hash, "status": {"$ne": "Rejected"}},
                {"_id": 0, "id": 1, "amount": 1, "expense_date": 1},
            )
            if existing_dup:
                duplicate_of = existing_dup["id"]
            # Store in GridFS via Motor
            from motor.motor_asyncio import AsyncIOMotorGridFSBucket
            bucket = AsyncIOMotorGridFSBucket(db, bucket_name="receipts")
            image_mime = receipt.content_type or "application/octet-stream"
            grid_in_id = await bucket.upload_from_stream(
                receipt.filename or "receipt", raw,
                metadata={"tm_user_id": user["id"], "mime": image_mime, "hash": image_hash},
            )
            image_id = str(grid_in_id)

    import uuid
    exp = {
        "id": str(uuid.uuid4()),
        "tm_user_id": user["id"],
        "tm_name": user.get("full_name", ""),
        "team_id": user.get("team_id"),
        "expense_date": expense_date,
        "submission_month": None,
        "category": category,
        "amount": float(amount),
        "currency": "EUR",
        "vendor": (vendor or "").strip() or None,
        "notes": (notes or "").strip() or None,
        "receipt_image_id": image_id,
        "receipt_mime": image_mime,
        "receipt_hash": image_hash,
        "ocr": None,
        "status": "Draft",
        "submitted_at": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.expenses.insert_one(exp)
    exp.pop("_id", None)
    await _audit(user, "create", "expense", exp["id"], new={"category": category, "amount": amount})
    return {"expense": exp, "duplicate_of": duplicate_of}


@api.post("/expenses/extract")
async def extract_expense_receipt(
    receipt: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """OCR a receipt (no DB write). Returns structured extraction + duplicate hint. TM only."""
    if user["role"] != "TM":
        raise HTTPException(status_code=403, detail="Only TMs can extract receipts")
    raw = await receipt.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty receipt")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Receipt image exceeds 8 MB limit")
    from expenses_ai import extract_receipt as _ocr, hash_receipt as _hash
    h = _hash(raw)
    extracted = await _ocr(raw, mime_type=receipt.content_type or "image/jpeg")
    dup = await db.expenses.find_one(
        {"tm_user_id": user["id"], "receipt_hash": h, "status": {"$ne": "Rejected"}},
        {"_id": 0, "id": 1, "amount": 1, "expense_date": 1, "category": 1},
    )
    return {"extracted": extracted, "duplicate_of": dup}


@api.get("/expenses")
async def list_expenses(
    month: Optional[str] = None,
    status: Optional[str] = None,
    tm_user_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    """List expenses scoped by role.

    - TM: own expenses (any status). `month` filters by expense_date YYYY-MM.
    - Manager: team expenses, optionally filtered by tm_user_id and/or status.
    - Admin: all expenses.
    """
    q: dict = {}
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
        if tm_user_id:
            q["tm_user_id"] = tm_user_id
    # Admin: no scope
    if status:
        q["status"] = status
    if month:
        q["expense_date"] = {"$gte": f"{month}-01", "$lte": f"{month}-31"}
    rows = await db.expenses.find(q, {"_id": 0}).sort([("expense_date", -1), ("created_at", -1)]).to_list(2000)
    return {"expenses": rows}


@api.get("/expenses/summary")
async def expense_summary(
    month: Optional[str] = None,
    tm_user_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Monthly totals + counts. Defaults to current month for TM.

    Manager/Admin may pass tm_user_id to scope to a single TM.
    """
    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
    q: dict = {"expense_date": {"$gte": f"{month}-01", "$lte": f"{month}-31"}}
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
        if tm_user_id:
            q["tm_user_id"] = tm_user_id
    elif tm_user_id:
        q["tm_user_id"] = tm_user_id

    rows = await db.expenses.find(q, {"_id": 0}).to_list(2000)
    by_cat: dict = {"Petrol": 0.0, "Food": 0.0}
    by_status: dict = {"Draft": 0, "Submitted": 0}
    total = 0.0
    for r in rows:
        amt = float(r.get("amount") or 0)
        total += amt
        cat = r.get("category")
        if cat in by_cat:
            by_cat[cat] += amt
        st = r.get("status")
        if st in by_status:
            by_status[st] += 1
    currency = "EUR"
    submittable = sum(1 for r in rows if r.get("status") == "Draft")
    return {
        "month": month,
        "count": len(rows),
        "total": round(total, 2),
        "currency": currency,
        "by_category": {k: round(v, 2) for k, v in by_cat.items()},
        "by_status": by_status,
        "submittable_drafts": submittable,
    }


@api.put("/expenses/{exp_id}")
async def update_expense(exp_id: str, body: ExpenseUpdate, user=Depends(get_current_user)):
    exp = await db.expenses.find_one({"id": exp_id}, {"_id": 0})
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")
    if not await _expense_visible_to(user, exp):
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "TM" and exp.get("tm_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if exp.get("status") != "Draft":
        raise HTTPException(status_code=409, detail="Only Draft expenses can be edited")
    update: dict = {}
    for field in ("expense_date", "category", "amount", "vendor", "notes"):
        v = getattr(body, field, None)
        if v is None:
            continue
        if field == "category" and v not in ("Petrol", "Food"):
            raise HTTPException(status_code=400, detail="category must be 'Petrol' or 'Food'")
        if field == "expense_date":
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except Exception:
                raise HTTPException(status_code=400, detail="expense_date must be YYYY-MM-DD")
        if field == "amount" and v < 0:
            raise HTTPException(status_code=400, detail="amount must be non-negative")
        update[field] = v
    if not update:
        return exp
    update["updated_at"] = _now_iso()
    await db.expenses.update_one({"id": exp_id}, {"$set": update})
    await _audit(user, "update", "expense", exp_id, prev=exp, new=update)
    fresh = await db.expenses.find_one({"id": exp_id}, {"_id": 0})
    return fresh


@api.delete("/expenses/{exp_id}")
async def delete_expense(exp_id: str, user=Depends(get_current_user)):
    exp = await db.expenses.find_one({"id": exp_id}, {"_id": 0})
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")
    if user["role"] != "Admin" and exp.get("tm_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if exp.get("status") != "Draft":
        raise HTTPException(status_code=409, detail="Only Draft expenses can be deleted")
    # Best-effort delete of GridFS attachment
    if exp.get("receipt_image_id"):
        try:
            from bson import ObjectId
            from motor.motor_asyncio import AsyncIOMotorGridFSBucket
            bucket = AsyncIOMotorGridFSBucket(db, bucket_name="receipts")
            await bucket.delete(ObjectId(exp["receipt_image_id"]))
        except Exception:
            logging.exception("Failed to delete GridFS receipt %s", exp["receipt_image_id"])
    await db.expenses.delete_one({"id": exp_id})
    await _audit(user, "delete", "expense", exp_id, prev=exp)
    return {"ok": True, "id": exp_id}


@api.get("/expenses/{exp_id}/receipt")
async def get_expense_receipt(exp_id: str, user=Depends(get_current_user)):
    exp = await db.expenses.find_one({"id": exp_id}, {"_id": 0})
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")
    if not await _expense_visible_to(user, exp):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not exp.get("receipt_image_id"):
        raise HTTPException(status_code=404, detail="No receipt attached")
    try:
        from bson import ObjectId
        from motor.motor_asyncio import AsyncIOMotorGridFSBucket
        from fastapi.responses import StreamingResponse
        bucket = AsyncIOMotorGridFSBucket(db, bucket_name="receipts")
        stream = await bucket.open_download_stream(ObjectId(exp["receipt_image_id"]))
        async def gen():
            while True:
                chunk = await stream.readchunk()
                if not chunk:
                    break
                yield chunk
        return StreamingResponse(gen(), media_type=exp.get("receipt_mime") or "image/jpeg")
    except HTTPException:
        raise
    except Exception:
        logging.exception("Failed to stream receipt")
        raise HTTPException(status_code=404, detail="Receipt not available")


@api.post("/expenses/submit-month")
async def submit_month(body: dict, user=Depends(get_current_user)):
    if user["role"] != "TM":
        raise HTTPException(status_code=403, detail="Only TMs submit months")
    month = (body or {}).get("month") or datetime.now(timezone.utc).strftime("%Y-%m")
    import re as _re
    if not _re.match(r"^\d{4}-\d{2}$", month):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    q = {
        "tm_user_id": user["id"],
        "status": "Draft",
        "expense_date": {"$gte": f"{month}-01", "$lte": f"{month}-31"},
    }
    drafts = await db.expenses.find(q, {"_id": 0, "id": 1}).to_list(1000)
    if not drafts:
        return {"ok": True, "submitted": 0, "month": month}
    now = _now_iso()
    res = await db.expenses.update_many(q, {"$set": {
        "status": "Submitted", "submission_month": month,
        "submitted_at": now, "updated_at": now,
    }})
    await _audit(user, "submit", "expense_month", month, new={"count": res.modified_count})
    return {"ok": True, "submitted": res.modified_count, "month": month}


@api.get("/expenses/team-summary")
async def expense_team_summary(
    month: Optional[str] = None,
    user=Depends(require_roles("Manager", "Admin")),
):
    """Manager/Admin view: per-TM totals + grand total for a given month.

    Manager is scoped to their team; Admin sees everything.
    """
    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
    q: dict = {"expense_date": {"$gte": f"{month}-01", "$lte": f"{month}-31"}}
    if user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    rows = await db.expenses.find(q, {"_id": 0}).to_list(5000)

    by_tm: dict = {}
    grand_total = 0.0
    submitted_count = 0
    for r in rows:
        amt = float(r.get("amount") or 0)
        grand_total += amt
        if r.get("status") == "Submitted":
            submitted_count += 1
        tm_id = r.get("tm_user_id")
        if not tm_id:
            continue
        bucket = by_tm.setdefault(tm_id, {
            "tm_user_id": tm_id,
            "tm_name": r.get("tm_name") or "",
            "total": 0.0,
            "petrol": 0.0,
            "food": 0.0,
            "count": 0,
            "submitted_count": 0,
            "draft_count": 0,
        })
        bucket["total"] += amt
        bucket["count"] += 1
        if r.get("category") == "Petrol":
            bucket["petrol"] += amt
        elif r.get("category") == "Food":
            bucket["food"] += amt
        if r.get("status") == "Submitted":
            bucket["submitted_count"] += 1
        elif r.get("status") == "Draft":
            bucket["draft_count"] += 1

    # round + sort by total desc
    tm_rows = []
    for v in by_tm.values():
        for k in ("total", "petrol", "food"):
            v[k] = round(v[k], 2)
        tm_rows.append(v)
    tm_rows.sort(key=lambda x: x["total"], reverse=True)

    return {
        "month": month,
        "currency": "EUR",
        "grand_total": round(grand_total, 2),
        "count": len(rows),
        "submitted_count": submitted_count,
        "by_tm": tm_rows,
    }


@api.get("/expenses/receipts.zip")
async def download_receipts_zip(
    month: Optional[str] = None,
    tm_user_id: Optional[str] = None,
    status: Optional[str] = None,
    user=Depends(require_roles("Manager", "Admin")),
):
    """Manager/Admin: bundle all receipt images for a filtered set into a ZIP."""
    import io as _io
    import zipfile
    from bson import ObjectId
    from motor.motor_asyncio import AsyncIOMotorGridFSBucket
    from fastapi.responses import Response

    q: dict = {}
    if user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    if month:
        q["expense_date"] = {"$gte": f"{month}-01", "$lte": f"{month}-31"}
    if tm_user_id:
        q["tm_user_id"] = tm_user_id
    if status:
        q["status"] = status
    # only entries with a receipt
    q["receipt_image_id"] = {"$ne": None}

    rows = await db.expenses.find(q, {"_id": 0}).sort([("tm_name", 1), ("expense_date", -1)]).to_list(5000)
    if not rows:
        raise HTTPException(status_code=404, detail="No receipts to download")

    buf = _io.BytesIO()
    bucket = AsyncIOMotorGridFSBucket(db, bucket_name="receipts")
    used = set()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            try:
                stream = await bucket.open_download_stream(ObjectId(r["receipt_image_id"]))
                data = await stream.read()
            except Exception:
                continue
            mime = (r.get("receipt_mime") or "image/jpeg").lower()
            ext = "jpg"
            if "png" in mime:
                ext = "png"
            elif "webp" in mime:
                ext = "webp"
            tm = (r.get("tm_name") or "tm").replace(" ", "_").replace("/", "_")
            base = f"{tm}/{r.get('expense_date','')}_{(r.get('vendor') or r.get('category') or 'receipt').replace(' ', '_').replace('/', '_')}_{r['id'][:8]}.{ext}"
            name = base
            i = 2
            while name in used:
                name = base.rsplit(".", 1)[0] + f"-{i}." + ext
                i += 1
            used.add(name)
            zf.writestr(name, data)

    payload = buf.getvalue()
    label = month or "all"
    if tm_user_id:
        label += f"_{tm_user_id[:8]}"
    fname = f"receipts_{label}.zip"
    await _audit(user, "export", "expense_receipts", label, new={"count": len(rows), "month": month})
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ====================================================
# Health
# ====================================================
@api.get("/")
async def root():
    return {"service": "Field Intelligence Platform", "status": "ok"}


# Include router
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def on_startup():
    # Indexes
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.teams.create_index("id", unique=True)
    await db.doctors.create_index("id", unique=True)
    await db.doctors.create_index([("assigned_tm_id", 1)])
    await db.doctors.create_index([("team_id", 1)])
    await db.doctors.create_index([("city", 1)])
    await db.doctors.create_index([("segment", 1)])
    await db.doctors.create_index([("doctor_name", "text"), ("clinic_name", "text"), ("city", "text")])
    await db.visits.create_index("id", unique=True)
    await db.visits.create_index([("doctor_id", 1), ("visit_date", -1)])
    await db.visits.create_index([("tm_user_id", 1)])
    await db.visits.create_index([("team_id", 1)])
    await db.tasks.create_index("id", unique=True)
    await db.tasks.create_index([("doctor_id", 1), ("due_date", 1)])
    await db.tasks.create_index([("tm_user_id", 1), ("status", 1)])
    await db.tasks.create_index([("team_id", 1)])
    await db.audit_logs.create_index([("timestamp", -1)])
    await db.reports.create_index("id", unique=True)
    await db.reports.create_index([("tm_user_id", 1), ("week_start", -1)])
    await db.reports.create_index([("team_id", 1), ("status", 1)])
    await db.expenses.create_index("id", unique=True)
    await db.expenses.create_index([("tm_user_id", 1), ("expense_date", -1)])
    await db.expenses.create_index([("team_id", 1), ("expense_date", -1)])
    await db.expenses.create_index([("receipt_hash", 1), ("tm_user_id", 1)])
    await db.meetings.create_index("id", unique=True)
    await db.meetings.create_index([("tm_user_id", 1), ("scheduled_at", 1)])
    await db.meetings.create_index([("doctor_id", 1)])
    await db.meetings.create_index([("team_id", 1), ("scheduled_at", 1)])
    await db.itero_stage_history.create_index([("doctor_id", 1), ("at", -1)])
    await db.events.create_index("id", unique=True)
    await db.events.create_index([("tm_user_id", 1), ("scheduled_at", 1)])
    await db.events.create_index([("team_id", 1), ("scheduled_at", 1)])
    # Migration: normalise legacy approval statuses (no-op on fresh DBs)
    await db.expenses.update_many(
        {"status": {"$in": ["Approved", "Rejected"]}},
        {"$set": {"status": "Submitted"}, "$unset": {"manager_comment": "", "reviewed_at": ""}},
    )
    await db.expenses.update_many(
        {"currency": {"$ne": "EUR"}},
        {"$set": {"currency": "EUR"}},
    )
    # Bootstrap platform Owner (idempotent)
    try:
        owner_report = await seed_owner(db)
        logger.info(f"Owner seed: {owner_report}")
    except Exception as e:
        logger.error(f"Owner seed failed: {e}")
    logger.info("Field Intelligence Platform started.")


@app.on_event("shutdown")
async def on_shutdown():
    mongo_client.close()
