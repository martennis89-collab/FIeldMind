import React, { useEffect, useMemo, useState } from "react";
import api from "../lib/api";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { ScanLine, MapPin, CalendarDays, CheckCircle2, XCircle, Search as SearchIcon } from "lucide-react";

const TABS = [
  { id: "booked", label: "Booked", icon: CalendarDays },
  { id: "completed", label: "Completed", icon: CheckCircle2 },
  { id: "lost", label: "Lost", icon: XCircle },
];

function fmtDate(s) {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  } catch { return s; }
}

function relDays(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso); d.setHours(0, 0, 0, 0);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    return Math.round((d - today) / 86400000);
  } catch { return null; }
}

function bucketLabel(days) {
  if (days == null) return "";
  if (days < 0) return `${-days}d ago`;
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  if (days <= 7) return `In ${days}d`;
  return `In ${days}d`;
}

export default function IteroDemos() {
  const { user } = useAuth();
  const [data, setData] = useState({ booked: [], completed: [], lost: [], counts: { booked: 0, completed: 0, lost: 0 } });
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("booked");
  const [q, setQ] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/itero/demos");
      setData(data);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const list = data[tab] || [];
  const filtered = useMemo(() => {
    if (!q.trim()) return list;
    const s = q.toLowerCase().trim();
    return list.filter((r) =>
      (r.doctor_name || "").toLowerCase().includes(s) ||
      (r.clinic_name || "").toLowerCase().includes(s) ||
      (r.city || "").toLowerCase().includes(s),
    );
  }, [list, q]);

  const isManager = user?.role === "Manager";

  return (
    <div data-testid="itero-demos-page">
      <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>iTero · Demos</div>
          <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Demos <span className="font-medium">overview.</span>
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            {isManager ? "All demos across the team." : "Your booked, completed, and lost demos."}
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/itero/pipeline">
            <Button variant="outline" style={{ borderColor: "var(--brand-primary)", color: "var(--brand-primary)" }}>Pipeline</Button>
          </Link>
          <Link to="/itero">
            <Button variant="outline" style={{ borderColor: "var(--brand-primary)", color: "var(--brand-primary)" }}>
              <ScanLine className="w-4 h-4 mr-1" /> Funnel
            </Button>
          </Link>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="inline-flex rounded-md border" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}>
          {TABS.map((t, i, arr) => {
            const Icon = t.icon;
            const active = tab === t.id;
            const count = (data.counts || {})[t.id] || 0;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                data-testid={`demos-tab-${t.id}`}
                className={`px-4 py-2 text-sm flex items-center gap-1.5 transition-colors ${i === 0 ? "rounded-l-md" : ""} ${i === arr.length - 1 ? "rounded-r-md" : ""}`}
                style={{
                  background: active ? "var(--brand-primary)" : "transparent",
                  color: active ? "white" : "var(--text-secondary)",
                }}
              >
                <Icon className="w-3.5 h-3.5" />
                {t.label}
                <span className="text-xs opacity-75">({count})</span>
              </button>
            );
          })}
        </div>
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: "var(--text-muted)" }} />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search doctor, clinic, city…"
            className="pl-9 bg-white h-10"
            data-testid="demos-search-input"
          />
        </div>
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-md border p-8 text-center" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
          <CalendarDays className="w-10 h-10 mx-auto mb-2" style={{ color: "var(--text-muted)" }} />
          <div className="font-display text-lg" style={{ color: "var(--brand-primary)" }}>
            {tab === "booked" ? "No demos booked yet" : tab === "completed" ? "No demos completed in the last 30 days" : "No lost demos yet"}
          </div>
        </div>
      ) : (
        <div className="space-y-2" data-testid={`demos-list-${tab}`}>
          {filtered.map((r) => {
            const dt = tab === "completed" ? r.completed_date : tab === "booked" ? r.booked_date : (r.completed_date || r.booked_date);
            const rel = relDays(dt);
            const isOverdue = tab === "booked" && rel !== null && rel < 0;
            return (
              <Link
                key={r.doctor_id}
                to={`/doctors/${r.doctor_id}`}
                data-testid={`demo-row-${r.doctor_id}`}
                className="block rounded-md border p-3 transition-colors hover:border-[var(--brand-primary)]"
                style={{
                  background: "var(--bg-default)",
                  borderColor: isOverdue ? "var(--status-danger)" : "var(--border-default)",
                  borderLeftWidth: 3,
                  borderLeftColor:
                    tab === "completed" ? "var(--status-success)" :
                    tab === "lost" ? "var(--text-muted)" :
                    isOverdue ? "var(--status-danger)" : "var(--brand-secondary)",
                }}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-medium" style={{ color: "var(--brand-primary)" }}>
                      {r.doctor_name}
                    </div>
                    <div className="text-xs mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5" style={{ color: "var(--text-secondary)" }}>
                      {(r.clinic_name || r.city) && (
                        <span className="inline-flex items-center gap-1"><MapPin className="w-3 h-3" />{[r.clinic_name, r.city].filter(Boolean).join(" · ")}</span>
                      )}
                      {r.segment && <span className="pill pill-info">{r.segment}</span>}
                      {isManager && r.tm_name && <span>TM: {r.tm_name}</span>}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-mono" style={{ color: isOverdue ? "var(--status-danger)" : "var(--text-primary)" }}>
                      {fmtDate(dt)}
                    </div>
                    {rel !== null && (
                      <div className="text-[11px]" style={{ color: isOverdue ? "var(--status-danger)" : "var(--text-muted)" }}>
                        {isOverdue ? `Overdue · ${bucketLabel(rel)}` : bucketLabel(rel)}
                      </div>
                    )}
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
