import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Gauge, Info, ChevronDown, ChevronUp } from "lucide-react";

/**
 * Field Execution Index V1 — compact TM dashboard widget.
 *
 * Pulls from GET /api/metrics/me/fei.
 * • If sufficient_data=false → shows backend "Not enough data yet" message.
 *   NEVER renders a fake 0.
 * • Always shows the "V1 beta" label so users know this is a first-generation
 *   composite, not the final/full Field Execution Index.
 * • Component breakdown is collapsed by default; expanding reads from the same
 *   payload (no extra request, no new backend logic).
 */
export default function FEIBadge() {
  const [data, setData] = useState(null); // null = loading, {} = error/empty
  const [error, setError] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get("/metrics/me/fei");
        if (!cancelled) setData(r.data || {});
      } catch {
        if (!cancelled) {
          setError(true);
          setData({});
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (data === null) {
    return (
      <div
        data-testid="fei-v1-loading"
        className="rounded-md border p-4 mb-4"
        style={{
          background: "var(--bg-default)",
          borderColor: "var(--border-default)",
        }}
      >
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
          Loading Execution Score V1…
        </div>
      </div>
    );
  }

  const sufficient = data.sufficient_data && data.fei != null;
  const label = data.label || null;
  const labelColor =
    label === "High"
      ? "var(--status-success)"
      : label === "Medium"
      ? "var(--status-warning)"
      : label === "Low"
      ? "var(--status-danger)"
      : "var(--text-muted)";

  return (
    <div
      data-testid="fei-v1-widget"
      className="rounded-md border p-4 mb-4"
      style={{
        background: "var(--bg-default)",
        borderColor: "var(--border-default)",
      }}
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="w-10 h-10 rounded-md flex-shrink-0 flex items-center justify-center"
            style={{ background: "var(--bg-paper)", color: "var(--brand-primary)" }}
          >
            <Gauge className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className="text-xs uppercase tracking-widest"
                style={{ color: "var(--text-muted)" }}
              >
                Field Execution Index
              </span>
              <span
                data-testid="fei-v1-pill"
                className="pill text-[10px]"
                style={{
                  background: "var(--bg-paper)",
                  color: "var(--brand-secondary)",
                  border: "1px solid var(--border-default)",
                }}
                title="First-generation composite score — not the final Field Execution Index."
              >
                V1 · beta
              </span>
            </div>
            {sufficient ? (
              <div className="flex items-baseline gap-2 mt-0.5">
                <span
                  className="font-display text-3xl font-medium leading-none"
                  style={{ color: "var(--brand-primary)" }}
                  data-testid="fei-v1-score"
                >
                  {data.fei}
                </span>
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  / 100
                </span>
                {label && (
                  <span
                    data-testid="fei-v1-label"
                    className="pill text-xs ml-1"
                    style={{ background: "var(--bg-paper)", color: labelColor, border: `1px solid ${labelColor}` }}
                  >
                    {label}
                  </span>
                )}
              </div>
            ) : (
              <div
                className="text-sm mt-0.5"
                style={{ color: "var(--text-secondary)" }}
                data-testid="fei-v1-insufficient"
              >
                {error
                  ? "Couldn't load Execution Score V1 right now."
                  : data.message ||
                    "Not enough data yet. Log a few visits, demos, and weekly reports to see your Execution Score V1."}
              </div>
            )}
          </div>
        </div>
        {Array.isArray(data.components) && data.components.length > 0 && (
          <button
            type="button"
            onClick={() => setShowDetails((s) => !s)}
            data-testid="fei-v1-toggle-details"
            className="text-xs px-3 py-1.5 rounded border flex items-center gap-1 hover:bg-[var(--bg-paper)]"
            style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
          >
            {showDetails ? (
              <>
                <ChevronUp className="w-3 h-3" /> Hide breakdown
              </>
            ) : (
              <>
                <ChevronDown className="w-3 h-3" /> Show breakdown
              </>
            )}
          </button>
        )}
      </div>

      {showDetails && Array.isArray(data.components) && data.components.length > 0 && (
        <div
          className="mt-3 pt-3 border-t space-y-2"
          style={{ borderColor: "var(--border-default)" }}
          data-testid="fei-v1-components"
        >
          {data.components.map((c) => (
            <div
              key={c.slug}
              className="flex items-center justify-between gap-2 text-xs"
              data-testid={`fei-v1-component-${c.slug}`}
            >
              <div className="min-w-0 flex-1">
                <div className="font-medium truncate" style={{ color: "var(--text-primary)" }}>
                  {c.name}
                </div>
                <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                  weight {Math.round((c.weight || 0) * 100)}%
                  {!c.sufficient_data && c.message ? ` · ${c.message}` : ""}
                </div>
              </div>
              <div className="font-mono text-right">
                {c.sufficient_data && c.value_0_100 != null ? (
                  <span style={{ color: "var(--brand-primary)" }}>{Math.round(c.value_0_100)}</span>
                ) : (
                  <span style={{ color: "var(--text-muted)" }}>—</span>
                )}
              </div>
            </div>
          ))}
          <div
            className="text-[11px] flex items-start gap-1 pt-1"
            style={{ color: "var(--text-muted)" }}
          >
            <Info className="w-3 h-3 mt-0.5 flex-shrink-0" />
            <span>
              Execution Score V1 is a weighted composite of your in-app activity (promises, demos,
              reports). Components without enough data are excluded from the score, never zero-padded.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
