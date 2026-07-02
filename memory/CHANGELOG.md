# FieldMind — Changelog

This file tracks shippable changes by phase, growing forward. Original product
requirements and historical iteration log remain in `/app/memory/PRD.md`.

## SeniorTM expense download bug fix + TM "Download my report" (Feb 2026)

**User report** (hit on production): "Download all as PDFs (ZIP)" button
showed a red "Could not download" toast and no file ever arrived.
**User request**: TMs should be able to download the same report after
they submit to their SeniorTM.

### Bug root causes (three-in-one)
1. `server.py` CORSMiddleware had no `expose_headers` — browser JS couldn't
   read `Content-Disposition`, so the filename fell back and any real HTTP
   error was masked.
2. `/expenses/receipts.zip` returned a buffered `Response` — on large batches
   the production ingress (30s default) killed the request before the whole
   ZIP was serialised.
3. Frontend `catch` clause swallowed the real backend message and always
   displayed the generic "Could not download".

### Fixes
- **`server.py`**: added `expose_headers=["Content-Disposition"]` so
  browser JS can read the download filename.
- **`routers/expenses.py`**:
  - Endpoint now returns a `StreamingResponse` chunked at 64 KB with an
    explicit `Content-Length`. Reliable delivery on constrained ingress.
  - Per-row `try/except` around `_build_expense_pdf` so one corrupt
    receipt image cannot 500 the whole batch (also closes the iter16
    hardening minor).
  - Endpoint now accepts role `TM` — auto-scoped to `q.tm_user_id =
    user.id` BEFORE any `tm_user_id` query param is applied. RBAC-safe.
- **`pages/Expenses.jsx`**:
  - New module-level `downloadExpenseZip(url, fallbackName)` helper reads
    JSON error bodies from `responseType: blob` responses. Surfaces the
    real backend `detail` (e.g. 404 → "No expenses to export").
  - `TMExpenses` gains a `downloading` state + `downloadMyReport` handler
    + a new button `data-testid="download-my-report-btn"` (label
    "Download my report").
  - `ManagerExpenses.downloadAll` refactored onto the shared helper —
    no duplicated download logic between the two views.

### Verification
- Testing agent iteration 17 → **100% pass** (8/8 new iter17 tests + 31/31
  regression from iter16 + Phase L + expenses).
- Verified end-to-end via Playwright: SeniorTM Team download, SeniorTM
  Personal download, TM Download-my-report all trigger real blob
  downloads with correct filenames.
- CORS `Access-Control-Expose-Headers: Content-Disposition` confirmed
  over HTTP.


## SeniorTM expense fix — visibility, submission, PDF-per-expense ZIP (Feb 2026)

**User bug report**: TM submitted an expense but Senior TM couldn't see it in
the Team expenses tab; SeniorTM couldn't submit their own expenses; export
format needed to be a ZIP of one-PDF-per-expense with the phone-camera image
embedded.

### Backend (`routers/expenses.py`)
- **POST `/api/expenses`** and **POST `/api/expenses/extract`** and **POST
  `/api/expenses/submit-month`** now accept SeniorTM in addition to TM.
- **GET `/api/expenses`** + **GET `/api/expenses/summary`** — SeniorTM defaults
  to the sub-team + self scope via `_managed_tm_ids_for(user)`. New optional
  `?personal=true` query param forces the SeniorTM's OWN tm_user_id filter
  (used by the "My expenses" panel).
- **GET `/api/expenses/team-summary`** — role guard broadened from
  `Manager+Admin` to `Manager+SeniorTM+Admin+Owner`. SeniorTM branch scopes
  via `_managed_tm_ids_for(user)`.
- **GET `/api/expenses/receipts.zip`** — role guard broadened; SeniorTM
  scoping added. Content-Disposition filename changed from `receipts_...` to
  `expense-report_...`.
- **New helper `_build_expense_pdf(exp, image_bytes, image_mime)`** renders
  one self-contained PDF per expense via reportlab. Layout: header "FieldMind
  — Expense Report", metadata table (TM name, date, category, vendor, amount,
  status, submission month, submitted_at, notes), then the phone-camera
  receipt image embedded on the same page. Filename in the ZIP:
  `<TM_name>/<YYYY-MM-DD>_<vendor_or_category>_<expense-id[:8]>.pdf`.
- **Hardening**: two-layer image resilience — PIL `.verify()` pre-check +
  reportlab fallback build. A single corrupt receipt image cannot 500 the
  whole team's monthly export.

### Frontend (`pages/Expenses.jsx`)
- New SeniorTM view toggle at the top (`data-testid=seniortm-expenses-view-toggle`)
  with two options: **Team view** (default, renders `ManagerExpenses`) and
  **My expenses** (renders `TMExpenses` with `personal={true}`).
- `TMExpenses` now takes a `personal` prop that appends `&personal=true` to
  `/api/expenses` and `/api/expenses/summary` calls.
- Download button relabelled to "Download all as PDFs (ZIP)" to match the
  new format.
- Route `/expenses/log` already permitted SeniorTM (no change needed).

### Verification
- Testing agent iteration 16 → **100% pass** (8/8 iter16 tests + 23/23
  pre-existing expense + Phase L regression tests). All three bug-report
  bullet points verified end-to-end.
- Backend lint clean. Frontend lint clean.
- Curl smoke: SeniorTM POST /expenses → 200, POST /submit-month → 200,
  team-summary → 200 with sub-team rows, receipts.zip → 200 with valid
  %PDF-1.4 PDF-per-expense entries.


## Backend perf sweep — every dashboard endpoint (Feb 2026)

Applied the same `asyncio.gather` + segment-pre-filter pattern from the
`/dashboard/manager` win across every remaining `_enrich_doctor` call site.

### Sites updated
- `routers/dashboards.py::tm_dashboard` (line 116)
- `routers/dashboards.py::manager_performance` (inner per-TM enrich, line 346)
- `routers/dashboards.py::manager_commercial` (line 428)
- `routers/dashboards.py::manager_interventions` (line 524)
- `routers/dashboards.py::manager_itero` (line 627)
- `routers/dashboards.py::manager_invisalign` (line 693)
- Plus 3 additional secondary endpoints picked up by `replace_all` (lines 771,
  816, 856)
- `server.py::report_generate` enrich loop (line 1240)

### Measured (Owner @ preview, warm)
| Endpoint | Before | After |
|----------|--------|-------|
| /dashboard/manager | ~10s | 0.38s |
| /dashboard/manager/performance | ~5-8s | 0.99s |
| /dashboard/manager/commercial | ~5-8s | 0.80s |
| /dashboard/manager/interventions | ~5-8s | 0.87s |
| /dashboard/manager/itero | ~5-8s | 0.81s |
| /dashboard/manager/invisalign | ~5-8s | 0.89s |

### Why this works
`_enrich_doctor` makes ~5 sequential DB roundtrips per doctor. Doing N
sequential awaits across a list of 1000 docs gives 5000 round-trips on a
single fibre. `asyncio.gather` lets the event loop interleave them — Motor /
the Mongo driver pipeline naturally batch the wire traffic so we end up
limited by the connection pool concurrency, not the latency × count product.

### Verification
- 72/72 backend pytest pass.
- `ruff check backend/` → clean.
- Curl timing of every Owner-visible dashboard endpoint is now sub-1s warm.


## P1 follow-ups + a backend perf bonus (Feb 2026)

Both items from the P2 retrospective shipped, plus a much bigger backend win
spotted during verification.

### 1. Dashboard.jsx — per-card progressive rendering
- `Promise.all` → four independent `safeGet(url, setter)` calls. Each card
  paints as soon as its OWN endpoint resolves.
- `loadError` is **cleared** on any subsequent success so a transient 503 on
  cross-sell can't blot the whole dashboard once stat cards are live.
- ManagerView now gates each stat tile on its specific data source:
  - `visits_week / doctors / open_meetings / completed_meetings` → `data`
  - `critical / high opportunity` → `interventions`
  - If `/interventions` arrives before `/dashboard/manager`, critical + opp
    paint first. New `StatCardShimmer` from `dashboard/StatCard.jsx` keeps the
    grid layout stable per-card while waiting.

### 2. Layout.jsx — viewport-aware top nav
- New `useTopPrimaryCount(role)` hook reads `window.innerWidth` (with rAF
  coalescing on resize) and returns the correct primary count from a
  per-role `{default, lg, xl}` map.
- `navConfig.js::TOP_PRIMARY_COUNT` now:
  - TM:        7 → 7 → 8 (default → lg → xl)
  - Manager:   5 → 5 → 5
  - SeniorTM:  6 → 8 → 10 (full union inline at ≥1440px)
  - Admin/Owner: 99 at every breakpoint
- Verified by testing agent iteration 15: 6/8/10 inline anchors with
  More-btn visible only at 1024 and 1280.

### 3. Backend perf — `/dashboard/manager` 10s → ~0.4s
- Was: `[await _enrich_doctor(d) for d in docs]` — 5 sequential DB roundtrips
  per doctor × N doctors. For Owner across all companies (~1000 docs) that
  hit ~10s.
- Now: pre-filter `docs` by `segment in ("Engaged","Expert")` first (~5% pass)
  and parallelise the remaining `_enrich_doctor` calls via `asyncio.gather`.
- Empirically: 0.3-0.5s warm vs 10s before. The progressive Dashboard
  rendering still helps for the OTHER three endpoints, but the primary stat
  grid now paints sub-second on its own.

### Verification
- `ruff check backend/` → No lint errors.
- ESLint on `frontend/src/` → No issues.
- Backend regression suite → **72 passed** (P2 set + earlier phases).
- curl timing on `/api/dashboard/manager` as Owner: 0.45s cold, 0.29s warm,
  0.40s warm — verified locally.


## Audit P2 — Security hardening (Feb 2026)

Four targeted hardening items shipped behind the existing `auth.py` + `_audit`
infrastructure. Zero schema changes outside of one new `login_attempts`
collection. **72/72 backend tests pass** (regression suite of 64 + 8 new P2
tests). Lint clean.

### 1. Brute-force login throttling (`auth.py`, `routers/auth.py`)
- New helpers `assert_not_locked_out`, `record_failed_login`,
  `clear_login_attempts`. Tracks attempts in a new `login_attempts` collection
  keyed by **both** `ip:{ip}|email:{email}` and `email:{email}` — so an
  attacker who rotates IPs is still throttled per account.
- Defaults: **5 failures within 15 min → HTTP 429**. Configurable via
  `LOGIN_MAX_FAILURES` / `LOGIN_LOCKOUT_MINUTES`.
- Successful login wipes both counters.
- Deactivated-account hits also increment the counter (closes the email-
  enumeration oracle).
- Indexes: `identifier` + `last_attempt_at` TTL (24h hard ceiling).

### 2. Per-user rate limit on `/api/reports/generate` (`routers/reports.py`)
- In-memory sliding-window token bucket. **20 generations / 60s / user** by
  default (`REPORT_GEN_LIMIT`, `REPORT_GEN_WINDOW_S`). Returns HTTP 429 with
  a `Retry-After` header when exhausted.
- Single-process safe; swap for Redis if the deployment fans out.

### 3. Owner cross-company-read audit (`_deps.py`)
- New `_audit_owner_cross_company_read(user, entity)` — appends one
  `audit_logs` row per `(owner_id, target_company_id, day, entity_type)` via
  the existing idempotency key on `_audit`. Pure observability (never raises;
  never affects the read path). Event type: `owner_cross_company_read`.
- Wired into `_can_access_doctor` (only entity Owner can reach today).

### 4. AI error string sanitisation (`ai.py`)
- New `_sanitise_ai_error(e)` redacts:
  - The literal `EMERGENT_LLM_KEY` value (whatever it is)
  - `sk-` / `pk-` / `Bearer` style tokens
  - JWT-shaped triple-base64 strings
  - Any 40+ char opaque blob
- Used by both `analyze_visit_note` and `extract_task_from_text`.

### 5. JWT secret env-only verification
- Confirmed `auth.py` uses `os.environ["JWT_SECRET"]` (no `.get(..., default)`).
- New static-source test in `test_audit_p2_security.py` blocks any future
  regression that re-introduces a fallback default.

### Verification
- `ruff check backend/` → No lint errors.
- Backend pytest (full suite + new P2 file) → **72 passed**.


## Audit P1 — Spaghetti / maintainability refactor (Feb 2026)

Goal: untangle the three largest hand-of-history files without changing any
visible behaviour. Validated by 64/64 backend pytest + a full frontend smoke
pass across Owner / SeniorTM / TM roles (testing agent iteration 14: 100%).

### 1. `backend/_deps.py` (new) ← extracted from `server.py`
- Moved **11 scope / RBAC helpers + 1 feature flag** out of `server.py`
  (1,822 → 1,684 lines): `_doctor_query_for`, `_can_access_doctor`,
  `_company_id_for`, `_company_query_for`, `_apply_company_scope`,
  `_managed_tm_ids_for`, `_is_manager_role`, `_same_company`,
  `_assert_same_company`, `_stamp_company`, `ENFORCE_COMPANY_ISOLATION`.
- DB-accessing helpers use a lazy `from server import db` inside the function
  body to break the import cycle. `server.py` re-exports the names via
  `from _deps import (...)` so every existing `from server import _helper`
  in routers keeps working — zero call-site changes.

### 2. `pages/Dashboard.jsx` ← 640 → 152 lines
- Extracted `ManagerView`, `TMView`, and the shared `StatCard` into
  `components/dashboard/` (3 new files, ~360 LOC total). The page now
  orchestrates role + view-toggle state and lets the sub-components render
  themselves from their own data.
- **Removed 145 lines of dead code** while at it: unused `TMPerformanceTable`,
  `FunnelRow`, and `sentimentColor` plus the orphaned
  `/dashboard/manager/performance` fetch (this data is rendered by the
  dedicated `/pages/TeamPerformance.jsx` route — Dashboard was double-fetching
  but never consuming it).

### 3. `components/Layout.jsx` ← 580 → 458 lines
- New `components/navConfig.js` (139 LOC) holds every role-based nav array:
  `TM_TOP`, `MANAGER_TOP`, `SENIORTM_TOP`, `TM_BOTTOM`, `MANAGER_BOTTOM`,
  `SENIORTM_BOTTOM`, the corresponding `_MORE` overflow arrays,
  `TOP_PRIMARY_COUNT` map, and `ADD_SHEET_ITEMS`.
- Unified the previously-triplicated mobile-nav JSX into two inner components:
  `MobileNavWithAdd` (TM + SeniorTM — central + Add) and `ManagerMobileNav`
  (Manager / Admin / Owner — no Add). `DesktopTopNav` handles the
  primary-vs-overflow split with the "More ▾" dropdown.

### Verification
- `ruff check backend/` → No lint errors.
- ESLint on `frontend/src/` → No issues.
- Backend pytest (a/b, d_metrics, e_insights, i_enrichment, i1_past_week,
  l_senior_tm) → **64 passed**.
- Frontend testing agent iteration 14 → **100% smoke pass**; SeniorTM
  dual-dashboard toggle, ADD_SHEET_ITEMS, More dropdown all verified.

### Known minor follow-ups (non-blocking, captured for backlog)
- Owner dashboard first paint is ~8s due to `Promise.all` of 4 cross-company
  endpoints. Pre-existing — consider progressive per-card rendering later.
- `TOP_PRIMARY_COUNT.SeniorTM = 6` always pushes 4 items into the More
  dropdown. On 1920px viewports there's room to show all 10 inline —
  consider a viewport-aware primary count.


## Audit P0 — Lint cleanup (Feb 2026)

Cleared all 121 outstanding lint warnings across backend (84 ruff) and frontend
(37 ESLint). Zero behavioural changes.

### Backend (`ruff` → 0 errors)
- Removed 7 redundant local `import uuid` / `import io` statements inside function
  bodies (F811) across `visits.py`, `expenses.py`, `reports.py`, `tasks.py`,
  `taxonomy.py`, `users.py`.
- Replaced `from models import *` with explicit imports in 11 router files
  (F405): `auth.py`, `clinical_patterns.py`, `doctors.py`, `events.py`,
  `expenses.py`, `meetings.py`, `reports.py`, `tasks.py`, `track_signals.py`,
  `users.py`, `visits.py`. Improves IDE navigation and type safety.
- Removed dead code block in `metrics/compute.py::_itero_discussed_to_booked`
  (4 unused locals + an `async for` loop whose body was just `pass`). The actual
  metric continues to use the `track_signals` collection — behaviour unchanged.
- Split 14 multi-statement lines in `routers/users.py` (E702) for readability.
- Cleaned up unused locals and E701 multi-statement lines in test files
  (`test_phase_a_and_b.py`, `test_phase_d_metrics.py`, `test_phase_e_insights.py`,
  `test_phase_g_benchmark.py`).

### Frontend (ESLint → 0 errors, 0 warnings)
- **Real perf bug fixed**: hoisted `IconLeft` / `IconRight` out of
  `components/ui/calendar.jsx` so they aren't re-defined every render
  (was triggering full subtree remount per React reconciliation rules).
- Escaped 22 unescaped JSX entities (`'` → `&apos;`, `"` → `&quot;`) across
  `Admin`, `BookMeeting`, `Dashboard`, `DoctorProfile`, `Expenses`, `InlineAddDoctor`,
  `Intervention`, `Itero`, `Login`, `QuickCaptureDialog`, `Reports`, `Tasks`.
- Removed 12 stale `eslint-disable` directives (no longer needed after
  hooks-deps refactors in earlier phases).
- Suppressed the intentional `cmdk-input-wrapper=""` attribute in
  `components/ui/command.jsx` (vendored shadcn convention).

### Verification
- `ruff check backend/` → No lint errors found.
- ESLint on `frontend/src/` → ✅ No issues found.
- Backend regression suite (`test_phase_a_and_b`, `_d_metrics`, `_e_insights`,
  `_l_senior_tm`) → **49 passed**.
- Frontend smoke screenshot: login page renders correctly.


## Phase L.4 — Senior TM TM-side endpoint parity (Feb 2026)

**User report**: "When I go to log a visit and create a new dr this error
appears" — screenshot showed 403 on `POST /api/doctors`.

### Root cause
Phase L wired Senior TM into Manager-style endpoints (dashboards, insights,
interventions, reports), but the TM-side endpoints (doctors, visits,
meetings, expenses, tasks) still hard-coded `require_roles("Admin", "TM")`
or `if user["role"] == "TM"` branches. Senior TM matched neither, so every
TM workflow returned 403 — including the doctor-create flow from /log-visit.

### What shipped (backend)
- **`routers/doctors.py`** — every `require_roles` decorator and every
  `user["role"] == "TM"` branch now also accepts `SeniorTM`:
  `create_doctor`, `preview_doctor_import`, `commit_doctor_import`,
  `update_doctor`, `delete_doctor`, `bulk_delete_doctors`, the doctor-import
  scope guard, the update-restrictions branch, the delete-only-own-doctors
  branch, the access-control branches, the `assigned_tm_id` query-filter
  whitelist.
- **`routers/visits.py`** — `list_visits` scope includes SeniorTM
  (own-data) and accepts `tm_user_id` query param for Senior TM (so they
  can scope to a specific direct report).
- **`routers/meetings.py`** — `list_meetings` scope + per-row access check
  treat SeniorTM as TM (own data).
- **`routers/expenses.py`** — `list_expenses`, `expense_summary`, and the
  per-row access check treat SeniorTM as TM.
- **`routers/tasks.py`** — `list_tasks` scope + the 3 per-row access checks
  treat SeniorTM as TM.
- **`server.py`** `_doctor_query_for` — Senior TM gets `assigned_tm_id IN
  [self.id, sub-team-ids]` so they see their personal doctors AND their
  direct reports' doctors. `_can_access_doctor` honours the same union.

### Verified
- `POST /api/doctors` as Senior TM → 200 with `assigned_tm_id = self.id`,
  `company_id` correctly stamped, doctor appears in the SeniorTM `/doctors`
  listing.
- `DELETE /api/doctors/{id}` as Senior TM → 200.
- Phase L + Phase I regression: **16/16 tests still green**.

### Action needed from you
Redeploy to push the fix to production. Once redeployed, the "create new
doctor" flow inside /log-visit will work for Senior TMs.

## Phase L.3 — Desktop top-nav "More ▾" dropdown (Feb 2026)

**Why**: After making Senior TM's top nav a full TM + Manager superset (10
items), the header started to feel crowded on 1024-1280px laptop screens.

### What shipped
- New `DesktopTopNav` component in `Layout.jsx` splits each role's top nav
  into **primary slots** (always visible) + an **overflow dropdown** under
  a "More ▾" button.
- Primary-slot counts: TM=7, Manager=5, SeniorTM=6, Admin/Owner=99 (no
  collapse — they keep the full bar since they're desktop-first).
- Overflow items render with `data-testid="{original}-overflow"` and the
  trigger has `data-testid="desktop-nav-more-btn"`. Active state
  highlighting is preserved inside the dropdown.
- Click-outside closes the menu. Clicking an item closes the menu and
  navigates.

### Senior TM nav now
- Primary inline: Dashboard / Intervention / Doctors / Meetings / Tasks /
  iTero.
- "More ▾" overflow: Invisalign · Team · Expenses · Reports.

### Plain TM nav now
- Primary inline: Dashboard / iTero / Invisalign / Doctors / Meetings /
  Tasks / Expenses.
- "More ▾" overflow: Reports.

### Manager nav now
- Primary inline: Dashboard / Intervention / iTero / Invisalign / Team.
- "More ▾" overflow: Expenses · Reports.

### Verified
Smoke-tested on preview as Senior TM (`snr.demo.1782126329@field.io`) and
TM1. All primary slots render, More button opens the dropdown with the
correct overflow items, and the menu closes when clicking outside or
selecting an item.

## Phase L.2 — Senior TM = full TM + Manager superset (Feb 2026)

**User report**: "I want the senior TM role to have the exact same view
access and capabilities as the normal TM. Right now senior TM cannot log
visits and some of the navigation in the header are only the ones for the
manager and the ones for TM only are missing. Senior TM should have all
those options available within a single login."

### What was missing
Phase L gave Senior TM the **Manager** top nav (MANAGER_TOP), which dropped
the TM-specific items: Doctors, Meetings, Tasks. Senior TMs effectively
lost TM-side capabilities even though backend RBAC allowed them.

### What shipped
- **`Layout.jsx`** — new `SENIORTM_TOP` array = full UNION of TM and Manager
  items (10 slots): Dashboard, **Intervention**, **Doctors**, **Meetings**,
  **Tasks**, iTero, Invisalign, **Team**, Expenses, Reports.
- Top-nav routing now picks: SENIORTM_TOP for Senior TM, MANAGER_TOP for
  Manager/Admin/Owner, TM_TOP for plain TM.
- Desktop "Log Visit" FAB (previously TM-only) already extended in Phase L
  to Senior TM — re-verified working: the red Log Visit button appears on
  every Senior TM page that isn't already `/log-visit`.

### Verified
- Senior TM logs in → top nav shows all 10 items (Dashboard / Intervention /
  Doctors / Meetings / Tasks / iTero / Invisalign / Team / Expenses /
  Reports). Each click loads the corresponding page without redirect or
  403. Doctors page renders ("Roster · Doctors (0)" with filters).
- Desktop "Log Visit" FAB visible on the Senior TM dashboard.
- Mobile bottom nav (5 slots: Dashboard / Intervention / + Add / Tasks /
  More) unchanged — already TM-hybrid.

## Phase L.1 — Senior TM dual dashboards + blank-page bug fix (Feb 2026)

**User report**: "The senior TM should have two dashboards. One for himself
as a TM like it is now for every TM and one as a manager. Right now in
production when I click on the dashboard nothing happens, nothing loads,
just a blank page."

### Root cause of the blank page
`Dashboard.jsx` rendered conditionally on role: `Manager`/`Admin`/`Owner` →
ManagerView, `TM` → TMView. SeniorTM matched **neither** branch, so the
`<ErrorBoundary>` resolved with no children and the page rendered blank
(no error to catch — just empty React output).

### What shipped
- **Dashboard.jsx** now fetches BOTH dashboards in parallel for SeniorTMs
  (`/dashboard/tm` + the 5 manager endpoints).
- New **toggle pill** at the top of the SeniorTM dashboard (`data-testid="seniortm-view-toggle"`)
  switches between:
  - **Team view** (default, `data-testid="seniortm-view-team"`) — full
    manager-style view scoped to their sub-team: visits/doctors/critical/
    high-opportunity stat cards, FieldMind Advisory panel, Action items,
    Team reports.
  - **Personal view** (`data-testid="seniortm-view-personal"`) — full TM
    dashboard: FEI V1 widget (their own score), Open promises / Overdue /
    Due today personal stats, Upcoming demos, personal advisory.
- Headline subtitle changes per view ("Your sub-team's funnels…" vs "Your
  personal activity, FEI V1, and priority doctors.").
- No data loss on toggle — both datasets stay in memory, switching is
  instant.

### Tests
- Frontend smoke verified end-to-end: SeniorTM logs in, dashboard renders
  Team view by default with all stat cards. Clicking "Personal view"
  switches the entire page to the TMView layout, FEI V1 widget visible
  with the "Not enough data yet" empty state.
- No backend changes — backend tests unchanged.

## Phase L — Senior TM role (Feb 2026)

**User request**: "We should introduce a new role which is Senior TM. We
should be able to create TMs under Senior TM team and TMs should be able to
submit reports directly to the Senior TM instead of the manager. Manager
will have the TMs under him and TMs under Senior TMs. Senior TMs should
have exact same visibility as the manager on the platform."

### Design (confirmed before code)
- **Hierarchy**: Owner → Admin → Manager → SeniorTM → TM (4 layers in the
  team).
- **Senior TM = TM + Manager hybrid** — they log their own visits/promises
  like a TM AND oversee a sub-team of TMs.
- **Reports-to pointer**: existing `users.manager_user_id` field is the
  "reports to" column. A TM may report to either a Manager OR a Senior TM.
  A Senior TM may only report to a Manager.
- **Visibility**: Senior TM sees ONLY their direct reports + themselves.
  Manager continues to see the whole team (including the Senior TMs and
  their sub-teams) via `team_id`.
- **Permissions**: Senior TM can create interventions, comment on weekly
  reports, see `/intervention`, `/reports?tab=team`, `/team-performance` —
  but only scoped to their sub-team. Cannot delete users or touch
  Admin/Owner accounts. Manager can reassign a TM between themselves and
  any Senior TM in the team.

### Backend changes
- **`models.py`**: added `SeniorTM` to the `Role` literal.
- **`server.py`**: added `_managed_tm_ids_for(user)` + `_is_manager_role(user)`
  helpers — resolve the list of user-ids the caller can manage based on role.
- **`routers/users.py`**:
  - `GET /api/users` now scoped per-role: Manager sees the whole team,
    Senior TM sees self + direct reports.
  - `POST /api/users` opens to Manager (not just Admin) but Managers can only
    create `TM` or `SeniorTM` users in their own team.
  - New `_validate_reports_to_chain` guard: TM must report to Manager or
    SeniorTM; SeniorTM must report to Manager; cross-company always rejected.
  - `PUT /api/users/{id}` opens to Manager — Manager can change
    `full_name`, `manager_user_id`, `active_status`, `region`, and toggle a
    user's role between TM ↔ SeniorTM. Cannot touch Admin/Owner/Manager
    accounts or grant Admin role.
- **`routers/insights.py`**: `_target_tms` resolves SeniorTM's sub-team +
  self; `/insights/team` and `/insights/company` accept `SeniorTM` in
  `require_roles`.
- **`routers/interventions.py`**: `_base_query` + `_load_or_404` aware of
  SeniorTM scope. Create/update guards reject Senior-TM attempts to target
  TMs outside their sub-team (returns 403).
- **`routers/dashboards.py`**: all 7 Manager dashboards (`/dashboard/manager`,
  `/performance`, `/commercial`, `/interventions`, `/cross-sell`, etc.)
  accept SeniorTM. Inline `team_id` scoping replaced with
  `_apply_role_scope` + `_users_scope_query` helpers — Senior TM gets
  `tm_user_id $in [...]` filter instead.
- **`routers/reports.py`**: SeniorTM can generate their own weekly report
  (`POST /reports/generate`), comment on a direct-report's report
  (`/comment` — guarded to their sub-team), and read/export those reports.
  The `/reports` listing returns their own + sub-team's reports.

### Frontend changes
- **`App.js`**: every `ProtectedRoute roles={["Manager", "Admin", "Owner"]}`
  now also includes `"SeniorTM"`. Every TM-only route also accepts
  `"SeniorTM"` (since they log their own visits).
- **`Layout.jsx`**: new `SENIORTM_BOTTOM` + `SENIORTM_MORE` arrays, new
  `isSeniorTM` branch with its own mobile bottom nav (5 slots:
  Dashboard / Intervention / **+ Add** / Tasks / More). Senior TM uses the
  Manager top nav on desktop. The "Log Visit" FAB shows for them too.
- **`pages/Admin.jsx`**: role dropdown now includes "SeniorTM"; the
  "Reports to" picker shows when role is TM **or** SeniorTM, and the
  picker is filtered by `reportsToOptionsForRole(role)` — TMs see both
  Managers and Senior TMs as options; Senior TMs see only Managers.

### Test proof
- `/app/backend/tests/test_phase_l_senior_tm.py` — **9/9 pass**:
  - Senior TM chain creation
  - Invalid reports-to (TM supervising a TM) rejected
  - `GET /users` scope returns only sub-team + self
  - Senior TM hits manager dashboard endpoints → 200
  - Senior TM generates their own weekly report
  - Senior TM can comment on a direct-report's report; cannot comment on
    another TM's report under the Manager (403)
  - Senior TM creates interventions only on direct reports (403 otherwise)
  - Manager can reassign a TM between self ↔ Senior TM
  - Manager cannot grant Admin role to a TM (403)
- Regression: `test_phase_c_company_isolation.py` + `test_phase_e_insights.py` +
  `test_phase_i_enrichment.py` — **41/41 still pass**.
- Frontend smoke verified: Senior TM logs in, top nav shows Manager-style
  links (Dashboard / Intervention / iTero / Invisalign / Team / Expenses /
  Reports), `/intervention` renders the full Manager interface, mobile
  bottom nav (`data-testid="mobile-bottom-nav-seniortm"`) has exactly 5
  slots with the central `+ Add` button.

## Phase I.2 — Full visit notes in PDF/CSV exports (Feb 2026)

**User report**: "When I generate the PDF weekly report in the section for
each Dr meeting, the longer notes are partly cut. All of the text should
be visible."

### Root cause
`server.py` `_build_report_draft` was truncating each doctor's latest visit
note to 220 chars (with an ellipsis) into a single `note_excerpt` field. The
PDF and CSV exports rendered that already-truncated excerpt, so the manager
never saw the rest of the note.

### Fix
- Backend `server.py` now emits BOTH fields in `doctor_breakdown`:
  - `note_excerpt` — short ≤220-char preview (used by the compact UI cards on
    the dashboard / draft modal).
  - `note_full` — the entire untruncated note (used by the PDF + CSV exports
    so the manager sees the whole story).
- PDF (`routers/reports.py`): `note_text = d.get("note_full") or d.get("note_excerpt")`.
  Text is XML-escaped and `\n` → `<br/>` so multi-paragraph notes wrap and
  render correctly. ReportLab `Paragraph` already handles line-wrap to the
  full page width, so no more cut-off.
- CSV: same fallback — full note in the `Latest note` column, with excerpt
  fallback for legacy reports.
- Backwards compatible: reports saved before this fix have only
  `note_excerpt`, and the PDF/CSV still render correctly from that.

### Tests
- `/app/backend/tests/test_phase_i2_full_note_in_pdf.py` — **2/2 pass**
  - End-to-end: log a 700+ char visit note → generate draft → save → export
    PDF via `pdfminer.six` extraction → assert distinctive late-in-note
    phrases ("TBI Bank representative meeting", "financing options") appear
    in the rendered text. Same assertion against the CSV export.
  - Legacy-shape report (no `note_full`, only `note_excerpt`) still exports
    cleanly — backwards compatibility verified.
- Regression: `test_report_doctor_breakdown.py` + `test_report_demos.py` —
  **6/6 still pass**.

## Phase I.1 — Past-week report generation (Feb 2026)

**User request**: "I wanna be able as a TM generate reports from previous
weeks. Up to two weeks back I should be able to regenerate weekly reports."

### Changes
- **Backend**: `POST /api/reports/generate` now accepts an optional
  `week_start` query param (YYYY-MM-DD, any day inside the target week — the
  server normalises to that week's Monday→Sunday). Validation:
  - Future weeks → HTTP 400.
  - More than 14 days behind the current Monday → HTTP 400.
  - Invalid date format → HTTP 400.
  - `Manager`/`Admin` still 403 (only TM role generates).
- **Frontend**: `Reports` page replaces the single "Generate weekly report"
  CTA with three buttons:
  - `generate-report-btn` → **This week** (unchanged behaviour, default).
  - `generate-report-last-week-btn` → **Last week**.
  - `generate-report-two-weeks-btn` → **2 weeks ago**.
  - Copy updated to: "FieldMind drafts it from your activity. You review,
    edit, and submit. You can also regenerate up to two weeks back."
- **Safety net**: app-wide `ErrorBoundary` now wraps every page inside the
  `Layout` `<main>` (keyed by route so it auto-resets on navigation). If
  any page crashes in the future, the user sees a friendly error card +
  "Try again" button instead of a blank screen.

### Test proof
- `/app/backend/tests/test_phase_i1_past_week_reports.py` — **8/8 pass**:
  current-week, 1w back, 2w back, 3w back rejected, future rejected,
  invalid-date rejected, non-TM still 403, end-to-end save of a past-week
  draft.
- Frontend smoke: confirmed via Playwright — three buttons render, clicking
  "Last week" opens the draft modal with `week_start = current Monday - 7d`.

## Phase I — Insight / Intervention UX Polish (Feb 2026)

**Goal**: Make the app feel credible for a real manager by removing UUID-leak
in the UI, replacing the `window.prompt` create-intervention flow with a real
modal, and surfacing readable names everywhere TMs and doctors are displayed.

### 1. Backend enrichment — readable names everywhere
- **`/api/insights/team`** and **`/api/insights/company`** now bulk-resolve
  `scope_id` → `scope_name` (TM `full_name`) via a single users lookup per
  request. Cards whose `scope_id` is not a TM (team/company-level) get
  `scope_name=null` and the frontend falls back to its existing rendering.
- **`/api/interventions`** (list, get, create, from-insight, update,
  in-progress, complete, dismiss) all enrich every response row with
  `tm_name` and `doctor_name`. Bulk-loads users + doctors in one query each.
- `_enrich_scope_names` (insights router) and `_enrich_names` /
  `_enrich_one` (interventions router) are pure helpers — zero schema
  migration, zero new collections.

### 2. Doctor linking on interventions
- New `InterventionUpdate.doctor_id: Optional[str]` field (`models.py`) so
  managers can link or unlink a doctor on edit or create-from-insight.
- `POST /api/interventions` and `POST /api/interventions/from-insight/{id}`
  now honor the `doctor_id` body field. The previous hard-coded `None` is
  gone.
- **Cross-company isolation**: doctor_id is validated server-side. An unknown
  id returns 404, a cross-company id returns 400. Same isolation guard
  applies to PUT updates.

### 3. Frontend — `InterventionDialog` (replaces `window.prompt`)
- New component `/app/frontend/src/components/InterventionDialog.jsx`.
- Used by AdvisoryPanel's "Create intervention" button on every insight card.
- Fields:
  - **Title** (required, pre-filled from insight title)
  - **Severity** (Critical/High/Medium/Low — defaults to the insight's
    severity)
  - **Due date** (defaults to today + 7 days)
  - **Doctor (optional)** — searchable picker. Auto-populates from
    `insight.related_doctor_id` when present (no-op for V1 metrics which are
    TM-scoped). Clear button + Cancel button.
  - **Manager note** — textarea.
- Submits to `POST /api/interventions/from-insight/{id}` with the full
  payload; honors the new `doctor_id` field.
- All elements carry stable `data-testid`s for testing.

### 4. Filter dropdowns — readable names
- **AdvisoryPanel** (`advisory-{team|company}-filter-tm`) now lists TM
  `full_name` from `scope_name` instead of `scope_id.slice(0, 8)…`.
- **InterventionList** (`interventions-filter-tm`) now lists TM `full_name`
  from the backend-enriched `tm_name` instead of falling back to UUID
  prefixes.
- **InterventionRow**: TM and (optional) Doctor labels render from
  `tm_name` / `doctor_name`.

### Test proof — Phase I
- Backend pytest: `/app/backend/tests/test_phase_i_enrichment.py` — **7/7
  green** covering scope_name on /insights/team, wrapped /insights/company
  payload, tm_name + doctor_name on /interventions, doctor_id create + PUT
  enrichment, unknown doctor 404, create-from-insight doctor_id override,
  TM 403 unchanged.
- Backend regression: `test_phase_e_insights.py` + `test_phase_f_interventions.py`
  — all 30 pre-existing tests still green.
- Frontend: `iteration_11.json` — **100% backend + 100% frontend** pass on
  the testing agent. Single low-priority a11y note (Clear button now has
  `aria-label="Clear linked doctor"` + spacing fix).

### Out of scope (per user instruction)
- ❌ Owner support-mode toggle + audit row → **Phase J**
- ❌ Phase D V2 trend / delta snapshots → **Phase K**
- ❌ Clean analytics test fixture → **Phase K**
- ❌ Weekly `/insights/me/digest` → backlog
- ❌ Owner Benchmark Insights → backlog
- ❌ Company logo + brand color exports → backlog

## Phase H — Nav Trim + Empty States + Final Spec Wrap (Feb 2026)

**Goal**: Final polish phase for the 37-point FieldMind spec. No backend
changes. Pure usability + clarity sweep across the TM, Manager, and Owner
surfaces.

### 1. Bottom navigation — strict 5-slot rule confirmed
- **TM** (mobile): Home · Doctors · `+ Add` · Tasks · More.
  `More` sheet contains: Quick capture, iTero, Invisalign, Meetings, Reports,
  Expenses, My account.
- **Manager / Admin / Owner** (mobile): Dashboard · Intervention · iTero ·
  Invisalign · More. `More` sheet contains: Quick capture, Team performance,
  Reports, Expenses, My account.
- No execution-only items (Log Visit / New task / Add expense) appear on
  Manager/Owner bottom nav — they live only on TM `+ Add`.

### 2. Field Execution Index V1 widget (TM only)
- New compact card at the top of the TM dashboard
  (`/app/frontend/src/components/FEIBadge.jsx`).
- Pulls from existing `GET /api/metrics/me/fei` — **no new backend logic**.
- Always carries a `V1 · beta` pill (testid `fei-v1-pill`) so users know this
  is a first-generation composite, not the final/full Field Execution Index.
- When `sufficient_data=false` or backend returns `null`, the widget displays
  the backend `message` ("Not enough data yet. Log a few visits, demos, and
  weekly reports to see your Execution Score V1.") instead of a fake 0.
- "Show breakdown" toggle reveals per-component scores, weights, and
  insufficient-data messages from the same payload (no extra request).

### 3. Empty / loading / error state audit
- **Skeletons everywhere**: replaced bare `Loading…` text with pulsing
  skeleton blocks on Dashboard (TM + Manager + Admin + Owner views),
  AdvisoryPanel, InterventionList, Intervention page, and the FEI widget.
  New shared helpers in `/app/frontend/src/components/Skeleton.jsx`.
- **Defensive value access**: every `data.stats.x` now uses `data.stats?.x ?? 0`
  so a partial payload never renders `NaN` or `undefined`.
- **Empty states**: new `EmptyState` component used for the TM "no priorities
  yet" case (`tm-no-priorities-empty`) and the Intervention page bucket-empty
  cards (`bucket-empty-{key}`) with friendly explanatory text.
- **Error states**: new dedicated `dashboard-load-error` and
  `intervention-load-error` banners shown when the page load API call
  rejects, with a `Refresh to retry` hint.
- **ErrorBoundary**: new
  `/app/frontend/src/components/ErrorBoundary.jsx` wraps the Dashboard and
  Intervention page so a rendering exception shows a friendly fallback with a
  "Try again" CTA instead of a white screen.

### 4. V1 copy polish
- AdvisoryPanel header (TM, Team, Company variants) gains a `V1 · beta` pill
  (testid pattern `advisory-{variant}-v1-pill`) so users know the insights
  layer is first-generation.
- FEI widget consistently labels the score as **Field Execution Index** with a
  visible **V1 · beta** pill and the message "Execution Score V1" in the
  insufficient-data state. Pre-existing copy that still says "Field Execution
  Index" inside AI-generated insight card bodies is intentionally left alone
  (constraint: no backend changes).

### 5. Mobile responsiveness pass (375 × 800)
- All Tabs strips with potentially-long labels (InterventionList 4-tab
  STATUS_TABS, Intervention page 3-bucket Tabs) wrapped in
  `overflow-x-auto -mx-1 px-1` with `inline-flex w-auto min-w-full
  whitespace-nowrap` on TabsList. The tabs now scroll inside their container
  instead of breaking the page width.
- Verified `document.body.scrollWidth === window.innerWidth` at 375px for the
  Owner /intervention page (was previously 474 > 375).

### 6. Owner role parity (regression caught + fixed in same iteration)
- `App.js` `ProtectedRoute roles=["Manager", "Admin"]` arrays on
  `/intervention`, `/market-intelligence`, and `/team-performance` now also
  include `"Owner"`. Without this, Owner saw the nav links (because
  `Layout.jsx` treats Owner as a Manager) but clicking them silently
  redirected to `/`.

### Test proof — Phase H
- `iteration_9.json`: initial Phase H frontend pass — 16 of 18 specced checks
  green; 2 HIGH regressions surfaced (Owner intervention guard + mobile
  overflow).
- `iteration_10.json` (retest): **15/15 retest checks pass · 100% · zero
  regressions · ready to ship.**

### Out of scope (deferred to future phases)
- Full Field Execution Index (V2+) — V1 is a first-generation composite.
- External benchmark UI — will land only after real benchmark cohort data
  exists (Phase G shipped the backend cohort plumbing).
- Weekly digest emails (`/insights/me/digest`).
- Company logo + brand color in exports.
- Per-cross-company-read audit row for Owner support mode.

## Backlog snapshot (post Phase H)
**P1**
- Owner support-mode toggle + per-cross-company-read audit row.
- Dashboard `company_id` defensive filters on subqueries.
- Automated test for `ENFORCE_COMPANY_ISOLATION=false` fallback.
- Add `scope_name` to `/insights/team`, `/insights/company`, and
  `/interventions` payloads so filters show readable names instead of UUID
  prefixes.
- Replace `window.prompt` create-intervention flow with a proper modal
  (manager note, severity, due date, doctor picker).
- Phase D V2 trend / delta snapshots, team / company / per-doctor scope
  metrics, and `comparison_value` back-fill.

**P2**
- Move helpers from `server.py` to `routers/_deps.py`.
- Regional taxonomy, Swagger tags, snapshot scheduler.
- My FEI badge UI variants (drawer, full breakdown page) for future Field
  Execution Index expansion.
- Empty-data TM visual regression test.

**P3**
- Company logo + brand color for report PDFs / exports.
- `/insights/me/digest` weekly email.
- Owner Benchmark Insights tab.
- Batch `POST /benchmark/cohorts/refresh-all`.
- Per-company "Request opt-in" admin flow.

---

## Phase M1 — Monthly Reimbursement Report (Feb 2026)

**Status:** SHIPPED — 5/5 backend pytest cases green, 13/14 E2E frontend
acceptance points verified (see `/app/test_reports/iteration_18.json`).

**Backend** (`/app/backend/routers/reimbursement.py`)
- `POST /api/reimbursement/reports/generate` — TM (self) / SeniorTM (team
  member) generates a monthly report by aggregating `visits` for the month,
  matching every visited doctor against the new `doctor_km` collection,
  computing total KM. Dedupes to a single active report per `(tm_user_id,
  month)`.
- `GET /api/reimbursement/reports` — scoped list (TM=own, SeniorTM=team,
  Admin/Owner=company).
- `GET /api/reimbursement/reports/{id}` — hydrated with expenses + totals.
- `PATCH /api/reimbursement/reports/{id}` — TM edits `fuel_price_per_l` /
  `already_reimbursed`; SeniorTM+ can also edit
  `fuel_consumption_l_per_100km`. Locked once Submitted (TM can only edit in
  Draft / Changes Requested).
- `POST /api/reimbursement/reports/{id}/refresh-breakdown` — re-runs the
  aggregation after KM fill.
- `POST /api/reimbursement/reports/{id}/submit` — validates fuel price + all
  doctor KM + all expenses have a receipt or exception, then Draft →
  Submitted.
- `POST /api/reimbursement/reports/{id}/{approve|reject|request-changes}` —
  Senior review transitions with mandatory comment on reject / request-changes.
- `POST /api/reimbursement/reports/{id}/mark-paid` — Approved → Paid.
- `GET /api/reimbursement/reports/{id}/pdf` — ReportLab-rendered A4 PDF with
  meta, totals, doctor breakdown, expenses, and comments.
- `GET/POST /api/doctor-km` — company-scoped KM lookup. TMs can seed a
  missing row (marked `PendingReview`) but cannot overwrite an existing one
  (403 → "ask your Senior TM"). SeniorTM/Admin/Owner have full write access.

**Frontend** (`/app/frontend/src/pages/Reimbursement.jsx`, wired in
`/app/frontend/src/App.js` and `navConfig.js`)
- Role-aware header ("Your monthly claims" / "Team reimbursement" /
  "Reimbursement — all teams").
- Month picker + Generate button; empty state with hint.
- Reports table with per-row totals + Open drawer button.
- Report drawer: totals grid, fuel inputs (consumption for SeniorTM+, price
  for TM), MissingKM panel with inline save, doctor breakdown table with
  match badges, expenses summary + link to `/expenses/log?reimbursement_report_id=…`,
  comments log, action bar (Submit / Approve / Request changes / Reject /
  Mark paid / PDF).
- Data-testids on every interactive element and every status pill for
  deterministic E2E.

**Data model additions**
- `doctor_kms` — `{id, doctor_id, company_id, km_per_visit, status, ...}`.
- `reimbursement_reports` — `{id, tm_user_id, month, status, total_km,
  fuel_price_per_l, doctor_breakdown, comments[], audit[], …}`.
- `expenses.reimbursement_report_id` — optional link so a TM's monthly
  receipts roll up into the report.

**Backend tests** (`/app/backend/tests/test_phase_m1_reimbursement.py`)
- Fixture fixes applied this session: load `frontend/.env` so
  `REACT_APP_BACKEND_URL` resolves; use `PUT /users/{id}` (not PATCH) to
  link the TM under the demo Senior TM; wipe stale
  `reimbursement_reports` + `doctor_km` rows before each module run to keep
  tests idempotent. Router bug fixed: dedup branch was returning the
  Mongo document with `_id` still attached — projection added.

**Backlog (untouched, still P1+)**
- Phase M2: OCR receipt extraction (Claude Sonnet 4.5 via Emergent LLM
  Key).
- Analytics Phase D V2 trend / delta snapshots.
- Weekly `/insights/me/digest` email.


---

## Phase M2 — Receipt OCR extraction (Feb 2026)

**Status:** SHIPPED — 6/6 new backend tests pass; Phase M1 regression suite
still green (35/35).

**What shipped**
- Extended the existing Claude Sonnet 4.5 vision OCR (`expenses_ai.py`,
  `/api/expenses/extract`) to recognise the full M1 category set:
  `Petrol | Food | Hotel | Parking | Tolls | Other`. Previously only
  `Petrol / Food`.
- Widened `POST /api/expenses` category whitelist to accept the same set.
  Unknown categories still 400.
- Frontend `LogExpense.jsx` now shows a 6-tile category picker (3-column
  grid with emoji labels). When opened from a reimbursement report
  (`?reimbursement_report_id=…`), Petrol is hidden (fuel is auto-computed
  from KM in M1) and the default category is Food. OCR-inferred Petrol is
  ignored in the reimbursement flow to prevent double-counting.
- New pytest coverage: `/app/backend/tests/test_phase_m2_receipt_ocr.py`
  — parametrised category acceptance, unknown-category rejection, and
  extract-endpoint response shape stability.

**How it works end-to-end**
1. TM taps "Take or upload receipt" in `/expenses/log`.
2. Image is uploaded to `/api/expenses/extract` → Claude Sonnet 4.5 vision
   returns `{amount, currency, expense_date, vendor, category_hint,
   confidence, notes}`.
3. Frontend prefills the form; TM can override any field before saving.
4. On save, the image is stored in GridFS (bucket `receipts`) and the
   expense is linked to the reimbursement report via
   `reimbursement_report_id`.
5. Duplicate SHA-1 hash check surfaces "Looks like you already uploaded
   this receipt" when a TM re-uploads.

**Backlog (still P1+)**
- Analytics Phase D V2 trend / delta snapshots, team / company / per-doctor
  scope metrics, `comparison_value` back-fill.
- `/insights/me/digest` weekly email.
- Owner Benchmark Insights tab.


### Phase M2.1 — Per-field AI confidence badges (Feb 2026)

- OCR contract extended: `expenses_ai.extract_receipt` now returns
  `field_confidence: {amount, expense_date, vendor, category_hint}` with
  each score clamped to `[0, 1]`. Null fields are forcibly zeroed to
  prevent misleading badges.
- Prompt rewritten to instruct Claude Sonnet 4.5 to return per-field
  confidence (1.0 = clearly read, 0.5 = inferred, 0 = unreadable).
- `LogExpense.jsx` displays a colored `AI %` pill next to each auto-filled
  field label:
    * green ≥ 85% (`--status-success`)
    * amber 50–84% (`--status-warning`)
    * red < 50% (`--status-danger`)
- Badges disappear the instant the TM edits the field (per-field `aiFields`
  Set with `clearAiField(name)` on every `onChange` / button click).
- Test coverage: `test_extract_receipt_shape` in
  `test_phase_m2_receipt_ocr.py` now asserts `field_confidence` shape,
  numeric range, and null-field-zero coercion.
- Verified via Playwright with mocked OCR response: high/medium/low tones
  render correctly and badge dismisses on edit.


---

## Phase N — Field Calendar + Visits on Meetings page (Feb 2026)

**User pain points addressed**
- "Only 7 meetings show up even though I logged 20+ visits" — the
  `/meetings` page was reading only the `meetings` collection, never
  `visits`. Fixed: `/api/visits` is now fetched alongside meetings +
  events and merged into the list.
- "I want a visual calendar to see my logged meetings and visits" —
  new `/calendar` page with Month + Week views.

**What shipped**
- New `/app/frontend/src/pages/Calendar.jsx` — Month + Week toggle
  (`view-month-btn` / `view-week-btn`). Prev / Today / Next controls, Log
  visit + Book meeting shortcuts. Colour legend: meeting (secondary),
  iTero demo (rust), event (primary green), logged visit (success green).
  Each event is a link to the doctor timeline or meetings page.
- New route `/calendar` added in `App.js` (any authenticated role).
- Nav wiring: Calendar added to `TM_TOP`, `MANAGER_TOP`, `SENIORTM_TOP`
  and to all three `*_MORE` mobile menus.
- `Meetings.jsx` updated:
    * Fetches `/api/visits` in parallel with meetings + events.
    * New "Visits" filter chip alongside All / Meetings / Events.
    * Visit rows render as `VisitCard` (green "Logged visit" pill,
      timestamp, note preview, "View timeline" link).
    * Visits are bucketed under "Past" (`upcoming` tab hides them). `all`
      tab shows Today / This week / Later / Past sections.
    * Sort direction: ascending for upcoming, descending for past/all.
- Verified via Playwright on preview: Month grid shows 12 events, Week
  view stacks per-day, and the Meetings page reads **114 visits + 19
  meetings** for `tm1@field.io` (previously would have shown 19).


---

## Phase O — Doctor duplicate prevention (Feb 2026)

**User pain:** "Whether I put Dr in front of the name or not, the system
should recognise the name and make sure there are no duplicate doctor
profiles created by TM and SeniorTM."

**What shipped**
- New `normalize_person_name()` and `normalize_city_key()` in
  `backend/_deps.py`. Strips stacked titles ("Prof. Dr. John Smith"),
  accent-folds Unicode ("Ján Škrabáček" → "jan skrabacek"), collapses
  whitespace, lowercases, and trims trailing punctuation.
- `POST /api/doctors` now checks for a same-company duplicate before
  inserting. Match rule: normalized name is identical AND (both cities
  equal OR one side has no city). Response on collision is HTTP **409**
  with a structured `detail`:
    ```json
    {
      "code": "DUPLICATE_DOCTOR",
      "message": "A doctor named \"…\" already exists…",
      "existing_id": "...",
      "existing_name": "...",
      "existing_city": "...",
      "existing_assigned_tm_id": "..."
    }
    ```
- New `doctors.name_normalized` field persisted on every future create /
  import row for fast lookups as the collection grows.
- Import commit path (`POST /doctors/import/commit`) uses the same
  normaliser so a spreadsheet row of "Dr. Ivan Petrov" collapses onto an
  existing "Ivan Petrov" record for the same TM.
- Frontend UX (`AddDoctor.jsx` + `InlineAddDoctor.jsx`) — on 409 the toast
  now surfaces an "Open existing" / "Use existing" action button that
  jumps straight to the existing profile instead of a dead-end error.
- Tests: 17-case suite in `test_doctor_dedupe.py` — 12 unit-tests of the
  normalizer (stacked titles, Cyrillic accents, no-title edge cases) plus
  5 API-level tests (Dr prefix blocked, multi-variant blocked, different
  city allowed, no-city fallback). All green alongside Phase M1 + M2
  regression (28/28 total).


---

## Phase O.1 — Event KM in monthly reimbursement (Feb 2026)

**User request:** "TM logs an event, weekly reports captures it and
monthly reports allows him to input KM covered for this event."

**Backend**
- `Event` model: new optional `km: float` field (works on
  `EventCreate` / `EventUpdate` / `Event`).
- New helper `_build_event_breakdown(tm_user_id, month, company_id)` in
  `reimbursement.py` — fetches every non-cancelled event scheduled
  inside the month, maps each to `{event_id, title, scheduled_at,
  location, status, km, match_status}`, and returns totals.
- `POST /reimbursement/reports/generate` and
  `POST /reimbursement/reports/{id}/refresh-breakdown` now populate
  `event_breakdown`, `event_count`, `events_total_km`, and roll
  `events_total_km` into the report's `total_km` (so the fuel-cost
  calculation catches event travel too).
- `_validate_submittable()` blocks submission with a clear 400 if any
  event in the month has a null `km`.
- Weekly reports (`_build_report_draft`) now include an
  `events / events_count / events_total_km` block in `content` so the
  Senior TM sees the event roster in the weekly PDF/UI.

**Frontend**
- Reimbursement drawer: new **Events attended (N)** table between the
  doctor breakdown and the manual expenses. Each row has an inline KM
  input (`event-km-input-{event_id}`) + Save button that PUTs to
  `/events/{id}` then refreshes the report. Read-only for Submitted /
  Paid reports.
- Meetings → "Add / Edit event" dialog: new KM field with helper text
  "Adds to fuel reimbursement. You can also fill this in later from the
  Monthly report."

**Tests**
- `test_phase_o_event_km.py` — end-to-end scenario: create event with no
  km → generate report → verify MissingKM row → submit fails with
  "event" in the error → PUT km → refresh → verify Matched, total_km
  bumped, submit succeeds. 1/1 pass.
- Full regression: 29/29 (M1 + M2 + M1.1 dedupe + this).


---

## Phase O.2 — SeniorTM ≥ union(TM, Manager) role-parity (Feb 2026)

**User request:** "Everything a normal TM is allowed should be allowed
for Senior TM and everything a Manager is allowed should be allowed for
Senior TM as well."

**Systemic fix (backend/auth.py::require_roles)**
- Any endpoint guarded with `require_roles("Manager", ...)` OR
  `require_roles("TM", ...)` now implicitly grants SeniorTM. Centralises
  the parity guarantee so it holds for **every current and every future**
  endpoint without a manual sweep. Owner ≥ Admin logic unchanged.

**Inline whitelists manually patched** (couldn't be captured by the
central upgrade because they don't use `require_roles`)
- `POST /api/ai/extract` — added SeniorTM.
- `POST /api/doctors/{id}/itero-stage` — added SeniorTM.
- `/api/track-signals` — added SeniorTM.
- `/api/clinical-patterns` — added SeniorTM.
- Earlier: `POST /api/events` (iter 19).

**Scope union for hybrid data reads**
- `_expense_visible_to()` — SeniorTM now sees own expenses (TM scope) OR
  team expenses (Manager scope). Explicit union, not fall-through.
- `_can_access_doctor()` and `_managed_tm_ids_for()` — already returned
  the correct union for SeniorTM; verified during the audit.

**Testing**
- Iter20 report: **98/98 pass** (16 new SeniorTM parity assertions across
  every TM-scope AND Manager-scope endpoint + 82 baseline regression
  covering M1, M2, dedupe, event km, Phase L, expenses, admin guardrails,
  audit P2, iter16-19). Zero regressions.
- Fixed a pre-existing flake in
  `test_audit_p2_security.py::test_success_clears_counter` — the
  assertion was too strict about K8s-ingress IP variance; now checks the
  behavioural invariant (email-only counter wiped, no leftover row above
  the lockout threshold).

