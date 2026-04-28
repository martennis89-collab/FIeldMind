import React, { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { Link } from "react-router-dom";
import { StatusPill, sentimentKind, cadenceKind, priorityKind, SegmentBadge } from "../components/StatusPill";
import {
  Activity, AlertTriangle, CalendarClock, CheckCircle2, ClipboardList, Flame, MapPin, TrendingDown, TrendingUp, Users,
  Sparkles, ChevronRight, ChevronDown, Target,
} from "lucide-react";

function StatCard({ label, value, sub, icon: Icon, kind = "muted", testId }) {
  const colors = {
    success: { bg: "var(--status-success-bg)", fg: "var(--status-success)" },
    warning: { bg: "var(--status-warning-bg)", fg: "var(--status-warning)" },
    danger: { bg: "var(--status-danger-bg)", fg: "var(--status-danger)" },
    info: { bg: "var(--status-info-bg)", fg: "var(--status-info)" },
    muted: { bg: "var(--bg-paper)", fg: "var(--text-primary)" },
  }[kind];
  return (
    <div className="rounded-md border p-5 card-lift" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={testId}>
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{label}</div>
        <div className="w-9 h-9 rounded-md flex items-center justify-center" style={{ background: colors.bg, color: colors.fg }}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
      <div className="mt-3 font-display text-3xl font-medium" style={{ color: "var(--brand-primary)" }}>{value}</div>
      {sub && <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{sub}</div>}
    </div>
  );
}

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

function TMPerformanceTable({ performance }) {
  const [expanded, setExpanded] = React.useState(null);
  const rows = performance?.rows || [];
  return (
    <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="tm-performance-table">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Team performance</div>
          <h3 className="font-display text-xl font-medium" style={{ color: "var(--brand-primary)" }}>How each TM is doing</h3>
        </div>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>Last 30 days</span>
      </div>
      {rows.length === 0 && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>}

      <div className="space-y-2">
        {rows.map((r) => {
          const isOpen = expanded === r.tm_id;
          const targetRatio = r.visits_vs_target;
          const ratioKind = targetRatio >= 0.9 ? "success" : targetRatio >= 0.6 ? "warning" : "danger";
          const completionPct = Math.round(r.completion_rate * 100);
          const completionKind = r.promises_total_30d < 3 ? "muted" : completionPct >= 70 ? "success" : completionPct >= 40 ? "warning" : "danger";
          const sentTrendIcon = r.sentiment_trend === "improving" ? <TrendingUp className="w-3 h-3" /> : r.sentiment_trend === "declining" ? <TrendingDown className="w-3 h-3" /> : null;
          const sentKind = r.sentiment_trend === "improving" ? "success" : r.sentiment_trend === "declining" ? "danger" : "muted";

          return (
            <div key={r.tm_id} className="rounded-md border" style={{ borderColor: "var(--border-default)" }} data-testid={`tm-perf-row-${r.tm_id}`}>
              <button
                onClick={() => setExpanded(isOpen ? null : r.tm_id)}
                className="w-full text-left p-3 hover:bg-[var(--bg-paper)] rounded-md transition-colors"
                data-testid={`expand-tm-${r.tm_id}`}
              >
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium" style={{ color: "var(--text-primary)" }}>{r.tm_name}</div>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>{r.doctors} doctors</div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <StatusPill kind={ratioKind} testId={`metric-target-${r.tm_id}`}>
                      <Target className="w-3 h-3" />{r.visits_month}/{r.visits_target_month} visits
                    </StatusPill>
                    <StatusPill kind="muted">{r.avg_visits_per_day}/day</StatusPill>
                    {r.overdue_count > 0 && <StatusPill kind="danger"><AlertTriangle className="w-3 h-3" />{r.overdue_count} overdue</StatusPill>}
                    {r.promises_total_30d >= 3 && <StatusPill kind={completionKind}><CheckCircle2 className="w-3 h-3" />{completionPct}% closed</StatusPill>}
                    {r.high_priority_unvisited > 0 && <StatusPill kind="warning"><Flame className="w-3 h-3" />{r.high_priority_unvisited} priority unvisited</StatusPill>}
                    {sentTrendIcon && <StatusPill kind={sentKind}>{sentTrendIcon}{r.sentiment_trend}</StatusPill>}
                  </div>
                  {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                </div>
                {(r.flags || []).length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {r.flags.map((f) => (
                      <span key={f.key} className={f.severity === "danger" ? "pill pill-danger" : "pill pill-warning"} data-testid={`flag-${r.tm_id}-${f.key}`}>
                        <AlertTriangle className="w-3 h-3" />{f.label}
                      </span>
                    ))}
                  </div>
                )}
              </button>

              {isOpen && (
                <div className="border-t p-4 space-y-3" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}>
                  {(r.insights || []).length > 0 && (
                    <div>
                      <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Behavioral insights</div>
                      <div className="space-y-1.5">
                        {r.insights.map((ins, i) => (
                          <div key={i} className="text-sm flex items-start gap-2" data-testid={`insight-${r.tm_id}-${i}`}>
                            <span className={`mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0`} style={{ background: ins.kind === "positive" ? "var(--status-success)" : "var(--status-danger)" }} />
                            <div>
                              <span className="font-medium" style={{ color: ins.kind === "positive" ? "var(--status-success)" : "var(--status-danger)" }}>{ins.label}</span>
                              <span style={{ color: "var(--text-secondary)" }}> — {ins.detail}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {(r.high_priority_unvisited_doctors || []).length > 0 && (
                    <div>
                      <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>High-priority doctors not visited (last 30d)</div>
                      <div className="space-y-1">
                        {r.high_priority_unvisited_doctors.map((d) => (
                          <Link key={d.id} to={`/doctors/${d.id}`} className="flex items-center justify-between text-sm hover:underline">
                            <span style={{ color: "var(--text-primary)" }}>{d.doctor_name} <span style={{ color: "var(--text-muted)" }}>· {d.segment}</span></span>
                            <span className="pill pill-danger">priority {d.score}</span>
                          </Link>
                        ))}
                      </div>
                    </div>
                  )}
                  {(r.flags || []).length === 0 && (r.insights || []).length === 0 && (
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>No flags. This TM is performing within expected ranges.</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ManagerView({ data, performance }) {
  if (!data) return null;
  const sentTotal = Object.values(data.sentiment_distribution || {}).reduce((a, b) => a + b, 0) || 1;
  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Visits this week" value={data.stats.visits_week} icon={Activity} kind="info" testId="stat-visits-week" />
        <StatCard label="Visits this month" value={data.stats.visits_month} icon={CalendarClock} kind="info" testId="stat-visits-month" />
        <StatCard label="Doctors" value={data.stats.doctors} icon={Users} kind="muted" testId="stat-doctors" />
        <StatCard label="Overdue promises" value={data.stats.overdue_promises} icon={AlertTriangle} kind="danger" testId="stat-overdue" />
      </div>

      <div className="grid lg:grid-cols-3 gap-6 mb-6">
        <div className="lg:col-span-2 rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Market pulse</div>
              <h2 className="font-display text-xl font-medium" style={{ color: "var(--brand-primary)" }}>What the field is telling us</h2>
            </div>
          </div>
          <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }} data-testid="market-pulse">{data.market_pulse}</p>

          <div className="grid sm:grid-cols-2 gap-6 mt-5">
            <div>
              <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Top barriers (30d)</div>
              <div className="space-y-1.5">
                {(data.top_barriers || []).slice(0, 6).map((b) => (
                  <div key={b.name} className="flex items-center justify-between text-sm">
                    <span className="truncate pr-2" style={{ color: "var(--text-primary)" }}>{b.name}</span>
                    <span className="pill pill-danger">{b.count}</span>
                  </div>
                ))}
                {(data.top_barriers || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>No data yet</div>}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Top topics (30d)</div>
              <div className="space-y-1.5">
                {(data.top_topics || []).slice(0, 6).map((t) => (
                  <div key={t.name} className="flex items-center justify-between text-sm">
                    <span className="truncate pr-2" style={{ color: "var(--text-primary)" }}>{t.name}</span>
                    <span className="pill pill-info">{t.count}</span>
                  </div>
                ))}
                {(data.top_topics || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>No data yet</div>}
              </div>
            </div>
          </div>
        </div>

        <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="text-xs uppercase tracking-widest mb-3" style={{ color: "var(--text-muted)" }}>Sentiment mix (30d)</div>
          <div className="space-y-2">
            {["Very Positive", "Positive", "Neutral", "Negative", "Very Negative"].map((s) => {
              const v = data.sentiment_distribution?.[s] || 0;
              const pct = Math.round((v / sentTotal) * 100);
              return (
                <div key={s}>
                  <div className="flex justify-between text-xs mb-1">
                    <span style={{ color: "var(--text-secondary)" }}>{s}</span>
                    <span style={{ color: "var(--text-muted)" }}>{v} · {pct}%</span>
                  </div>
                  <div className="h-2 rounded-full" style={{ background: "var(--bg-muted)" }}>
                    <div className="h-2 rounded-full" style={{ width: `${pct}%`, background: sentimentColor(s) }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <TMPerformanceTable performance={performance} />

      <div className="grid lg:grid-cols-2 gap-6 mb-6 mt-6">
        <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Under-visited high-segment doctors</h3>
          <div className="space-y-2">
            {(data.under_visited_high_segment || []).map((d) => (
              <Link key={d.id} to={`/doctors/${d.id}`} className="flex items-center justify-between text-sm hover:bg-[var(--bg-paper)] rounded px-2 py-1.5">
                <div>
                  <div className="font-medium" style={{ color: "var(--text-primary)" }}>{d.doctor_name}</div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>{d.segment} · {d.city}</div>
                </div>
                <StatusPill kind={cadenceKind(d.cadence_status)}>{d.days_since_last_visit ?? "—"}d ago</StatusPill>
              </Link>
            ))}
            {(data.under_visited_high_segment || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>All high-segment doctors are well covered.</div>}
          </div>
        </div>

        <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Opportunity state mix (30d)</h3>
          <div className="space-y-2">
            {Object.entries(data.opportunity_distribution || {}).map(([k, v]) => {
              const total = Object.values(data.opportunity_distribution || {}).reduce((a, b) => a + b, 0) || 1;
              const pct = Math.round((v / total) * 100);
              const color = k === "Advancing" ? "var(--status-success)" : k === "Stuck" ? "var(--status-warning)" : k === "Blocked" ? "var(--status-danger)" : "var(--status-info)";
              return (
                <div key={k}>
                  <div className="flex justify-between text-xs mb-1">
                    <span style={{ color: "var(--text-secondary)" }}>{k}</span>
                    <span style={{ color: "var(--text-muted)" }}>{v} · {pct}%</span>
                  </div>
                  <div className="h-2 rounded-full" style={{ background: "var(--bg-muted)" }}>
                    <div className="h-2 rounded-full" style={{ width: `${pct}%`, background: color }} />
                  </div>
                </div>
              );
            })}
            {Object.keys(data.opportunity_distribution || {}).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>No data yet.</div>}
          </div>
        </div>
      </div>
    </>
  );
}

function sentimentColor(s) {
  return {
    "Very Positive": "var(--status-success)",
    "Positive": "#5C8A6F",
    "Neutral": "var(--status-info)",
    "Negative": "#C9846B",
    "Very Negative": "var(--status-danger)",
  }[s] || "var(--bg-muted)";
}

function TMView({ data }) {
  if (!data) return null;
  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Visits this week" value={data.stats.visits_this_week} icon={Activity} kind="info" testId="stat-visits-week" />
        <StatCard label="Open promises" value={data.stats.open_promises} icon={ClipboardList} kind="muted" testId="stat-open-promises" />
        <StatCard label="Overdue" value={data.stats.overdue_promises} icon={AlertTriangle} kind="danger" testId="stat-overdue" />
        <StatCard label="Due today" value={data.stats.due_today} icon={CalendarClock} kind="warning" testId="stat-due-today" />
      </div>

      <div className="flex items-baseline justify-between mb-4">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Today's intelligence</div>
          <h2 className="font-display text-2xl font-medium" style={{ color: "var(--brand-primary)" }}>Doctors who need you next</h2>
        </div>
        <Link to="/doctors" className="text-sm underline" style={{ color: "var(--text-secondary)" }} data-testid="see-all-doctors-link">
          See all →
        </Link>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8" data-testid="priority-doctors-grid">
        {(data.top_priorities || []).map((d, idx) => <PriorityCard key={d.id} d={d} idx={idx} />)}
      </div>

      {(data.overdue_doctors || []).length > 0 && (
        <div className="rounded-md border p-6 mb-8" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <h3 className="font-display text-lg font-medium mb-4 flex items-center gap-2" style={{ color: "var(--brand-primary)" }}>
            <AlertTriangle className="w-5 h-5" style={{ color: "var(--status-danger)" }} /> Promises you owe
          </h3>
          <div className="grid sm:grid-cols-2 gap-3">
            {data.overdue_doctors.map((d) => (
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

export default function Dashboard() {
  const { user } = useAuth();
  const [tmData, setTmData] = useState(null);
  const [mgrData, setMgrData] = useState(null);
  const [perfData, setPerfData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const tm = await api.get("/dashboard/tm");
        setTmData(tm.data);
        if (user.role === "Manager" || user.role === "Admin") {
          const [mgr, perf] = await Promise.all([
            api.get("/dashboard/manager"),
            api.get("/dashboard/manager/performance"),
          ]);
          setMgrData(mgr.data);
          setPerfData(perf.data);
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [user.role]);

  return (
    <div data-testid="dashboard-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{user.role} dashboard</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          Hello, <span className="font-medium">{user.full_name?.split(" ")[0]}</span>.
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          {user.role === "TM" ? "Here's who needs your attention today." : "Here's how the field is performing."}
        </p>
      </div>

      {loading && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>}

      {(user.role === "Manager" || user.role === "Admin") && <ManagerView data={mgrData} performance={perfData} />}
      {user.role === "TM" && <TMView data={tmData} />}
    </div>
  );
}
