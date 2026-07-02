"""Monthly Reimbursement Report module (Phase M1).

Provides the doctor-KM database + the reimbursement-report workflow:
generate → draft → submit → review (approve / reject / request changes) →
paid.

Data model (all one-per-doc):
- `doctor_km`         — per-doctor km-per-visit lookup.
- `reimbursement_reports`  — one report per (tm_user_id, month).

Existing `expenses` collection is REUSED for the receipt/invoice line items
that a TM attaches to a report. A new optional field `reimbursement_report_id`
links each expense to its parent report. That keeps the existing "monthly
expenses" UX intact while letting a reimbursement report aggregate the exact
same rows.
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Body

from server import (
    api, db,
    get_current_user, require_roles,
    _company_query_for, _managed_tm_ids_for, _same_company, _audit,
)


DEFAULT_CONSUMPTION_L_PER_100KM = 11.0
REPORT_STATUSES = ("Draft", "Submitted", "Changes Requested", "Approved", "Rejected", "Paid", "Needs Recalculation")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _month_bounds(month: str) -> tuple[str, str]:
    """`month` = YYYY-MM. Returns (YYYY-MM-01, YYYY-MM-31) inclusive strings."""
    if not month or len(month) != 7 or month[4] != "-":
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    return f"{month}-01", f"{month}-31"


# ============================================================
# DOCTOR KM DATABASE
# ============================================================
@api.get("/doctor-km")
async def list_doctor_km(user=Depends(get_current_user)):
    """List KM-per-visit records for the caller's company. Every role can read."""
    q = dict(_company_query_for(user))
    rows = await db.doctor_km.find(q, {"_id": 0}).sort([("doctor_name", 1)]).to_list(5000)
    return {"records": rows}


@api.post("/doctor-km")
async def upsert_doctor_km(body: dict = Body(...), user=Depends(get_current_user)):
    """Create or update a KM record.

    - Admin / Owner / SeniorTM: unrestricted upsert.
    - TM: allowed ONLY when no active record exists for that doctor (the
      "fill missing KM during report generation" flow). Any TM upsert is
      recorded as `created_by_role='TM'` so SeniorTM/Admin can audit.
    """
    doctor_id = body.get("doctor_id")
    km_per_visit = body.get("km_per_visit")
    if not doctor_id:
        raise HTTPException(status_code=400, detail="doctor_id required")
    try:
        km_val = float(km_per_visit)
        if km_val < 0 or km_val > 5000:
            raise ValueError()
    except Exception:
        raise HTTPException(status_code=400, detail="km_per_visit must be 0-5000")

    doctor = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    if not _same_company(user, doctor):
        raise HTTPException(status_code=403, detail="Cross-company forbidden")

    existing = await db.doctor_km.find_one({"doctor_id": doctor_id, "company_id": doctor.get("company_id")})
    now = _now_iso()
    if user["role"] == "TM":
        if existing and existing.get("km_per_visit") is not None:
            raise HTTPException(status_code=403, detail="TM cannot overwrite existing KM — ask your Senior TM.")
        status = "PendingReview"
    else:
        status = "Active"

    if existing:
        upd = {
            "km_per_visit": km_val,
            "status": status,
            "updated_at": now,
            "updated_by_user_id": user["id"],
            "updated_by_role": user["role"],
        }
        await db.doctor_km.update_one({"_id": existing["_id"]}, {"$set": upd})
        record_id = existing.get("id")
    else:
        import uuid
        record_id = str(uuid.uuid4())
        await db.doctor_km.insert_one({
            "id": record_id,
            "doctor_id": doctor_id,
            "doctor_name": doctor.get("doctor_name") or "",
            "clinic_name": doctor.get("clinic_name") or "",
            "city": doctor.get("city") or "",
            "km_per_visit": km_val,
            "status": status,
            "company_id": doctor.get("company_id"),
            "created_by_user_id": user["id"],
            "created_by_role": user["role"],
            "created_at": now,
            "updated_at": now,
            "updated_by_user_id": user["id"],
            "updated_by_role": user["role"],
        })
    await _audit(user, "upsert", "doctor_km", record_id, new={"km_per_visit": km_val, "status": status})
    return {"id": record_id, "km_per_visit": km_val, "status": status}


# ============================================================
# REIMBURSEMENT REPORTS
# ============================================================
async def _visits_for_month(tm_user_id: str, month: str, company_id: Optional[str]) -> list[dict]:
    m_from, m_to = _month_bounds(month)
    q = {"tm_user_id": tm_user_id, "visit_date": {"$gte": m_from, "$lte": m_to + "T23:59:59Z"}}
    if company_id:
        q["company_id"] = company_id
    return await db.visits.find(q, {"_id": 0}).to_list(5000)


async def _build_breakdown(tm_user_id: str, month: str, company_id: Optional[str]) -> dict:
    """Aggregate visits → per-doctor counts → match against doctor_km."""
    visits = await _visits_for_month(tm_user_id, month, company_id)
    counts: dict[str, int] = {}
    for v in visits:
        did = v.get("doctor_id")
        if did:
            counts[did] = counts.get(did, 0) + 1

    breakdown = []
    missing = []
    total_km = 0.0
    if counts:
        docs = await db.doctors.find({"id": {"$in": list(counts.keys())}}, {"_id": 0}).to_list(len(counts))
        km_rows = await db.doctor_km.find({"doctor_id": {"$in": list(counts.keys())}}, {"_id": 0}).to_list(len(counts))
        km_by_doc = {r["doctor_id"]: r for r in km_rows}
        docs_by_id = {d["id"]: d for d in docs}
        for did, cnt in counts.items():
            d = docs_by_id.get(did) or {}
            km = km_by_doc.get(did)
            km_val = float(km["km_per_visit"]) if km and km.get("km_per_visit") is not None else None
            total = round((km_val or 0.0) * cnt, 2)
            row = {
                "doctor_id": did,
                "doctor_name": d.get("doctor_name") or "Unknown",
                "clinic_name": d.get("clinic_name") or "",
                "city": d.get("city") or "",
                "visit_count": cnt,
                "km_per_visit": km_val,
                "total_km": total if km_val is not None else None,
                "match_status": ("Matched" if km_val is not None else "MissingKM"),
            }
            breakdown.append(row)
            if km_val is None:
                missing.append({"doctor_id": did, "doctor_name": row["doctor_name"], "clinic_name": row["clinic_name"], "city": row["city"], "visit_count": cnt})
            else:
                total_km += total
    breakdown.sort(key=lambda r: (r["match_status"] != "MissingKM", -r["visit_count"]))
    return {
        "breakdown": breakdown,
        "missing_km": missing,
        "total_visits": sum(counts.values()),
        "unique_doctors": len(counts),
        "total_km": round(total_km, 2),
    }


def _compute_totals(report: dict, expenses: list[dict]) -> dict:
    consumption = float(report.get("fuel_consumption_l_per_100km") or DEFAULT_CONSUMPTION_L_PER_100KM)
    price = report.get("fuel_price_per_l")
    total_km = float(report.get("total_km") or 0.0)
    litres = round(total_km * consumption / 100.0, 3)
    fuel_cost = round(litres * float(price), 2) if price is not None else None

    by_cat: dict[str, float] = {"Food": 0.0, "Hotel": 0.0, "Parking": 0.0, "Tolls": 0.0, "Other": 0.0}
    manual_total = 0.0
    receipt_count = 0
    exception_count = 0
    for e in expenses:
        cat = e.get("category") or "Other"
        amt = float(e.get("amount") or 0)
        if cat not in by_cat:
            cat = "Other"
        by_cat[cat] += amt
        manual_total += amt
        if e.get("receipt_image_id"):
            receipt_count += 1
        elif e.get("exception_approved"):
            exception_count += 1

    already = float(report.get("already_reimbursed") or 0.0)
    total_reimbursable = (fuel_cost or 0.0) + manual_total
    amount_due = round(total_reimbursable - already, 2)
    return {
        "consumption_l_per_100km": consumption,
        "fuel_price_per_l": price,
        "litres_used": litres,
        "fuel_cost": fuel_cost,
        "by_category": {k: round(v, 2) for k, v in by_cat.items()},
        "manual_expenses_total": round(manual_total, 2),
        "total_reimbursable": round(total_reimbursable, 2) if price is not None else None,
        "already_reimbursed": round(already, 2),
        "amount_to_reimburse": amount_due if price is not None else None,
        "receipt_invoice_count": receipt_count,
        "exception_count": exception_count,
    }


async def _load_expenses_for(report: dict) -> list[dict]:
    q = {"reimbursement_report_id": report["id"]}
    return await db.expenses.find(q, {"_id": 0}).to_list(5000)


async def _hydrate(report: dict) -> dict:
    expenses = await _load_expenses_for(report)
    totals = _compute_totals(report, expenses)
    out = dict(report)
    out["expenses"] = expenses
    out["totals"] = totals
    return out


@api.post("/reimbursement/reports/generate")
async def generate_reimbursement_report(body: dict = Body(...), user=Depends(get_current_user)):
    """TM (self only) or SeniorTM (for a member of their sub-team) generates
    a monthly report by pulling visits + doctor KM lookup for the given month.

    Body: {month: "YYYY-MM", tm_user_id?: str}
    """
    month = body.get("month")
    target_tm_id = body.get("tm_user_id") or user["id"]
    if user["role"] == "TM" and target_tm_id != user["id"]:
        raise HTTPException(status_code=403, detail="TMs can only generate for themselves")
    if user["role"] == "SeniorTM":
        ids = await _managed_tm_ids_for(user) or [user["id"]]
        if target_tm_id not in ids:
            raise HTTPException(status_code=403, detail="TM not in your sub-team")

    tm = await db.users.find_one({"id": target_tm_id}, {"_id": 0, "password_hash": 0})
    if not tm:
        raise HTTPException(status_code=404, detail="TM not found")

    # Prevent duplicate active reports for the same TM+month.
    dup = await db.reimbursement_reports.find_one({
        "tm_user_id": target_tm_id,
        "month": month,
        "status": {"$nin": ["Rejected", "Cancelled"]},
    })
    if dup:
        return await _hydrate(dup)

    agg = await _build_breakdown(target_tm_id, month, tm.get("company_id"))
    weekly_ids = [r["id"] for r in await db.reports.find(
        {"tm_user_id": target_tm_id, "week_start": {"$regex": f"^{month}"}},
        {"_id": 0, "id": 1},
    ).to_list(20)]

    import uuid
    report = {
        "id": str(uuid.uuid4()),
        "tm_user_id": target_tm_id,
        "tm_name": tm.get("full_name") or tm.get("email"),
        "senior_tm_user_id": tm.get("manager_user_id"),
        "month": month,
        "status": "Draft",
        "company_id": tm.get("company_id"),
        "fuel_consumption_l_per_100km": DEFAULT_CONSUMPTION_L_PER_100KM,
        "fuel_price_per_l": None,
        "already_reimbursed": 0.0,
        "doctor_breakdown": agg["breakdown"],
        "total_visits": agg["total_visits"],
        "unique_doctors": agg["unique_doctors"],
        "total_km": agg["total_km"],
        "weekly_report_ids": weekly_ids,
        "comments": [],
        "audit": [{"at": _now_iso(), "by": user["id"], "role": user["role"], "action": "generated"}],
        "created_at": _now_iso(),
        "created_by_user_id": user["id"],
        "updated_at": _now_iso(),
        "submitted_at": None,
        "reviewed_at": None,
        "reviewed_by_user_id": None,
        "paid_at": None,
    }
    await db.reimbursement_reports.insert_one(report)
    await _audit(user, "generate", "reimbursement_report", report["id"], new={"month": month, "tm_user_id": target_tm_id, "total_km": agg["total_km"]})
    report.pop("_id", None)
    return await _hydrate(report)


async def _load_report_scoped(report_id: str, user) -> dict:
    report = await db.reimbursement_reports.find_one({"id": report_id}, {"_id": 0})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not _same_company(user, report):
        raise HTTPException(status_code=403, detail="Cross-company forbidden")
    role = user["role"]
    if role == "TM" and report["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if role == "SeniorTM":
        ids = await _managed_tm_ids_for(user) or [user["id"]]
        if report["tm_user_id"] not in ids:
            raise HTTPException(status_code=403, detail="TM not in your sub-team")
    return report


@api.get("/reimbursement/reports")
async def list_reimbursement_reports(month: Optional[str] = None, status: Optional[str] = None, user=Depends(get_current_user)):
    q = dict(_company_query_for(user))
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "SeniorTM":
        ids = await _managed_tm_ids_for(user) or [user["id"]]
        q["tm_user_id"] = {"$in": ids}
    if month:
        q["month"] = month
    if status:
        q["status"] = status
    rows = await db.reimbursement_reports.find(q, {"_id": 0}).sort([("month", -1), ("created_at", -1)]).to_list(500)
    # Cheap hydration for the list view — totals but not full expense rows.
    out = []
    for r in rows:
        expenses = await _load_expenses_for(r)
        r["totals"] = _compute_totals(r, expenses)
        r["expense_count"] = len(expenses)
        out.append(r)
    return {"reports": out}


@api.get("/reimbursement/reports/{report_id}")
async def get_reimbursement_report(report_id: str, user=Depends(get_current_user)):
    report = await _load_report_scoped(report_id, user)
    return await _hydrate(report)


@api.patch("/reimbursement/reports/{report_id}")
async def update_reimbursement_report(report_id: str, body: dict = Body(...), user=Depends(get_current_user)):
    """TM edits draft/changes-requested fields (fuel_price, already_reimbursed).
    SeniorTM/Admin may also edit fuel_consumption_l_per_100km.
    """
    report = await _load_report_scoped(report_id, user)
    if user["role"] == "TM" and report["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    editable_statuses = ("Draft", "Changes Requested")
    if user["role"] == "TM" and report["status"] not in editable_statuses:
        raise HTTPException(status_code=403, detail=f"TM cannot edit a {report['status']} report")

    updates: dict = {}
    if "fuel_price_per_l" in body and body["fuel_price_per_l"] is not None:
        p = float(body["fuel_price_per_l"])
        if p < 0 or p > 100:
            raise HTTPException(status_code=400, detail="fuel_price_per_l out of range")
        updates["fuel_price_per_l"] = p
    if "already_reimbursed" in body and body["already_reimbursed"] is not None:
        updates["already_reimbursed"] = float(body["already_reimbursed"])
    if user["role"] in ("SeniorTM", "Admin", "Owner") and "fuel_consumption_l_per_100km" in body:
        updates["fuel_consumption_l_per_100km"] = float(body["fuel_consumption_l_per_100km"])
    if not updates:
        raise HTTPException(status_code=400, detail="No editable fields provided")
    updates["updated_at"] = _now_iso()
    updates["updated_by_user_id"] = user["id"]
    await db.reimbursement_reports.update_one(
        {"id": report_id},
        {"$set": updates, "$push": {"audit": {"at": _now_iso(), "by": user["id"], "role": user["role"], "action": "edit", "fields": list(updates.keys())}}},
    )
    await _audit(user, "update", "reimbursement_report", report_id, new=updates)
    report = await db.reimbursement_reports.find_one({"id": report_id}, {"_id": 0})
    return await _hydrate(report)


@api.post("/reimbursement/reports/{report_id}/refresh-breakdown")
async def refresh_breakdown(report_id: str, user=Depends(get_current_user)):
    """Re-run the visits→breakdown aggregation. Called after the TM fills in
    missing KM values so the doctor table shows Matched rows and the total_km
    updates."""
    report = await _load_report_scoped(report_id, user)
    if user["role"] == "TM" and report["status"] not in ("Draft", "Changes Requested"):
        raise HTTPException(status_code=403, detail=f"Cannot refresh a {report['status']} report")
    agg = await _build_breakdown(report["tm_user_id"], report["month"], report.get("company_id"))
    await db.reimbursement_reports.update_one(
        {"id": report_id},
        {"$set": {
            "doctor_breakdown": agg["breakdown"],
            "total_visits": agg["total_visits"],
            "unique_doctors": agg["unique_doctors"],
            "total_km": agg["total_km"],
            "updated_at": _now_iso(),
        },
         "$push": {"audit": {"at": _now_iso(), "by": user["id"], "role": user["role"], "action": "refresh"}}},
    )
    report = await db.reimbursement_reports.find_one({"id": report_id}, {"_id": 0})
    return await _hydrate(report)


def _validate_submittable(report: dict, expenses: list[dict]) -> None:
    if report.get("fuel_price_per_l") in (None, "", 0):
        raise HTTPException(status_code=400, detail="Fuel price per litre is required before submission")
    for row in report.get("doctor_breakdown", []):
        if row.get("km_per_visit") is None:
            raise HTTPException(status_code=400, detail=f"Missing KM for doctor '{row.get('doctor_name')}' — fill in the Missing KM table.")
    for e in expenses:
        if not e.get("receipt_image_id") and not e.get("exception_approved"):
            raise HTTPException(status_code=400, detail=f"Expense '{e.get('vendor') or e.get('category')}' has no receipt attached")


@api.post("/reimbursement/reports/{report_id}/submit")
async def submit_reimbursement_report(report_id: str, user=Depends(get_current_user)):
    report = await _load_report_scoped(report_id, user)
    if report["tm_user_id"] != user["id"] and user["role"] not in ("Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Only the report owner or Admin can submit")
    if report["status"] not in ("Draft", "Changes Requested"):
        raise HTTPException(status_code=400, detail=f"Cannot submit a {report['status']} report")
    expenses = await _load_expenses_for(report)
    _validate_submittable(report, expenses)
    now = _now_iso()
    await db.reimbursement_reports.update_one(
        {"id": report_id},
        {"$set": {"status": "Submitted", "submitted_at": now, "updated_at": now},
         "$push": {"audit": {"at": now, "by": user["id"], "role": user["role"], "action": "submit"}}},
    )
    await _audit(user, "submit", "reimbursement_report", report_id)
    report = await db.reimbursement_reports.find_one({"id": report_id}, {"_id": 0})
    return await _hydrate(report)


async def _review_transition(report_id: str, new_status: str, comment: Optional[str], user) -> dict:
    report = await _load_report_scoped(report_id, user)
    if user["role"] not in ("SeniorTM", "Admin", "Owner"):
        raise HTTPException(status_code=403, detail="Only Senior TM or Admin can review")
    if user["role"] == "SeniorTM":
        ids = await _managed_tm_ids_for(user) or [user["id"]]
        if report["tm_user_id"] not in ids:
            raise HTTPException(status_code=403, detail="TM not in your sub-team")
    if report["status"] not in ("Submitted", "Changes Requested"):
        raise HTTPException(status_code=400, detail=f"Cannot review a {report['status']} report")
    if new_status in ("Changes Requested", "Rejected") and not comment:
        raise HTTPException(status_code=400, detail="A comment is required for this action")

    now = _now_iso()
    updates = {"status": new_status, "reviewed_at": now, "reviewed_by_user_id": user["id"], "updated_at": now}
    push = {"audit": {"at": now, "by": user["id"], "role": user["role"], "action": new_status.lower().replace(" ", "_"), "comment": comment}}
    if comment:
        push["comments"] = {"at": now, "by": user["id"], "role": user["role"], "text": comment}
    await db.reimbursement_reports.update_one({"id": report_id}, {"$set": updates, "$push": push})
    await _audit(user, "review", "reimbursement_report", report_id, new={"status": new_status, "comment": (comment or "")[:200]})
    report = await db.reimbursement_reports.find_one({"id": report_id}, {"_id": 0})
    return await _hydrate(report)


@api.post("/reimbursement/reports/{report_id}/approve")
async def approve_report(report_id: str, body: dict = Body(default={}), user=Depends(get_current_user)):
    return await _review_transition(report_id, "Approved", body.get("comment"), user)


@api.post("/reimbursement/reports/{report_id}/reject")
async def reject_report(report_id: str, body: dict = Body(...), user=Depends(get_current_user)):
    return await _review_transition(report_id, "Rejected", body.get("comment") or "", user)


@api.post("/reimbursement/reports/{report_id}/request-changes")
async def request_changes(report_id: str, body: dict = Body(...), user=Depends(get_current_user)):
    return await _review_transition(report_id, "Changes Requested", body.get("comment") or "", user)


@api.post("/reimbursement/reports/{report_id}/mark-paid")
async def mark_paid(report_id: str, user=Depends(require_roles("SeniorTM", "Admin", "Owner"))):
    report = await _load_report_scoped(report_id, user)
    if report["status"] != "Approved":
        raise HTTPException(status_code=400, detail=f"Only Approved reports can be marked Paid (current: {report['status']})")
    now = _now_iso()
    await db.reimbursement_reports.update_one(
        {"id": report_id},
        {"$set": {"status": "Paid", "paid_at": now, "updated_at": now},
         "$push": {"audit": {"at": now, "by": user["id"], "role": user["role"], "action": "mark_paid"}}},
    )
    await _audit(user, "mark_paid", "reimbursement_report", report_id)
    report = await db.reimbursement_reports.find_one({"id": report_id}, {"_id": 0})
    return await _hydrate(report)


# ============================================================
# PDF export
# ============================================================
@api.get("/reimbursement/reports/{report_id}/pdf")
async def reimbursement_pdf(report_id: str, user=Depends(get_current_user)):
    from fastapi.responses import Response
    report = await _load_report_scoped(report_id, user)
    hydrated = await _hydrate(report)
    pdf_bytes = _render_reimbursement_pdf(hydrated)
    fname = f"reimbursement_{report['tm_name'].replace(' ', '_')}_{report['month']}.pdf"
    await _audit(user, "export", "reimbursement_report", report_id, new={"format": "pdf"})
    return Response(pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


def _render_reimbursement_pdf(report: dict) -> bytes:
    import io as _io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, textColor=colors.HexColor("#1a3d2f"), spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#1a3d2f"), spaceBefore=8, spaceAfter=4)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=13)

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    story = []
    t = report.get("totals", {}) or {}
    story.append(Paragraph("FieldMind — Monthly Reimbursement Report", h1))
    story.append(Paragraph(f"Generated {_now_iso()[:19].replace('T',' ')} UTC — Report {report.get('id','')[:8]}", small))
    story.append(Spacer(1, 6*mm))

    meta = [
        ["TM", report.get("tm_name") or "—"],
        ["Month", report.get("month") or "—"],
        ["Status", report.get("status") or "—"],
        ["Submitted", (report.get("submitted_at") or "—")[:19].replace("T", " ")],
        ["Reviewed", (report.get("reviewed_at") or "—")[:19].replace("T", " ")],
        ["Paid", (report.get("paid_at") or "—")[:19].replace("T", " ")],
    ]
    m = Table(meta, colWidths=[35*mm, 140*mm])
    m.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f4f2ee")),
                           ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#d9d6cf")),
                           ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e6e2da"))]))
    story.append(m)

    # Totals
    story.append(Paragraph("Reimbursement summary", h2))
    def _eur(v):
        if v is None:
            return "—"
        return f"€ {v:,.2f}"
    totals_tbl = [
        ["Total visits", report.get("total_visits", 0), "Total KM", f"{report.get('total_km', 0):.2f} km"],
        ["Unique doctors", report.get("unique_doctors", 0), "Consumption", f"{t.get('consumption_l_per_100km', 11):.1f} L/100km"],
        ["Fuel price / L", _eur(t.get("fuel_price_per_l")), "Litres used", f"{t.get('litres_used', 0):.2f} L"],
        ["Fuel cost", _eur(t.get("fuel_cost")), "Manual expenses", _eur(t.get("manual_expenses_total"))],
        ["Total reimbursable", _eur(t.get("total_reimbursable")), "Already reimbursed", _eur(t.get("already_reimbursed"))],
        ["", "", "Amount to reimburse", _eur(t.get("amount_to_reimburse"))],
    ]
    tt = Table(totals_tbl, colWidths=[42*mm, 45*mm, 42*mm, 46*mm])
    tt.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("FONTNAME", (2, -1), (3, -1), "Helvetica-Bold"),
                            ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#d9d6cf")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e6e2da"))]))
    story.append(tt)

    story.append(Paragraph("Doctor breakdown", h2))
    hdr = ["Doctor", "City", "Visits", "KM / visit", "Total KM", "Match"]
    rows = [hdr]
    for r in report.get("doctor_breakdown", []):
        rows.append([r.get("doctor_name") or "—", r.get("city") or "—",
                     r.get("visit_count", 0),
                     f"{r.get('km_per_visit'):.1f}" if r.get("km_per_visit") is not None else "—",
                     f"{r.get('total_km'):.1f}" if r.get("total_km") is not None else "—",
                     r.get("match_status") or "—"])
    db_tbl = Table(rows, colWidths=[55*mm, 30*mm, 15*mm, 22*mm, 22*mm, 25*mm])
    db_tbl.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f2ee")),
                                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#d9d6cf")),
                                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e6e2da"))]))
    story.append(db_tbl)

    exps = report.get("expenses", []) or []
    if exps:
        story.append(Paragraph("Manual expenses (receipts)", h2))
        e_hdr = ["Category", "Vendor", "Date", "Amount", "Receipt"]
        e_rows = [e_hdr]
        for e in exps:
            e_rows.append([e.get("category") or "—",
                           e.get("vendor") or "—",
                           (e.get("expense_date") or "—")[:10],
                           _eur(e.get("amount")),
                           "Yes" if e.get("receipt_image_id") else ("Exception" if e.get("exception_approved") else "MISSING")])
        et = Table(e_rows, colWidths=[25*mm, 55*mm, 25*mm, 30*mm, 30*mm])
        et.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f2ee")),
                                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#d9d6cf")),
                                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e6e2da"))]))
        story.append(et)

    if report.get("comments"):
        story.append(Paragraph("Review comments", h2))
        for c in report["comments"][-5:]:
            story.append(Paragraph(f"<i>{c.get('role','?')} · {c.get('at','')[:19].replace('T',' ')}</i>: {c.get('text','')}", body))

    doc.build(story)
    return buf.getvalue()
