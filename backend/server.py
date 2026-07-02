"""Field Intelligence Platform — main FastAPI server.

All routes are prefixed with /api.
"""
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Query, UploadFile, File, Form
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta, date
import uuid
from typing import List, Optional, Literal
from pydantic import BaseModel

from auth import (
    hash_password,
    verify_password,
    create_token,
    get_current_user,
    require_roles,
    assert_not_locked_out,
    record_failed_login,
    clear_login_attempts,
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
    # Phase B
    TrackSignal,
    TrackSignalCreate,
    ClinicalPattern,
    ClinicalPatternCreate,
    ITERO_SIGNAL_TYPES,
    INVISALIGN_SIGNAL_TYPES,
)
from ai import analyze_note as ai_analyze_note
from ai import extract_task_from_text as ai_extract_task
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


async def _audit(
    user,
    action_type,
    entity_type,
    entity_id=None,
    prev=None,
    new=None,
    ip=None,
    *,
    event_type=None,
    track_type=None,
    idempotency_key=None,
):
    """Append an entry to the Activity Event Ledger (collection: audit_logs).

    `action_type` is the legacy generic verb (create/update/delete/...).
    `event_type` is the spec §3.12 named event (e.g. promise_completed).
    `idempotency_key`, when provided, prevents duplicate ledger rows for the same
    logical action (e.g. promise_overdue should be recorded once per promise).
    """
    if idempotency_key:
        existing = await db.audit_logs.find_one(
            {"idempotency_key": idempotency_key}, {"_id": 0, "id": 1}
        )
        if existing:
            return existing["id"]
    doc = {
        "id": __import__("uuid").uuid4().hex,
        "user_id": user["id"] if user else None,
        "user_email": user["email"] if user else None,
        "action_type": action_type,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "track_type": track_type,
        "timestamp": _now_iso(),
        "previous_value": prev,
        "new_value": new,
        "ip": ip,
        "idempotency_key": idempotency_key,
        "company_id": (user or {}).get("company_id") if user else None,
        "team_id": (user or {}).get("team_id") if user else None,
    }
    await db.audit_logs.insert_one(doc)
    return doc["id"]


# ============================================================
# PHASE C — Multi-tenant company + RBAC scoping helpers.
# Moved to backend/_deps.py during the P1 refactor. Imported here so every
# `from server import ...` chain keeps working unchanged.
# ============================================================
from _deps import (  # noqa: E402,F401 — re-exported for routers
    ENFORCE_COMPANY_ISOLATION,
    _company_id_for,
    _company_query_for,
    _apply_company_scope,
    _is_manager_role,
    _same_company,
    _assert_same_company,
    _stamp_company,
    _doctor_query_for,
    _can_access_doctor,
    _managed_tm_ids_for,
)


async def _ensure_default_company_and_backfill() -> dict:
    """Idempotent Phase C migration.

    1. Ensure the default company exists (`slug=default`).
    2. Stamp `company_id=<default>` on every existing row in every relevant collection
       that does not already have one.
    Safe to run on every boot.
    """
    from models import DEFAULT_COMPANY  # imported here to avoid import-time cycles

    existing = await db.companies.find_one({"slug": "default"}, {"_id": 0})
    if existing:
        default_id = existing["id"]
        # Make sure mandatory fields are present even on older default rows.
        patch = {k: v for k, v in DEFAULT_COMPANY.items() if k not in existing}
        if patch:
            patch["updated_at"] = _now_iso()
            await db.companies.update_one({"id": default_id}, {"$set": patch})
    else:
        import uuid as _uuid_mod
        default_id = _uuid_mod.uuid4().hex
        doc = {"id": default_id, **DEFAULT_COMPANY,
               "created_at": _now_iso(), "updated_at": _now_iso()}
        await db.companies.insert_one(doc)

    collections = [
        "users", "teams", "doctors", "visits", "meetings", "tasks", "events",
        "track_signals", "clinical_patterns", "audit_logs", "expenses", "reports",
        "taxonomy_terms", "itero_stage_history", "doctor_imports",
    ]
    counts: dict[str, int] = {}
    for c in collections:
        coll = db[c]
        # Only stamp rows that don't have a company_id set yet.
        r = await coll.update_many(
            {"$or": [{"company_id": {"$exists": False}}, {"company_id": None}]},
            {"$set": {"company_id": default_id}},
        )
        if r.modified_count:
            counts[c] = r.modified_count

    # Indexes (sparse-friendly) — keep them lightweight.
    await db.companies.create_index("id", unique=True)
    await db.companies.create_index("slug", unique=True)
    for c in ["users", "doctors", "visits", "meetings", "tasks", "events",
              "track_signals", "clinical_patterns", "audit_logs", "expenses",
              "reports", "teams"]:
        try:
            await db[c].create_index("company_id")
        except Exception:
            pass

    return {"default_company_id": default_id, "backfilled": counts,
            "enforce_isolation": ENFORCE_COMPANY_ISOLATION}


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








# ====================================================
# SEED (gated — only available when ENABLE_DEMO_SEED=true, i.e. preview/dev)
# ====================================================




# ====================================================
# USERS (admin)
# ====================================================








# ====================================================
# TEAMS
# ====================================================




# ====================================================
# DOCTORS
# ====================================================




# ====================================================
# DOCTOR IMPORT (xlsx / csv)
# ====================================================






















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




def _visit_track_type(body) -> str:
    """Translate the legacy uppercase track_type to the spec's titlecase value."""
    raw = (getattr(body, "track_type", None) or "BOTH").upper()
    return {"ITERO": "iTero", "INVISALIGN": "Invisalign", "BOTH": "Both", "GENERAL": "General"}.get(raw, "General")


# ============================================================
# PHASE B — Track Signal materialization
# Mirror legacy embedded itero_actions/commercial_actions/invisalign_actions
# into the new first-class `track_signals` collection so analytics can join on it.
# Visits stay backward-compatible — the embedded fields are still written.
# ============================================================

# Map a legacy boolean field on itero_actions to the spec's signal_type token.
ITERO_FIELD_TO_SIGNAL = {
    "demo_discussed": "demo_discussed",
    "demo_booked": "demo_booked",
    "demo_completed": "demo_completed",
    "boost_discussed": "boost_discussed",
    "trade_in_discussed": "trade_in_discussed",
    "trade_in_interest": "trade_in_interest",
    "scanner_concern": "scanner_concern",
    "itero_value_discussed": "itero_value_discussed",
    "face_scan_discussed": "face_scan_discussed",
}
# commercial_actions also carries demo/proposal flags (legacy)
COMMERCIAL_FIELD_TO_ITERO_SIGNAL = {
    "demo_discussed": "demo_discussed",
    "demo_booked": "demo_booked",
    "demo_completed": "demo_completed",
    "proposal_sent": "proposal_sent",
    "proposal_follow_up_done": "proposal_followed_up",
}
INVISALIGN_FIELD_TO_SIGNAL = {
    "growth_program_explained": "growth_program_explained",
    "growth_program_not_understood": "growth_program_not_understood",
    "certification_interest": "certification_interest",
    "tps_discussed": "tps_discussed",
    "p2p_suggested": "p2p_suggested",
    "staff_training_needed": "staff_training_needed",
    "clinical_confidence_barrier": "clinical_confidence_barrier",
    "business_confidence_barrier": "business_confidence_barrier",
    "patient_affordability_concern": "patient_affordability_concern",
    "case_selection_concern": "case_selection_concern",
    "clincheck_understanding": "clincheck_understanding",
    "smileview_smilevideo_discussed": "smileview_smilevideo_discussed",
    "teen_confidence_cover_discussed": "teen_confidence_cover_discussed",
    "docloc_benefits_discussed": "docloc_benefits_discussed",
    "invited_to_event": "invited_to_event",
    "marketing_support_discussed": "marketing_support_discussed",
    "lead_generation_concern": "lead_generation_concern",
    "time_constraint": "time_constraint",
    "competition_braces": "competition_braces",
    "competition_other_aligners": "competition_other_aligners",
    "extraction_case_concern": "extraction_case_concern",
    "retained_teeth_concern": "retained_teeth_concern",
    "maob_discussed": "maob_discussed",
    "maob_interest": "maob_interest",
    "ipe_discussed": "ipe_discussed",
    "ipe_interest": "ipe_interest",
}

# Map signal_type → named event_type for ledger
SIGNAL_TO_EVENT = {
    "demo_discussed": "itero_demo_discussed",
    "demo_booked": "itero_demo_booked",
    "demo_completed": "itero_demo_completed",
    "proposal_sent": "itero_proposal_sent",
    "proposal_followed_up": "itero_proposal_followed_up",
    "boost_discussed": "itero_boost_discussed",
    "trade_in_discussed": "itero_trade_in_discussed",
    "growth_program_explained": "invisalign_growth_program_explained",
    "certification_interest": "invisalign_certification_interest_logged",
    "tps_discussed": "invisalign_tps_discussed",
    "p2p_suggested": "invisalign_p2p_suggested",
    "staff_training_needed": "invisalign_staff_training_needed",
    "maob_discussed": "invisalign_maob_discussed",
    "ipe_discussed": "invisalign_ipe_discussed",
    "clinical_confidence_barrier": "invisalign_clinical_confidence_barrier_logged",
    "business_confidence_barrier": "invisalign_business_confidence_barrier_logged",
    "patient_affordability_concern": "invisalign_patient_affordability_concern_logged",
    "case_selection_concern": "invisalign_case_selection_concern_logged",
}


async def _insert_track_signal(
    *, doctor, visit_id, track_type, signal_type, signal_value, signal_status,
    signal_date, source, user, fire_event=True,
):
    """Insert a TrackSignal row + (optionally) an event_ledger entry.
    Uses idempotency_key = (visit_id, track_type, signal_type) so re-saving a
    visit twice doesn't produce duplicate signals/events. For manual entries
    (visit_id=None) the key is randomised so independent manual signals are
    never blocked by an earlier (or soft-deleted) row."""
    import uuid as _uuid_mod
    if visit_id:
        idem = f"ts:{visit_id}:{track_type}:{signal_type}"
        existing = await db.track_signals.find_one(
            {"idempotency_key": idem, "deleted_at": None}, {"_id": 0, "id": 1}
        )
        if existing:
            return existing["id"]
    else:
        idem = f"ts:manual:{doctor['id']}:{track_type}:{signal_type}:{_uuid_mod.uuid4().hex}"
    row = {
        "id": _uuid_mod.uuid4().hex,
        "doctor_id": doctor["id"],
        "tm_user_id": user["id"],
        "team_id": user.get("team_id") or doctor.get("team_id"),
        "meeting_id": visit_id,
        "track_type": track_type,
        "signal_type": signal_type,
        "signal_value": signal_value,
        "signal_status": signal_status,
        "signal_date": signal_date or datetime.now(timezone.utc).date().isoformat(),
        "source": source,
        "company_id": _company_id_for(user) or doctor.get("company_id"),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "deleted_at": None,
        "idempotency_key": idem,
    }
    await db.track_signals.insert_one(row)
    if fire_event:
        await _audit(
            user, "create", "track_signal", row["id"],
            new={"track_type": track_type, "signal_type": signal_type},
            event_type=SIGNAL_TO_EVENT.get(signal_type, "track_signal_created"),
            track_type=track_type,
            idempotency_key=f"ev:{idem}",
        )
    return row["id"]


async def _materialize_track_signals_from_visit(*, visit, doctor, body, source, user):
    """Fan out a saved visit into one row per confirmed Track Signal."""
    visit_id = visit["id"]
    visit_date = (visit.get("visit_date") or _now_iso())[:10]

    ia = body.itero_actions
    if ia:
        ia_dict = ia.model_dump()
        for field, signal_type in ITERO_FIELD_TO_SIGNAL.items():
            if ia_dict.get(field):
                await _insert_track_signal(
                    doctor=doctor, visit_id=visit_id, track_type="iTero",
                    signal_type=signal_type, signal_value=None, signal_status=None,
                    signal_date=visit_date, source=source, user=user,
                )
        if ia_dict.get("scanner_interest_level"):
            await _insert_track_signal(
                doctor=doctor, visit_id=visit_id, track_type="iTero",
                signal_type="scanner_interest_level",
                signal_value=str(ia_dict["scanner_interest_level"]),
                signal_status=None,
                signal_date=visit_date, source=source, user=user,
            )

    ca = body.commercial_actions
    if ca:
        ca_dict = ca.model_dump()
        for field, signal_type in COMMERCIAL_FIELD_TO_ITERO_SIGNAL.items():
            if ca_dict.get(field):
                await _insert_track_signal(
                    doctor=doctor, visit_id=visit_id, track_type="iTero",
                    signal_type=signal_type, signal_value=None, signal_status=None,
                    signal_date=visit_date, source=source, user=user,
                )

    inv = body.invisalign_actions
    if inv:
        inv_dict = inv.model_dump()
        for field, signal_type in INVISALIGN_FIELD_TO_SIGNAL.items():
            if inv_dict.get(field):
                await _insert_track_signal(
                    doctor=doctor, visit_id=visit_id, track_type="Invisalign",
                    signal_type=signal_type, signal_value=None, signal_status=None,
                    signal_date=visit_date, source=source, user=user,
                )


# ---- Backfill helper (idempotent — uses idempotency_key) ----
async def _backfill_track_signals_from_visits() -> int:
    """For every existing visit, generate the track_signals rows that the new
    write path would emit. Idempotent — re-running is safe."""
    cursor = db.visits.find(
        {"deleted_at": {"$in": [None, False]}},
        {"_id": 0},
    )
    created = 0
    async for v in cursor:
        doctor = await db.doctors.find_one({"id": v["doctor_id"]}, {"_id": 0})
        if not doctor:
            continue
        user_stub = {"id": v["tm_user_id"], "email": "", "team_id": v.get("team_id")}
        # We pass a tiny shim with model_dump() returning the embedded dict
        class _Shim:
            def __init__(self, d): self._d = d or {}
            def model_dump(self): return self._d
        ia = _Shim(v.get("itero_actions"))
        ca = _Shim(v.get("commercial_actions"))
        inv = _Shim(v.get("invisalign_actions"))

        before = await db.track_signals.count_documents({"meeting_id": v["id"]})
        # Re-use the materialize logic with shim body
        class _Body:
            itero_actions = ia
            commercial_actions = ca
            invisalign_actions = inv
        await _materialize_track_signals_from_visit(
            visit={"id": v["id"], "visit_date": v.get("visit_date")},
            doctor=doctor, body=_Body(), source="Manual", user=user_stub,
        )
        after = await db.track_signals.count_documents({"meeting_id": v["id"]})
        created += max(0, after - before)
    return created


# ============================================================
# PHASE B — Track Signals CRUD
# ============================================================






# ============================================================
# PHASE B — Clinical Patterns CRUD
# ============================================================










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
        "company_id": _company_id_for(user),
    })










# ====================================================
# MEETINGS  (lightweight scheduler; not a calendar integration)
# ====================================================
















# ============================================================
# Quick-capture: voice / text → AI suggested task
# ============================================================


# ====================================================
# EVENTS  (generic agenda items, no doctor link)
# ====================================================










# ====================================================
# TASKS
# ====================================================


def _add_business_days(start_date: date, days: int) -> date:
    """Add N business days (skip Sat/Sun) to a date. Spec §3.6 default for promises."""
    if days <= 0:
        return start_date
    cur = start_date
    added = 0
    while added < days:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:  # Mon=0..Fri=4
            added += 1
    return cur








# ====================================================
# DASHBOARDS
# ====================================================




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




# ----- Admin: editable taxonomy CRUD -----









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


# ====================================================
# INTERVENTION (manager)
# ====================================================


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
    enriched = list(await asyncio.gather(*[_enrich_doctor(d) for d in my_docs])) if my_docs else []
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

    # Commercial momentum — visits-based (legacy manual flags) + meeting-based (new unified demo flow)
    demos_discussed = sum(1 for v in visits if (v.get("commercial_actions") or {}).get("demo_discussed"))
    proposals_sent = sum(1 for v in visits if (v.get("commercial_actions") or {}).get("proposal_sent"))
    proposals_followed = sum(1 for v in visits if (v.get("commercial_actions") or {}).get("proposal_follow_up_done"))

    # Pull this-week's iTero demo meetings (source of truth for the new Book-a-Demo flow)
    demo_meetings_booked = await db.meetings.find({
        "tm_user_id": tm_id,
        "is_demo": True,
        "created_at": {"$gte": week_start_iso, "$lte": week_end_iso + "T23:59:59"},
    }, {"_id": 0}).to_list(2000)
    demo_meetings_completed = await db.meetings.find({
        "tm_user_id": tm_id,
        "is_demo": True,
        "status": "Completed",
        "updated_at": {"$gte": week_start_iso, "$lte": week_end_iso + "T23:59:59"},
    }, {"_id": 0}).to_list(2000)

    # Legacy fallback: count demos flagged directly on visits that don't have a linked meeting
    legacy_demos_booked = sum(
        1 for v in visits
        if not v.get("meeting_id") and (v.get("commercial_actions") or {}).get("demo_booked")
    )
    legacy_demos_completed = sum(
        1 for v in visits
        if not v.get("meeting_id") and (
            (v.get("commercial_actions") or {}).get("demo_completed")
            or (v.get("itero_actions") or {}).get("demo_completed")
        )
    )

    demos_booked = len(demo_meetings_booked) + legacy_demos_booked
    demos_completed = len(demo_meetings_completed) + legacy_demos_completed

    # Build a flat demo list (used by UI / PDF / CSV) showing each booked or completed demo this week
    demo_doctor_ids = {m["doctor_id"] for m in (demo_meetings_booked + demo_meetings_completed)}
    demo_doctor_lookup = {}
    if demo_doctor_ids:
        demo_doctor_lookup = {
            d["id"]: d for d in await db.doctors.find(
                {"id": {"$in": list(demo_doctor_ids)}}, {"_id": 0}
            ).to_list(1000)
        }

    def _doctor_name_for(mt):
        return mt.get("doctor_name") or (demo_doctor_lookup.get(mt.get("doctor_id"), {}) or {}).get("doctor_name") or "—"

    demos_booked_list = sorted(
        [
            {
                "meeting_id": m["id"],
                "doctor_id": m["doctor_id"],
                "doctor_name": _doctor_name_for(m),
                "clinic_name": m.get("clinic_name"),
                "scheduled_at": m.get("scheduled_at"),
                "is_completed": m.get("status") == "Completed",
                "status": m.get("status"),
            }
            for m in demo_meetings_booked
        ],
        key=lambda x: x.get("scheduled_at") or "",
    )
    demos_completed_list = sorted(
        [
            {
                "meeting_id": m["id"],
                "doctor_id": m["doctor_id"],
                "doctor_name": _doctor_name_for(m),
                "clinic_name": m.get("clinic_name"),
                "scheduled_at": m.get("scheduled_at"),
                "completed_at": m.get("updated_at"),
            }
            for m in demo_meetings_completed
        ],
        key=lambda x: x.get("completed_at") or "",
    )

    if demos_completed:
        insights.append(f"✓ {demos_completed} iTero demo{'s' if demos_completed != 1 else ''} completed this week.")
    elif demos_booked:
        insights.append(f"✓ {demos_booked} iTero demo{'s' if demos_booked != 1 else ''} booked this week.")
    if proposals_sent and not proposals_followed:
        insights.append(f"⚠️ {proposals_sent} proposal{'s' if proposals_sent != 1 else ''} sent — schedule follow-ups.")

    # Per-doctor breakdown for the week — one row per doctor visited
    # Include doctors who only have demo activity (but no visit) this week too
    combined_doctor_ids = set(doctor_ids) | demo_doctor_ids
    doctor_lookup = {d["id"]: d for d in (await db.doctors.find({"id": {"$in": list(combined_doctor_ids)}}, {"_id": 0}).to_list(2000))}
    # Tasks created this week, grouped by doctor
    tasks_by_doctor: dict = {}
    for tk in tasks_created:
        tasks_by_doctor.setdefault(tk.get("doctor_id"), []).append(tk)
    # Aggregate visits per doctor
    visits_by_doctor: dict = {}
    for v in visits:
        visits_by_doctor.setdefault(v["doctor_id"], []).append(v)
    # Aggregate demo meetings per doctor
    demos_booked_by_doctor: dict = {}
    demos_completed_by_doctor: dict = {}
    for m in demo_meetings_booked:
        demos_booked_by_doctor.setdefault(m["doctor_id"], []).append(m)
    for m in demo_meetings_completed:
        demos_completed_by_doctor.setdefault(m["doctor_id"], []).append(m)
    breakdown = []
    for did in combined_doctor_ids:
        vs = visits_by_doctor.get(did, [])
        d = doctor_lookup.get(did) or {}
        # Sort visits chronologically
        vs.sort(key=lambda x: x.get("visit_date", ""))
        last_visit = vs[-1] if vs else {}
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
        # Pull the visit note. We keep BOTH a short excerpt (for compact UI
        # previews on dashboard/draft cards) AND the full untruncated text
        # (used by the PDF/CSV exports so the manager sees the whole story).
        note_full = (last_visit.get("free_text_note") or "").strip() if last_visit else ""
        note_excerpt = note_full
        if len(note_excerpt) > 220:
            note_excerpt = note_excerpt[:217] + "…"
        d_booked = demos_booked_by_doctor.get(did, [])
        d_completed = demos_completed_by_doctor.get(did, [])
        breakdown.append({
            "doctor_id": did,
            "doctor_name": d.get("doctor_name") or "—",
            "clinic_name": d.get("clinic_name"),
            "city": d.get("city"),
            "segment": d.get("segment"),
            "visits_count": len(vs),
            "last_visit_date": (last_visit.get("visit_date", "") or "")[:10] if last_visit else "",
            "topics": topics_set[:5],
            "barriers": barriers_set[:5],
            "sentiment": latest_sentiment,
            "promises_count": len(promise_titles),
            "promises": promise_titles[:5],
            "note_excerpt": note_excerpt,
            "note_full": note_full,
            "demos_booked_count": len(d_booked),
            "demos_completed_count": len(d_completed),
            "demo_dates": sorted([m.get("scheduled_at", "")[:10] for m in d_booked if m.get("scheduled_at")]),
        })
    # Sort by demo activity + visit count desc, then last visit desc
    breakdown.sort(key=lambda x: (
        x["demos_completed_count"] + x["demos_booked_count"] + x["visits_count"],
        x["last_visit_date"] or "",
    ), reverse=True)

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
        "demos_booked_list": demos_booked_list,
        "demos_completed_list": demos_completed_list,
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



















# ====================================================
# AUDIT
# ====================================================




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






















# ====================================================
# Health
# ====================================================


# Include router

# ====================================================
# PHASE C0 — Router modules
# ====================================================
# Each module imports `api` and the shared helpers from this file and re-registers
# its handlers on the SAME `api` instance. They MUST be imported AFTER all helpers
# are defined above and BEFORE `app.include_router(api)`.
from routers import (
    auth,
    users,
    doctors,
    visits,
    track_signals,
    clinical_patterns,
    meetings,
    events,
    tasks,
    dashboards,
    itero,
    search,
    taxonomy,
    reports,
    audit_logs,
    expenses,
    ai_extract,
    root,
    companies,
    metrics,
    insights,
    interventions,
    benchmark,
)
_ = (auth, users, doctors, visits, track_signals, clinical_patterns, meetings, events, tasks, dashboards, itero, search, taxonomy, reports, audit_logs, expenses, ai_extract, root, companies, metrics, insights, interventions, benchmark)  # silence unused-import linters

app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    # Expose custom headers so browser JS can read the download filename from
    # streamed exports (receipts.zip, report PDFs, etc.).
    expose_headers=["Content-Disposition"],
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
    await db.audit_logs.create_index([("event_type", 1), ("timestamp", -1)])
    await db.audit_logs.create_index(
        [("idempotency_key", 1)], unique=False, sparse=True
    )
    # P2 brute-force protection — TTL purges old rows so the counter resets cleanly.
    await db.login_attempts.create_index("identifier")
    await db.login_attempts.create_index(
        "last_attempt_at",
        expireAfterSeconds=24 * 3600,  # auto-evict after a day even if never cleared
    )
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

    # PHASE C — multi-tenant Company spine
    try:
        c_report = await _ensure_default_company_and_backfill()
        logger.info(f"Phase C company: {c_report}")
    except Exception as e:
        logger.error(f"Phase C company init failed: {e}")

    # PHASE A — backfill nullable defaults for backward compatibility
    try:
        a = await db.visits.update_many(
            {"deleted_at": {"$exists": False}},
            {"$set": {"deleted_at": None, "is_draft": False}},
        )
        b = await db.meetings.update_many(
            {"deleted_at": {"$exists": False}},
            {"$set": {"deleted_at": None, "is_draft": False, "track_type": "General"}},
        )
        c = await db.tasks.update_many(
            {"category": {"$exists": False}},
            {"$set": {"category": "other", "ai_confirmed": True}},
        )
        logger.info(f"Phase A backfill: visits={a.modified_count} meetings={b.modified_count} tasks={c.modified_count}")
    except Exception as e:
        logger.error(f"Phase A backfill failed: {e}")

    # PHASE B — indexes + backfill track_signals from historical visits
    try:
        await db.track_signals.create_index([("doctor_id", 1), ("track_type", 1), ("signal_date", -1)])
        await db.track_signals.create_index("idempotency_key", unique=False, sparse=True)
        await db.track_signals.create_index([("tm_user_id", 1)])
        await db.clinical_patterns.create_index([("doctor_id", 1)])
        await db.clinical_patterns.create_index([("tm_user_id", 1)])
        # Backfill: walk every visit that hasn't been processed yet and materialize signals.
        # We use the meeting_id (=visit_id) idempotency_key set on insert.
        backfilled = await _backfill_track_signals_from_visits()
        logger.info(f"Phase B backfill: {backfilled} new track_signals materialized")
    except Exception as e:
        logger.error(f"Phase B init failed: {e}")

    logger.info("Field Intelligence Platform started.")


@app.on_event("shutdown")
async def on_shutdown():
    mongo_client.close()
