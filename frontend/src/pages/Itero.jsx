import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { StatusPill } from "../components/StatusPill";
import { ScanLine, AlertTriangle, Activity, Flame, ArrowRight, X } from "lucide-react";

function FunnelRow({ label, value, max, color, testId }) {
  const pct = max ? Math.round((value / max) * 100) : 0;
  return (
    <div data-testid={testId}>
      <div className="flex justify-between text-sm mb-1">
        <span style={{ color: "var(--text-primary)" }}>{label}</span>
        <span className="font-mono" style={{ color: "var(--text-muted)" }}>{value}</span>
      </div>
      <div className="h-2.5 rounded-full" style={{ background: "var(--bg-muted)" }}>
        <div className="h-2.5 rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

export default function Itero() {
  const { user } = useAuth();
  const isManager = user.role === "Manager" || user.role === "Admin";
  const [data, setData] = useState(null);

  useEffect(() => {
    const url = isManager ? "/dashboard/manager/itero" : "/dashboard/tm/itero";
    api.get(url).then((r) => setData(r.data));
  }, [isManager]);

  return (
    <div data-testid="itero-page">
      <div className="mb-6 flex items-start gap-3">
        <div className="w-12 h-12 rounded-md flex items-center justify-center" style={{ background: "var(--brand-accent)", color: "white" }}>
          <ScanLine className="w-6 h-6" />
        </div>
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{isManager ? "iTero (manager view)" : "iTero (TM view)"}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Scanner <span className="font-medium">demo & engagement.</span>
          </h1>
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>This page reads ONLY iTero-tagged data. No growth-program data here.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/itero/demos" data-testid="itero-demos-link">
            <button className="px-4 py-2 rounded-md text-sm font-medium border" style={{ borderColor: "var(--brand-primary)", color: "var(--brand-primary)", background: "transparent" }}>
              Demos overview →
            </button>
          </Link>
          <Link to="/itero/pipeline" data-testid="itero-pipeline-link">
            <button className="px-4 py-2 rounded-md text-sm font-medium" style={{ background: "var(--brand-secondary)", color: "white" }}>
              Open pipeline →
            </button>
          </Link>
        </div>
      </div>

      {!data && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>}
      {data && <BookedDemosBlock />}
      {data && (isManager ? <ManagerItero data={data} /> : <TMItero data={data} />)}
    </div>
  );
}

function BookedDemosBlock() {
  const [demos, setDemos] = React.useState(null);
  React.useEffect(() => {
    api.get("/itero/demos").then((r) => setDemos(r.data)).catch(() => setDemos({ booked: [], counts: { booked: 0 } }));
  }, []);
  const fmt = (s) => { try { return new Date(s).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }); } catch { return s; } };
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
  if (!demos) return null;
  const list = demos.booked || [];
  return (
    <div
      data-testid="itero-booked-demos-section"
      className="rounded-md border p-5 mb-6"
      style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
    >
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Demos · Booked</div>
          <h3 className="font-display text-lg font-medium" style={{ color: "var(--brand-primary)" }}>
            {list.length === 0 ? "No demos booked yet" : `${list.length} demo${list.length === 1 ? "" : "s"} on the calendar`}
          </h3>
        </div>
        <Link to="/itero/demos" data-testid="itero-booked-see-all" className="text-sm hover:underline" style={{ color: "var(--brand-secondary)" }}>
          See all →
        </Link>
      </div>
      {list.length > 0 && (
        <div className="space-y-1.5">
          {list.slice(0, 8).map((r) => {
            const days = (() => {
              try { const d = new Date(r.booked_date); d.setHours(0, 0, 0, 0); const t = new Date(); t.setHours(0, 0, 0, 0); return Math.round((d - t) / 86400000); } catch { return null; }
            })();
            const overdue = days != null && days < 0;
            return (
              <Link
                key={r.doctor_id}
                to={`/doctors/${r.doctor_id}`}
                data-testid={`itero-booked-row-${r.doctor_id}`}
                className="flex items-center justify-between gap-2 rounded border px-3 py-2 text-sm transition-colors hover:border-[var(--brand-primary)]"
                style={{ borderColor: overdue ? "var(--status-danger)" : "var(--border-default)", background: "var(--bg-paper)" }}
              >
                <div className="min-w-0">
                  <div className="font-medium truncate" style={{ color: "var(--brand-primary)" }}>{r.doctor_name}</div>
                  <div className="text-xs truncate" style={{ color: "var(--text-secondary)" }}>
                    {[r.clinic_name, r.city].filter(Boolean).join(" · ") || "—"}
                    {r.tm_name && <span className="ml-2" style={{ color: "var(--text-muted)" }}>· TM: {r.tm_name}</span>}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-sm font-mono" style={{ color: overdue ? "var(--status-danger)" : "var(--text-primary)" }}>{fmt(r.booked_date)}</div>
                  <div className="text-[10px]" style={{ color: overdue ? "var(--status-danger)" : "var(--text-muted)" }}>{rel(r.booked_date)}</div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ManagerItero({ data }) {
  const f = data.demo_funnel;
  const max = Math.max(f.discussed, f.booked, f.completed, 1);
  return (
    <>
      {(data.drop_offs || []).length > 0 && (
        <div className="rounded-md border p-4 mb-6" style={{ background: "var(--status-danger-bg)", borderColor: "var(--status-danger)" }} data-testid="itero-alerts">
          <div className="flex items-center gap-2 mb-2 text-xs uppercase tracking-widest" style={{ color: "var(--status-danger)" }}>
            <AlertTriangle className="w-4 h-4" /> Demo drop-offs
          </div>
          <div className="flex flex-wrap gap-2">
            {data.drop_offs.map((d) => (
              <span key={d.key} className="pill pill-danger" data-testid={`itero-alert-${d.key}`}>{d.label} — {d.detail}</span>
            ))}
          </div>
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6 mb-6">
        <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="itero-demo-funnel">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Demo funnel</div>
              <h3 className="font-display text-lg font-medium" style={{ color: "var(--brand-primary)" }}>Discussed → booked → completed</h3>
            </div>
            <div className="text-xs text-right" style={{ color: "var(--text-muted)" }}>
              booking {Math.round(f.booking_rate * 100)}%<br />completion {Math.round(f.completion_rate * 100)}%
            </div>
          </div>
          <div className="space-y-3">
            <FunnelRow label="Discussed" value={f.discussed} max={max} color="var(--status-info)" testId="itero-funnel-discussed" />
            <FunnelRow label="Booked" value={f.booked} max={max} color="var(--brand-accent)" testId="itero-funnel-booked" />
            <FunnelRow label="Completed" value={f.completed} max={max} color="var(--status-success)" testId="itero-funnel-completed" />
          </div>
          {f.pending > 0 && (
            <div className="mt-3 text-xs px-3 py-2 rounded" style={{ background: "var(--status-warning-bg)", color: "var(--status-warning)" }}>
              {f.pending} demo{f.pending > 1 ? "s" : ""} booked but not completed
            </div>
          )}
        </div>

        <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="itero-engagement">
          <div className="text-xs uppercase tracking-widest mb-3" style={{ color: "var(--text-muted)" }}>Scanner interest</div>
          <div className="space-y-2">
            {["High", "Medium", "Low", "None"].map((k) => {
              const v = data.scanner_interest[k] || 0;
              const total = Object.values(data.scanner_interest).reduce((a, b) => a + b, 0) || 1;
              const pct = Math.round((v / total) * 100);
              const color = k === "High" ? "var(--status-success)" : k === "Medium" ? "var(--status-warning)" : k === "Low" ? "var(--status-danger)" : "var(--bg-muted)";
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
          </div>
          {data.top_concerns?.length > 0 && (
            <div className="mt-4">
              <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Top scanner concerns</div>
              <div className="flex flex-wrap gap-1.5">{data.top_concerns.map((c) => <span key={c.name} className="pill pill-warning">{c.name} · {c.count}</span>)}</div>
            </div>
          )}
        </div>
      </div>

      <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="itero-by-tm">
        <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>TM performance — demos</h3>
        {(data.by_tm || []).length === 0 ? (
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>No demo activity yet.</div>
        ) : (
          <div className="space-y-2">
            {data.by_tm.map((b) => (
              <div key={b.tm_id} className="flex items-center justify-between text-sm" data-testid={`itero-by-tm-${b.tm_id}`}>
                <div className="font-medium" style={{ color: "var(--text-primary)" }}>{b.tm_name}</div>
                <div className="flex gap-2">
                  <StatusPill kind="info">discussed {b.demos_discussed}</StatusPill>
                  <StatusPill kind="muted">booked {b.demos_booked}</StatusPill>
                  <StatusPill kind="success">completed {b.demos_completed}</StatusPill>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function TMItero({ data }) {
  const [scope, setScope] = useState("week"); // 'week' | 'all'
  const [breakdown, setBreakdown] = useState(null);
  const [openBucket, setOpenBucket] = useState(null); // 'discussed' | 'booked' | 'completed' | null

  useEffect(() => {
    setBreakdown(null);
    api.get("/itero/demo-breakdown", { params: { scope } })
      .then((r) => setBreakdown(r.data))
      .catch(() => setBreakdown({ counts: { discussed: 0, booked: 0, completed: 0 }, discussed: [], booked: [], completed: [] }));
  }, [scope]);

  const counts = breakdown?.counts || { discussed: 0, booked: 0, completed: 0 };

  return (
    <>
      {/* Week / All-time toggle */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
            Demo funnel
          </div>
          <h3 className="font-display text-lg font-medium" style={{ color: "var(--brand-primary)" }}>
            {scope === "week" ? "This week" : "All time"} · click a tile to see doctors
          </h3>
        </div>
        <div
          className="inline-flex rounded-md border overflow-hidden text-xs"
          style={{ borderColor: "var(--border-default)" }}
          data-testid="itero-scope-toggle"
        >
          <button
            type="button"
            onClick={() => setScope("week")}
            data-testid="itero-scope-week"
            className="px-3 py-1.5 font-medium transition-colors"
            style={{
              background: scope === "week" ? "var(--brand-primary)" : "transparent",
              color: scope === "week" ? "white" : "var(--text-secondary)",
            }}
          >
            This week
          </button>
          <button
            type="button"
            onClick={() => setScope("all")}
            data-testid="itero-scope-all"
            className="px-3 py-1.5 font-medium transition-colors"
            style={{
              background: scope === "all" ? "var(--brand-primary)" : "transparent",
              color: scope === "all" ? "white" : "var(--text-secondary)",
            }}
          >
            All time
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-6">
        <ClickableStat
          label="Discussed"
          value={counts.discussed}
          testId="tm-itero-discussed"
          onClick={() => counts.discussed > 0 && setOpenBucket("discussed")}
        />
        <ClickableStat
          label="Booked"
          value={counts.booked}
          testId="tm-itero-booked"
          onClick={() => counts.booked > 0 && setOpenBucket("booked")}
        />
        <ClickableStat
          label="Completed"
          value={counts.completed}
          kind="success"
          testId="tm-itero-completed"
          onClick={() => counts.completed > 0 && setOpenBucket("completed")}
        />
      </div>
      <p className="text-[11px] -mt-4 mb-6" style={{ color: "var(--text-muted)" }}>
        Counts every demo <strong>event</strong> — a doctor with two demos in the window counts twice.
        {scope === "week" && " Resets every Monday."}
      </p>

      {openBucket && (
        <BreakdownDialog
          title={
            openBucket === "discussed" ? "Demos discussed"
              : openBucket === "booked" ? "Demos booked"
                : "Demos completed"
          }
          scope={scope}
          rows={breakdown?.[openBucket] || []}
          bucket={openBucket}
          onClose={() => setOpenBucket(null)}
        />
      )}

      <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
        <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Demo follow-ups</h3>
        <div className="space-y-2">
          {(data.follow_ups || []).map((f) => (
            <Link key={f.id} to={`/doctors/${f.id}`} className="block rounded-md border p-3 card-lift" data-testid={`tm-itero-followup-${f.id}`} style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div>
                  <div className="font-medium" style={{ color: "var(--brand-primary)" }}>{f.doctor_name}</div>
                  <div className="text-sm" style={{ color: "var(--status-warning)" }}>{f.issue}</div>
                  <div className="text-xs flex items-center gap-1 mt-1" style={{ color: "var(--text-secondary)" }}><ArrowRight className="w-3 h-3" />{f.suggested_action}</div>
                </div>
                <StatusPill kind="muted"><Flame className="w-3 h-3" />priority {f.score}</StatusPill>
              </div>
            </Link>
          ))}
          {(data.follow_ups || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>No demo follow-ups pending — solid.</div>}
        </div>
      </div>

      <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
        <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>High scanner interest</h3>
        <div className="space-y-1">
          {(data.high_interest_doctors || []).map((d) => (
            <Link key={d.id} to={`/doctors/${d.id}`} className="block text-sm hover:underline" style={{ color: "var(--text-primary)" }}>
              {d.doctor_name} <span className="text-xs" style={{ color: "var(--text-muted)" }}>· {d.segment}</span>
            </Link>
          ))}
          {(data.high_interest_doctors || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>No high-interest doctors yet — start with a demo discussion.</div>}
        </div>
      </div>
    </>
  );
}

function ClickableStat({ label, value, kind = "muted", testId, onClick }) {
  const fg = kind === "success" ? "var(--status-success)" : "var(--brand-primary)";
  const disabled = !value || value === 0;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className="text-left rounded-md border p-4 transition-all enabled:hover:border-[var(--brand-primary)] enabled:hover:shadow-sm disabled:cursor-default"
      style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
    >
      <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="font-display text-3xl font-medium mt-1" style={{ color: fg }}>{value ?? 0}</div>
      {!disabled && (
        <div className="text-[10px] uppercase tracking-widest mt-1" style={{ color: "var(--text-muted)" }}>
          See doctors →
        </div>
      )}
    </button>
  );
}

function BreakdownDialog({ title, scope, rows, bucket, onClose }) {
  const fmt = (iso) => {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    } catch {
      return iso;
    }
  };
  // Group events by doctor so the same doctor appears once with all their event dates
  const byDoctor = new Map();
  rows.forEach((r) => {
    if (!byDoctor.has(r.doctor_id)) {
      byDoctor.set(r.doctor_id, {
        doctor_id: r.doctor_id,
        doctor_name: r.doctor_name,
        clinic_name: r.clinic_name,
        city: r.city,
        segment: r.segment,
        itero_stage: r.itero_stage,
        events: [],
      });
    }
    byDoctor.get(r.doctor_id).events.push(r);
  });
  const groups = Array.from(byDoctor.values());

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(39,64,53,0.55)" }}
      onClick={onClose}
      data-testid="itero-breakdown-dialog"
    >
      <div
        className="w-full max-w-xl rounded-lg border shadow-xl max-h-[85vh] flex flex-col"
        style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between p-5 border-b" style={{ borderColor: "var(--border-default)" }}>
          <div>
            <div className="text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
              {scope === "week" ? "This week" : "All time"} · {rows.length} event{rows.length === 1 ? "" : "s"}
            </div>
            <h3 className="font-display text-xl font-medium" style={{ color: "var(--brand-primary)" }}>{title}</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            data-testid="itero-breakdown-close"
            className="p-1 rounded hover:bg-[var(--bg-paper)]"
            aria-label="Close"
          >
            <X className="w-4 h-4" style={{ color: "var(--text-secondary)" }} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {groups.length === 0 && (
            <div className="text-sm text-center py-6" style={{ color: "var(--text-muted)" }}>
              No {bucket} demos in this window.
            </div>
          )}
          {groups.map((g) => (
            <Link
              key={g.doctor_id}
              to={`/doctors/${g.doctor_id}`}
              onClick={onClose}
              data-testid={`itero-breakdown-row-${g.doctor_id}`}
              className="block rounded-md border p-3 transition-colors hover:border-[var(--brand-primary)]"
              style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}
            >
              <div className="flex items-start justify-between gap-2 flex-wrap">
                <div className="min-w-0">
                  <div className="font-medium" style={{ color: "var(--brand-primary)" }}>{g.doctor_name}</div>
                  <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {[g.clinic_name, g.city, g.segment].filter(Boolean).join(" · ") || "—"}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-0.5 shrink-0">
                  {g.events.length > 1 && (
                    <StatusPill kind="info">{g.events.length} events</StatusPill>
                  )}
                  {g.itero_stage && (
                    <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
                      {g.itero_stage}
                    </span>
                  )}
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {g.events.slice(0, 6).map((ev, idx) => (
                  <span
                    key={idx}
                    className="text-[11px] px-2 py-0.5 rounded border"
                    style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
                  >
                    {fmt(ev.event_date)}
                    {ev.source === "meeting" && " · via meeting"}
                    {ev.interest_level && ` · interest: ${ev.interest_level}`}
                  </span>
                ))}
                {g.events.length > 6 && (
                  <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                    +{g.events.length - 6} more
                  </span>
                )}
              </div>
            </Link>
          ))}
        </div>

        <div className="p-4 border-t text-xs" style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}>
          Click any row to open that doctor's profile.
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, kind = "muted", testId }) {
  const fg = kind === "success" ? "var(--status-success)" : "var(--brand-primary)";
  return (
    <div className="rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={testId}>
      <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="font-display text-3xl font-medium mt-1" style={{ color: fg }}>{value ?? 0}</div>
    </div>
  );
}
