"""Phase E — Deterministic insight-card generation rules.

Each rule looks at a SINGLE Phase D metric snapshot and decides whether to emit a card.

Rules:
  • Only generate when the underlying metric has `sufficient_data=True`.
  • Severity buckets are explicit (no AI, no vagueness):
        rate metrics → "lower_is_better": >0.30 = High, >0.20 = Medium, ≤0.20 = none
                       "higher_is_better": <0.50 = High, <0.70 = Medium, ≥0.70 = none
        FEI         : <50 = High (Low), 50–74 = Medium, ≥75 = none
  • Each card is deterministic via `dedup_key = "insight:<scope_id>:<slug>:<period_yyyymmdd>"`.
    Re-running the generator on the same day for the same TM produces the SAME card id.
  • All cards carry the source `metric_value` and a `suggested_action`.
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime, timezone


# ============================================================
# Severity bucketing
# ============================================================
def _bucket_higher_better(value: float) -> Optional[str]:
    if value < 0.50:
        return "High"
    if value < 0.70:
        return "Medium"
    return None


def _bucket_lower_better(value: float) -> Optional[str]:
    if value > 0.30:
        return "High"
    if value > 0.20:
        return "Medium"
    return None


def _bucket_fei(fei: float) -> Optional[str]:
    if fei < 50:
        return "High"
    if fei < 75:
        return "Medium"
    return None


# ============================================================
# Rule definitions — one per Phase D metric slug
# ============================================================
RULES: dict[str, dict] = {
    "overdue_promise_rate": {
        "category": "Promise Discipline",
        "direction": "lower_is_better",
        "title_high":   "Overdue promise risk is high",
        "title_medium": "Overdue promises building up",
        "suggested":    "Review overdue promises and complete or reschedule them today.",
        "why":          "Letting promises slip erodes doctor trust and lowers your Field Execution Index.",
    },
    "promise_completion_rate": {
        "category": "Promise Discipline",
        "direction": "higher_is_better",
        "title_high":   "Promise completion is weak",
        "title_medium": "Promise completion is below target",
        "suggested":    "Focus on closing open commitments before creating new ones.",
        "why":          "Doctors remember unkept commitments. Closing the loop is the cheapest trust signal you have.",
    },
    "itero_demo_discussed_to_booked_rate": {
        "category": "iTero Execution",
        "direction": "higher_is_better",
        "title_high":   "iTero demo discussions are not converting to bookings",
        "title_medium": "iTero discussed → booked conversion is below target",
        "suggested":    "Review doctors where the iTero demo was discussed but not booked.",
        "why":          "Discussed-without-booked is the single biggest leak in the iTero pipeline.",
    },
    "itero_demo_booked_to_completed_rate": {
        "category": "iTero Execution",
        "direction": "higher_is_better",
        "title_high":   "Booked iTero demos are not being completed",
        "title_medium": "iTero booked → completed conversion is below target",
        "suggested":    "Follow up on booked demos and confirm a completion date with each doctor.",
        "why":          "A booked-but-incomplete demo is the most expensive activity to recover — schedule explicitly.",
    },
    "meeting_to_visit_followthrough_rate": {
        "category": "Meeting Follow-through",
        "direction": "higher_is_better",
        "title_high":   "Meetings are not turning into field activity",
        "title_medium": "Meeting follow-through is below target",
        "suggested":    "Review recent meetings without a visit log and add a next step.",
        "why":          "Meetings that don't generate a logged visit produce no compounding pipeline value.",
    },
    "weekly_report_submission_rate": {
        "category": "Reporting",
        "direction": "higher_is_better",
        "title_high":   "Weekly reporting discipline is weak",
        "title_medium": "Weekly reporting is slipping",
        "suggested":    "Submit overdue weekly reports and keep weekly reports current.",
        "why":          "Missing reports blind your manager and yourself to what's actually happening in the field.",
    },
}


# ============================================================
# Engine
# ============================================================
def _today_yyyymmdd() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _dedup_key(scope_id: str, slug: str) -> str:
    return f"insight:{scope_id}:{slug}:{_today_yyyymmdd()}"


def evaluate_metric(scope_id: str, scope_type: str, company_id: Optional[str],
                    team_id: Optional[str], manager_id: Optional[str],
                    metric: dict) -> Optional[dict]:
    """Return an InsightCard dict if `metric` triggers a rule, else None.
    `metric` is the dict shape returned by `MetricResult.to_doc()`.
    """
    if not metric.get("sufficient_data"):
        return None
    slug = metric["slug"]
    rule = RULES.get(slug)
    if not rule:
        return None
    value = metric["value"]
    if value is None:
        return None
    direction = rule["direction"]
    if direction == "higher_is_better":
        sev = _bucket_higher_better(value)
    else:
        sev = _bucket_lower_better(value)
    if sev is None:
        return None
    title = rule["title_high"] if sev == "High" else rule["title_medium"]
    body = (
        f"{rule['why']} Current value: {round(value * 100, 1)}% "
        f"(sample size: {metric['denominator']})."
    )
    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "company_id": company_id,
        "team_id": team_id,
        "tm_user_id": scope_id if scope_type == "TM" else None,
        "manager_id": manager_id,
        "severity": sev,
        "category": rule["category"],
        "title": title,
        "body": body,
        "related_metric_slug": slug,
        "metric_value": value,
        "comparison_value": None,
        "suggested_action": rule["suggested"],
        "status": "New",
        "dedup_key": _dedup_key(scope_id, slug),
    }


def evaluate_fei(scope_id: str, scope_type: str, company_id: Optional[str],
                 team_id: Optional[str], manager_id: Optional[str],
                 fei_payload: dict) -> Optional[dict]:
    """Emit one FEI advisory card when FEI < 75."""
    if not fei_payload.get("sufficient_data"):
        return None
    fei = fei_payload.get("fei")
    if fei is None:
        return None
    sev = _bucket_fei(float(fei))
    if sev is None:
        return None
    title = "Field Execution Index is low" if sev == "High" else "Field Execution Index is below target"
    body = (
        f"Your Field Execution Index is {fei}/100. "
        "Start with overdue promises and weak iTero follow-through — those move the score fastest."
    )
    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "company_id": company_id,
        "team_id": team_id,
        "tm_user_id": scope_id if scope_type == "TM" else None,
        "manager_id": manager_id,
        "severity": sev,
        "category": "Field Execution",
        "title": title,
        "body": body,
        "related_metric_slug": "field_execution_index",
        "metric_value": float(fei) / 100.0,  # normalised 0–1 for consistency with rate metrics
        "comparison_value": None,
        "suggested_action": "Open your weakest metric first; fix one card at a time.",
        "status": "New",
        "dedup_key": _dedup_key(scope_id, "field_execution_index"),
    }
