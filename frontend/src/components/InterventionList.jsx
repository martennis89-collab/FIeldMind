import React, { useEffect, useState, useCallback } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { toast } from "sonner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./ui/tabs";
import {
  AlertTriangle, CheckCircle2, X, Play, Edit2, Trash2, Sparkles, ClipboardCheck,
} from "lucide-react";

const SEVERITY_RANK = { Critical: 0, High: 1, Medium: 2, Low: 3 };
const STATUS_TABS = ["Open", "In Progress", "Completed", "Dismissed"];

const sevColor = (s) => ({
  Critical: { bg: "var(--status-danger-bg)", fg: "var(--status-danger)" },
  High:     { bg: "var(--status-danger-bg)", fg: "var(--status-danger)" },
  Medium:   { bg: "var(--status-warning-bg)", fg: "var(--status-warning)" },
  Low:      { bg: "var(--status-info-bg)", fg: "var(--status-info)" },
}[s] || { bg: "var(--bg-paper)", fg: "var(--text-secondary)" });

function InterventionRow({ row, canEdit, onAction, onDelete, onEdit, userMap }) {
  const c = sevColor(row.severity);
  const tmLabel = userMap[row.tm_user_id]?.full_name || row.tm_user_id?.slice(0, 8) || "Unassigned";
  return (
    <div
      data-testid={`intervention-row-${row.id}`}
      data-status={row.status}
      data-severity={row.severity}
      className="rounded-md border p-4"
      style={{
        background: "var(--bg-default)",
        borderColor: row.severity === "High" || row.severity === "Critical" ? c.fg : "var(--border-default)",
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="w-9 h-9 rounded-md flex-shrink-0 flex items-center justify-center"
          style={{ background: c.bg, color: c.fg }}
        >
          <AlertTriangle className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span className="pill" style={{ background: c.bg, color: c.fg }} data-testid={`intervention-severity-${row.id}`}>
              {row.severity}
            </span>
            <span className="pill pill-muted">{row.track_type}</span>
            {row.created_from_insight && (
              <span className="pill" style={{ background: "var(--status-info-bg)", color: "var(--status-info)" }}>
                <Sparkles className="w-3 h-3" /> From insight
              </span>
            )}
          </div>
          <div className="font-display text-base font-semibold" style={{ color: "var(--brand-primary)" }}>{row.issue_title}</div>
          <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
            TM: <span data-testid={`intervention-tm-${row.id}`}>{tmLabel}</span>
            {row.due_date && <> · Due: <span data-testid={`intervention-due-${row.id}`}>{row.due_date}</span></>}
          </div>
          {row.issue_description && (
            <p className="text-sm mt-2" style={{ color: "var(--text-secondary)" }}>{row.issue_description}</p>
          )}
          {row.suggested_action && (
            <div className="mt-3 rounded px-3 py-2 text-sm" style={{ background: "var(--bg-paper)", color: "var(--text-primary)" }}>
              → {row.suggested_action}
            </div>
          )}
          {row.manager_note && (
            <div className="mt-2 text-sm italic" style={{ color: "var(--text-secondary)" }}>
              Manager note: {row.manager_note}
            </div>
          )}
        </div>
      </div>
      {canEdit && row.status !== "Completed" && row.status !== "Dismissed" && (
        <div className="mt-3 flex flex-wrap gap-2 justify-end">
          {row.status === "Open" && (
            <button
              type="button"
              data-testid={`intervention-in-progress-${row.id}`}
              onClick={() => onAction(row.id, "in-progress")}
              className="text-xs px-3 py-1.5 rounded border flex items-center gap-1 hover:bg-[var(--bg-paper)]"
              style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
            >
              <Play className="w-3 h-3" /> Start
            </button>
          )}
          <button
            type="button"
            data-testid={`intervention-edit-${row.id}`}
            onClick={() => onEdit(row)}
            className="text-xs px-3 py-1.5 rounded border flex items-center gap-1 hover:bg-[var(--bg-paper)]"
            style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
          >
            <Edit2 className="w-3 h-3" /> Edit
          </button>
          <button
            type="button"
            data-testid={`intervention-dismiss-${row.id}`}
            onClick={() => onAction(row.id, "dismiss")}
            className="text-xs px-3 py-1.5 rounded border flex items-center gap-1 hover:bg-[var(--bg-paper)]"
            style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
          >
            <X className="w-3 h-3" /> Dismiss
          </button>
          <button
            type="button"
            data-testid={`intervention-complete-${row.id}`}
            onClick={() => onAction(row.id, "complete")}
            className="text-xs px-3 py-1.5 rounded border flex items-center gap-1"
            style={{ background: "var(--brand-primary)", color: "white", borderColor: "var(--brand-primary)" }}
          >
            <CheckCircle2 className="w-3 h-3" /> Complete
          </button>
          <button
            type="button"
            data-testid={`intervention-delete-${row.id}`}
            onClick={() => onDelete(row.id)}
            className="text-xs px-2 py-1.5 rounded border flex items-center gap-1 hover:bg-[var(--bg-paper)]"
            style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}
            title="Delete"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      )}
    </div>
  );
}

function EditDialog({ row, onClose, onSaved }) {
  const [issueTitle, setIssueTitle] = useState(row.issue_title || "");
  const [managerNote, setManagerNote] = useState(row.manager_note || "");
  const [dueDate, setDueDate] = useState(row.due_date || "");
  const [severity, setSeverity] = useState(row.severity || "Medium");
  const save = async () => {
    try {
      await api.put(`/interventions/${row.id}`, {
        issue_title: issueTitle, manager_note: managerNote || null,
        due_date: dueDate || null, severity,
      });
      toast.success("Intervention updated.");
      onSaved();
    } catch {
      toast.error("Could not save.");
    }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.5)" }} data-testid="intervention-edit-dialog">
      <div className="rounded-md border p-6 w-full max-w-md" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
        <div className="font-display text-lg font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Edit intervention</div>
        <label className="block text-xs uppercase tracking-widest mb-1 mt-3" style={{ color: "var(--text-muted)" }}>Title</label>
        <input data-testid="intervention-edit-title" value={issueTitle} onChange={(e) => setIssueTitle(e.target.value)} className="w-full px-3 py-2 rounded border" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }} />
        <label className="block text-xs uppercase tracking-widest mb-1 mt-3" style={{ color: "var(--text-muted)" }}>Severity</label>
        <select data-testid="intervention-edit-severity" value={severity} onChange={(e) => setSeverity(e.target.value)} className="w-full px-3 py-2 rounded border" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}>
          {["Critical", "High", "Medium", "Low"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <label className="block text-xs uppercase tracking-widest mb-1 mt-3" style={{ color: "var(--text-muted)" }}>Due date</label>
        <input data-testid="intervention-edit-due" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className="w-full px-3 py-2 rounded border" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }} />
        <label className="block text-xs uppercase tracking-widest mb-1 mt-3" style={{ color: "var(--text-muted)" }}>Manager note</label>
        <textarea data-testid="intervention-edit-note" value={managerNote} onChange={(e) => setManagerNote(e.target.value)} rows={3} className="w-full px-3 py-2 rounded border" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }} />
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="text-sm px-3 py-1.5 rounded border" style={{ borderColor: "var(--border-default)" }}>Cancel</button>
          <button type="button" data-testid="intervention-edit-save" onClick={save} className="text-sm px-3 py-1.5 rounded" style={{ background: "var(--brand-primary)", color: "white" }}>Save</button>
        </div>
      </div>
    </div>
  );
}

/**
 * Main Phase F surface. Variant decides the lens:
 *  - "manager" → full Manager Intervention tab (status tabs, filters, edit, delete).
 *  - "tm"      → read-only Manager Follow-Up list embedded in the TM dashboard.
 */
export default function InterventionList({ variant = "manager" }) {
  const { user } = useAuth();
  const [rows, setRows] = useState(null);
  const [usersById, setUsersById] = useState({});
  const [activeTab, setActiveTab] = useState("Open");
  const [filterSev, setFilterSev] = useState("All");
  const [filterTM, setFilterTM] = useState("All");
  const [filterTrack, setFilterTrack] = useState("All");
  const [editing, setEditing] = useState(null);

  const canEdit = variant === "manager" && (user?.role === "Manager" || user?.role === "Admin" || user?.role === "Owner");

  const load = useCallback(async () => {
    try {
      const params = { include_dismissed: true, include_completed: true };
      const r = await api.get("/interventions", { params });
      setRows(Array.isArray(r.data) ? r.data : []);
    } catch {
      setRows([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Build user map for TM display names (Manager+Admin only)
  useEffect(() => {
    if (!canEdit) return;
    api.get("/users").then((r) => {
      const map = {};
      (r.data || []).forEach((u) => { map[u.id] = u; });
      setUsersById(map);
    }).catch(() => {});
  }, [canEdit]);

  const onAction = async (id, action) => {
    try {
      await api.post(`/interventions/${id}/${action}`);
      await load();
      const msg = { "in-progress": "Marked in progress.", complete: "Marked complete.", dismiss: "Dismissed." }[action] || "Updated.";
      toast.success(msg);
    } catch {
      toast.error("Action failed.");
    }
  };

  const onDelete = async (id) => {
    if (!window.confirm("Delete intervention? This is a soft delete and can be restored.")) return;
    try {
      await api.delete(`/interventions/${id}`);
      await load();
      toast.success("Intervention deleted.");
    } catch {
      toast.error("Could not delete.");
    }
  };

  if (rows == null) {
    return <div className="text-sm" style={{ color: "var(--text-muted)" }} data-testid={`interventions-${variant}-loading`}>Loading…</div>;
  }

  const distinctTMs = Array.from(new Set(rows.map((r) => r.tm_user_id).filter(Boolean)));
  const filtered = rows
    .filter((r) => (filterSev === "All" || r.severity === filterSev))
    .filter((r) => (filterTM === "All" || r.tm_user_id === filterTM))
    .filter((r) => (filterTrack === "All" || r.track_type === filterTrack))
    .sort((a, b) => (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9) || (b.created_at || "").localeCompare(a.created_at || ""));

  // ---------- TM read-only embedded variant ----------
  if (variant === "tm") {
    const visible = filtered.filter((r) => r.status !== "Dismissed");
    if (visible.length === 0) return null;
    return (
      <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="tm-followup-panel">
        <div className="mb-4">
          <div className="text-xs uppercase tracking-widest flex items-center gap-2" style={{ color: "var(--text-muted)" }}>
            <ClipboardCheck className="w-3 h-3" /> From your manager
          </div>
          <h2 className="font-display text-xl font-medium" style={{ color: "var(--brand-primary)" }}>Manager follow-up</h2>
          <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>Action items your manager has flagged for you.</p>
        </div>
        <div className="space-y-3">
          {visible.map((row) => (
            <InterventionRow key={row.id} row={row} canEdit={false} userMap={usersById}
                             onAction={() => {}} onDelete={() => {}} onEdit={() => {}} />
          ))}
        </div>
      </div>
    );
  }

  // ---------- Manager full variant ----------
  const grouped = STATUS_TABS.reduce((acc, t) => {
    acc[t] = filtered.filter((r) => r.status === t);
    return acc;
  }, {});

  return (
    <div className="rounded-md border p-6 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="interventions-manager-panel">
      <div className="flex items-start justify-between flex-wrap gap-3 mb-4">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Manager interventions</div>
          <h2 className="font-display text-xl font-medium" style={{ color: "var(--brand-primary)" }}>Action items</h2>
          <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>Corrective actions assigned to TMs. Created manually or directly from insight cards.</p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <select data-testid="interventions-filter-tm" value={filterTM} onChange={(e) => setFilterTM(e.target.value)} className="text-xs px-2 py-1.5 rounded border" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }}>
            <option value="All">All TMs</option>
            {distinctTMs.map((tm) => <option key={tm} value={tm}>{(usersById[tm]?.full_name) || tm.slice(0, 8)}</option>)}
          </select>
          <select data-testid="interventions-filter-severity" value={filterSev} onChange={(e) => setFilterSev(e.target.value)} className="text-xs px-2 py-1.5 rounded border" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }}>
            <option value="All">All severities</option>
            {["Critical", "High", "Medium", "Low"].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select data-testid="interventions-filter-track" value={filterTrack} onChange={(e) => setFilterTrack(e.target.value)} className="text-xs px-2 py-1.5 rounded border" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }}>
            <option value="All">All tracks</option>
            {["General", "iTero", "Invisalign", "Both"].map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="bg-[var(--bg-paper)]">
          {STATUS_TABS.map((t) => (
            <TabsTrigger key={t} value={t} data-testid={`intervention-tab-${t.replace(" ", "-").toLowerCase()}`}>
              {t} ({grouped[t].length})
            </TabsTrigger>
          ))}
        </TabsList>
        {STATUS_TABS.map((t) => (
          <TabsContent key={t} value={t}>
            <div className="space-y-3 mt-4">
              {grouped[t].length === 0 ? (
                <div className="rounded-md border p-8 text-center" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }} data-testid={`interventions-${t.replace(" ", "-").toLowerCase()}-empty`}>
                  <CheckCircle2 className="w-8 h-8 mx-auto mb-2" style={{ color: "var(--status-success)" }} />
                  <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No {t.toLowerCase()} interventions.</p>
                </div>
              ) : (
                grouped[t].map((row) => (
                  <InterventionRow
                    key={row.id} row={row} canEdit={canEdit} userMap={usersById}
                    onAction={onAction} onDelete={onDelete} onEdit={(r) => setEditing(r)}
                  />
                ))
              )}
            </div>
          </TabsContent>
        ))}
      </Tabs>

      {editing && (
        <EditDialog row={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />
      )}
    </div>
  );
}
