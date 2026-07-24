import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { ChevronLeft, ChevronRight, CalendarDays, Rows3, ClipboardList, CalendarPlus } from "lucide-react";

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

// ---------- Item extraction ----------
// Convert a meeting / event / visit doc to a common shape.
function toItem(doc, kind) {
  const iso = kind === "visit" ? doc.visit_date : doc.scheduled_at;
  if (!iso) return null;
  const startDate = new Date(iso);
  const isDemo = kind === "meeting" && !!doc.is_demo;
  const label =
    kind === "visit" ? (doc.doctor_name || "Visit") :
    kind === "event" ? (doc.title || doc.subject || "Event") :
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
    href: kind === "visit" || kind === "meeting"
      ? (doc.doctor_id ? `/doctors/${doc.doctor_id}` : "/meetings")
      : "/meetings",
  };
}

const KIND_STYLE = {
  meeting: { bg: "var(--brand-secondary)", fg: "white", label: "Meeting" },
  demo:    { bg: "#A8542F", fg: "white", label: "iTero" },
  event:   { bg: "var(--brand-primary)", fg: "white", label: "Event" },
  visit:   { bg: "var(--status-success)", fg: "white", label: "Visit" },
};

function styleFor(item) {
  if (item.kind === "meeting" && item.isDemo) return KIND_STYLE.demo;
  return KIND_STYLE[item.kind];
}

export default function CalendarPage() {
  const [view, setView] = useState("month"); // "month" | "week"
  const [cursor, setCursor] = useState(() => { const n = new Date(); n.setHours(0, 0, 0, 0); return n; });
  const [meetings, setMeetings] = useState([]);
  const [events, setEvents] = useState([]);
  const [visits, setVisits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedDay, setSelectedDay] = useState(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [m, e, v] = await Promise.all([
          api.get("/meetings", { params: { when: "all" } }),
          api.get("/events",   { params: { when: "all" } }),
          api.get("/visits"),
        ]);
        setMeetings(m.data || []);
        setEvents(e.data || []);
        setVisits(v.data || []);
      } finally { setLoading(false); }
    })();
  }, []);

  const items = useMemo(() => {
    const out = [];
    for (const x of meetings) { const it = toItem(x, "meeting"); if (it) out.push(it); }
    for (const x of events) { const it = toItem(x, "event"); if (it) out.push(it); }
    for (const x of visits) { const it = toItem(x, "visit"); if (it) out.push(it); }
    out.sort((a, b) => a.iso.localeCompare(b.iso));
    return out;
  }, [meetings, events, visits]);

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
        <MonthGrid cursor={cursor} byDay={byDay} onDayClick={setSelectedDay} />
      ) : (
        <WeekGrid cursor={cursor} byDay={byDay} onDayClick={setSelectedDay} />
      )}

      <DayModal date={selectedDay} items={selectedDayItems} onClose={() => setSelectedDay(null)} />
    </div>
  );
}

// ---------- Day detail modal ----------
function DayModal({ date, items, onClose }) {
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
              return (
                <Link
                  key={it.id}
                  to={it.href}
                  onClick={onClose}
                  data-testid={`cal-day-modal-item-${it.id}`}
                  className="flex items-center gap-3 rounded-md border p-2.5 hover:bg-[var(--bg-paper)] transition-colors"
                  style={{ borderColor: "var(--border-default)" }}
                >
                  <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: s.bg }} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>{it.label}</div>
                    <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>{fmtHM(it.iso)} · {s.label}</div>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Legend() {
  const items = [
    { k: "meeting", label: "Meeting" },
    { k: "demo", label: "iTero demo" },
    { k: "event", label: "Event" },
    { k: "visit", label: "Logged visit" },
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
function MonthGrid({ cursor, byDay, onDayClick }) {
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
                {list.slice(0, 3).map((it) => <EventPill key={it.id} item={it} />)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------- Week view ----------
function WeekGrid({ cursor, byDay, onDayClick }) {
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
                list.map((it) => <EventBlock key={it.id} item={it} />)
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------- Row-shape event pill (month view) ----------
function EventPill({ item }) {
  const s = styleFor(item);
  return (
    <Link to={item.href}
          onClick={(e) => e.stopPropagation()}
          data-testid={`cal-item-${item.id}`}
          className="text-[10px] truncate rounded px-1.5 py-0.5 leading-tight hover:opacity-90"
          style={{ background: s.bg, color: s.fg }}
          title={`${fmtHM(item.iso)} · ${item.label}`}>
      <span className="opacity-75 mr-1">{fmtHM(item.iso)}</span>{item.label}
    </Link>
  );
}

// ---------- Row-shape event block (week view — a bit taller) ----------
function EventBlock({ item }) {
  const s = styleFor(item);
  return (
    <Link to={item.href}
          onClick={(e) => e.stopPropagation()}
          data-testid={`cal-item-${item.id}`}
          className="rounded px-2 py-1 text-xs leading-tight hover:opacity-90"
          style={{ background: s.bg, color: s.fg }}>
      <div className="opacity-80 text-[10px] mb-0.5">{fmtHM(item.iso)} · {s.label}</div>
      <div className="font-medium truncate">{item.label}</div>
    </Link>
  );
}
