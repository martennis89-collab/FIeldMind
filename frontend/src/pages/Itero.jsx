import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { StatusPill } from "../components/StatusPill";
import { ScanLine, AlertTriangle, Activity, Flame, ArrowRight } from "lucide-react";

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
      </div>

      {!data && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>}
      {data && (isManager ? <ManagerItero data={data} /> : <TMItero data={data} />)}
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
  const f = data.demo_funnel;
  return (
    <>
      <div className="grid grid-cols-3 gap-3 mb-6">
        <Stat label="Discussed" value={f.discussed} testId="tm-itero-discussed" />
        <Stat label="Booked" value={f.booked} testId="tm-itero-booked" />
        <Stat label="Completed" value={f.completed} kind="success" testId="tm-itero-completed" />
      </div>

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

function Stat({ label, value, kind = "muted", testId }) {
  const fg = kind === "success" ? "var(--status-success)" : "var(--brand-primary)";
  return (
    <div className="rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={testId}>
      <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="font-display text-3xl font-medium mt-1" style={{ color: fg }}>{value ?? 0}</div>
    </div>
  );
}
