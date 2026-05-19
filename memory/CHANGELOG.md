# FieldMind — Changelog

This file tracks shippable changes by phase, growing forward. Original product
requirements and historical iteration log remain in `/app/memory/PRD.md`.

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
