# FieldMind — Field Intelligence Platform PRD

## Original problem statement
Build a secure, production-ready, multi-user Field Intelligence Platform for Territory Managers in the dental/medical (Invisalign/aligners) industry. NOT a CRM. Helps TMs log doctor interactions, remember what was discussed, track promises/follow-ups, identify market sentiment, and surface aggregated insights for managers. Highest priority: SECURITY → UX → intelligence.

Positioning: "Salesforce records that an activity happened. FieldMind remembers what was discussed, what was promised, what the market is saying, and which doctors need attention next."

## User personas
- **TM (Territory Manager)** — sees only their own assigned doctors, visits, tasks, notes.
- **Manager** — team-level dashboards and aggregated insights; sees assigned team activity.
- **Admin** — manages users, teams, doctors, taxonomy, audit logs, settings.

## Architecture
- **Backend**: FastAPI + Motor (MongoDB). Files: `server.py` (routes), `auth.py` (JWT+bcrypt+RBAC), `models.py` (Pydantic), `ai.py` (Claude Sonnet 4.5 via `emergentintegrations`), `seed.py` (idempotent demo seed). All routes prefixed `/api`. JWT bearer auth. Server-side ownership/team checks on every query.
- **Frontend**: React 19 + react-router 7 + shadcn/ui + lucide-react + sonner. AuthContext + ProtectedRoute. Mobile-first earthy design (#FDFBF7 bg, #274035 forest green primary, #C26D53 secondary, #7CA1B4 accent), Outfit + IBM Plex Sans fonts.
- **DB**: MongoDB collections — users, teams, doctors, visits, tasks, audit_logs. Indexes on doctor_name (text), assigned_tm_id, team_id, due_date, visit_date.

## Implemented (Phase 1 MVP — Feb 2026)
- JWT auth (login/logout/me) with bcrypt + role-based access control (TM/Manager/Admin) enforced on backend
- Team & user management (Admin)
- Doctor database with computed enrichment: last_visit_date, days_since_last_visit, visits_this_quarter, open/overdue promises, top topics & barriers (last 10 visits), current sentiment + trend, cadence_status, visit_priority_score (0–100) + label
- Visit logging — 3-step mobile-first wizard (<60s): pick doctor → free-text note (with privacy warning) → AI analysis & confirm tags/promises → save. Original note preserved untouched.
- AI extraction via Claude Sonnet 4.5 + Emergent Universal LLM Key — returns summary, topics (controlled vocab), barriers, sentiment, opportunity_state, promises_detected, suggested_next_action, market_signals, privacy_warnings (patient name detection)
- Promise/task auto-creation from confirmed AI promises; default due +3 business days; bucketed list (Overdue/Today/Week/Later/Completed) with one-click complete
- TM dashboard: stats, top priority doctors sorted by visit_priority_score, "promises you owe" overdue section
- Manager dashboard: team stats, market pulse text, top barriers/topics (30d), sentiment distribution, sentiment-by-segment, by-TM activity, under-visited high-segment doctors
- Doctor profile: Prepare-for-visit (suggested reason, talking points), full Timeline (all visits with notes/tags), Promises tab (open + completed)
- Global search across doctors, visit notes, promises (RBAC-scoped)
- Filtering: doctor list by segment / cadence / city + text search
- Admin: user CRUD (activate/deactivate), team CRUD, audit log viewer
- Audit logging on auth, create/update of users/doctors/teams/visits/tasks
- Idempotent demo seed: 1 admin, 1 manager, 2 TMs, 10 doctors, 19 visits, 8 tasks (incl. overdue)
- Cadence presets per segment (Occasional 60d / Active 45d / Engaged 30d / Expert 21d)
- Privacy guardrails: in-app warnings on note input + AI-side patient-name detection

## Test coverage
- Backend: 21/21 pytest cases passing (auth, RBAC, filters, AI live call, visit save, task buckets, dashboards, search, admin)
- Frontend: full E2E across all roles (login, dashboard, doctors, profile, log-visit, tasks, search, admin, logout)

## Backlog (next phases)
**P1**
- Voice-to-text note capture for mobile field use
- Weekly report generator with PDF/CSV export
- Advanced market intelligence dashboard with date/segment/city filters and trend charts
- Editable Admin taxonomy (custom topics & barriers per region)

**P2**
- Expense tracking module with receipt photo upload + OCR (deferred per user request)
- Configurable cadence per team
- Soft-delete + archive for inactive doctors
- view_sensitive / export audit action types
- Doctor assignment bulk operations
- Refactor `server.py` (~950 lines) into routers (auth/doctors/visits/tasks/dashboards/admin)
- Aggregation pipelines for `_enrich_doctor` to scale beyond a few hundred doctors
