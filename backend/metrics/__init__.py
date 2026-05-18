"""Phase D — Metric package public API."""
from .registry import (
    MetricDefinition,
    V1_METRICS,
    metric_by_slug,
    fei_components,
)
from .compute import (
    MetricResult,
    compute_metric_for_tm,
    compute_all_for_tm,
    compute_fei_for_tm,
)
