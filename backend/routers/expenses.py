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
from models import ExpenseUpdate


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
    q: dict = dict(_company_query_for(user))
    if user["role"] in ("TM", "SeniorTM"):
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
    if user["role"] in ("TM", "SeniorTM"):
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

    q: dict = dict(_company_query_for(user))
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
