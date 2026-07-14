import React, { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { StatusPill, sentimentKind, cadenceKind, priorityKind, SegmentBadge } from "../components/StatusPill";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Button } from "../components/ui/button";
import { ArrowLeft, ClipboardList, CalendarClock, CalendarPlus, ScanLine, Brain, MessageSquare, AlertTriangle, MapPin, CheckCircle2, Sprout, Trash2, UserCog } from "lucide-react";
import { toast } from "sonner";

function formatDate(s) {
  if (!s) return "—";
  try { return new Date(s).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }); } catch { return s; }
}
function formatDateTime(s) {
  if (!s) return "—";
  try { return new Date(s).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return s; }
}

export default function DoctorProfile() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [doctor, setDoctor] = useState(null);
  const [visits, setVisits] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [meetings, setMeetings] = useState([]);
  const [prep, setPrep] = useState(null);
  const [loading, setLoading] = useState(true);
  const [teamMembers, setTeamMembers] = useState([]);
  const [reassigning, setReassigning] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [d, v, t, m, p] = await Promise.all([
        api.get(`/doctors/${id}`),
        api.get(`/doctors/${id}/visits`),
        api.get(`/doctors/${id}/tasks`),
        api.get(`/doctors/${id}/meetings`),
        api.get(`/doctors/${id}/prepare`),
      ]);
      setDoctor(d.data);
      setVisits(v.data);
      setTasks(t.data);
      setMeetings(m.data);
      setPrep(p.data);
    } catch (err) {
      toast.error("Doctor not accessible");
      navigate("/doctors");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]);

  useEffect(() => {
    if (user?.role !== "SeniorTM") return;
    api.get("/users").then((r) => {
      const list = (r.data || []).filter((u) => u.role === "TM" || u.id === user.id);
      setTeamMembers(list);
    }).catch(() => {});
  }, [user]);

  const completeTask = async (task) => {
    await api.put(`/tasks/${task.id}`, { status: "Completed" });
    toast.success("Promise completed");
    load();
  };

  const deleteTask = async (task) => {
    if (!window.confirm(`Delete this promise?\n\n"${task.task_title}"`)) return;
    try {
      await api.delete(`/tasks/${task.id}`);
      toast.success("Promise deleted");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to delete");
    }
  };

  const deleteVisit = async (visit) => {
    if (!window.confirm(`Delete this visit${visit.visit_date ? ` from ${formatDate(visit.visit_date)}` : ""}?\n\nThis does not undo any promises or pipeline changes it created.`)) return;
    try {
      await api.delete(`/visits/${visit.id}`);
      toast.success("Visit deleted");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to delete");
    }
  };

  const deleteMeeting = async (meeting) => {
    if (!window.confirm(`Delete this meeting${meeting.subject ? `\n\n"${meeting.subject}"` : ""}?`)) return;
    try {
      await api.delete(`/meetings/${meeting.id}`);
      toast.success("Meeting deleted");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to delete");
    }
  };

  const reassignDoctor = async (targetTmId) => {
    if (!targetTmId || targetTmId === doctor.assigned_tm_id) return;
    setReassigning(true);
    try {
      await api.put(`/doctors/${doctor.id}`, { assigned_tm_id: targetTmId });
      const target = teamMembers.find((m) => m.id === targetTmId);
      toast.success(`Reassigned to ${target?.full_name || "team member"}`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to reassign");
    } finally {
      setReassigning(false);
    }
  };

  const toggleGrowthProgram = async () => {
    const next = !doctor.in_growth_program;
    try {
      await api.put(`/doctors/${doctor.id}`, { in_growth_program: next });
      setDoctor((prev) => ({ ...prev, in_growth_program: next }));
      toast.success(next ? "Added to growth programme — monthly visit target applied" : "Removed from growth programme");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to update");
    }
  };

  if (loading || !doctor) return <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>;

  const openTasks = tasks.filter((t) => t.status === "Open" || t.status === "Overdue");
  const completedTasks = tasks.filter((t) => t.status === "Completed");

  return (
    <div data-testid="doctor-profile-page">
      <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-sm mb-4" style={{ color: "var(--text-secondary)" }} data-testid="back-btn">
        <ArrowLeft className="w-4 h-4" /> Back
      </button>

      <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{doctor.doctor_type} · {doctor.region || "—"}</div>
            <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
              {doctor.doctor_name}
            </h1>
            <div className="mt-1 flex items-center gap-2 text-sm" style={{ color: "var(--text-secondary)" }}>
              <MapPin className="w-4 h-4" /> {doctor.clinic_name || "—"} · {doctor.city || "—"}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <SegmentBadge segment={doctor.segment} />
              <StatusPill kind={priorityKind(doctor.visit_priority_label)}>{doctor.visit_priority_label} priority · {doctor.visit_priority_score}</StatusPill>
              <StatusPill kind={cadenceKind(doctor.cadence_status)}>{doctor.cadence_status}</StatusPill>
              {doctor.current_sentiment && <StatusPill kind={sentimentKind(doctor.current_sentiment)}>{doctor.current_sentiment} ({doctor.sentiment_trend})</StatusPill>}
              {doctor.itero_stage && doctor.itero_stage !== "None" && (
                <Link to="/itero/pipeline" data-testid="itero-stage-pill">
                  <span className={`pill ${doctor.itero_stage === "Contract Signed" ? "pill-success" : doctor.itero_stage === "Lost" ? "pill-muted" : "pill-warning"}`}>
                    iTero: {doctor.itero_stage}
                  </span>
                </Link>
              )}
              {doctor.in_growth_program && (
                <span className="pill pill-success" data-testid="growth-program-pill">
                  <Sprout className="w-3 h-3" /> Growth programme
                </span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => navigate(`/log-visit?doctor=${doctor.id}`)}
              data-testid="log-visit-from-profile-btn"
              style={{ background: "var(--brand-secondary)", color: "white" }}
              className="font-medium"
            >
              <ClipboardList className="w-4 h-4 mr-2" /> Log Visit
            </Button>
            <Button
              onClick={() => navigate(`/meetings/book?doctor_id=${doctor.id}`)}
              data-testid="book-meeting-from-profile-btn"
              variant="outline"
              className="font-medium"
              style={{ borderColor: "var(--brand-primary)", color: "var(--brand-primary)" }}
            >
              <CalendarPlus className="w-4 h-4 mr-2" /> Book meeting
            </Button>
            <Button
              onClick={() => navigate(`/meetings/book?doctor_id=${doctor.id}&demo=1`)}
              data-testid="book-demo-from-profile-btn"
              variant="outline"
              className="font-medium"
              style={{ borderColor: "var(--brand-secondary)", color: "var(--brand-secondary)" }}
            >
              <ScanLine className="w-4 h-4 mr-2" /> Book demo
            </Button>
            <Button
              onClick={toggleGrowthProgram}
              data-testid="toggle-growth-program-btn"
              variant="outline"
              className="font-medium"
              style={{
                borderColor: doctor.in_growth_program ? "var(--status-success)" : "var(--border-default)",
                color: doctor.in_growth_program ? "var(--status-success)" : "var(--text-secondary)",
              }}
            >
              <Sprout className="w-4 h-4 mr-2" /> {doctor.in_growth_program ? "In growth programme" : "Add to growth programme"}
            </Button>
            {user?.role === "SeniorTM" && teamMembers.length > 0 && (
              <Select value={doctor.assigned_tm_id || ""} onValueChange={reassignDoctor} disabled={reassigning}>
                <SelectTrigger
                  data-testid="reassign-doctor-select"
                  className="w-auto bg-white font-medium"
                  style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
                >
                  <UserCog className="w-4 h-4 mr-2" />
                  <SelectValue placeholder="Reassign to…" />
                </SelectTrigger>
                <SelectContent>
                  {teamMembers.map((m) => (
                    <SelectItem key={m.id} value={m.id} data-testid={`reassign-option-${m.id}`}>
                      {m.id === user.id ? `${m.full_name} (me)` : m.full_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mt-6">
          <Stat label="Last visit" value={doctor.days_since_last_visit ? `${doctor.days_since_last_visit}d ago` : "Never"} sub={formatDate(doctor.last_visit_date)} />
          <Stat label="Q visits" value={doctor.visits_this_quarter} sub="last 90 days" />
          <Stat label="Open promises" value={doctor.open_promises} />
          <Stat label="Overdue" value={doctor.overdue_promises} kind={doctor.overdue_promises > 0 ? "danger" : "muted"} />
          <Stat label="Cadence target" value={`${doctor.cadence_target_days}d`} sub={doctor.in_growth_program ? `${doctor.segment} · growth programme` : doctor.segment} />
        </div>
      </div>

      <Tabs defaultValue="prepare" className="space-y-4">
        <TabsList className="bg-[var(--bg-paper)]">
          <TabsTrigger value="prepare" data-testid="tab-prepare"><Brain className="w-4 h-4 mr-1" />Prepare</TabsTrigger>
          <TabsTrigger value="timeline" data-testid="tab-timeline"><MessageSquare className="w-4 h-4 mr-1" />Timeline</TabsTrigger>
          <TabsTrigger value="promises" data-testid="tab-promises"><ClipboardList className="w-4 h-4 mr-1" />Promises ({openTasks.length})</TabsTrigger>
          <TabsTrigger value="meetings" data-testid="tab-meetings"><CalendarPlus className="w-4 h-4 mr-1" />Meetings ({meetings.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="prepare">
          <div className="grid lg:grid-cols-3 gap-5">
            <div className="lg:col-span-2 rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
              <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Suggested reason to visit</div>
              <p className="font-display text-xl font-medium mt-1 mb-4" style={{ color: "var(--brand-primary)" }}>
                {prep?.suggested_reason || "Routine check-in"}
              </p>
              <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Talking points</div>
              <ul className="space-y-2" data-testid="talking-points">
                {(prep?.talking_points || []).map((p, i) => (
                  <li key={i} className="flex gap-2 text-sm">
                    <span className="mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: "var(--brand-secondary)" }} />
                    <span style={{ color: "var(--text-primary)" }}>{p}</span>
                  </li>
                ))}
                {(prep?.talking_points || []).length === 0 && <li className="text-xs" style={{ color: "var(--text-muted)" }}>No talking points yet — log a visit to build memory.</li>}
              </ul>

              <div className="grid sm:grid-cols-2 gap-5 mt-6">
                <div>
                  <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Top topics</div>
                  <div className="flex flex-wrap gap-1.5">
                    {(doctor.top_topics || []).map((t) => <span key={t} className="pill pill-info">{t}</span>)}
                    {(doctor.top_topics || []).length === 0 && <span className="text-xs" style={{ color: "var(--text-muted)" }}>None yet</span>}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Top barriers</div>
                  <div className="flex flex-wrap gap-1.5">
                    {(doctor.top_barriers || []).map((b) => <span key={b} className="pill pill-warning">{b}</span>)}
                    {(doctor.top_barriers || []).length === 0 && <span className="text-xs" style={{ color: "var(--text-muted)" }}>None yet</span>}
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-md border p-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
              <div className="text-xs uppercase tracking-widest mb-3" style={{ color: "var(--text-muted)" }}>Recent visits</div>
              <div className="space-y-3">
                {(prep?.recent_visits || []).map((v) => (
                  <div key={v.id} className="text-sm border-l-2 pl-3" style={{ borderColor: "var(--brand-accent)" }}>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>{formatDate(v.visit_date)} · {v.visit_type}</div>
                    <div className="line-clamp-2" style={{ color: "var(--text-primary)" }}>{v.free_text_note || "(no note)"}</div>
                    {v.next_step && <div className="text-xs italic mt-1" style={{ color: "var(--text-secondary)" }}>→ {v.next_step}</div>}
                  </div>
                ))}
                {(prep?.recent_visits || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>No visits yet.</div>}
              </div>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="timeline">
          <div className="space-y-3" data-testid="visits-timeline">
            {visits.map((v) => (
              <div key={v.id} className="rounded-md border p-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={`visit-${v.id}`}>
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{formatDateTime(v.visit_date)} · {v.visit_type}</div>
                  <div className="flex items-center gap-2">
                    {v.sentiment && <StatusPill kind={sentimentKind(v.sentiment)}>{v.sentiment}</StatusPill>}
                    {v.opportunity_state && <StatusPill kind="muted">{v.opportunity_state}</StatusPill>}
                    <button
                      onClick={() => deleteVisit(v)}
                      data-testid={`delete-visit-${v.id}`}
                      title="Delete visit"
                      className="p-1.5 rounded hover:bg-[var(--bg-paper)]"
                    >
                      <Trash2 className="w-4 h-4" style={{ color: "var(--status-danger)" }} />
                    </button>
                  </div>
                </div>
                <div className="mt-2 text-sm whitespace-pre-wrap" style={{ color: "var(--text-primary)" }}>{v.free_text_note || "(no note)"}</div>
                {(v.confirmed_topics?.length > 0 || v.confirmed_barriers?.length > 0) && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {v.confirmed_topics?.map((t) => <span key={t} className="pill pill-info">{t}</span>)}
                    {v.confirmed_barriers?.map((b) => <span key={b} className="pill pill-warning">{b}</span>)}
                  </div>
                )}
                {v.next_step && (
                  <div className="mt-3 text-xs px-3 py-2 rounded" style={{ background: "var(--bg-paper)", color: "var(--text-secondary)" }}>
                    Next step → {v.next_step}
                  </div>
                )}
              </div>
            ))}
            {visits.length === 0 && <div className="text-sm" style={{ color: "var(--text-muted)" }}>No visits logged yet.</div>}
          </div>
        </TabsContent>

        <TabsContent value="promises">
          <div className="space-y-3">
            {openTasks.map((t) => {
              const overdue = t.status === "Overdue" || (t.due_date && t.due_date < new Date().toISOString().slice(0, 10));
              return (
                <div key={t.id} className="rounded-md border p-4 flex items-start justify-between gap-3" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={`task-${t.id}`}>
                  <div className="min-w-0">
                    <div className="font-medium" style={{ color: "var(--text-primary)" }}>{t.task_title}</div>
                    {t.task_description && <div className="text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>{t.task_description}</div>}
                    <div className="mt-2 flex flex-wrap gap-2">
                      <StatusPill kind={overdue ? "danger" : "info"}><CalendarClock className="w-3 h-3" />Due {formatDate(t.due_date)}</StatusPill>
                      <StatusPill kind={priorityKind(t.priority)}>{t.priority}</StatusPill>
                      {t.created_from_ai && <StatusPill kind="muted"><Brain className="w-3 h-3" />AI</StatusPill>}
                    </div>
                  </div>
                  <div className="flex flex-col gap-2 items-end shrink-0">
                    <Button size="sm" variant="outline" onClick={() => completeTask(t)} data-testid={`complete-task-${t.id}`}>
                      <CheckCircle2 className="w-4 h-4 mr-1" /> Complete
                    </Button>
                    <button
                      onClick={() => deleteTask(t)}
                      data-testid={`delete-task-${t.id}`}
                      title="Delete promise"
                      className="p-1.5 rounded hover:bg-[var(--bg-paper)]"
                    >
                      <Trash2 className="w-4 h-4" style={{ color: "var(--status-danger)" }} />
                    </button>
                  </div>
                </div>
              );
            })}
            {openTasks.length === 0 && <div className="text-sm" style={{ color: "var(--text-muted)" }}>No open promises. ✓</div>}

            {completedTasks.length > 0 && (
              <>
                <div className="text-xs uppercase tracking-widest mt-6 mb-2" style={{ color: "var(--text-muted)" }}>Completed</div>
                {completedTasks.map((t) => (
                  <div key={t.id} className="rounded-md border p-3 flex items-center gap-3" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
                    <CheckCircle2 className="w-4 h-4" style={{ color: "var(--status-success)" }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm line-through" style={{ color: "var(--text-muted)" }}>{t.task_title}</div>
                    </div>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>{formatDate(t.completed_at)}</div>
                    <button
                      onClick={() => deleteTask(t)}
                      data-testid={`delete-task-${t.id}`}
                      title="Delete promise"
                      className="p-1.5 rounded hover:bg-white"
                    >
                      <Trash2 className="w-4 h-4" style={{ color: "var(--status-danger)" }} />
                    </button>
                  </div>
                ))}
              </>
            )}
          </div>
        </TabsContent>

        <TabsContent value="meetings">
          <div className="space-y-3" data-testid="meetings-list">
            {meetings.map((m) => (
              <div key={m.id} className="rounded-md border p-4 flex items-start justify-between gap-3" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={`meeting-${m.id}`}>
                <div className="min-w-0">
                  <div className="font-medium" style={{ color: "var(--text-primary)" }}>{m.subject || (m.is_demo ? "iTero demo" : "Meeting")}</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <StatusPill kind="info"><CalendarClock className="w-3 h-3" />{formatDateTime(m.scheduled_at)}</StatusPill>
                    <StatusPill kind={m.status === "Completed" ? "success" : m.status === "Cancelled" ? "muted" : "info"}>{m.status}</StatusPill>
                    {m.is_demo && <StatusPill kind="muted"><ScanLine className="w-3 h-3" />Demo</StatusPill>}
                  </div>
                </div>
                <button
                  onClick={() => deleteMeeting(m)}
                  data-testid={`delete-meeting-${m.id}`}
                  title="Delete meeting"
                  className="p-1.5 rounded hover:bg-[var(--bg-paper)] shrink-0"
                >
                  <Trash2 className="w-4 h-4" style={{ color: "var(--status-danger)" }} />
                </button>
              </div>
            ))}
            {meetings.length === 0 && <div className="text-sm" style={{ color: "var(--text-muted)" }}>No meetings booked.</div>}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Stat({ label, value, sub, kind = "muted" }) {
  const fg = kind === "danger" ? "var(--status-danger)" : "var(--brand-primary)";
  return (
    <div>
      <div className="text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="font-display text-2xl font-medium" style={{ color: fg }}>{value}</div>
      {sub && <div className="text-xs" style={{ color: "var(--text-muted)" }}>{sub}</div>}
    </div>
  );
}
