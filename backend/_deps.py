"""Scope / RBAC helpers extracted from server.py during the P1 spaghetti refactor.

These functions enforce the multi-tenant company isolation and the role-based
visibility scope (Owner / Admin / Manager / SeniorTM / TM) across every
read-heavy endpoint. They live in their own module so:

- Routers can import them directly without pulling the whole `server.py`
  surface area.
- The scope logic is centralised — one place to audit for tenancy bugs.
- `server.py` shrinks below 1700 lines and stops being a junk drawer.

Functions that need MongoDB access use a *lazy* `from server import db` inside
the function body. That avoids an import-time cycle (server -> _deps -> server)
while still letting the runtime resolve `db` once supervisor has fully booted.
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Optional

from fastapi import HTTPException


# ============================================================
# Doctor-name normalisation — used for duplicate detection so that
# "Dr John Smith", "dr. john smith", "John Smith" and "Ján Smith"
# collapse to the same key. Applied at both create-doctor and
# import time so the two paths stay consistent.
# ============================================================

# Common honorifics — repeated stripping handles "Prof. Dr. John".
_TITLE_RE = re.compile(
    r"^(?:dr\.?|drs\.?|doctor|prof\.?|professor|mr\.?|mrs\.?|ms\.?|mx\.?|sir|dame)\s+",
    re.IGNORECASE,
)


def normalize_person_name(name: object) -> str:
    """Return a stable lowercase key for a doctor / person name.

    - Strips titles (Dr, Prof, Mr, Mrs, Ms, Doctor, etc.), even stacked.
    - Removes accents (é -> e) so cross-locale entries collide.
    - Collapses internal whitespace.
    - Strips trailing punctuation.
    """
    if not name:
        return ""
    s = str(name).strip()
    # Strip repeated leading titles.
    while True:
        s2 = _TITLE_RE.sub("", s).strip()
        if s2 == s:
            break
        s = s2
    # Unicode-fold accents.
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # Collapse whitespace, strip trailing punctuation.
    s = re.sub(r"\s+", " ", s).strip(" .,;:")
    return s.lower()


def normalize_city_key(city: object) -> str:
    """Loose city key — lowercase, strip accents & punctuation. Empty for None."""
    if not city:
        return ""
    s = unicodedata.normalize("NFKD", str(city).strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip(" .,;:").lower()


# ============================================================
# PHASE C — Multi-tenant company helpers
# ============================================================
# Feature flag mirrors the original definition in server.py. Kept here so the
# scope helpers are self-contained.
ENFORCE_COMPANY_ISOLATION = os.environ.get("ENFORCE_COMPANY_ISOLATION", "true").lower() == "true"


def _company_id_for(user) -> Optional[str]:
    """The company_id that should be stamped on every write made by `user`."""
    if not user:
        return None
    return user.get("company_id")


def _company_query_for(user) -> dict:
    """Mongo query fragment that enforces company isolation for reads.

    Owner role bypasses isolation for support. If the feature flag is off,
    returns {} — legacy behaviour preserved.
    """
    if not ENFORCE_COMPANY_ISOLATION:
        return {}
    if not user:
        return {}
    # Owner bypasses isolation for cross-company support visibility.
    if user.get("role") == "Owner":
        return {}
    cid = user.get("company_id")
    if not cid:
        return {}
    return {"company_id": cid}


def _apply_company_scope(q: dict, user) -> dict:
    """Merge company-scope clause into an existing query dict."""
    extra = _company_query_for(user)
    if not extra:
        return q
    out = dict(q)
    out.update(extra)
    return out


def _is_manager_role(user) -> bool:
    """Roles that get the manager-style dashboard / oversight pages."""
    return user.get("role") in ("Manager", "SeniorTM", "Admin", "Owner")


def _same_company(user, entity) -> bool:
    """Cross-company guard for individual records."""
    if not ENFORCE_COMPANY_ISOLATION:
        return True
    if not user or not entity:
        return False
    if user.get("role") == "Owner":
        return True
    ucid = user.get("company_id")
    ecid = entity.get("company_id") if isinstance(entity, dict) else None
    if not ucid:
        # Pre-migration user with no company — fail closed.
        return False
    return ucid == ecid


def _assert_same_company(user, entity, *, code: int = 403, detail: str = "Cross-company access forbidden"):
    """Raise HTTP 403 if `entity` doesn't belong to `user`'s company.

    Use immediately after fetching a record by id but before mutating it.
    """
    if _same_company(user, entity):
        return
    raise HTTPException(status_code=code, detail=detail)


def _stamp_company(doc: dict, user) -> dict:
    """In-place attach `company_id` from `user` if not already set."""
    if not doc.get("company_id"):
        cid = _company_id_for(user)
        if cid:
            doc["company_id"] = cid
    return doc


# ============================================================
# Role-aware doctor / TM scoping (require db access)
# ============================================================
async def _doctor_query_for(user) -> dict:
    """Return base mongo query enforcing access scope (RBAC + company isolation)."""
    from server import db  # lazy: avoids server <-> _deps import cycle
    q: dict = {}
    if user["role"] in ("Admin", "Owner"):
        pass
    elif user["role"] == "Manager":
        q["team_id"] = user.get("team_id")
    elif user["role"] == "SeniorTM":
        # Senior TM sees their own doctors + every doctor assigned to a TM
        # they manage (manager_user_id == self.id).
        sub_rows = await db.users.find(
            {"manager_user_id": user["id"], "role": "TM"},
            {"_id": 0, "id": 1},
        ).to_list(2000)
        tm_ids = [r["id"] for r in sub_rows] + [user["id"]]
        q["assigned_tm_id"] = {"$in": tm_ids}
    else:  # TM
        q["assigned_tm_id"] = user["id"]
    return _apply_company_scope(q, user)


async def _can_access_doctor(user, doctor) -> bool:
    from server import db  # lazy
    if not doctor:
        return False
    # Phase C — block cross-company first.
    if not _same_company(user, doctor):
        return False
    if user["role"] == "Owner":
        # Audit P2 — record any Owner read that crosses company boundaries.
        # Idempotency keyed by (owner, target_company, day) so we get one row
        # per Owner per company per day, not a flood per request.
        await _audit_owner_cross_company_read(user, doctor)
        return True
    if user["role"] == "Admin":
        return True
    if user["role"] == "Manager":
        return doctor.get("team_id") == user.get("team_id")
    if user["role"] == "SeniorTM":
        # Senior TM owns their personal doctors AND their sub-team's doctors.
        if doctor.get("assigned_tm_id") == user["id"]:
            return True
        sub = await db.users.find_one(
            {"id": doctor.get("assigned_tm_id"), "manager_user_id": user["id"]},
            {"_id": 0, "id": 1},
        )
        return sub is not None
    return doctor.get("assigned_tm_id") == user["id"]


async def _audit_owner_cross_company_read(user, entity) -> None:
    """Append one audit_logs row when an Owner reads data from another company.

    Idempotency: one row per (owner_id, target_company_id, calendar-day, entity_type).
    Pure observability — never raises so a flaky write doesn't break reads.
    """
    if not isinstance(entity, dict):
        return
    target_company = entity.get("company_id")
    if not target_company:
        return
    owner_company = user.get("company_id")
    if target_company == owner_company:
        return  # same company — not a cross-company read
    try:
        from server import _audit, _now_iso  # lazy
        from datetime import datetime, timezone
        day = datetime.now(timezone.utc).date().isoformat()
        entity_type = "doctor"  # the only call site today; extend when adding more
        idem = f"owner_xc_read|{user.get('id')}|{target_company}|{day}|{entity_type}"
        await _audit(
            user,
            "read",
            entity_type,
            entity.get("id"),
            new={
                "target_company_id": target_company,
                "owner_company_id": owner_company,
                "day": day,
            },
            event_type="owner_cross_company_read",
            idempotency_key=idem,
        )
        _ = _now_iso  # silence unused-import lint
    except Exception:
        # Observability path must not impact the read.
        pass


# Phase L — Senior TM scoping helpers.
# A Senior TM is a TM-hybrid who oversees a sub-team. We resolve their
# "managed view" as themselves + every TM whose manager_user_id == seniorTM.id.
# Manager continues to use team_id (whole team). Admin/Owner = no restriction.
async def _managed_tm_ids_for(user) -> Optional[list[str]]:
    """Return the list of TM user-ids the caller can view as a manager-style scope.

    - Admin / Owner: returns None (meaning "no user-id restriction" — only the
      company scope still applies elsewhere).
    - Manager: every TM/SeniorTM in their team_id.
    - SeniorTM: themselves + every TM whose manager_user_id == self.id.
    - TM: themselves only.
    """
    from server import db  # lazy
    role = user.get("role")
    if role in ("Admin", "Owner"):
        return None
    q = dict(_company_query_for(user))
    if role == "Manager":
        q["team_id"] = user.get("team_id")
        q["role"] = {"$in": ["TM", "SeniorTM"]}
        rows = await db.users.find(q, {"_id": 0, "id": 1}).to_list(2000)
        return [r["id"] for r in rows]
    if role == "SeniorTM":
        q["manager_user_id"] = user["id"]
        q["role"] = "TM"
        rows = await db.users.find(q, {"_id": 0, "id": 1}).to_list(2000)
        ids = [r["id"] for r in rows]
        # Senior TM also sees their own activity (they log visits like a TM).
        ids.append(user["id"])
        return ids
    # TM
    return [user["id"]]
