"""Field Intelligence Platform — main FastAPI server.

All routes are prefixed with /api.
"""
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Query
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional

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
    WeeklyReport,
    ReportCreate,
    ReportUpdate,
    ReportContent,
    ReportComment,
)
from ai import analyze_note as ai_analyze_note
from seed import seed_demo

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
DEFAULT_CADENCE = {"Occasional": 60, "Active": 45, "Engaged": 30, "Expert": 21}


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
    score += {"Occasional": 5, "Active": 15, "Engaged": 25, "Expert": 35}.get(seg, 10)
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
    }
    return enriched


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
    import uuid
    doc = {
        "id": str(uuid.uuid4()),
        "full_name": body.full_name,
        "email": body.email.lower(),
        "password_hash": hash_password(body.password),
        "role": body.role,
        "team_id": body.team_id,
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
    update = {k: v for k, v in body.model_dump(exclude_none=True).items() if k != "password"}
    if body.password:
        update["password_hash"] = hash_password(body.password)
    update["updated_at"] = _now_iso()
    await db.users.update_one({"id": user_id}, {"$set": update})
    new = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    await _audit(user, "update", "user", user_id, prev={"role": existing.get("role"), "active": existing.get("active_status")}, new={k: v for k, v in update.items() if k != "password_hash"})
    return new


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
async def create_doctor(body: DoctorCreate, user=Depends(require_roles("Admin", "Manager"))):
    doc = Doctor(**body.model_dump()).model_dump()
    if user["role"] == "Manager" and not doc.get("team_id"):
        doc["team_id"] = user.get("team_id")
    await db.doctors.insert_one(doc)
    await _audit(user, "create", "doctor", doc["id"], new={"doctor_name": doc["doctor_name"]})
    _strip_id(doc)
    return await _enrich_doctor(doc)


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
    tasks = await db.tasks.find({"doctor_id": doctor_id}, {"_id": 0}).sort("due_date", 1).to_list(200)
    return tasks


@api.get("/doctors/{doctor_id}/prepare")
async def prepare_visit(doctor_id: str, user=Depends(get_current_user)):
    doc = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doc or not await _can_access_doctor(user, doc):
        raise HTTPException(status_code=404, detail="Doctor not found")
    enriched = await _enrich_doctor(doc)
    visits = await db.visits.find({"doctor_id": doctor_id}, {"_id": 0}).sort("visit_date", -1).to_list(3)
    open_tasks = await db.tasks.find(
        {"doctor_id": doctor_id, "status": {"$in": ["Open", "Overdue"]}}, {"_id": 0}
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
        "free_text_note": body.free_text_note,
        "confirmed_topics": body.confirmed_topics,
        "confirmed_barriers": body.confirmed_barriers,
        "sentiment": body.sentiment,
        "opportunity_state": body.opportunity_state,
        "next_step": body.next_step,
        "ai_extraction": body.ai_extraction.model_dump() if body.ai_extraction else None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.visits.insert_one(visit)
    await _audit(user, "create", "visit", visit["id"], new={"doctor_id": body.doctor_id, "sentiment": body.sentiment})

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
    # access
    if user["role"] == "TM" and t.get("tm_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "Manager" and t.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    update = body.model_dump(exclude_none=True)
    if update.get("status") == "Completed":
        update["completed_at"] = _now_iso()
    update["updated_at"] = _now_iso()
    await db.tasks.update_one({"id": task_id}, {"$set": update})
    await _audit(user, "update", "task", task_id, prev=t, new=update)
    new = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    return new


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


@api.get("/taxonomy")
async def taxonomy(user=Depends(get_current_user)):
    return {
        "topics": TOPICS_DEFAULT,
        "barriers": BARRIERS_DEFAULT,
        "sentiments": ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"],
        "opportunity_states": ["Blocked", "Stuck", "Advancing", "Unknown"],
        "visit_types": ["In-person visit", "Phone call", "Online meeting", "Event conversation", "Training/session", "Other"],
        "segments": ["Occasional", "Active", "Engaged", "Expert"],
        "cadence": DEFAULT_CADENCE,
    }



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
        perf["flags"] = _classify_flags(perf)
        perf["insights"] = _classify_insights(perf)
        rows.append(perf)

    rows.sort(key=lambda r: (-len(r["flags"]), -r["overdue_count"], -r["high_priority_unvisited"]))
    return {"rows": rows}


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
        "notes_from_tm": "",
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



# ====================================================
# AUDIT
# ====================================================
@api.get("/audit")
async def audit_logs(limit: int = 100, user=Depends(require_roles("Admin"))):
    logs = await db.audit_logs.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return logs


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
    logger.info("Field Intelligence Platform started.")


@app.on_event("shutdown")
async def on_shutdown():
    mongo_client.close()
