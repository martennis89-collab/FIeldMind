"""reports routes — extracted from server.py during Phase C0 refactor.

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
from collections import defaultdict, deque
from threading import Lock


# ============================================================
# P2 — Simple per-user in-memory rate limiter for /reports/generate.
# The endpoint composes a PDF on the fly with N database aggregations; we cap
# at REPORT_GEN_LIMIT calls per REPORT_GEN_WINDOW_S seconds per user.
# In-memory is enough for a single-process supervisor deployment. If we go
# multi-process later, swap for a Redis or Mongo-backed counter.
# ============================================================
REPORT_GEN_LIMIT = int(os.environ.get("REPORT_GEN_LIMIT", "20"))
REPORT_GEN_WINDOW_S = int(os.environ.get("REPORT_GEN_WINDOW_S", "60"))
_report_gen_hits: dict[str, deque[float]] = defaultdict(deque)
_report_gen_lock = Lock()


def _enforce_report_rate_limit(user_id: str) -> None:
    import time
    now = time.monotonic()
    cutoff = now - REPORT_GEN_WINDOW_S
    with _report_gen_lock:
        bucket = _report_gen_hits[user_id]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= REPORT_GEN_LIMIT:
            retry_after = max(1, int(bucket[0] + REPORT_GEN_WINDOW_S - now))
            raise HTTPException(
                status_code=429,
                detail=f"Too many report generations. Try again in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)


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
from models import ReportCreate, ReportUpdate, WeeklyReport


@api.post("/reports/generate")
async def generate_report(week_start: Optional[str] = None, user=Depends(get_current_user)):
    """Generate a draft for THIS week, or for a past week within the last 2 weeks.

    `week_start` (optional) — YYYY-MM-DD of any day inside the target week. The
    server normalises to the Monday→Sunday window. Allowed range: current week,
    last week, or 2 weeks ago. Older weeks → HTTP 400.
    """
    if user["role"] not in ("TM", "SeniorTM"):
        # Admin/Manager can preview their own (no-op)
        raise HTTPException(status_code=403, detail="Only TMs generate reports")
    # P2 — lightweight per-user rate limit for the expensive PDF/CSV path.
    _enforce_report_rate_limit(user["id"])
    anchor = datetime.now(timezone.utc)
    if week_start:
        try:
            anchor = datetime.fromisoformat(week_start).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid week_start (YYYY-MM-DD)")
        # Reject anchors more than 14 days behind the current Monday.
        cur_monday, _ = _week_bounds()
        if anchor.date() > cur_monday.date() + timedelta(days=6):
            raise HTTPException(status_code=400, detail="week_start cannot be in the future")
        if (cur_monday.date() - anchor.date()).days > 14:
            raise HTTPException(status_code=400, detail="Cannot generate reports older than 2 weeks back")
    monday, sunday = _week_bounds(anchor)
    draft = await _build_report_draft(user, monday.date().isoformat(), sunday.date().isoformat())
    return draft

@api.post("/reports")
async def create_report(body: ReportCreate, user=Depends(get_current_user)):
    if user["role"] not in ("TM", "SeniorTM"):
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
    _stamp_company(doc, user)
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
async def comment_report(report_id: str, body: dict, user=Depends(require_roles("Manager", "SeniorTM", "Admin"))):
    r = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if user["role"] == "Manager" and r.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    # Phase L — Senior TM can comment ONLY on reports submitted by their direct
    # reports (a TM whose manager_user_id == self.id).
    if user["role"] == "SeniorTM":
        tm = await db.users.find_one(
            {"id": r.get("tm_user_id")},
            {"_id": 0, "manager_user_id": 1},
        )
        if not tm or tm.get("manager_user_id") != user["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty comment")
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

    # Phase L — SeniorTMs see THEIR direct reports' submissions + their OWN
    # report. They submit their own report up to their manager.
    if user["role"] == "SeniorTM":
        sub = await db.users.find(
            {"manager_user_id": user["id"], "role": "TM"},
            {"_id": 0, "id": 1},
        ).to_list(2000)
        sr_ids = [r["id"] for r in sub] + [user["id"]]
        team_q = {**_company_query_for(user), "tm_user_id": {"$in": sr_ids}}
        user_q = {"id": {"$in": sr_ids}}
        tms = await db.users.find(user_q, {"_id": 0, "password_hash": 0}).to_list(500)
    else:
        team_q = dict(_company_query_for(user)) if user["role"] in ("Admin","Owner") else {**_company_query_for(user), "team_id": user.get("team_id")}
        user_q = {**({"team_id": user.get("team_id"), "role": {"$in": ["TM", "SeniorTM"]}} if user["role"] == "Manager" else {"role": {"$in": ["TM", "SeniorTM"]}})}
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
    if user["role"] == "SeniorTM":
        # SeniorTM can read their own report OR a direct-report's report.
        if r.get("tm_user_id") != user["id"]:
            tm = await db.users.find_one({"id": r.get("tm_user_id")}, {"_id": 0, "manager_user_id": 1})
            if not tm or tm.get("manager_user_id") != user["id"]:
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
    if user["role"] == "SeniorTM":
        if r.get("tm_user_id") != user["id"]:
            tm = await db.users.find_one({"id": r.get("tm_user_id")}, {"_id": 0, "manager_user_id": 1})
            if not tm or tm.get("manager_user_id") != user["id"]:
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
        w.writerow(["Doctor", "Clinic", "City", "Segment", "Visits", "Last visit", "Sentiment", "Topics", "Barriers", "Promises", "Demos booked", "Demos completed", "Demo dates", "Latest note"])
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
                d.get("demos_booked_count", 0),
                d.get("demos_completed_count", 0),
                "; ".join(d.get("demo_dates", []) or []),
                d.get("note_full") or d.get("note_excerpt", "") or "",
            ])
        w.writerow([])
        # iTero demos this week (booked + completed)
        w.writerow(["iTero demos booked this week"])
        w.writerow(["Doctor", "Clinic", "Scheduled at", "Status"])
        for dm in (c.get("demos_booked_list", []) or []):
            w.writerow([dm.get("doctor_name", ""), dm.get("clinic_name", "") or "", dm.get("scheduled_at", "") or "", dm.get("status", "") or ""])
        w.writerow([])
        w.writerow(["iTero demos completed this week"])
        w.writerow(["Doctor", "Clinic", "Scheduled at", "Completed at"])
        for dm in (c.get("demos_completed_list", []) or []):
            w.writerow([dm.get("doctor_name", ""), dm.get("clinic_name", "") or "", dm.get("scheduled_at", "") or "", dm.get("completed_at", "") or ""])
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
    styles.add(ParagraphStyle(name="TableCell", parent=styles["Normal"], fontSize=8.5,
                              textColor=colors.HexColor("#274035"), leading=11))

    def _pdf_safe(text: str) -> str:
        """reportlab's default font can't render most emoji (shows as tofu boxes) —
        swap the ones we actually generate for plain-text equivalents. Only used on
        the PDF path; the same strings still render fine as real emoji in the app."""
        return (text or "").replace("⚠️", "!").replace("⚠", "!")

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
        items = [ListItem(Paragraph(_pdf_safe(line), styles["Body"]), leftIndent=8) for line in c["key_insights"]]
        flow.append(ListFlowable(items, bulletType="bullet", start="•"))

    if c.get("doctors_needing_attention"):
        flow.append(Paragraph("Doctors needing attention next week", styles["H2"]))
        rows = [["Doctor", "Segment", "Reason", "Score"]]
        for d in c["doctors_needing_attention"]:
            # Plain strings in a reportlab Table never wrap — a long "Reason" just
            # overflows and overlaps the Score column next to it. Wrap the
            # free-text cells in Paragraphs so they wrap within the column instead.
            rows.append([
                Paragraph(d.get("doctor_name", ""), styles["TableCell"]),
                Paragraph(d.get("segment", ""), styles["TableCell"]),
                Paragraph(d.get("reason", ""), styles["TableCell"]),
                str(d.get("score", "")),
            ])
        att = Table(rows, colWidths=[35 * mm, 22 * mm, 78 * mm, 15 * mm])
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

    # iTero demos this week — booked & completed
    demos_booked_list = c.get("demos_booked_list") or []
    demos_completed_list = c.get("demos_completed_list") or []
    if demos_booked_list or demos_completed_list:
        flow.append(Paragraph("iTero demos this week", styles["H2"]))
        rows = [["Doctor", "Clinic", "Scheduled", "Status"]]
        for dm in demos_booked_list:
            rows.append([
                Paragraph(dm.get("doctor_name", ""), styles["TableCell"]),
                Paragraph(dm.get("clinic_name", "") or "", styles["TableCell"]),
                (dm.get("scheduled_at", "") or "")[:16].replace("T", " "),
                "Completed" if dm.get("is_completed") else (dm.get("status") or "Scheduled"),
            ])
        # also append completed-this-week demos whose booking isn't in this week
        booked_ids = {dm.get("meeting_id") for dm in demos_booked_list}
        for dm in demos_completed_list:
            if dm.get("meeting_id") in booked_ids:
                continue
            rows.append([
                Paragraph(dm.get("doctor_name", ""), styles["TableCell"]),
                Paragraph(dm.get("clinic_name", "") or "", styles["TableCell"]),
                (dm.get("scheduled_at", "") or "")[:16].replace("T", " "),
                "Completed",
            ])
        dt = Table(rows, colWidths=[45 * mm, 45 * mm, 40 * mm, 25 * mm])
        dt.setStyle(TableStyle([
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
        flow.append(dt)

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
            db_count = d.get("demos_booked_count", 0)
            dc_count = d.get("demos_completed_count", 0)
            if db_count or dc_count:
                dm_line = []
                if db_count:
                    dm_line.append(f"{db_count} booked")
                if dc_count:
                    dm_line.append(f"{dc_count} completed")
                if d.get("demo_dates"):
                    dm_line.append("on " + ", ".join(d["demo_dates"]))
                head_bits.append(Paragraph("<b>iTero demos:</b> " + " · ".join(dm_line), styles["Body"]))
            if d.get("topics"):
                head_bits.append(Paragraph("<b>Topics:</b> " + ", ".join(d["topics"]), styles["Body"]))
            if d.get("barriers"):
                head_bits.append(Paragraph("<b>Barriers:</b> " + ", ".join(d["barriers"]), styles["Body"]))
            if d.get("promises"):
                head_bits.append(Paragraph("<b>Promises:</b> " + "; ".join(d["promises"]), styles["Body"]))
            note_text = d.get("note_full") or d.get("note_excerpt")
            if note_text:
                # ReportLab Paragraph treats &<> as markup; escape them, preserve
                # line breaks so multi-paragraph notes render readably and the
                # text wraps to full width across as many lines as needed.
                from xml.sax.saxutils import escape as _xml_escape
                safe = _xml_escape(note_text).replace("\n", "<br/>")
                head_bits.append(Paragraph(f"<i>{safe}</i>", styles["Muted"]))
            for elem in head_bits:
                flow.append(elem)
            flow.append(Spacer(1, 6))

    from xml.sax.saxutils import escape as _xml_escape

    notes = (c.get("notes_from_tm") or r.get("notes_from_tm") or "").strip()
    if notes:
        flow.append(Paragraph("TM notes", styles["H2"]))
        flow.append(Paragraph(_xml_escape(notes).replace("\n", "<br/>"), styles["Body"]))

    if r.get("manager_comment"):
        flow.append(Paragraph("Manager comment", styles["H2"]))
        flow.append(Paragraph(_xml_escape(r["manager_comment"]).replace("\n", "<br/>"), styles["Body"]))

    doc.build(flow)
    pdf_bytes = buf.getvalue()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{base}.pdf"'},
    )
