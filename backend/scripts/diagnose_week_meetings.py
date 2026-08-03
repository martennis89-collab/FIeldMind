"""READ-ONLY diagnostic: why does the weekly report count N meetings?

Writes NOTHING. Safe to run against production.

Prints, for one TM and one week:
  * the exact Mon->Sun window the report normalises to
  * every meeting in a padded window around it
  * for each meeting, whether the REPORT counts it, whether the CALENDAR
    shows it, and — when they disagree — precisely which filter is
    responsible (owner / demo / cancelled / soft-deleted / outside window)

The padding matters: a meeting stored with a timezone offset can land just
outside the window in UTC even though it looks in-week on screen, so we
deliberately look wider than the report does and flag anything that only
just missed.

USAGE (Render shell, or any env with MONGO_URL pointing at the target DB):

    cd /app && python -m scripts.diagnose_week_meetings \
        --tm-email you@example.com --week 2026-07-27
"""
from dotenv import load_dotenv
load_dotenv()

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorClient

NOT_DELETED = {"$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]}


def week_bounds(anchor: datetime):
    monday = (anchor - timedelta(days=anchor.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return monday, sunday


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tm-email", required=True)
    ap.add_argument("--week", required=True, help="any date inside the target week, YYYY-MM-DD")
    args = ap.parse_args()

    mongo_url, db_name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        sys.exit("MONGO_URL and DB_NAME must be set.")
    db = AsyncIOMotorClient(mongo_url)[db_name]

    print(f"\nDatabase: {db_name} @ {mongo_url.split('@')[-1].split('/')[0]}   (READ-ONLY)\n")

    user = await db.users.find_one({"email": args.tm_email.lower().strip()}, {"_id": 0})
    if not user:
        sys.exit(f"No user with email {args.tm_email!r}")

    anchor = datetime.fromisoformat(args.week).replace(tzinfo=timezone.utc)
    monday, sunday = week_bounds(anchor)
    ws, we = monday.date().isoformat(), sunday.date().isoformat()
    lo, hi = ws, we + "T23:59:59"

    print(f"TM        : {user.get('full_name')}  <{user.get('email')}>  role={user.get('role')}")
    print(f"user id   : {user['id']}")
    print(f"Report week: {ws} -> {we}   (matches scheduled_at >= '{lo}' and <= '{hi}')\n")

    # Deliberately wider than the report, so near-misses are visible.
    pad_lo = (monday - timedelta(days=2)).date().isoformat()
    pad_hi = (sunday + timedelta(days=2)).date().isoformat() + "T23:59:59"
    rows = await db.meetings.find(
        {"scheduled_at": {"$gte": pad_lo, "$lte": pad_hi}}, {"_id": 0}
    ).sort("scheduled_at", 1).to_list(1000)

    # Who the calendar would show for this user (mirrors routers/meetings.list_meetings)
    if user["role"] == "TM":
        cal_owners = {user["id"]}
    elif user["role"] == "SeniorTM":
        subs = await db.users.find({"manager_user_id": user["id"], "role": "TM"}, {"_id": 0, "id": 1}).to_list(500)
        cal_owners = {user["id"]} | {s["id"] for s in subs}
    else:
        cal_owners = None  # manager/admin — team or all

    counted = shown = 0
    print(f"{'scheduled_at':34s} {'doctor':22s} {'status':10s} rpt cal  why-not")
    print("-" * 104)
    for m in rows:
        sched = m.get("scheduled_at") or ""
        in_window = lo <= sched <= hi
        is_mine = m.get("tm_user_id") == user["id"]
        is_demo = bool(m.get("is_demo"))
        cancelled = m.get("status") == "Cancelled"
        deleted = m.get("deleted_at") is not None

        in_report = in_window and is_mine and not is_demo and not cancelled and not deleted
        on_calendar = (not deleted) and (cal_owners is None or m.get("tm_user_id") in cal_owners)

        reasons = []
        if not in_window:
            reasons.append(f"outside week (stored {sched[:10]})")
        if not is_mine:
            reasons.append("owned by another TM")
        if is_demo:
            reasons.append("is_demo -> counted as demo, not meeting")
        if cancelled:
            reasons.append("cancelled")
        if deleted:
            reasons.append("soft-deleted")

        counted += in_report
        shown += on_calendar
        print(f"{sched[:34]:34s} {str(m.get('doctor_name'))[:22]:22s} {str(m.get('status'))[:10]:10s} "
              f"{'Y' if in_report else '.':3s} {'Y' if on_calendar else '.':3s}  {'; '.join(reasons)}")

    print("-" * 104)
    print(f"\nREPORT counts   : {counted} meeting(s)")
    print(f"CALENDAR shows  : {shown} meeting(s) in the padded range")
    if counted != shown:
        print("\nThe two disagree — see the why-not column above for the exact reason per row.")


if __name__ == "__main__":
    asyncio.run(main())
