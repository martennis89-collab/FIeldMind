"""expenses routes — extracted from server.py during Phase C0 refactor.

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

logger = logging.getLogger(__name__)

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
    _managed_tm_ids_for,
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
from models import ExpenseUpdate


@api.post("/expenses")
async def create_expense(
    expense_date: str = Form(...),
    category: str = Form(...),
    amount: float = Form(...),
    vendor: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    reimbursement_report_id: Optional[str] = Form(None),
    receipt: Optional[UploadFile] = File(None),
    user=Depends(get_current_user),
):
    """Create an expense. Optional receipt upload stored in GridFS.

    Allowed roles: TM and SeniorTM (Phase L — Senior TMs log their own
    activity like a TM does, so they must also be able to file expenses).
    """
    if user["role"] not in ("TM", "SeniorTM"):
        raise HTTPException(status_code=403, detail="Only TMs can log expenses")
    if category not in ("Petrol", "Food", "Hotel", "Parking", "Tolls", "Other"):
        raise HTTPException(status_code=400, detail="category must be one of Petrol, Food, Hotel, Parking, Tolls, Other")
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
        "reimbursement_report_id": reimbursement_report_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _stamp_company(exp, user)
    await db.expenses.insert_one(exp)
    exp.pop("_id", None)
    await _audit(user, "create", "expense", exp["id"], new={"category": category, "amount": amount})
    return {"expense": exp, "duplicate_of": duplicate_of}

@api.post("/expenses/extract")
async def extract_expense_receipt(
    receipt: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """OCR a receipt (no DB write). Returns structured extraction + duplicate hint.

    Allowed roles: TM and SeniorTM.
    """
    if user["role"] not in ("TM", "SeniorTM"):
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
    personal: bool = False,
    user=Depends(get_current_user),
):
    """List expenses scoped by role.

    - TM: own expenses (any status). `month` filters by expense_date YYYY-MM.
    - SeniorTM: own + sub-team by default. Pass `?personal=true` to force only
      the caller's own rows (used by the "My expenses" panel).
    - Manager: team expenses, optionally filtered by tm_user_id and/or status.
    - Admin/Owner: all expenses (company-scoped).
    """
    q: dict = dict(_company_query_for(user))
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "SeniorTM":
        if personal:
            q["tm_user_id"] = user["id"]
        else:
            ids = await _managed_tm_ids_for(user) or [user["id"]]
            if tm_user_id:
                # SeniorTM can only drill into their own sub-team + self.
                if tm_user_id not in ids:
                    raise HTTPException(status_code=403, detail="TM not in your sub-team")
                q["tm_user_id"] = tm_user_id
            else:
                q["tm_user_id"] = {"$in": ids}
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
        if tm_user_id:
            q["tm_user_id"] = tm_user_id
    elif tm_user_id:
        q["tm_user_id"] = tm_user_id
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
    personal: bool = False,
    user=Depends(get_current_user),
):
    """Monthly totals + counts. Defaults to current month for TM.

    Manager/Admin may pass tm_user_id to scope to a single TM.
    SeniorTM: same as list_expenses — sub-team + own by default, `personal=true`
    filters to only the caller's own rows for the personal panel header.
    """
    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
    q: dict = {"expense_date": {"$gte": f"{month}-01", "$lte": f"{month}-31"}}
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "SeniorTM":
        if personal:
            q["tm_user_id"] = user["id"]
        else:
            ids = await _managed_tm_ids_for(user) or [user["id"]]
            q["tm_user_id"] = tm_user_id if tm_user_id and tm_user_id in ids else {"$in": ids}
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
    # `submittable_drafts` counts only the caller's OWN drafts — that's what the
    # "Submit month" button acts on for a SeniorTM's personal view.
    caller_id = user["id"]
    submittable = sum(1 for r in rows if r.get("status") == "Draft" and r.get("tm_user_id") == caller_id)
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
    if user["role"] in ("TM", "SeniorTM") and exp.get("tm_user_id") != user["id"]:
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
    # Phase L — SeniorTM also files personal expenses and needs to submit them.
    if user["role"] not in ("TM", "SeniorTM"):
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
    user=Depends(require_roles("Manager", "SeniorTM", "Admin", "Owner")),
):
    """Manager / SeniorTM / Admin view: per-TM totals + grand total for a
    given month.

    - Manager: scoped to their team_id.
    - SeniorTM (Phase L): scoped to sub-team + self via _managed_tm_ids_for.
    - Admin / Owner: everything (company-scoped for Admin, no scope for Owner).
    """
    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
    q: dict = dict(_company_query_for(user))
    q["expense_date"] = {"$gte": f"{month}-01", "$lte": f"{month}-31"}
    if user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    elif user["role"] == "SeniorTM":
        ids = await _managed_tm_ids_for(user) or [user["id"]]
        q["tm_user_id"] = {"$in": ids}
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
    personal: bool = False,
    user=Depends(get_current_user),
):
    """Download a ZIP of PDF reports — one PDF per expense — for the filtered set.

    Role scoping:
      - TM: always their OWN expenses (`personal` is implicit).
      - SeniorTM: sub-team + self by default; `personal=true` filters to own.
      - Manager: their team_id.
      - Admin / Owner: everything (Admin company-scoped).

    Each PDF contains expense metadata + the original phone-camera receipt
    image embedded on the same page. The response is STREAMED so the client
    starts receiving headers before the whole batch is composed — important
    for teams with many expenses on the production ingress (30s default
    timeout would kill a big buffered response).
    """
    import io as _io
    import zipfile
    from bson import ObjectId
    from motor.motor_asyncio import AsyncIOMotorGridFSBucket
    from fastapi.responses import StreamingResponse

    q: dict = dict(_company_query_for(user))
    if user["role"] == "TM":
        q["tm_user_id"] = user["id"]
    elif user["role"] == "SeniorTM":
        if personal:
            q["tm_user_id"] = user["id"]
        else:
            ids = await _managed_tm_ids_for(user) or [user["id"]]
            if tm_user_id and tm_user_id not in ids:
                raise HTTPException(status_code=403, detail="TM not in your sub-team")
            q["tm_user_id"] = {"$in": ids} if not tm_user_id else tm_user_id
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
        if tm_user_id:
            q["tm_user_id"] = tm_user_id
    elif tm_user_id:
        q["tm_user_id"] = tm_user_id

    if month:
        q["expense_date"] = {"$gte": f"{month}-01", "$lte": f"{month}-31"}
    if status:
        q["status"] = status

    rows = await db.expenses.find(q, {"_id": 0}).sort([("tm_name", 1), ("expense_date", -1)]).to_list(5000)
    if not rows:
        raise HTTPException(status_code=404, detail="No expenses to export")

    bucket = AsyncIOMotorGridFSBucket(db, bucket_name="receipts")
    # Build the ZIP into an in-memory buffer, but hand it back to the client
    # via StreamingResponse so the browser reliably receives the bytes even
    # for large batches. We still gather image bytes async for maximum speed.
    buf = _io.BytesIO()
    used = set()
    receipts_with_image = 0
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            image_bytes = None
            image_mime = (r.get("receipt_mime") or "image/jpeg").lower()
            if r.get("receipt_image_id"):
                try:
                    stream = await bucket.open_download_stream(ObjectId(r["receipt_image_id"]))
                    image_bytes = await stream.read()
                    receipts_with_image += 1
                except Exception:
                    image_bytes = None
            try:
                pdf_bytes = _build_expense_pdf(r, image_bytes, image_mime)
            except Exception as e:  # never let one bad row abort the whole ZIP
                logger.exception("PDF build failed for expense %s: %s", r.get("id"), e)
                continue

            tm = (r.get("tm_name") or "tm").replace(" ", "_").replace("/", "_")
            vendor = (r.get("vendor") or r.get("category") or "expense").replace(" ", "_").replace("/", "_")
            base = f"{tm}/{r.get('expense_date','')}_{vendor}_{r['id'][:8]}.pdf"
            name = base
            i = 2
            while name in used:
                name = base.rsplit(".", 1)[0] + f"-{i}.pdf"
                i += 1
            used.add(name)
            zf.writestr(name, pdf_bytes)

    payload = buf.getvalue()
    label = month or "all"
    if tm_user_id:
        label += f"_{tm_user_id[:8]}"
    fname = f"expense-report_{label}.zip"
    await _audit(
        user, "export", "expense_report", label,
        new={"count": len(rows), "with_receipt_image": receipts_with_image, "month": month, "personal": bool(personal)},
    )

    def _iter():
        # Chunked so the client sees traffic quickly on large payloads.
        chunk = 65536
        for start in range(0, len(payload), chunk):
            yield payload[start:start + chunk]

    return StreamingResponse(
        _iter(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Content-Length": str(len(payload)),
        },
    )


def _build_expense_pdf(exp: dict, image_bytes: Optional[bytes], image_mime: str) -> bytes:
    """Render a single expense as a self-contained one-page PDF.

    Layout:
      - Header: "FieldMind — Expense Report"
      - Metadata table: date, category, amount, vendor, status, TM, notes
      - Original receipt image (from the TM's phone camera) if present.
    """
    import io as _io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=6, textColor=colors.HexColor("#1a3d2f"))
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=colors.grey)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=14)

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Expense {exp.get('id','')[:8]}",
    )

    story = []
    story.append(Paragraph("FieldMind — Expense Report", h1))
    story.append(Paragraph(
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"Expense id <b>{exp.get('id','')}</b>",
        small,
    ))
    story.append(Spacer(1, 6 * mm))

    def _fmt_money(amt, cur):
        try:
            return f"{float(amt or 0):,.2f} {cur or 'EUR'}"
        except Exception:
            return f"{amt} {cur or 'EUR'}"

    meta_rows = [
        ["Territory Manager", exp.get("tm_name") or "—"],
        ["Expense date", exp.get("expense_date") or "—"],
        ["Category", exp.get("category") or "—"],
        ["Vendor", exp.get("vendor") or "—"],
        ["Amount", _fmt_money(exp.get("amount"), exp.get("currency"))],
        ["Status", exp.get("status") or "—"],
        ["Submission month", exp.get("submission_month") or "—"],
        ["Submitted at", (exp.get("submitted_at") or "—")[:19].replace("T", " ")],
        ["Notes", exp.get("notes") or "—"],
    ]
    tbl = Table(meta_rows, colWidths=[45 * mm, 130 * mm])
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f4f2ee")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1a3d2f")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d6cf")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e6e2da")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8 * mm))

    # Embed the phone-camera receipt image if we have one.
    # Two-layer resilience:
    #   1. Pre-validate with PIL.verify() so obviously corrupt bytes are
    #      dropped BEFORE we hand them to reportlab.
    #   2. If doc.build() still fails (e.g. reportlab-specific parser edge
    #      cases PIL missed), re-build the PDF WITHOUT the image so a single
    #      unreadable receipt can't 500 the whole team's monthly ZIP.
    safe_image_bytes = None
    if image_bytes:
        try:
            from PIL import Image as _PILImage  # lazy — reportlab already imports Pillow
            _PILImage.open(_io.BytesIO(image_bytes)).verify()
            safe_image_bytes = image_bytes
        except Exception:
            safe_image_bytes = None

    if safe_image_bytes:
        try:
            story.append(Paragraph("Receipt (original phone-camera image)", body))
            story.append(Spacer(1, 3 * mm))
            img_buf = _io.BytesIO(safe_image_bytes)
            # Cap width to page usable width, let reportlab scale height.
            img = Image(img_buf)
            page_w = A4[0] - 30 * mm  # left+right margin
            page_h = A4[1] - 90 * mm  # top+bottom + header block
            iw, ih = img.wrap(0, 0)
            if iw <= 0 or ih <= 0:
                raise ValueError("Bad image dimensions")
            scale = min(page_w / iw, page_h / ih, 1.0)
            img.drawWidth = iw * scale
            img.drawHeight = ih * scale
            story.append(img)
        except Exception:
            # Malformed / unsupported image — swallow and note it in the PDF
            # so the report still renders for the rest of the batch.
            safe_image_bytes = None
            story = [s for s in story if not isinstance(s, Image)]
            story.append(Paragraph(
                f"<i>Receipt image could not be embedded (mime: {image_mime}).</i>",
                small,
            ))
    else:
        story.append(Paragraph("<i>No receipt image on file for this expense.</i>", small))

    try:
        doc.build(story)
    except Exception:
        # Belt-and-braces: if reportlab still can't render (extremely rare),
        # strip any lingering Image flowable and render the metadata-only PDF.
        buf = _io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=15 * mm, rightMargin=15 * mm,
            topMargin=15 * mm, bottomMargin=15 * mm,
            title=f"Expense {exp.get('id','')[:8]}",
        )
        fallback = [s for s in story if not isinstance(s, Image)]
        fallback.append(Paragraph(
            "<i>Receipt image could not be rendered by the PDF engine and was omitted.</i>",
            small,
        ))
        doc.build(fallback)
    return buf.getvalue()
