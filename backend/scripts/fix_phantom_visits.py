"""One-off migration: find visits that were really just promises, and undo them.

WHY THIS EXISTS
Before the "log_promise" intent was added, the AI had no way to classify
"I promised Dr X I'd send the pricing info" as anything other than a visit.
Notes like that were logged through the smart-action path (Telegram / Quick
Capture) as a full VISIT record — a "phantom visit". Each phantom then:
  * showed on the calendar as if a visit had happened, and
  * inflated the weekly report's visit count.

The promise itself was NOT lost: create_visit already turned each detected
promise into a real task linked to the doctor. So the pollution is only the
extra visit row.

WHAT IT DOES
  1. Cheap DB pre-filter for plausible phantoms (AI-created, has note text,
     and by default no topics/barriers) — keeps the AI bill to candidates
     only. --thorough drops the topics/barriers condition, since the AI often
     tags a topic even on a note that is purely a promise.
  2. Re-classifies each candidate's ORIGINAL note text with the SAME
     analyze_note() the app now uses. Only notes the AI now calls
     "log_promise" are treated as phantoms — no bespoke regex heuristics
     that could drift from real behaviour.
  3. If a phantom has no surviving promise task, recreates it first so the
     commitment is never lost.
  4. SOFT-deletes the visit (sets deleted_at) — the same reversible delete
     the app itself uses. Nothing is ever hard-deleted.

SAFETY
  * DRY RUN BY DEFAULT. Prints exactly what it would do and changes nothing.
  * Requires an explicit --apply to write, and --yes to skip the prompt.
  * Soft-delete only, so any mistake is reversible by clearing deleted_at.
  * Every change is written to the audit_logs collection.

USAGE (from /app inside the backend container, or any env with MONGO_URL set
to the target database — on Render that is production):

    # 1. review first — writes nothing
    python -m scripts.fix_phantom_visits --since 2026-07-01

    # widen the net if that finds fewer candidates than you expect
    python -m scripts.fix_phantom_visits --thorough

    # 2. apply once you're happy with the list
    python -m scripts.fix_phantom_visits --since 2026-07-01 --apply

Useful filters: --tm-email, --since, --until, --limit.
"""
from dotenv import load_dotenv
load_dotenv()

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorClient

from ai import analyze_note


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


NOT_DELETED = {"$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]}


async def find_candidates(db, args) -> list:
    """Cheap DB-side pre-filter. Deliberately permissive — the AI re-check in
    classify() is what actually decides.

    By default a visit that recorded topics or barriers is treated as a real
    conversation and skipped. That is a cost optimisation, not a rule: the AI
    often tags a topic ("Invisalign pricing") even on a note that is purely a
    promise, so a genuine phantom can carry topics and be missed. Pass
    --thorough to drop that condition and AI-check every AI-created visit.
    """
    q = {
        **NOT_DELETED,
        "free_text_note": {"$nin": [None, ""]},
        # Came from the AI smart-action path. A visit typed manually through
        # the Log Visit form was a deliberate choice by the user — not ours to
        # second-guess.
        "ai_extraction": {"$ne": None},
    }
    if not args.thorough:
        q["$and"] = [
            {"$or": [{"confirmed_topics": {"$size": 0}}, {"confirmed_topics": {"$exists": False}}]},
            {"$or": [{"confirmed_barriers": {"$size": 0}}, {"confirmed_barriers": {"$exists": False}}]},
        ]
    if args.since:
        q.setdefault("visit_date", {})["$gte"] = args.since
    if args.until:
        q.setdefault("visit_date", {})["$lte"] = args.until + "T23:59:59"
    if args.tm_email:
        user = await db.users.find_one({"email": args.tm_email.lower().strip()}, {"_id": 0, "id": 1})
        if not user:
            print(f"!! No user with email {args.tm_email!r} — nothing to do.")
            return []
        q["tm_user_id"] = user["id"]

    return await db.visits.find(q, {"_id": 0}).sort("visit_date", 1).to_list(args.limit)


async def classify(db, visit) -> dict | None:
    """Re-run the CURRENT classifier over the original note. Returns the AI
    result only when it now reads as a pure promise."""
    tz = None
    user = await db.users.find_one({"id": visit["tm_user_id"]}, {"_id": 0, "timezone": 1})
    if user:
        tz = user.get("timezone")
    result = await analyze_note(
        visit.get("free_text_note") or "",
        session_id=f"phantom-check-{visit['id']}",
        user_timezone=tz,
    )
    if result.get("ai_error"):
        print(f"   !! AI error on visit {visit['id']}: {result['ai_error']} — SKIPPING (left untouched)")
        return None
    return result if result.get("intent") == "log_promise" else None


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="actually write changes (default: dry run)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt (implies --apply intent)")
    ap.add_argument("--tm-email", help="only this TM's visits")
    ap.add_argument("--since", help="earliest visit_date, YYYY-MM-DD")
    ap.add_argument("--until", help="latest visit_date, YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=500, help="max candidates to inspect (default 500)")
    ap.add_argument("--thorough", action="store_true",
                    help="AI-check every AI-created visit, including ones that recorded "
                         "topics/barriers (slower + more AI calls, but catches phantoms "
                         "the AI happened to tag with a topic)")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        sys.exit("MONGO_URL and DB_NAME must be set.")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # Show which database is being touched — this script may be pointed at
    # production, and the operator should be able to see that before saying yes.
    host = mongo_url.split("@")[-1].split("/")[0]
    mode = "APPLY (will write)" if args.apply else "DRY RUN (no changes)"
    print(f"\nDatabase : {db_name} @ {host}")
    print(f"Mode     : {mode}\n")

    candidates = await find_candidates(db, args)
    print(f"Pre-filter matched {len(candidates)} visit(s) worth AI-checking.\n")

    phantoms = []
    for v in candidates:
        result = await classify(db, v)
        if not result:
            continue
        tasks = await db.tasks.find(
            {"visit_id": v["id"], **NOT_DELETED}, {"_id": 0, "id": 1, "task_title": 1}
        ).to_list(20)
        doctor = await db.doctors.find_one({"id": v.get("doctor_id")}, {"_id": 0, "doctor_name": 1})
        phantoms.append({"visit": v, "ai": result, "tasks": tasks, "doctor": doctor})

    if not phantoms:
        print("No phantom visits found. Nothing to do.")
        client.close()
        return

    print(f"=== {len(phantoms)} PHANTOM VISIT(S) — promises logged as visits ===\n")
    for i, p in enumerate(phantoms, 1):
        v, tasks = p["visit"], p["tasks"]
        note = (v.get("free_text_note") or "").replace("\n", " ")
        print(f"{i}. visit {v['id']}  ·  {(v.get('visit_date') or '')[:10]}")
        print(f"   doctor : {(p['doctor'] or {}).get('doctor_name', '(unknown)')}")
        print(f"   note   : {note[:110]}{'…' if len(note) > 110 else ''}")
        if tasks:
            print(f"   promise: already saved as a task — {'; '.join(t['task_title'] for t in tasks)}")
        else:
            titles = [x.get("task_title") for x in (p["ai"].get("promises_detected") or []) if x.get("task_title")]
            print(f"   promise: NO task exists — will create: {'; '.join(titles) or '(none detected)'}")
        print()

    if not args.apply:
        print("DRY RUN — nothing was changed.")
        print("Re-run with --apply once the list above looks right.")
        client.close()
        return

    if not args.yes:
        print(f"About to soft-delete {len(phantoms)} visit(s) in '{db_name}'.")
        if input("Type 'yes' to proceed: ").strip().lower() != "yes":
            print("Aborted — nothing changed.")
            client.close()
            return

    deleted = created = 0
    for p in phantoms:
        v, tasks = p["visit"], p["tasks"]
        # Never drop the commitment: if the promise has no surviving task,
        # recreate it BEFORE retiring the visit it came from.
        if not tasks:
            for pr in (p["ai"].get("promises_detected") or []):
                title = (pr.get("task_title") or "").strip()
                if not title:
                    continue
                due = pr.get("suggested_due_date")
                if not due:
                    base = (v.get("visit_date") or _now_iso())[:10]
                    due = (datetime.fromisoformat(base).date() + timedelta(days=14)).isoformat()
                await db.tasks.insert_one({
                    "id": str(uuid.uuid4()),
                    "doctor_id": v.get("doctor_id"),
                    "tm_user_id": v["tm_user_id"],
                    "team_id": v.get("team_id"),
                    "company_id": v.get("company_id"),
                    "visit_id": None,  # the visit is being retired
                    "task_title": title,
                    "task_description": pr.get("task_description") or "",
                    "due_date": due,
                    "priority": pr.get("priority") if pr.get("priority") in ("Low", "Medium", "High") else "Medium",
                    "status": "Open",
                    "created_from_ai": True,
                    "ai_confirmed": True,
                    "category": "other",
                    "created_at": _now_iso(),
                    "updated_at": _now_iso(),
                    "completed_at": None,
                    "deleted_at": None,
                })
                created += 1

        now = _now_iso()
        await db.visits.update_one({"id": v["id"]}, {"$set": {"deleted_at": now, "updated_at": now}})
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": v["tm_user_id"],
            "action": "delete",
            "entity": "visit",
            "entity_id": v["id"],
            "event_type": "phantom_visit_retired",
            "new": {"deleted_at": now, "reason": "promise mis-logged as visit (fix_phantom_visits migration)"},
            "timestamp": now,
            "company_id": v.get("company_id"),
        })
        deleted += 1

    print(f"\nDone. Soft-deleted {deleted} phantom visit(s); recreated {created} missing promise task(s).")
    print("Reversible: clear deleted_at on those visit ids to restore them.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
