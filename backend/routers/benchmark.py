"""Phase G — Benchmark Cohort routes.

Endpoints (Owner-only for cohort management):
  • `GET  /api/benchmark/cohorts`              — Owner: list every cohort.
  • `POST /api/benchmark/cohorts`              — Owner: create.
  • `PUT  /api/benchmark/cohorts/{id}`         — Owner: edit.
  • `POST /api/benchmark/cohorts/{id}/refresh` — Owner: recompute counts.
  • `GET  /api/benchmark/cohorts/{id}/status`  — Owner: cohort-level eligibility status.
  • `GET  /api/benchmark/status`               — ANY authenticated user: SAFE company status
                                                  (opt-in / matched cohort count / availability).
                                                  Returns NO benchmark values.

What is NOT exposed in Phase G:
  • No public benchmark comparison endpoint.
  • No values surfaced to non-Owner roles.
  • No company / TM / doctor / pricing / revenue / raw-note data in any payload.
"""
from __future__ import annotations
from typing import Optional
import uuid

from fastapi import Depends, HTTPException

from server import (
    api,
    db,
    get_current_user,
    require_roles,
    _audit,
    _now_iso,
)
from models import BenchmarkCohort, BenchmarkCohortCreate, BenchmarkCohortUpdate
from metrics.benchmark import (
    COHORT_FIELDS,
    _cohort_match_query,
    _refresh_cohort_counts,
    _benchmark_company_eligible,
    _safe_benchmark_metric,
)
from metrics.registry import V1_METRICS


def _strip(d):
    if d and "_id" in d:
        d.pop("_id", None)
    return d


# ============================================================
# Cohort management — Owner only
# ============================================================
@api.get("/benchmark/cohorts")
async def list_cohorts(user=Depends(require_roles("Owner"))):
    rows = await db.benchmark_cohorts.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return rows


@api.post("/benchmark/cohorts")
async def create_cohort(body: BenchmarkCohortCreate, user=Depends(require_roles("Owner"))):
    doc = body.model_dump()
    doc["id"] = uuid.uuid4().hex
    doc["current_company_count"] = 0
    doc["benchmark_available"] = False
    doc["created_at"] = _now_iso()
    doc["updated_at"] = _now_iso()
    if doc["minimum_company_count"] < 1:
        raise HTTPException(status_code=400, detail="minimum_company_count must be >= 1")
    await db.benchmark_cohorts.insert_one(doc)
    refreshed = await _refresh_cohort_counts(db, doc["id"])
    await _audit(user, "create", "benchmark_cohort", doc["id"],
                 new={"name": doc["cohort_name"]}, event_type="cohort_created")
    return _strip(refreshed)


@api.put("/benchmark/cohorts/{cohort_id}")
async def update_cohort(cohort_id: str, body: BenchmarkCohortUpdate,
                        user=Depends(require_roles("Owner"))):
    cohort = await db.benchmark_cohorts.find_one({"id": cohort_id}, {"_id": 0})
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "minimum_company_count" in updates and updates["minimum_company_count"] < 1:
        raise HTTPException(status_code=400, detail="minimum_company_count must be >= 1")
    updates["updated_at"] = _now_iso()
    await db.benchmark_cohorts.update_one({"id": cohort_id}, {"$set": updates})
    await _refresh_cohort_counts(db, cohort_id)
    await _audit(user, "update", "benchmark_cohort", cohort_id,
                 prev=cohort, new=updates, event_type="cohort_updated")
    return await db.benchmark_cohorts.find_one({"id": cohort_id}, {"_id": 0})


@api.post("/benchmark/cohorts/{cohort_id}/refresh")
async def refresh_cohort(cohort_id: str, user=Depends(require_roles("Owner"))):
    cohort = await _refresh_cohort_counts(db, cohort_id)
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")
    return cohort


@api.get("/benchmark/cohorts/{cohort_id}/status")
async def cohort_status(cohort_id: str, user=Depends(require_roles("Owner"))):
    """Owner-only status for ONE cohort. Returns count + availability + criteria —
    NO benchmark values, NO company names."""
    cohort = await db.benchmark_cohorts.find_one({"id": cohort_id}, {"_id": 0})
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")
    return {
        "cohort_id": cohort["id"],
        "cohort_name": cohort["cohort_name"],
        "active_status": cohort["active_status"],
        "current_company_count": cohort.get("current_company_count", 0),
        "minimum_company_count": cohort.get("minimum_company_count", 10),
        "benchmark_available": bool(cohort.get("benchmark_available", False)),
        "criteria": {f: cohort.get(f) for f in COHORT_FIELDS},
    }


# ============================================================
# Safe per-company status — ANY authenticated user
# ============================================================
@api.get("/benchmark/status")
async def benchmark_status(user=Depends(get_current_user)):
    """Phase G safe per-company benchmark status — opt-in + matched cohort count + availability.
    **Returns no benchmark values.** No company names. No PII."""
    cid = user.get("company_id")
    company = await db.companies.find_one({"id": cid}, {"_id": 0}) if cid else None
    if not company:
        return {
            "company_benchmark_opt_in": False,
            "eligible_for_benchmarking": False,
            "matched_cohort_count": 0,
            "benchmark_available": False,
            "reason_if_unavailable": "Company not found.",
        }

    opt_in = bool(company.get("benchmark_opt_in", False))
    active = company.get("active_status") == "Active"

    if not opt_in:
        return {
            "company_benchmark_opt_in": False,
            "eligible_for_benchmarking": False,
            "matched_cohort_count": 0,
            "benchmark_available": False,
            "reason_if_unavailable": "Company has not opted in.",
        }
    if not active:
        return {
            "company_benchmark_opt_in": True,
            "eligible_for_benchmarking": False,
            "matched_cohort_count": 0,
            "benchmark_available": False,
            "reason_if_unavailable": "Company is not active.",
        }

    # Find cohorts whose match query includes THIS company.
    # We re-evaluate by counting cohorts where every non-null criterion equals the company's value.
    matched_cohorts: list[dict] = []
    async for co in db.benchmark_cohorts.find({"active_status": "Active"}, {"_id": 0}):
        match = True
        for f in COHORT_FIELDS:
            crit = co.get(f)
            if crit is not None and company.get(f) != crit:
                match = False
                break
        if match:
            matched_cohorts.append(co)

    if not matched_cohorts:
        return {
            "company_benchmark_opt_in": True,
            "eligible_for_benchmarking": True,
            "matched_cohort_count": 0,
            "benchmark_available": False,
            "reason_if_unavailable": "No active cohorts match this company yet.",
        }

    # Is ANY matched cohort already available (i.e. has ≥ minimum companies)?
    any_available = any(c.get("benchmark_available") for c in matched_cohorts)

    # Eligibility additionally requires at least one safe metric snapshot for THIS company.
    has_eligible_metric_snapshot = await db.metric_snapshots.find_one(
        {
            "company_id": cid,
            "sufficient_data": True,
            "slug": {"$in": [m.slug for m in V1_METRICS if m.benchmark_eligible]},
        },
        {"_id": 0, "id": 1},
    )
    if not has_eligible_metric_snapshot:
        return {
            "company_benchmark_opt_in": True,
            "eligible_for_benchmarking": False,
            "matched_cohort_count": len(matched_cohorts),
            "benchmark_available": False,
            "reason_if_unavailable": "No eligible metric snapshots yet.",
        }

    if not any_available:
        # Pick the closest cohort by current_company_count for the reason message.
        biggest = max(matched_cohorts, key=lambda c: c.get("current_company_count", 0))
        return {
            "company_benchmark_opt_in": True,
            "eligible_for_benchmarking": True,
            "matched_cohort_count": len(matched_cohorts),
            "benchmark_available": False,
            "reason_if_unavailable": (
                f"Not enough anonymized companies in cohort yet "
                f"({biggest.get('current_company_count', 0)}/{biggest.get('minimum_company_count', 10)})."
            ),
        }

    return {
        "company_benchmark_opt_in": True,
        "eligible_for_benchmarking": True,
        "matched_cohort_count": len(matched_cohorts),
        "benchmark_available": True,
        "reason_if_unavailable": None,
    }
