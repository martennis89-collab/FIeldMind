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

## Implemented (Phase 1 MVP — Feb 2026)- JWT auth (login/logout/me) with bcrypt + role-based access control (TM/Manager/Admin) enforced on backend
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
- Backend: 21/21 (iter1) + 8/8 (iter2) pytest cases passing — auth, RBAC, filters, AI live call, visit save, task buckets, dashboards, search, admin, manager performance, weekly reports CRUD + buckets + comments
- Frontend: full E2E across all roles (login, dashboard, doctors, profile, log-visit, tasks, search, admin, logout, performance table, reports flow, manager review)

## Iteration 3 (Feb 2026) — Commercial Actions + Control Tower
- **Commercial Actions Tracking**: each visit now records 13 execution-layer fields (demo_discussed/booked/+date, demo_completed/+date, boost_discussed, trade_in_discussed, trade_in_interest, growth_program_explained, proposal_discussed, proposal_sent/+date, proposal_follow_up_done). AI extraction prompt updated to detect & pre-fill these from the free-text note.
- **Doctor commercial_state**: derived per-doctor aggregate exposed on `_enrich_doctor` — adds days_since_proposal, demo_pending (booked-not-completed), proposal_unfollowed (sent-no-followup).
- **New endpoints**:
  - `GET /api/dashboard/manager/commercial` — demo & proposal funnels (discussed→booked→completed; sent→followed-up), booking/completion/follow-up rates, avg-days-since-proposal, pricing-context coverage % + lists of doctors without boost/trade-in/growth discussion, drop-off alerts, barriers-by-stage (pre-demo / post-demo / post-proposal).
  - `GET /api/dashboard/manager/interventions` — three buckets each with doctor name + assigned TM + issue + suggested_action: **Critical** (proposal>7d unfollowed / demo booked-not-completed / Engaged-Expert ignored), **At-risk** (declining sentiment / overdue promises piling), **High opportunity** (recent demo + no proposal / strong-engagement+pricing-context+no proposal).
- **Performance endpoint extended** with `execution_quality_score (0-100, Low/Med/High)`, `high_priority_visited_pct`, demo & proposal counts per TM, and a `coaching` block (strengths / weaknesses / suggestions).
- **Manager UI cleanup** — Manager nav now ONLY shows: Dashboard / Intervention / Market Intel / Team / Reports. Removed for managers: Doctors browser, Tasks, Search, Log Visit FAB. (Doctor profile still reachable via deep-link from intervention/team lists.)
- **Manager Dashboard = Control Tower**: 4 stat cards (Visits this week, Doctors, Critical, High opportunity) + Alerts strip (drop-offs) + Demo funnel + Proposal funnel + Market pulse + 3 quick-link tiles to Intervention / Team Performance / Market Intelligence.
- **Dedicated pages**: `/intervention` (3 buckets with cards), `/market-intelligence` (top barriers, top topics, barriers by stage, pricing coverage), `/team-performance` (full TM table with EQS pills, flags, expandable strengths/weaknesses/coaching panel).
- **Log Visit (TM)**: review step now includes a "Commercial actions" section with three columns (Demo / Pricing context / Proposal) of checkboxes. AI pre-fills any detected booleans; user confirms/edits before save.
- **Reports updated**: Auto draft includes `demos_discussed/booked/completed` + `proposals_sent/proposals_followed_up`. Auto insights include "✓ N demo completed this week" / "⚠️ N proposal sent — schedule follow-ups".

## Iteration 4 (Feb 2026) — iTero ↔ Invisalign strict separation
- **Visit schema**: added `track_type` enum (`ITERO` / `INVISALIGN` / `BOTH`), `itero_actions` (demo funnel, scanner_interest_level, scanner_concerns) and `invisalign_actions` (growth_program_explained, certification_interest, tps_discussed, p2p_suggested, staff_training_needed, clinical_confidence, business_confidence, patient_affordability_perception). Track-agnostic pricing/proposal stays in `commercial_actions`.
- **AI extraction split**: Claude now returns `track_types[]`, `itero_actions{}`, `invisalign_actions{}` alongside legacy commercial_actions for back-compat.
- **New endpoints (manager + TM)**: `GET /api/dashboard/manager/itero`, `/manager/invisalign`, `/manager/cross-sell`, `/tm/itero`, `/tm/invisalign` — strict track filtering at the query level (Invisalign-only visits never affect iTero demo funnel and vice-versa).
- **Doctor enrichment**: now exposes `itero_state` + `invisalign_state` (9 keys each) alongside the legacy `commercial_state`.
- **Manager nav**: Dashboard / iTero / Invisalign / Intervention / Team / Reports (Market Intel / Doctors / Tasks / Search removed).
- **TM nav**: Dashboard / iTero / Invisalign / Doctors / Tasks / Reports.
- **Manager Control Tower**: cross-sell panel (3 columns: iTero only, Invisalign only, Both) + quick-link tiles to /itero and /invisalign. Dedicated pages render: scanner demo funnel + alerts + by-TM (iTero) / coverage + confidence + by-segment + growth-opps (Invisalign).
- **TM /itero & /invisalign**: track-specific dashboards (discussed/booked/completed for iTero; certification interest, TPS needs, confidence barriers for Invisalign).
- **Log Visit Step 3**: track selector (iTero / Invisalign / Both) toggles iTero block + Invisalign block. AI pre-fills both.

## Iteration 4 polish (Feb 2026)
- Renamed test ids for Playwright reliability: `pick-doctor-{id}` → `doctor-option-{id}`; `skip-ai-btn` → `step2-skip-ai-btn`; `analyze-btn` → `step2-analyze-btn`.
- Updated legacy iter-3 pytest suite (`test_commercial_and_control_tower.py`) to match new commercial_actions shape (demo_* moved to itero_actions; growth_program_explained moved to invisalign_actions). All 58 backend tests pass.

## Iteration 2 (Feb 2026) — Manager Control Dashboard + Reports- Replaced TM-style dashboard view for managers with **Manager Control Dashboard**
- Added **TM Performance Table** with: visits vs target (cadence-derived), avg visits/day, overdue count, promise completion rate (30d), high-priority doctors not visited (priority ≥ 55), sentiment trend per TM (recent vs prior 30d)
- Auto **performance flags**: Low visit activity / Rising or High overdue tasks / Poor follow-up discipline / Avoidance of high-priority doctors — color-coded chips
- **Behavioral insights** per TM: Over-visiting low-value doctors, Under-visiting high-opportunity doctors, Strong/Weak follow-up habits, Sentiment trending up/down
- New **Reports system**:
  - TM: "Generate Weekly Report" → AI-assembled draft with Auto Insight Summary, key insights (heuristic-driven), topics, barriers, doctors needing attention, manager-notes textarea — fully editable, saves as Draft, Submit pushes to manager
  - Manager: dedicated `/reports` page with tabs **Submitted / Pending / Overdue** (synthetic rows for TMs who haven't submitted current/previous week), full report drawer with Auto Insight Summary at top, comment box (status flips to Reviewed)
- **Status tracking**: Draft / Submitted / Reviewed / Pending (no current-week submission) / Overdue (missed prior week)

## Backlog (next phases)
**P1**
- Voice-to-text note capture for mobile field use
- Weekly report generator with PDF/CSV export
- Editable Admin taxonomy (custom topics & barriers per region)
- Expense tracking module with receipt photo upload + OCR (deferred per user request)

**P2**
- Configurable cadence per team
- Soft-delete + archive for inactive doctors
- view_sensitive / export audit action types
- Doctor assignment bulk operations
- Refactor `server.py` (~2100 lines) into routers (auth/doctors/visits/tasks/dashboards/reports/admin)
- Switch doctor enrichment to `$facet` aggregation (currently N+1)
- `/reports` edit-after-submit → return `409 Conflict` instead of `400`
- Remove legacy `commercial_actions.demo_*` / `growth_program_explained` back-compat shim once migration is fully verified
- Advanced Admin Audit logs UI integration
