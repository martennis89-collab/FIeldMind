import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import QuickCaptureDialog from "../components/QuickCaptureDialog";
import {
  ChevronLeft, ChevronRight, CalendarDays, Rows3, ClipboardList, CalendarPlus,
  Clock, MapPin, CheckCircle2, XCircle, ExternalLink,
} from "lucide-react";

// ---------- Date helpers ----------
const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const startOfMonth = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
const endOfMonth = (d) => new Date(d.getFullYear(), d.getMonth() + 1, 0);
const startOfWeek = (d) => {
  const day = d.getDay(); // 0 = Sun
  const dow = day === 0 ? 6 : day - 1; // Monday-first
  const out = new Date(d);
  out.setDate(d.getDate() - dow);
  out.setHours(0, 0, 0, 0);
  return out;
};
const addDays = (d, n) => { const out = new Date(d); out.setDate(out.getDate() + n); return out; };
const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
const fmtMonthYear = (d) => d.toLocaleString(undefined, { month: "long", year: "numeric" });
const fmtWeekRange = (start) => {
  const end = addDays(start, 6);
  const sameMonth = start.getMonth() === end.getMonth();
  const s = start.toLocaleString(undefined, { month: "short", day: "numeric" });
  const e = end.toLocaleString(undefined, { month: sameMonth ? undefined : "short", day: "numeric", year: "numeric" });
  return `${s} – ${e}`;
};
const fmtHM = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { hour: "numeric", minute: "2-digit" });
};

// A promise's due_date is a bare "YYYY-MM-DD". new Date("2026-07-28") parses
// as UTC midnight, which lands on the PREVIOUS day for any negative-offset
// timezone — filing the promise under the wrong calendar day. Build it from
// parts so it's local midnight instead.
const parseDateOnly = (s) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};

// ---------- Item extraction ----------
// Convert a meeting / event / visit doc to a common shape.
function toItem(doc, kind, doctorNames = {}) {
  const iso =
    kind === "visit" ? doc.visit_date :
    kind === "promise" ? doc.due_date :
    doc.scheduled_at;
  if (!iso) return null;
  // Promises are date-only (no clock time); everything else is a full datetime.
  const isPromise = kind === "promise";
  const startDate = isPromise ? parseDateOnly(iso) : new Date(iso);
  if (Number.isNaN(startDate.getTime())) return null;
  const isDemo = kind === "meeting" && !!doc.is_demo;
  const promiseDoctor = isPromise && doc.doctor_id ? doctorNames[doc.doctor_id] : null;
  const label =
    kind === "visit" ? (doc.doctor_name || "Visit") :
    kind === "event" ? (doc.title || doc.subject || "Event") :
    isPromise ? (promiseDoctor ? `${promiseDoctor}: ${doc.task_title}` : doc.task_title || "Promise") :
    isDemo ? `iTero · ${doc.doctor_name || "Demo"}` :
    (doc.doctor_name || doc.subject || "Meeting");
  return {
    id: `${kind}-${doc.id}`,
    kind,
    doc,
    startDate,
    iso,
    dayKey: ymd(startDate),
    label,
    isDemo,
    isPromise,
    href:
      isPromise ? "/tasks" :
      kind === "visit" || kind === "meeting"
        ? (doc.doctor_id ? `/doctors/${doc.doctor_id}` : "/meetings")
        : "/meetings",
  };
}

const KIND_STYLE = {
  meeting: { bg: "var(--brand-secondary)", fg: "white", label: "Meeting" },
  demo:    { bg: "#A8542F", fg: "white", label: "iTero" },
  event:   { bg: "var(--brand-primary)", fg: "white", label: "Event" },
  visit:   { bg: "var(--status-success)", fg: "white", label: "Visit" },
  promise: { bg: "var(--status-warning)", fg: "white", label: "Promise" },
};

function styleFor(item) {
  if (item.kind === "meeting" && item.isDemo) return KIND_STYLE.demo;
  return KIND_STYLE[item.kind];
}

// Promises have no clock time — showing "12:00 AM" would be misleading.
const timeLabel = (item) => (item.isPromise ? "Due" : fmtHM(item.iso));

export default function CalendarPage() {
  const [view, setView] = useState("month"); // "month" | "week"
  const [cursor, setCursor] = useState(() => { const n = new Date(); n.setHours(0, 0, 0, 0); return n; });
  const [meetings, setMeetings] = useState([]);
  const [events, setEvents] = useState([]);
  const [visits, setVisits] = useState([]);
  const [promises, setPromises] = useState([]);
  const [doctorNames, setDoctorNames] = useState({});
  const [loading, setLoading] = useState(true);
  const [selectedDay, setSelectedDay] = useState(null);
  const [selectedMeeting, setSelectedMeeting] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [m, e, v, t, d] = await Promise.all([
        api.get("/meetings", { params: { when: "all" } }),
        api.get("/events",   { params: { when: "all" } }),
        api.get("/visits"),
        // Open + overdue promises only — completed ones would just clutter
        // the calendar with work that's already done.
        api.get("/tasks", { params: { bucket: "open" } }),
        api.get("/doctors"),
      ]);
      setMeetings(m.data || []);
      setEvents(e.data || []);
      setVisits(v.data || []);
      setPromises(t.data || []);
      const docs = Array.isArray(d.data) ? d.data : (d.data?.doctors || []);
      setDoctorNames(Object.fromEntries(docs.map((x) => [x.id, x.doctor_name])));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const items = useMemo(() => {
    const out = [];
    for (const x of meetings) { const it = toItem(x, "meeting"); if (it) out.push(it); }
    for (const x of events) { const it = toItem(x, "event"); if (it) out.push(it); }
    for (const x of visits) { const it = toItem(x, "visit"); if (it) out.push(it); }
    for (const x of promises) { const it = toItem(x, "promise", doctorNames); if (it) out.push(it); }
    // Sort within a day by real start time. Promises are date-only, so sort
    // them first — comparing a bare "YYYY-MM-DD" against a full ISO datetime
    // lexicographically would otherwise scatter them unpredictably.
    out.sort((a, b) => (a.dayKey.localeCompare(b.dayKey)) || (a.startDate - b.startDate));
    return out;
  }, [meetings, events, visits, promises, doctorNames]);

  const byDay = useMemo(() => {
    const g = new Map();
    for (const it of items) {
      const arr = g.get(it.dayKey) || [];
      arr.push(it);
      g.set(it.dayKey, arr);
    }
    return g;
  }, [items]);

  const selectedDayItems = useMemo(
    () => (selectedDay ? (byDay.get(ymd(selectedDay)) || []) : []),
    [selectedDay, byDay]
  );

  const shiftCursor = (dir) => {
    setCursor((prev) => {
      const next = new Date(prev);
      if (view === "month") next.setMonth(prev.getMonth() + dir);
      else next.setDate(prev.getDate() + 7 * dir);
      return next;
    });
  };
  const goToday = () => { const n = new Date(); n.setHours(0, 0, 0, 0); setCursor(n); };

  return (
    <div data-testid="calendar-page">
      <div className="flex items-baseline justify-between gap-4 flex-wrap mb-5">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Field calendar</div>
          <h1 className="font-display text-3xl sm:text-4xl font-light" style={{ color: "var(--brand-primary)" }}>
            {view === "month" ? fmtMonthYear(cursor) : fmtWeekRange(startOfWeek(cursor))}
          </h1>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="inline-flex rounded-md border overflow-hidden" style={{ borderColor: "var(--border-default)" }} data-testid="view-toggle">
            <button onClick={() => setView("month")} data-testid="view-month-btn"
                    className="px-3 py-1.5 text-sm inline-flex items-center gap-1"
                    style={{ background: view === "month" ? "var(--brand-primary)" : "transparent", color: view === "month" ? "white" : "var(--text-secondary)" }}>
              <CalendarDays className="w-3.5 h-3.5" /> Month
            </button>
            <button onClick={() => setView("week")} data-testid="view-week-btn"
                    className="px-3 py-1.5 text-sm inline-flex items-center gap-1"
                    style={{ background: view === "week" ? "var(--brand-primary)" : "transparent", color: view === "week" ? "white" : "var(--text-secondary)" }}>
              <Rows3 className="w-3.5 h-3.5" /> Week
            </button>
          </div>
          <div className="inline-flex items-center gap-1">
            <Button variant="outline" size="sm" onClick={() => shiftCursor(-1)} data-testid="cal-prev-btn"><ChevronLeft className="w-4 h-4" /></Button>
            <Button variant="outline" size="sm" onClick={goToday} data-testid="cal-today-btn">Today</Button>
            <Button variant="outline" size="sm" onClick={() => shiftCursor(1)} data-testid="cal-next-btn"><ChevronRight className="w-4 h-4" /></Button>
          </div>
          <Link to="/log-visit"><Button size="sm" variant="outline" data-testid="cal-log-visit-btn"><ClipboardList className="w-3.5 h-3.5 mr-1" /> Log visit</Button></Link>
          <Link to="/meetings/book"><Button size="sm" data-testid="cal-book-meeting-btn" style={{ background: "var(--brand-secondary)", color: "white" }}>
            <CalendarPlus className="w-3.5 h-3.5 mr-1" /> Book meeting
          </Button></Link>
        </div>
      </div>

      <Legend />

      {loading ? (
        <div className="text-sm py-8 text-center" style={{ color: "var(--text-muted)" }} data-testid="cal-loading">Loading calendar…</div>
      ) : view === "month" ? (
        <MonthGrid cursor={cursor} byDay={byDay} onDayClick={setSelectedDay} onMeetingClick={setSelectedMeeting} />
      ) : (
        <WeekGrid cursor={cursor} byDay={byDay} onDayClick={setSelectedDay} onMeetingClick={setSelectedMeeting} />
      )}

      <DayModal
        date={selectedDay}
        items={selectedDayItems}
        onClose={() => setSelectedDay(null)}
        onMeetingClick={setSelectedMeeting}
      />

      <MeetingDetailModal
        meeting={selectedMeeting}
        onClose={() => setSelectedMeeting(null)}
        onChanged={load}
      />
    </div>
  );
}

// ---------- Day detail modal ----------
function DayModal({ date, items, onClose, onMeetingClick }) {
  const dateLabel = date
    ? date.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" })
    : "";
  return (
    <Dialog open={!!date} onOpenChange={(v) => !v && onClose()}>
      <DialogContent data-testid="cal-day-modal">
        <DialogHeader><DialogTitle>{dateLabel}</DialogTitle></DialogHeader>
        {items.length === 0 ? (
          <div className="text-sm py-6 text-center" style={{ color: "var(--text-muted)" }}>
            Nothing scheduled this day.
          </div>
        ) : (
          <div className="flex flex-col gap-2 max-h-[60vh] overflow-y-auto" data-testid="cal-day-modal-list">
            {items.map((it) => {
              const s = styleFor(it);
              const inner = (
                <>
                  <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: s.bg }} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>{it.label}</div>
                    <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>{timeLabel(it)} · {s.label}</div>
                  </div>
                </>
              );
              const rowClass = "flex items-center gap-3 rounded-md border p-2.5 hover:bg-[var(--bg-paper)] transition-colors text-left";
              return it.kind === "meeting" ? (
                <button
                  key={it.id}
                  type="button"
                  onClick={() => { onMeetingClick(it.doc); onClose(); }}
                  data-testid={`cal-day-modal-item-${it.id}`}
                  className={rowClass}
                  style={{ borderColor: "var(--border-default)" }}
                >
                  {inner}
                </button>
              ) : (
                <Link
                  key={it.id}
                  to={it.href}
                  onClick={onClose}
                  data-testid={`cal-day-modal-item-${it.id}`}
                  className={rowClass}
                  style={{ borderColor: "var(--border-default)" }}
                >
                  {inner}
                </Link>
              );
            })}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ---------- Meeting detail modal ----------
function MeetingDetailModal({ meeting, onClose, onChanged }) {
  const [completing, setCompleting] = useState(false);
  const isDemo = !!meeting?.is_demo;
  const completed = meeting?.status === "Completed";
  const cancelled = meeting?.status === "Cancelled";

  const handleClose = () => { setCompleting(false); onClose(); };

  return (
    <>
      <Dialog open={!!meeting && !completing} onOpenChange={(v) => !v && handleClose()}>
        <DialogContent data-testid="cal-meeting-modal">
          {meeting && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  {isDemo ? "iTero demo" : "Meeting"} — {meeting.doctor_name}
                </DialogTitle>
              </DialogHeader>
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                  <Clock className="w-3.5 h-3.5" />
                  {new Date(meeting.scheduled_at).toLocaleString(undefined, {
                    weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
                  })}
                  {meeting.duration_minutes ? ` · ${meeting.duration_minutes} min` : ""}
                </div>
                {(meeting.clinic_name || meeting.city) && (
                  <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                    <MapPin className="w-3.5 h-3.5" />
                    {[meeting.clinic_name, meeting.city].filter(Boolean).join(" · ")}
                  </div>
                )}
                {meeting.subject && (
                  <div className="text-sm" style={{ color: "var(--text-primary)" }}>{meeting.subject}</div>
                )}
                <div>
                  {completed && <span className="pill pill-success inline-flex items-center gap-1"><CheckCircle2 className="w-3 h-3" />Completed</span>}
                  {cancelled && <span className="pill pill-muted inline-flex items-center gap-1"><XCircle className="w-3 h-3" />Cancelled</span>}
                  {!completed && !cancelled && <span className="pill">Scheduled</span>}
                </div>
              </div>
              <DialogFooter className="flex-wrap gap-2 sm:justify-between">
                <Link
                  to={`/doctors/${meeting.doctor_id}`}
                  onClick={handleClose}
                  data-testid="cal-meeting-view-doctor"
                  className="text-sm inline-flex items-center gap-1 hover:underline"
                  style={{ color: "var(--brand-primary)" }}
                >
                  <ExternalLink className="w-3.5 h-3.5" /> View doctor profile
                </Link>
                {!completed && !cancelled && (
                  <Button
                    onClick={() => setCompleting(true)}
                    data-testid="cal-meeting-complete-btn"
                    style={{ background: "var(--status-success)", color: "white" }}
                  >
                    <CheckCircle2 className="w-4 h-4 mr-1" /> Complete meeting
                  </Button>
                )}
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <QuickCaptureDialog
        open={completing}
        meetingId={meeting?.id}
        defaultDoctorId={meeting?.doctor_id}
        onClose={() => setCompleting(false)}
        onCreated={() => { setCompleting(false); onChanged?.(); handleClose(); }}
      />
    </>
  );
}

function Legend() {
  const items = [
    { k: "meeting", label: "Meeting" },
    { k: "demo", label: "iTero demo" },
    { k: "event", label: "Event" },
    { k: "visit", label: "Logged visit" },
    { k: "promise", label: "Promise due" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-3 mb-3 text-xs" data-testid="cal-legend" style={{ color: "var(--text-muted)" }}>
      {items.map((i) => (
        <span key={i.k} className="inline-flex items-center gap-1.5">
          <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: KIND_STYLE[i.k].bg }} /> {i.label}
        </span>
      ))}
    </div>
  );
}

// ---------- Month view ----------
function MonthGrid({ cursor, byDay, onDayClick, onMeetingClick }) {
  const first = startOfMonth(cursor);
  const gridStart = startOfWeek(first);
  const days = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
  const monthIdx = cursor.getMonth();
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const dowLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  return (
    <div className="rounded-md border overflow-hidden" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }} data-testid="cal-month-grid">
      <div className="grid grid-cols-7 text-[11px] uppercase tracking-widest font-medium" style={{ background: "var(--bg-paper)", color: "var(--text-muted)" }}>
        {dowLabels.map((d) => <div key={d} className="px-2 py-2">{d}</div>)}
      </div>
      <div className="grid grid-cols-7">
        {days.map((d) => {
          const key = ymd(d);
          const inMonth = d.getMonth() === monthIdx;
          const isToday = sameDay(d, today);
          const list = byDay.get(key) || [];
          return (
            <div key={key}
                 data-testid={`cal-day-${key}`}
                 onClick={() => onDayClick(d)}
                 onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onDayClick(d); } }}
                 role="button"
                 tabIndex={0}
                 className="min-h-[110px] border-t border-r p-1.5 flex flex-col gap-1 cursor-pointer"
                 style={{
                   borderColor: "var(--border-default)",
                   background: inMonth ? "var(--bg-default)" : "var(--bg-paper)",
                   opacity: inMonth ? 1 : 0.55,
                 }}>
              <div className="flex items-center justify-between">
                <span className={`text-xs font-medium ${isToday ? "px-1.5 rounded-full" : ""}`}
                      style={{ color: isToday ? "white" : "var(--text-secondary)", background: isToday ? "var(--brand-secondary)" : "transparent" }}>
                  {d.getDate()}
                </span>
                {list.length > 3 && <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>+{list.length - 3}</span>}
              </div>
              <div className="flex flex-col gap-0.5 overflow-hidden">
                {list.slice(0, 3).map((it) => <EventPill key={it.id} item={it} onMeetingClick={onMeetingClick} />)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------- Week view ----------
function WeekGrid({ cursor, byDay, onDayClick, onMeetingClick }) {
  const start = startOfWeek(cursor);
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return (
    <div className="grid grid-cols-1 md:grid-cols-7 gap-2" data-testid="cal-week-grid">
      {days.map((d) => {
        const key = ymd(d);
        const isToday = sameDay(d, today);
        const list = byDay.get(key) || [];
        return (
          <div key={key} data-testid={`cal-day-${key}`}
               onClick={() => onDayClick(d)}
               onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onDayClick(d); } }}
               role="button"
               tabIndex={0}
               className="rounded-md border p-2 min-h-[220px] flex flex-col cursor-pointer"
               style={{
                 background: "var(--bg-default)",
                 borderColor: isToday ? "var(--brand-secondary)" : "var(--border-default)",
                 borderWidth: isToday ? 2 : 1,
               }}>
            <div className="flex items-baseline justify-between mb-2">
              <div className="text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
                {d.toLocaleString(undefined, { weekday: "short" })}
              </div>
              <div className={`text-lg font-semibold ${isToday ? "px-2 rounded-full" : ""}`}
                   style={{ color: isToday ? "white" : "var(--brand-primary)", background: isToday ? "var(--brand-secondary)" : "transparent" }}>
                {d.getDate()}
              </div>
            </div>
            <div className="flex flex-col gap-1 overflow-hidden">
              {list.length === 0 ? (
                <div className="text-[11px] italic" style={{ color: "var(--text-muted)" }}>—</div>
              ) : (
                list.map((it) => <EventBlock key={it.id} item={it} onMeetingClick={onMeetingClick} />)
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------- Row-shape event pill (month view) ----------
function EventPill({ item, onMeetingClick }) {
  const s = styleFor(item);
  if (item.kind === "meeting") {
    return (
      <button type="button"
              onClick={(e) => { e.stopPropagation(); onMeetingClick(item.doc); }}
              data-testid={`cal-item-${item.id}`}
              className="text-[10px] truncate rounded px-1.5 py-0.5 leading-tight hover:opacity-90 text-left"
              style={{ background: s.bg, color: s.fg }}
              title={`${timeLabel(item)} · ${item.label}`}>
        <span className="opacity-75 mr-1">{timeLabel(item)}</span>{item.label}
      </button>
    );
  }
  return (
    <Link to={item.href}
          onClick={(e) => e.stopPropagation()}
          data-testid={`cal-item-${item.id}`}
          className="text-[10px] truncate rounded px-1.5 py-0.5 leading-tight hover:opacity-90"
          style={{ background: s.bg, color: s.fg }}
          title={`${timeLabel(item)} · ${item.label}`}>
      <span className="opacity-75 mr-1">{timeLabel(item)}</span>{item.label}
    </Link>
  );
}

// ---------- Row-shape event block (week view — a bit taller) ----------
function EventBlock({ item, onMeetingClick }) {
  const s = styleFor(item);
  const inner = (
    <>
      <div className="opacity-80 text-[10px] mb-0.5">{timeLabel(item)} · {s.label}</div>
      <div className="font-medium truncate">{item.label}</div>
    </>
  );
  if (item.kind === "meeting") {
    return (
      <button type="button"
              onClick={(e) => { e.stopPropagation(); onMeetingClick(item.doc); }}
              data-testid={`cal-item-${item.id}`}
              className="rounded px-2 py-1 text-xs leading-tight hover:opacity-90 text-left w-full"
              style={{ background: s.bg, color: s.fg }}>
        {inner}
      </button>
    );
  }
  return (
    <Link to={item.href}
          onClick={(e) => e.stopPropagation()}
          data-testid={`cal-item-${item.id}`}
          className="rounded px-2 py-1 text-xs leading-tight hover:opacity-90"
          style={{ background: s.bg, color: s.fg }}>
      {inner}
    </Link>
  );
}
