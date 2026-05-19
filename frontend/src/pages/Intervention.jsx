import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Link } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { StatusPill } from "../components/StatusPill";
import InterventionList from "../components/InterventionList";
import ErrorBoundary from "../components/ErrorBoundary";
import { AlertOctagon, AlertTriangle, Sparkles, ArrowRight, Flame, CheckCircle2 } from "lucide-react";

const BUCKETS = [
  { key: "critical", label: "Critical", icon: AlertOctagon, color: "var(--status-danger)", desc: "Stuck or stalled — needs immediate manager attention." },
  { key: "at_risk", label: "At-risk", icon: AlertTriangle, color: "var(--status-warning)", desc: "Drifting — sentiment, follow-up, or barriers signal deterioration." },
  { key: "high_opportunity", label: "High opportunity", icon: Sparkles, color: "var(--status-success)", desc: "Hot momentum — push to next stage." },
];

export default function Intervention() {
  const [data, setData] = useState({ critical: [], at_risk: [], high_opportunity: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get("/dashboard/manager/interventions");
        if (!cancelled) setData(data);
      } catch (e) {
        if (!cancelled) setError(e?.message || "Could not load interventions.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div data-testid="intervention-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Manager intervention</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          Where you <span className="font-medium">need to step in.</span>
        </h1>
        <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          Doctors that are stuck, drifting, or ready to advance — with the suggested action for each.
        </p>
      </div>

      {error && (
        <div
          data-testid="intervention-load-error"
          className="rounded-md border p-4 mb-4 flex items-start gap-3"
          style={{ background: "var(--status-danger-bg)", borderColor: "var(--status-danger)" }}
        >
          <AlertTriangle className="w-5 h-5 mt-0.5 flex-shrink-0" style={{ color: "var(--status-danger)" }} />
          <div>
            <div className="text-sm font-medium" style={{ color: "var(--status-danger)" }}>
              Couldn't load interventions.
            </div>
            <div className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
              {error}. Refresh to retry.
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        {BUCKETS.map((b) => (
          <div key={b.key} className="rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={`bucket-stat-${b.key}`}>
            <div className="flex items-center gap-2 text-xs uppercase tracking-widest" style={{ color: b.color }}>
              <b.icon className="w-4 h-4" /> {b.label}
            </div>
            <div className="font-display text-3xl font-medium mt-2" style={{ color: "var(--brand-primary)" }}>
              {loading ? (
                <span className="inline-block h-7 w-10 rounded animate-pulse align-middle" style={{ background: "var(--bg-muted)" }} />
              ) : (
                (data[b.key] || []).length
              )}
            </div>
            <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{b.desc}</div>
          </div>
        ))}
      </div>

      {loading && (
        <div className="space-y-2 mb-4" data-testid="intervention-loading">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-20 rounded animate-pulse" style={{ background: "var(--bg-muted)" }} />
          ))}
        </div>
      )}

      {!loading && (
      <Tabs defaultValue="critical">
        <TabsList className="bg-[var(--bg-paper)]">
          {BUCKETS.map((b) => (
            <TabsTrigger key={b.key} value={b.key} data-testid={`tab-${b.key}`}>
              {b.label} ({(data[b.key] || []).length})
            </TabsTrigger>
          ))}
        </TabsList>
        {BUCKETS.map((b) => (
          <TabsContent key={b.key} value={b.key}>
            <div className="space-y-2 mt-4">
              {(data[b.key] || []).length === 0 && (
                <div
                  className="rounded-md border p-8 text-center"
                  style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
                  data-testid={`bucket-empty-${b.key}`}
                >
                  <CheckCircle2 className="w-8 h-8 mx-auto mb-2" style={{ color: "var(--status-success)" }} />
                  <div className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                    Nothing in {b.label.toLowerCase()} right now
                  </div>
                  <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{b.desc}</div>
                </div>
              )}
              {(data[b.key] || []).map((item, i) => (
                <Link
                  key={`${item.doctor_id}-${i}`}
                  to={`/doctors/${item.doctor_id}`}
                  data-testid={`intervention-item-${item.doctor_id}-${i}`}
                  className="block rounded-md border p-4 card-lift fade-up"
                  style={{ background: "var(--bg-default)", borderColor: "var(--border-default)", animationDelay: `${i * 25}ms` }}
                >
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div className="min-w-0">
                      <div className="font-display text-base font-medium" style={{ color: "var(--brand-primary)" }}>{item.doctor_name}</div>
                      <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                        {item.segment} · TM: {item.tm_name}
                      </div>
                      <div className="mt-2 text-sm" style={{ color: "var(--text-primary)" }}>
                        <span style={{ color: b.color, fontWeight: 600 }}>{item.issue}</span>
                      </div>
                      <div className="mt-2 flex items-center gap-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                        <ArrowRight className="w-4 h-4" style={{ color: "var(--brand-secondary)" }} />
                        <span>{item.suggested_action}</span>
                      </div>
                    </div>
                    <StatusPill kind="muted"><Flame className="w-3 h-3" />priority {item.score}</StatusPill>
                  </div>
                </Link>
              ))}
            </div>
          </TabsContent>
        ))}
      </Tabs>
      )}

      <ErrorBoundary label="Manager interventions panel failed to render.">
        <div className="mt-10">
          <InterventionList variant="manager" />
        </div>
      </ErrorBoundary>
    </div>
  );
}
