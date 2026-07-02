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
import re

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


async def _build_event_breakdown(tm_user_id: str, month: str, company_id: Optional[str]) -> dict:
    """Fetch every event the TM had scheduled inside `month` and turn them into
    reimbursement rows. Each event has an optional `km` field (the TM types it
    in from the reimbursement drawer). Rows without km get `MissingKM`.

    Cancelled events are ignored so a TM isn't paid for events they never
    attended."""
    start, end = _month_bounds(month)
    q: dict = {
        "tm_user_id": tm_user_id,
        "scheduled_at": {"$gte": start, "$lte": f"{end}T23:59:59Z"},
        "status": {"$ne": "Cancelled"},
    }
    if company_id:
        q["company_id"] = company_id
    events = await db.events.find(q, {"_id": 0}).sort([("scheduled_at", 1)]).to_list(500)
    rows = []
    missing = []
    total_km = 0.0
    for e in events:
        km_val = e.get("km")
        km_val = float(km_val) if km_val not in (None, "") else None
        row = {
            "event_id": e["id"],
            "title": e.get("title") or "Event",
            "scheduled_at": e.get("scheduled_at"),
            "location": e.get("location") or "",
            "status": e.get("status") or "Scheduled",
            "km": km_val,
            "match_status": "Matched" if km_val is not None else "MissingKM",
        }
        rows.append(row)
        if km_val is None:
            missing.append({"event_id": e["id"], "title": row["title"], "scheduled_at": row["scheduled_at"], "location": row["location"]})
        else:
            total_km += km_val
    return {
        "events": rows,
        "missing_km": missing,
        "event_count": len(rows),
        "events_total_km": round(total_km, 2),
    }



def _compute_totals(report: dict, expenses: list[dict]) -> dict:
    consumption = float(report.get("fuel_consumption_l_per_100km") or DEFAULT_CONSUMPTION_L_PER_100KM)
    price = report.get("fuel_price_per_l")
    total_km = float(report.get("total_km") or 0.0)
    litres = round(total_km * consumption / 100.0, 3)
    fuel_cost = round(litres * float(price), 2) if price is not None else None
    report_id = report.get("id")
    month = report.get("month") or ""

    # Buckets:
    #   by_cat_recorded      — sum by category across EVERY expense we loaded
    #                          (current month + prior-month expenses linked
    #                          via search). Purely informational.
    #   manual_total         — sum of non-Petrol expenses that count toward
    #                          reimbursement. A row counts if it's in the
    #                          report's month (auto-include) OR explicitly
    #                          linked via `reimbursement_report_id == report.id`
    #                          (a previous-month expense the TM pulled in
    #                          from the search widget).
    #   petrol_recorded      — every Petrol receipt in the loaded set —
    #                          never contributes to manual_total.
    by_cat_recorded: dict[str, float] = {"Petrol": 0.0, "Food": 0.0, "Hotel": 0.0, "Parking": 0.0, "Tolls": 0.0, "Other": 0.0}
    manual_total = 0.0
    petrol_recorded = 0.0
    receipt_count_counted = 0
    exception_count_counted = 0
    included_count = 0
    for e in expenses:
        cat = e.get("category") or "Other"
        amt = float(e.get("amount") or 0)
        if cat not in by_cat_recorded:
            cat = "Other"
        by_cat_recorded[cat] += amt

        exp_date = (e.get("expense_date") or "")
        in_current_month = exp_date.startswith(month) if month else False
        is_linked = e.get("reimbursement_report_id") == report_id
        counts_in_manual = (cat != "Petrol") and (in_current_month or is_linked)

        if cat == "Petrol":
            petrol_recorded += amt
        elif counts_in_manual:
            manual_total += amt
        if counts_in_manual:
            included_count += 1
            if e.get("receipt_image_id"):
                receipt_count_counted += 1
            elif e.get("exception_approved"):
                exception_count_counted += 1

    expenses_recorded_total = round(petrol_recorded + sum(v for k, v in by_cat_recorded.items() if k != "Petrol"), 2)
    variance = None
    if fuel_cost is not None:
        variance = round(expenses_recorded_total - fuel_cost, 2)

    already = float(report.get("already_reimbursed") or 0.0)
    total_reimbursable = (fuel_cost or 0.0) + manual_total
    amount_due = round(total_reimbursable - already, 2)
    return {
        "consumption_l_per_100km": consumption,
        "fuel_price_per_l": price,
        "litres_used": litres,
        "fuel_cost": fuel_cost,
        "by_category": {k: round(v, 2) for k, v in by_cat_recorded.items()},
        "manual_expenses_total": round(manual_total, 2),
        "petrol_receipts_total": round(petrol_recorded, 2),
        "expenses_recorded_total": expenses_recorded_total,
        "variance_vs_km_fuel": variance,
        "included_expense_count": included_count,
        "total_reimbursable": round(total_reimbursable, 2) if price is not None else None,
        "already_reimbursed": round(already, 2),
        "amount_to_reimburse": amount_due if price is not None else None,
        "receipt_invoice_count": receipt_count_counted,
        "exception_count": exception_count_counted,
    }


async def _load_expenses_for(report: dict) -> list[dict]:
    """Return every expense that belongs on this report:

    - All expenses the TM logged during the report's month (auto-included
      unless the TM explicitly unlinks — Phase O.4/O.5).
    - Any prior-month expenses the TM has pulled in via the search widget
      (linked via `reimbursement_report_id == report.id`).
    """
    tm_user_id = report.get("tm_user_id")
    month = report.get("month") or ""
    m_from, m_to = _month_bounds(month) if month else (None, None)
    if not tm_user_id or not m_from:
        return []
    q = {
        "tm_user_id": tm_user_id,
        "$or": [
            {"expense_date": {"$gte": m_from, "$lte": f"{m_to}T23:59:59"}},
            {"reimbursement_report_id": report.get("id")},
        ],
    }
    rows = await db.expenses.find(q, {"_id": 0}).sort([("expense_date", 1)]).to_list(5000)
    # De-dup in case an expense matches both branches of the $or.
    seen = set()
    out = []
    for r in rows:
        if r.get("id") in seen:
            continue
        seen.add(r.get("id"))
        out.append(r)
    return out


@api.get("/reimbursement/reports/{report_id}/searchable-expenses")
async def searchable_expenses(
    report_id: str,
    q: Optional[str] = None,
    month: Optional[str] = None,
    limit: int = 25,
    user=Depends(get_current_user),
):
    """Search this TM's expenses OUTSIDE the report's month so the TM can
    pull older / newer receipts into the report from the drawer.

    Returns rows scoped to `report.tm_user_id` and excludes:
      * expenses whose date is within the report's month (already shown).
    Filters:
      * `q` — case-insensitive substring on vendor / category / notes.
      * `month` — narrow to a specific YYYY-MM.
    """
    report = await _load_report_scoped(report_id, user)
    if user["role"] in ("TM", "SeniorTM") and report["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    m_from, m_to = _month_bounds(report["month"])
    match: dict = {
        "tm_user_id": report["tm_user_id"],
        # Exclude the report's own month — those already surface in the panel.
        "$nor": [{"expense_date": {"$gte": m_from, "$lte": f"{m_to}T23:59:59"}}],
    }
    if month:
        try:
            f, t = _month_bounds(month)
            match["expense_date"] = {"$gte": f, "$lte": f"{t}T23:59:59"}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid month, expected YYYY-MM")
    if q:
        safe = re.escape(q.strip())
        match["$or"] = [
            {"vendor": {"$regex": safe, "$options": "i"}},
            {"category": {"$regex": safe, "$options": "i"}},
            {"notes": {"$regex": safe, "$options": "i"}},
        ]
    rows = await db.expenses.find(
        match,
        {"_id": 0, "id": 1, "expense_date": 1, "category": 1, "amount": 1, "currency": 1,
         "vendor": 1, "receipt_image_id": 1, "reimbursement_report_id": 1, "notes": 1},
    ).sort([("expense_date", -1)]).to_list(max(1, min(limit, 100)))
    return {"results": rows, "count": len(rows)}


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
    }, {"_id": 0})
    if dup:
        return await _hydrate(dup)

    agg = await _build_breakdown(target_tm_id, month, tm.get("company_id"))
    ev_agg = await _build_event_breakdown(target_tm_id, month, tm.get("company_id"))
    combined_total_km = round(agg["total_km"] + ev_agg["events_total_km"], 2)
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
        "event_breakdown": ev_agg["events"],
        "total_visits": agg["total_visits"],
        "unique_doctors": agg["unique_doctors"],
        "event_count": ev_agg["event_count"],
        "doctor_total_km": agg["total_km"],
        "events_total_km": ev_agg["events_total_km"],
        "total_km": combined_total_km,
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
    role = user["role"]
    is_tm_scope = role in ("TM", "SeniorTM")  # SeniorTM acts as TM when editing their own report
    if is_tm_scope and report["tm_user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    editable_statuses = ("Draft", "Changes Requested")
    if is_tm_scope and report["status"] not in editable_statuses:
        raise HTTPException(status_code=403, detail=f"You cannot edit a {report['status']} report")

    updates: dict = {}
    if "fuel_price_per_l" in body and body["fuel_price_per_l"] is not None:
        p = float(body["fuel_price_per_l"])
        if p < 0 or p > 100:
            raise HTTPException(status_code=400, detail="fuel_price_per_l out of range")
        updates["fuel_price_per_l"] = p
    if "already_reimbursed" in body and body["already_reimbursed"] is not None:
        updates["already_reimbursed"] = float(body["already_reimbursed"])
    if role in ("SeniorTM", "Admin", "Owner") and "fuel_consumption_l_per_100km" in body:
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
    if user["role"] in ("TM", "SeniorTM") and report["tm_user_id"] == user["id"] and report["status"] not in ("Draft", "Changes Requested"):
        raise HTTPException(status_code=403, detail=f"Cannot refresh a {report['status']} report")
    agg = await _build_breakdown(report["tm_user_id"], report["month"], report.get("company_id"))
    ev_agg = await _build_event_breakdown(report["tm_user_id"], report["month"], report.get("company_id"))
    combined_total_km = round(agg["total_km"] + ev_agg["events_total_km"], 2)
    await db.reimbursement_reports.update_one(
        {"id": report_id},
        {"$set": {
            "doctor_breakdown": agg["breakdown"],
            "event_breakdown": ev_agg["events"],
            "total_visits": agg["total_visits"],
            "unique_doctors": agg["unique_doctors"],
            "event_count": ev_agg["event_count"],
            "doctor_total_km": agg["total_km"],
            "events_total_km": ev_agg["events_total_km"],
            "total_km": combined_total_km,
            "updated_at": _now_iso(),
        },
         "$push": {"audit": {"at": _now_iso(), "by": user["id"], "role": user["role"], "action": "refresh"}}},
    )
    report = await db.reimbursement_reports.find_one({"id": report_id}, {"_id": 0})
    return await _hydrate(report)


# ============================================================
# Include / exclude a recorded expense in this report
# ============================================================
@api.patch("/reimbursement/reports/{report_id}/expenses/{expense_id}")
async def toggle_expense_inclusion(
    report_id: str,
    expense_id: str,
    body: dict,
    user=Depends(get_current_user),
):
    """Attach or detach a single expense to/from this monthly report.

    Body: `{"included": true|false}`.

    - included=true  → sets `expense.reimbursement_report_id = report_id`
                       so the expense counts toward `manual_expenses_total`
                       and gets validated for receipts on submission.
    - included=false → clears the link. The expense stays visible in the
                       reconciliation panel but no longer contributes to
                       the reimbursable amount.

    Only the report owner (TM or SeniorTM) can toggle their own report
    while it's in Draft / Changes Requested. Admin/Owner can toggle any
    report. The expense must belong to the same TM as the report.
    """
    report = await _load_report_scoped(report_id, user)
    if user["role"] in ("TM", "SeniorTM"):
        if report["tm_user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Forbidden")
        if report["status"] not in ("Draft", "Changes Requested"):
            raise HTTPException(status_code=403, detail=f"Cannot edit a {report['status']} report")
    exp = await db.expenses.find_one({"id": expense_id}, {"_id": 0})
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")
    if exp.get("tm_user_id") != report["tm_user_id"]:
        raise HTTPException(status_code=403, detail="Expense does not belong to this TM")

    include = bool(body.get("included"))
    if include:
        # If the expense is already linked to a DIFFERENT report, prevent
        # silent theft — the TM must first detach from the other report.
        other = exp.get("reimbursement_report_id")
        if other and other != report_id:
            raise HTTPException(
                status_code=400,
                detail="This expense is already attached to another report. Detach it there first.",
            )
        await db.expenses.update_one(
            {"id": expense_id},
            {"$set": {"reimbursement_report_id": report_id, "updated_at": _now_iso()}},
        )
    else:
        await db.expenses.update_one(
            {"id": expense_id},
            {"$unset": {"reimbursement_report_id": ""}, "$set": {"updated_at": _now_iso()}},
        )
    await _audit(user, "toggle_expense", "reimbursement_report", report_id,
                 new={"expense_id": expense_id, "included": include})
    report = await db.reimbursement_reports.find_one({"id": report_id}, {"_id": 0})
    return await _hydrate(report)



def _validate_submittable(report: dict, expenses: list[dict]) -> None:
    if report.get("fuel_price_per_l") in (None, "", 0):
        raise HTTPException(status_code=400, detail="Fuel price per litre is required before submission")
    for row in report.get("doctor_breakdown", []):
        if row.get("km_per_visit") is None:
            raise HTTPException(status_code=400, detail=f"Missing KM for doctor '{row.get('doctor_name')}' — fill in the Missing KM table.")
    for ev in report.get("event_breakdown", []):
        if ev.get("km") is None:
            raise HTTPException(status_code=400, detail=f"Missing KM for event '{ev.get('title')}' — enter the KM you drove for this event.")
    for e in expenses:
        # Phase O.3 — receipts are only required for expenses the TM
        # explicitly attached to THIS report (via `reimbursement_report_id`).
        # Other month expenses show up for reconciliation totals but aren't
        # gated by receipt-attachment.
        if e.get("reimbursement_report_id") != report["id"]:
            continue
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
# Delete
# ============================================================
@api.delete("/reimbursement/reports/{report_id}")
async def delete_reimbursement_report(report_id: str, user=Depends(get_current_user)):
    """Remove a reimbursement report.

    - Owner / Admin: can delete a report in ANY status. Useful to purge
      accidentally-generated reports.
    - The report owner (TM or SeniorTM) can delete THEIR OWN report while
      it's still in Draft or Changes Requested — i.e. before or during
      revisions, but never once it's been Submitted / Approved / Paid.
    - Any TM linked to the deleted report has their expenses' inverse
      `reimbursement_report_id` link cleared so nothing dangles.
    """
    report = await _load_report_scoped(report_id, user)
    role = user["role"]
    is_owner = report.get("tm_user_id") == user["id"]
    allowed_owner_statuses = ("Draft", "Changes Requested")

    if role in ("Admin", "Owner"):
        pass  # always allowed
    elif role in ("TM", "SeniorTM") and is_owner and report.get("status") in allowed_owner_statuses:
        pass
    else:
        raise HTTPException(
            status_code=403,
            detail=(
                f"You cannot delete a {report.get('status')} report. Only Draft or Changes Requested reports can be deleted by their owner."
                if is_owner else "Only Admin/Owner can delete another user's report."
            ),
        )

    # Detach linked expenses so their `reimbursement_report_id` back-pointer
    # doesn't reference a ghost. Their receipts / rows are preserved.
    await db.expenses.update_many(
        {"reimbursement_report_id": report_id},
        {"$unset": {"reimbursement_report_id": ""}},
    )

    await db.reimbursement_reports.delete_one({"id": report_id})
    await _audit(user, "delete", "reimbursement_report", report_id,
                 prev={"tm_user_id": report.get("tm_user_id"), "month": report.get("month"), "status": report.get("status")})
    return {"ok": True, "id": report_id}



# ============================================================
# PDF export
# ============================================================
@api.get("/reimbursement/reports/{report_id}/pdf")
async def reimbursement_pdf(report_id: str, user=Depends(get_current_user)):
    from fastapi.responses import Response
    report = await _load_report_scoped(report_id, user)
    hydrated = await _hydrate(report)
    pdf_bytes = _render_reimbursement_pdf(hydrated, weekly=await _weekly_km_summary(report))
    fname = f"reimbursement_{report['tm_name'].replace(' ', '_')}_{report['month']}.pdf"
    await _audit(user, "export", "reimbursement_report", report_id, new={"format": "pdf"})
    return Response(pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


def _iso_week_bucket(date_iso: str) -> tuple[str, str]:
    """Return (label, sort-key) for an ISO date grouped by ISO week."""
    from datetime import datetime as _dt
    try:
        d = _dt.strptime(date_iso[:10], "%Y-%m-%d").date()
    except Exception:
        return ("Unknown", "9999-W99")
    year, week, _ = d.isocalendar()
    # Compute Monday/Sunday of the ISO week for a friendly label.
    from datetime import timedelta as _td
    monday = _dt.fromisocalendar(year, week, 1).date()
    sunday = monday + _td(days=6)
    label = f"Week {week:02d}  ({monday.strftime('%b %d')} – {sunday.strftime('%b %d')})"
    return (label, f"{year}-W{week:02d}")


async def _weekly_km_summary(report: dict) -> list[dict]:
    """Aggregate the report's visits into per-ISO-week km totals so the
    PDF can show a weekly rollup instead of a per-doctor breakdown.
    Doctor-KM values come from the same `doctor_km` collection used by
    _build_breakdown."""
    tm_user_id = report.get("tm_user_id")
    month = report.get("month") or ""
    if not tm_user_id or not month:
        return []
    m_from, m_to = _month_bounds(month)
    visits = await db.visits.find({
        "tm_user_id": tm_user_id,
        "visit_date": {"$gte": m_from, "$lte": f"{m_to}T23:59:59"},
    }, {"_id": 0, "doctor_id": 1, "visit_date": 1}).to_list(5000)
    doctor_ids = list({v.get("doctor_id") for v in visits if v.get("doctor_id")})
    km_rows = []
    if doctor_ids:
        km_rows = await db.doctor_km.find(
            {"doctor_id": {"$in": doctor_ids}}, {"_id": 0, "doctor_id": 1, "km_per_visit": 1}
        ).to_list(len(doctor_ids))
    km_by_doc = {r["doctor_id"]: float(r["km_per_visit"] or 0) for r in km_rows}

    weekly: dict[str, dict] = {}
    for v in visits:
        did = v.get("doctor_id")
        km = km_by_doc.get(did, 0.0)
        label, key = _iso_week_bucket(v.get("visit_date") or "")
        row = weekly.setdefault(key, {"label": label, "sort": key, "visits": 0, "km": 0.0})
        row["visits"] += 1
        row["km"] += km

    # Events attended, using event.km already stored on each event.
    events = await db.events.find({
        "tm_user_id": tm_user_id,
        "status": {"$ne": "Cancelled"},
        "scheduled_at": {"$gte": m_from, "$lte": f"{m_to}T23:59:59"},
    }, {"_id": 0, "scheduled_at": 1, "km": 1}).to_list(500)
    for e in events:
        km = float(e.get("km") or 0.0)
        if km <= 0:
            continue
        label, key = _iso_week_bucket((e.get("scheduled_at") or "")[:10])
        row = weekly.setdefault(key, {"label": label, "sort": key, "visits": 0, "km": 0.0})
        row["km"] += km

    return sorted(
        [{"week": r["label"], "visits": r["visits"], "km": round(r["km"], 2)} for r in weekly.values()],
        key=lambda x: x["week"],
    )


def _register_pdf_font():
    """Register a Cyrillic-capable TTF font so Bulgarian text renders
    properly (was showing as black squares with the default Helvetica)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os as _os

    # LiberationSans is bundled on all our images; DejaVuSans is a fallback.
    candidates = [
        ("FMSans", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ("FMSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    bold_candidates = [
        ("FMSans-Bold", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("FMSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    reg_name = None
    for name, path in candidates:
        if _os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                reg_name = name
                break
            except Exception:
                pass
    bold_name = None
    for name, path in bold_candidates:
        if _os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                bold_name = name
                break
            except Exception:
                pass
    return reg_name, bold_name


def _render_reimbursement_pdf(report: dict, weekly: list[dict] | None = None) -> bytes:
    import io as _io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfbase.pdfmetrics import registerFontFamily

    font_regular, font_bold = _register_pdf_font()
    body_font = font_regular or "Helvetica"
    bold_font = font_bold or "Helvetica-Bold"
    if font_regular and font_bold:
        registerFontFamily(font_regular, normal=font_regular, bold=font_bold)

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName=bold_font, fontSize=18, textColor=colors.HexColor("#1a3d2f"), spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=bold_font, fontSize=12, textColor=colors.HexColor("#1a3d2f"), spaceBefore=8, spaceAfter=4)
    small = ParagraphStyle("small", parent=styles["Normal"], fontName=body_font, fontSize=8, textColor=colors.grey)
    body = ParagraphStyle("body", parent=styles["Normal"], fontName=body_font, fontSize=10, leading=13)

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
    m.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), body_font),
                           ("FONTSIZE", (0, 0), (-1, -1), 9),
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
    tt.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), body_font),
                            ("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("FONTNAME", (2, -1), (3, -1), bold_font),
                            ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#d9d6cf")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e6e2da"))]))
    story.append(tt)

    # Weekly KM summary (replaces the doctor breakdown — user prefers a
    # rollup view for the exported PDF).
    if weekly:
        story.append(Paragraph("Weekly KM breakdown", h2))
        w_hdr = ["Week", "Visits", "KM"]
        w_rows = [w_hdr]
        wk_total = 0.0
        for w in weekly:
            w_rows.append([w["week"], str(w.get("visits", 0)), f"{w['km']:.1f}"])
            wk_total += float(w.get("km", 0))
        w_rows.append(["Total", "", f"{wk_total:.1f}"])
        wt = Table(w_rows, colWidths=[95*mm, 30*mm, 45*mm])
        wt.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), body_font),
                                ("FONTSIZE", (0, 0), (-1, -1), 9),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f2ee")),
                                ("FONTNAME", (0, -1), (-1, -1), bold_font),
                                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f4f2ee")),
                                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#d9d6cf")),
                                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e6e2da"))]))
        story.append(wt)

    exps = report.get("expenses", []) or []
    if exps:
        story.append(Paragraph("Expenses", h2))
        e_hdr = ["Category", "Vendor", "Date", "Amount", "Receipt"]
        e_rows = [e_hdr]
        for e in exps:
            e_rows.append([e.get("category") or "—",
                           e.get("vendor") or "—",
                           (e.get("expense_date") or "—")[:10],
                           _eur(e.get("amount")),
                           "Yes" if e.get("receipt_image_id") else ("Exception" if e.get("exception_approved") else "MISSING")])
        et = Table(e_rows, colWidths=[25*mm, 55*mm, 25*mm, 30*mm, 30*mm])
        et.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), body_font),
                                ("FONTSIZE", (0, 0), (-1, -1), 8),
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
