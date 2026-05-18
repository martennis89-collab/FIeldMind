"""One-shot demo-data seeder for showcasing FieldMind.

Creates a deliberately bumpy field-execution profile for tm1@field.io (Maria)
so the Insight Cards + Advisory Layer + FEI all light up during the demo.

Expected outcome (after running):
  • Promise completion rate ≈ 30%  → High severity insight card.
  • Overdue promise rate ≈ 50%     → High severity insight card.
  • iTero discussed → booked ≈ 17% → High severity insight card.
  • iTero booked → completed = 0%  → High severity insight card.
  • Weekly report submission ≈ 50% → Medium severity insight card.
  • Field Execution Index ≈ 18/100 → "Field Execution Index is low" advisory card.

Also creates 1 manager-assigned Intervention so the TM's
"Manager follow-up" panel renders on the dashboard.

Run from /app/backend with:
    python -m demo.seed_low_fei

Idempotent: re-running clears tm1's previous demo rows first.
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient


TM_EMAIL = "tm1@field.io"
MANAGER_EMAIL = "manager@field.io"


def _iso(dt=None):
    return (dt or datetime.now(timezone.utc)).isoformat()


def _today():
    return datetime.now(timezone.utc).date()


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    tm = await db.users.find_one({"email": TM_EMAIL}, {"_id": 0})
    mgr = await db.users.find_one({"email": MANAGER_EMAIL}, {"_id": 0})
    if not tm or not mgr:
        print("FATAL: tm1@field.io or manager@field.io not found. Run POST /api/seed/init first.")
        return

    tm_id = tm["id"]
    cid = tm.get("company_id")
    team_id = tm.get("team_id")
    print(f"Seeding demo for TM {tm['full_name']} ({tm_id}) in company {cid}")

    # 1) Find or create a couple of doctors for this TM
    doctors = await db.doctors.find({"assigned_tm_id": tm_id}, {"_id": 0}).limit(8).to_list(8)
    if len(doctors) < 5:
        print("FATAL: TM has fewer than 5 doctors. Run POST /api/seed/init first.")
        return
    print(f"  found {len(doctors)} doctors")

    # 2) Wipe Maria's TASKS / SIGNALS / REPORTS / MEETINGS / INSIGHT CARDS so the demo lights
    #    up cleanly — otherwise her historical activity dilutes the metric values.
    today_iso = _today().isoformat()
    await db.tasks.delete_many({"tm_user_id": tm_id})
    await db.track_signals.delete_many({"tm_user_id": tm_id})
    await db.reports.delete_many({"tm_user_id": tm_id})
    await db.meetings.delete_many({"tm_user_id": tm_id})
    await db.insight_cards.delete_many({"scope_id": tm_id})
    await db.interventions.delete_many({"tm_user_id": tm_id, "issue_title": {"$regex": "^DEMO "}})

    # 3) Promises: 3 completed / 10 total → 30% completion · 5 overdue
    now = _iso()
    past = (_today() - timedelta(days=3)).isoformat()
    future = (_today() + timedelta(days=5)).isoformat()
    promise_rows = []
    for i in range(3):  # completed
        promise_rows.append({
            "id": uuid.uuid4().hex, "tm_user_id": tm_id, "team_id": team_id, "company_id": cid,
            "doctor_id": doctors[i % len(doctors)]["id"],
            "task_title": f"DEMO Follow up with Dr {i+1}",
            "category": "follow up on proposal",
            "status": "Completed", "due_date": today_iso, "completed_at": now,
            "created_at": now, "updated_at": now, "deleted_at": None,
        })
    for i in range(5):  # overdue
        promise_rows.append({
            "id": uuid.uuid4().hex, "tm_user_id": tm_id, "team_id": team_id, "company_id": cid,
            "doctor_id": doctors[(i + 3) % len(doctors)]["id"],
            "task_title": f"DEMO Send Invisalign proposal to Dr {i+1}",
            "category": "send proposal",
            "status": "Open", "due_date": past,
            "created_at": now, "updated_at": now, "deleted_at": None,
        })
    for i in range(2):  # open but on-time
        promise_rows.append({
            "id": uuid.uuid4().hex, "tm_user_id": tm_id, "team_id": team_id, "company_id": cid,
            "doctor_id": doctors[i]["id"],
            "task_title": f"DEMO Confirm iTero demo with Dr {i+1}",
            "category": "arrange demo",
            "status": "Open", "due_date": future,
            "created_at": now, "updated_at": now, "deleted_at": None,
        })
    await db.tasks.insert_many(promise_rows)
    print(f"  inserted {len(promise_rows)} tasks (3 completed, 5 overdue, 2 future)")

    # 4) iTero signals — 6 doctors discussed, only 1 booked, 4 booked but 0 completed
    def _sig(doc_id, sig_type):
        return {
            "id": uuid.uuid4().hex,
            "doctor_id": doc_id, "tm_user_id": tm_id, "team_id": team_id, "company_id": cid,
            "track_type": "iTero", "signal_type": sig_type,
            "signal_date": today_iso, "source": "Manual",
            "created_at": now, "updated_at": now, "deleted_at": None,
            "idempotency_key": f"ts:demo:{doc_id}:{sig_type}:{uuid.uuid4().hex[:6]}",
        }

    sigs = []
    # 6 doctors with "demo discussed"
    for i in range(6):
        sigs.append(_sig(f"demo_disc_{i}", "demo_discussed"))
    # Only 1 of those booked → 1/6 ≈ 17%
    sigs.append(_sig("demo_disc_0", "demo_booked"))
    # Plus 3 more standalone booked doctors with NO completion → booked→completed = 0%
    for i in range(3):
        sigs.append(_sig(f"demo_bok_{i}", "demo_booked"))
    await db.track_signals.insert_many(sigs)
    print(f"  inserted {len(sigs)} iTero track signals")

    # 5) Weekly reports — 2 of last 4 weeks submitted → 50%
    for i in range(2):
        ws = (_today() - timedelta(days=7 * (i + 1))).isoformat()
        await db.reports.insert_one({
            "id": uuid.uuid4().hex, "tm_user_id": tm_id, "team_id": team_id, "company_id": cid,
            "status": "Submitted", "submitted_at": now, "summary": "DEMO weekly summary",
            "week_start": ws,
        })
    print("  inserted 2 weekly reports (of 4 weeks expected)")

    # 6) Pre-create one manager-assigned Intervention so the TM dashboard renders
    #    the "Manager follow-up" panel during the demo.
    await db.interventions.insert_one({
        "id": uuid.uuid4().hex,
        "company_id": cid, "team_id": team_id,
        "manager_id": mgr["id"], "tm_user_id": tm_id,
        "doctor_id": doctors[0]["id"],
        "insight_card_id": None,
        "track_type": "iTero", "severity": "High",
        "issue_title": "DEMO Maria, your iTero discussed-to-booked rate dropped this week",
        "issue_description": "Several doctors discussed an iTero demo but no booking followed. Pair with Stoyan on Wednesday morning calls.",
        "suggested_action": "Re-contact the 5 doctors where the demo was discussed but not booked. Aim to book at least 2 by Friday.",
        "manager_note": "Block 30 min on Wed AM. I'll join the first 2 calls.",
        "status": "Open",
        "due_date": (_today() + timedelta(days=4)).isoformat(),
        "created_from_insight": False,
        "created_at": now, "updated_at": now,
        "completed_at": None, "dismissed_at": None, "deleted_at": None,
    })
    print("  inserted 1 manager-assigned intervention")

    print("\nDemo scenario ready.")
    print("  • Log in as tm1@field.io / tm123 to see:")
    print("      - Manager follow-up panel (1 high-severity intervention)")
    print("      - What to do next: 5+ insight cards (3 High, 1 Medium, 1 FEI advisory)")
    print("      - Field Execution Index ~ 18/100 (Low)")
    print("  • Log in as manager@field.io / manager123 to see:")
    print("      - What needs attention: team insight cards, including Maria's")
    print("      - Intervention tab: 1 Open intervention for Maria")
    print("\nNote: insight cards will materialise the moment any user clicks Refresh on")
    print("the advisory panel (or you can hit POST /api/insights/generate as admin first).")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
