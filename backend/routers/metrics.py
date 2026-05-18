"""Phase D — Metrics API.

  • `GET  /api/metrics/registry`            — list every metric definition
  • `GET  /api/metrics/tm/{tm_id}`          — compute all V1 metrics for a TM (live, not stored)
  • `GET  /api/metrics/tm/{tm_id}/fei`      — Field Execution Index for a TM
  • `GET  /api/metrics/me`                  — convenience for the calling TM
  • `GET  /api/metrics/me/fei`              — convenience for the calling TM
  • `POST /api/metrics/snapshots/run`       — Admin/Manager: persist a snapshot for one TM (or all team TMs)
  • `GET  /api/metrics/snapshots`           — list stored snapshots (RBAC + company-scoped)

RBAC:
  • TM: own data only.
  • Manager: own + team TMs.
  • Admin: own company.
  • Owner: any company.
"""
from __future__ import annotations
from typing import Optional, List
import uuid

from fastapi import Depends, HTTPException, Query

from server import (
    api,
    db,
    get_current_user,
    require_roles,
    _audit,
    _now_iso,
    _company_id_for,
    _company_query_for,
    _assert_same_company,
)

from metrics import (
    V1_METRICS,
    compute_all_for_tm,
    compute_metric_for_tm,
    compute_fei_for_tm,
    metric_by_slug,
)


async def _resolve_target_tm(target_id: str, user) -> dict:
    """Validate the caller is allowed to read metrics for `target_id`."""
    target = await db.users.find_one({"id": target_id}, {"_id": 0, "password_hash": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    _assert_same_company(user, target, code=404, detail="User not found")
    role = user.get("role")
    if role == "TM" and target["id"] != user["id"]:
        raise HTTPException(status_code=403, detail="TM may only read own metrics")
    if role == "Manager" and target.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Manager limited to team")
    return target


@api.get("/metrics/registry")
async def metrics_registry(user=Depends(get_current_user)):
    """Read-only registry of all V1 metrics."""
    return [m.model_dump() for m in V1_METRICS]


@api.get("/metrics/me")
async def my_metrics(window_days: Optional[int] = None, user=Depends(get_current_user)):
    rows = await compute_all_for_tm(db, user["id"], user.get("company_id"), window_days)
    return [r.to_doc() for r in rows]


@api.get("/metrics/me/fei")
async def my_fei(window_days: Optional[int] = None, user=Depends(get_current_user)):
    return await compute_fei_for_tm(db, user["id"], user.get("company_id"), window_days)


@api.get("/metrics/tm/{tm_id}")
async def tm_metrics(tm_id: str, window_days: Optional[int] = None, user=Depends(get_current_user)):
    target = await _resolve_target_tm(tm_id, user)
    rows = await compute_all_for_tm(db, target["id"], target.get("company_id"), window_days)
    return [r.to_doc() for r in rows]


@api.get("/metrics/tm/{tm_id}/{slug}")
async def tm_metric_single(tm_id: str, slug: str, window_days: Optional[int] = None,
                           user=Depends(get_current_user)):
    if not metric_by_slug(slug):
        raise HTTPException(status_code=404, detail=f"Unknown metric slug: {slug}")
    target = await _resolve_target_tm(tm_id, user)
    r = await compute_metric_for_tm(db, slug, target["id"], target.get("company_id"), window_days)
    return r.to_doc()


@api.get("/metrics/tm/{tm_id}/fei/summary")
async def tm_fei(tm_id: str, window_days: Optional[int] = None, user=Depends(get_current_user)):
    target = await _resolve_target_tm(tm_id, user)
    return await compute_fei_for_tm(db, target["id"], target.get("company_id"), window_days)


# ---------- Persisted snapshots ----------
@api.post("/metrics/snapshots/run")
async def run_snapshots(
    tm_id: Optional[str] = Query(None, description="If omitted: snapshot every TM in caller's company (Manager: only their team)."),
    user=Depends(require_roles("Manager", "Admin", "Owner")),
):
    """Persist a fresh snapshot for each metric (per TM) into `db.metric_snapshots`.
    Idempotent within the same minute (idempotency key = slug:scope_id:period_end[:16]).
    """
    targets: list[dict] = []
    if tm_id:
        targets.append(await _resolve_target_tm(tm_id, user))
    else:
        q = dict(_company_query_for(user))
        q["role"] = "TM"
        if user.get("role") == "Manager":
            q["team_id"] = user.get("team_id")
        async for u in db.users.find(q, {"_id": 0, "password_hash": 0}):
            targets.append(u)

    created = 0
    for t in targets:
        rows = await compute_all_for_tm(db, t["id"], t.get("company_id"))
        for r in rows:
            doc = r.to_doc(metric_id=uuid.uuid4().hex)
            idem = f"snap:{doc['slug']}:{doc['scope_id']}:{doc['period_end'][:16]}"
            doc["idempotency_key"] = idem
            existing = await db.metric_snapshots.find_one({"idempotency_key": idem}, {"_id": 0, "id": 1})
            if existing:
                continue
            await db.metric_snapshots.insert_one(doc)
            created += 1
    await _audit(user, "create", "metric_snapshot", f"batch:{created}", new={"created": created})
    return {"ok": True, "snapshots_created": created, "tms_processed": len(targets)}


@api.get("/metrics/snapshots")
async def list_snapshots(
    tm_id: Optional[str] = None,
    slug: Optional[str] = None,
    limit: int = 200,
    user=Depends(get_current_user),
):
    q = dict(_company_query_for(user))
    if tm_id:
        await _resolve_target_tm(tm_id, user)  # RBAC check
        q["scope_id"] = tm_id
    elif user.get("role") == "TM":
        q["scope_id"] = user["id"]
    elif user.get("role") == "Manager":
        # Only show snapshots for TMs in this manager's team
        tm_ids = await db.users.distinct("id", {"team_id": user.get("team_id"), "role": "TM"})
        q["scope_id"] = {"$in": tm_ids}
    if slug:
        q["slug"] = slug
    cursor = db.metric_snapshots.find(q, {"_id": 0}).sort("computed_at", -1).limit(limit)
    return await cursor.to_list(limit)
