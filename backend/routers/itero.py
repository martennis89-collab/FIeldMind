"""itero routes — extracted from server.py during Phase C0 refactor.

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
    _week_bounds,
    _classify_flags,
    _classify_insights,
    _coaching_for,
    # ai
    ai_analyze_note,
    ai_extract_task,
    # seed
    seed_demo,
    seed_owner,
)
from models import *  # noqa: F401,F403 — all models are exported under their original names


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
    # Track total event counts per doctor across all sources so the UI/counts
    # can show "N completions across M doctors" (events, not just unique rows).
    demos: dict = {}

    def _bump(did, bucket):
        d = demos.setdefault(did, {})
        d[f"{bucket}_events"] = d.get(f"{bucket}_events", 0) + 1

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
        # Count every event flag on the visit
        if ia.get("demo_discussed") or ca.get("demo_discussed"):
            _bump(v["doctor_id"], "discussed")
        if ia.get("demo_booked") or ca.get("demo_booked") or bd:
            _bump(v["doctor_id"], "booked")
        if ia.get("demo_completed") or ca.get("demo_completed") or cd:
            _bump(v["doctor_id"], "completed")
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
        # Every non-cancelled demo meeting is a booking event
        if mt.get("status") != "Cancelled":
            _bump(mt["doctor_id"], "booked")
        # Completed (visit logged from it) → counts as completed_date if more recent than visit-derived one.
        if mt.get("status") == "Completed":
            # If the meeting has an attached visit, the visit loop already counted it.
            if not mt.get("visit_id"):
                _bump(mt["doctor_id"], "completed")
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
            "discussed_events": d.get("discussed_events", 0),
            "booked_events": d.get("booked_events", 0),
            "completed_events": d.get("completed_events", 0),
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
        "counts": {
            "booked": len(booked),
            "completed": len(completed),
            "lost": len(lost),
            # Event-level totals across the bucket — match the weekly report semantics
            # (a doctor with 2 demos in the window contributes 2 to *_events).
            "booked_events": sum(r.get("booked_events", 0) for r in booked),
            "completed_events": sum(r.get("completed_events", 0) for r in completed),
            "lost_events": sum(r.get("completed_events", 0) or r.get("booked_events", 0) for r in lost),
        },
    }

@api.get("/itero/demo-breakdown")
async def itero_demo_breakdown(scope: str = "week", user=Depends(get_current_user)):
    """Event-level breakdown of iTero demos.
    scope=week → events whose date falls in the current ISO week (reset every Monday).
    scope=all  → every event ever logged.

    A demo "event" is counted from two sources:
      • meetings with is_demo=True  (the Book-a-Demo flow) — date = scheduled_at
      • visit.itero_actions / commercial_actions flags (legacy) — date = visit_date

    Scoping:
      • TM      → only the TM's own doctors
      • Manager → all doctors in their team
      • Admin/Owner → everyone
    """
    if scope not in ("week", "all"):
        raise HTTPException(status_code=400, detail="scope must be 'week' or 'all'")

    # Build owner scope filters
    visit_filter: dict = {}
    meeting_filter: dict = {"is_demo": True}
    doctor_filter: dict = {}
    if user["role"] == "TM":
        visit_filter["tm_user_id"] = user["id"]
        meeting_filter["tm_user_id"] = user["id"]
        doctor_filter["assigned_tm_id"] = user["id"]
    elif user["role"] == "Manager":
        visit_filter["team_id"] = user.get("team_id")
        meeting_filter["team_id"] = user.get("team_id")
        doctor_filter["team_id"] = user.get("team_id")
    # Admin/Owner — no extra filter

    # Window
    week_start_iso = week_end_iso = None
    if scope == "week":
        monday, sunday = _week_bounds()
        week_start_iso = monday.isoformat()
        week_end_iso = sunday.isoformat()

    # Fetch the data we need
    visits = await db.visits.find(visit_filter, {"_id": 0}).to_list(10000)
    meetings = await db.meetings.find(meeting_filter, {"_id": 0}).to_list(10000)

    # Doctor lookup for naming
    doc_ids = {v.get("doctor_id") for v in visits if v.get("doctor_id")} | \
              {m.get("doctor_id") for m in meetings if m.get("doctor_id")}
    doctor_lookup: dict = {}
    if doc_ids:
        doctor_lookup = {
            d["id"]: d
            for d in await db.doctors.find({"id": {"$in": list(doc_ids)}}, {"_id": 0}).to_list(10000)
        }

    def _in_window(iso_str: Optional[str]) -> bool:
        if scope == "all":
            return True
        if not iso_str:
            return False
        return week_start_iso <= iso_str <= (week_end_iso + "T23:59:59")

    def _doc_info(did: str) -> dict:
        d = doctor_lookup.get(did) or {}
        return {
            "doctor_id": did,
            "doctor_name": d.get("doctor_name") or "—",
            "clinic_name": d.get("clinic_name"),
            "city": d.get("city"),
            "segment": d.get("segment"),
            "itero_stage": d.get("itero_stage"),
        }

    discussed: list = []
    booked: list = []
    completed: list = []

    # 1) Visit-derived events (legacy flags)
    #    Any visit whose itero_actions / commercial_actions has the flag set.
    #    For demo_booked / demo_completed we prefer the explicit *_date on the action
    #    if present; otherwise fall back to visit_date.
    for v in visits:
        ia = v.get("itero_actions") or {}
        ca = v.get("commercial_actions") or {}
        vd = v.get("visit_date") or ""
        did = v.get("doctor_id")

        # demo_discussed — use visit_date
        if (ia.get("demo_discussed") or ca.get("demo_discussed")) and _in_window(vd):
            discussed.append({
                **_doc_info(did),
                "event_date": vd,
                "source": "visit",
                "visit_id": v.get("id"),
            })

        # demo_booked — prefer ca.demo_booked_date (YYYY-MM-DD) or ia.demo_booked_date else visit_date
        if ia.get("demo_booked") or ca.get("demo_booked"):
            booked_date = ca.get("demo_booked_date") or ia.get("demo_booked_date") or vd
            # Skip visit-based booked events that were also captured as a meeting
            # (the meetings loop below already covers those). Dedup later by (doctor_id, ~date).
            if _in_window(booked_date):
                booked.append({
                    **_doc_info(did),
                    "event_date": booked_date,
                    "source": "visit",
                    "visit_id": v.get("id"),
                })

        # demo_completed — prefer ia.demo_completed_date or ca.demo_completed_date else visit_date
        if ia.get("demo_completed") or ca.get("demo_completed"):
            completed_date = ia.get("demo_completed_date") or ca.get("demo_completed_date") or vd
            if _in_window(completed_date):
                completed.append({
                    **_doc_info(did),
                    "event_date": completed_date,
                    "source": "visit",
                    "visit_id": v.get("id"),
                    "interest_level": ia.get("scanner_interest_level"),
                })

    # 2) Meeting-derived events (Book-a-Demo flow is the source of truth going forward)
    for m in meetings:
        did = m.get("doctor_id")
        sched = m.get("scheduled_at") or ""
        created = m.get("created_at") or sched
        # A booked demo event's date = when it was booked (created_at), so the week tab
        # reflects "demos you booked *this* week" — matching the weekly report semantics.
        if _in_window(created):
            booked.append({
                **_doc_info(did),
                "event_date": created,
                "scheduled_at": sched,
                "source": "meeting",
                "meeting_id": m.get("id"),
                "status": m.get("status"),
            })
        if m.get("status") == "Completed":
            completed_at = m.get("updated_at") or sched
            if _in_window(completed_at):
                completed.append({
                    **_doc_info(did),
                    "event_date": completed_at,
                    "scheduled_at": sched,
                    "source": "meeting",
                    "meeting_id": m.get("id"),
                })

    # Dedup booked/completed: when a visit was generated from a meeting (meeting_id present),
    # we'd double-count. The visit loop intentionally keeps them — we de-dup here by removing
    # visit rows whose visit_id is referenced as a meeting's visit_id.
    linked_visit_ids = {m.get("visit_id") for m in meetings if m.get("visit_id")}
    def _dedup(rows):
        return [r for r in rows if not (r.get("source") == "visit" and r.get("visit_id") in linked_visit_ids)]

    booked = _dedup(booked)
    completed = _dedup(completed)

    # Sort newest first
    discussed.sort(key=lambda r: r.get("event_date") or "", reverse=True)
    booked.sort(key=lambda r: r.get("event_date") or "", reverse=True)
    completed.sort(key=lambda r: r.get("event_date") or "", reverse=True)

    return {
        "scope": scope,
        "week_start": week_start_iso,
        "week_end": week_end_iso,
        "counts": {
            "discussed": len(discussed),
            "booked": len(booked),
            "completed": len(completed),
            "unique_doctors_completed": len({r["doctor_id"] for r in completed}),
        },
        "discussed": discussed,
        "booked": booked,
        "completed": completed,
    }
