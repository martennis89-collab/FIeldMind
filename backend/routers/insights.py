"""Phase E — Insight Cards + Advisory Layer.

  • `POST /api/insights/generate`     — compute fresh metrics + persist insight cards.
                                        TM   → own insights only.
                                        Mgr  → all TMs in own team.
                                        Adm  → all TMs in own company.
                                        Owner → all TMs in own company (Owner uses /companies for cross-company).
  • `GET  /api/insights/me`           — caller's own insight cards.
  • `GET  /api/insights/team`         — Manager: all team-member cards. Adm/Owner: all company TM cards.
  • `GET  /api/insights/company`      — Admin/Owner: company-level rollup + every TM card.
  • `POST /api/insights/{id}/seen`    — flip status=Seen (additive — never moves resolved/dismissed).
  • `POST /api/insights/{id}/resolve` — flip status=Resolved.
  • `POST /api/insights/{id}/dismiss` — flip status=Dismissed.

Phase I: `/insights/team` and `/insights/company` enrich each card with a
readable `scope_name` (TM full_name) so the frontend doesn't have to fall back
to UUID prefixes.

History: cards are never deleted; status transitions are recorded with timestamps.
Dedup: re-running `/generate` on the same day for the same TM updates (not duplicates) the
existing card via `dedup_key`.
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
    _company_query_for,
    _assert_same_company,
)
from metrics import compute_all_for_tm, compute_fei_for_tm
from metrics.insights import evaluate_metric, evaluate_fei


# ============================================================
# Helpers
# ============================================================
async def _target_tms(user) -> list[dict]:
    """Return the list of TM user documents the caller is allowed to generate insights for."""
    role = user.get("role")
    q = dict(_company_query_for(user))
    q["role"] = "TM"
    if role == "TM":
        q["id"] = user["id"]
    elif role == "Manager":
        q["team_id"] = user.get("team_id")
    # Admin / Owner → all TMs in company (Owner skips company filter because _company_query_for is empty)
    return await db.users.find(q, {"_id": 0, "password_hash": 0}).to_list(2000)


async def _upsert_card(card: dict) -> str:
    """Idempotent persist via dedup_key. Returns the row id (new or existing)."""
    existing = await db.insight_cards.find_one({"dedup_key": card["dedup_key"]}, {"_id": 0, "id": 1, "status": 1})
    now = _now_iso()
    if existing:
        # Refresh title/body/severity/metric_value/updated_at; do NOT clobber user-set status.
        patch = {k: v for k, v in card.items() if k not in ("id", "created_at", "status", "dedup_key",
                                                            "seen_at", "resolved_at", "dismissed_at")}
        patch["updated_at"] = now
        await db.insight_cards.update_one({"dedup_key": card["dedup_key"]}, {"$set": patch})
        return existing["id"]
    doc = {**card, "id": uuid.uuid4().hex, "created_at": now, "updated_at": now}
    await db.insight_cards.insert_one(doc)
    return doc["id"]


def _strip(doc):
    if doc and "_id" in doc:
        doc.pop("_id", None)
    return doc


async def _enrich_scope_names(cards: list[dict]) -> list[dict]:
    """Phase I: resolve `scope_id` (TM UUID) to a readable `scope_name` (TM full_name).

    Bulk-loads users in one query, then mutates each card in-place. Cards whose
    scope_id is not a TM (e.g. team-level or company-level scopes) get
    `scope_name=None` and the frontend keeps its existing fallback rendering.
    """
    if not cards:
        return cards
    ids = sorted({c.get("scope_id") for c in cards if c.get("scope_id")})
    if not ids:
        return cards
    users = await db.users.find(
        {"id": {"$in": list(ids)}},
        {"_id": 0, "id": 1, "full_name": 1},
    ).to_list(len(ids))
    name_by_id = {u["id"]: u.get("full_name") for u in users}
    for c in cards:
        c["scope_name"] = name_by_id.get(c.get("scope_id"))
    return cards


# ============================================================
# Generate
# ============================================================
@api.post("/insights/generate")
async def generate_insights(user=Depends(get_current_user)):
    """Compute Phase D metrics for the caller's allowed scope and persist insight cards.
    Returns the freshly created/updated cards (only those that pass the rule thresholds)."""
    targets = await _target_tms(user)
    created_ids: list[str] = []
    for t in targets:
        cid = t.get("company_id")
        team_id = t.get("team_id")
        mgr_id = t.get("manager_user_id")
        rows = await compute_all_for_tm(db, t["id"], cid)
        for r in rows:
            card = evaluate_metric(t["id"], "TM", cid, team_id, mgr_id, r.to_doc())
            if card:
                created_ids.append(await _upsert_card(card))
        fei = await compute_fei_for_tm(db, t["id"], cid)
        fei_card = evaluate_fei(t["id"], "TM", cid, team_id, mgr_id, fei)
        if fei_card:
            created_ids.append(await _upsert_card(fei_card))
    await _audit(user, "create", "insight_card_batch", f"batch:{len(created_ids)}",
                 new={"count": len(created_ids), "tms": len(targets)},
                 event_type="insights_generated")
    fresh = await db.insight_cards.find({"id": {"$in": created_ids}}, {"_id": 0}).sort("severity", -1).to_list(5000)
    return {"ok": True, "cards_generated": len(created_ids), "tms_processed": len(targets), "cards": fresh}


# ============================================================
# READ — scoped by role
# ============================================================
def _active_only(q: dict, include_resolved: bool, include_dismissed: bool) -> dict:
    statuses: list[str] = ["New", "Seen"]
    if include_resolved:
        statuses.append("Resolved")
    if include_dismissed:
        statuses.append("Dismissed")
    q["status"] = {"$in": statuses}
    return q


@api.get("/insights/me")
async def my_insights(
    include_resolved: bool = False,
    include_dismissed: bool = False,
    user=Depends(get_current_user),
):
    q = dict(_company_query_for(user))
    q["scope_id"] = user["id"]
    _active_only(q, include_resolved, include_dismissed)
    return await db.insight_cards.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)


@api.get("/insights/team")
async def team_insights(
    include_resolved: bool = False,
    include_dismissed: bool = False,
    user=Depends(require_roles("Manager", "Admin", "Owner")),
):
    targets = await _target_tms(user)
    tm_ids = [t["id"] for t in targets]
    q = dict(_company_query_for(user))
    q["scope_id"] = {"$in": tm_ids}
    _active_only(q, include_resolved, include_dismissed)
    cards = await db.insight_cards.find(q, {"_id": 0}).sort([("severity", -1), ("created_at", -1)]).to_list(5000)
    return await _enrich_scope_names(cards)


@api.get("/insights/company")
async def company_insights(
    include_resolved: bool = False,
    include_dismissed: bool = False,
    user=Depends(require_roles("Admin", "Owner")),
):
    q = dict(_company_query_for(user))
    _active_only(q, include_resolved, include_dismissed)
    cards = await db.insight_cards.find(q, {"_id": 0}).sort([("severity", -1), ("created_at", -1)]).to_list(5000)
    await _enrich_scope_names(cards)
    # Severity histogram for quick rollup
    by_sev: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    for c in cards:
        by_sev[c["severity"]] = by_sev.get(c["severity"], 0) + 1
        by_cat[c["category"]] = by_cat.get(c["category"], 0) + 1
    return {"cards": cards, "by_severity": by_sev, "by_category": by_cat, "total": len(cards)}


# ============================================================
# Status actions
# ============================================================
async def _load_card_or_403(card_id: str, user) -> dict:
    c = await db.insight_cards.find_one({"id": card_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Insight card not found")
    _assert_same_company(user, c, code=404, detail="Insight card not found")
    # Owner/Admin → company wide. Manager → team-scope. TM → own only.
    role = user.get("role")
    if role == "TM" and c.get("scope_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if role == "Manager" and c.get("team_id") not in (user.get("team_id"), None):
        # Allow Manager to act on company-scope cards in their team_id; otherwise forbid.
        if c.get("team_id") and c["team_id"] != user.get("team_id"):
            raise HTTPException(status_code=403, detail="Forbidden")
    return c


async def _transition(card_id: str, new_status: str, ts_field: str, user) -> dict:
    c = await _load_card_or_403(card_id, user)
    now = _now_iso()
    patch = {"status": new_status, ts_field: now, "updated_at": now}
    await db.insight_cards.update_one({"id": card_id}, {"$set": patch})
    await _audit(user, "update", "insight_card", card_id, prev={"status": c["status"]},
                 new=patch, event_type=f"insight_{new_status.lower()}")
    return await db.insight_cards.find_one({"id": card_id}, {"_id": 0})


@api.post("/insights/{card_id}/seen")
async def mark_seen(card_id: str, user=Depends(get_current_user)):
    c = await _load_card_or_403(card_id, user)
    # Only flip if currently New (don't unwind a Resolved/Dismissed)
    if c["status"] != "New":
        return c
    return await _transition(card_id, "Seen", "seen_at", user)


@api.post("/insights/{card_id}/resolve")
async def mark_resolved(card_id: str, user=Depends(get_current_user)):
    return await _transition(card_id, "Resolved", "resolved_at", user)


@api.post("/insights/{card_id}/dismiss")
async def mark_dismissed(card_id: str, user=Depends(get_current_user)):
    return await _transition(card_id, "Dismissed", "dismissed_at", user)
