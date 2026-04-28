import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Link } from "react-router-dom";
import { StatusPill } from "../components/StatusPill";
import { AlertTriangle, ChevronDown, ChevronRight, Flame, Target, CheckCircle2, TrendingDown, TrendingUp, Sparkles } from "lucide-react";

export default function TeamPerformance() {
  const [perf, setPerf] = useState(null);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    api.get("/dashboard/manager/performance").then((r) => setPerf(r.data));
  }, []);

  const rows = perf?.rows || [];

  return (
    <div data-testid="team-performance-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Team performance</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          How each TM is <span className="font-medium">executing.</span>
        </h1>
      </div>

      {!perf && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>}

      <div className="space-y-3">
        {rows.map((r) => {
          const isOpen = expanded === r.tm_id;
          const targetRatio = r.visits_vs_target;
          const ratioKind = targetRatio >= 0.9 ? "success" : targetRatio >= 0.6 ? "warning" : "danger";
          const completionPct = Math.round(r.completion_rate * 100);
          const completionKind = r.promises_total_30d < 3 ? "muted" : completionPct >= 70 ? "success" : completionPct >= 40 ? "warning" : "danger";
          const eqsKind = r.execution_quality_label === "High" ? "success" : r.execution_quality_label === "Medium" ? "warning" : "danger";
          const sentTrendIcon = r.sentiment_trend === "improving" ? <TrendingUp className="w-3 h-3" /> : r.sentiment_trend === "declining" ? <TrendingDown className="w-3 h-3" /> : null;
          return (
            <div key={r.tm_id} className="rounded-md border" style={{ borderColor: "var(--border-default)" }} data-testid={`tm-perf-row-${r.tm_id}`}>
              <button
                onClick={() => setExpanded(isOpen ? null : r.tm_id)}
                className="w-full text-left p-4 hover:bg-[var(--bg-paper)] rounded-md transition-colors"
                data-testid={`expand-tm-${r.tm_id}`}
              >
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="flex-1 min-w-0">
                    <div className="font-display text-base font-medium" style={{ color: "var(--text-primary)" }}>{r.tm_name}</div>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>{r.doctors} doctors · {r.tm_email}</div>
                  </div>
                  <StatusPill kind={eqsKind} testId={`eqs-${r.tm_id}`}>
                    EQS {r.execution_quality_score} · {r.execution_quality_label}
                  </StatusPill>
                  {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <StatusPill kind={ratioKind}><Target className="w-3 h-3" />{r.visits_month}/{r.visits_target_month} visits</StatusPill>
                  <StatusPill kind="muted">{r.avg_visits_per_day}/day</StatusPill>
                  {r.overdue_count > 0 && <StatusPill kind="danger"><AlertTriangle className="w-3 h-3" />{r.overdue_count} overdue</StatusPill>}
                  {r.promises_total_30d >= 3 && <StatusPill kind={completionKind}><CheckCircle2 className="w-3 h-3" />{completionPct}% closed</StatusPill>}
                  {r.high_priority_visited_pct !== null && <StatusPill kind={r.high_priority_visited_pct >= 0.7 ? "success" : "warning"}><Flame className="w-3 h-3" />{Math.round(r.high_priority_visited_pct * 100)}% priority covered</StatusPill>}
                  {(r.demos_booked > 0 || r.demos_completed > 0) && <StatusPill kind="info">demos {r.demos_completed}/{r.demos_booked}</StatusPill>}
                  {(r.proposals_sent > 0) && <StatusPill kind={r.proposals_unfollowed > 0 ? "warning" : "info"}>props {r.proposals_sent} ({r.proposals_unfollowed} unfollowed)</StatusPill>}
                  {sentTrendIcon && <StatusPill kind={r.sentiment_trend === "improving" ? "success" : "danger"}>{sentTrendIcon}{r.sentiment_trend}</StatusPill>}
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
                <div className="border-t p-4 space-y-4" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}>
                  {r.coaching && (
                    <div className="grid md:grid-cols-3 gap-4" data-testid={`coaching-${r.tm_id}`}>
                      <CoachBlock title="Strengths" items={r.coaching.strengths} kind="positive" />
                      <CoachBlock title="Weaknesses" items={r.coaching.weaknesses} kind="negative" />
                      <CoachBlock title="Coaching suggestions" items={r.coaching.suggestions} kind="info" icon={<Sparkles className="w-3 h-3" />} />
                    </div>
                  )}
                  {(r.high_priority_unvisited_doctors || []).length > 0 && (
                    <div>
                      <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>High-priority doctors not visited (30d)</div>
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
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CoachBlock({ title, items, kind, icon }) {
  const color = kind === "positive" ? "var(--status-success)" : kind === "negative" ? "var(--status-danger)" : "var(--status-info)";
  return (
    <div>
      <div className="text-xs uppercase tracking-widest mb-2 flex items-center gap-1" style={{ color }}>
        {icon} {title}
      </div>
      {(items || []).length === 0 ? (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>—</div>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {items.map((it, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className="mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: color }} />
              <span style={{ color: "var(--text-primary)" }}>{it}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
