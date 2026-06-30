import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../../lib/api";
import {
  Activity, AlertTriangle, Calendar, CalendarClock, CheckCircle2, ClipboardList,
  Flame, MapPin, Sun,
} from "lucide-react";

import StatCard from "./StatCard";
import { StatusPill, sentimentKind, cadenceKind, priorityKind, SegmentBadge } from "../StatusPill";
import AdvisoryPanel from "../AdvisoryPanel";
import InterventionList from "../InterventionList";
import FEIBadge from "../FEIBadge";
import EmptyState from "../EmptyState";
import { StatGridSkeleton, CardSkeleton } from "../Skeleton";

function PriorityCard({ d, idx }) {
  return (
    <Link
      to={`/doctors/${d.id}`}
      data-testid={`priority-doctor-${d.id}`}
      className="block rounded-md border p-4 card-lift fade-up"
      style={{ background: "var(--bg-default)", borderColor: "var(--border-default)", animationDelay: `${idx * 30}ms` }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-display text-base font-semibold truncate" style={{ color: "var(--brand-primary)" }}>{d.doctor_name}</div>
          <div className="text-sm truncate flex items-center gap-1" style={{ color: "var(--text-secondary)" }}>
            <MapPin className="w-3 h-3" /> {d.clinic_name || "—"} · {d.city || "—"}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <SegmentBadge segment={d.segment} />
          <StatusPill kind={priorityKind(d.visit_priority_label)} testId={`priority-label-${d.id}`}>
            <Flame className="w-3 h-3" /> {d.visit_priority_label} · {d.visit_priority_score}
          </StatusPill>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Last visit</div>
          <div style={{ color: "var(--text-primary)" }}>{d.days_since_last_visit ?? "—"}d ago</div>
        </div>
        <div>
          <div className="uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Cadence</div>
          <StatusPill kind={cadenceKind(d.cadence_status)}>{d.cadence_status}</StatusPill>
        </div>
        <div>
          <div className="uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Sentiment</div>
          <StatusPill kind={sentimentKind(d.current_sentiment)}>{d.current_sentiment || "—"}</StatusPill>
        </div>
      </div>
      {d.suggested_next_action && (
        <div className="mt-3 text-xs italic px-3 py-2 rounded" style={{ background: "var(--bg-paper)", color: "var(--text-secondary)" }}>
          → {d.suggested_next_action}
        </div>
      )}
      {(d.open_promises > 0 || d.overdue_promises > 0) && (
        <div className="mt-3 flex gap-2 text-xs">
          {d.overdue_promises > 0 && <StatusPill kind="danger"><AlertTriangle className="w-3 h-3" />{d.overdue_promises} overdue</StatusPill>}
          {d.open_promises > 0 && <StatusPill kind="info"><ClipboardList className="w-3 h-3" />{d.open_promises} open promise{d.open_promises > 1 ? "s" : ""}</StatusPill>}
        </div>
      )}
    </Link>
  );
}

function UpcomingDemosWidget() {
  const [demos, setDemos] = useState(null);
  useEffect(() => {
    api.get("/itero/demos").then((r) => setDemos(r.data)).catch(() => setDemos({ booked: [] }));
  }, []);
  if (!demos) return null;
  const list = (demos.booked || []).slice(0, 4);
  if (list.length === 0) return null;
  const fmt = (s) => {
    try { return new Date(s).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }); }
    catch { return s; }
  };
  const rel = (s) => {
    if (!s) return null;
    try {
      const d = new Date(s); d.setHours(0, 0, 0, 0);
      const today = new Date(); today.setHours(0, 0, 0, 0);
      const days = Math.round((d - today) / 86400000);
      if (days < 0) return `${-days}d ago`;
      if (days === 0) return "Today";
      if (days === 1) return "Tomorrow";
      return `In ${days}d`;
    } catch { return null; }
  };
  return (
    <div data-testid="dashboard-demos-widget" className="rounded-md border p-5 mb-8" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>iTero · Booked demos</div>
          <h3 className="font-display text-lg font-medium" style={{ color: "var(--brand-primary)" }}>Upcoming demos</h3>
        </div>
        <Link to="/itero/demos" className="text-sm hover:underline" style={{ color: "var(--brand-secondary)" }}>See all →</Link>
      </div>
      <div className="grid sm:grid-cols-2 gap-2">
        {list.map((r) => {
          const overdue = (() => {
            try {
              const d = new Date(r.booked_date); d.setHours(0, 0, 0, 0);
              const t = new Date(); t.setHours(0, 0, 0, 0);
              return d < t;
            } catch { return false; }
          })();
          return (
            <Link
              key={r.doctor_id}
              to={`/doctors/${r.doctor_id}`}
              data-testid={`dashboard-demo-${r.doctor_id}`}
              className="flex items-center justify-between p-3 rounded border transition-colors hover:border-[var(--brand-primary)]"
              style={{ borderColor: overdue ? "var(--status-danger)" : "var(--border-default)", background: "var(--bg-paper)" }}
            >
              <div className="min-w-0">
                <div className="font-medium text-sm truncate" style={{ color: "var(--brand-primary)" }}>{r.doctor_name}</div>
                <div className="text-xs truncate" style={{ color: "var(--text-secondary)" }}>{[r.clinic_name, r.city].filter(Boolean).join(" · ") || "—"}</div>
              </div>
              <div className="text-right shrink-0 ml-2">
                <div className="text-sm font-mono" style={{ color: overdue ? "var(--status-danger)" : "var(--text-primary)" }}>{fmt(r.booked_date)}</div>
                <div className="text-[10px]" style={{ color: overdue ? "var(--status-danger)" : "var(--text-muted)" }}>{rel(r.booked_date)}</div>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export default function TMView({ data }) {
  if (!data) {
    return (
      <div data-testid="tm-view-skeleton">
        <div
          className="rounded-md border p-4 mb-4 animate-pulse"
          style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
        >
          <div className="h-3 w-40 rounded mb-2" style={{ background: "var(--bg-muted)" }} />
          <div className="h-7 w-24 rounded" style={{ background: "var(--bg-muted)" }} />
        </div>
        <StatGridSkeleton count={4} testId="tm-stats-skeleton-1" />
        <StatGridSkeleton count={2} testId="tm-stats-skeleton-2" />
        <CardSkeleton testId="tm-advisory-skeleton" rows={4} />
      </div>
    );
  }
  const topPriorities = data.top_priorities || [];
  const overdueDoctors = data.overdue_doctors || [];
  return (
    <>
      <FEIBadge />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-3">
        <StatCard label="Visits this week" value={data.stats?.visits_this_week ?? 0} icon={Activity} kind="info" testId="stat-visits-week" />
        <StatCard label="Open promises" value={data.stats?.open_promises ?? 0} icon={ClipboardList} kind="muted" testId="stat-open-promises" />
        <StatCard label="Overdue" value={data.stats?.overdue_promises ?? 0} icon={AlertTriangle} kind="danger" testId="stat-overdue" />
        <StatCard label="Due today" value={data.stats?.due_today ?? 0} icon={CalendarClock} kind="warning" testId="stat-due-today" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Open meetings" value={data.stats?.open_meetings ?? 0} icon={Calendar} kind="muted" testId="stat-open-meetings" />
        <StatCard label="Meetings done this week" value={data.stats?.completed_meetings_this_week ?? 0} icon={CheckCircle2} kind="success" testId="stat-completed-meetings-week" />
      </div>

      <UpcomingDemosWidget />
      <InterventionList variant="tm" />
      <AdvisoryPanel variant="tm" />

      <div className="flex items-baseline justify-between mb-4">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Today&apos;s intelligence</div>
          <h2 className="font-display text-2xl font-medium" style={{ color: "var(--brand-primary)" }}>Doctors who need you next</h2>
        </div>
        <Link to="/doctors" className="text-sm underline" style={{ color: "var(--text-secondary)" }} data-testid="see-all-doctors-link">
          See all →
        </Link>
      </div>

      {topPriorities.length === 0 ? (
        <EmptyState
          icon={Sun}
          tone="success"
          title="Clear sky — nothing urgent right now"
          description="Add a few doctors or log a visit to start surfacing priorities here."
          testId="tm-no-priorities-empty"
        />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8" data-testid="priority-doctors-grid">
          {topPriorities.map((d, idx) => <PriorityCard key={d.id} d={d} idx={idx} />)}
        </div>
      )}

      {overdueDoctors.length > 0 && (
        <div className="rounded-md border p-6 mb-8" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <h3 className="font-display text-lg font-medium mb-4 flex items-center gap-2" style={{ color: "var(--brand-primary)" }}>
            <AlertTriangle className="w-5 h-5" style={{ color: "var(--status-danger)" }} /> Promises you owe
          </h3>
          <div className="grid sm:grid-cols-2 gap-3">
            {overdueDoctors.map((d) => (
              <Link key={d.id} to={`/doctors/${d.id}`} className="flex items-center justify-between p-3 rounded hover:bg-[var(--bg-paper)] border" style={{ borderColor: "var(--border-default)" }}>
                <div>
                  <div className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>{d.doctor_name}</div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>{d.clinic_name} · {d.city}</div>
                </div>
                <StatusPill kind="danger">{d.overdue_promises} overdue</StatusPill>
              </Link>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
