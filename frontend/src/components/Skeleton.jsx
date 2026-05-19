import React from "react";

/**
 * Lightweight pulsing skeleton blocks for loading states across the app.
 * No external dependency. Uses Tailwind animate-pulse + theme tokens.
 */
export function SkeletonBlock({ className = "", height = 12, width = "100%", testId }) {
  return (
    <div
      data-testid={testId}
      className={`animate-pulse rounded ${className}`}
      style={{
        height,
        width,
        background: "var(--bg-muted)",
      }}
    />
  );
}

export function StatCardSkeleton({ testId }) {
  return (
    <div
      data-testid={testId}
      className="rounded-md border p-5"
      style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
    >
      <div className="flex items-center justify-between">
        <SkeletonBlock width={80} height={10} />
        <SkeletonBlock width={36} height={36} className="rounded-md" />
      </div>
      <div className="mt-3">
        <SkeletonBlock width={64} height={28} />
      </div>
    </div>
  );
}

export function StatGridSkeleton({ count = 4, testId = "stat-grid-skeleton" }) {
  return (
    <div data-testid={testId} className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      {Array.from({ length: count }).map((_, i) => (
        <StatCardSkeleton key={i} testId={`${testId}-${i}`} />
      ))}
    </div>
  );
}

export function CardSkeleton({ rows = 3, testId }) {
  return (
    <div
      data-testid={testId}
      className="rounded-md border p-6 mb-6"
      style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
    >
      <SkeletonBlock width={140} height={10} />
      <div className="mt-2">
        <SkeletonBlock width={220} height={20} />
      </div>
      <div className="mt-4 space-y-2">
        {Array.from({ length: rows }).map((_, i) => (
          <SkeletonBlock key={i} height={12} width={`${75 + ((i * 7) % 20)}%`} />
        ))}
      </div>
    </div>
  );
}
