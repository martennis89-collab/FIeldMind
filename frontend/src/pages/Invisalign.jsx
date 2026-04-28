import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { StatusPill } from "../components/StatusPill";
import { Smile, Sparkles, AlertTriangle, ArrowRight, Flame } from "lucide-react";

function PctBar({ value, total, color = "var(--status-info)" }) {
  const pct = total ? Math.round((value / total) * 100) : 0;
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span style={{ color: "var(--text-secondary)" }}>{value} of {total}</span>
        <span style={{ color: "var(--text-muted)" }}>{pct}%</span>
      </div>
      <div className="h-2 rounded-full" style={{ background: "var(--bg-muted)" }}>
        <div className="h-2 rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

export default function Invisalign() {
  const { user } = useAuth();
  const isManager = user.role === "Manager" || user.role === "Admin";
  const [data, setData] = useState(null);

  useEffect(() => {
    const url = isManager ? "/dashboard/manager/invisalign" : "/dashboard/tm/invisalign";
    api.get(url).then((r) => setData(r.data));
  }, [isManager]);

  return (
    <div data-testid="invisalign-page">
      <div className="mb-6 flex items-start gap-3">
        <div className="w-12 h-12 rounded-md flex items-center justify-center" style={{ background: "var(--brand-secondary)", color: "white" }}>
          <Smile className="w-6 h-6" />
        </div>
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{isManager ? "Invisalign (manager view)" : "Invisalign (TM view)"}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Aligner growth & <span className="font-medium">confidence.</span>
          </h1>
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>This page reads ONLY Invisalign-tagged data. No demo data here.</p>
        </div>
      </div>

      {!data && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>}
      {data && (isManager ? <ManagerInvisalign data={data} /> : <TMInvisalign data={data} />)}
    </div>
  );
}

function ManagerInvisalign({ data }) {
  const total = data.totals.doctors;
  return (
    <>
      <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="invisalign-coverage">
        <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Growth program awareness</h3>
        <div className="grid sm:grid-cols-3 gap-5">
          <div>
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Growth program explained</div>
            <PctBar value={Math.round(data.coverage.growth_program_pct * total)} total={total} />
          </div>
          <div>
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Certification interest</div>
            <PctBar value={Math.round(data.coverage.certification_pct * total)} total={total} color="var(--status-success)" />
          </div>
          <div>
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>P2P / TPS / Training need</div>
            <PctBar value={Math.round((data.coverage.p2p_pct + data.coverage.tps_pct + data.coverage.training_pct) * total / 3)} total={total} color="var(--brand-accent)" />
          </div>
        </div>
        {(data.coverage.no_growth || []).length > 0 && (
          <div className="mt-4">
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Doctors lacking growth program explanation</div>
            <div className="flex flex-wrap gap-1.5">
              {data.coverage.no_growth.slice(0, 12).map((d) => (
                <Link key={d.id} to={`/doctors/${d.id}`} className="pill pill-warning hover:opacity-80">{d.doctor_name}</Link>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mb-6">
        <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="invisalign-confidence">
          <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Confidence gaps</h3>
          {[
            { title: "Clinical confidence", buckets: data.confidence.clinical, list: data.confidence.low_clinical_doctors, kind: "low_clinical" },
            { title: "Business confidence", buckets: data.confidence.business, list: data.confidence.low_business_doctors, kind: "low_business" },
          ].map((sec) => {
            const t = Object.values(sec.buckets).reduce((a, b) => a + b, 0) || 1;
            return (
              <div key={sec.title} className="mb-5">
                <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>{sec.title}</div>
                <div className="space-y-1.5">
                  {["High", "Medium", "Low", "Unknown"].map((k) => {
                    const v = sec.buckets[k] || 0;
                    const pct = Math.round((v / t) * 100);
                    const color = k === "High" ? "var(--status-success)" : k === "Medium" ? "var(--status-warning)" : k === "Low" ? "var(--status-danger)" : "var(--bg-muted)";
                    return (
                      <div key={k}>
                        <div className="flex justify-between text-xs mb-0.5">
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
                {sec.list.length > 0 && (
                  <div className="mt-2 text-xs" data-testid={`${sec.kind}-list`} style={{ color: "var(--text-muted)" }}>
                    Low: {sec.list.slice(0, 5).map((d) => d.doctor_name).join(", ")}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="invisalign-by-segment">
          <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Barriers by segment</h3>
          <div className="space-y-4">
            {Object.entries(data.barriers_by_segment || {}).map(([seg, bs]) => (
              <div key={seg}>
                <div className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>{seg}</div>
                <div className="flex flex-wrap gap-1.5">
                  {bs.slice(0, 4).map((b) => <span key={b.name} className="pill pill-warning">{b.name} · {b.count}</span>)}
                  {bs.length === 0 && <span className="text-xs" style={{ color: "var(--text-muted)" }}>None</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="invisalign-growth-opps">
        <h3 className="font-display text-lg font-medium mb-4 flex items-center gap-2" style={{ color: "var(--brand-primary)" }}>
          <Sparkles className="w-5 h-5" style={{ color: "var(--status-success)" }} /> Growth opportunities
        </h3>
        <div className="space-y-2">
          {(data.growth_opportunities || []).map((d) => (
            <Link key={d.id} to={`/doctors/${d.id}`} className="block rounded-md border p-3 card-lift" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div>
                  <div className="font-medium" style={{ color: "var(--brand-primary)" }}>{d.doctor_name}</div>
                  <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{d.segment}</div>
                  <div className="text-sm mt-1" style={{ color: "var(--status-success)" }}>{d.reason}</div>
                </div>
                <StatusPill kind="muted"><Flame className="w-3 h-3" />priority {d.score}</StatusPill>
              </div>
            </Link>
          ))}
          {(data.growth_opportunities || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>No active growth opportunities yet.</div>}
        </div>
      </div>
    </>
  );
}

function TMInvisalign({ data }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-3 mb-6">
        <div className="rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Doctors with growth program explained</div>
          <div className="font-display text-3xl font-medium mt-1" style={{ color: "var(--brand-primary)" }}>{data.growth_program_explained_count}<span className="text-base" style={{ color: "var(--text-muted)" }}> / {data.totals.doctors}</span></div>
        </div>
        <div className="rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Confidence-barrier doctors</div>
          <div className="font-display text-3xl font-medium mt-1" style={{ color: "var(--status-danger)" }}>{(data.confidence_barriers || []).length}</div>
        </div>
      </div>

      <Section title="Certification interest" data={data.certification_interest_doctors} kind="success" testId="tm-cert-interest" />
      <Section title="TPS / P2P / Training needs" data={data.needs_tps_p2p_training} kind="info" testId="tm-tps-needs" />
      <Section title="Confidence barriers" data={data.confidence_barriers} kind="danger" testId="tm-conf-barriers" />
    </>
  );
}

function Section({ title, data, kind, testId }) {
  return (
    <div className="rounded-md border p-5 mb-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={testId}>
      <h3 className="font-display text-lg font-medium mb-3" style={{ color: "var(--brand-primary)" }}>{title}</h3>
      <div className="space-y-1">
        {(data || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>None.</div>}
        {(data || []).map((d) => (
          <Link key={d.id + (d.issue || d.reason || "")} to={`/doctors/${d.id}`} className="flex items-center justify-between text-sm hover:underline">
            <span style={{ color: "var(--text-primary)" }}>{d.doctor_name} <span className="text-xs" style={{ color: "var(--text-muted)" }}>· {d.segment}</span></span>
            {(d.issue || d.reason) && <StatusPill kind={kind}>{d.issue || d.reason}</StatusPill>}
          </Link>
        ))}
      </div>
    </div>
  );
}
