"""Phase D — Metric computation engine.

Each metric is computed from REAL stored data:
  • event ledger (`audit_logs.event_type`)
  • meetings / visits / tasks
  • reports

When the denominator is below `min_data_points` the metric is returned with
`sufficient_data=False` and `value=None` — UI/API surfaces "Not enough data yet."
We NEVER return NaN or fake scores.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from .registry import (
    MetricDefinition,
    V1_METRICS,
    metric_by_slug,
    fei_components,
)


def _iso_minus_days(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@dataclass
class MetricResult:
    """One computed metric snapshot."""
    slug: str
    name: str
    scope: str
    scope_id: str
    company_id: Optional[str]
    window_days: int
    period_start: str
    period_end: str
    numerator: int
    denominator: int
    value: Optional[float]            # None when sufficient_data=False
    unit: str
    direction: str
    sufficient_data: bool
    min_data_points: int
    computed_at: str
    message: Optional[str] = None     # "Not enough data yet" etc

    def to_doc(self, metric_id: Optional[str] = None) -> dict:
        return {
            "id": metric_id,
            "slug": self.slug,
            "name": self.name,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "company_id": self.company_id,
            "window_days": self.window_days,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
            "unit": self.unit,
            "direction": self.direction,
            "sufficient_data": self.sufficient_data,
            "min_data_points": self.min_data_points,
            "computed_at": self.computed_at,
            "message": self.message,
        }


def _build(slug: str, scope_id: str, company_id: Optional[str], numerator: int,
           denominator: int, window_days: int) -> MetricResult:
    m = metric_by_slug(slug)
    if not m:
        raise ValueError(f"Unknown metric slug: {slug}")
    sufficient = (denominator >= m.min_data_points) and (numerator >= getattr(m, "min_numerator", 0))
    value: Optional[float] = (numerator / denominator) if (sufficient and denominator > 0) else None
    msg = None
    if not sufficient:
        if denominator < m.min_data_points:
            msg = f"Not enough data yet (need at least {m.min_data_points} data points; have {denominator})."
        else:
            msg = f"Not enough data yet (need at least {m.min_numerator} positive events; have {numerator})."
    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(days=window_days)
    return MetricResult(
        slug=m.slug,
        name=m.name,
        scope=m.scope,
        scope_id=scope_id,
        company_id=company_id,
        window_days=window_days,
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        numerator=numerator,
        denominator=denominator,
        value=value,
        unit=m.unit,
        direction=m.direction,
        sufficient_data=sufficient,
        min_data_points=m.min_data_points,
        computed_at=period_end.isoformat(),
        message=msg,
    )


# ============================================================
# Individual metric calculators
# Each takes `db` (motor async db), the TM user_id, the company_id,
# and the window_days. Returns a MetricResult.
# ============================================================

async def _promise_completion_rate(db, tm_id: str, company_id: Optional[str], window_days: int) -> MetricResult:
    """Promises whose due_date is in the window AND status=Completed, divided by promises
    whose due_date is in the window.
    """
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=window_days)
    base = {
        "tm_user_id": tm_id,
        "company_id": company_id,
        "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}],
        "due_date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
    }
    denom = await db.tasks.count_documents(base)
    completed = await db.tasks.count_documents({**base, "status": "Completed"})
    return _build("promise_completion_rate", tm_id, company_id, completed, denom, window_days)


async def _overdue_promise_rate(db, tm_id: str, company_id: Optional[str], window_days: int) -> MetricResult:
    """Open promises overdue (due_date < today) / all open promises right now.
    Window is not used here (the rate is point-in-time); we keep `window_days` for API symmetry.
    """
    today = _today_iso()[:10]
    base = {
        "tm_user_id": tm_id,
        "company_id": company_id,
        "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}],
        "status": {"$in": ["Open", "Overdue"]},
    }
    denom = await db.tasks.count_documents(base)
    overdue = await db.tasks.count_documents({**base, "due_date": {"$lt": today}})
    return _build("overdue_promise_rate", tm_id, company_id, overdue, denom, window_days)


async def _itero_discussed_to_booked(db, tm_id: str, company_id: Optional[str], window_days: int) -> MetricResult:
    """Distinct doctors with an `itero_demo_booked` event in window / distinct doctors with an
    `itero_demo_discussed` OR `itero_demo_booked` event in window.
    """
    since = _iso_minus_days(window_days)
    base = {"user_id": tm_id, "company_id": company_id, "timestamp": {"$gte": since}}
    discussed = await db.audit_logs.distinct("entity_id", {
        **base,
        "event_type": {"$in": ["itero_demo_discussed", "itero_demo_booked"]},
    })
    booked = await db.audit_logs.distinct("entity_id", {
        **base,
        "event_type": "itero_demo_booked",
    })
    # entity_id for these events is the track_signal id; we want distinct DOCTORS — use related docs.
    # Cheaper: pull `new_value.doctor_id` from the matching audit rows.
    discussed_docs = set()
    async for row in db.audit_logs.find({
        **base,
        "event_type": {"$in": ["itero_demo_discussed", "itero_demo_booked"]},
    }, {"_id": 0, "entity_id": 1, "new_value": 1}):
        nv = row.get("new_value") or {}
        # track_signal audit emits {"track_type":..., "signal_type":...}; doctor not in payload.
        # Fall back: look up the signal row.
        pass
    # Pragmatic fallback: use `track_signals` directly (one row per (doctor, track, signal_type, visit))
    # since the audit row carries the same info but lacks the doctor_id.
    end = datetime.now(timezone.utc).date().isoformat()
    start_date = (datetime.now(timezone.utc) - timedelta(days=window_days)).date().isoformat()
    ts_base = {
        "tm_user_id": tm_id,
        "company_id": company_id,
        "track_type": "iTero",
        "signal_date": {"$gte": start_date, "$lte": end},
        "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}],
    }
    discussed_doc_ids = await db.track_signals.distinct("doctor_id", {
        **ts_base,
        "signal_type": {"$in": ["demo_discussed", "demo_booked"]},
    })
    booked_doc_ids = await db.track_signals.distinct("doctor_id", {
        **ts_base,
        "signal_type": "demo_booked",
    })
    return _build(
        "itero_demo_discussed_to_booked_rate",
        tm_id, company_id,
        numerator=len(booked_doc_ids),
        denominator=len(discussed_doc_ids),
        window_days=window_days,
    )


async def _itero_booked_to_completed(db, tm_id: str, company_id: Optional[str], window_days: int) -> MetricResult:
    end = datetime.now(timezone.utc).date().isoformat()
    start_date = (datetime.now(timezone.utc) - timedelta(days=window_days)).date().isoformat()
    ts_base = {
        "tm_user_id": tm_id,
        "company_id": company_id,
        "track_type": "iTero",
        "signal_date": {"$gte": start_date, "$lte": end},
        "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}],
    }
    booked = await db.track_signals.distinct("doctor_id", {
        **ts_base, "signal_type": "demo_booked",
    })
    completed = await db.track_signals.distinct("doctor_id", {
        **ts_base, "signal_type": "demo_completed",
    })
    # Booked-to-completed: distinct doctors who eventually have a completion among the booked set.
    completed_overlap = [d for d in completed if d in set(booked)]
    return _build(
        "itero_demo_booked_to_completed_rate",
        tm_id, company_id,
        numerator=len(completed_overlap),
        denominator=len(booked),
        window_days=window_days,
    )


async def _meeting_to_visit_followthrough(db, tm_id: str, company_id: Optional[str], window_days: int) -> MetricResult:
    """Completed meetings in window / those with a linked visit_id (auto-completed via visit log).
    Soft-deleted meetings excluded.
    """
    since = _iso_minus_days(window_days)
    base = {
        "tm_user_id": tm_id,
        "company_id": company_id,
        "updated_at": {"$gte": since},
        "status": "Completed",
        "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}],
    }
    denom = await db.meetings.count_documents(base)
    linked = await db.meetings.count_documents({**base, "visit_id": {"$exists": True, "$ne": None}})
    return _build("meeting_to_visit_followthrough_rate", tm_id, company_id, linked, denom, window_days)


async def _weekly_report_submission_rate(db, tm_id: str, company_id: Optional[str], window_days: int) -> MetricResult:
    """Reports submitted by this TM in the last `window_days` / expected (1 per week)."""
    weeks_expected = max(1, window_days // 7)
    since = _iso_minus_days(window_days)
    submitted = await db.reports.count_documents({
        "tm_user_id": tm_id,
        "company_id": company_id,
        "status": {"$in": ["Submitted", "Reviewed"]},
        "submitted_at": {"$gte": since},
    })
    return _build("weekly_report_submission_rate", tm_id, company_id, submitted, weeks_expected, window_days)


# Map slug -> async calculator
CALCULATORS = {
    "promise_completion_rate": _promise_completion_rate,
    "overdue_promise_rate": _overdue_promise_rate,
    "itero_demo_discussed_to_booked_rate": _itero_discussed_to_booked,
    "itero_demo_booked_to_completed_rate": _itero_booked_to_completed,
    "meeting_to_visit_followthrough_rate": _meeting_to_visit_followthrough,
    "weekly_report_submission_rate": _weekly_report_submission_rate,
}


# ---------- Public API ----------
async def compute_metric_for_tm(db, slug: str, tm_id: str, company_id: Optional[str],
                                window_days: Optional[int] = None) -> MetricResult:
    m = metric_by_slug(slug)
    if not m:
        raise ValueError(f"Unknown metric slug: {slug}")
    calc = CALCULATORS.get(slug)
    if not calc:
        raise ValueError(f"No calculator wired for slug: {slug}")
    wd = window_days or m.window_days
    return await calc(db, tm_id, company_id, wd)


async def compute_all_for_tm(db, tm_id: str, company_id: Optional[str],
                             window_days: Optional[int] = None) -> list[MetricResult]:
    out: list[MetricResult] = []
    for m in V1_METRICS:
        if m.scope != "tm":
            continue
        wd = window_days or m.window_days
        calc = CALCULATORS.get(m.slug)
        if not calc:
            continue
        out.append(await calc(db, tm_id, company_id, wd))
    return out


def _normalize_to_0_100(result: MetricResult) -> Optional[float]:
    """Translate a rate/percentage into a 0–100 component score.
    `lower_is_better` rates are inverted. `None` if insufficient data."""
    if not result.sufficient_data or result.value is None:
        return None
    v = max(0.0, min(1.0, float(result.value)))
    if result.direction == "lower_is_better":
        v = 1.0 - v
    return round(v * 100.0, 2)


async def compute_fei_for_tm(db, tm_id: str, company_id: Optional[str],
                             window_days: Optional[int] = None) -> dict:
    """Field Execution Index (0–100) — weighted composite of the FEI-component metrics.

    Returns a dict:
      {
        "scope": "tm",
        "scope_id": tm_id,
        "company_id": ...,
        "fei": 76 | None,
        "label": "High" | "Medium" | "Low" | None,
        "components": [
          {slug, value_0_100, weight, sufficient_data, message},
          ...
        ],
        "sufficient_data": bool,
        "message": ...,
        "computed_at": iso,
      }
    """
    comps = fei_components()
    results = []
    weighted_sum = 0.0
    weight_sum = 0.0
    for m in comps:
        wd = window_days or m.window_days
        calc = CALCULATORS.get(m.slug)
        r = await calc(db, tm_id, company_id, wd)
        v100 = _normalize_to_0_100(r)
        results.append({
            "slug": m.slug,
            "name": m.name,
            "value_0_100": v100,
            "raw_value": r.value,
            "weight": m.fei_weight,
            "sufficient_data": r.sufficient_data,
            "message": r.message,
            "denominator": r.denominator,
            "min_data_points": r.min_data_points,
        })
        if v100 is not None:
            weighted_sum += v100 * m.fei_weight
            weight_sum += m.fei_weight

    if weight_sum == 0:
        return {
            "scope": "tm",
            "scope_id": tm_id,
            "company_id": company_id,
            "fei": None,
            "label": None,
            "components": results,
            "sufficient_data": False,
            "message": "Not enough data yet. Log a few visits, demos, and weekly reports to get your Field Execution Index.",
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    fei = round(weighted_sum / weight_sum, 1)
    label = "High" if fei >= 75 else ("Medium" if fei >= 50 else "Low")
    return {
        "scope": "tm",
        "scope_id": tm_id,
        "company_id": company_id,
        "fei": fei,
        "label": label,
        "components": results,
        "sufficient_data": True,
        "message": None,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
