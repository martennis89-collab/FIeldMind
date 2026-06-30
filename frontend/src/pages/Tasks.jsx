import React, { useEffect, useMemo, useState } from "react";
import api from "../lib/api";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { StatusPill, priorityKind } from "../components/StatusPill";
import { CalendarClock, CheckCircle2, AlertTriangle, Brain, Clock, Pencil, Trash2, Undo2, Plus, Wand2, UserPlus, Search as SearchIcon } from "lucide-react";
import { toast } from "sonner";
import QuickCaptureDialog from "../components/QuickCaptureDialog";
import InlineAddDoctor from "../components/InlineAddDoctor";

const KINDS = [
  { key: "open", label: "Open" },
  { key: "completed", label: "Completed" },
];

function fmtDate(s) {
  if (!s) return "—";
  try { return new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric" }); } catch { return s; }
}
function fmtDateTime(s) {
  if (!s) return "—";
  try { return new Date(s).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return s; }
}
function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function Tasks() {
  const [kind, setKind] = useState("open");
  const [open, setOpen] = useState([]);     // open + overdue
  const [completed, setCompleted] = useState([]);
  const [doctors, setDoctors] = useState({});
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [creating, setCreating] = useState(false);
  const [quickCapture, setQuickCapture] = useState(false);
  const [allDoctors, setAllDoctors] = useState([]);
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    if (searchParams.get("new") === "1") {
      setCreating(true);
      // Strip the param so reopening tabs doesn't keep popping the dialog
      const sp = new URLSearchParams(searchParams);
      sp.delete("new");
      setSearchParams(sp, { replace: true });
    }
  }, []);

  // OPTIMISTIC HELPERS
  const moveToCompleted = (id) => {
    let moved = null;
    setOpen((prev) => {
      const idx = prev.findIndex((t) => t.id === id);
      if (idx >= 0) {
        moved = { ...prev[idx], status: "Completed", completed_at: new Date().toISOString() };
        return prev.slice(0, idx).concat(prev.slice(idx + 1));
      }
      return prev;
    });
    if (moved) setCompleted((prev) => [moved, ...prev]);
  };
  const moveToOpen = (id) => {
    let moved = null;
    setCompleted((prev) => {
      const idx = prev.findIndex((t) => t.id === id);
      if (idx >= 0) {
        moved = { ...prev[idx], status: "Open", completed_at: null };
        return prev.slice(0, idx).concat(prev.slice(idx + 1));
      }
      return prev;
    });
    if (moved) setOpen((prev) => [moved, ...prev]);
  };

  const fetchDoctorsFor = async (lists) => {
    const ids = Array.from(new Set(lists.flat().map((t) => t.doctor_id)));
    const map = { ...doctors };
    const missing = ids.filter((id) => id && !map[id]);
    await Promise.all(missing.map(async (id) => {
      try { const r = await api.get(`/doctors/${id}`); map[id] = r.data; } catch {/* ignore */}
    }));
    setDoctors(map);
  };

  const load = async () => {
    setLoading(true);
    try {
      const [a, b] = await Promise.all([
        api.get("/tasks", { params: { bucket: "open" } }),
        api.get("/tasks", { params: { bucket: "completed" } }),
      ]);
      setOpen(a.data || []);
      setCompleted(b.data || []);
      fetchDoctorsFor([a.data || [], b.data || []]);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    api.get("/doctors").then((r) => setAllDoctors(Array.isArray(r.data) ? r.data : (r.data.doctors || []))).catch(() => {});
  }, []);

  const list = kind === "open" ? open : completed;

  // Sort: overdue first, then by due date asc; completed = newest first
  const sorted = useMemo(() => {
    const today = todayISO();
    if (kind === "open") {
      return [...list].sort((a, b) => {
        const aOver = a.due_date && a.due_date < today;
        const bOver = b.due_date && b.due_date < today;
        if (aOver !== bOver) return aOver ? -1 : 1;
        return (a.due_date || "9999").localeCompare(b.due_date || "9999");
      });
    }
    return [...list].sort((a, b) => (b.completed_at || "").localeCompare(a.completed_at || ""));
  }, [list, kind]);

  const complete = async (t) => {
    moveToCompleted(t.id);
    try {
      await api.put(`/tasks/${t.id}`, { status: "Completed" });
      toast.success("Marked complete");
    } catch {
      // rollback
      moveToOpen(t.id);
      toast.error("Could not complete");
    }
  };
  const reopen = async (t) => {
    moveToOpen(t.id);
    try {
      await api.put(`/tasks/${t.id}`, { status: "Open" });
      toast.success("Reopened");
    } catch {
      moveToCompleted(t.id);
      toast.error("Could not reopen");
    }
  };
  const remove = async (t) => {
    if (!window.confirm(`Delete this task?\n\n"${t.task_title}"\n\nThis can be reviewed in the audit log later.`)) return;
    // optimistic
    if (t.status === "Completed") setCompleted((p) => p.filter((x) => x.id !== t.id));
    else setOpen((p) => p.filter((x) => x.id !== t.id));
    try {
      await api.delete(`/tasks/${t.id}`);
      toast.success("Task deleted");
    } catch {
      // rollback by full reload
      load();
      toast.error("Could not delete");
    }
  };

  return (
    <div data-testid="tasks-page">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Promises & follow-ups</div>
          <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Things you <span className="font-medium">owe.</span>
          </h1>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button
            onClick={() => setQuickCapture(true)}
            data-testid="quick-capture-btn"
            variant="outline"
            style={{ borderColor: "var(--brand-primary)", color: "var(--brand-primary)" }}
          >
            <Wand2 className="w-4 h-4 mr-1" /> Quick capture
          </Button>
          <Button
            onClick={() => setCreating(true)}
            data-testid="new-task-btn"
            style={{ background: "var(--brand-secondary)", color: "white" }}
          >
            <Plus className="w-4 h-4 mr-1" /> New task
          </Button>
        </div>
      </div>

      {/* Open / Completed toggle */}
      <div className="flex gap-1 rounded-full p-1 mb-5 w-fit" style={{ background: "var(--bg-paper)" }} data-testid="tasks-kind-toggle">
        {KINDS.map((k) => {
          const count = k.key === "open" ? open.length : completed.length;
          const active = kind === k.key;
          return (
            <button
              key={k.key}
              type="button"
              onClick={() => setKind(k.key)}
              data-testid={`tasks-tab-${k.key}`}
              className="px-4 py-1.5 text-sm rounded-full transition-all"
              style={{
                background: active ? "var(--brand-primary)" : "transparent",
                color: active ? "white" : "var(--text-secondary)",
                fontWeight: active ? 500 : 400,
              }}
            >
              {k.label} <span className="ml-1.5 text-xs opacity-80">{count}</span>
            </button>
          );
        })}
      </div>

      {loading ? (
        <div className="text-sm py-12 text-center" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : sorted.length === 0 ? (
        <div className="rounded-md border p-10 text-center" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }} data-testid="tasks-empty">
          <CheckCircle2 className="w-8 h-8 mx-auto mb-2" style={{ color: "var(--text-muted)" }} />
          <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {kind === "open" ? "Nothing on the runway. Log a visit to capture promises." : "No completed tasks yet."}
          </div>
        </div>
      ) : (
        <div className="space-y-3" data-testid="tasks-list">
          {sorted.map((t, i) => (
            <TaskRow
              key={t.id}
              task={t}
              doctor={doctors[t.doctor_id]}
              index={i}
              onComplete={() => complete(t)}
              onReopen={() => reopen(t)}
              onEdit={() => setEditing(t)}
              onDelete={() => remove(t)}
            />
          ))}
        </div>
      )}

      <EditTaskDialog
        open={!!editing}
        task={editing}
        onClose={() => setEditing(null)}
        onSaved={(updated) => {
          // patch in place
          const patch = (arr) => arr.map((x) => (x.id === updated.id ? { ...x, ...updated } : x));
          setOpen((p) => patch(p));
          setCompleted((p) => patch(p));
        }}
      />

      <NewTaskDialog
        open={creating}
        doctors={allDoctors}
        onClose={() => setCreating(false)}
        onDoctorAdded={(d) => setAllDoctors((prev) => [d, ...prev])}
        onCreated={(t, doctor) => {
          // optimistic insert into open list and doctor cache
          setOpen((prev) => [t, ...prev]);
          if (doctor) setDoctors((m) => ({ ...m, [doctor.id]: doctor }));
        }}
      />

      <QuickCaptureDialog
        open={quickCapture}
        onClose={() => setQuickCapture(false)}
        onCreated={() => { setQuickCapture(false); load(); }}
      />
    </div>
  );
}

function TaskRow({ task: t, doctor, index, onComplete, onReopen, onEdit, onDelete }) {
  const today = todayISO();
  const overdue = t.status !== "Completed" && t.due_date && t.due_date < today;
  const completed = t.status === "Completed";
  const bg = completed
    ? "linear-gradient(0deg, var(--status-success-bg), var(--status-success-bg))"
    : overdue
      ? "linear-gradient(0deg, var(--status-danger-bg), var(--status-danger-bg))"
      : "var(--bg-default)";
  const borderColor = completed ? "var(--status-success)" : overdue ? "var(--status-danger)" : "var(--border-default)";
  return (
    <div
      data-testid={`task-row-${t.id}`}
      className="rounded-md border p-4 flex items-start gap-3 fade-up transition-all"
      style={{ background: bg, borderColor, borderLeftWidth: "3px", animationDelay: `${index * 18}ms` }}
    >
      <div className="mt-0.5">
        {completed ? (
          <CheckCircle2 className="w-5 h-5" style={{ color: "var(--status-success)" }} />
        ) : overdue ? (
          <AlertTriangle className="w-5 h-5" style={{ color: "var(--status-danger)" }} />
        ) : (
          <Clock className="w-5 h-5" style={{ color: "var(--status-info)" }} />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium" style={{ color: "var(--text-primary)", textDecoration: completed ? "line-through" : "none", opacity: completed ? 0.7 : 1 }}>
          {t.task_title}
        </div>
        {t.task_description && (
          <div className="text-sm mt-0.5" style={{ color: "var(--text-secondary)", opacity: completed ? 0.7 : 1 }}>{t.task_description}</div>
        )}
        <div className="mt-2 flex flex-wrap gap-2 text-xs items-center">
          {doctor && (
            <Link to={`/doctors/${doctor.id}`} className="pill pill-muted hover:opacity-80" data-testid={`task-doctor-${t.id}`}>
              {doctor.doctor_name} · {doctor.clinic_name}
            </Link>
          )}
          <StatusPill kind={overdue ? "danger" : completed ? "success" : "info"}>
            <CalendarClock className="w-3 h-3" />Due {fmtDate(t.due_date)}
          </StatusPill>
          <StatusPill kind={priorityKind(t.priority)}>{t.priority}</StatusPill>
          {t.created_from_ai && <StatusPill kind="muted"><Brain className="w-3 h-3" />AI</StatusPill>}
          {completed && t.completed_at && (
            <span className="text-xs" style={{ color: "var(--status-success)" }} data-testid={`task-completed-at-${t.id}`}>
              ✓ Done {fmtDateTime(t.completed_at)}
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-col sm:flex-row gap-1 flex-shrink-0">
        {completed ? (
          <button onClick={onReopen} data-testid={`task-reopen-${t.id}`} title="Reopen" className="p-1.5 rounded hover:bg-[var(--bg-paper)]">
            <Undo2 className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
          </button>
        ) : (
          <Button size="sm" variant="outline" onClick={onComplete} data-testid={`task-complete-${t.id}`}>
            <CheckCircle2 className="w-4 h-4 mr-1" /> Complete
          </Button>
        )}
        <button onClick={onEdit} data-testid={`task-edit-${t.id}`} title="Edit" className="p-1.5 rounded hover:bg-[var(--bg-paper)]">
          <Pencil className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
        </button>
        <button onClick={onDelete} data-testid={`task-delete-${t.id}`} title="Delete" className="p-1.5 rounded hover:bg-[var(--bg-paper)]">
          <Trash2 className="w-4 h-4" style={{ color: "var(--status-danger)" }} />
        </button>
      </div>
    </div>
  );
}

function EditTaskDialog({ open, task, onClose, onSaved }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [priority, setPriority] = useState("Medium");
  const [doctorId, setDoctorId] = useState(null);
  const [doctors, setDoctors] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!task) return;
    setTitle(task.task_title || "");
    setDescription(task.task_description || "");
    setDueDate(task.due_date || "");
    setPriority(task.priority || "Medium");
    setDoctorId(task.doctor_id || null);
    api.get("/doctors").then((r) => {
      const list = Array.isArray(r.data) ? r.data : (r.data?.doctors || []);
      setDoctors(list);
    }).catch(() => {});
  }, [task]);

  const save = async () => {
    if (!title.trim()) { toast.error("Title is required"); return; }
    setSaving(true);
    try {
      const payload = {
        task_title: title.trim(),
        task_description: description.trim(),
        due_date: dueDate || null,
        priority,
      };
      if (doctorId && doctorId !== task.doctor_id) payload.doctor_id = doctorId;
      const { data } = await api.put(`/tasks/${task.id}`, payload);
      onSaved(data);
      toast.success("Task updated");
      onClose();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent data-testid="edit-task-dialog">
        <DialogHeader><DialogTitle>Edit task</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="mb-1 block text-xs">Title</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} className="bg-white" data-testid="edit-task-title" />
          </div>
          <div>
            <Label className="mb-1 block text-xs">Description</Label>
            <Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} className="bg-white" data-testid="edit-task-description" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="mb-1 block text-xs">Due date</Label>
              <Input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className="bg-white" data-testid="edit-task-date" />
            </div>
            <div>
              <Label className="mb-1 block text-xs">Priority</Label>
              <Select value={priority} onValueChange={setPriority}>
                <SelectTrigger className="bg-white" data-testid="edit-task-priority"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["Low", "Medium", "High"].map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label className="mb-1 block text-xs">Doctor</Label>
            <Select value={doctorId || ""} onValueChange={setDoctorId}>
              <SelectTrigger className="bg-white" data-testid="edit-task-doctor"><SelectValue placeholder="Pick a doctor" /></SelectTrigger>
              <SelectContent>
                {doctors.map((d) => <SelectItem key={d.id} value={d.id}>{d.doctor_name} · {d.clinic_name || "—"}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving} data-testid="edit-task-save" style={{ background: "var(--brand-primary)", color: "white" }}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


function NewTaskDialog({ open, doctors, onClose, onCreated, onDoctorAdded }) {
  const [doctorId, setDoctorId] = useState("");
  const [docQuery, setDocQuery] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dueDate, setDueDate] = useState(todayISO());
  const [priority, setPriority] = useState("Medium");
  const [saving, setSaving] = useState(false);
  const [addingDoctor, setAddingDoctor] = useState(false);

  // Reset form whenever dialog opens
  useEffect(() => {
    if (open) {
      setDoctorId(""); setDocQuery(""); setTitle(""); setDescription("");
      setDueDate(todayISO()); setPriority("Medium"); setAddingDoctor(false);
    }
  }, [open]);

  const filtered = useMemo(() => {
    if (!docQuery.trim()) return doctors.slice(0, 12);
    const q = docQuery.toLowerCase().trim();
    return doctors.filter((d) =>
      (d.doctor_name || "").toLowerCase().includes(q) ||
      (d.clinic_name || "").toLowerCase().includes(q) ||
      (d.city || "").toLowerCase().includes(q),
    ).slice(0, 20);
  }, [doctors, docQuery]);

  const selectedDoctor = doctors.find((d) => d.id === doctorId);

  const save = async () => {
    if (!doctorId) { toast.error("Pick a doctor"); return; }
    if (!title.trim()) { toast.error("Add a task title"); return; }
    setSaving(true);
    try {
      const { data } = await api.post("/tasks", {
        doctor_id: doctorId,
        task_title: title.trim(),
        task_description: description.trim() || "",
        due_date: dueDate || null,
        priority,
      });
      toast.success("Task created");
      onCreated?.(data, selectedDoctor);
      onClose?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to create task");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New task</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Doctor</Label>
            {selectedDoctor ? (
              <div className="rounded-md border bg-white p-3 mt-1 flex items-start justify-between gap-3" style={{ borderColor: "var(--border-default)" }}>
                <div>
                  <div className="font-medium" style={{ color: "var(--brand-primary)" }}>{selectedDoctor.doctor_name}</div>
                  <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {[selectedDoctor.clinic_name, selectedDoctor.city, selectedDoctor.segment].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => { setDoctorId(""); setDocQuery(""); }} data-testid="new-task-clear-doctor">Change</Button>
              </div>
            ) : (
              <>
                <div className="relative mt-1">
                  <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: "var(--text-muted)" }} />
                  <Input
                    autoFocus
                    placeholder="Search doctor by name, clinic, city…"
                    value={docQuery}
                    onChange={(e) => setDocQuery(e.target.value)}
                    className="pl-9 bg-white"
                    data-testid="new-task-doctor-search"
                  />
                </div>
                <div className="mt-2 max-h-56 overflow-y-auto rounded-md border bg-white" style={{ borderColor: "var(--border-default)" }}>
                  {filtered.length === 0 ? (
                    <div className="p-3 text-sm" style={{ color: "var(--text-muted)" }}>No doctors match.</div>
                  ) : (
                    filtered.map((d) => (
                      <button
                        key={d.id}
                        onClick={() => setDoctorId(d.id)}
                        data-testid={`new-task-doctor-${d.id}`}
                        className="w-full text-left px-3 py-2 border-b last:border-b-0 hover:bg-[var(--bg-paper)] transition-colors"
                        style={{ borderColor: "var(--border-default)" }}
                      >
                        <div className="text-sm font-medium" style={{ color: "var(--brand-primary)" }}>{d.doctor_name}</div>
                        <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                          {[d.clinic_name, d.city, d.segment].filter(Boolean).join(" · ") || "—"}
                        </div>
                      </button>
                    ))
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setAddingDoctor(true)}
                  data-testid="new-task-add-doctor"
                  className="mt-2 text-xs flex items-center gap-1 hover:underline"
                  style={{ color: "var(--brand-primary)" }}
                >
                  <UserPlus className="w-3.5 h-3.5" />
                  Can&apos;t find them? Add new doctor{docQuery ? ` "${docQuery}"` : ""}
                </button>
              </>
            )}
          </div>

          <div>
            <Label>Task</Label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Send pricing for the iTero scanner"
              className="bg-white"
              data-testid="new-task-title"
            />
          </div>

          <div>
            <Label>Details (optional)</Label>
            <Textarea
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Anything that helps you finish this faster"
              className="bg-white"
              data-testid="new-task-description"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Due date</Label>
              <Input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="bg-white"
                data-testid="new-task-due-date"
              />
              <div className="text-[10px] mt-1" style={{ color: "var(--text-muted)" }}>Defaults to today.</div>
            </div>
            <div>
              <Label>Priority</Label>
              <Select value={priority} onValueChange={setPriority}>
                <SelectTrigger className="bg-white" data-testid="new-task-priority"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["Low", "Medium", "High"].map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={save} disabled={saving || !doctorId || !title.trim()} data-testid="new-task-save" style={{ background: "var(--brand-secondary)", color: "white" }}>
            {saving ? "Saving…" : "Create task"}
          </Button>
        </DialogFooter>
      </DialogContent>
      <InlineAddDoctor
        open={addingDoctor}
        prefillName={docQuery}
        onClose={() => setAddingDoctor(false)}
        onCreated={(d) => {
          onDoctorAdded?.(d);
          setDoctorId(d.id);
          setDocQuery("");
          setAddingDoctor(false);
        }}
      />
    </Dialog>
  );
}

