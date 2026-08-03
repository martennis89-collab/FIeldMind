"""One-off migration: fold every visit into the meetings collection.

Meetings become the single record of doctor activity. A meeting with
status="Completed" now IS "this interaction happened" — the role visits used
to play. This script moves the existing history across so nothing is lost.

For each visit:
  * if it is already linked to a meeting (either direction — visit.meeting_id
    or meeting.visit_id), the visit's outcome fields are MERGED onto that
    meeting and it is marked Completed. No duplicate is created.
  * otherwise a new Completed meeting is created carrying the visit's date,
    doctor, note, sentiment, topics/barriers and the itero/invisalign/
    commercial action blocks.
  * the visit is then SOFT-deleted (deleted_at), never dropped.

Idempotent: a visit that already has a corresponding meeting (matched by
migrated_from_visit_id) is skipped, so re-running is safe.

SAFETY
  * DRY RUN BY DEFAULT — prints a summary and changes nothing.
  * --apply to write; --yes to skip the prompt.
  * Soft-delete only. To roll back: clear deleted_at on the visits and delete
    meetings where migrated_from_visit_id is set.

USAGE (Render shell, or any env with MONGO_URL pointing at the target DB):
    cd /app && python -m scripts.migrate_visits_to_meetings
    cd /app && python -m scripts.migrate_visits_to_meetings --apply
"""
from dotenv import load_dotenv
load_dotenv()

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

NOT_DELETED = {"$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]}

# Visit field -> Meeting field. Everything else is copied verbatim.
OUTCOME_FIELDS = [
    "free_text_note", "confirmed_topics", "confirmed_barriers", "sentiment",
    "opportunity_state", "next_step", "ai_extraction", "itero_actions",
    "invisalign_actions", "commercial_actions", "visit_type",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def outcome_from(visit: dict) -> dict:
    out = {f: visit[f] for f in OUTCOME_FIELDS if visit.get(f) is not None}
    out["status"] = "Completed"
    out["completed_at"] = visit.get("visit_date") or visit.get("created_at") or _now_iso()
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--limit", type=int, default=100000)
    args = ap.parse_args()

    mongo_url, db_name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        sys.exit("MONGO_URL and DB_NAME must be set.")
    db = AsyncIOMotorClient(mongo_url)[db_name]

    print(f"\nDatabase: {db_name} @ {mongo_url.split('@')[-1].split('/')[0]}")
    print(f"Mode    : {'APPLY (will write)' if args.apply else 'DRY RUN (no changes)'}\n")

    visits = await db.visits.find(NOT_DELETED, {"_id": 0}).sort("visit_date", 1).to_list(args.limit)
    print(f"{len(visits)} live visit(s) to migrate.\n")
    if not visits:
        return

    merged = created = skipped = 0
    plan = []
    for v in visits:
        # Already migrated on a previous run?
        if await db.meetings.find_one({"migrated_from_visit_id": v["id"]}, {"_id": 1}):
            skipped += 1
            continue

        target = None
        if v.get("meeting_id"):
            target = await db.meetings.find_one({"id": v["meeting_id"]}, {"_id": 0, "id": 1})
        if not target:
            target = await db.meetings.find_one({"visit_id": v["id"]}, {"_id": 0, "id": 1})

        if target:
            merged += 1
            plan.append(("merge", v, target["id"]))
        else:
            created += 1
            plan.append(("create", v, None))

    print(f"  merge into an existing meeting : {merged}")
    print(f"  create a new Completed meeting : {created}")
    print(f"  already migrated (skipped)     : {skipped}\n")

    for action, v, mid in plan[:10]:
        note = (v.get("free_text_note") or "").replace("\n", " ")[:60]
        print(f"  [{action:6s}] {(v.get('visit_date') or '')[:10]}  {note}{'…' if len(note) == 60 else ''}")
    if len(plan) > 10:
        print(f"  … and {len(plan) - 10} more")

    if not args.apply:
        print("\nDRY RUN — nothing changed. Re-run with --apply when the plan looks right.")
        return
    if not args.yes:
        print(f"\nAbout to write {len(plan)} change(s) to '{db_name}'.")
        if input("Type 'yes' to proceed: ").strip().lower() != "yes":
            print("Aborted.")
            return

    for action, v, mid in plan:
        outcome = outcome_from(v)
        if action == "merge":
            outcome["migrated_from_visit_id"] = v["id"]
            outcome["updated_at"] = _now_iso()
            await db.meetings.update_one({"id": mid}, {"$set": outcome})
        else:
            doctor = await db.doctors.find_one(
                {"id": v.get("doctor_id")}, {"_id": 0, "doctor_name": 1, "clinic_name": 1, "city": 1}
            ) or {}
            tm = await db.users.find_one({"id": v.get("tm_user_id")}, {"_id": 0, "full_name": 1}) or {}
            doc = {
                "id": str(uuid.uuid4()),
                "migrated_from_visit_id": v["id"],
                "company_id": v.get("company_id"),
                "doctor_id": v.get("doctor_id"),
                "doctor_name": doctor.get("doctor_name", ""),
                "clinic_name": doctor.get("clinic_name"),
                "city": doctor.get("city"),
                "tm_user_id": v.get("tm_user_id"),
                "tm_name": tm.get("full_name", ""),
                "team_id": v.get("team_id"),
                # The visit's date IS when the interaction happened.
                "scheduled_at": v.get("visit_date") or v.get("created_at"),
                "duration_minutes": 30,
                "subject": None,
                "is_demo": bool((v.get("itero_actions") or {}).get("demo_completed")),
                "track_type": v.get("track_type") or "General",
                "is_draft": False,
                "deleted_at": None,
                "visit_id": None,
                "created_at": v.get("created_at") or _now_iso(),
                "updated_at": _now_iso(),
                **outcome,
            }
            await db.meetings.insert_one(doc)

        now = _now_iso()
        await db.visits.update_one({"id": v["id"]}, {"$set": {"deleted_at": now, "updated_at": now}})

    print(f"\nDone. Merged {merged}, created {created}, skipped {skipped}. Visits soft-deleted.")
    print("Rollback: clear deleted_at on visits, and delete meetings with migrated_from_visit_id set.")


if __name__ == "__main__":
    asyncio.run(main())
