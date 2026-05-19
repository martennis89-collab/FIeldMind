"""Phase G — Benchmark Cohort infrastructure + privacy guardrails.

Phase G is INFRASTRUCTURE + PRIVACY ONLY. No external benchmark UI.
No company-vs-company values are EVER returned to non-Owner callers.

Privacy guarantees enforced here:
  • Only metrics whose `MetricDefinition.benchmark_eligible == True` can be aggregated.
  • Only companies with `benchmark_opt_in == True` AND `active_status == "Active"` contribute.
  • A cohort below `minimum_company_count` returns `benchmark_available: False` with a reason.
  • Aggregated payloads contain only `company_count` / `sample_size` / percentile stats —
    NEVER company names, TM names, doctor names, raw notes, pricing, revenue, or any PII.
  • A safe `/api/benchmark/status` endpoint returns eligibility + availability only — no values.
"""
from __future__ import annotations
from typing import Optional
from statistics import median

from metrics.registry import V1_METRICS, metric_by_slug


# ---------- Cohort-matching fields (these are the ONLY company fields we use) ----------
COHORT_FIELDS = (
    "industry", "country", "region", "market",
    "team_size_category", "sales_motion", "account_type",
)


def _safe_benchmark_metric(metric_slug: str) -> bool:
    """Allow-list gate. Only V1 metrics flagged benchmark_eligible can ever be aggregated.
    Anything that could leak operator behaviour or business volume (e.g. weekly_report_submission_rate
    which is a discipline signal, or the FEI composite) is intentionally excluded."""
    m = metric_by_slug(metric_slug)
    return bool(m and m.benchmark_eligible)


def _benchmark_company_eligible(company: dict) -> bool:
    """A company contributes to a cohort only if it has opted in AND is active.
    `benchmark_opt_in=False` companies are filtered out at EVERY level (count, aggregate, status)."""
    if not company:
        return False
    if not company.get("benchmark_opt_in", False):
        return False
    if company.get("active_status") != "Active":
        return False
    return True


def _cohort_match_query(cohort: dict) -> dict:
    """Build the Mongo query that matches companies for this cohort.
    Only NON-NULL cohort fields are required; a `None` field means "any value matches"."""
    q: dict = {"benchmark_opt_in": True, "active_status": "Active"}
    for f in COHORT_FIELDS:
        v = cohort.get(f)
        if v is not None:
            q[f] = v
    return q


async def _cohort_company_count(db, cohort: dict) -> int:
    """Count how many opted-in active companies match this cohort's criteria.
    Used to gate `benchmark_available`."""
    return await db.companies.count_documents(_cohort_match_query(cohort))


async def _refresh_cohort_counts(db, cohort_id: str) -> dict:
    """Recompute `current_company_count` + `benchmark_available` for ONE cohort.
    Idempotent. Returns the updated cohort doc."""
    cohort = await db.benchmark_cohorts.find_one({"id": cohort_id}, {"_id": 0})
    if not cohort:
        return {}
    count = await _cohort_company_count(db, cohort)
    minimum = int(cohort.get("minimum_company_count", 10))
    available = (count >= minimum) and (cohort.get("active_status") == "Active")
    from server import _now_iso
    await db.benchmark_cohorts.update_one(
        {"id": cohort_id},
        {"$set": {
            "current_company_count": count,
            "benchmark_available": bool(available),
            "updated_at": _now_iso(),
        }},
    )
    return await db.benchmark_cohorts.find_one({"id": cohort_id}, {"_id": 0})


def _assert_benchmark_available(cohort: dict) -> Optional[str]:
    """Return None if the cohort meets all privacy + sample thresholds; else a reason string."""
    if not cohort:
        return "Cohort not found."
    if cohort.get("active_status") != "Active":
        return "Cohort is inactive."
    minimum = int(cohort.get("minimum_company_count", 10))
    count = int(cohort.get("current_company_count", 0))
    if count < minimum:
        return f"Not enough anonymized companies in cohort yet ({count}/{minimum})."
    return None


# ---------- Anonymous aggregate ----------
async def _aggregate_metric(db, cohort: dict, metric_slug: str,
                            period_days: int = 30) -> Optional[dict]:
    """Compute an anonymized statistical aggregate for one metric across the cohort.

    Returns None if:
      • metric is not benchmark_eligible
      • cohort is too small
      • cohort is inactive

    Returns a payload that contains ONLY: company_count, sample_size, median, average,
    percentile_25, percentile_75, top_quartile_threshold, bottom_quartile_threshold,
    period_start, period_end. **Never company / TM / doctor / pricing data.**
    """
    if not _safe_benchmark_metric(metric_slug):
        return None
    reason = _assert_benchmark_available(cohort)
    if reason:
        return None

    # Identify matching companies (opted-in + active + cohort-field match).
    company_ids = await db.companies.distinct("id", _cohort_match_query(cohort))
    if not company_ids:
        return None

    # Use stored metric_snapshots from Phase D. Aggregate per-company medians so a single
    # noisy TM cannot dominate. The snapshot already excludes PII by construction
    # (it only stores numerator/denominator/value/scope_id/company_id).
    from datetime import datetime, timezone, timedelta
    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(days=period_days)

    # Pull every snapshot for these companies in the period.
    q = {
        "slug": metric_slug,
        "company_id": {"$in": company_ids},
        "sufficient_data": True,
        "value": {"$ne": None},
        "computed_at": {"$gte": period_start.isoformat()},
    }
    rows = await db.metric_snapshots.find(q, {
        "_id": 0, "company_id": 1, "value": 1,
    }).to_list(50000)
    if not rows:
        return None

    # Per-company median to anonymize within-company variance.
    by_company: dict[str, list[float]] = {}
    for r in rows:
        by_company.setdefault(r["company_id"], []).append(float(r["value"]))
    company_values = [median(vs) for vs in by_company.values() if vs]
    company_count = len(company_values)
    if company_count < int(cohort.get("minimum_company_count", 10)):
        # Even when the cohort is technically eligible, if too few companies have
        # snapshots for THIS metric we still suppress.
        return None

    sorted_vals = sorted(company_values)
    n = len(sorted_vals)

    def _pct(p: float) -> float:
        if n == 0:
            return 0.0
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        if f == c:
            return sorted_vals[f]
        return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)

    avg = sum(sorted_vals) / n
    med = _pct(0.5)
    p25 = _pct(0.25)
    p75 = _pct(0.75)
    return {
        "metric_slug": metric_slug,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "company_count": company_count,
        "sample_size": len(rows),
        "median": round(med, 4),
        "average": round(avg, 4),
        "percentile_25": round(p25, 4),
        "percentile_75": round(p75, 4),
        "top_quartile_threshold": round(p75, 4),
        "bottom_quartile_threshold": round(p25, 4),
    }
