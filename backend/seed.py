"""Idempotent demo seed."""
from datetime import datetime, timezone, timedelta
import uuid
from auth import hash_password


def _uuid():
    return str(uuid.uuid4())


def _iso(dt=None):
    return (dt or datetime.now(timezone.utc)).isoformat()


async def seed_demo(db) -> dict:
    """Create demo users/team/doctors/visits/tasks if not present.
    Returns a small report."""
    report = {"created": {}, "skipped": False}

    # Skip if admin already exists
    existing_admin = await db.users.find_one({"email": "admin@field.io"})
    if existing_admin:
        report["skipped"] = True
        return report

    now = _iso()

    # Team
    team_id = _uuid()
    team = {
        "id": team_id,
        "team_name": "Northern Region",
        "manager_user_id": None,
        "region": "North",
        "created_at": now,
        "updated_at": now,
    }

    # Users
    admin_id, mgr_id, tm1_id, tm2_id = _uuid(), _uuid(), _uuid(), _uuid()
    users = [
        {
            "id": admin_id,
            "full_name": "Alice Admin",
            "email": "admin@field.io",
            "password_hash": hash_password("admin123"),
            "role": "Admin",
            "team_id": None,
            "region": None,
            "active_status": True,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": mgr_id,
            "full_name": "Marko Manager",
            "email": "manager@field.io",
            "password_hash": hash_password("manager123"),
            "role": "Manager",
            "team_id": team_id,
            "region": "North",
            "active_status": True,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": tm1_id,
            "full_name": "Tina TM",
            "email": "tm1@field.io",
            "password_hash": hash_password("tm123"),
            "role": "TM",
            "team_id": team_id,
            "region": "North",
            "active_status": True,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": tm2_id,
            "full_name": "Theo TM",
            "email": "tm2@field.io",
            "password_hash": hash_password("tm123"),
            "role": "TM",
            "team_id": team_id,
            "region": "North",
            "active_status": True,
            "created_at": now,
            "updated_at": now,
        },
    ]

    team["manager_user_id"] = mgr_id

    # Doctors
    cities = ["Sofia", "Plovdiv", "Varna", "Burgas", "Ruse"]
    segments = ["Occasional", "Active", "Engaged", "Expert"]
    types_ = ["GP", "Ortho", "GP", "Ortho", "GP"]
    doc_specs = [
        ("Dr. Ivanov", "Smile Studio", 0, 1, tm1_id),
        ("Dr. Petrova", "Bright Dental", 1, 2, tm1_id),
        ("Dr. Georgiev", "Aligned Smiles", 2, 0, tm1_id),
        ("Dr. Dimitrova", "Modern Ortho", 3, 3, tm1_id),
        ("Dr. Stoyanov", "Family Dental", 0, 0, tm1_id),
        ("Dr. Nikolova", "Pearl Dental", 1, 1, tm2_id),
        ("Dr. Kolev", "City Ortho", 4, 3, tm2_id),
        ("Dr. Marinova", "Premium Smile", 2, 2, tm2_id),
        ("Dr. Todorov", "Fresh Dental", 3, 0, tm2_id),
        ("Dr. Hristova", "Crown Clinic", 0, 1, tm2_id),
    ]
    doctors = []
    for name, clinic, ci, si, tm in doc_specs:
        doctors.append(
            {
                "id": _uuid(),
                "doctor_name": name,
                "clinic_name": clinic,
                "city": cities[ci],
                "region": "North",
                "doctor_type": types_[ci],
                "segment": segments[si],
                "assigned_tm_id": tm,
                "team_id": team_id,
                "status": "Active",
                "general_notes": "",
                "created_at": now,
                "updated_at": now,
            }
        )

    # Visits + tasks
    visits = []
    tasks = []
    visit_templates = [
        {
            "note": "Dr says Invisalign is too expensive for patients but wants to start offering it more. She didn't know about the growth programs. I promised to send her certification info.",
            "topics": ["Invisalign pricing", "Growth programs awareness", "Certification interest"],
            "barriers": ["Patient affordability concern", "Does not understand growth programs"],
            "sentiment": "Neutral",
            "op": "Stuck",
            "next_step": "Explain growth program options",
            "promise": "Send certification info",
            "due_offset": 4,
        },
        {
            "note": "Doctor very interested in iTero demo. Asked about complex extraction cases. Wants P2P with experienced ortho.",
            "topics": ["iTero demo", "Extraction cases", "Peer-to-peer"],
            "barriers": ["Complex case uncertainty"],
            "sentiment": "Positive",
            "op": "Advancing",
            "next_step": "Arrange P2P call",
            "promise": "Arrange P2P with senior ortho",
            "due_offset": 2,
        },
        {
            "note": "Doctor prefers braces, says aligners are unprofitable. Negative past experience. Not open right now.",
            "topics": ["Case acceptance"],
            "barriers": ["Prefers braces", "Believes braces are more profitable", "Negative past aligner experience"],
            "sentiment": "Negative",
            "op": "Blocked",
            "next_step": "Revisit in 60 days with new clinical evidence",
            "promise": None,
            "due_offset": 0,
        },
        {
            "note": "Quick chat at event. Doctor curious about ClinCheck and digital workflow. Asked for staff training.",
            "topics": ["ClinCheck understanding", "Digital workflow", "Staff training"],
            "barriers": ["Staff not trained"],
            "sentiment": "Positive",
            "op": "Advancing",
            "next_step": "Schedule staff training session",
            "promise": "Send TPS info and book training slot",
            "due_offset": 3,
        },
        {
            "note": "Discussed pricing fairness vs competitors. Doctor unsure about case selection.",
            "topics": ["Invisalign pricing", "Case selection confidence"],
            "barriers": ["Perceived unfair pricing", "Low clinical confidence"],
            "sentiment": "Neutral",
            "op": "Stuck",
            "next_step": "Send case selection guide",
            "promise": "Send case selection guide",
            "due_offset": -2,  # overdue
        },
    ]

    for idx, doc in enumerate(doctors):
        # 1-3 visits per doctor across last 80 days
        n_visits = 1 + (idx % 3)
        for j in range(n_visits):
            tpl = visit_templates[(idx + j) % len(visit_templates)]
            days_ago = 5 + j * 20 + (idx * 3) % 30
            vdate = datetime.now(timezone.utc) - timedelta(days=days_ago)
            visit_id = _uuid()
            ai_extraction = {
                "summary": tpl["note"][:140],
                "topics": tpl["topics"],
                "barriers": tpl["barriers"],
                "sentiment": tpl["sentiment"],
                "opportunity_state": tpl["op"],
                "promises_detected": [],
                "suggested_next_action": tpl["next_step"],
                "market_signals": [],
                "privacy_warnings": [],
            }
            visit = {
                "id": visit_id,
                "doctor_id": doc["id"],
                "tm_user_id": doc["assigned_tm_id"],
                "team_id": team_id,
                "visit_date": _iso(vdate),
                "visit_type": "In-person visit",
                "free_text_note": tpl["note"],
                "confirmed_topics": tpl["topics"],
                "confirmed_barriers": tpl["barriers"],
                "sentiment": tpl["sentiment"],
                "opportunity_state": tpl["op"],
                "next_step": tpl["next_step"],
                "ai_extraction": ai_extraction,
                "created_at": _iso(vdate),
                "updated_at": _iso(vdate),
            }
            visits.append(visit)

            if tpl["promise"] and j == 0:
                due = datetime.now(timezone.utc) + timedelta(days=tpl["due_offset"])
                status = "Overdue" if tpl["due_offset"] < 0 else "Open"
                tasks.append(
                    {
                        "id": _uuid(),
                        "doctor_id": doc["id"],
                        "tm_user_id": doc["assigned_tm_id"],
                        "team_id": team_id,
                        "visit_id": visit_id,
                        "task_title": tpl["promise"],
                        "task_description": tpl["next_step"],
                        "due_date": due.date().isoformat(),
                        "priority": "High" if tpl["due_offset"] < 0 else "Medium",
                        "status": status,
                        "created_from_ai": True,
                        "created_at": _iso(vdate),
                        "updated_at": _iso(vdate),
                        "completed_at": None,
                    }
                )

    # Insert
    await db.users.insert_many(users)
    await db.teams.insert_one(team)
    await db.doctors.insert_many(doctors)
    if visits:
        await db.visits.insert_many(visits)
    if tasks:
        await db.tasks.insert_many(tasks)

    report["created"] = {
        "users": len(users),
        "teams": 1,
        "doctors": len(doctors),
        "visits": len(visits),
        "tasks": len(tasks),
    }
    return report
