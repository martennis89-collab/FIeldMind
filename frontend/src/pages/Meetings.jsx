import React, { useEffect, useMemo, useState } from "react";
import api from "../lib/api";
import { useNavigate, Link } from "react-router-dom";
import { Button } from "../components/ui/button";
import { CalendarPlus, Clock, MapPin, ClipboardList, Trash2, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function dayBucket(iso) {
  const now = new Date();
  const d = new Date(iso);
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const tomorrow = new Date(startOfDay); tomorrow.setDate(tomorrow.getDate() + 1);
  const endOfWeek = new Date(startOfDay); endOfWeek.setDate(endOfWeek.getDate() + 7);
  if (d < startOfDay) return "Past";
  if (d < tomorrow) return "Today";
  if (d < endOfWeek) return "This week";
  return "Later";
}

export default function Meetings() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("upcoming");
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/meetings`, { params: { when: tab } });
      setRows(data);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [tab]);

  const grouped = useMemo(() => {
    const g = { Today: [], "This week": [], Later: [], Past: [] };
    for (const m of rows) {
      const k = tab === "past" ? "Past" : dayBucket(m.scheduled_at);
      (g[k] = g[k] || []).push(m);
    }
    return g;
  }, [rows, tab]);

  const cancelMeeting = async (m) => {
    if (!window.confirm(`Cancel meeting with ${m.doctor_name}?`)) return;
    try {
      await api.delete(`/meetings/${m.id}`);
      toast.success("Meeting cancelled");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    }
  };

  const logVisit = (m) => {
    navigate(`/log-visit?doctor_id=${m.doctor_id}&meeting_id=${m.id}`);
  };

  const sectionOrder = tab === "past" ? ["Past"] : ["Today", "This week", "Later"];

  return (
    <div data-testid="meetings-page">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Schedule</div>
          <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Meetings <span className="font-medium">({rows.length})</span>
          </h1>
        </div>
        <Link to="/meetings/book" data-testid="book-meeting-link">
          <Button style={{ background: "var(--brand-secondary)", color: "white" }}>
            <CalendarPlus className="w-4 h-4 mr-1" /> Book a meeting
          </Button>
        </Link>
      </div>

      <div className="inline-flex rounded-md border mb-4" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}>
        {[
          { id: "upcoming", label: "Upcoming" },
          { id: "past", label: "Past" },
          { id: "all", label: "All" },
        ].map((t, i, arr) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            data-testid={`meetings-tab-${t.id}`}
            className={`px-4 py-2 text-sm transition-colors ${i === 0 ? "rounded-l-md" : ""} ${i === arr.length - 1 ? "rounded-r-md" : ""}`}
            style={{
              background: tab === t.id ? "var(--brand-primary)" : "transparent",
              color: tab === t.id ? "white" : "var(--text-secondary)",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : rows.length === 0 ? (
        <div className="rounded-md border p-8 text-center" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
          <CalendarPlus className="w-10 h-10 mx-auto mb-2" style={{ color: "var(--text-muted)" }} />
          <div className="font-display text-lg" style={{ color: "var(--brand-primary)" }}>No meetings yet</div>
          <p className="text-sm mt-1 mb-4" style={{ color: "var(--text-secondary)" }}>Book your next visit and it'll show up here.</p>
          <Link to="/meetings/book"><Button style={{ background: "var(--brand-secondary)", color: "white" }}>Book a meeting</Button></Link>
        </div>
      ) : (
        <div className="space-y-6">
          {sectionOrder.map((sec) =>
            (grouped[sec] && grouped[sec].length > 0) ? (
              <div key={sec}>
                <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>{sec} ({grouped[sec].length})</div>
                <div className="space-y-2">
                  {grouped[sec].map((m) => {
                    const cancelled = m.status === "Cancelled";
                    const completed = m.status === "Completed";
                    return (
                      <div
                        key={m.id}
                        data-testid={`meeting-card-${m.id}`}
                        className="rounded-md border p-4"
                        style={{
                          background: "var(--bg-default)",
                          borderColor: "var(--border-default)",
                          borderLeftWidth: 3,
                          borderLeftColor: completed ? "var(--status-success)" : cancelled ? "var(--text-muted)" : "var(--brand-secondary)",
                          opacity: cancelled ? 0.55 : 1,
                        }}
                      >
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="min-w-0">
                            <Link to={`/doctors/${m.doctor_id}`} className="font-display text-lg font-semibold hover:underline" style={{ color: "var(--brand-primary)" }}>
                              {m.doctor_name}
                            </Link>
                            <div className="text-sm flex flex-wrap items-center gap-x-3 gap-y-1 mt-0.5" style={{ color: "var(--text-secondary)" }}>
                              <span className="inline-flex items-center gap-1"><Clock className="w-3.5 h-3.5" />{fmtDate(m.scheduled_at)}{m.duration_minutes ? ` · ${m.duration_minutes} min` : ""}</span>
                              {(m.clinic_name || m.city) && (
                                <span className="inline-flex items-center gap-1">
                                  <MapPin className="w-3.5 h-3.5" /> {[m.clinic_name, m.city].filter(Boolean).join(" · ")}
                                </span>
                              )}
                            </div>
                            {m.subject && <div className="text-sm mt-1.5" style={{ color: "var(--text-primary)" }}>{m.subject}</div>}
                          </div>
                          <div className="flex flex-col items-end gap-2 shrink-0">
                            {completed && <span className="pill pill-success inline-flex items-center gap-1"><CheckCircle2 className="w-3 h-3" />Logged</span>}
                            {cancelled && <span className="pill pill-muted">Cancelled</span>}
                            {!completed && !cancelled && (
                              <div className="flex gap-1">
                                <Button size="sm" onClick={() => logVisit(m)} data-testid={`meeting-log-${m.id}`} style={{ background: "var(--brand-primary)", color: "white" }}>
                                  <ClipboardList className="w-3.5 h-3.5 mr-1" /> Log visit
                                </Button>
                                <Button size="sm" variant="outline" onClick={() => cancelMeeting(m)} data-testid={`meeting-cancel-${m.id}`}>
                                  <Trash2 className="w-3.5 h-3.5" style={{ color: "var(--status-danger)" }} />
                                </Button>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null,
          )}
        </div>
      )}
    </div>
  );
}
