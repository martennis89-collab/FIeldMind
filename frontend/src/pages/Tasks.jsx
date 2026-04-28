import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Link } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Button } from "../components/ui/button";
import { StatusPill, priorityKind } from "../components/StatusPill";
import { CalendarClock, CheckCircle2, AlertTriangle, Brain, Clock } from "lucide-react";
import { toast } from "sonner";

const BUCKETS = [
  { key: "overdue", label: "Overdue", kind: "danger" },
  { key: "today", label: "Today", kind: "warning" },
  { key: "week", label: "This week", kind: "info" },
  { key: "upcoming", label: "Later", kind: "muted" },
  { key: "completed", label: "Completed", kind: "success" },
];

function formatDate(s) {
  if (!s) return "—";
  try { return new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric" }); } catch { return s; }
}

export default function Tasks() {
  const [bucket, setBucket] = useState("overdue");
  const [tasks, setTasks] = useState([]);
  const [doctors, setDoctors] = useState({});
  const [loading, setLoading] = useState(true);
  const [counts, setCounts] = useState({});

  const load = async (b) => {
    setLoading(true);
    try {
      const { data } = await api.get("/tasks", { params: { bucket: b } });
      setTasks(data);
      // load doctors for naming
      const ids = Array.from(new Set(data.map((t) => t.doctor_id)));
      const map = { ...doctors };
      const missing = ids.filter((id) => !map[id]);
      await Promise.all(missing.map(async (id) => {
        try {
          const r = await api.get(`/doctors/${id}`);
          map[id] = r.data;
        } catch {/* ignore */}
      }));
      setDoctors(map);
    } finally {
      setLoading(false);
    }
  };

  const loadCounts = async () => {
    const entries = await Promise.all(BUCKETS.map(async (b) => {
      try {
        const { data } = await api.get("/tasks", { params: { bucket: b.key } });
        return [b.key, data.length];
      } catch { return [b.key, 0]; }
    }));
    setCounts(Object.fromEntries(entries));
  };

  useEffect(() => { load(bucket); /* eslint-disable-next-line */ }, [bucket]);
  useEffect(() => { loadCounts(); /* eslint-disable-next-line */ }, []);

  const complete = async (t) => {
    await api.put(`/tasks/${t.id}`, { status: "Completed" });
    toast.success("Marked complete");
    load(bucket); loadCounts();
  };

  return (
    <div data-testid="tasks-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Promises & follow-ups</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          Things you owe<span className="font-medium">.</span>
        </h1>
      </div>

      <Tabs value={bucket} onValueChange={setBucket}>
        <TabsList className="bg-[var(--bg-paper)] flex-wrap h-auto">
          {BUCKETS.map((b) => (
            <TabsTrigger key={b.key} value={b.key} data-testid={`tab-${b.key}`} className="data-[state=active]:bg-white">
              {b.label} <span className="ml-1.5 text-xs opacity-70">({counts[b.key] ?? "·"})</span>
            </TabsTrigger>
          ))}
        </TabsList>
        {BUCKETS.map((b) => (
          <TabsContent key={b.key} value={b.key}>
            {loading ? (
              <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>
            ) : (
              <div className="space-y-3 mt-4">
                {tasks.length === 0 && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Nothing here.</div>}
                {tasks.map((t, i) => {
                  const doc = doctors[t.doctor_id];
                  const overdue = b.key === "overdue" || (t.due_date && t.due_date < new Date().toISOString().slice(0, 10) && t.status !== "Completed");
                  return (
                    <div key={t.id} className="rounded-md border p-4 flex items-start gap-3 fade-up" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)", animationDelay: `${i * 25}ms` }} data-testid={`task-row-${t.id}`}>
                      <div className="mt-0.5">
                        {t.status === "Completed" ? (
                          <CheckCircle2 className="w-5 h-5" style={{ color: "var(--status-success)" }} />
                        ) : overdue ? (
                          <AlertTriangle className="w-5 h-5" style={{ color: "var(--status-danger)" }} />
                        ) : (
                          <Clock className="w-5 h-5" style={{ color: "var(--status-info)" }} />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium" style={{ color: "var(--text-primary)", textDecoration: t.status === "Completed" ? "line-through" : "none" }}>
                          {t.task_title}
                        </div>
                        {t.task_description && <div className="text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>{t.task_description}</div>}
                        <div className="mt-2 flex flex-wrap gap-2 text-xs">
                          {doc && (
                            <Link to={`/doctors/${doc.id}`} className="pill pill-muted hover:opacity-80">
                              {doc.doctor_name} · {doc.clinic_name}
                            </Link>
                          )}
                          <StatusPill kind={overdue ? "danger" : "info"}><CalendarClock className="w-3 h-3" />Due {formatDate(t.due_date)}</StatusPill>
                          <StatusPill kind={priorityKind(t.priority)}>{t.priority}</StatusPill>
                          {t.created_from_ai && <StatusPill kind="muted"><Brain className="w-3 h-3" />AI</StatusPill>}
                        </div>
                      </div>
                      {t.status !== "Completed" && (
                        <Button size="sm" variant="outline" onClick={() => complete(t)} data-testid={`task-complete-${t.id}`}>
                          <CheckCircle2 className="w-4 h-4 mr-1" /> Complete
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
