import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Link } from "react-router-dom";

function PctBar({ value, total, color = "var(--status-info)", testId }) {
  const pct = total ? Math.round((value / total) * 100) : 0;
  return (
    <div data-testid={testId}>
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

export default function MarketIntelligence() {
  const [mgr, setMgr] = useState(null);
  const [com, setCom] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [a, b] = await Promise.all([api.get("/dashboard/manager"), api.get("/dashboard/manager/commercial")]);
        setMgr(a.data); setCom(b.data);
      } finally { setLoading(false); }
    })();
  }, []);

  if (loading || !mgr || !com) return <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>;

  const totalDoctors = com.totals.doctors || 1;

  return (
    <div data-testid="market-intel-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Market intelligence</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          The field, <span className="font-medium">aggregated.</span>
        </h1>
      </div>

      <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Market pulse</div>
        <p className="text-sm mt-1 leading-relaxed" data-testid="market-pulse" style={{ color: "var(--text-primary)" }}>{mgr.market_pulse}</p>
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mb-6">
        <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Top barriers (30d)</h3>
          <div className="space-y-1.5">
            {mgr.top_barriers.map((b) => (
              <div key={b.name} className="flex items-center justify-between text-sm">
                <span className="truncate pr-2" style={{ color: "var(--text-primary)" }}>{b.name}</span>
                <span className="pill pill-danger">{b.count}</span>
              </div>
            ))}
            {mgr.top_barriers.length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>No data yet.</div>}
          </div>
        </div>

        <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Top topics (30d)</h3>
          <div className="space-y-1.5">
            {mgr.top_topics.map((t) => (
              <div key={t.name} className="flex items-center justify-between text-sm">
                <span className="truncate pr-2" style={{ color: "var(--text-primary)" }}>{t.name}</span>
                <span className="pill pill-info">{t.count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="barriers-by-stage">
        <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Barriers by stage</h3>
        <div className="grid sm:grid-cols-3 gap-5">
          {[
            { key: "pre_demo", label: "Pre-demo" },
            { key: "post_demo", label: "Post-demo" },
            { key: "post_proposal", label: "Post-proposal" },
          ].map((s) => (
            <div key={s.key}>
              <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>{s.label}</div>
              <div className="space-y-1">
                {(com.barriers_by_stage[s.key] || []).map((b) => (
                  <div key={b.name} className="flex items-center justify-between text-sm">
                    <span className="truncate pr-2" style={{ color: "var(--text-primary)" }}>{b.name}</span>
                    <span className="pill pill-warning">{b.count}</span>
                  </div>
                ))}
                {(com.barriers_by_stage[s.key] || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>None</div>}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="pricing-coverage">
        <h3 className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Pricing context coverage</h3>
        <div className="grid sm:grid-cols-3 gap-5">
          <div>
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Boost discussed</div>
            <PctBar value={Math.round(com.pricing_coverage.boost_pct * totalDoctors)} total={totalDoctors} color="var(--status-info)" />
          </div>
          <div>
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Trade-in discussed</div>
            <PctBar value={Math.round(com.pricing_coverage.trade_in_pct * totalDoctors)} total={totalDoctors} color="var(--status-info)" />
          </div>
          <div>
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Growth program explained</div>
            <PctBar value={Math.round(com.pricing_coverage.growth_pct * totalDoctors)} total={totalDoctors} color="var(--status-info)" />
          </div>
        </div>

        <div className="grid sm:grid-cols-3 gap-5 mt-6">
          {[
            { key: "no_boost", label: "Doctors without boost discussion" },
            { key: "no_trade_in", label: "Doctors without trade-in discussion" },
            { key: "no_growth", label: "Doctors without growth program explanation" },
          ].map((cfg) => (
            <div key={cfg.key}>
              <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>{cfg.label}</div>
              <div className="space-y-1 max-h-44 overflow-y-auto">
                {(com.pricing_coverage[cfg.key] || []).slice(0, 8).map((d) => (
                  <Link key={d.id} to={`/doctors/${d.id}`} className="block text-sm hover:underline" style={{ color: "var(--text-primary)" }}>
                    {d.doctor_name} <span className="text-xs" style={{ color: "var(--text-muted)" }}>· {d.segment}</span>
                  </Link>
                ))}
                {(com.pricing_coverage[cfg.key] || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>All covered ✓</div>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
