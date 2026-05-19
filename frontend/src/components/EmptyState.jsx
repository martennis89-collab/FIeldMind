import React from "react";
import { Inbox } from "lucide-react";

/**
 * Reusable empty state. Render when a list has loaded with zero rows
 * (NEVER as a loading placeholder — use SkeletonBlock for that).
 */
export default function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  testId = "empty-state",
  tone = "muted", // "muted" | "success" | "info"
}) {
  const color =
    tone === "success"
      ? "var(--status-success)"
      : tone === "info"
      ? "var(--status-info)"
      : "var(--text-muted)";
  return (
    <div
      data-testid={testId}
      className="rounded-md border p-8 text-center"
      style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
    >
      <div
        className="w-12 h-12 mx-auto rounded-md flex items-center justify-center mb-3"
        style={{ background: "var(--bg-paper)", color }}
      >
        <Icon className="w-6 h-6" />
      </div>
      {title && (
        <div
          className="font-display text-base font-medium mb-1"
          style={{ color: "var(--text-primary)" }}
        >
          {title}
        </div>
      )}
      {description && (
        <p className="text-sm max-w-md mx-auto" style={{ color: "var(--text-secondary)" }}>
          {description}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
