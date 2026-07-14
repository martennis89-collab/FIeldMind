"""doctors routes — extracted from server.py during Phase C0 refactor.

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
from models import Doctor, DoctorCreate, DoctorUpdate, IteroStageUpdate
from _deps import normalize_person_name, normalize_city_key


async def _find_duplicate_doctor(company_id: str, name: str, city: str | None) -> dict | None:
    """Return the first same-company doctor whose name (title-stripped, accent-
    folded, lowercased) matches the given name. If both sides have a city,
    require that city to match as well. Returns None if no duplicate."""
    norm_name = normalize_person_name(name)
    norm_city = normalize_city_key(city)
    if not norm_name:
        return None
    # Load all doctors in the company (bounded by a generous cap). Company
    # doctor counts sit well under this in every real deployment.
    company_docs = await db.doctors.find(
        {"company_id": company_id},
        {"_id": 0, "id": 1, "doctor_name": 1, "city": 1, "assigned_tm_id": 1, "clinic_name": 1},
    ).to_list(10000)
    for existing in company_docs:
        if normalize_person_name(existing.get("doctor_name")) != norm_name:
            continue
        ec = normalize_city_key(existing.get("city"))
        # Match if either side has no city, or cities agree.
        if not norm_city or not ec or norm_city == ec:
            return existing
    return None


@api.get("/doctors")
async def list_doctors(
    segment: Optional[str] = None,
    city: Optional[str] = None,
    cadence: Optional[str] = None,
    sentiment: Optional[str] = None,
    assigned_tm_id: Optional[str] = None,
    growth_program: Optional[bool] = None,
    q: Optional[str] = None,
    user=Depends(get_current_user),
):
    base = await _doctor_query_for(user)
    if segment:
        base["segment"] = segment
    if city:
        base["city"] = city
    if assigned_tm_id and user["role"] in ("Admin", "Manager", "SeniorTM"):
        base["assigned_tm_id"] = assigned_tm_id
    if growth_program is not None:
        base["in_growth_program"] = growth_program
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
async def create_doctor(body: DoctorCreate, user=Depends(require_roles("Admin", "Manager", "SeniorTM", "TM"))):
    doc = Doctor(**body.model_dump()).model_dump()
    if user["role"] in ("TM", "SeniorTM"):
        # TM (and SeniorTM in their TM-hybrid capacity) creates a doctor for themselves
        doc["assigned_tm_id"] = user["id"]
        doc["team_id"] = user.get("team_id")
    elif user["role"] in ("Manager", "SeniorTM") and not doc.get("team_id"):
        doc["team_id"] = user.get("team_id")
    _stamp_company(doc, user)

    # Duplicate guard — title-agnostic, accent-folded, case-insensitive.
    dup = await _find_duplicate_doctor(doc["company_id"], doc.get("doctor_name") or "", doc.get("city"))
    if dup:
        # Enrich the response so the UI can offer "Open existing" instead of a
        # dead-end error toast.
        assigned_hint = ""
        if dup.get("assigned_tm_id") and dup["assigned_tm_id"] != user["id"]:
            owner = await db.users.find_one({"id": dup["assigned_tm_id"]}, {"_id": 0, "name": 1, "email": 1})
            if owner:
                assigned_hint = f" It's currently in {owner.get('name') or owner.get('email')}'s book."
        raise HTTPException(status_code=409, detail={
            "code": "DUPLICATE_DOCTOR",
            "message": (
                f"A doctor named \"{dup['doctor_name']}\" already exists in your company"
                + (f" in {dup['city']}" if dup.get("city") else "")
                + "."
                + assigned_hint
            ),
            "existing_id": dup["id"],
            "existing_name": dup["doctor_name"],
            "existing_city": dup.get("city"),
            "existing_clinic_name": dup.get("clinic_name"),
            "existing_assigned_tm_id": dup.get("assigned_tm_id"),
        })

    # Persist the normalized key so future lookups can skip the full scan when
    # the collection grows. Older documents will be backfilled lazily by the
    # same dedupe path.
    doc["name_normalized"] = normalize_person_name(doc.get("doctor_name") or "")
    await db.doctors.insert_one(doc)
    await _audit(user, "create", "doctor", doc["id"], new={"doctor_name": doc["doctor_name"]})
    _strip_id(doc)
    return await _enrich_doctor(doc)

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
async def preview_doctor_import(file: UploadFile = File(...), user=Depends(require_roles("Admin", "SeniorTM", "TM"))):
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
async def commit_doctor_import(body: dict, user=Depends(require_roles("Admin", "SeniorTM", "TM"))):
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
    if user["role"] in ("TM", "SeniorTM"):
        assigned_tm_id = user["id"]
    elif user["role"] == "Admin":
        if not assigned_tm_id:
            raise HTTPException(status_code=400, detail="assigned_tm_id is required for Admin imports")

    target_user = await db.users.find_one({"id": assigned_tm_id, "role": {"$in": ["TM", "SeniorTM"]}}, {"_id": 0})
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
        # Title-agnostic, accent-folded — must match POST /doctors dedupe.
        return f"{normalize_person_name(name)}|{normalize_city_key(city)}"

    def key2(clinic, city):
        return f"{(clinic or '').strip().lower()}|{normalize_city_key(city)}"

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
            "name_normalized": normalize_person_name(p["doctor_name"]),
            "created_at": now,
            "updated_at": now,
        }
        _stamp_company(new_doc, user)
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
    _stamp_company(summary, user)
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
async def update_doctor(doctor_id: str, body: DoctorUpdate, user=Depends(require_roles("Admin", "Manager", "SeniorTM", "TM"))):
    existing = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not existing or not await _can_access_doctor(user, existing):
        raise HTTPException(status_code=404, detail="Doctor not found")
    if user["role"] in ("TM", "SeniorTM"):
        # TM/SeniorTM may only update general_notes / status / growth-programme flag
        allowed = {k: v for k, v in body.model_dump(exclude_none=True).items() if k in ("general_notes", "status", "in_growth_program")}
        update = allowed
    else:
        update = body.model_dump(exclude_none=True)
    update["updated_at"] = _now_iso()
    await db.doctors.update_one({"id": doctor_id}, {"$set": update})
    new = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    await _audit(user, "update", "doctor", doctor_id, prev=existing, new=new)
    return await _enrich_doctor(new)

@api.delete("/doctors/{doctor_id}")
async def delete_doctor(doctor_id: str, user=Depends(require_roles("Admin", "SeniorTM", "TM"))):
    existing = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Doctor not found")
    # TM/SeniorTM can only delete doctors assigned to them
    if user["role"] in ("TM", "SeniorTM") and existing.get("assigned_tm_id") != user["id"]:
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
async def bulk_delete_doctors(body: dict, user=Depends(require_roles("Admin", "SeniorTM", "TM"))):
    """Delete multiple doctors in one go. TM can only delete doctors assigned to them."""
    ids = (body or {}).get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids must be a non-empty list")
    if len(ids) > 1000:
        raise HTTPException(status_code=400, detail="Too many ids (max 1000)")
    q = {"id": {"$in": ids}}
    if user["role"] in ("TM", "SeniorTM"):
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

@api.post("/doctors/{doctor_id}/itero-stage")
async def set_itero_stage(doctor_id: str, body: IteroStageUpdate, user=Depends(get_current_user)):
    doc = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doc or not await _can_access_doctor(user, doc):
        raise HTTPException(status_code=404, detail="Doctor not found")
    if user["role"] not in ("TM", "SeniorTM", "Manager", "Admin", "Owner"):
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
        "company_id": _company_id_for(user) or doc.get("company_id"),
    })
    await _audit(user, "stage_change", "doctor", doctor_id,
                 prev={"itero_stage": current}, new={"itero_stage": body.stage, "note": body.note})
    return {"ok": True, "doctor_id": doctor_id, "from_stage": current, "to_stage": body.stage}

@api.get("/doctors/{doctor_id}/itero-stage-history")
async def itero_stage_history(doctor_id: str, user=Depends(get_current_user)):
    doc = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doc or not await _can_access_doctor(user, doc):
        raise HTTPException(status_code=404, detail="Doctor not found")
    rows = await db.itero_stage_history.find({"doctor_id": doctor_id}, {"_id": 0}).sort("at", -1).to_list(200)
    return rows

@api.post("/doctors/{doctor_id}/itero/quick-complete-demo")
async def quick_complete_demo_for_doctor(doctor_id: str, user=Depends(get_current_user)):
    """One-tap "Mark demo done" from the iTero pipeline column.
    Strategy:
      1. If the doctor has any open (Scheduled) demo meeting -> complete the most recent one
         (this fires the existing /complete-demo flow: visit + pipeline auto-advance).
      2. If no open demo meeting but doctor has any non-cancelled non-completed demo meeting,
         complete that one.
      3. Otherwise, just bump the iTero stage to "Demo Completed" via /itero_stage so the
         pipeline still moves forward (no synthetic visit/meeting created).
    """
    doc = await db.doctors.find_one({"id": doctor_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found")
    if user["role"] in ("TM", "SeniorTM") and doc.get("assigned_tm_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if user["role"] == "Manager" and doc.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")

    # Look for a non-completed, non-cancelled demo meeting
    candidate = await db.meetings.find_one(
        {"doctor_id": doctor_id, "is_demo": True, "status": {"$nin": ["Completed", "Cancelled"]}},
        {"_id": 0},
        sort=[("scheduled_at", -1)],
    )
    if candidate:
        from routers.meetings import complete_demo_meeting, CompleteDemoBody
        result = await complete_demo_meeting(
            candidate["id"],
            CompleteDemoBody(interest_level="Medium", outcome_note=None),
            user,
        )
        return {**result, "via": "meeting"}

    # No meeting → just advance the stage
    new_stage = "Demo Completed"
    if doc.get("itero_stage") == new_stage:
        raise HTTPException(status_code=400, detail="Doctor is already in Demo Completed")
    await db.doctors.update_one(
        {"id": doctor_id},
        {"$set": {"itero_stage": new_stage, "updated_at": _now_iso()}},
    )
    # Record the stage change in history (matches the manual move flow)
    await db.itero_stage_history.insert_one({
        "id": str(uuid.uuid4()),
        "doctor_id": doctor_id,
        "old_stage": doc.get("itero_stage"),
        "new_stage": new_stage,
        "changed_by": user["id"],
        "changed_at": _now_iso(),
        "note": "Quick-complete demo (no booked demo meeting)",
        "company_id": _company_id_for(user) or doc.get("company_id"),
    })
    await _audit(user, "quick_complete_demo", "doctor", doctor_id,
                 new={"itero_stage": new_stage, "from_stage": doc.get("itero_stage")})
    return {"ok": True, "doctor_id": doctor_id, "via": "stage_only", "itero_stage": new_stage}
