import React from "react";

// Shared metric tile used by ManagerView and TMView dashboards.
export default function StatCard({ label, value, sub, icon: Icon, kind = "muted", testId }) {
  const colors = {
    success: { bg: "var(--status-success-bg)", fg: "var(--status-success)" },
    warning: { bg: "var(--status-warning-bg)", fg: "var(--status-warning)" },
    danger: { bg: "var(--status-danger-bg)", fg: "var(--status-danger)" },
    info: { bg: "var(--status-info-bg)", fg: "var(--status-info)" },
    muted: { bg: "var(--bg-paper)", fg: "var(--text-primary)" },
  }[kind];
  return (
    <div
      className="rounded-md border p-5 card-lift"
      style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
      data-testid={testId}
    >
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
