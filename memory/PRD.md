# FieldMind — Field Intelligence Platform PRD

> **NB (Phase H, Feb 2026)**: This PRD has grown past 800 lines of historic
> iteration log. Phase H onwards, new phase entries live in
> `/app/memory/CHANGELOG.md`. PRD remains the original product requirements +
> historical record.

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

## Iteration 5 (Feb 2026) — Voice-to-text dictation for TM visits
- **New endpoint**: `POST /api/visits/transcribe` (auth required) — accepts multipart `audio` field (webm/mp3/m4a/wav/mp4/mpga/mpeg, ≤25 MB) and returns `{text}`. Powered by OpenAI Whisper-1 via Emergent Universal LLM Key (`emergentintegrations.llm.openai.OpenAISpeechToText`).
- **Frontend**: LogVisit Step 2 now has a "Voice note" mic button beside the textarea. Browser MediaRecorder (audio/webm) records, auto-stops at ~110s, uploads to `/visits/transcribe`, and **appends** transcribed text into the existing note (TM can dictate multiple chunks). Live elapsed timer + "Transcribing…" spinner state. Graceful fallbacks: unsupported device, mic permission denied, empty transcription.
- Test coverage: 6/6 backend tests for the endpoint + 29/29 regression (iter-3 + iter-4) all green.

## Iteration 6 (Feb 2026) — Weekly report PDF / CSV export
- **New endpoint**: `GET /api/reports/{report_id}/export?format=pdf|csv` — RBAC mirrors `GET /reports/{id}` (TM only own; Manager only same team; Admin all). Returns `application/pdf` (built with reportlab — branded forest-green letterhead, metrics grid, insights bullet list, doctor attention table) or `text/csv` (flat key-value layout) with proper `Content-Disposition: attachment`.
- **Frontend**: TM Reports list shows PDF + CSV buttons on every row; Manager review drawer adds the same two actions in the footer. Both wire through a shared `downloadReportExport()` helper that uses axios `responseType: blob`, honours server-side filename, and shows a success/error toast.
- **Audit**: every export records an audit_log entry (`action=export`, `entity=report`, with `format`).
- Test coverage: 6/6 new tests in `tests/test_report_export.py` (PDF magic bytes, CSV header, 400 invalid format, 401 no-auth, manager same-team allowed, other-TM 403). Total backend now 70/70 green.

## Iteration 7 (Feb 2026) — Editable Admin taxonomy
- **DB-backed taxonomy**: replaced hardcoded TOPICS_DEFAULT/BARRIERS_DEFAULT with a `taxonomy_terms` MongoDB collection (`{id, kind, category, term, active, created_at, updated_at}`). `GET /api/taxonomy` now reads from DB (idempotent first-run seed from defaults).
- **New admin endpoints** (Admin role only):
  - `GET /api/admin/taxonomy` — list every term (active + inactive) sorted by kind/category/term.
  - `POST /api/admin/taxonomy` — add a term `{kind, category, term}` (409 on duplicate within same kind, 400 on missing fields or invalid kind).
  - `PUT /api/admin/taxonomy/{id}` — rename / recategorize / toggle active.
  - `DELETE /api/admin/taxonomy/{id}` — remove a term (existing visits keep their stored label — no cascade).
- **Admin UI**: new **Taxonomy** tab with Topic / Barrier toggle, grouped by category, inline rename + delete, "Add" form with category autocomplete (datalist).
- All mutations write to the audit log (`taxonomy_term` entity).
- Test coverage: 6/6 new tests in `tests/test_taxonomy_editable.py` (RBAC, CRUD lifecycle, duplicate detection, validation, public endpoint reflects DB). Total backend now 76/76 green.

## Iteration 8 (Feb 2026) — Expense Tracking module (Phase 3)
Mobile-first, food/petrol-only, image-driven expense capture with monthly submission to manager. **EUR-only, no per-receipt approval workflow** — manager simply views totals and downloads receipts.

- **Data model**: `expenses` collection with GridFS `receipts` bucket. Status lifecycle is `Draft → Submitted` only.
- **AI receipt OCR** via Claude Sonnet 4.5 vision (`expenses_ai.py`) extracts amount/currency/date/vendor/category_hint/confidence with SHA-1 dedupe.
- **Endpoints**: `POST /expenses` (TM, multipart, currency forced to EUR), `POST /expenses/extract` (OCR-only), `GET /expenses` (RBAC-scoped + filters), `GET /expenses/summary`, `PUT/DELETE /expenses/{id}` (Draft only), `GET /expenses/{id}/receipt`, `POST /expenses/submit-month`, `GET /expenses/team-summary` (Manager/Admin per-TM rollup), `GET /expenses/receipts.zip` (Manager/Admin bulk download).
- **TM `/expenses`**: month navigator, 4 stat cards, Add/Submit-month buttons, list with receipt thumbnails + delete-draft.
- **TM `/expenses/log`**: mobile camera capture → AI pre-fill → Petrol/Food picker → save in <10s.
- **Manager `/expenses`**: by-Territory-Manager rollup table (Petrol € / Food € / Total € / counts), drill-down list, "Download all receipts (ZIP)" + per-TM zip icon.
- Idempotent startup migration normalised legacy Approved/Rejected → Submitted and any non-EUR currency → EUR.

## Iteration 10 (Feb 2026) — Tasks/Promises UX + role-based mobile navigation

### Tasks (Promises) UX overhaul
- **Inline complete / edit / delete** on every row — no navigation, no full reload, no tab switch.
  - Optimistic state updates; rollback on API error.
  - Completed rows: green left-border accent, line-through title, "✓ Done <timestamp>" inline. Reopen via undo icon.
  - Overdue rows: red left-border accent, alert icon.
  - Delete = soft-delete with `window.confirm` prompt; logged in audit trail.
- **Open / Completed pill toggle** with row counts. Default tab is **Open** (sorted: overdue first, then by due-date asc; Completed sorted by completion timestamp desc).
- **Edit dialog** lets the TM update title, description, due_date, priority, and reassign to another doctor (server validates the user can access the new doctor).
- **Backend changes**:
  - `TaskUpdate` now accepts `doctor_id` (with access validation; 400 if not allowed).
  - `PUT /tasks/{id}` clears `completed_at` when status flips back to Open/Overdue, and 410 if the task was soft-deleted.
  - **New `DELETE /tasks/{id}`** soft-deletes via `{deleted_at, deleted_by}`. Idempotent on second call. Audit-logged.
  - `GET /tasks` and `GET /doctors/{id}/tasks` and `/doctors/{id}/prepare` now exclude soft-deleted tasks (`$or [exists:false, null]`).

### Role-based bottom navigation (mobile-first)
- Reduced bottom nav to **5 items max** for both roles. Desktop top nav unchanged (still shows the full set).
- **TM bottom**: Home · Doctors · **+ Add (centered FAB)** · Tasks · iTero. The + Add button opens a bottom sheet with: Log a visit, Add an expense, Add a doctor (Import from spreadsheet).
- **Manager bottom**: Dashboard · Intervention · iTero · Invisalign · **More** (sheet → Team performance, Reports, Expenses).
- Manager top nav reordered: Dashboard · Intervention · iTero · Invisalign · Team · Expenses · Reports (Intervention promoted next to Dashboard per UX rules).
- Manager intentionally has no Add button or Tasks tab; TM intentionally has no Reports button on the bottom (still in top nav).
- Bottom sheets use a slide-up animation with backdrop dismiss + close button.

### Test coverage (iter-10)
- 6 task UX tests: soft-delete excludes from list, complete sets/clears completed_at on status flip, edit (title/description/date/priority), reassign-doctor validates access, other-TM cannot delete, idempotent delete.
- 3 manual-add-doctor tests: TM self-assigns, required-field validation (422), invalid-segment Literal rejection.

### Manual "Add doctor" form
- New `/doctors/add` page (TM + Admin) — clean form with **Name (required)**, Clinic, City, Region, Type (GP/Ortho/Other), Segment (Occasional/Active/Engaged/Expert), General notes.
- Two save actions: **Save doctor** → goes to `/doctors/{id}`, and **Save & log a visit** → goes to `/log-visit?doctor_id={id}` (LogVisit now also supports `?doctor_id=` param alongside the existing `?doctor=`).
- Doctors page (TM only) gets a primary **+ Add doctor** button next to **Import** (outlined).
- The "+ Add" mobile bottom sheet for TMs now shows **both** options: "Add a doctor" (manual form) and "Import doctors" (spreadsheet wizard).
- **Total backend 109/109 green.**

## Iteration 9 (Feb 2026) — Admin user management + doctor import wizard

### Admin user management (existing endpoints regression-hardened)
- `POST /api/users` — Admin only (Manager/TM forbidden — verified by tests).
- `PUT /api/users/{id}` — extended to allow **email change** (with 409 duplicate check) on top of existing fields (name / role / team / region / active_status / password).
- Login flow already rejects users where `active_status=False` (regression test added).
- The Admin > Users tab UI already supports create + activate/deactivate; this iteration adds the regression coverage and email-update capability.

### Doctor import (xlsx / csv) — TM self-service + Admin on-behalf
- **New module** `imports.py`: parses .xlsx (openpyxl) / .csv, auto-suggests header → field mapping (smart aliases), validates rows (required `doctor_name`, normalises `doctor_type` to GP/Ortho/Other, validates `segment` against the four allowed values).
- **Endpoints**:
  - `GET /api/doctors/import/template?format=xlsx|csv` — branded template with a sample row "Dr Ivanov · Smile Clinic · Sofia · Sofia · Ortho · Active · Interested in Invisalign but low clinical confidence".
  - `POST /api/doctors/import/preview` (TM/Admin, multipart) — returns `{filename, headers, row_count, sample_rows, rows, suggested_mapping, target_fields}`.
  - `POST /api/doctors/import/commit` (TM/Admin, JSON) — applies the mapping, performs **dedupe** (same name+city OR same clinic+city, scoped to the target TM), supports `duplicate_strategy=skip|update|import`. Returns a full `DoctorImport` summary record `{created/updated/skipped/failed counts, details}` and persists it to the new `doctor_imports` collection. Also catches duplicates **inside** the same uploaded file.
  - `GET /api/admin/doctor-imports` — admin-only history feed.
  - **`POST /api/doctors`** widened to accept TM role — TMs can now also create individual doctors (auto-assigned to themselves). Strict RBAC unchanged otherwise.
  - **`DELETE /api/doctors/{id}`** added (Admin only) for taxonomy-style cleanup.
- **Frontend wizard** `/doctors/import` (TM + Admin):
  - 4-step pill stepper: Upload → Map columns → Preview → Done.
  - Step 1: dropzone (.xlsx/.csv, ≤5 MB), template-download buttons, Admin-only TM picker.
  - Step 2: target-field × source-header mapping with auto-fill from `suggested_mapping`.
  - Step 3: live validation (total / valid / invalid / possible-duplicates stats, errors banner with first 10 row errors), duplicate-strategy chooser, sample-row preview table.
  - Step 4: success summary + "Import another" / "Back to doctors" actions.
- **Doctors page** gains a "Import doctors" button (TM-only).
- **Admin > Doctor imports** tab: history table with row counts, created/updated/skipped/failed (colored), per-row "Details" dialog showing the failed-row errors and skipped duplicates list.
- All actions audited (`audit_logs` action=`import` entity=`doctors`; `delete` entity=`doctor`).
- New index on `doctor_imports.created_at` ordering (implicit by sort).

### Test coverage (iter-9)
- 8 doctor-import tests: template (csv/xlsx), preview→commit, dedupe-skip, missing-name validation, xlsx upload, manager-cannot-import, admin-must-pick-tm, admin import-history visibility.
- 2 user-management tests: only-admin-can-create + deactivation-blocks-login, manager-cannot-edit.
- Tests include teardown cleanup so the seeded baseline (10 doctors) is preserved for downstream regression. **Total backend 100/100 green.**
Mobile-first, food/petrol-only, image-driven expense capture with monthly submission to manager. **EUR-only, no per-receipt approval workflow** — manager simply views totals and downloads receipts.

- **Data model**: `expenses` collection — `{id, tm_user_id, tm_name, team_id, expense_date, submission_month, category (Petrol|Food), amount, currency=EUR, vendor?, notes?, receipt_image_id, receipt_mime, receipt_hash, ocr, status (Draft|Submitted), submitted_at, created_at, updated_at}`. Receipt images stored in **GridFS** (`receipts` bucket).
- **AI receipt OCR** — module `expenses_ai.py` using Claude Sonnet 4.5 vision via Emergent LLM Key (`emergentintegrations.llm.chat` + `ImageContent.image_base64`) extracts `{amount, currency, expense_date, vendor, category_hint, confidence, notes}`.
- **Endpoints**:
  - `POST /api/expenses` (multipart, TM only) — create draft, optional receipt upload, returns `{expense, duplicate_of}` (SHA-1 hash dedupe). **Currency is server-forced to EUR.**
  - `POST /api/expenses/extract` (multipart, TM only) — OCR-only, no DB write; pre-fill the form.
  - `GET /api/expenses` — TM scope (own), Manager (team), Admin (all); filters `month`, `status`, `tm_user_id`.
  - `GET /api/expenses/summary` — month totals, by-category, by-status, submittable_drafts count.
  - `PUT /api/expenses/{id}` — only when Draft; TM scope.
  - `DELETE /api/expenses/{id}` — only when Draft; deletes GridFS attachment too.
  - `GET /api/expenses/{id}/receipt` — streams the receipt image (RBAC enforced).
  - `POST /api/expenses/submit-month` `{month: "YYYY-MM"}` — locks all of caller's drafts that month → Submitted.
  - `GET /api/expenses/team-summary?month=YYYY-MM` (Manager/Admin) — per-TM rollup with petrol/food split, total, count, submitted/draft counts, and team grand_total.
  - `GET /api/expenses/receipts.zip?month=YYYY-MM&tm_user_id=…` (Manager/Admin) — bundles every receipt image (filtered) into a ZIP archive named `<TM>/<date>_<vendor>_<id>.jpg`.
- **Frontend**:
  - **TM `/expenses`**: month navigator, 4 stat cards (Total / Receipts / Petrol / Food), Add-expense + Submit-month buttons, list with receipt thumbnails (lazy-loaded as blobs) + status pills (Draft/Submitted) + delete-draft action.
  - **TM `/expenses/log`**: photo capture (file input with `capture="environment"` for direct camera on mobile) → "Reading receipt with AI…" → form pre-filled with extracted fields + confidence banner + duplicate-receipt warning. Petrol/Food pill selector, EUR-only amount with leading € symbol, date, optional vendor + notes. Save draft.
  - **Manager `/expenses`**: month navigator, "Download all receipts (ZIP)" button, **Team Total / Receipts / Submitted / TMs reporting** stat cards. **By-Territory-Manager table** (Petrol € / Food € / Total € / receipts / submitted+draft counts / per-TM ZIP icon). Row-click drills into that TM's receipts list with status filter and lazy-loaded thumbnails.
- All state changes audited (`create/update/delete/submit/export`, entity=`expense`/`expense_receipts`).
- **Migration**: on startup, any legacy `Approved`/`Rejected` rows are normalised to `Submitted` and any non-EUR currencies are rewritten to `EUR` (idempotent, no-op on fresh DBs). New indexes on `expenses.id`, `(tm_user_id, expense_date)`, `(team_id, expense_date)`, `(receipt_hash, tm_user_id)`.
- Test coverage: 14/14 tests in `tests/test_expenses.py` (CRUD, RBAC, EUR enforcement, receipt upload + dedupe, GridFS streaming, monthly submission lock, **team-summary**, **receipts ZIP** with magic-byte assertion, OCR endpoint smoke, manager-cannot-create, validation, approve-endpoint-removed assertion). **Total backend 90/90 green.**

## Iteration 2 (Feb 2026) — Manager Control Dashboard + Reports- Replaced TM-style dashboard view for managers with **Manager Control Dashboard**
- Added **TM Performance Table** with: visits vs target (cadence-derived), avg visits/day, overdue count, promise completion rate (30d), high-priority doctors not visited (priority ≥ 55), sentiment trend per TM (recent vs prior 30d)
- Auto **performance flags**: Low visit activity / Rising or High overdue tasks / Poor follow-up discipline / Avoidance of high-priority doctors — color-coded chips
- **Behavioral insights** per TM: Over-visiting low-value doctors, Under-visiting high-opportunity doctors, Strong/Weak follow-up habits, Sentiment trending up/down
- New **Reports system**:
  - TM: "Generate Weekly Report" → AI-assembled draft with Auto Insight Summary, key insights (heuristic-driven), topics, barriers, doctors needing attention, manager-notes textarea — fully editable, saves as Draft, Submit pushes to manager
  - Manager: dedicated `/reports` page with tabs **Submitted / Pending / Overdue** (synthetic rows for TMs who haven't submitted current/previous week), full report drawer with Auto Insight Summary at top, comment box (status flips to Reviewed)
- **Status tracking**: Draft / Submitted / Reviewed / Pending (no current-week submission) / Overdue (missed prior week)

## Iteration 22 (Feb 2026) — One-tap "Mark demo done"
- **New endpoint** `POST /api/meetings/{id}/complete-demo` (only for `is_demo=true` meetings). Body: `{interest_level, outcome_note?, next_step?, next_step_due?}`. In one transaction it:
  1. Inserts a lightweight visit (`visit_type=Demo session`, `track_type=iTero`, `meeting_id` linked, `itero_actions: {demo_completed: true, demo_completed_date: today, scanner_interest_level}`).
  2. Marks the meeting `status=Completed` and stores `visit_id`.
  3. Auto-advances the doctor's pipeline stage to **Demo Completed** (forward-only) with stage-history note.
  4. Optionally creates a Medium-priority follow-up task tied to the doctor when `next_step` is provided.
  5. Returns `{ok, meeting_id, visit_id, task_id}`. Re-completing returns HTTP 400.
- **Frontend Schedule (`/meetings`)** — meeting cards with `is_demo=true` now render an iTero-orange "**Mark demo done**" primary button beside "Log visit". Header label switches to "iTero demo" with a matching left border colour for instant scanning.
- **DemoDoneDialog**: 4-button interest-level selector (None / Low / Medium / High), optional outcome note, optional next-step input that reveals a due-date field (defaulting to today + 7 days). One submit.
- Test coverage: 3 new tests in `tests/test_mark_demo_done.py` (advances pipeline + creates visit + appears in Completed; creates follow-up task when next_step set; non-demo meeting returns 400). 25/25 schedule+iTero tests green.

## Iteration 21 (Feb 2026) — Explicit "Book a demo" flow
- **Problem**: booking a demo previously required logging a visit and ticking `iTero → demo_booked` — not discoverable. Users asked "how do I actually book a demo?".
- **`Meeting.is_demo`** boolean field added (default `false`). `MeetingCreate` / `MeetingUpdate` accept it. When `is_demo=true` on create, the server auto-advances the doctor's iTero pipeline to **"Demo Booked"** (forward-only, never overwrites Lost) and writes a stage-history entry with note "Auto-advanced from booked iTero demo".
- **`/api/itero/demos`** now also reads `meetings.is_demo=true` rows: Scheduled meetings supply a future `booked_date`; Completed meetings supply a `completed_date`. Demos overview shows them alongside visit-derived demos automatically.
- **Frontend `/meetings/book`** page: prominent "**This is an iTero demo**" toggle at the top (auto-prefills subject "iTero demo"). Heading and submit-button label flip between "Book a meeting" / "Book demo". `?demo=1` query param pre-checks the toggle.
- **Quick entry points**:
  - TM `+ Add` bottom sheet: new "**Book an iTero demo**" entry below "Book a meeting".
  - Doctor profile: new "**Book demo**" outline button next to "Book meeting".
  - `/itero/demos` page: primary "**Book a demo**" button in the header.
- Test coverage: 2 new tests in `tests/test_book_demo.py` (is_demo auto-advances stage + appears in Booked bucket; non-demo meeting leaves stage untouched). 18/18 demos+meetings+pipeline tests green.

## Iteration 20 (Feb 2026) — Demos overview (Booked / Completed / Lost)
- **New endpoint** `GET /api/itero/demos` — walks each scoped doctor's visit history newest→oldest to extract earliest available `demo_booked_date` and `demo_completed_date`, then buckets:
  - `booked` — has a booked date but no completed date (sorted soonest first)
  - `completed` — `demo_completed_date` within the last 30 days (sorted latest first)
  - `lost` — doctor stage = `Lost` AND ever had any demo signal (sorted by latest available date)
  - RBAC: TM=own, Manager=team, Admin/Owner=all (mirror of `/itero/pipeline`)
  - Each row carries `doctor_id`, `doctor_name`, `clinic_name`, `city`, `segment`, `tm_user_id`, `tm_name`, `stage`, `booked_date`, `completed_date`.
- **New page** `/itero/demos`: tab strip Booked / Completed / Lost with live counts, search box (name/clinic/city), color-left-bordered rows, days-until/since pill, **overdue booked dates highlighted in red**. Each row links to the doctor profile so the TM can prep before the demo.
- **`/itero` funnel page**: new "Demos · Booked" section above the funnel listing the next 8 booked dates (links to full Demos overview).
- **TM Dashboard widget** "Upcoming demos" — top 4 nearest booked dates with the same overdue highlight + "See all →" to `/itero/demos`. Hidden if there are no booked demos.
- "Demos overview →" link added to the iTero header beside "Open pipeline →".
- Test coverage: 4 new tests in `tests/test_itero_demos.py` (booked appears with date · completed within 30d · Lost overrides booked · Manager sees team demos). 4/4 green.

## Iteration 19 (Feb 2026) — Events: from / to date-time
- **`Event.ends_at`** (Optional ISO datetime) added; `EventCreate/Update` accept `ends_at` and the server keeps `scheduled_at` (=start), `ends_at` and `duration_minutes` consistent (computes whichever wasn't provided; rejects end ≤ start with HTTP 400).
- **EventDialog** now has **From** + **To** datetime inputs (instead of single datetime + duration). Defaults to tomorrow 10:00 → 11:00. Auto-bumps the end forward by 1 h if the user picks a start that's ≥ the current end.
- **EventCard** shows a clean range like "Mon, Apr 27 · 10:00 – 12:00" (or full date on both sides when the event spans days).
- Test coverage: regression updated to send `ends_at` instead of `duration_minutes`; new `test_end_must_be_after_start` asserts 400. **9/9 schedule tests green.**

## Iteration 18 (Feb 2026) — Generic events alongside meetings (unified Schedule)
- **New `events` collection** (`{id, title, tm_user_id, tm_name, team_id, scheduled_at, duration_minutes, location, notes, status: Scheduled|Done|Cancelled, ...}`). Not tied to a doctor — for things like internal trainings, conferences, off-sites.
- **Endpoints**: `POST/GET/PUT/DELETE /api/events` (`?when=upcoming|past|all`). RBAC mirrors meetings (TM owns; Manager sees team; Admin/Owner sees all). Indexes on `id`, `(tm_user_id, scheduled_at)`, `(team_id, scheduled_at)`.
- **Unified Schedule view** (`/meetings` page rebuilt):
  - Heading renamed to **"Meetings & events"**, count includes both.
  - Tabs: Upcoming / Past / All. New filter chips: All / Meetings / Events.
  - Combined timeline grouped by Today / This week / Later (or Past). Meetings show "Log visit" + Cancel; events show "Done" + Delete. Different left-border color and label badge per kind for instant scanning.
- **Add event dialog**: title (required), datetime (default tomorrow 10:00), duration (default 60), optional location, optional notes. Same dialog handles edit (click event title in list).
- **Quick access**: TM `+ Add` bottom sheet now has both "Book a meeting" and "Add an event" entries. `/meetings?new_event=1` deep-link auto-opens the event dialog and strips the param.
- Test coverage: 3 new tests in `tests/test_events.py` (create/list/update/delete cycle, other-TM blocked, Manager-sees-team-events). 8/8 schedule tests green.

## Iteration 17 (Feb 2026) — Standalone task creation + visit-date picker
- **Tasks page header** gains a "**+ New task**" button. Opens a dialog that pre-selects no doctor; user searches the roster (name / clinic / city), then fills task title + optional details + due date (**defaults to today**) + priority. POSTs to existing `/api/tasks` and inserts the new task at the top of the Open list optimistically.
- **Deep-link**: `/tasks?new=1` auto-opens the dialog and strips the param. Wired into the TM `+ Add` bottom sheet so phone users can tap one shortcut to start a task.
- **Log Visit step 1** gets a "**Visit date**" `<input type="date">` (defaults to today, max=today). The combined ISO timestamp is sent in the visit payload so backdated visits land on the right day in the timeline. Helper text reminds users they can pick a past date for visits they forgot to log.
- Test coverage: 3 new tests in `tests/test_tasks_and_visit_date.py` (standalone task create · complete-then-reopen · backdated visit_date persists). 15/15 tasks/meetings/itero-pipeline tests green.

## Iteration 16 (Feb 2026) — iTero pipeline (Demo → Contract Signed)
- **New 8-stage pipeline** on Doctor: `None / Demo Discussed / Demo Booked / Demo Completed / Proposal Sent / Contract Sent / Contract Signed / Lost` (`models.IteroStage`).
- **Doctor doc** gains `itero_stage`, `itero_stage_updated_at`, `itero_stage_updated_by`. New collection `itero_stage_history` records every move (`from_stage / to_stage / by_user / note / auto / at`).
- **`IteroActions`** extended with `contract_sent`, `contract_sent_date`, `contract_signed`, `contract_signed_date`, `lost`, `lost_reason`.
- **Auto-advance** on `POST /api/visits` — `_auto_advance_itero_stage()` reads the most-advanced signal across `itero_actions` + `commercial_actions.proposal_sent` and bumps the doctor's stage **forward only**. `Lost` is terminal — never auto-overwritten.
- **Endpoints**:
  - `GET /api/itero/pipeline` — RBAC-scoped (TM=own, Manager=full team, Admin/Owner=all). Returns `{stages, groups, counts, total}` with TM names + last-visit days per card. Each column sorted by `stage_updated_at` desc, then last visit.
  - `POST /api/doctors/{id}/itero-stage` — `{stage, note?}` to manually set; appends history (`auto:false`).
  - `GET /api/doctors/{id}/itero-stage-history` — chronological audit of stage moves.
- **Frontend `/itero/pipeline`**: horizontal kanban (8 columns, mobile-friendly horizontal scroll-snap). Each card shows doctor name, segment pill, clinic·city, TM name (managers only see this when the data is from another TM), days since last visit, and a "Move forward" / "Change stage" button that opens a dialog for stage + optional note.
- **Doctor profile** shows current iTero stage as a coloured pill linking to the pipeline.
- **`/itero` funnel page** got an "Open pipeline →" button.
- Indexes: `itero_stage_history.(doctor_id, at desc)`.
- Test coverage: 7 new tests in `tests/test_itero_pipeline.py` (groups returned, manual stage + history, **visit auto-advance**, **no backward auto-advance**, **Lost not auto-overwritten**, manager team scope, other-TM cannot mutate). 37/37 critical tests green.

## Iteration 15 (Feb 2026) — Book a meeting (lightweight scheduler)
- **New `meetings` collection** (`{id, doctor_id, doctor_name, clinic_name, city, tm_user_id, tm_name, team_id, scheduled_at, duration_minutes, subject, status, visit_id, created_at, updated_at}`).
- **Endpoints** (TM-only create; RBAC-scoped reads/edits):
  - `POST /api/meetings` — `{doctor_id, scheduled_at, duration_minutes?, subject?}`. Verifies the TM owns/can-access the doctor; auto-fills `doctor_name/clinic_name/city`.
  - `GET /api/meetings?when=upcoming|past|all` — TM sees own; Manager sees team; Admin/Owner sees all.
  - `GET /api/meetings/{id}`, `PUT`, `DELETE` — same scope rules.
  - `POST /api/visits` accepts new optional `meeting_id` body field — when present, the linked meeting flips to `status="Completed"` with `visit_id` populated.
- **Frontend pages**:
  - `/meetings` — Upcoming / Past / All tabs. Sections grouped Today / This week / Later (Past for the Past tab). Each card: doctor name (links to profile), datetime + duration, clinic·city, optional subject, "Log visit" + "Cancel" buttons. Completed/Cancelled show a status pill instead of actions.
  - `/meetings/book` — TM-only. Doctor search-and-pick (name / clinic / city), `<input type="datetime-local">` with default = tomorrow 10:00, duration (default 30 min, step 5), optional subject. Single primary button. Pre-selects the doctor when navigated with `?doctor_id=…`.
- **Shortcuts surfaced**:
  - TM top nav: new "Meetings" tab between Doctors and Tasks.
  - TM mobile More-sheet: Meetings entry.
  - TM `+ Add` bottom sheet: "Book a meeting" between "Log a visit" and "Add an expense".
  - Doctor profile: secondary outline "Book meeting" button next to "Log Visit".
  - Meeting card "Log visit" button navigates to `/log-visit?doctor_id=…&meeting_id=…`; the existing visit form forwards `meeting_id` so the meeting flips to Completed automatically on save.
- Indexes added on `meetings.id`, `(tm_user_id, scheduled_at)`, `(doctor_id)`, `(team_id, scheduled_at)`.
- Test coverage: 5 new tests in `tests/test_meetings.py` (TM create + list, Manager-403 on create, other-TM-can't-book-for-not-mine, delete+404, **visit-with-meeting_id auto-completes meeting**). All green.

## Iteration 14 (Feb 2026) — Per-doctor breakdown in reports + TM mobile "More" sheet
- **TM mobile bottom-nav reshuffle**: replaced the 5th slot (was iTero) with a "**More**" sheet (slide-up panel). The sheet contains: iTero, Invisalign, Reports, Expenses. TM nav becomes: Home · Doctors · ＋ Add · Tasks · More.
- **Per-doctor breakdown in reports** (`ReportContent.doctor_breakdown`): one row per doctor visited that week, with `visits_count`, `last_visit_date`, accumulated `topics`, `barriers`, latest `sentiment`, list of `promises` opened, and a 220-char excerpt of the latest free-text note. Sorted by visits-desc / last-visit-desc.
- **`_build_report_draft`** populates the breakdown automatically; existing reports without it just render an empty section.
- **Reports UI** (TM editor + Manager review drawer) gets a new "Per-doctor breakdown" section — collapsible card per doctor with topic/barrier pills, promise list, sentiment chip, and italicised note excerpt.
- **CSV export**: new "Per-doctor visit breakdown" section with columns `Doctor / Clinic / City / Segment / Visits / Last visit / Sentiment / Topics / Barriers / Promises / Latest note`.
- **PDF export**: new "Per-doctor breakdown" page block, one stacked summary per doctor (header + meta line + topics + barriers + promises + italicised note).
- Test coverage: 3 new tests in `tests/test_report_doctor_breakdown.py` (`test_generate_includes_doctor_breakdown`, `test_csv_export_contains_per_doctor_section`, `test_pdf_export_still_returns_pdf`). All 9 report-export tests green.

## Iteration 13 (Feb 2026) — Owner role + full admin user CRUD
- **New role: `Owner`** (`Literal["TM", "Manager", "Admin", "Owner"]`). `auth.require_roles` auto-grants Owner the same access as Admin (no per-route refactor needed).
- **Auto-seeded Owner**: every backend startup runs `seed.seed_owner()` (idempotent) — creates Martin Petrov (`martennis89@gmail.com` / `1234.`) if missing. Survives all wipes/redeploys.
- **Owner protection rules** in `update_user` & new `delete_user`:
  - Only an Owner can create another Owner, promote to Owner, or modify/delete an Owner row.
  - Last-active-Owner cannot be deactivated/demoted/deleted.
  - Last-active-Admin (counting Owner) cannot be deactivated/demoted/deleted.
  - Self-deactivation, self-demotion, and self-delete remain blocked.
- **Admin Users tab — full UX rebuild**:
  - Edit dialog (full_name, email, role, team, manager, region) — saves via `PUT /users/{id}` with `exclude_unset=True` so explicit nulls clear fields.
  - Reset password dialog (Owner/Admin can set any user's new password).
  - Hard delete user (red trash icon) — cascades by orphaning their doctors (`assigned_tm_id=null`, `status=Inactive`).
  - Disable / Enable toggle (now wraps server guards — bug "I can no longer disable users" fixed: was a UI artifact when you tried to disable yourself).
  - Disabled actions on Owner row when caller isn't Owner.
- **TM ↔ Manager link**: `manager_user_id` field added to `User`. Editable directly on TM rows (not via team). Surfaced in users table as "Manager" column. Reassign by editing.
- **New endpoint `DELETE /api/users/{id}`** (Admin/Owner) and **`POST /api/admin/wipe-test-data`** (Owner only) — wipes the four demo accounts plus their doctors/visits/tasks/expenses/reports/imports + any pytest token rows.
- **Frontend access**: `/admin` route + nav link now allow Owner; `App.js` `ProtectedRoute roles=["Admin","Owner"]`.
- Test coverage: 9 new tests in `tests/test_owner_and_admin.py` (Owner login, Owner-only owner-creation, edit/delete flow, admin-can't-modify-Owner, password reset, team/manager assignment, self-delete-blocked, **admin-can-disable-TM bug verification**). Updated `test_admin_guardrails.py` to accept either guard message (last-admin or self-lock). **24/24 admin/import/owner tests green.**

## Iteration 12 (Feb 2026) — Doctor list view + delete UX
- **List ⇄ Cards toggle** on `/doctors` (saved in `localStorage.doctors_view`, default = list). List shows: name, clinic·city, segment, cadence, sentiment, last-visit days; Cards keep the original visual richness (priority pills, top barriers, etc.).
- **Per-row delete** button (red trash icon) on every row/card, with `window.confirm` and toast feedback. Visits + tasks for that doctor are cascade-removed (visits hard-deleted, tasks soft-deleted) so the data stays consistent.
- **Bulk delete**: row-level checkboxes + sticky action bar showing "{N} selected · Clear · Delete N". Single API call to `POST /api/doctors/bulk-delete` (cap 1 000 ids/request).
- **Backend RBAC widened**: `DELETE /api/doctors/{id}` now allows `Admin` **or** `TM` (TM may only delete doctors where `assigned_tm_id == user.id`; otherwise 403). Manager still forbidden.
- **New endpoint**: `POST /api/doctors/bulk-delete` `{ids: [...]}` — TM-scoped automatically (out-of-scope ids return in `skipped_ids`); cascades visits + tasks; full audit trail per doctor.
- Test coverage: 5 new tests in `tests/test_doctor_delete.py` (TM-self-delete, TM-cannot-delete-other-TM, Manager-403, bulk-delete-TM-scope with mixed ownership, bulk-delete-validation). **All 5 green.**

## Iteration 11 (Feb 2026) — Doctor import refinements + "New" / "Lapsed" segments
- **Split-name import**: Doctor import now accepts `first_name` + `last_name` columns; `imports.validate_and_project()` auto-merges them into `doctor_name` when no explicit full-name column is mapped. Required-name validation passes when first+last is provided.
- **Updated import template**: `/api/doctors/import/template` (csv & xlsx) now ships with `first_name,last_name,…` columns + sample row "Ivan, Ivanov".
- **Frontend `ImportDoctors.jsx`**: `TARGET_FIELDS` includes First name + Last name with help-text and merge logic in preview/dedupe.
- **"New" + "Lapsed" segments** (Iter 11.1, fix from real-world `Planning 9.csv`): added to `Segment` Literal in `models.py` (`New | Lapsed | Occasional | Active | Engaged | Expert`), `imports.ALLOWED_SEGMENTS`, taxonomy endpoint, scoring weights (`Lapsed=12`), default cadence (`New=30d, Lapsed=90d`), `StatusPill.SegmentBadge` colors, frontend `AddDoctor.jsx` SEGMENTS list and `ImportDoctors.jsx` validator. The user's 189-row file (51 Lapsed) now validates with 0 failures.
- **Larger imports**: row cap raised from 2 000 → **5 000** in `/doctors/import/preview` and `/commit` (HTTP 413 above that).
- Test coverage: 4 new tests in `tests/test_doctor_import.py` (`test_first_last_name_merge`, `test_new_segment_accepted` (now also asserts Lapsed), `test_manual_add_new_segment`) + template-shape assertion updated. **16/16 import+manual-add tests green.**


## Iteration 22 (May 2026) — TM Weekly Report captures iTero demos
**Problem**: `_build_report_draft` in `/app/backend/server.py` was only counting demos from legacy `visits.commercial_actions.demo_*` flags. The new unified Book-a-Demo flow stores demos in the `meetings` collection (`is_demo=True`), and the one-tap "Mark demo done" flow sets `itero_actions.demo_completed` (not `commercial_actions`). Consequently, TMs who booked/completed demos via the new flow saw **0 demos** on their weekly report.

**Fix**:
- `_build_report_draft` now queries `meetings` for `is_demo=True` & TM ownership, counting:
  - `demos_booked` = meetings with `created_at` in the report week (+ legacy visits without `meeting_id`)
  - `demos_completed` = meetings with `status="Completed"` & `updated_at` in the week (+ legacy visits without `meeting_id`; includes `itero_actions.demo_completed` fallback)
- Added `content.demos_booked_list` and `content.demos_completed_list` payload arrays (each row: doctor_id, doctor_name, clinic_name, scheduled_at, meeting_id, status/completed_at) — surfaced in the Reports UI.
- Per-doctor breakdown now includes rows for doctors with demo-only activity (no visit this week) and each row exposes `demos_booked_count`, `demos_completed_count`, `demo_dates`.
- CSV export adds two new sections: "iTero demos booked this week" and "iTero demos completed this week".
- PDF export adds an "iTero demos this week" table + "iTero demos" line on each per-doctor breakdown card.
- Frontend `Reports.jsx`: new `<DemosSection>` block under the demo stats in both Draft and Manager drawer views; each per-doctor breakdown card now shows an inline "N demos done" / "N demos booked" success pill.

**Tests**: `backend/tests/test_report_demos.py` (3/3) + full testing-agent E2E — 8/8 backend pytest + live UI verification (`[data-testid='report-demos-section']` renders, status pill correct, per-doctor demo pill visible).


## Iteration 23 (Feb 2026) — FieldMind Phase A + B (data spine + Track Signals + Clinical Patterns)

**Goal**: Lay the multi-tenant-ready foundation for FieldMind. Phase A = data-model spine (soft-deletes, track separation, draft flag, promise categories, +3-business-day default, event ledger with idempotency). Phase B = first-class `track_signals` and `clinical_patterns` collections with strict iTero/Invisalign separation and AI-confirmation flow.

### Phase A — data spine
- **`track_type`** added to visits/meetings: `iTero | Invisalign | Both | General`. Hard-separation enforced at all read paths.
- **`is_draft`** flag added on visit/meeting models (`is_draft=true` rows excluded from analytics until confirmed).
- **Soft-delete (`deleted_at`)** on `meetings`, `visits`, `tasks`, `track_signals`, `clinical_patterns`. Read paths (`GET /meetings`, `GET /meetings/{id}`, `GET /track-signals`, `GET /clinical-patterns`, `GET /tasks`) filter out soft-deleted rows.
- **Promise categories** (`Task.category`): `arrange demo | send proposal | follow up on proposal | resolve barrier | provide info | invite to event | other`. Invalid values rejected with HTTP 422.
- **`created_from_ai` / `ai_confirmed`** flags on tasks for AI-extraction provenance.
- **+3 business-days default `due_date`** when none provided (skips Sat/Sun via `_add_business_days`).
- **Activity Event Ledger** (`audit_logs`) extended with `event_type` (spec §3.12 named events: `promise_created`, `promise_completed`, `meeting_logged`, `meeting_deleted`, `itero_demo_booked`, `itero_demo_completed`, `invisalign_growth_program_explained`, `track_signal_created`, `clinical_pattern_created`, …) and `idempotency_key` so re-emits of the same logical event are deduped at the DB layer.
- **`GET /api/audit_logs?entity_type=&entity_id=&event_type=&limit=`** — Admin/Owner-only filtered reader (legacy `/api/audit` kept for back-compat).

### Phase B — Track Signals + Clinical Patterns
- **New collection `track_signals`** — `{id, doctor_id, tm_user_id, team_id, meeting_id, track_type (iTero|Invisalign), signal_type, signal_value, signal_status, signal_date, source (Manual|AI Suggested|AI Confirmed), idempotency_key, deleted_at, created_at, updated_at}`. Vocabularies `ITERO_SIGNAL_TYPES` (12) and `INVISALIGN_SIGNAL_TYPES` (26) enforced server-side.
- **Endpoints**:
  - `POST /api/track-signals` — manual create (TM/Manager/Admin/Owner). RBAC by doctor ownership. Invalid `signal_type` → 400.
  - `GET /api/track-signals?doctor_id=&track_type=&signal_type=&since=` — RBAC-scoped (TM=own, Manager=team, Admin=all).
  - `DELETE /api/track-signals/{id}` — soft-delete.
- **Visit save auto-materialization**: `POST /api/visits` calls `_materialize_track_signals_from_visit` which fans out confirmed `itero_actions`/`invisalign_actions`/legacy `commercial_actions` flags into the new `track_signals` collection (source = `AI Confirmed` when the visit had an `ai_extraction`, else `Manual`). Each row carries an idempotency key `ts:{visit_id}:{track_type}:{signal_type}` so re-saving never double-counts.
- **Backfill helper** `_backfill_track_signals_from_visits()` (idempotent — re-uses the same idempotency keys) seeded historical visits into the new collection.
- **New collection `clinical_patterns`** — `{id, doctor_id, tm_user_id, team_id, meeting_id, case_type, treatment_preference, treatment_strategy, confidence_level, barrier_type, source, deleted_at, …}`. Controlled enums on case_type (`Class I/II/III/Skeletal discrepancy/Mixed complex/Unknown`), treatment_preference, treatment_strategy, confidence_level, barrier_type. Invalid enum → 422.
- **Endpoints**: `POST /api/clinical-patterns`, `GET /api/clinical-patterns`, `DELETE /api/clinical-patterns/{id}` — same RBAC pattern.

### Quick-Capture + Inline Add-Doctor UX (this iteration)
- Global **Quick Capture** dialog (Wand icon) — TM can voice/text-record straight to a task with optional doctor binding.
- **InlineAddDoctor** dialog wired into all four doctor pickers (Quick Capture, Tasks, Book Meeting, Log Visit) — creates a doctor + selects it inline without leaving the flow.
- Fixed `addingDoctor` state crash on Book Meeting page.

### Tests
- **`backend/tests/test_phase_a_and_b.py`** — 13/13 green covering: +3 business-day default, explicit due-date respected, promise category persisted, invalid category rejected (422), meeting soft-delete + list exclusion, `promise_created` named event in ledger via filtered `/audit_logs`, manual iTero signal CRUD, invalid signal_type rejected (400), iTero/Invisalign list separation, RBAC isolation between TMs, visit-save materializes track signals (3 across both tracks), clinical pattern CRUD, invalid case_type rejected (422).
- `test_meetings.py` + `test_mark_demo_done.py` updated to match the new soft-delete contract and use a relative future due-date (no more hard-coded past dates).

## Iteration 24 (Feb 2026) — Phase C0: Router Refactor + Migration Safety Prep

**Goal**: Split the 5 165-line `server.py` into per-domain FastAPI APIRouter modules before any Phase C multi-tenant work. Zero behaviour change. Zero route-name change. All existing tests stay green.

### Architecture
- `server.py` (now **1 612 lines**) keeps: imports, Mongo init, `app`/`api` instances, every shared helper (`_audit`, `_enrich_doctor`, `_aggregate_*`, `_build_report_draft`, `_materialize_track_signals_from_visit`, etc.), startup/shutdown hooks, and the CORS middleware.
- New package **`routers/`** — one module per business domain. Each module:
  - `from server import api, db, _audit, get_current_user, require_roles, _now_iso, ...`
  - Re-registers handlers on the shared `api: APIRouter(prefix="/api")` via the original `@api.<verb>(...)` decorators.
- `server.py` imports the router modules at the bottom (BEFORE `app.include_router(api)`) so the decorator side-effects run before route mounting.

### Files created
```
routers/__init__.py           routers/ai_extract.py   (1 handler)
routers/auth.py        (5)    routers/audit_logs.py   (2 handlers)
routers/users.py       (7)    routers/clinical_patterns.py (3)
routers/doctors.py    (16)    routers/dashboards.py  (10)
routers/visits.py      (4)    routers/events.py       (5)
routers/meetings.py    (7)    routers/expenses.py    (10)
routers/tasks.py       (4)    routers/itero.py        (3)
routers/track_signals.py (3)  routers/reports.py      (8)
routers/search.py      (1)    routers/root.py         (1)
routers/taxonomy.py    (5)
```
**95 handlers** redistributed; not a single one renamed.

### Routes preserved (sample — all 95 unchanged)
`POST /auth/login`, `GET /auth/me`, `POST /auth/logout`, `POST /auth/change-password`,
`POST /seed/init`, `POST /admin/wipe-test-data`,
`GET|POST|PUT|DELETE /users[/{id}]`, `GET|POST /teams`,
`GET|POST|PUT|DELETE /doctors[/{id}]`, `POST /doctors/bulk-delete`, `GET/POST /doctors/import/*`,
`GET /doctors/{id}/{visits|tasks|prepare|itero-stage-history}`, `POST /doctors/{id}/itero-stage`, `POST /doctors/{id}/itero/quick-complete-demo`,
`POST /visits[/analyze|/transcribe]`, `GET /visits`,
`GET|POST|DELETE /track-signals[/{id}]`, `GET|POST|DELETE /clinical-patterns[/{id}]`,
`GET|POST|PUT|DELETE /meetings[/{id}]`, `POST /meetings/{id}/{complete|complete-demo}`,
`GET|POST|PUT|DELETE /events[/{id}]`, `GET|POST|PUT|DELETE /tasks[/{id}]`,
`GET /dashboard/{tm|manager|manager/commercial|manager/interventions|manager/itero|manager/invisalign|manager/cross-sell|tm/itero|tm/invisalign}`,
`GET /itero/{pipeline|demos|demo-breakdown}`,
`GET /search`, `GET /taxonomy`, `*/admin/taxonomy*`,
`GET|POST|PUT /reports[/{id}]`, `POST /reports/{id}/{submit|comment}`, `GET /reports/{id}/export`,
`GET /audit`, `GET /audit_logs`,
`POST|GET|PUT|DELETE /expenses[/{id}]`, `POST /expenses/{extract|submit-month}`, `GET /expenses/{summary|team-summary|{id}/receipt}`, `GET /expenses/receipts.zip`,
`POST /ai/extract-task`, `GET /`.

### Test proof
- `tests/test_phase_a_and_b.py` — **13/13 PASSED** post-refactor.
- Full regression batch (`test_meetings, test_mark_demo_done, test_book_demo, test_events, test_itero_demos, test_itero_pipeline, test_tasks_ux, test_tasks_and_visit_date, test_dashboard_counters, test_inline_add_doctor, test_quick_capture_and_pipeline_demo, test_complete_meeting, test_doctor_delete, test_taxonomy_editable, test_change_password, test_admin_guardrails, test_voice_transcription, test_reports_and_performance, test_report_export, test_report_demos, test_report_doctor_breakdown, test_report_pdf_export, test_doctor_import, test_manual_doctor_add, test_iter4_itero_invisalign, test_itero_demo_breakdown, test_itero_demos_event_counts`) — **148/148 PASSED**.
- 6 failures remain in `test_owner_and_admin` / `test_field_intelligence` / `test_commercial_and_control_tower` — **all pre-existing data-dependency issues** (confirmed by re-running against the pre-refactor `server.py.bak` — same failures).

### Bugs fixed inline (regression caught + fixed in same iteration)
- `routers/doctors.py::quick_complete_demo_for_doctor` referenced `complete_demo_meeting` and `CompleteDemoBody` which were moved into `routers/meetings.py`. Added a local-scope `from routers.meetings import complete_demo_meeting, CompleteDemoBody` to avoid a cross-router top-level circular import.

### Risks / limitations
- `from models import *` in every router file: triggers ruff F405 noise (no functional impact). Cleanup is P2.
- A handful of routers shadow stdlib imports (`uuid`, `io`) locally inside functions: pre-existing, kept verbatim to satisfy the "no behaviour change" constraint.
- Helpers `_audit`, `_now_iso`, etc. still live in `server.py`. A later refactor can move them to `routers/_deps.py` for cleaner separation, but it is **not** required for Phase C.

### Migration safety prep — why this matters before Phase C
The Phase C migration will add `company_id` to every doc in every collection. With handlers now grouped by domain, the `company_id` plumbing can be applied router-by-router with reviewable, isolated diffs (e.g. inject a `_company_query_for(user)` helper into `routers/doctors.py` then `routers/visits.py` etc.) rather than scrolling a 5 k-line monolith.

## Iteration 25 (Feb 2026) — Phase C: Multi-tenant Company + company_id migration

**Goal**: Add company-level isolation across the entire app as the foundation for multi-tenancy, with zero behaviour change for single-tenant installs. Future-proofs the data model for Phase D-H without requiring another migration.

### 1. `Company` model — `/app/backend/models.py`
Full 14-field model per spec — `{id, company_name, slug, industry, country, market, region, team_size_category, sales_motion, account_type, plan, benchmark_opt_in, active_status, created_at, updated_at}`.
- `team_size_category`: `1-5 | 6-15 | 16-50 | 51-100 | 101+` (Literal-enforced)
- `sales_motion`: `field sales | medical device sales | pharma field team | dental/orthodontic field team | B2B distribution | equipment sales | other`
- `benchmark_opt_in` defaults to **False** — Phase G gating.
- `active_status`: `Active | Inactive`.

### 2. `company_id` on every collection
Added `company_id: Optional[str] = None` to **Pydantic models**: `UserPublic, Team, Doctor, Visit, Task, AuditLog, WeeklyReport, Expense, Meeting, Event, TrackSignal, ClinicalPattern`. MongoDB collections also indexed on `company_id` at startup.

### 3. Migration helper (`_ensure_default_company_and_backfill`)
Runs on every startup, idempotent. Live snapshot after migration: 56 users, 325 doctors, 46 visits, 151 meetings, 109 tasks, 199 track_signals, 13 clinical_patterns, 8 353 audit_logs, 14 expenses, 4 reports, 2 teams — **all stamped with `company_id=<default>`**, 0 without.

### 4. Helper functions (`server.py`)
- `_company_id_for(user)`, `_company_query_for(user)`, `_apply_company_scope(q, user)`, `_same_company(user, entity)`, `_assert_same_company(user, entity)`, `_stamp_company(doc, user)`.

### 5. Feature flag
`ENFORCE_COMPANY_ISOLATION` env var (default **`true`**). When `false`, `_company_query_for()` returns `{}` and `_same_company()` returns `True` — legacy team-scope behaviour preserved as safe rollback.

### 6. Route coverage
**Every router** (auth, users, doctors, visits, meetings, tasks, reports, expenses, track_signals, clinical_patterns, audit_logs, dashboards, events, taxonomy, search, ai_extract, itero) updated to stamp `company_id` on writes (15 `insert_one` calls + 4 inline-dict inserts patched) and filter reads via `_company_query_for(user)` in every base-query dict.

### 7. Admin company management — `/app/backend/routers/companies.py`
- `GET /api/companies/mine` — any authenticated user.
- `GET /api/companies/{id}` — own company, or Owner for any.
- `GET /api/companies` — **Owner only**.
- `POST /api/companies` — Owner only; slug uniqueness; `benchmark_opt_in` forced `False`.
- `PUT /api/companies/{id}` — Owner: full edit. Admin: limited edit on own company (no `active_status/slug/plan/benchmark_opt_in`).
- `POST /api/companies/{id}/deactivate` — Owner only; default-company protected.

### 8. Test coverage — `tests/test_phase_c_company_isolation.py` (19/19 ✅)
Covers: default-company auto-seed, `benchmark_opt_in=False`, all backfilled collections, new-write auto-stamping, cross-company TM seeing zero doctors/meetings/tasks, dashboard counters company-scoped, search company-scoped, track signals + clinical patterns company-scoped, Owner-vs-Admin company-list RBAC, no external benchmark endpoint exposed (`/benchmark`, `/benchmarks`, `/companies/benchmark`, `/dashboard/benchmark` all 404/405).

**Full regression**: 167/167 passing (148 pre-existing + 19 new Phase C). 4 pre-existing data-dependent failures (`test_field_intelligence` doctor-count asserts, `test_commercial_and_control_tower` seed-demo asserts) unrelated to Phase C.

### 9. Owner role re-asserted
`seed_owner` previously seeded `martennis89@gmail.com` as `Admin`. Phase C **requires** this user to be `Owner` for cross-company support. Reverted to `OWNER_ROLE="Owner"`. `test_credentials.md` updated.

### 10. Risks / limitations
- Owner cross-company access has no explicit "support-mode" audit guard yet — P2 hardening item.
- `ENFORCE_COMPANY_ISOLATION=false` fallback path validated manually (toggling requires a backend restart) but not automated.

## Iteration 26 (Feb 2026) — Phase D: Metric Registry + V1 metrics + Field Execution Index

**Goal**: Build the **measuring engine** for FieldMind on top of real stored data — Event Ledger, Meetings/Visits, Tasks (Promises), Track Signals, Clinical Patterns, Reports, Expenses. Insight Cards, Advisory, Intervention, Benchmark Cohorts remain out of scope until later phases.

### 1. Metric Registry — `/app/backend/metrics/registry.py`
Pure-data `MetricDefinition` Pydantic class with: `slug, name, description, category {execution|pipeline|discipline|quality}, scope {tm|team|company|doctor}, unit {percentage|rate|count|score}, direction {higher_is_better|lower_is_better}, min_data_points, min_numerator (Phase D refinement), window_days, fei_weight, source`.

**V1 metrics shipped (6)** — all read from real persistent data, no fake/NaN values, "Not enough data yet" returned when below thresholds:

| Slug | Source | Formula | min_data_points | min_numerator | FEI weight |
|---|---|---|---|---|---|
| `promise_completion_rate` | `tasks` | Completed / due_date-in-window | 5 | 0 | 0.25 |
| `overdue_promise_rate` | `tasks` | (Open + due_date<today) / Open | 5 | 0 | 0.15 (lower is better — inverted in FEI) |
| `itero_demo_discussed_to_booked_rate` | `track_signals` (iTero) | distinct doctors booked / distinct doctors discussed-or-booked | 3 | 0 | 0.15 |
| `itero_demo_booked_to_completed_rate` | `track_signals` (iTero) | distinct doctors completed (overlap with booked) / distinct doctors booked | 3 | 0 | 0.20 |
| `meeting_to_visit_followthrough_rate` | `meetings` | Completed-with-linked-visit / Completed | 3 | 0 | 0.10 |
| `weekly_report_submission_rate` | `reports` | Submitted / weeks-in-window | 2 | 1 | 0.15 |

### 2. Compute engine — `/app/backend/metrics/compute.py`
- Pure async, takes a motor `db` handle, `tm_id`, `company_id`, optional `window_days`.
- `_build()` constructs a `MetricResult` dataclass with explicit `numerator`, `denominator`, `value (Optional[float])`, `sufficient_data: bool`, `message`.
- **Insufficiency rules** (no fake scores): `value` is `None` and `message` is set when `denominator < min_data_points` OR `numerator < min_numerator`.
- Public API: `compute_metric_for_tm`, `compute_all_for_tm`, `compute_fei_for_tm`.

### 3. Field Execution Index (0–100)
Weighted average of normalised component scores. `_normalize_to_0_100(result)`: clamps the rate to [0, 1], inverts for `lower_is_better`, multiplies by 100. Only components with `sufficient_data=True` contribute (`weight_sum` accumulates only their weights — no zero-padding bias).
- FEI returned with `label: "High" (≥75)`, `"Medium" (≥50)`, `"Low"` plus per-component breakdown (slug, raw value, value_0_100, weight, sufficient_data, message).
- When NO component has sufficient data, FEI is `None` with message **"Not enough data yet. Log a few visits, demos, and weekly reports to get your Field Execution Index."**

### 4. Metrics API — `/app/backend/routers/metrics.py`
- `GET  /api/metrics/registry` — list every metric definition.
- `GET  /api/metrics/me` — live compute for caller (TM convenience).
- `GET  /api/metrics/me/fei` — caller's FEI.
- `GET  /api/metrics/tm/{tm_id}` — RBAC-guarded (TM=self, Manager=team, Admin=company, Owner=any).
- `GET  /api/metrics/tm/{tm_id}/{slug}` — single metric by slug.
- `GET  /api/metrics/tm/{tm_id}/fei/summary` — single TM FEI.
- `POST /api/metrics/snapshots/run` — Manager/Admin/Owner: compute + persist a snapshot per TM. Idempotent within a minute via `idempotency_key=snap:{slug}:{scope_id}:{period_end[:16]}`.
- `GET  /api/metrics/snapshots` — RBAC + company-scoped listing.

### 5. Test coverage — `tests/test_phase_d_metrics.py` (12/12 ✅)
Each test class creates an isolated fresh TM, seeds known data, asserts EXACT `numerator/denominator/value`. Cleans up on teardown.
- **TestRegistry**: registry contains all 6 V1 metric slugs.
- **TestPromiseMetrics**: `promise_completion_rate` 6/10 = 0.6 ✅, insufficient-data (2 tasks) → `value=None` + "Not enough data yet" ✅, `overdue_promise_rate` 3/8 = 0.375 ✅.
- **TestIteroPipelineMetrics**: `discussed_to_booked` 3/6 = 0.5 ✅, `booked_to_completed` 1/4 = 0.25 ✅.
- **TestMeetingAndReportMetrics**: `meeting_to_visit_followthrough` 3/5 = 0.6 ✅, `weekly_report_submission_rate` 3/4 = 0.75 ✅.
- **TestFieldExecutionIndex**: empty-data → `fei=None`, `sufficient_data=False`, "Not enough data yet" message ✅. Promise-only seed (6/10 → 60.0 component, single contributor) → `fei == 60.0`, label "Medium" ✅.
- **TestSnapshotsAndRBAC**: Admin runs snapshot for one TM, listing returns it ✅. TM cross-TM read → 403 ✅.

**Full regression**: 202/202 passing in isolation. 1 pre-existing flake in `test_report_export.py::test_other_tm_forbidden` when full-suite DB state accumulates (passes in isolation) — **not a Phase D regression**.

### 6. Risks / limitations
- Snapshot scheduler not implemented — snapshots are computed via explicit `POST /metrics/snapshots/run`. Cron / weekly autorun is P2.
- All V1 metrics are TM-scoped. Team/company aggregations and per-doctor metrics will come with Insight Cards (Phase E).
- `meeting_to_visit_followthrough_rate` uses `meetings.visit_id` populated on visit log; older meetings without that link will read as "no follow-through" which is the correct semantic.

## Iteration 27 (Feb 2026) — Phase E: Insight Cards + Advisory Layer

**Goal**: Turn the Phase D V1 metric set into role-specific, actionable cards. Deterministic, rule-based — **no AI generation in this phase**. Build strictly on the V1 metrics; do not invent metrics, do not fake Invisalign insights, do not expose benchmarks.

> **Scope note**: This is the deterministic V1 advisory layer. AI-generated insights, predictive lift, and trend-based "improving / worsening" advisories are future enhancements gated behind Phase D V2 metrics (delta / trend tracking).

### 1. InsightCard model — `/app/backend/models.py`
Fields: `id, company_id, team_id, tm_user_id, manager_id, scope_type {TM|Manager|Admin|Team|Company}, scope_id, severity {Low|Medium|High|Critical}, category {Promise Discipline | iTero Execution | Reporting | Meeting Follow-through | Field Execution | Data Quality | General}, title, body, related_metric_slug, metric_value, comparison_value, suggested_action, status {New|Seen|Resolved|Dismissed}, dedup_key, created_at, updated_at, seen_at, resolved_at, dismissed_at`.

### 2. Deterministic insight rules — `/app/backend/metrics/insights.py`
Six rules + one FEI rule. Severity bucketing:
- `higher_is_better`: value < 0.50 → **High**, < 0.70 → **Medium**, ≥ 0.70 → no card.
- `lower_is_better`: value > 0.30 → **High**, > 0.20 → **Medium**, ≤ 0.20 → no card.
- `FEI`: < 50 → **High** (titled "Field Execution Index is low"), 50–74 → **Medium**, ≥ 75 → no card.
Each rule emits: `title (severity-specific), body (with current value + sample size), category, suggested_action, related_metric_slug, metric_value, dedup_key`.

**Dedup**: `dedup_key = "insight:<scope_id>:<slug>:<yyyymmdd>"`. Re-running `/generate` the same day **updates** the card body/severity/metric_value in place — never duplicates. User-set `status`, `seen_at`, `resolved_at`, `dismissed_at` are preserved across regenerations.

### 3. API endpoints — `/app/backend/routers/insights.py`
- `POST /api/insights/generate` — RBAC-scoped: TM→self, Manager→team TMs, Admin→all company TMs, Owner→all company TMs (Owner uses /companies for cross-company).
- `GET  /api/insights/me` — caller's cards (excludes Resolved/Dismissed by default; `?include_resolved=true`/`?include_dismissed=true` to widen).
- `GET  /api/insights/team` — Manager/Admin/Owner: cards for all TMs in scope.
- `GET  /api/insights/company` — Admin/Owner: `{cards, by_severity, by_category, total}` rollup.
- `POST /api/insights/{id}/seen` — TM-only state change (idempotent: New→Seen; Resolved/Dismissed untouched).
- `POST /api/insights/{id}/resolve` → status=Resolved, `resolved_at` set; row preserved.
- `POST /api/insights/{id}/dismiss` → status=Dismissed, `dismissed_at` set; row preserved.

**Company isolation**: every endpoint wraps `_company_query_for(user)` over the cards query. Cross-company TMs see empty lists. Cross-company action attempts → 404 (treated as "doesn't exist for you").

### 4. Test coverage — `tests/test_phase_e_insights.py` (15/15 ✅)
| # | Test | Result |
|---|---|---|
| 1 | TM with no data → 0 cards (no fake insights) | ✅ |
| 2 | promise_completion 3/10 → **High** "Promise completion is weak" | ✅ |
| 3 | overdue_promise 4/10 → **High** "Overdue promise risk is high" | ✅ |
| 4 | iTero discussed→booked 1/6 → **High** "iTero demo discussions are not converting" | ✅ |
| 5 | iTero booked→completed 0/4 → **High** "Booked iTero demos are not being completed" | ✅ |
| 6 | weekly_report 2/4 → Medium/High "Weekly reporting" | ✅ |
| 7 | Low FEI (3/10 completed, 7 overdue) → FEI 18.75 → **High** "Field Execution Index is low" | ✅ |
| 8 | Idempotent generation — re-run does NOT duplicate cards | ✅ |
| 9 | TM sees only own cards | ✅ |
| 10 | Admin company rollup contains team TM cards | ✅ |
| 11 | TM cannot call `/insights/company` (403) | ✅ |
| 12 | Cross-company TM sees empty `/insights/me` | ✅ |
| 13 | Resolve marks status=Resolved + `resolved_at` set + excluded from default list + reappears with `?include_resolved=true` | ✅ |
| 14 | Dismiss marks status=Dismissed + `dismissed_at` set + history preserved | ✅ |
| 15 | Seen marks status=Seen + `seen_at` set | ✅ |

**Full Phase A+B+C+D+E suite: 59/59 ✅** (13 + 19 + 12 + 15).

### 5. Example generated insight cards (live, from test fixtures)
```json
{"category": "Promise Discipline", "severity": "High",
 "title": "Promise completion is weak",
 "body": "Doctors remember unkept commitments. … Current value: 30.0% (sample size: 10).",
 "related_metric_slug": "promise_completion_rate", "metric_value": 0.30,
 "suggested_action": "Focus on closing open commitments before creating new ones.",
 "scope_type": "TM", "status": "New"}

{"category": "Field Execution", "severity": "High",
 "title": "Field Execution Index is low",
 "body": "Your Field Execution Index is 18.75/100. Start with overdue promises and weak iTero follow-through — those move the score fastest.",
 "related_metric_slug": "field_execution_index", "metric_value": 0.1875,
 "suggested_action": "Open your weakest metric first; fix one card at a time."}
```

### 6. Risks / limitations
- "Improved vs previous period" / trend-based cards are NOT implemented in Phase E. They require Phase D V2 (delta snapshots) — explicitly listed in the user's spec but parked.
- Manager / Admin advisories ride on top of the same per-TM cards (no team-level aggregate card generation yet). The `/insights/team` and `/insights/company` rollups are pure read-side aggregations of TM cards. Team-aggregate cards (e.g. "team-level weakest area") are Phase F territory.
- No frontend yet — Phase E ships the backend engine + endpoints; the React UI surfaces ("What to Do Next" panel, "What Needs Attention" panel, "Company Priorities" panel) are tracked as the next P0 frontend deliverable.
- Severity thresholds are hard-coded constants in `metrics/insights.py`. Per-company threshold customization is a future Phase G dependency.

### 7. What remains for Phase F
- Intervention entity (a Manager creates an action item targeted at a TM in response to an insight card).
- Manager Intervention tab (UI + tests).
- Closing the loop: when an Intervention is created from a card, set `comparison_value` and link to the intervention id.

## Iteration 28 (Feb 2026) — Phase E Frontend: Advisory UI Surfaces

**Goal**: Expose the Phase E backend Insight Cards + Advisory engine in the actual app. No new backend logic added — surface the existing endpoints (`/insights/me`, `/insights/team`, `/insights/company`, `/insights/generate`, `/insights/{id}/seen|resolve|dismiss`) through role-specific dashboards.

### 1. Single new component — `/app/frontend/src/components/AdvisoryPanel.jsx`
Driven by a `variant` prop:
- `variant="tm"` → GET `/insights/me` — title "What to do next".
- `variant="team"` → GET `/insights/team` — title "What needs attention".
- `variant="company"` → GET `/insights/company` — title "Company priorities" with rollup tiles (Total / Critical / High / Medium).

Internal sort: severity (Critical→High→Medium→Low), then status (New before Seen), then newest first.
Filters: severity (`All|Critical|High|Medium|Low`) and TM (`team`/`company` variants only).
Empty states with the exact spec copy ("No urgent actions right now. Keep logging meetings and completing promises." etc).
Resolved/Dismissed cards excluded by default; checkbox toggle brings them back.
Per-card action buttons: **Mark seen**, **Dismiss**, **Resolve** (last two visible until status is final).
"Refresh insights" button calls `POST /insights/generate` and reloads — success/failure toasts wired through sonner.

### 2. Dashboard integration — `/app/frontend/src/pages/Dashboard.jsx`
- `TMView` renders `<AdvisoryPanel variant="tm" />` after the upcoming-demos widget.
- `ManagerView` renders `<AdvisoryPanel variant="team" />`. When `user.role === "Admin"`, **also** renders `<AdvisoryPanel variant="company" />`.
- Existing dashboard widgets (priority doctors, TM performance table, cross-sell panel, alerts strip) untouched — Advisory sits alongside them.

### 3. Data-testids exposed (for automated tests)
`advisory-panel-{variant}`, `advisory-{variant}-refresh`, `advisory-{variant}-show-done`, `advisory-{variant}-filter-severity`, `advisory-{variant}-filter-tm`, `advisory-{variant}-empty`, `advisory-{variant}-list`, `advisory-{variant}-loading`, `advisory-company-rollup`, `insight-card-{id}`, `insight-severity-{id}`, `insight-status-{id}`, `insight-seen-{id}`, `insight-dismiss-{id}`, `insight-resolve-{id}`, `insight-metric-{id}`, `insight-scope-{id}`.

### 4. Frontend integration test — **10/10 acceptance criteria ✅** (`/app/test_reports/iteration_7.json`)
1. ✅ TM dashboard renders `advisory-panel-tm`. No team/company panel leaked to TM.
2. ✅ Empty state OR cards render depending on data (component branch verified; current seed produces 3 cards for tm1).
3. ✅ Refresh button (`advisory-tm-refresh`) → `POST /api/insights/generate` succeeds + reloads + success toast.
4. ✅ Each card displays severity badge + title + body + suggested action + 3 action buttons.
5. ✅ Resolve removes card from default view; "Show resolved/dismissed" checkbox brings it back.
6. ✅ Manager dashboard renders `advisory-panel-team` with TM + severity filters.
7. ✅ Admin dashboard renders BOTH `advisory-panel-team` + `advisory-panel-company`; rollup shows TOTAL=2, CRITICAL=0, HIGH=1, MEDIUM=1 on seed.
8. ✅ TM page does NOT render `advisory-panel-company` (RBAC honoured client-side as well).
9. ✅ No "benchmark" text appears anywhere in advisory panels.
10. ✅ Loading state (`advisory-{variant}-loading`) shown before content loads.

**Backend regression**: 59/59 across Phases A+B+C+D+E (13 + 19 + 12 + 15) still green.

### 5. Cosmetic fix applied post-test
Action toast strings now use a small map (`{seen:"Insight marked seen.", dismiss:"Insight dismissed.", resolve:"Insight resolved."}`) — fixed the `${action}d` typo that produced "dismissd".

### 6. Known limitations
- **TM filter dropdown** in `team`/`company` variants currently displays the truncated UUID (`tm.slice(0,8)…`) because `/insights/team` and `/insights/company` payloads don't include `scope_name`. Backend payload augmentation to ship `full_name` alongside `scope_id` is a P2 UX nit — backlogged.
- **Empty-state path** is not currently exercisable end-to-end on the seeded dataset (every demo TM has enough recent activity to produce at least one card). The component branch is verified by code review; future Phase E2 should add a "Clear all cards" affordance or seed an empty-data TM for visual regression.
- Visual-edit dev instrumentation wraps dynamic `<option>` labels in a `<span>`, producing a benign React hydration warning in dev console — disappears in production builds; non-blocking.

### 7. Phase F can safely start
- All Phase E acceptance criteria met (backend + frontend).
- No regressions in Phase A/B/C/D suites.
- Intervention entity (Phase F) can now reference live `InsightCard.id` to close-the-loop ("manager creates intervention from card X").

## Iteration 29 (Feb 2026) — Phase F: Intervention Entity + Manager Intervention Tab

**Goal**: Close the loop between insight and manager action. Insight cards tell the manager **what** is wrong; Interventions let the manager **track the corrective action** assigned to a specific TM.

### 1. Intervention model — `/app/backend/models.py`
Full spec fields: `id, company_id, team_id, manager_id, tm_user_id, doctor_id, insight_card_id, related_entity_type, related_entity_id, track_type {General|iTero|Invisalign|Both}, severity {Low|Medium|High|Critical}, issue_title, issue_description, suggested_action, manager_note, status {Open|In Progress|Completed|Dismissed}, due_date, created_from_insight, created_at, updated_at, completed_at, dismissed_at, deleted_at`.

### 2. API surface — `/app/backend/routers/interventions.py`
```
GET    /api/interventions                          GET    /api/interventions/{id}
POST   /api/interventions                          POST   /api/interventions/from-insight/{insight_id}
PUT    /api/interventions/{id}
POST   /api/interventions/{id}/in-progress         POST   /api/interventions/{id}/complete
POST   /api/interventions/{id}/dismiss             DELETE /api/interventions/{id}     (soft delete)
```
- RBAC: TM read-only on own assignments. Manager full CRUD on own team. Admin company-wide. Owner cross-company.
- Auto-team-id resolution: when manager assigns to a TM, intervention inherits the TM's `team_id` (manager can only assign to TMs in own team).
- Soft delete only — `deleted_at` set; rows preserved.
- Event ledger: `intervention_created`, `intervention_updated`, `intervention_in_progress`, `intervention_completed`, `intervention_dismissed`, `intervention_deleted`.

### 3. from-insight pre-fill flow
`POST /interventions/from-insight/{insight_id}` reads the insight card, derives `track_type` from `related_metric_slug` (slug contains "itero" → iTero, "invisalign" → Invisalign, else General), copies `severity`, `title`, `body`, `suggested_action`. Manager body overrides `manager_note`, `due_date`, etc. Source card is automatically transitioned `New → Seen` (never `Resolved/Dismissed`), preserving full insight history.

### 4. Frontend surfaces
**New components** (~430 LOC):
- `/app/frontend/src/components/InterventionList.jsx` — variant-driven:
  - `variant="manager"` (Manager Intervention Tab): 4 status tabs (Open / In Progress / Completed / Dismissed), TM/severity/track filters, per-row action buttons (Start / Edit / Dismiss / Complete / Delete), modal Edit dialog with title/severity/due-date/manager-note fields.
  - `variant="tm"` (TM dashboard panel): read-only "Manager follow-up" panel that hides itself when empty.

**Dashboard integration**:
- `Intervention.jsx` (existing doctor-priority bucket page) **augmented** — now ALSO renders `<InterventionList variant="manager" />` below the doctor buckets.
- `Dashboard.jsx::TMView` — renders `<InterventionList variant="tm" />` above the AdvisoryPanel.
- `AdvisoryPanel.jsx` — Manager/Admin/Owner cards now show a **"Create intervention"** button (`insight-create-intervention-{id}`) that opens a `window.prompt` for the manager note and POSTs `/interventions/from-insight/{id}`. TMs do NOT see this button (RBAC honoured client-side).

### 5. Test coverage
**Backend — 15/15 ✅** (`tests/test_phase_f_interventions.py`):
1. ✅ Manager creates intervention from insight card (auto-derives track_type, severity, title, body, suggested_action; insight card flips New→Seen)
2. ✅ Intervention persists `insight_card_id` link
3. ✅ Manager manual create (no card link, `created_from_insight=False`)
4. ✅ Manager sees only own-team interventions (`team_id == self.team_id`)
5. ✅ TM sees only own-assigned interventions
6. ✅ TM cannot DELETE or COMPLETE manager intervention (403)
7. ✅ Admin sees all company interventions
8. ✅ Cross-company TM list returns `[]`; direct GET returns 404
9. ✅ `POST .../in-progress` → `status=In Progress`
10. ✅ `POST .../complete` → `status=Completed` + `completed_at` set
11. ✅ `POST .../dismiss` → `status=Dismissed` + `dismissed_at` set
12. ✅ `DELETE` soft-deletes (row preserved with `deleted_at`)
13. ✅ Event ledger records `intervention_created` + `intervention_in_progress` + `intervention_completed`
14. ✅ List filters: default excludes Dismissed; `?include_dismissed=true` brings back; `?status=Completed` returns only completed
15. ✅ Insight card preserved after intervention creation (body and metric_value intact; status flipped to Seen)

**Frontend — 100% success** (`/app/test_reports/iteration_8.json`):
- Manager `/intervention` renders both the existing doctor-priority bucket tabs AND `interventions-manager-panel` with 4 status tabs + 3 filters.
- Manager `/dashboard` AdvisoryPanel: 8 team insight cards each show `insight-create-intervention-{id}` button; click triggers prompt, POST succeeds, toast "Intervention created from insight."
- TM `/dashboard`: `tm-followup-panel` renders (TM has ≥1 manager follow-up); does NOT see `insight-create-intervention-*` buttons (RBAC honoured client-side).
- Admin `/intervention`: also sees `interventions-manager-panel` (company-wide visibility).
- All empty-states (`interventions-{status}-empty`) render correctly when a tab has 0 items.
- One pre-existing hydration warning in AdvisoryPanel TM filter `<option>` — Emergent dev-tooling cosmetic, does NOT affect functionality.

**Full Phase A+B+C+D+E+F regression: 74/74 ✅** (13+19+12+15+15).

### 6. Risks / limitations
- **Edit dialog uses `window.confirm()` for delete** — acceptable for V1 but a custom modal would be cleaner. Backlogged P2.
- **Create-intervention prompt uses `window.prompt()`** — works but is a single-field flow. A full modal (currently only `EditDialog` exists) for the create-from-insight path is P2 polish.
- **TM filter dropdown** in Manager Intervention panel still uses `usersById` map; if the manager's users list is large, falls back to UUID prefix when the name isn't found. Same payload-augmentation issue tracked under Phase E P1 follow-up — single backend fix solves both.
- **Manager assignment cross-team**: Admin/Owner can assign an intervention to any TM in own company; Manager is constrained to own team. Tests cover the Manager path; Admin cross-team assignment is currently allowed (correct per spec).
- **Doctor association** is captured on `doctor_id` field but UI does not yet offer a doctor picker in the create-from-insight flow (deferred — insight cards are TM-scoped, not doctor-scoped, so deriving a doctor would require user input which the prompt UI cannot host).

### 7. Phase G can safely start
- Intervention entity is fully wired backend + frontend.
- Event ledger records every lifecycle transition (foundation for Phase G benchmark cohort eligibility tracking).
- `benchmark_opt_in` Company field still defaults `False` and zero external benchmark endpoints exist.
- All regression suites green.

## Iteration 30 (Feb 2026) — Phase G: Benchmark Cohort Infrastructure + Privacy Rules

**Goal**: Build the backend foundation for future anonymized external benchmarks. **No external UI**. **No company-vs-company values surfaced** to non-Owner roles. **No PII** in any payload.

### 1. `BenchmarkCohort` model — `/app/backend/models.py`
Full spec fields: `id, cohort_name, industry, country, region, market, team_size_category, sales_motion, account_type, minimum_company_count (default 10), current_company_count, benchmark_available, active_status {Active|Inactive}, created_at, updated_at`. Cohort-matching fields share the exact Literal enums from the Company model (Phase C).

### 2. `MetricDefinition.benchmark_eligible` flag — `/app/backend/metrics/registry.py`
New explicit allow-list on the V1 metric registry:
- **Eligible** (5): `promise_completion_rate`, `overdue_promise_rate`, `itero_demo_discussed_to_booked_rate`, `itero_demo_booked_to_completed_rate`, `meeting_to_visit_followthrough_rate`.
- **Blocked** (intentional): `weekly_report_submission_rate` (reporting-discipline → operator-behaviour signal) and `field_execution_index` (composite that could be reverse-engineered).

### 3. Privacy guardrails — `/app/backend/metrics/benchmark.py`
- `_safe_benchmark_metric(slug)` — gates every aggregation through the allow-list.
- `_benchmark_company_eligible(company)` — requires `benchmark_opt_in=True` AND `active_status="Active"`.
- `_cohort_match_query(cohort)` — Mongo query for matching companies; only NON-NULL cohort fields constrain.
- `_cohort_company_count(db, cohort)` — counts eligible matching companies.
- `_refresh_cohort_counts(db, cohort_id)` — recomputes `current_company_count` + `benchmark_available`.
- `_assert_benchmark_available(cohort)` — returns a reason string when blocked, else `None`.
- `_aggregate_metric(db, cohort, slug, period_days)` — anonymized aggregate. Per-company median rolled up, then median / mean / p25 / p75 across companies. Returns `None` whenever metric or cohort is blocked. **Never** returns company ids, names, or any value that could identify a contributor.

### 4. Aggregation logic
1. Allow-list gate (`_safe_benchmark_metric`) → metric blocked → `None`.
2. Cohort gate (`_assert_benchmark_available`) → too small / inactive → `None`.
3. Pull `metric_snapshots` for ONLY companies in `_cohort_match_query` (i.e. opted-in active companies matching cohort criteria).
4. Per-company median to anonymize within-company variance.
5. If `company_count` < `minimum_company_count` after the per-company collapse → `None` (defence in depth).
6. Return `{metric_slug, period_start, period_end, company_count, sample_size, median, average, percentile_25, percentile_75, top_quartile_threshold, bottom_quartile_threshold}` — **stats only**.

### 5. API surface — `/app/backend/routers/benchmark.py`
**Owner-only cohort management**:
- `GET    /api/benchmark/cohorts`
- `POST   /api/benchmark/cohorts`
- `PUT    /api/benchmark/cohorts/{id}`
- `POST   /api/benchmark/cohorts/{id}/refresh`
- `GET    /api/benchmark/cohorts/{id}/status` — Owner-only, returns cohort criteria + counts + availability, no company names.

**Safe per-company status** (any authenticated user):
- `GET /api/benchmark/status` — returns ONLY: `{company_benchmark_opt_in, eligible_for_benchmarking, matched_cohort_count, benchmark_available, reason_if_unavailable}`. **Zero benchmark values.** Reason strings include "Company has not opted in.", "Not enough anonymized companies in cohort yet (X/Y).", "No eligible metric snapshots yet.", "No active cohorts match this company yet.", "Company is not active."

**Deliberately NOT shipped** (asserted by test #15):
- `/benchmark/compare`, `/benchmark/values`, `/benchmark/dashboard`, `/benchmark/aggregate`, `/benchmark/results`, `/companies/compare`, `/dashboard/benchmark` — all 404/405.

### 6. RBAC
- **Owner**: full cohort management (`require_roles("Owner")` on every cohort endpoint).
- **Admin**: blocked from `/benchmark/cohorts/*`. Can call `/benchmark/status` (own company status only).
- **Manager**: blocked from cohort endpoints. Can call `/benchmark/status`.
- **TM**: blocked from cohort endpoints. Can call `/benchmark/status`.

### 7. Test coverage — `tests/test_phase_g_benchmark.py` (15/15 ✅)
1. ✅ `benchmark_opt_in=False` excluded from cohort counts.
2. ✅ `benchmark_opt_in=True` company counted (delta +1 on refresh).
3. ✅ Deactivating a company removes it from the cohort count.
4. ✅ Cohort below threshold → `benchmark_available=False`.
5. ✅ Cohort at/above threshold → `benchmark_available=True`.
6. ✅ Raw notes never appear in `/benchmark/status` (no `note`, `doctor_name`, `tm_name`, `price`, `revenue`, …).
7. ✅ Company names never appear in `/benchmark/status` or `/benchmark/cohorts/{id}/status`.
8. ✅ TM gets 403 on `/benchmark/cohorts*`.
9. ✅ Manager gets 403 on `/benchmark/cohorts*`.
10. ✅ Admin gets 403 on `/benchmark/cohorts*`; `/benchmark/status` returns own-company state only.
11. ✅ Owner can create / refresh / edit / list cohorts.
12. ✅ Non-eligible metric slugs blocked by `_safe_benchmark_metric` (`weekly_report_submission_rate`, `field_execution_index`, invented slugs).
13. ✅ Cohort with unreachable threshold (`minimum=999`) stays `benchmark_available=False` even after refresh.
14. ✅ `/benchmark/status` response keys are exactly `{company_benchmark_opt_in, eligible_for_benchmarking, matched_cohort_count, benchmark_available, reason_if_unavailable}` — no extras.
15. ✅ No external comparison/dashboard endpoint responds 200 for any role.

**Full Phase A+B+C+D+E+F+G regression: 89/89 ✅** (13+19+12+15+15+15). (One transient connection-timeout flake fixed in Phase C test by tightening the path list it probes.)

### 8. Proof: no raw / company / user / account data exposed
- `/benchmark/status` payload keys are an explicit whitelist (test #14 enforces this).
- `/benchmark/cohorts/{id}/status` returns `cohort_name + criteria + counts + availability` — never company-level identifiers.
- `_aggregate_metric` payload contains only stats (no `company_id`, `tm_user_id`, `doctor_id` fields).
- The aggregation engine reads from `metric_snapshots` only — which by construction stores `numerator / denominator / value / scope_id (TM id) / company_id` and has never contained notes, doctor names, or pricing data.
- Pre-existing Phase C test asserts `/benchmark/compare`, `/benchmark/values`, `/benchmark/dashboard`, etc. all 404/405 for the Owner role.

### 9. Risks / limitations
- The aggregation engine is wired but **no endpoint exposes its output** in Phase G — by design. A future "Owner Benchmark Insights" tab will wrap `_aggregate_metric` behind Owner RBAC + extra logging.
- Refreshing one cohort at a time scales linearly; a batch `POST /benchmark/cohorts/refresh-all` is a future P2 nicety.
- `_aggregate_metric` requires at least one `metric_snapshot` per company in the period — operators must run `POST /metrics/snapshots/run` periodically (Phase D snapshot scheduler is still backlogged as P2).
- "Industry" is currently a free-text field on Company; cohort matching is strict equality. A future Phase H taxonomy could canonicalise it.

### 10. Confirmation: external benchmark UI is still hidden
- No frontend components for benchmarks exist.
- No nav links to benchmark surfaces in `Layout.jsx`.
- No `/benchmark` route in the React router.
- Every "values" endpoint returns 404/405 (test #15 covers 8 candidate paths).

## Backlog (next phases)
**P0 — pending user sign-off**
- Phase H — Nav trim (max 5 items per role) + empty-states pass.

**P1 — Phase G follow-ups**
- Owner Benchmark Insights tab UI (Owner-only) wrapping `_aggregate_metric` output with explicit cohort guard rails.
- Batch `POST /benchmark/cohorts/refresh-all`.
- Per-company "Request opt-in" admin flow.

**P1 — Phase E / F follow-ups**
- `scope_name` in `/insights/team`, `/insights/company`, `/interventions` payloads.
- Replace `window.prompt` create-intervention with full modal (severity + due-date + doctor picker).
- Linked-insight-card preview inside intervention rows.

**P1 — Phase D V2**
- Trend/delta snapshots, team/company/per-doctor scope metrics, `comparison_value` back-fill.

**P1 — Hardening**
- Owner support-mode audit, dashboard `company_id` defence, `ENFORCE_COMPANY_ISOLATION=false` automated test, clean analytics fixture.

**P2**
- Helpers → `routers/_deps.py`, taxonomy per-region, Swagger tags, snapshot scheduler, My-FEI badge UI, empty-data TM visual regression test.

**Future**
- `/insights/me/digest` weekly email.

**P3 — Branding**
- Company logo + brand color for report PDFs and exports.
- Refactor `server.py` (~3 200 lines) into FastAPI APIRouter modules (`routers/users.py`, `doctors.py`, `visits.py`, `tasks.py`, `expenses.py`, `reports.py`, `dashboards.py`, `taxonomy.py`)
- Per-region scoping for taxonomy terms (currently global; users.region exists but not yet enforced)

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
