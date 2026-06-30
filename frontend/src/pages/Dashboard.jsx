import React, { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { AlertTriangle } from "lucide-react";

import ErrorBoundary from "../components/ErrorBoundary";
import ManagerView from "../components/dashboard/ManagerView";
import TMView from "../components/dashboard/TMView";

export default function Dashboard() {
  const { user } = useAuth();
  const [tmData, setTmData] = useState(null);
  const [mgrData, setMgrData] = useState(null);
  const [commercialData, setCommercialData] = useState(null);
  const [interventionsData, setInterventionsData] = useState(null);
  const [crossSellData, setCrossSellData] = useState(null);
  const [loadError, setLoadError] = useState(null);

  // Phase L: SeniorTMs get TWO dashboards — their personal TM dashboard and
  // a Manager-style view of their sub-team. Default to "team" since oversight
  // is the primary reason this role exists.
  const isSeniorTM = user.role === "SeniorTM";
  const isManagerOnly =
    user.role === "Manager" || user.role === "Admin" || user.role === "Owner";
  const [seniorView, setSeniorView] = useState("team"); // "personal" | "team"

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);

    // P1 follow-up — fire each endpoint independently so each card paints as
    // soon as its data lands (previously a single Promise.all blocked the
    // whole dashboard on the slowest cross-company endpoint ~8s for Owners).
    const wantsManager = isManagerOnly || isSeniorTM;
    const wantsTm = user.role === "TM" || isSeniorTM;

    const safeGet = async (url, setter) => {
      try {
        const r = await api.get(url);
        if (!cancelled) {
          setter(r.data);
          // Clear a previously-set fatal banner once any subsequent fetch
          // succeeds — a transient 503 on cross-sell shouldn't keep blotting
          // the dashboard once /dashboard/manager + stat cards have rendered.
          setLoadError(null);
        }
      } catch (e) {
        if (!cancelled) setLoadError(e?.message || "Could not load the dashboard.");
      }
    };

    if (wantsManager) {
      safeGet("/dashboard/manager", setMgrData);
      safeGet("/dashboard/manager/commercial", setCommercialData);
      safeGet("/dashboard/manager/interventions", setInterventionsData);
      safeGet("/dashboard/manager/cross-sell", setCrossSellData);
    }
    if (wantsTm) {
      safeGet("/dashboard/tm", setTmData);
    }

    return () => { cancelled = true; };
  }, [user.role, isManagerOnly, isSeniorTM]);

  const headerEyebrow = isSeniorTM
    ? "Senior TM"
    : user.role === "Manager"
    ? "Control tower"
    : `${user.role} dashboard`;
  const headerSubtitle = isSeniorTM
    ? seniorView === "personal"
      ? "Your personal activity, FEI V1, and priority doctors."
      : "Your sub-team's funnels, alerts, and where to step in."
    : user.role === "TM"
    ? "Here's who needs your attention today."
    : "Funnels, alerts, and where to step in.";

  return (
    <div data-testid="dashboard-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{headerEyebrow}</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          Hello, <span className="font-medium">{user.full_name?.split(" ")[0]}</span>.
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>{headerSubtitle}</p>
      </div>

      {isSeniorTM && (
        <div
          className="inline-flex rounded-md border p-0.5 mb-6"
          data-testid="seniortm-view-toggle"
          style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}
        >
          {[
            { key: "team", label: "Team view" },
            { key: "personal", label: "Personal view" },
          ].map((opt) => {
            const active = seniorView === opt.key;
            return (
              <button
                key={opt.key}
                type="button"
                onClick={() => setSeniorView(opt.key)}
                data-testid={`seniortm-view-${opt.key}`}
                aria-pressed={active}
                className="text-xs px-4 py-1.5 rounded font-medium transition-colors"
                style={{
                  background: active ? "var(--brand-primary)" : "transparent",
                  color: active ? "white" : "var(--text-secondary)",
                }}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      )}

      {loadError && (
        <div
          data-testid="dashboard-load-error"
          className="rounded-md border p-4 mb-4 flex items-start gap-3"
          style={{ background: "var(--status-danger-bg)", borderColor: "var(--status-danger)" }}
        >
          <AlertTriangle className="w-5 h-5 mt-0.5 flex-shrink-0" style={{ color: "var(--status-danger)" }} />
          <div>
            <div className="text-sm font-medium" style={{ color: "var(--status-danger)" }}>
              Couldn&apos;t load the dashboard.
            </div>
            <div className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
              {loadError}. Refresh the page to retry.
            </div>
          </div>
        </div>
      )}

      <ErrorBoundary label="The dashboard hit an unexpected rendering error.">
        {isManagerOnly && (
          <ManagerView data={mgrData} commercial={commercialData} interventions={interventionsData} crossSell={crossSellData} />
        )}
        {isSeniorTM && seniorView === "team" && (
          <ManagerView data={mgrData} commercial={commercialData} interventions={interventionsData} crossSell={crossSellData} />
        )}
        {isSeniorTM && seniorView === "personal" && <TMView data={tmData} />}
        {user.role === "TM" && <TMView data={tmData} />}
      </ErrorBoundary>
    </div>
  );
}
