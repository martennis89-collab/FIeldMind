"""dashboards routes — extracted from server.py during Phase C0 refactor.

This module imports the shared `api` APIRouter + helpers from server.py and re-registers
its handlers on it. Behaviour is byte-for-byte identical to pre-refactor.
"""
from __future__ import annotations
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta, date
import asyncio
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
    _enrich_doctors_batch,
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
    _week_bounds,
    _classify_flags,
    _classify_insights,
    _coaching_for,
    _managed_tm_ids_for,
    _is_manager_role,
    # ai
    ai_analyze_note,
    ai_extract_task,
    # seed
    seed_demo,
    seed_owner,
)
from models import *  # noqa: F401,F403,F405 — all models are exported under their original names


# Phase L — single helper that applies role-appropriate scope to a Mongo
# query for collections that carry `team_id` + `tm_user_id` (visits, tasks,
# meetings, etc.). `sr_ids` is the precomputed Senior-TM-managed user-id
# list and must be passed by the caller (resolved once per handler).
def _apply_role_scope(q: dict, user, sr_ids: Optional[list[str]] = None) -> dict:
    role = user["role"]
    if role == "TM":
        q["tm_user_id"] = user["id"]
    elif role == "Manager":
        q["team_id"] = user.get("team_id")
    elif role == "SeniorTM":
        q["tm_user_id"] = {"$in": sr_ids or []}
    return q


def _users_scope_query(user, sr_ids: Optional[list[str]] = None) -> dict:
    """Filter for db.users.find that scopes to the caller's manager view.

    Returns ONLY the role filter — the caller must merge with company scope.
    """
    role = user["role"]
    if role == "Manager":
        return {"team_id": user.get("team_id"), "role": {"$in": ["TM", "SeniorTM"]}}
    if role == "SeniorTM":
        return {"id": {"$in": sr_ids or []}, "role": "TM"}
    return {"role": {"$in": ["TM", "SeniorTM"]}}


# Team standard: every TM should see at least this many distinct doctors per working day.
DAILY_DOCTOR_TARGET = 2


def _count_working_days(start_date: date, end_date: date) -> int:
    """Count Mon-Fri days in [start_date, end_date], inclusive."""
    days = (end_date - start_date).days + 1
    if days <= 0:
        return 0
    full_weeks, remainder = divmod(days, 7)
    count = full_weeks * 5
    for i in range(remainder):
        d = start_date + timedelta(days=full_weeks * 7 + i)
        if d.weekday() < 5:
            count += 1
    return count


@api.get("/dashboard/tm")
async def tm_dashboard(user=Depends(get_current_user)):
    if user["role"] not in ("TM", "Admin", "Manager", "SeniorTM"):
        raise HTTPException(status_code=403, detail="Forbidden")
    doc_q = await _doctor_query_for(user)
    docs = await db.doctors.find(doc_q, {"_id": 0}).to_list(500)
    enriched = await _enrich_doctors_batch(docs)
    enriched.sort(key=lambda d: d["visit_priority_score"], reverse=True)

    today = datetime.now(timezone.utc).date().isoformat()
    now_iso = _now_iso()
    monday, sunday = _week_bounds()
    week_start = monday.isoformat()
    week_end_inclusive = sunday.isoformat()

    task_q = dict(_company_query_for(user))
    if user["role"] in ("TM", "SeniorTM"):
        task_q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        task_q["team_id"] = user.get("team_id")
    overdue = await db.tasks.count_documents({**task_q, "status": {"$in": ["Open", "Overdue"]}, "due_date": {"$lt": today}})
    due_today = await db.tasks.count_documents({**task_q, "status": {"$in": ["Open", "Overdue"]}, "due_date": today})
    open_total = await db.tasks.count_documents({**task_q, "status": {"$in": ["Open", "Overdue"]}})

    visit_q = dict(_company_query_for(user))
    meeting_q = dict(_company_query_for(user))
    if user["role"] in ("TM", "SeniorTM"):
        visit_q["tm_user_id"] = user["id"]
        meeting_q["tm_user_id"] = user["id"]
    elif user["role"] == "Manager":
        visit_q["team_id"] = user.get("team_id")
        meeting_q["team_id"] = user.get("team_id")
    # Visits logged in the current ISO week (resets every Monday)
    visits_week = await db.visits.count_documents({
        **visit_q,
        "visit_date": {"$gte": week_start, "$lte": week_end_inclusive + "T23:59:59"},
    })
    # Distinct doctors visited today, vs the team's daily target.
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    doctors_visited_today = await db.visits.distinct("doctor_id", {
        **visit_q,
        "visit_date": {"$gte": today, "$lt": tomorrow},
    })
    # Meetings — open (scheduled, not yet completed) and completed this week
    open_meetings = await db.meetings.count_documents({
        **meeting_q,
        "status": "Scheduled",
        "scheduled_at": {"$gte": now_iso[:10]},  # today or later
        "deleted_at": None,
    })
    completed_meetings_week = await db.meetings.count_documents({
        **meeting_q,
        "status": "Completed",
        "updated_at": {"$gte": week_start, "$lte": week_end_inclusive + "T23:59:59"},
        "deleted_at": None,
    })

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
            "open_meetings": open_meetings,
            "completed_meetings_this_week": completed_meetings_week,
            "doctors_visited_today": len(doctors_visited_today),
            "daily_doctor_target": DAILY_DOCTOR_TARGET,
        },
        "top_priorities": priorities,
        "overdue_doctors": overdue_doctors,
    }

@api.get("/dashboard/manager")
async def manager_dashboard(user=Depends(require_roles("Manager", "SeniorTM", "Admin", "Owner"))):
    _sr_ids = await _managed_tm_ids_for(user) if user["role"] == "SeniorTM" else None
    team_q = dict(_company_query_for(user)) if user["role"] in ("Admin","Owner") else _apply_role_scope(dict(_company_query_for(user)), user, sr_ids=_sr_ids)
    # NOTE: doctors are scoped by `assigned_tm_id`/`team_id`, not `tm_user_id` like
    # visits/tasks/meetings — team_q (built by _apply_role_scope) doesn't apply here.
    docs_q = await _doctor_query_for(user)
    docs = await db.doctors.find(docs_q, {"_id": 0}).to_list(1000)
    visits = await db.visits.find(team_q, {"_id": 0}).sort("visit_date", -1).to_list(2000)
    tasks = await db.tasks.find(team_q, {"_id": 0}).to_list(2000)
    users = await db.users.find({**({"team_id": user.get("team_id")} if user["role"] == "Manager" else {}), "role": {"$in": ["TM", "SeniorTM"]}}, {"_id": 0, "password_hash": 0}).to_list(200)

    today = datetime.now(timezone.utc).date().isoformat()
    now_iso = _now_iso()
    monday, sunday = _week_bounds()
    week_start = monday.isoformat()
    week_end_inclusive = sunday.isoformat() + "T23:59:59"
    month_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    visits_week = [v for v in visits if week_start <= v["visit_date"] <= week_end_inclusive]
    visits_month = [v for v in visits if v["visit_date"] >= month_start]

    # Meetings — open & completed-this-week counts (team-scoped)
    open_meetings = await db.meetings.count_documents({
        **team_q,
        "status": "Scheduled",
        "scheduled_at": {"$gte": now_iso[:10]},
        "deleted_at": None,
    })
    completed_meetings_week = await db.meetings.count_documents({
        **team_q,
        "status": "Completed",
        "updated_at": {"$gte": week_start, "$lte": week_end_inclusive},
        "deleted_at": None,
    })

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

    # Under-visited high-segment doctors.
    # P1 follow-up perf — enriching every doctor was 5×N sequential awaits
    # (~10s for Owner across 1000 doctors). We can pre-filter by segment
    # cheaply (already in the doctor row) before paying the per-doc enrich
    # cost — only ~5% of doctors typically match Engaged/Expert.
    high_seg_candidates = [d for d in docs if d.get("segment") in ("Engaged", "Expert")]
    enriched_candidates = await _enrich_doctors_batch(high_seg_candidates)
    under_visited = [
        d for d in enriched_candidates
        if d["cadence_status"] in ("Overdue", "Critical")
    ][:8]

    market_pulse = _market_pulse(top_barriers, top_topics, sentiment_counts)

    return {
        "stats": {
            "visits_week": len(visits_week),
            "visits_month": len(visits_month),
            "doctors": len(docs),
            "tms": len(users),
            "overdue_promises": sum(b["overdue"] for b in by_tm.values()),
            "open_meetings": open_meetings,
            "completed_meetings_this_week": completed_meetings_week,
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

@api.get("/dashboard/manager/performance")
async def manager_performance(user=Depends(require_roles("Manager", "SeniorTM", "Admin", "Owner"))):
    _sr_ids = await _managed_tm_ids_for(user) if user["role"] == "SeniorTM" else None
    team_q = dict(_company_query_for(user)) if user["role"] in ("Admin","Owner") else _apply_role_scope(dict(_company_query_for(user)), user, sr_ids=_sr_ids)
    user_q = {**({"team_id": user.get("team_id"), "role": {"$in": ["TM", "SeniorTM"]}} if user["role"] == "Manager" else {"id": {"$in": _sr_ids or []}, "role": "TM"} if user["role"] == "SeniorTM" else {"role": {"$in": ["TM", "SeniorTM"]}})}
    tms = await db.users.find(user_q, {"_id": 0, "password_hash": 0}).to_list(500)
    docs = await db.doctors.find(await _doctor_query_for(user), {"_id": 0}).to_list(2000)
    visits = await db.visits.find(team_q, {"_id": 0}).to_list(5000)
    tasks = await db.tasks.find(team_q, {"_id": 0}).to_list(5000)

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    month_start = (now - timedelta(days=30)).isoformat()
    prev_month_start = (now - timedelta(days=60)).isoformat()

    sentiment_score = {"Very Negative": 1, "Negative": 2, "Neutral": 3, "Positive": 4, "Very Positive": 5}
    # Team standard: DAILY_DOCTOR_TARGET distinct doctors per working day, over the
    # same 30-day lookback window used for visits_month.
    working_days_30 = _count_working_days(now.date() - timedelta(days=30), now.date())

    rows = []
    for tm in tms:
        my_docs = [d for d in docs if d.get("assigned_tm_id") == tm["id"]]
        my_visits = [v for v in visits if v.get("tm_user_id") == tm["id"]]
        my_visits_30 = [v for v in my_visits if v.get("visit_date", "") >= month_start]
        my_visits_prev = [v for v in my_visits if prev_month_start <= v.get("visit_date", "") < month_start]
        my_tasks = [t for t in tasks if t.get("tm_user_id") == tm["id"]]
        my_tasks_30 = [t for t in my_tasks if t.get("created_at", "") >= month_start]

        # Team standard: DAILY_DOCTOR_TARGET distinct doctors per working day.
        target_int = max(working_days_30 * DAILY_DOCTOR_TARGET, 1)

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
        enriched_my = await _enrich_doctors_batch(my_docs)
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

@api.get("/dashboard/manager/commercial")
async def manager_commercial(user=Depends(require_roles("Manager", "SeniorTM", "Admin", "Owner"))):
    _sr_ids = await _managed_tm_ids_for(user) if user["role"] == "SeniorTM" else None
    team_q = dict(_company_query_for(user)) if user["role"] in ("Admin","Owner") else _apply_role_scope(dict(_company_query_for(user)), user, sr_ids=_sr_ids)
    docs = await db.doctors.find(await _doctor_query_for(user), {"_id": 0}).to_list(2000)
    enriched = await _enrich_doctors_batch(docs)
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

@api.get("/dashboard/manager/interventions")
async def manager_interventions(stale_proposal_days: int = 7, user=Depends(require_roles("Manager", "SeniorTM", "Admin", "Owner"))):
    _sr_ids = await _managed_tm_ids_for(user) if user["role"] == "SeniorTM" else None
    team_q = dict(_company_query_for(user)) if user["role"] in ("Admin","Owner") else _apply_role_scope(dict(_company_query_for(user)), user, sr_ids=_sr_ids)
    docs = await db.doctors.find(await _doctor_query_for(user), {"_id": 0}).to_list(2000)
    enriched = await _enrich_doctors_batch(docs)
    user_q = {**({"team_id": user.get("team_id"), "role": {"$in": ["TM", "SeniorTM"]}} if user["role"] == "Manager" else {"id": {"$in": _sr_ids or []}, "role": "TM"} if user["role"] == "SeniorTM" else {"role": {"$in": ["TM", "SeniorTM"]}})}
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

@api.get("/dashboard/manager/itero")
async def manager_itero(user=Depends(require_roles("Manager", "SeniorTM", "Admin", "Owner"))):
    _sr_ids = await _managed_tm_ids_for(user) if user["role"] == "SeniorTM" else None
    team_q = dict(_company_query_for(user)) if user["role"] in ("Admin","Owner") else _apply_role_scope(dict(_company_query_for(user)), user, sr_ids=_sr_ids)
    docs = await db.doctors.find(await _doctor_query_for(user), {"_id": 0}).to_list(2000)
    enriched = await _enrich_doctors_batch(docs)

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
    user_q = {**({"team_id": user.get("team_id"), "role": {"$in": ["TM", "SeniorTM"]}} if user["role"] == "Manager" else {"id": {"$in": _sr_ids or []}, "role": "TM"} if user["role"] == "SeniorTM" else {"role": {"$in": ["TM", "SeniorTM"]}})}
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
async def manager_invisalign(user=Depends(require_roles("Manager", "SeniorTM", "Admin", "Owner"))):
    _sr_ids = await _managed_tm_ids_for(user) if user["role"] == "SeniorTM" else None
    team_q = dict(_company_query_for(user)) if user["role"] in ("Admin","Owner") else _apply_role_scope(dict(_company_query_for(user)), user, sr_ids=_sr_ids)
    docs = await db.doctors.find(await _doctor_query_for(user), {"_id": 0}).to_list(2000)
    enriched = await _enrich_doctors_batch(docs)
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
async def manager_cross_sell(user=Depends(require_roles("Manager", "SeniorTM", "Admin", "Owner"))):
    _sr_ids = await _managed_tm_ids_for(user) if user["role"] == "SeniorTM" else None
    team_q = dict(_company_query_for(user)) if user["role"] in ("Admin","Owner") else _apply_role_scope(dict(_company_query_for(user)), user, sr_ids=_sr_ids)
    docs = await db.doctors.find(await _doctor_query_for(user), {"_id": 0}).to_list(2000)
    enriched = await _enrich_doctors_batch(docs)

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
    if user["role"] not in ("TM", "SeniorTM"):
        raise HTTPException(status_code=403, detail="TM only")
    docs = await db.doctors.find({"assigned_tm_id": user["id"]}, {"_id": 0}).to_list(500)
    enriched = await _enrich_doctors_batch(docs)
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
    if user["role"] not in ("TM", "SeniorTM"):
        raise HTTPException(status_code=403, detail="TM only")
    docs = await db.doctors.find({"assigned_tm_id": user["id"]}, {"_id": 0}).to_list(500)
    enriched = await _enrich_doctors_batch(docs)
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
