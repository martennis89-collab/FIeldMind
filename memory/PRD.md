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

## Backlog (next phases)
**P1**
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
