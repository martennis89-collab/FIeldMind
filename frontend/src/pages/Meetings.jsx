import React, { useEffect, useMemo, useState } from "react";
import api from "../lib/api";
import { useNavigate, Link, useSearchParams } from "react-router-dom";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import {
  CalendarPlus, Clock, MapPin, ClipboardList, Trash2, CheckCircle2,
  CalendarDays, Users as UsersIcon, Plus, Sparkles,
} from "lucide-react";
import { toast } from "sonner";

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "short", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit",
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

const FILTERS = [
  { id: "all", label: "All" },
  { id: "meetings", label: "Meetings" },
  { id: "events", label: "Events" },
];

const TABS = [
  { id: "upcoming", label: "Upcoming" },
  { id: "past", label: "Past" },
  { id: "all", label: "All" },
];

export default function Meetings() {
  const [meetings, setMeetings] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("upcoming");
  const [filter, setFilter] = useState("all");
  const [eventDialog, setEventDialog] = useState(null); // null | "new" | event obj for edit
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    if (searchParams.get("new_event") === "1") {
      setEventDialog("new");
      const sp = new URLSearchParams(searchParams);
      sp.delete("new_event");
      setSearchParams(sp, { replace: true });
    }
    // eslint-disable-next-line
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const [m, e] = await Promise.all([
        api.get(`/meetings`, { params: { when: tab } }),
        api.get(`/events`, { params: { when: tab } }),
      ]);
      setMeetings(m.data); setEvents(e.data);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [tab]);

  // Combine + sort
  const combined = useMemo(() => {
    const m = (filter !== "events") ? meetings.map((x) => ({ ...x, _kind: "meeting" })) : [];
    const e = (filter !== "meetings") ? events.map((x) => ({ ...x, _kind: "event" })) : [];
    const all = [...m, ...e].sort((a, b) => (a.scheduled_at || "").localeCompare(b.scheduled_at || ""));
    return all;
  }, [meetings, events, filter]);

  const grouped = useMemo(() => {
    const g = { Today: [], "This week": [], Later: [], Past: [] };
    for (const r of combined) {
      const k = tab === "past" ? "Past" : dayBucket(r.scheduled_at);
      (g[k] = g[k] || []).push(r);
    }
    return g;
  }, [combined, tab]);

  const sectionOrder = tab === "past" ? ["Past"] : ["Today", "This week", "Later"];

  const cancelMeeting = async (m) => {
    if (!window.confirm(`Cancel meeting with ${m.doctor_name}?`)) return;
    try { await api.delete(`/meetings/${m.id}`); toast.success("Meeting cancelled"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Failed"); }
  };
  const deleteEvent = async (e) => {
    if (!window.confirm(`Delete "${e.title}"?`)) return;
    try { await api.delete(`/events/${e.id}`); toast.success("Event deleted"); load(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Failed"); }
  };
  const markEventDone = async (e) => {
    try { await api.put(`/events/${e.id}`, { status: "Done" }); toast.success("Marked done"); load(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Failed"); }
  };

  const logVisit = (m) => navigate(`/log-visit?doctor_id=${m.doctor_id}&meeting_id=${m.id}`);

  const total = combined.length;

  return (
    <div data-testid="meetings-page">
      <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Schedule</div>
          <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Meetings &amp; events <span className="font-medium">({total})</span>
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={() => setEventDialog("new")}
            data-testid="add-event-btn"
            style={{ borderColor: "var(--brand-primary)", color: "var(--brand-primary)" }}
          >
            <Plus className="w-4 h-4 mr-1" /> Add event
          </Button>
          <Link to="/meetings/book" data-testid="book-meeting-link">
            <Button style={{ background: "var(--brand-secondary)", color: "white" }}>
              <CalendarPlus className="w-4 h-4 mr-1" /> Book meeting
            </Button>
          </Link>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="inline-flex rounded-md border" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}>
          {TABS.map((t, i, arr) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              data-testid={`schedule-tab-${t.id}`}
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
        <div className="inline-flex rounded-md border" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}>
          {FILTERS.map((f, i, arr) => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              data-testid={`schedule-filter-${f.id}`}
              className={`px-3 py-1.5 text-xs transition-colors ${i === 0 ? "rounded-l-md" : ""} ${i === arr.length - 1 ? "rounded-r-md" : ""}`}
              style={{
                background: filter === f.id ? "var(--brand-secondary)" : "transparent",
                color: filter === f.id ? "white" : "var(--text-secondary)",
              }}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : combined.length === 0 ? (
        <div className="rounded-md border p-8 text-center" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
          <CalendarDays className="w-10 h-10 mx-auto mb-2" style={{ color: "var(--text-muted)" }} />
          <div className="font-display text-lg" style={{ color: "var(--brand-primary)" }}>Nothing scheduled</div>
          <p className="text-sm mt-1 mb-4" style={{ color: "var(--text-secondary)" }}>Book a meeting or add an event to fill your week.</p>
          <div className="flex justify-center gap-2">
            <Button variant="outline" onClick={() => setEventDialog("new")}><Plus className="w-4 h-4 mr-1" /> Add event</Button>
            <Link to="/meetings/book"><Button style={{ background: "var(--brand-secondary)", color: "white" }}>Book meeting</Button></Link>
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {sectionOrder.map((sec) =>
            (grouped[sec] && grouped[sec].length > 0) ? (
              <div key={sec}>
                <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>{sec} ({grouped[sec].length})</div>
                <div className="space-y-2">
                  {grouped[sec].map((r) =>
                    r._kind === "meeting"
                      ? <MeetingCard key={`m-${r.id}`} m={r} onLog={() => logVisit(r)} onCancel={() => cancelMeeting(r)} />
                      : <EventCard key={`e-${r.id}`} e={r} onEdit={() => setEventDialog(r)} onDone={() => markEventDone(r)} onDelete={() => deleteEvent(r)} />,
                  )}
                </div>
              </div>
            ) : null,
          )}
        </div>
      )}

      <EventDialog
        open={!!eventDialog}
        existing={eventDialog && eventDialog !== "new" ? eventDialog : null}
        onClose={() => setEventDialog(null)}
        onSaved={() => { setEventDialog(null); load(); }}
      />
    </div>
  );
}

function MeetingCard({ m, onLog, onCancel }) {
  const cancelled = m.status === "Cancelled";
  const completed = m.status === "Completed";
  return (
    <div
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
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--brand-secondary)" }}>Meeting</span>
            <Link to={`/doctors/${m.doctor_id}`} className="font-display text-lg font-semibold hover:underline" style={{ color: "var(--brand-primary)" }}>
              {m.doctor_name}
            </Link>
          </div>
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
              <Button size="sm" onClick={onLog} data-testid={`meeting-log-${m.id}`} style={{ background: "var(--brand-primary)", color: "white" }}>
                <ClipboardList className="w-3.5 h-3.5 mr-1" /> Log visit
              </Button>
              <Button size="sm" variant="outline" onClick={onCancel} data-testid={`meeting-cancel-${m.id}`}>
                <Trash2 className="w-3.5 h-3.5" style={{ color: "var(--status-danger)" }} />
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function EventCard({ e, onEdit, onDone, onDelete }) {
  const done = e.status === "Done";
  const cancelled = e.status === "Cancelled";

  // Format the time range. If start and end are on the same day, show day once.
  const start = e.scheduled_at ? new Date(e.scheduled_at) : null;
  const end = e.ends_at ? new Date(e.ends_at) : null;
  const sameDay = start && end &&
    start.getFullYear() === end.getFullYear() &&
    start.getMonth() === end.getMonth() &&
    start.getDate() === end.getDate();
  const timeFmt = (d) => d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const dayFmt = (d) => d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  let timeRange;
  if (start && end && sameDay) timeRange = `${dayFmt(start)} · ${timeFmt(start)} – ${timeFmt(end)}`;
  else if (start && end) timeRange = `${dayFmt(start)} ${timeFmt(start)} → ${dayFmt(end)} ${timeFmt(end)}`;
  else timeRange = fmtDate(e.scheduled_at);

  return (
    <div
      data-testid={`event-card-${e.id}`}
      className="rounded-md border p-4"
      style={{
        background: "var(--bg-default)",
        borderColor: "var(--border-default)",
        borderLeftWidth: 3,
        borderLeftColor: done ? "var(--status-success)" : cancelled ? "var(--text-muted)" : "var(--brand-primary)",
        opacity: cancelled ? 0.55 : 1,
      }}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-widest font-semibold inline-flex items-center gap-1" style={{ color: "var(--brand-primary)" }}>
              <Sparkles className="w-3 h-3" /> Event
            </span>
            <button onClick={onEdit} className="font-display text-lg font-semibold hover:underline text-left" data-testid={`event-edit-${e.id}`} style={{ color: "var(--brand-primary)" }}>
              {e.title}
            </button>
          </div>
          <div className="text-sm flex flex-wrap items-center gap-x-3 gap-y-1 mt-0.5" style={{ color: "var(--text-secondary)" }}>
            <span className="inline-flex items-center gap-1"><Clock className="w-3.5 h-3.5" />{timeRange}</span>
            {e.location && (
              <span className="inline-flex items-center gap-1"><MapPin className="w-3.5 h-3.5" /> {e.location}</span>
            )}
          </div>
          {e.notes && <div className="text-sm mt-1.5" style={{ color: "var(--text-primary)" }}>{e.notes}</div>}
        </div>
        <div className="flex flex-col items-end gap-2 shrink-0">
          {done && <span className="pill pill-success inline-flex items-center gap-1"><CheckCircle2 className="w-3 h-3" />Done</span>}
          {cancelled && <span className="pill pill-muted">Cancelled</span>}
          {!done && !cancelled && (
            <div className="flex gap-1">
              <Button size="sm" onClick={onDone} data-testid={`event-done-${e.id}`} style={{ background: "var(--brand-primary)", color: "white" }}>
                <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Done
              </Button>
              <Button size="sm" variant="outline" onClick={onDelete} data-testid={`event-delete-${e.id}`}>
                <Trash2 className="w-3.5 h-3.5" style={{ color: "var(--status-danger)" }} />
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function defaultStartEnd() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(10, 0, 0, 0);
  const e = new Date(d.getTime() + 60 * 60 * 1000); // +1h
  const fmt = (x) => {
    const pad = (n) => String(n).padStart(2, "0");
    return `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}T${pad(x.getHours())}:${pad(x.getMinutes())}`;
  };
  return { start: fmt(d), end: fmt(e) };
}

function toLocalInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function EventDialog({ open, existing, onClose, onSaved }) {
  const [title, setTitle] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      if (existing) {
        setTitle(existing.title || "");
        setStartsAt(toLocalInput(existing.scheduled_at));
        const fallbackEnd = existing.ends_at
          || (existing.scheduled_at && existing.duration_minutes
            ? new Date(new Date(existing.scheduled_at).getTime() + (existing.duration_minutes * 60 * 1000)).toISOString()
            : null);
        setEndsAt(toLocalInput(fallbackEnd));
        setLocation(existing.location || "");
        setNotes(existing.notes || "");
      } else {
        const { start, end } = defaultStartEnd();
        setTitle(""); setStartsAt(start); setEndsAt(end); setLocation(""); setNotes("");
      }
    }
  }, [open, existing]);

  // If user picks a new start that's >= current end, push end +1h
  const onStartChange = (v) => {
    setStartsAt(v);
    if (v && endsAt && new Date(v) >= new Date(endsAt)) {
      const e = new Date(new Date(v).getTime() + 60 * 60 * 1000);
      setEndsAt(toLocalInput(e.toISOString()));
    }
  };

  const save = async () => {
    if (!title.trim()) { toast.error("Add a title"); return; }
    if (!startsAt || !endsAt) { toast.error("Pick start and end"); return; }
    if (new Date(endsAt) <= new Date(startsAt)) { toast.error("End must be after start"); return; }
    setBusy(true);
    try {
      const payload = {
        title: title.trim(),
        scheduled_at: new Date(startsAt).toISOString(),
        ends_at: new Date(endsAt).toISOString(),
        location: location.trim() || null,
        notes: notes.trim() || null,
      };
      if (existing) {
        await api.put(`/events/${existing.id}`, payload);
        toast.success("Event updated");
      } else {
        await api.post("/events", payload);
        toast.success("Event added");
      }
      onSaved?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save");
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>{existing ? "Edit event" : "Add event"}</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <div>
            <Label>Title</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Internal training, conference, off-site"
              data-testid="event-title-input" autoFocus className="bg-white" />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <Label>From</Label>
              <Input type="datetime-local" value={startsAt} onChange={(e) => onStartChange(e.target.value)}
                data-testid="event-start-input" className="bg-white" />
            </div>
            <div>
              <Label>To</Label>
              <Input type="datetime-local" value={endsAt} onChange={(e) => setEndsAt(e.target.value)}
                min={startsAt || undefined}
                data-testid="event-end-input" className="bg-white" />
            </div>
          </div>
          <div>
            <Label>Location (optional)</Label>
            <Input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Office, Zoom link, city, address…"
              data-testid="event-location-input" className="bg-white" />
          </div>
          <div>
            <Label>Notes (optional)</Label>
            <Textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)}
              placeholder="Anything you'd like to remember about this event"
              data-testid="event-notes-input" className="bg-white" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={save} disabled={busy || !title.trim() || !startsAt || !endsAt} data-testid="event-save-btn"
            style={{ background: "var(--brand-secondary)", color: "white" }}>
            {busy ? "Saving…" : (existing ? "Save" : "Add event")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
