import React from "react";

export function StatusPill({ kind = "muted", children, testId }) {
  const cls = {
    success: "pill pill-success",
    warning: "pill pill-warning",
    danger: "pill pill-danger",
    info: "pill pill-info",
    muted: "pill pill-muted",
  }[kind] || "pill pill-muted";
  return <span className={cls} data-testid={testId}>{children}</span>;
}

export function sentimentKind(s) {
  if (!s) return "muted";
  if (s === "Very Positive" || s === "Positive") return "success";
  if (s === "Neutral") return "info";
  return "danger";
}

export function cadenceKind(s) {
  if (s === "Good") return "success";
  if (s === "Due Soon") return "warning";
  return "danger";
}

export function priorityKind(label) {
  if (label === "Critical" || label === "High") return "danger";
  if (label === "Medium") return "warning";
  return "muted";
}

export function SegmentBadge({ segment }) {
  const map = {
    Occasional: "pill-muted",
    Active: "pill-info",
    Engaged: "pill-warning",
    Expert: "pill-success",
  };
  return <span className={`pill ${map[segment] || "pill-muted"}`} data-testid={`segment-${segment}`}>{segment}</span>;
}
