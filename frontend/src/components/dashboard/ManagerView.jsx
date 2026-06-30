import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../lib/auth";
import { Activity, AlertTriangle, Calendar, CheckCircle2, Sparkles, Users } from "lucide-react";

import StatCard from "./StatCard";
import AdvisoryPanel from "../AdvisoryPanel";
import { StatGridSkeleton, CardSkeleton } from "../Skeleton";

function CrossBucket({ label, items, kind, testId }) {
  const color =
    kind === "success" ? "var(--status-success)" :
    kind === "warning" ? "var(--status-warning)" :
                         "var(--status-info)";
  return (
    <div data-testid={testId}>
      <div className="text-xs uppercase tracking-widest mb-2" style={{ color }}>{label}</div>
      <div className="space-y-1">
        {items.length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>None.</div>}
        {items.slice(0, 5).map((d) => (
          <Link key={d.id} to={`/doctors/${d.id}`} className="block rounded p-2 hover:bg-[var(--bg-paper)]">
            <div className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{d.doctor_name}</div>
            <div className="text-xs" style={{ color: "var(--text-secondary)" }}>{d.reason}</div>
            <div className="text-xs italic mt-0.5" style={{ color }}>→ {d.suggested_action}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function ManagerView({ data, commercial, interventions, crossSell }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  // P1 follow-up — progressive rendering. Each prop loads independently so
  // each card can appear as soon as its own endpoint resolves. The full-page
  // skeleton fallback is only used during the very first paint when NOTHING
  // has arrived yet (keeps the layout from snapping in once data lands).
  if (!data && !commercial && !interventions && !crossSell) {
    return (
      <div data-testid="manager-view-skeleton">
        <StatGridSkeleton count={4} testId="manager-stats-skeleton-1" />
        <StatGridSkeleton count={2} testId="manager-stats-skeleton-2" />
        <CardSkeleton testId="manager-advisory-skeleton" rows={4} />
      </div>
    );
  }
  const critCount = (interventions?.critical || []).length;
  const atRiskCount = (interventions?.at_risk || []).length;
  const oppCount = (interventions?.high_opportunity || []).length;

  return (
    <>
      {data ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-3">
            <StatCard label="Visits this week" value={data.stats?.visits_week ?? 0} icon={Activity} kind="info" testId="stat-visits-week" />
            <StatCard label="Doctors" value={data.stats?.doctors ?? 0} icon={Users} kind="muted" testId="stat-doctors" />
            <StatCard label="Critical" value={critCount} icon={AlertTriangle} kind="danger" testId="stat-critical" />
            <StatCard label="High opportunity" value={oppCount} icon={Sparkles} kind="success" testId="stat-opportunity" />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <StatCard label="Open meetings" value={data.stats?.open_meetings ?? 0} icon={Calendar} kind="muted" testId="stat-open-meetings" />
            <StatCard label="Meetings done this week" value={data.stats?.completed_meetings_this_week ?? 0} icon={CheckCircle2} kind="success" testId="stat-completed-meetings-week" />
          </div>
        </>
      ) : (
        <>
          <StatGridSkeleton count={4} testId="manager-stats-skeleton-1" />
          <StatGridSkeleton count={2} testId="manager-stats-skeleton-2" />
        </>
      )}

      {(commercial?.drop_offs || []).length > 0 && (
        <div className="rounded-md border p-4 mb-6" style={{ background: "var(--status-danger-bg)", borderColor: "var(--status-danger)" }} data-testid="alerts-strip">
          <div className="flex items-center gap-2 mb-2 text-xs uppercase tracking-widest" style={{ color: "var(--status-danger)" }}>
            <AlertTriangle className="w-4 h-4" /> Alerts
          </div>
          <div className="flex flex-wrap gap-2">
            {commercial.drop_offs.map((d) => (
              <span key={d.key} className="pill pill-danger" data-testid={`alert-${d.key}`}>{d.label} — {d.detail}</span>
            ))}
          </div>
        </div>
      )}

      <AdvisoryPanel variant="team" />
      {user?.role === "Admin" || user?.role === "Owner" ? <AdvisoryPanel variant="company" /> : null}

      {crossSell ? (
        <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="cross-sell-panel">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Cross-sell insights</div>
            <h3 className="font-display text-xl font-medium" style={{ color: "var(--brand-primary)" }}>Where iTero and Invisalign meet</h3>
          </div>
        </div>
        <div className="grid md:grid-cols-3 gap-4">
          <CrossBucket label="Invisalign strong, no iTero" items={crossSell?.invisalign_strong_no_itero || []} kind="info" testId="cross-inv-no-itero" />
          <CrossBucket label="iTero present, low Invisalign" items={crossSell?.itero_present_low_invisalign || []} kind="warning" testId="cross-itero-low-inv" />
          <CrossBucket label="High opportunity for both" items={crossSell?.high_opportunity_both || []} kind="success" testId="cross-high-both" />
        </div>
      </div>
      ) : (
        <CardSkeleton testId="cross-sell-skeleton" rows={3} />
      )}

      {data && (
        <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="market-pulse-card">
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Market pulse</div>
          <p className="text-sm mt-1 leading-relaxed" data-testid="market-pulse" style={{ color: "var(--text-primary)" }}>{data.market_pulse}</p>
        </div>
      )}

      <div className="grid sm:grid-cols-3 gap-4 mb-6">
        <button onClick={() => navigate("/itero")} data-testid="quick-link-itero" className="rounded-md border p-5 text-left card-lift" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="text-xs uppercase tracking-widest flex items-center gap-1" style={{ color: "var(--brand-accent)" }}>iTero</div>
          <div className="font-display text-2xl font-medium mt-1" style={{ color: "var(--brand-primary)" }}>scanner</div>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>demo funnel · drop-offs · TM perf →</div>
        </button>
        <button onClick={() => navigate("/invisalign")} data-testid="quick-link-invisalign" className="rounded-md border p-5 text-left card-lift" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="text-xs uppercase tracking-widest flex items-center gap-1" style={{ color: "var(--brand-secondary)" }}>Invisalign</div>
          <div className="font-display text-2xl font-medium mt-1" style={{ color: "var(--brand-primary)" }}>aligners</div>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>growth · confidence · barriers →</div>
        </button>
        <button onClick={() => navigate("/intervention")} data-testid="quick-link-intervention" className="rounded-md border p-5 text-left card-lift" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="text-xs uppercase tracking-widest flex items-center gap-1" style={{ color: "var(--status-danger)" }}>
            <AlertTriangle className="w-3 h-3" /> Intervention
          </div>
          <div className="font-display text-2xl font-medium mt-1" style={{ color: "var(--brand-primary)" }}>{critCount + atRiskCount}</div>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>doctors needing attention →</div>
        </button>
      </div>
    </>
  );
}
