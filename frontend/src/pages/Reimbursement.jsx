import React, { useEffect, useMemo, useState } from "react";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import {
  FileText, Plus, Send, CheckCircle2, XCircle, MessageSquare, Wallet, Download,
  AlertTriangle, RefreshCw, MapPin, Car, Receipt, CalendarDays, Trash2,
} from "lucide-react";

const fmtEUR = (v) => (v == null ? "—" : `€ ${Number(v).toFixed(2)}`);
const monthKey = () => new Date().toISOString().slice(0, 7);
const shiftMonth = (m, delta) => {
  const [y, mo] = m.split("-").map(Number);
  const d = new Date(Date.UTC(y, mo - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
};
const STATUS_COLORS = {
  Draft: "bg-[var(--bg-paper)] text-[var(--text-secondary)]",
  Submitted: "bg-[var(--status-info-bg)] text-[var(--status-info)]",
  "Changes Requested": "bg-[var(--status-warning-bg)] text-[var(--status-warning)]",
  Approved: "bg-[var(--status-success-bg)] text-[var(--status-success)]",
  Rejected: "bg-[var(--status-danger-bg)] text-[var(--status-danger)]",
  Paid: "bg-[var(--status-success-bg)] text-[var(--status-success)]",
  "Needs Recalculation": "bg-[var(--status-warning-bg)] text-[var(--status-warning)]",
};

function StatusPill({ status }) {
  return (
    <span data-testid={`report-status-${status.replace(/\s+/g, "-")}`}
          className={`text-[10px] uppercase tracking-widest font-semibold rounded-full px-2 py-0.5 ${STATUS_COLORS[status] || "bg-[var(--bg-paper)]"}`}>
      {status}
    </span>
  );
}

const OWNER_DELETABLE_STATUSES = new Set(["Draft", "Changes Requested"]);
function canDeleteReport(r, user) {
  if (["Admin", "Owner"].includes(user.role)) return true;
  if (["TM", "SeniorTM"].includes(user.role) && r.tm_user_id === user.id && OWNER_DELETABLE_STATUSES.has(r.status)) return true;
  return false;
}

export default function Reimbursement() {
  const { user } = useAuth();
  const [reports, setReports] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [genMonth, setGenMonth] = useState(monthKey());

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/reimbursement/reports");
      setReports(r.data.reports || []);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const generate = async () => {
    setGenerating(true);
    try {
      const r = await api.post("/reimbursement/reports/generate", { month: genMonth });
      toast.success(`Report generated for ${genMonth}`);
      await load();
      setOpenId(r.data.id);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not generate");
    } finally {
      setGenerating(false);
    }
  };

  const deleteReport = async (r) => {
    if (!window.confirm(`Delete the ${r.month} report? This can't be undone. Linked receipts will keep, but the report totals will be lost — you can regenerate anytime.`)) return;
    try {
      await api.delete(`/reimbursement/reports/${r.id}`);
      toast.success(`Report for ${r.month} deleted`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not delete report");
    }
  };

  return (
    <div data-testid="reimbursement-page">
      <div className="mb-6 flex items-baseline justify-between gap-4 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Monthly reimbursement</div>
          <h1 className="font-display text-3xl sm:text-4xl font-light" style={{ color: "var(--brand-primary)" }}>
            {user.role === "TM" ? "Your monthly claims" : user.role === "SeniorTM" ? "Team reimbursement" : "Reimbursement — all teams"}
          </h1>
        </div>
        {(user.role === "TM" || user.role === "SeniorTM") && (
          <div className="flex items-center gap-2" data-testid="generate-controls">
            <input type="month" value={genMonth} onChange={(e) => setGenMonth(e.target.value)}
                   className="px-3 py-2 rounded border text-sm"
                   style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }}
                   data-testid="gen-month-input" />
            <Button onClick={generate} disabled={generating} data-testid="generate-report-btn"
                    style={{ background: "var(--brand-secondary)", color: "white" }}>
              <Plus className="w-4 h-4 mr-1" /> Generate report
            </Button>
          </div>
        )}
      </div>

      {loading && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>}

      {!loading && reports.length === 0 && (
        <div className="rounded-md border p-6 text-center" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="empty-state">
          <FileText className="w-8 h-8 mx-auto mb-2" style={{ color: "var(--text-muted)" }} />
          <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
            No reimbursement reports yet.
            {user.role === "TM" && " Pick a month and hit Generate."}
          </div>
        </div>
      )}

      {!loading && reports.length > 0 && (
        <div className="rounded-md border overflow-hidden" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="reports-table">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)", background: "var(--bg-paper)" }}>
                {user.role !== "TM" && <th className="px-4 py-2">TM</th>}
                <th className="px-4 py-2">Month</th>
                <th className="px-4 py-2">Visits</th>
                <th className="px-4 py-2">KM</th>
                <th className="px-4 py-2">Fuel</th>
                <th className="px-4 py-2">Manual</th>
                <th className="px-4 py-2">To reimburse</th>
                <th className="px-4 py-2">Receipts</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id} className="border-t" style={{ borderColor: "var(--border-default)" }} data-testid={`report-row-${r.id}`}>
                  {user.role !== "TM" && <td className="px-4 py-3">{r.tm_name}</td>}
                  <td className="px-4 py-3 font-mono text-xs">{r.month}</td>
                  <td className="px-4 py-3">{r.total_visits}</td>
                  <td className="px-4 py-3">{(r.total_km || 0).toFixed(1)}</td>
                  <td className="px-4 py-3">{fmtEUR(r.totals?.fuel_cost)}</td>
                  <td className="px-4 py-3">{fmtEUR(r.totals?.manual_expenses_total)}</td>
                  <td className="px-4 py-3 font-medium">{fmtEUR(r.totals?.amount_to_reimburse)}</td>
                  <td className="px-4 py-3">{r.totals?.receipt_invoice_count ?? 0}</td>
                  <td className="px-4 py-3"><StatusPill status={r.status} /></td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <Button size="sm" variant="outline" onClick={() => setOpenId(r.id)} data-testid={`open-report-${r.id}`}>Open</Button>
                      {canDeleteReport(r, user) && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => deleteReport(r)}
                          data-testid={`delete-report-${r.id}`}
                          title="Delete this report"
                          style={{ color: "var(--status-danger)" }}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openId && (
        <ReportDrawer id={openId} onClose={() => setOpenId(null)} onChange={load} user={user} />
      )}
    </div>
  );
}


function ReportDrawer({ id, onClose, onChange, user }) {
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");

  const load = async () => {
    const r = await api.get(`/reimbursement/reports/${id}`);
    setReport(r.data);
  };
  useEffect(() => { load(); }, [id]);

  if (!report) {
    return (
      <div className="fixed inset-0 z-40 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.4)" }}>
        <div className="p-6 rounded-md bg-white">Loading…</div>
      </div>
    );
  }

  // Phase O.2 — TM and SeniorTM (a TM+Manager hybrid) can both edit their own Draft/Changes-Requested reports.
  const canEdit = ["TM", "SeniorTM"].includes(user.role) && report.tm_user_id === user.id && ["Draft", "Changes Requested"].includes(report.status);
  const canReview = ["SeniorTM", "Admin", "Owner"].includes(user.role) && ["Submitted", "Changes Requested"].includes(report.status);
  const canMarkPaid = ["SeniorTM", "Admin", "Owner"].includes(user.role) && report.status === "Approved";
  const missingKm = (report.doctor_breakdown || []).filter((d) => d.match_status === "MissingKM");
  const missingEventKm = (report.event_breakdown || []).filter((e) => e.match_status === "MissingKM");
  const t = report.totals || {};

  const patch = async (body) => {
    setBusy(true);
    try {
      const r = await api.patch(`/reimbursement/reports/${id}`, body);
      setReport(r.data);
      toast.success("Updated");
      onChange();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Update failed");
    } finally { setBusy(false); }
  };

  const setKm = async (doctor_id, km) => {
    setBusy(true);
    try {
      await api.post("/doctor-km", { doctor_id, km_per_visit: Number(km) });
      const r = await api.post(`/reimbursement/reports/${id}/refresh-breakdown`);
      setReport(r.data);
      onChange();
      toast.success("KM saved");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save KM");
    } finally { setBusy(false); }
  };

  const setEventKm = async (event_id, km) => {
    setBusy(true);
    try {
      await api.put(`/events/${event_id}`, { km: Number(km) });
      const r = await api.post(`/reimbursement/reports/${id}/refresh-breakdown`);
      setReport(r.data);
      onChange();
      toast.success("Event KM saved");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not save event KM");
    } finally { setBusy(false); }
  };

  const submitReport = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/reimbursement/reports/${id}/submit`);
      setReport(r.data);
      onChange();
      toast.success("Submitted to Senior TM");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Submit failed");
    } finally { setBusy(false); }
  };

  const review = async (action) => {
    if (["reject", "request-changes"].includes(action) && !comment.trim()) {
      toast.error("A comment is required for this action");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post(`/reimbursement/reports/${id}/${action}`, { comment: comment.trim() || undefined });
      setReport(r.data);
      setComment("");
      onChange();
      toast.success("Done");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    } finally { setBusy(false); }
  };

  const markPaid = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/reimbursement/reports/${id}/mark-paid`);
      setReport(r.data);
      onChange();
      toast.success("Marked as paid");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    } finally { setBusy(false); }
  };

  const downloadPdf = async () => {
    const res = await api.get(`/reimbursement/reports/${id}/pdf`, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    const cd = res.headers?.["content-disposition"] || "";
    const m = /filename="?([^"]+)"?/i.exec(cd);
    a.download = m ? m[1] : `reimbursement_${report.month}.pdf`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  };

  return (
    <div className="fixed inset-0 z-40 flex items-stretch justify-end" data-testid="report-drawer" style={{ background: "rgba(0,0,0,0.4)" }} onClick={onClose}>
      <div className="w-full max-w-3xl h-full overflow-y-auto p-6 shadow-2xl" style={{ background: "var(--bg-default)" }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-baseline justify-between mb-4">
          <div>
            <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Reimbursement</div>
            <h2 className="font-display text-2xl" style={{ color: "var(--brand-primary)" }}>{report.tm_name} — {report.month}</h2>
          </div>
          <div className="flex items-center gap-2">
            <StatusPill status={report.status} />
            <button onClick={onClose} data-testid="close-drawer" className="text-sm px-2 py-1 rounded hover:bg-[var(--bg-paper)]">Close</button>
          </div>
        </div>

        {/* Totals */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6" data-testid="report-totals">
          <Stat label="Total visits" value={report.total_visits ?? 0} />
          <Stat label="Total KM" value={(report.total_km || 0).toFixed(1)} />
          <Stat label="Litres used" value={(t.litres_used || 0).toFixed(2)} />
          <Stat label="Fuel cost" value={fmtEUR(t.fuel_cost)} />
          <Stat label="Manual expenses" value={fmtEUR(t.manual_expenses_total)} />
          <Stat label="Total reimbursable" value={fmtEUR(t.total_reimbursable)} />
          <Stat label="Already reimbursed" value={fmtEUR(t.already_reimbursed)} />
          <Stat label="To reimburse" value={fmtEUR(t.amount_to_reimburse)} strong />
        </div>

        {/* Fuel inputs */}
        <div className="rounded-md border p-4 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="fuel-inputs">
          <div className="text-xs uppercase tracking-widest mb-3" style={{ color: "var(--text-muted)" }}><Car className="w-3 h-3 inline mr-1" /> Fuel</div>
          <div className="grid grid-cols-2 gap-4">
            <label className="block">
              <div className="text-xs mb-1" style={{ color: "var(--text-secondary)" }}>Consumption (L/100km)</div>
              <input type="number" step="0.1" defaultValue={report.fuel_consumption_l_per_100km}
                     disabled={!(["SeniorTM", "Admin", "Owner"].includes(user.role))}
                     onBlur={(e) => patch({ fuel_consumption_l_per_100km: Number(e.target.value) })}
                     className="w-full px-3 py-2 rounded border text-sm" style={{ borderColor: "var(--border-default)" }}
                     data-testid="fuel-consumption-input" />
            </label>
            <label className="block">
              <div className="text-xs mb-1" style={{ color: "var(--text-secondary)" }}>Price per litre (€) {canEdit && <span style={{ color: "var(--status-danger)" }}>*</span>}</div>
              <input type="number" step="0.001" defaultValue={report.fuel_price_per_l ?? ""}
                     disabled={!canEdit}
                     onBlur={(e) => e.target.value && patch({ fuel_price_per_l: Number(e.target.value) })}
                     className="w-full px-3 py-2 rounded border text-sm" style={{ borderColor: "var(--border-default)" }}
                     data-testid="fuel-price-input" placeholder="e.g. 1.85" />
            </label>
          </div>
        </div>

        {/* Missing KM */}
        {missingKm.length > 0 && (
          <div className="rounded-md border p-4 mb-6" style={{ background: "var(--status-warning-bg)", borderColor: "var(--status-warning)" }} data-testid="missing-km-panel">
            <div className="text-xs uppercase tracking-widest mb-3 flex items-center gap-1" style={{ color: "var(--status-warning)" }}>
              <AlertTriangle className="w-3 h-3" /> Missing KM ({missingKm.length}) — required before submit
            </div>
            <div className="space-y-2">
              {missingKm.map((d) => (
                <MissingKMRow key={d.doctor_id} d={d} onSave={(km) => setKm(d.doctor_id, km)} disabled={!canEdit || busy} />
              ))}
            </div>
          </div>
        )}

        {/* Doctor breakdown */}
        <div className="rounded-md border mb-6 overflow-hidden" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="doctor-breakdown">
          <div className="px-4 py-2 text-xs uppercase tracking-widest flex items-center justify-between" style={{ color: "var(--text-muted)", background: "var(--bg-paper)" }}>
            <span><MapPin className="w-3 h-3 inline mr-1" /> Doctor breakdown</span>
            {canEdit && (
              <button onClick={async () => { const r = await api.post(`/reimbursement/reports/${id}/refresh-breakdown`); setReport(r.data); toast.success("Refreshed"); }}
                      className="text-[11px] flex items-center gap-1 hover:text-[var(--brand-primary)]" data-testid="refresh-breakdown-btn">
                <RefreshCw className="w-3 h-3" /> Refresh
              </button>
            )}
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px]" style={{ color: "var(--text-muted)" }}>
                <th className="px-4 py-2">Doctor</th>
                <th className="px-4 py-2">City</th>
                <th className="px-4 py-2">Visits</th>
                <th className="px-4 py-2">KM/visit</th>
                <th className="px-4 py-2">Total KM</th>
                <th className="px-4 py-2">Match</th>
              </tr>
            </thead>
            <tbody>
              {(report.doctor_breakdown || []).map((d) => (
                <tr key={d.doctor_id} className="border-t" style={{ borderColor: "var(--border-default)" }} data-testid={`doctor-row-${d.doctor_id}`}>
                  <td className="px-4 py-2">{d.doctor_name}</td>
                  <td className="px-4 py-2">{d.city || "—"}</td>
                  <td className="px-4 py-2">{d.visit_count}</td>
                  <td className="px-4 py-2">{d.km_per_visit != null ? d.km_per_visit.toFixed(1) : "—"}</td>
                  <td className="px-4 py-2">{d.total_km != null ? d.total_km.toFixed(1) : "—"}</td>
                  <td className="px-4 py-2">
                    <span className={`text-[10px] px-2 py-0.5 rounded-full ${d.match_status === "Matched" ? "bg-[var(--status-success-bg)] text-[var(--status-success)]" : "bg-[var(--status-danger-bg)] text-[var(--status-danger)]"}`}>
                      {d.match_status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Event breakdown */}
        <div className="rounded-md border mb-6 overflow-hidden" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="event-breakdown">
          <div className="px-4 py-2 text-xs uppercase tracking-widest flex items-center justify-between" style={{ color: "var(--text-muted)", background: "var(--bg-paper)" }}>
            <span><CalendarDays className="w-3 h-3 inline mr-1" /> Events attended ({(report.event_breakdown || []).length})</span>
            {missingEventKm.length > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: "var(--status-warning-bg)", color: "var(--status-warning)" }}>
                {missingEventKm.length} missing KM
              </span>
            )}
          </div>
          {(report.event_breakdown || []).length === 0 ? (
            <div className="text-xs px-4 py-3" style={{ color: "var(--text-muted)" }}>
              No events this month. Book one from the Calendar to include event travel in your reimbursement.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px]" style={{ color: "var(--text-muted)" }}>
                  <th className="px-4 py-2">Event</th>
                  <th className="px-4 py-2">Date</th>
                  <th className="px-4 py-2">Location</th>
                  <th className="px-4 py-2">KM</th>
                  <th className="px-4 py-2">Match</th>
                </tr>
              </thead>
              <tbody>
                {(report.event_breakdown || []).map((ev) => (
                  <tr key={ev.event_id} className="border-t align-middle" style={{ borderColor: "var(--border-default)" }} data-testid={`event-row-${ev.event_id}`}>
                    <td className="px-4 py-2">{ev.title}</td>
                    <td className="px-4 py-2 whitespace-nowrap">{(ev.scheduled_at || "").slice(0, 10)}</td>
                    <td className="px-4 py-2">{ev.location || "—"}</td>
                    <td className="px-4 py-2">
                      {canEdit ? (
                        <EventKMInput
                          initial={ev.km}
                          testId={`event-km-input-${ev.event_id}`}
                          saveTestId={`event-km-save-${ev.event_id}`}
                          onSave={(km) => setEventKm(ev.event_id, km)}
                          disabled={busy}
                        />
                      ) : (
                        ev.km != null ? `${ev.km.toFixed(1)} km` : "—"
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <span className={`text-[10px] px-2 py-0.5 rounded-full ${ev.match_status === "Matched" ? "bg-[var(--status-success-bg)] text-[var(--status-success)]" : "bg-[var(--status-warning-bg)] text-[var(--status-warning)]"}`} data-testid={`event-match-${ev.event_id}`}>
                        {ev.match_status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Expenses summary */}
        <div className="rounded-md border p-4 mb-6" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="expenses-panel">
          <div className="text-xs uppercase tracking-widest mb-3 flex items-center justify-between" style={{ color: "var(--text-muted)" }}>
            <span><Receipt className="w-3 h-3 inline mr-1" /> Manual expenses ({(report.expenses || []).length})</span>
            {canEdit && (
              <a href={`/expenses/log?reimbursement_report_id=${id}`} className="text-[11px] hover:text-[var(--brand-primary)]" data-testid="add-expense-link">
                + Add expense
              </a>
            )}
          </div>
          {(report.expenses || []).length === 0 ? (
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>No receipts attached yet.</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px]" style={{ color: "var(--text-muted)" }}>
                  <th className="px-2 py-1">Category</th>
                  <th className="px-2 py-1">Vendor</th>
                  <th className="px-2 py-1">Date</th>
                  <th className="px-2 py-1">Amount</th>
                  <th className="px-2 py-1">Receipt</th>
                </tr>
              </thead>
              <tbody>
                {(report.expenses || []).map((e) => (
                  <tr key={e.id} className="border-t" style={{ borderColor: "var(--border-default)" }} data-testid={`expense-row-${e.id}`}>
                    <td className="px-2 py-1">{e.category}</td>
                    <td className="px-2 py-1">{e.vendor || "—"}</td>
                    <td className="px-2 py-1 font-mono text-xs">{(e.expense_date || "").slice(0, 10)}</td>
                    <td className="px-2 py-1">{fmtEUR(e.amount)}</td>
                    <td className="px-2 py-1 text-[11px]">
                      {e.receipt_image_id ? <span style={{ color: "var(--status-success)" }}>Attached</span> :
                       e.exception_approved ? <span style={{ color: "var(--status-warning)" }}>Exception</span> :
                       <span style={{ color: "var(--status-danger)" }}>Missing</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Comments */}
        {(report.comments || []).length > 0 && (
          <div className="rounded-md border p-4 mb-6" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }} data-testid="comments-panel">
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>
              <MessageSquare className="w-3 h-3 inline mr-1" /> Comments
            </div>
            {(report.comments || []).map((c, i) => (
              <div key={i} className="text-xs mb-1"><b>{c.role}</b> · {c.at?.slice(0, 16).replace("T", " ")} — {c.text}</div>
            ))}
          </div>
        )}

        {/* Actions */}
        <div className="flex flex-wrap gap-2 items-center" data-testid="report-actions">
          <Button onClick={downloadPdf} variant="outline" data-testid="download-pdf-btn">
            <Download className="w-4 h-4 mr-1" /> PDF
          </Button>
          {canEdit && (
            <Button onClick={submitReport} disabled={busy} data-testid="submit-report-btn"
                    style={{ background: "var(--brand-secondary)", color: "white" }}>
              <Send className="w-4 h-4 mr-1" /> Submit
            </Button>
          )}
          {canReview && (
            <>
              <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (required for reject / changes)"
                     className="px-3 py-2 rounded border text-sm flex-1 min-w-[240px]" style={{ borderColor: "var(--border-default)" }}
                     data-testid="review-comment" />
              <Button onClick={() => review("approve")} disabled={busy} data-testid="approve-report-btn"
                      style={{ background: "var(--status-success)", color: "white" }}>
                <CheckCircle2 className="w-4 h-4 mr-1" /> Approve
              </Button>
              <Button onClick={() => review("request-changes")} disabled={busy} data-testid="request-changes-btn" variant="outline">
                <MessageSquare className="w-4 h-4 mr-1" /> Request changes
              </Button>
              <Button onClick={() => review("reject")} disabled={busy} data-testid="reject-report-btn"
                      style={{ background: "var(--status-danger)", color: "white" }}>
                <XCircle className="w-4 h-4 mr-1" /> Reject
              </Button>
            </>
          )}
          {canMarkPaid && (
            <Button onClick={markPaid} disabled={busy} data-testid="mark-paid-btn"
                    style={{ background: "var(--brand-primary)", color: "white" }}>
              <Wallet className="w-4 h-4 mr-1" /> Mark as paid
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}


function Stat({ label, value, strong }) {
  return (
    <div className="rounded border px-3 py-2" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}>
      <div className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className={`mt-0.5 ${strong ? "text-lg font-semibold" : "text-sm font-medium"}`} style={{ color: "var(--brand-primary)" }}>{value}</div>
    </div>
  );
}


function MissingKMRow({ d, onSave, disabled }) {
  const [km, setKm] = useState("");
  return (
    <div className="flex items-center gap-2 text-sm" data-testid={`missing-km-${d.doctor_id}`}>
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{d.doctor_name}</div>
        <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>{d.city || "—"} · {d.visit_count} visit(s)</div>
      </div>
      <input type="number" step="0.5" value={km} onChange={(e) => setKm(e.target.value)}
             placeholder="km / visit" className="w-32 px-2 py-1 rounded border text-sm"
             style={{ borderColor: "var(--border-default)" }} data-testid={`missing-km-input-${d.doctor_id}`} />
      <Button size="sm" disabled={disabled || !km} onClick={() => onSave(km)} data-testid={`missing-km-save-${d.doctor_id}`}>Save</Button>
    </div>
  );
}

function EventKMInput({ initial, testId, saveTestId, onSave, disabled }) {
  const [km, setKm] = useState(initial == null ? "" : String(initial));
  const [dirty, setDirty] = useState(false);
  const changed = km !== "" && Number(km) !== Number(initial);
  return (
    <div className="flex items-center gap-1.5">
      <input
        type="number"
        step="0.5"
        min="0"
        value={km}
        onChange={(e) => { setKm(e.target.value); setDirty(true); }}
        placeholder="km"
        className="w-24 px-2 py-1 rounded border text-sm"
        style={{ borderColor: "var(--border-default)" }}
        data-testid={testId}
      />
      <Button
        size="sm"
        disabled={disabled || km === "" || (!dirty && !changed)}
        onClick={() => onSave(km)}
        data-testid={saveTestId}
      >
        Save
      </Button>
    </div>
  );
}

