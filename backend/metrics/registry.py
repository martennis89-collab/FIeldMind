"""Phase D — Metric Registry & V1 metric definitions.

Each metric is a pure-data record telling the compute engine WHAT to measure.
The actual computation lives in `metrics.compute`.

Conventions:
  • `slug`        — stable identifier referenced everywhere (event_ledger, snapshots, FEI).
  • `scope`       — the entity dimension the metric makes sense for.
                    `tm` = per-TM, `team` = per-team, `company` = company-wide, `doctor` = per-doctor.
  • `unit`        — "percentage" (0–100, "rate" displayed as 0–1), "count", "score" (0–100).
  • `direction`   — `higher_is_better` or `lower_is_better`.
  • `min_data_points` — minimum denominator before the metric is considered "sufficient".
                       Below this threshold the snapshot is stored with `sufficient_data=False`
                       and the UI/API returns "Not enough data yet."
  • `category`    — `execution`, `pipeline`, `discipline`, `quality`. Used by the FEI composite.
  • `fei_weight`  — 0–1; how much the metric contributes to the Field Execution Index.
                    Metrics with weight=0 are tracked but do NOT roll up into FEI.
  • `window_days` — default measurement window (default = 30).
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel


class MetricDefinition(BaseModel):
    slug: str
    name: str
    description: str
    category: Literal["execution", "pipeline", "discipline", "quality"]
    scope: Literal["tm", "team", "company", "doctor"]
    unit: Literal["percentage", "rate", "count", "score"]
    direction: Literal["higher_is_better", "lower_is_better"]
    min_data_points: int = 5
    # Optional secondary gate — if the numerator (number of POSITIVE events) is below this
    # the snapshot is "not enough data yet". Useful for metrics whose denominator is a
    # constant time-window (e.g. "weeks elapsed") and would otherwise return a misleading 0%.
    min_numerator: int = 0
    window_days: int = 30
    fei_weight: float = 0.0
    benchmark_eligible: bool = False  # Phase G — only safe operational metrics can be benchmarked
    source: str  # human-readable source description


# ---------- V1 metric definitions (registry) ----------
V1_METRICS: list[MetricDefinition] = [
    # --- Promises / Tasks ---
    MetricDefinition(
        slug="promise_completion_rate",
        name="Promise completion rate",
        description=(
            "Promises completed within the window ÷ promises whose due_date falls inside the window. "
            "Measures TM follow-through discipline."
        ),
        category="execution",
        scope="tm",
        unit="rate",
        direction="higher_is_better",
        min_data_points=5,
        window_days=30,
        fei_weight=0.25,
        benchmark_eligible=True,
        source="tasks (status=Completed) / tasks where due_date in window",
    ),
    MetricDefinition(
        slug="overdue_promise_rate",
        name="Overdue promise rate",
        description=(
            "Open promises whose due_date is in the past ÷ all open promises at the snapshot timestamp. "
            "Higher = worse follow-through."
        ),
        category="execution",
        scope="tm",
        unit="rate",
        direction="lower_is_better",
        min_data_points=5,
        window_days=30,
        fei_weight=0.15,
        benchmark_eligible=True,
        source="tasks (status=Open AND due_date<today) / tasks (status=Open)",
    ),
    # --- iTero pipeline ---
    MetricDefinition(
        slug="itero_demo_discussed_to_booked_rate",
        name="iTero — Discussed → Booked rate",
        description=(
            "Doctors with an `itero_demo_booked` event in the window ÷ doctors with at least one "
            "`itero_demo_discussed` event in the window (or earlier)."
        ),
        category="pipeline",
        scope="tm",
        unit="rate",
        direction="higher_is_better",
        min_data_points=3,
        window_days=30,
        fei_weight=0.15,
        benchmark_eligible=True,
        source="event_ledger (itero_demo_discussed / itero_demo_booked)",
    ),
    MetricDefinition(
        slug="itero_demo_booked_to_completed_rate",
        name="iTero — Booked → Completed rate",
        description=(
            "Doctors with an `itero_demo_completed` event ÷ doctors with an `itero_demo_booked` "
            "event in the window. The healthiest single signal of execution discipline on the iTero track."
        ),
        category="pipeline",
        scope="tm",
        unit="rate",
        direction="higher_is_better",
        min_data_points=3,
        window_days=30,
        fei_weight=0.20,
        benchmark_eligible=True,
        source="event_ledger (itero_demo_booked / itero_demo_completed)",
    ),
    # --- Meeting quality ---
    MetricDefinition(
        slug="meeting_to_visit_followthrough_rate",
        name="Meeting → visit follow-through rate",
        description=(
            "Scheduled meetings that have an associated visit logged within 7 days of the meeting "
            "÷ all completed meetings in the window. Measures execution discipline on planned activities."
        ),
        category="quality",
        scope="tm",
        unit="rate",
        direction="higher_is_better",
        min_data_points=3,
        window_days=30,
        fei_weight=0.10,
        benchmark_eligible=True,
        source="meetings (status=Completed with linked visit_id) / meetings (status=Completed)",
    ),
    # --- Report discipline ---
    MetricDefinition(
        slug="weekly_report_submission_rate",
        name="Weekly report submission rate",
        description=(
            "Weekly reports submitted ÷ weeks elapsed in the window. Healthy TMs submit one per week."
        ),
        category="discipline",
        scope="tm",
        unit="rate",
        direction="higher_is_better",
        min_data_points=2,
        min_numerator=1,  # require at least 1 submitted report before reporting a rate
        window_days=30,
        fei_weight=0.15,
        source="reports (status in [Submitted, Reviewed]) / weeks in window",
    ),
]


def metric_by_slug(slug: str) -> Optional[MetricDefinition]:
    for m in V1_METRICS:
        if m.slug == slug:
            return m
    return None


def fei_components() -> list[MetricDefinition]:
    """The subset of metrics whose `fei_weight > 0` — these feed the composite score."""
    return [m for m in V1_METRICS if m.fei_weight > 0]
