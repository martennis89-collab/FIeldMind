import React, { useEffect, useMemo, useState } from "react";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { StatusPill } from "../components/StatusPill";
import { toast } from "sonner";
import { FileText, Sparkles, Send, Pencil, MessageSquare, AlertTriangle, Clock, CheckCircle2, X, Plus, Download } from "lucide-react";

function formatDate(s) {
  if (!s) return "—";
  try { return new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }); } catch { return s; }
}
function formatDateTime(s) {
  if (!s) return "—";
  try { return new Date(s).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return s; }
}

async function downloadReportExport(reportId, format, fallbackName) {
  try {
    const res = await api.get(`/reports/${reportId}/export`, {
      params: { format },
      responseType: "blob",
    });
    const blob = res.data;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    // Try to honour server-provided filename
    const cd = res.headers?.["content-disposition"] || "";
    const match = /filename="?([^"]+)"?/i.exec(cd);
    a.download = match ? match[1] : `${fallbackName}.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    toast.success(`${format.toUpperCase()} downloaded`);
  } catch {
    toast.error(`Could not export ${format.toUpperCase()}`);
  }
}

export default function Reports() {
  const { user } = useAuth();
  return (
    <div data-testid="reports-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Weekly reports</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          {user.role === "TM" ? <>Your <span className="font-medium">weekly intelligence.</span></> : <>Team <span className="font-medium">reports.</span></>}
        </h1>
      </div>
      {user.role === "TM" ? <TMReports /> : <ManagerReports />}
    </div>
  );
}

// ============== TM VIEW ==============
function TMReports() {
  const [reports, setReports] = useState([]);
  const [draftOpen, setDraftOpen] = useState(false);
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/reports");
      setReports(data.reports || []);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const generate = async () => {
    try {
      const { data } = await api.post("/reports/generate");
      setDraft(data);
      setEditingId(null);
      setDraftOpen(true);
    } catch (e) {
      toast.error("Could not generate draft");
    }
  };

  const editReport = (r) => {
    setDraft({
      tm_user_id: r.tm_user_id,
      tm_name: r.tm_name,
      team_id: r.team_id,
      week_start: r.week_start,
      week_end: r.week_end,
      auto_summary: r.auto_summary,
      content: r.content,
      notes_from_tm: r.notes_from_tm || "",
    });
    setEditingId(r.id);
    setDraftOpen(true);
  };

  const saveDraft = async (submit = false) => {
    if (!draft) return;
    setSaving(true);
    try {
      let saved;
      if (editingId) {
        const { data } = await api.put(`/reports/${editingId}`, {
          auto_summary: draft.auto_summary,
          content: draft.content,
          notes_from_tm: draft.notes_from_tm,
        });
        saved = data;
      } else {
        const { data } = await api.post("/reports", {
          week_start: draft.week_start,
          week_end: draft.week_end,
          auto_summary: draft.auto_summary,
          content: draft.content,
          notes_from_tm: draft.notes_from_tm,
        });
        saved = data;
        setEditingId(saved.id);
      }
      if (submit) {
        await api.post(`/reports/${saved.id}/submit`);
        toast.success("Report submitted to your manager");
      } else {
        toast.success("Draft saved");
      }
      setDraftOpen(false);
      setDraft(null);
      setEditingId(null);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="rounded-md border p-6 mb-6 flex items-center justify-between" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
        <div>
          <div className="font-display text-lg font-medium" style={{ color: "var(--brand-primary)" }}>Generate this week's report</div>
          <div className="text-sm" style={{ color: "var(--text-secondary)" }}>FieldMind drafts it from your activity. You review, edit, and submit.</div>
        </div>
        <Button onClick={generate} data-testid="generate-report-btn" style={{ background: "var(--brand-primary)", color: "white" }} className="font-medium">
          <Sparkles className="w-4 h-4 mr-2" /> Generate weekly report
        </Button>
      </div>

      {loading ? <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div> : (
        <div className="space-y-3" data-testid="tm-reports-list">
          {reports.length === 0 && (
            <div className="rounded-md border p-8 text-center" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
              <FileText className="w-8 h-8 mx-auto mb-2" style={{ color: "var(--text-muted)" }} />
              <div className="text-sm" style={{ color: "var(--text-secondary)" }}>No reports yet. Generate your first one above.</div>
            </div>
          )}
          {reports.map((r) => (
            <div key={r.id} className="rounded-md border p-5 card-lift" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={`report-row-${r.id}`}>
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="min-w-0">
                  <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Week of {formatDate(r.week_start)}</div>
                  <div className="font-display text-lg font-medium mt-0.5" style={{ color: "var(--brand-primary)" }}>{r.auto_summary || "Weekly report"}</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <ReportStatusPill status={r.status} />
                    {r.submitted_at && <span className="text-xs" style={{ color: "var(--text-muted)" }}>Submitted {formatDateTime(r.submitted_at)}</span>}
                    {(r.comments?.length > 0) && <StatusPill kind="info"><MessageSquare className="w-3 h-3" />{r.comments.length} comment{r.comments.length > 1 ? "s" : ""}</StatusPill>}
                  </div>
                </div>
                <div className="flex gap-2">
                  {r.status === "Draft" && (
                    <Button size="sm" variant="outline" onClick={() => editReport(r)} data-testid={`edit-report-${r.id}`}>
                      <Pencil className="w-3 h-3 mr-1" /> Continue editing
                    </Button>
                  )}
                  {r.status !== "Draft" && (
                    <Button size="sm" variant="outline" onClick={() => editReport(r)} data-testid={`view-report-${r.id}`}>
                      View
                    </Button>
                  )}
                  <Button size="sm" variant="outline" onClick={() => downloadReportExport(r.id, "pdf", `weekly_report_${r.week_start}`)} data-testid={`export-pdf-${r.id}`} title="Export as PDF">
                    <Download className="w-3 h-3 mr-1" /> PDF
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => downloadReportExport(r.id, "csv", `weekly_report_${r.week_start}`)} data-testid={`export-csv-${r.id}`} title="Export as CSV">
                    CSV
                  </Button>
                </div>
              </div>
              {r.comments?.length > 0 && (
                <div className="mt-3 space-y-2 border-t pt-3" style={{ borderColor: "var(--border-default)" }}>
                  {r.comments.map((c) => (
                    <div key={c.id} className="text-sm" style={{ background: "var(--status-info-bg)", padding: "8px 12px", borderRadius: 6 }}>
                      <div className="text-xs" style={{ color: "var(--status-info)" }}><strong>{c.user_name}</strong> · {formatDateTime(c.created_at)}</div>
                      <div style={{ color: "var(--text-primary)" }}>{c.text}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <ReportEditor
        open={draftOpen}
        onClose={() => { setDraftOpen(false); setDraft(null); setEditingId(null); }}
        draft={draft}
        setDraft={setDraft}
        readonly={editingId && reports.find((r) => r.id === editingId)?.status !== "Draft"}
        saving={saving}
        onSave={() => saveDraft(false)}
        onSubmit={() => saveDraft(true)}
      />
    </>
  );
}

function ReportStatusPill({ status }) {
  const map = {
    Draft: { kind: "muted", icon: <Pencil className="w-3 h-3" /> },
    Submitted: { kind: "info", icon: <Send className="w-3 h-3" /> },
    Reviewed: { kind: "success", icon: <CheckCircle2 className="w-3 h-3" /> },
    Pending: { kind: "warning", icon: <Clock className="w-3 h-3" /> },
    Overdue: { kind: "danger", icon: <AlertTriangle className="w-3 h-3" /> },
  };
  const m = map[status] || map.Draft;
  return <StatusPill kind={m.kind} testId={`status-${status}`}>{m.icon}{status}</StatusPill>;
}

function ReportEditor({ open, onClose, draft, setDraft, readonly, saving, onSave, onSubmit }) {
  if (!draft) return null;
  const c = draft.content || {};
  const updateContent = (patch) => setDraft({ ...draft, content: { ...c, ...patch } });
  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Weekly report — {formatDate(draft.week_start)} → {formatDate(draft.week_end)}</DialogTitle>
        </DialogHeader>

        <div className="space-y-5">
          <section className="rounded-md p-4" style={{ background: "var(--status-info-bg)" }}>
            <div className="text-xs uppercase tracking-widest mb-1 flex items-center gap-1" style={{ color: "var(--status-info)" }}>
              <Sparkles className="w-3 h-3" /> Auto insight summary
            </div>
            {readonly ? (
              <p className="text-sm" style={{ color: "var(--text-primary)" }} data-testid="auto-summary-text">{draft.auto_summary}</p>
            ) : (
              <Textarea
                value={draft.auto_summary}
                onChange={(e) => setDraft({ ...draft, auto_summary: e.target.value })}
                rows={3}
                className="bg-white text-sm"
                data-testid="auto-summary-textarea"
              />
            )}
          </section>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Visits" value={c.visits_completed} />
            <Stat label="Doctors" value={c.doctors_visited} />
            <Stat label="Promises created" value={c.promises_created} />
            <Stat label="Promises completed" value={c.promises_completed} kind="success" />
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Demos discussed" value={c.demos_discussed || 0} />
            <Stat label="Demos booked" value={c.demos_booked || 0} />
            <Stat label="Demos completed" value={c.demos_completed || 0} kind="success" />
            <Stat label="Proposals sent" value={c.proposals_sent || 0} />
          </div>

          <DemosSection content={c} />

          <section>
            <Label className="text-xs uppercase tracking-widest mb-2 block" style={{ color: "var(--text-muted)" }}>Key insights</Label>
            <div className="space-y-2">
              {(c.key_insights || []).map((ins, i) => (
                <div key={i} className="rounded border p-3 flex items-start gap-2" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
                  <span className="flex-1 text-sm" style={{ color: "var(--text-primary)" }}>
                    {readonly ? ins : (
                      <Input
                        value={ins}
                        onChange={(e) => updateContent({ key_insights: c.key_insights.map((x, idx) => idx === i ? e.target.value : x) })}
                        className="bg-white"
                        data-testid={`insight-${i}`}
                      />
                    )}
                  </span>
                  {!readonly && (
                    <button onClick={() => updateContent({ key_insights: c.key_insights.filter((_, idx) => idx !== i) })} data-testid={`remove-insight-${i}`}>
                      <X className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                    </button>
                  )}
                </div>
              ))}
              {!readonly && (
                <Button size="sm" variant="outline" onClick={() => updateContent({ key_insights: [...(c.key_insights || []), ""] })} data-testid="add-insight-btn">
                  <Plus className="w-3 h-3 mr-1" /> Add insight
                </Button>
              )}
            </div>
          </section>

          <div className="grid sm:grid-cols-2 gap-4">
            <section>
              <Label className="text-xs uppercase tracking-widest mb-2 block" style={{ color: "var(--text-muted)" }}>Topics discussed</Label>
              <div className="flex flex-wrap gap-1.5">
                {(c.topics_discussed || []).map((t) => <span key={t} className="pill pill-info">{t}</span>)}
                {(c.topics_discussed || []).length === 0 && <span className="text-xs" style={{ color: "var(--text-muted)" }}>None</span>}
              </div>
            </section>
            <section>
              <Label className="text-xs uppercase tracking-widest mb-2 block" style={{ color: "var(--text-muted)" }}>Barriers heard</Label>
              <div className="flex flex-wrap gap-1.5">
                {(c.barriers_heard || []).map((t) => <span key={t} className="pill pill-warning">{t}</span>)}
                {(c.barriers_heard || []).length === 0 && <span className="text-xs" style={{ color: "var(--text-muted)" }}>None</span>}
              </div>
            </section>
          </div>

          <section>
            <Label className="text-xs uppercase tracking-widest mb-2 block" style={{ color: "var(--text-muted)" }}>Doctors needing attention next week</Label>
            <div className="space-y-1.5">
              {(c.doctors_needing_attention || []).map((d) => (
                <div key={d.id} className="rounded border p-2 text-sm flex items-center justify-between" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }}>
                  <div>
                    <div className="font-medium" style={{ color: "var(--text-primary)" }}>{d.doctor_name}</div>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>{d.segment} · {d.reason}</div>
                  </div>
                  <span className="pill pill-danger">priority {d.score}</span>
                </div>
              ))}
              {(c.doctors_needing_attention || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>None flagged</div>}
            </div>
          </section>

          <section data-testid="report-doctor-breakdown-edit">
            <Label className="text-xs uppercase tracking-widest mb-2 block" style={{ color: "var(--text-muted)" }}>
              Per-doctor breakdown ({(c.doctor_breakdown || []).length})
            </Label>
            <div className="space-y-2">
              {(c.doctor_breakdown || []).map((d) => (
                <div key={d.doctor_id} className="rounded border p-3 text-sm" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }}>
                  <div className="flex items-start justify-between gap-2 mb-1">
                    <div>
                      <div className="font-medium" style={{ color: "var(--text-primary)" }}>{d.doctor_name}</div>
                      <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                        {[d.clinic_name, d.city, d.segment].filter(Boolean).join(" · ")}
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-0.5">
                      <span className="pill pill-info">{d.visits_count} visit{d.visits_count !== 1 ? "s" : ""}</span>
                      {(d.demos_booked_count > 0 || d.demos_completed_count > 0) && (
                        <span className="pill pill-success text-[10px]">
                          {d.demos_completed_count > 0 ? `${d.demos_completed_count} demo${d.demos_completed_count !== 1 ? "s" : ""} done` : `${d.demos_booked_count} demo${d.demos_booked_count !== 1 ? "s" : ""} booked`}
                        </span>
                      )}
                      {d.sentiment && d.sentiment !== "—" && (
                        <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{d.sentiment}</span>
                      )}
                    </div>
                  </div>
                  {(d.topics || []).length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {d.topics.map((t) => <span key={t} className="pill pill-info">{t}</span>)}
                    </div>
                  )}
                  {(d.barriers || []).length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {d.barriers.map((b) => <span key={b} className="pill pill-warning">{b}</span>)}
                    </div>
                  )}
                  {(d.promises || []).length > 0 && (
                    <div className="mt-1.5 text-xs" style={{ color: "var(--text-secondary)" }}>
                      <span className="font-semibold">Promises: </span>
                      {d.promises.join("; ")}
                    </div>
                  )}
                  {d.note_excerpt && (
                    <div className="mt-1.5 text-xs italic" style={{ color: "var(--text-muted)" }}>
                      "{d.note_excerpt}"
                    </div>
                  )}
                </div>
              ))}
              {(c.doctor_breakdown || []).length === 0 && (
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>No visits logged this week.</div>
              )}
            </div>
          </section>

          <section>
            <Label className="text-xs uppercase tracking-widest mb-2 block" style={{ color: "var(--text-muted)" }}>Notes for your manager</Label>
            {readonly ? (
              <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-primary)" }}>{draft.notes_from_tm || "—"}</p>
            ) : (
              <Textarea
                value={draft.notes_from_tm}
                onChange={(e) => setDraft({ ...draft, notes_from_tm: e.target.value })}
                rows={4}
                placeholder="Anything you want to add — context, asks, blockers."
                className="bg-white"
                data-testid="tm-notes-textarea"
              />
            )}
          </section>
        </div>

        <DialogFooter>
          {!readonly && (
            <>
              <Button variant="outline" onClick={onSave} disabled={saving} data-testid="save-draft-btn">Save draft</Button>
              <Button onClick={onSubmit} disabled={saving} data-testid="submit-report-btn" style={{ background: "var(--brand-secondary)", color: "white" }}>
                <Send className="w-4 h-4 mr-1" /> Submit to manager
              </Button>
            </>
          )}
          {readonly && <Button variant="outline" onClick={onClose}>Close</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Stat({ label, value, kind = "muted" }) {
  const fg = kind === "success" ? "var(--status-success)" : "var(--brand-primary)";
  return (
    <div className="rounded-md border p-3" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
      <div className="text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="font-display text-2xl font-medium" style={{ color: fg }}>{value ?? 0}</div>
    </div>
  );
}

function fmtDemoWhen(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function DemosSection({ content }) {
  const booked = content?.demos_booked_list || [];
  const completed = content?.demos_completed_list || [];
  if (booked.length === 0 && completed.length === 0) return null;
  const bookedIds = new Set(booked.map((d) => d.meeting_id));
  const extraCompleted = completed.filter((d) => !bookedIds.has(d.meeting_id));
  return (
    <section data-testid="report-demos-section">
      <Label className="text-xs uppercase tracking-widest mb-2 block" style={{ color: "var(--text-muted)" }}>
        iTero demos this week ({booked.length + extraCompleted.length})
      </Label>
      <div className="space-y-1.5">
        {booked.map((d) => (
          <div key={d.meeting_id} className="rounded border p-2 text-sm flex items-center justify-between gap-2" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }} data-testid={`report-demo-${d.meeting_id}`}>
            <div className="min-w-0 flex-1">
              <div className="font-medium truncate" style={{ color: "var(--text-primary)" }}>{d.doctor_name}</div>
              <div className="text-xs truncate" style={{ color: "var(--text-muted)" }}>
                {[d.clinic_name, fmtDemoWhen(d.scheduled_at)].filter(Boolean).join(" · ")}
              </div>
            </div>
            <span className={`pill ${d.is_completed ? "pill-success" : "pill-info"}`}>
              {d.is_completed ? "Completed" : (d.status || "Scheduled")}
            </span>
          </div>
        ))}
        {extraCompleted.map((d) => (
          <div key={d.meeting_id} className="rounded border p-2 text-sm flex items-center justify-between gap-2" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }} data-testid={`report-demo-${d.meeting_id}`}>
            <div className="min-w-0 flex-1">
              <div className="font-medium truncate" style={{ color: "var(--text-primary)" }}>{d.doctor_name}</div>
              <div className="text-xs truncate" style={{ color: "var(--text-muted)" }}>
                {[d.clinic_name, `Scheduled ${fmtDemoWhen(d.scheduled_at)}`].filter(Boolean).join(" · ")}
              </div>
            </div>
            <span className="pill pill-success">Completed</span>
          </div>
        ))}
      </div>
    </section>
  );
}

// ============== MANAGER VIEW ==============
function ManagerReports() {
  const [bucket, setBucket] = useState("submitted");
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [counts, setCounts] = useState({});
  const [openId, setOpenId] = useState(null);

  const load = async (b) => {
    setLoading(true);
    try {
      const { data } = await api.get("/reports", { params: { bucket: b } });
      setReports(data.reports || []);
    } finally {
      setLoading(false);
    }
  };
  const loadCounts = async () => {
    const buckets = ["submitted", "pending", "overdue"];
    const entries = await Promise.all(buckets.map(async (b) => {
      try { const { data } = await api.get("/reports", { params: { bucket: b } }); return [b, (data.reports || []).length]; }
      catch { return [b, 0]; }
    }));
    setCounts(Object.fromEntries(entries));
  };
  useEffect(() => { load(bucket); /* eslint-disable-next-line */ }, [bucket]);
  useEffect(() => { loadCounts(); }, []);

  return (
    <>
      <Tabs value={bucket} onValueChange={setBucket}>
        <TabsList className="bg-[var(--bg-paper)]">
          <TabsTrigger value="submitted" data-testid="tab-submitted">Submitted ({counts.submitted ?? "·"})</TabsTrigger>
          <TabsTrigger value="pending" data-testid="tab-pending">Pending ({counts.pending ?? "·"})</TabsTrigger>
          <TabsTrigger value="overdue" data-testid="tab-overdue">Overdue ({counts.overdue ?? "·"})</TabsTrigger>
        </TabsList>
        {["submitted", "pending", "overdue"].map((b) => (
          <TabsContent key={b} value={b}>
            <div className="mt-4 space-y-3">
              {loading && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>}
              {!loading && reports.length === 0 && (
                <div className="rounded-md border p-8 text-center" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
                  <CheckCircle2 className="w-8 h-8 mx-auto mb-2" style={{ color: "var(--status-success)" }} />
                  <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
                    {b === "pending" ? "All TMs have submitted this week." : b === "overdue" ? "No overdue reports last week." : "No submitted reports yet."}
                  </div>
                </div>
              )}
              {reports.map((r) => (
                <ReportRow key={r.id || r.tm_user_id} report={r} onOpen={() => !r.synthetic && setOpenId(r.id)} />
              ))}
            </div>
          </TabsContent>
        ))}
      </Tabs>

      {openId && <ReportDrawer reportId={openId} onClose={() => { setOpenId(null); load(bucket); loadCounts(); }} />}
    </>
  );
}

function ReportRow({ report, onOpen }) {
  const r = report;
  const synth = r.synthetic;
  const Wrapper = synth ? "div" : "button";
  return (
    <Wrapper
      onClick={synth ? undefined : onOpen}
      data-testid={`mgr-report-row-${r.id || r.tm_user_id}`}
      className={`w-full text-left rounded-md border p-5 ${synth ? "" : "card-lift cursor-pointer"}`}
      style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
    >
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
            {r.tm_name} · Week of {formatDate(r.week_start)}
          </div>
          <div className="font-display text-base font-medium mt-0.5 line-clamp-2" style={{ color: "var(--brand-primary)" }}>
            {synth ? (r.status === "Pending" ? "Report not yet submitted for this week" : "Missed submission for last week") : (r.auto_summary || "Weekly report")}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <ReportStatusPill status={r.status} />
            {r.submitted_at && <span className="text-xs" style={{ color: "var(--text-muted)" }}>Submitted {formatDateTime(r.submitted_at)}</span>}
            {(r.comments?.length > 0) && <StatusPill kind="info"><MessageSquare className="w-3 h-3" />{r.comments.length}</StatusPill>}
          </div>
        </div>
      </div>
    </Wrapper>
  );
}

function ReportDrawer({ reportId, onClose }) {
  const [report, setReport] = useState(null);
  const [comment, setComment] = useState("");
  const [posting, setPosting] = useState(false);

  const load = async () => {
    try { const { data } = await api.get(`/reports/${reportId}`); setReport(data); }
    catch { toast.error("Could not load report"); onClose(); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [reportId]);

  const post = async () => {
    if (!comment.trim()) return;
    setPosting(true);
    try {
      const { data } = await api.post(`/reports/${reportId}/comment`, { text: comment });
      setReport(data);
      setComment("");
      toast.success("Comment posted — TM will see it");
    } finally {
      setPosting(false);
    }
  };

  if (!report) return null;
  const c = report.content || {};
  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto" data-testid="report-drawer">
        <DialogHeader>
          <DialogTitle>{report.tm_name} — Week of {formatDate(report.week_start)}</DialogTitle>
        </DialogHeader>

        <section className="rounded-md p-4" style={{ background: "var(--status-info-bg)" }}>
          <div className="text-xs uppercase tracking-widest mb-1 flex items-center gap-1" style={{ color: "var(--status-info)" }}>
            <Sparkles className="w-3 h-3" /> Auto insight summary
          </div>
          <p className="text-sm" style={{ color: "var(--text-primary)" }} data-testid="drawer-auto-summary">{report.auto_summary}</p>
        </section>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
          <Stat label="Visits" value={c.visits_completed} />
          <Stat label="Doctors" value={c.doctors_visited} />
          <Stat label="Promises created" value={c.promises_created} />
          <Stat label="Promises completed" value={c.promises_completed} kind="success" />
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3">
          <Stat label="Demos discussed" value={c.demos_discussed || 0} />
          <Stat label="Demos booked" value={c.demos_booked || 0} />
          <Stat label="Demos completed" value={c.demos_completed || 0} kind="success" />
          <Stat label="Proposals sent" value={c.proposals_sent || 0} />
        </div>

        <div className="mt-5">
          <DemosSection content={c} />
        </div>

        {(c.key_insights || []).length > 0 && (
          <section className="mt-5">
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Key insights</div>
            <ul className="space-y-1.5 list-disc list-inside text-sm">
              {c.key_insights.map((i, k) => <li key={k} style={{ color: "var(--text-primary)" }}>{i}</li>)}
            </ul>
          </section>
        )}

        <div className="grid sm:grid-cols-2 gap-4 mt-5">
          <section>
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Topics</div>
            <div className="flex flex-wrap gap-1.5">{(c.topics_discussed || []).map((t) => <span key={t} className="pill pill-info">{t}</span>)}</div>
          </section>
          <section>
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Barriers</div>
            <div className="flex flex-wrap gap-1.5">{(c.barriers_heard || []).map((b) => <span key={b} className="pill pill-warning">{b}</span>)}</div>
          </section>
        </div>

        {(c.doctors_needing_attention || []).length > 0 && (
          <section className="mt-5">
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Doctors needing attention</div>
            <div className="space-y-1.5">
              {c.doctors_needing_attention.map((d) => (
                <div key={d.id} className="rounded border p-2 text-sm flex items-center justify-between" style={{ borderColor: "var(--border-default)" }}>
                  <div>
                    <div className="font-medium">{d.doctor_name}</div>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>{d.segment} · {d.reason}</div>
                  </div>
                  <span className="pill pill-danger">priority {d.score}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {(c.doctor_breakdown || []).length > 0 && (
          <section className="mt-5" data-testid="report-doctor-breakdown-readonly">
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>
              Per-doctor breakdown ({c.doctor_breakdown.length})
            </div>
            <div className="space-y-2">
              {c.doctor_breakdown.map((d) => (
                <div key={d.doctor_id} className="rounded border p-3 text-sm" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }}>
                  <div className="flex items-start justify-between gap-2 mb-1">
                    <div>
                      <div className="font-medium">{d.doctor_name}</div>
                      <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                        {[d.clinic_name, d.city, d.segment].filter(Boolean).join(" · ")}
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-0.5">
                      <span className="pill pill-info">{d.visits_count} visit{d.visits_count !== 1 ? "s" : ""}</span>
                      {(d.demos_booked_count > 0 || d.demos_completed_count > 0) && (
                        <span className="pill pill-success text-[10px]">
                          {d.demos_completed_count > 0 ? `${d.demos_completed_count} demo${d.demos_completed_count !== 1 ? "s" : ""} done` : `${d.demos_booked_count} demo${d.demos_booked_count !== 1 ? "s" : ""} booked`}
                        </span>
                      )}
                      {d.sentiment && d.sentiment !== "—" && (
                        <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{d.sentiment}</span>
                      )}
                    </div>
                  </div>
                  {(d.topics || []).length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {d.topics.map((t) => <span key={t} className="pill pill-info">{t}</span>)}
                    </div>
                  )}
                  {(d.barriers || []).length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {d.barriers.map((b) => <span key={b} className="pill pill-warning">{b}</span>)}
                    </div>
                  )}
                  {(d.promises || []).length > 0 && (
                    <div className="mt-1.5 text-xs" style={{ color: "var(--text-secondary)" }}>
                      <span className="font-semibold">Promises: </span>
                      {d.promises.join("; ")}
                    </div>
                  )}
                  {d.note_excerpt && (
                    <div className="mt-1.5 text-xs italic" style={{ color: "var(--text-muted)" }}>
                      "{d.note_excerpt}"
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {report.notes_from_tm && (
          <section className="mt-5">
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Notes from TM</div>
            <p className="text-sm whitespace-pre-wrap rounded p-3" style={{ background: "var(--bg-paper)", color: "var(--text-primary)" }}>{report.notes_from_tm}</p>
          </section>
        )}

        <section className="mt-6 border-t pt-4" style={{ borderColor: "var(--border-default)" }}>
          <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Manager comments</div>
          <div className="space-y-2 mb-3">
            {(report.comments || []).map((cm) => (
              <div key={cm.id} className="rounded p-3 text-sm" style={{ background: "var(--status-info-bg)" }}>
                <div className="text-xs mb-0.5" style={{ color: "var(--status-info)" }}><strong>{cm.user_name}</strong> · {formatDateTime(cm.created_at)}</div>
                <div style={{ color: "var(--text-primary)" }}>{cm.text}</div>
              </div>
            ))}
            {(report.comments || []).length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>No comments yet.</div>}
          </div>
          <Textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Add a comment / feedback for this TM…" rows={3} className="bg-white" data-testid="manager-comment-textarea" />
          <div className="flex justify-end mt-2">
            <Button onClick={post} disabled={!comment.trim() || posting} data-testid="post-comment-btn" style={{ background: "var(--brand-primary)", color: "white" }}>
              <MessageSquare className="w-4 h-4 mr-1" /> Post comment
            </Button>
          </div>
        </section>

        <DialogFooter>
          <div className="flex flex-1 gap-2">
            <Button variant="outline" size="sm" onClick={() => downloadReportExport(report.id, "pdf", `weekly_report_${report.week_start}`)} data-testid="manager-export-pdf">
              <Download className="w-3 h-3 mr-1" /> PDF
            </Button>
            <Button variant="ghost" size="sm" onClick={() => downloadReportExport(report.id, "csv", `weekly_report_${report.week_start}`)} data-testid="manager-export-csv">
              CSV
            </Button>
          </div>
          <Button variant="outline" onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
