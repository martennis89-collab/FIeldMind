import React, { useEffect, useState, useCallback } from "react";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { toast } from "sonner";
import {
  AlertTriangle, RefreshCw, CheckCircle2, X, Eye, ChevronDown,
  Sparkles, Filter,
} from "lucide-react";

// ---------- helpers ----------
const SEVERITY_RANK = { Critical: 0, High: 1, Medium: 2, Low: 3 };
const STATUS_RANK = { New: 0, Seen: 1, Resolved: 2, Dismissed: 3 };

const severityColor = (s) => ({
  Critical: { bg: "var(--status-danger-bg)", fg: "var(--status-danger)", label: "Critical" },
  High:     { bg: "var(--status-danger-bg)", fg: "var(--status-danger)", label: "High" },
  Medium:   { bg: "var(--status-warning-bg)", fg: "var(--status-warning)", label: "Medium" },
  Low:      { bg: "var(--status-info-bg)", fg: "var(--status-info)", label: "Low" },
}[s] || { bg: "var(--bg-paper)", fg: "var(--text-secondary)", label: s || "—" });

const prettyMetric = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

function sortCards(cards) {
  return [...cards].sort((a, b) => {
    const sa = SEVERITY_RANK[a.severity] ?? 9;
    const sb = SEVERITY_RANK[b.severity] ?? 9;
    if (sa !== sb) return sa - sb;
    const stA = STATUS_RANK[a.status] ?? 9;
    const stB = STATUS_RANK[b.status] ?? 9;
    if (stA !== stB) return stA - stB;
    // newest first
    return (b.created_at || "").localeCompare(a.created_at || "");
  });
}

// ---------- One card ----------
function InsightCard({ card, onAction, showWho }) {
  const sev = severityColor(card.severity);
  const isDone = card.status === "Resolved" || card.status === "Dismissed";
  return (
    <div
      data-testid={`insight-card-${card.id}`}
      data-severity={card.severity}
      data-status={card.status}
      className="rounded-md border p-4 fade-up"
      style={{
        background: "var(--bg-default)",
        borderColor: card.severity === "Critical" || card.severity === "High" ? sev.fg : "var(--border-default)",
        opacity: isDone ? 0.6 : 1,
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="w-9 h-9 rounded-md flex-shrink-0 flex items-center justify-center"
          style={{ background: sev.bg, color: sev.fg }}
        >
          <AlertTriangle className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span
              className="pill"
              style={{ background: sev.bg, color: sev.fg }}
              data-testid={`insight-severity-${card.id}`}
            >
              {sev.label}
            </span>
            <span className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
              {card.category}
            </span>
            {card.status !== "New" && (
              <span className="pill pill-muted text-xs" data-testid={`insight-status-${card.id}`}>
                {card.status}
              </span>
            )}
          </div>
          {showWho && card.scope_id && (
            <div className="text-xs mb-1" style={{ color: "var(--text-secondary)" }}>
              TM: <span data-testid={`insight-scope-${card.id}`}>{card.scope_id}</span>
            </div>
          )}
          <div className="font-display text-base font-semibold" style={{ color: "var(--brand-primary)" }}>
            {card.title}
          </div>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>{card.body}</p>
          <div className="mt-3 rounded px-3 py-2 text-sm" style={{ background: "var(--bg-paper)", color: "var(--text-primary)" }}>
            → {card.suggested_action}
          </div>
          {card.metric_value != null && card.related_metric_slug && (
            <div className="text-xs mt-2 font-mono" style={{ color: "var(--text-muted)" }} data-testid={`insight-metric-${card.id}`}>
              {card.related_metric_slug} · {prettyMetric(card.metric_value)}
            </div>
          )}
        </div>
      </div>
      {!isDone && (
        <div className="mt-3 flex flex-wrap gap-2 justify-end">
          {card.status === "New" && (
            <button
              type="button"
              data-testid={`insight-seen-${card.id}`}
              onClick={() => onAction(card.id, "seen")}
              className="text-xs px-3 py-1.5 rounded border flex items-center gap-1 hover:bg-[var(--bg-paper)]"
              style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
            >
              <Eye className="w-3 h-3" /> Mark seen
            </button>
          )}
          <button
            type="button"
            data-testid={`insight-dismiss-${card.id}`}
            onClick={() => onAction(card.id, "dismiss")}
            className="text-xs px-3 py-1.5 rounded border flex items-center gap-1 hover:bg-[var(--bg-paper)]"
            style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
          >
            <X className="w-3 h-3" /> Dismiss
          </button>
          <button
            type="button"
            data-testid={`insight-resolve-${card.id}`}
            onClick={() => onAction(card.id, "resolve")}
            className="text-xs px-3 py-1.5 rounded border flex items-center gap-1"
            style={{ background: "var(--brand-primary)", color: "white", borderColor: "var(--brand-primary)" }}
          >
            <CheckCircle2 className="w-3 h-3" /> Resolve
          </button>
        </div>
      )}
    </div>
  );
}

// ---------- Panel (TM / Manager / Admin) ----------
/**
 * variant: "tm" → /insights/me · "team" → /insights/team · "company" → /insights/company
 */
export default function AdvisoryPanel({ variant = "tm" }) {
  const { user } = useAuth();
  const [cards, setCards] = useState(null);
  const [rollup, setRollup] = useState(null); // for company
  const [showDone, setShowDone] = useState(false);
  const [filterSeverity, setFilterSeverity] = useState("All");
  const [filterTM, setFilterTM] = useState("All");
  const [refreshing, setRefreshing] = useState(false);

  const endpoint = variant === "tm" ? "/insights/me" : variant === "team" ? "/insights/team" : "/insights/company";

  const load = useCallback(async () => {
    try {
      const params = showDone ? { include_resolved: true, include_dismissed: true } : {};
      const r = await api.get(endpoint, { params });
      if (variant === "company") {
        setRollup(r.data);
        setCards(r.data.cards || []);
      } else {
        setCards(Array.isArray(r.data) ? r.data : []);
      }
    } catch {
      setCards([]);
    }
  }, [endpoint, showDone, variant]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await api.post("/insights/generate");
      await load();
      toast.success("Insights refreshed.");
    } catch {
      toast.error("Could not refresh insights.");
    } finally {
      setRefreshing(false);
    }
  };

  const onAction = async (id, action) => {
    try {
      await api.post(`/insights/${id}/${action}`);
      await load();
      const msg = { seen: "Insight marked seen.", dismiss: "Insight dismissed.", resolve: "Insight resolved." }[action] || "Insight updated.";
      toast.success(msg);
    } catch {
      toast.error("Action failed.");
    }
  };

  if (!cards) {
    return (
      <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={`advisory-${variant}-loading`}>
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading insights…</div>
      </div>
    );
  }

  const emptyMessages = {
    tm: "No urgent actions right now. Keep logging meetings and completing promises.",
    team: "No urgent team issues right now.",
    company: "No company-level operational risks right now.",
  };
  const titles = {
    tm: "What to do next",
    team: "What needs attention",
    company: "Company priorities",
  };
  const subtitles = {
    tm: "Your top priorities based on your activity in the last 30 days.",
    team: "Your team's top operational risks, sorted by severity.",
    company: "Company-wide operational signals — no external benchmarks.",
  };

  // Filtering — only applied in non-"tm" variants where TM filter makes sense
  const distinctTMs = Array.from(new Set(cards.map((c) => c.scope_id))).sort();
  const filtered = sortCards(
    cards
      .filter((c) => filterSeverity === "All" || c.severity === filterSeverity)
      .filter((c) => variant === "tm" || filterTM === "All" || c.scope_id === filterTM)
  );

  return (
    <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={`advisory-panel-${variant}`}>
      <div className="flex items-start justify-between flex-wrap gap-3 mb-4">
        <div>
          <div className="text-xs uppercase tracking-widest flex items-center gap-2" style={{ color: "var(--text-muted)" }}>
            <Sparkles className="w-3 h-3" /> FieldMind advisory
          </div>
          <h2 className="font-display text-xl font-medium" style={{ color: "var(--brand-primary)" }}>{titles[variant]}</h2>
          <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{subtitles[variant]}</p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          {variant !== "tm" && distinctTMs.length > 0 && (
            <select
              data-testid={`advisory-${variant}-filter-tm`}
              value={filterTM}
              onChange={(e) => setFilterTM(e.target.value)}
              className="text-xs px-2 py-1.5 rounded border"
              style={{ borderColor: "var(--border-default)", background: "var(--bg-default)", color: "var(--text-primary)" }}
            >
              <option value="All">All TMs</option>
              {distinctTMs.map((tm) => <option key={tm} value={tm}>{tm.slice(0, 8)}…</option>)}
            </select>
          )}
          <select
            data-testid={`advisory-${variant}-filter-severity`}
            value={filterSeverity}
            onChange={(e) => setFilterSeverity(e.target.value)}
            className="text-xs px-2 py-1.5 rounded border"
            style={{ borderColor: "var(--border-default)", background: "var(--bg-default)", color: "var(--text-primary)" }}
          >
            <option value="All">All severities</option>
            <option value="Critical">Critical</option>
            <option value="High">High</option>
            <option value="Medium">Medium</option>
            <option value="Low">Low</option>
          </select>
          <label className="flex items-center gap-1 text-xs cursor-pointer" style={{ color: "var(--text-secondary)" }}>
            <input
              type="checkbox"
              data-testid={`advisory-${variant}-show-done`}
              checked={showDone}
              onChange={(e) => setShowDone(e.target.checked)}
            />
            Show resolved/dismissed
          </label>
          <button
            type="button"
            data-testid={`advisory-${variant}-refresh`}
            onClick={onRefresh}
            disabled={refreshing}
            className="text-xs px-3 py-1.5 rounded border flex items-center gap-1 hover:bg-[var(--bg-paper)] disabled:opacity-50"
            style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
          >
            <RefreshCw className={`w-3 h-3 ${refreshing ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
      </div>

      {variant === "company" && rollup && rollup.total > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4" data-testid="advisory-company-rollup">
          <div className="rounded border p-3" style={{ borderColor: "var(--border-default)" }}>
            <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Total</div>
            <div className="font-display text-2xl font-medium" style={{ color: "var(--brand-primary)" }}>{rollup.total}</div>
          </div>
          {["Critical", "High", "Medium"].map((s) => (
            <div key={s} className="rounded border p-3" style={{ borderColor: "var(--border-default)" }}>
              <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{s}</div>
              <div className="font-display text-2xl font-medium" style={{ color: severityColor(s).fg }}>
                {rollup.by_severity?.[s] || 0}
              </div>
            </div>
          ))}
        </div>
      )}

      {filtered.length === 0 ? (
        <div className="py-8 text-center" data-testid={`advisory-${variant}-empty`}>
          <CheckCircle2 className="w-8 h-8 mx-auto mb-2" style={{ color: "var(--status-success)" }} />
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{emptyMessages[variant]}</p>
        </div>
      ) : (
        <div className="space-y-3" data-testid={`advisory-${variant}-list`}>
          {filtered.map((c) => (
            <InsightCard key={c.id} card={c} onAction={onAction} showWho={variant !== "tm"} />
          ))}
        </div>
      )}
    </div>
  );
}
