# FieldMind — Changelog

This file tracks shippable changes by phase, growing forward. Original product
requirements and historical iteration log remain in `/app/memory/PRD.md`.

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
