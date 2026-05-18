"""Phase C — Company management routes.

- `GET  /api/companies/mine`     — any authenticated user; returns their own company profile.
- `GET  /api/companies`          — Owner only; lists every company.
- `POST /api/companies`          — Owner only; create a new company.
- `PUT  /api/companies/{id}`     — Owner only (or Admin editing their OWN company,
                                   restricted to non-structural fields).
- `POST /api/companies/{id}/deactivate` — Owner only; flips active_status to Inactive.
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime, timezone

from fastapi import Depends, HTTPException

from server import (
    api,
    db,
    get_current_user,
    require_roles,
    _audit,
    _now_iso,
    _company_id_for,
    ENFORCE_COMPANY_ISOLATION,
)
from models import Company, CompanyCreate, CompanyUpdate, DEFAULT_COMPANY


def _strip(d):
    if d and "_id" in d:
        d.pop("_id", None)
    return d


# ---------- READ ----------
@api.get("/companies/mine")
async def get_my_company(user=Depends(get_current_user)):
    """Every authenticated user can see their OWN company profile."""
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(status_code=404, detail="No company assigned")
    c = await db.companies.find_one({"id": cid}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    return c


@api.get("/companies")
async def list_companies(user=Depends(require_roles("Owner"))):
    """Owner-only — list every company for support/admin purposes."""
    return await db.companies.find({}, {"_id": 0}).sort("company_name", 1).to_list(1000)


@api.get("/companies/{company_id}")
async def get_company(company_id: str, user=Depends(get_current_user)):
    """Any user can read their own company; Owner can read any."""
    if user.get("role") != "Owner" and user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Cross-company read forbidden")
    c = await db.companies.find_one({"id": company_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    return c


# ---------- WRITE (Owner only) ----------
@api.post("/companies")
async def create_company(body: CompanyCreate, user=Depends(require_roles("Owner"))):
    import uuid
    # Slug uniqueness (case-insensitive)
    slug = (body.slug or body.company_name.strip().lower().replace(" ", "-"))[:80]
    if await db.companies.find_one({"slug": slug}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=409, detail="Slug already in use")
    doc = body.model_dump()
    doc["id"] = uuid.uuid4().hex
    doc["slug"] = slug
    doc.setdefault("benchmark_opt_in", False)  # Phase C — never expose benchmarks yet
    doc["created_at"] = _now_iso()
    doc["updated_at"] = _now_iso()
    await db.companies.insert_one(doc)
    await _audit(user, "create", "company", doc["id"], new={"name": doc["company_name"]},
                 event_type="company_created")
    return _strip(doc)


@api.put("/companies/{company_id}")
async def update_company(company_id: str, body: CompanyUpdate, user=Depends(get_current_user)):
    """Owner: full edit on any company. Admin: limited edit on OWN company only."""
    role = user.get("role")
    if role == "Owner":
        pass
    elif role == "Admin":
        if user.get("company_id") != company_id:
            raise HTTPException(status_code=403, detail="Admin cannot edit other companies")
    else:
        raise HTTPException(status_code=403, detail="Forbidden")

    c = await db.companies.find_one({"id": company_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    # Non-Owner cannot toggle activation, slug, plan, or benchmark_opt_in.
    if role != "Owner":
        for forbidden in ("active_status", "slug", "plan", "benchmark_opt_in"):
            updates.pop(forbidden, None)
    if not updates:
        return c
    updates["updated_at"] = _now_iso()
    await db.companies.update_one({"id": company_id}, {"$set": updates})
    await _audit(user, "update", "company", company_id, prev=c, new=updates,
                 event_type="company_updated")
    return await db.companies.find_one({"id": company_id}, {"_id": 0})


@api.post("/companies/{company_id}/deactivate")
async def deactivate_company(company_id: str, user=Depends(require_roles("Owner"))):
    c = await db.companies.find_one({"id": company_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    if c.get("slug") == "default":
        raise HTTPException(status_code=400, detail="Cannot deactivate the default company")
    await db.companies.update_one(
        {"id": company_id},
        {"$set": {"active_status": "Inactive", "updated_at": _now_iso()}},
    )
    await _audit(user, "deactivate", "company", company_id, event_type="company_deactivated")
    return {"ok": True, "id": company_id, "active_status": "Inactive"}
