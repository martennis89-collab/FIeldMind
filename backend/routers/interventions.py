"""Phase F — Intervention entity + Manager Intervention tab.

  • `GET    /api/interventions`                          — list (RBAC + company-scoped).
  • `GET    /api/interventions/{id}`                     — single.
  • `POST   /api/interventions`                          — manual create (Manager/Admin/Owner).
  • `POST   /api/interventions/from-insight/{insight_id}` — pre-fill from insight card.
  • `PUT    /api/interventions/{id}`                     — partial update (issue, note, due, severity, …).
  • `POST   /api/interventions/{id}/in-progress`         — flip status → In Progress.
  • `POST   /api/interventions/{id}/complete`            — flip status → Completed + completed_at.
  • `POST   /api/interventions/{id}/dismiss`             — flip status → Dismissed + dismissed_at.
  • `DELETE /api/interventions/{id}`                     — soft delete (deleted_at).

RBAC:
  - Manager: read/write own-team interventions (`team_id == self.team_id`).
  - Admin: read/write all interventions in own company.
  - Owner: cross-company support visibility.
  - TM: READ-ONLY on interventions where `tm_user_id == self.id`. Cannot create, edit, or delete.
"""
from __future__ import annotations
from typing import Optional, List
from datetime import datetime, timezone

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
    _stamp_company,
)
from models import Intervention, InterventionCreate, InterventionUpdate

# Allowed enum values for runtime validation (mirrors Literals in models.py)
ALLOWED_STATUS = {"Open", "In Progress", "Completed", "Dismissed"}
ALLOWED_SEVERITY = {"Low", "Medium", "High", "Critical"}
ALLOWED_TRACK = {"General", "iTero", "Invisalign", "Both"}


# ---------- helpers ----------
def _strip(d):
    if d and "_id" in d:
        d.pop("_id", None)
    return d


def _base_query(user) -> dict:
    """Read-side base query enforcing soft-delete + RBAC + company scope."""
    q: dict = {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]}
    q.update(_company_query_for(user))
    role = user.get("role")
    if role == "TM":
        q["tm_user_id"] = user["id"]
    elif role == "Manager":
        q["team_id"] = user.get("team_id")
    # Admin / Owner → all in own company (Owner already bypasses via _company_query_for)
    return q


async def _load_or_404(intervention_id: str, user) -> dict:
    i = await db.interventions.find_one({"id": intervention_id}, {"_id": 0})
    if not i or i.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Intervention not found")
    _assert_same_company(user, i, code=404, detail="Intervention not found")
    role = user.get("role")
    if role == "TM" and i.get("tm_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if role == "Manager" and i.get("team_id") != user.get("team_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return i


async def _audit_intervention(user, action: str, intervention_id: str,
                              prev: Optional[dict] = None, new: Optional[dict] = None,
                              event_type: Optional[str] = None):
    await _audit(user, action, "intervention", intervention_id,
                 prev=prev, new=new, event_type=event_type)


# ---------- LIST + GET ----------
@api.get("/interventions")
async def list_interventions(
    status: Optional[str] = Query(None),
    tm_id: Optional[str] = Query(None),
    severity: Optional[str] = None,
    track_type: Optional[str] = None,
    include_dismissed: bool = False,
    include_completed: bool = True,
    user=Depends(get_current_user),
):
    q = _base_query(user)
    statuses: list[str] = ["Open", "In Progress"]
    if include_completed:
        statuses.append("Completed")
    if include_dismissed:
        statuses.append("Dismissed")
    q["status"] = {"$in": statuses}
    if status:
        if status not in ALLOWED_STATUS:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        q["status"] = status
    if tm_id:
        q["tm_user_id"] = tm_id
    if severity:
        if severity not in ALLOWED_SEVERITY:
            raise HTTPException(status_code=400, detail="Invalid severity")
        q["severity"] = severity
    if track_type:
        if track_type not in ALLOWED_TRACK:
            raise HTTPException(status_code=400, detail="Invalid track_type")
        q["track_type"] = track_type
    rows = await db.interventions.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return rows


@api.get("/interventions/{intervention_id}")
async def get_intervention(intervention_id: str, user=Depends(get_current_user)):
    return await _load_or_404(intervention_id, user)


# ---------- CREATE ----------
async def _insert_intervention(doc: dict, user) -> dict:
    """Common create path used by both manual + from-insight endpoints."""
    if doc["severity"] not in ALLOWED_SEVERITY:
        raise HTTPException(status_code=400, detail="Invalid severity")
    if doc["track_type"] not in ALLOWED_TRACK:
        raise HTTPException(status_code=400, detail="Invalid track_type")

    # Pull team_id from the assigned TM (or fall back to manager's team)
    tm_id = doc.get("tm_user_id")
    team_id = None
    if tm_id:
        tm = await db.users.find_one({"id": tm_id}, {"_id": 0, "team_id": 1, "company_id": 1})
        if not tm:
            raise HTTPException(status_code=404, detail="Assigned TM not found")
        _assert_same_company(user, tm, code=400, detail="Cannot assign cross-company TM")
        team_id = tm.get("team_id")
        if user.get("role") == "Manager" and team_id != user.get("team_id"):
            raise HTTPException(status_code=403, detail="Manager can only assign to own team")
    else:
        team_id = user.get("team_id")

    import uuid as _u
    now = _now_iso()
    row = {
        "id": _u.uuid4().hex,
        "company_id": _company_id_for(user),
        "team_id": team_id,
        "manager_id": user["id"],
        "tm_user_id": tm_id,
        "doctor_id": doc.get("doctor_id"),
        "insight_card_id": doc.get("insight_card_id"),
        "related_entity_type": doc.get("related_entity_type"),
        "related_entity_id": doc.get("related_entity_id"),
        "track_type": doc["track_type"],
        "severity": doc["severity"],
        "issue_title": doc["issue_title"],
        "issue_description": doc.get("issue_description"),
        "suggested_action": doc.get("suggested_action"),
        "manager_note": doc.get("manager_note"),
        "status": "Open",
        "due_date": doc.get("due_date"),
        "created_from_insight": bool(doc.get("insight_card_id")),
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "dismissed_at": None,
        "deleted_at": None,
    }
    _stamp_company(row, user)
    await db.interventions.insert_one(row)
    await _audit_intervention(user, "create", row["id"], new={
        "issue_title": row["issue_title"], "tm_user_id": tm_id,
        "severity": row["severity"], "from_insight": row["created_from_insight"],
    }, event_type="intervention_created")
    return _strip(row)


@api.post("/interventions")
async def create_intervention(body: InterventionCreate,
                              user=Depends(require_roles("Manager", "Admin", "Owner"))):
    return await _insert_intervention(body.model_dump(), user)


@api.post("/interventions/from-insight/{insight_id}")
async def create_from_insight(insight_id: str,
                              body: Optional[InterventionUpdate] = None,
                              user=Depends(require_roles("Manager", "Admin", "Owner"))):
    """Pre-fill from an existing insight card. Manager can override note/due_date/severity via body."""
    card = await db.insight_cards.find_one({"id": insight_id}, {"_id": 0})
    if not card:
        raise HTTPException(status_code=404, detail="Insight card not found")
    _assert_same_company(user, card, code=404, detail="Insight card not found")

    # Map insight severity → intervention severity (1:1)
    severity = card.get("severity") or "Medium"
    # Map metric slug → track_type
    slug = card.get("related_metric_slug", "")
    if "itero" in slug:
        track = "iTero"
    elif "invisalign" in slug:
        track = "Invisalign"
    else:
        track = "General"

    # Apply optional overrides
    override = body.model_dump(exclude_unset=True) if body else {}
    doc = {
        "tm_user_id": override.get("tm_user_id") or card.get("scope_id"),
        "doctor_id": None,
        "insight_card_id": card["id"],
        "related_entity_type": "insight_card",
        "related_entity_id": card["id"],
        "track_type": override.get("track_type") or track,
        "severity": override.get("severity") or severity,
        "issue_title": override.get("issue_title") or card.get("title"),
        "issue_description": override.get("issue_description") or card.get("body"),
        "suggested_action": override.get("suggested_action") or card.get("suggested_action"),
        "manager_note": override.get("manager_note"),
        "due_date": override.get("due_date"),
    }
    inter = await _insert_intervention(doc, user)

    # Optionally mark the source insight card as Seen if it's still New (don't unwind resolved/dismissed)
    if card.get("status") == "New":
        await db.insight_cards.update_one(
            {"id": card["id"]},
            {"$set": {"status": "Seen", "seen_at": _now_iso(), "updated_at": _now_iso()}},
        )
    return inter


# ---------- UPDATE ----------
@api.put("/interventions/{intervention_id}")
async def update_intervention(intervention_id: str, body: InterventionUpdate,
                              user=Depends(require_roles("Manager", "Admin", "Owner"))):
    existing = await _load_or_404(intervention_id, user)
    updates = body.model_dump(exclude_unset=True)
    # Validate enums
    if "severity" in updates and updates["severity"] not in ALLOWED_SEVERITY:
        raise HTTPException(status_code=400, detail="Invalid severity")
    if "track_type" in updates and updates["track_type"] not in ALLOWED_TRACK:
        raise HTTPException(status_code=400, detail="Invalid track_type")
    if "status" in updates and updates["status"] not in ALLOWED_STATUS:
        raise HTTPException(status_code=400, detail="Invalid status")

    # Cross-company / cross-team TM reassignment guard
    if "tm_user_id" in updates and updates["tm_user_id"]:
        tm = await db.users.find_one({"id": updates["tm_user_id"]}, {"_id": 0, "team_id": 1, "company_id": 1})
        if not tm:
            raise HTTPException(status_code=404, detail="TM not found")
        _assert_same_company(user, tm, code=400, detail="Cross-company TM")
        if user.get("role") == "Manager" and tm.get("team_id") != user.get("team_id"):
            raise HTTPException(status_code=403, detail="Manager can only assign to own team")
        updates["team_id"] = tm.get("team_id")

    updates["updated_at"] = _now_iso()
    await db.interventions.update_one({"id": intervention_id}, {"$set": updates})
    await _audit_intervention(user, "update", intervention_id, prev=existing,
                              new=updates, event_type="intervention_updated")
    return await db.interventions.find_one({"id": intervention_id}, {"_id": 0})


async def _transition(intervention_id: str, status: str, ts_field: Optional[str],
                      event_type: str, user) -> dict:
    existing = await _load_or_404(intervention_id, user)
    now = _now_iso()
    patch = {"status": status, "updated_at": now}
    if ts_field:
        patch[ts_field] = now
    await db.interventions.update_one({"id": intervention_id}, {"$set": patch})
    await _audit_intervention(user, "update", intervention_id,
                              prev={"status": existing["status"]}, new=patch,
                              event_type=event_type)
    return await db.interventions.find_one({"id": intervention_id}, {"_id": 0})


@api.post("/interventions/{intervention_id}/in-progress")
async def mark_in_progress(intervention_id: str,
                           user=Depends(require_roles("Manager", "Admin", "Owner"))):
    return await _transition(intervention_id, "In Progress", None,
                             "intervention_in_progress", user)


@api.post("/interventions/{intervention_id}/complete")
async def mark_complete(intervention_id: str,
                        user=Depends(require_roles("Manager", "Admin", "Owner"))):
    return await _transition(intervention_id, "Completed", "completed_at",
                             "intervention_completed", user)


@api.post("/interventions/{intervention_id}/dismiss")
async def mark_dismissed(intervention_id: str,
                         user=Depends(require_roles("Manager", "Admin", "Owner"))):
    return await _transition(intervention_id, "Dismissed", "dismissed_at",
                             "intervention_dismissed", user)


@api.delete("/interventions/{intervention_id}")
async def delete_intervention(intervention_id: str,
                              user=Depends(require_roles("Manager", "Admin", "Owner"))):
    existing = await _load_or_404(intervention_id, user)
    await db.interventions.update_one(
        {"id": intervention_id},
        {"$set": {"deleted_at": _now_iso(), "updated_at": _now_iso()}},
    )
    await _audit_intervention(user, "delete", intervention_id, prev=existing,
                              event_type="intervention_deleted")
    return {"ok": True, "id": intervention_id, "deleted": True}
