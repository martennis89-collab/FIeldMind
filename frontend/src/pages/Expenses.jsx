import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { toast } from "sonner";
import { Receipt, Plus, ChevronLeft, ChevronRight, FileText, Trash2, Send, Download } from "lucide-react";

const STATUS_KIND = { Draft: "muted", Submitted: "info" };

function fmtMonth(m) {
  try {
    const [y, mm] = m.split("-");
    const d = new Date(parseInt(y), parseInt(mm) - 1, 1);
    return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  } catch { return m; }
}
function fmtDate(s) {
  if (!s) return "—";
  try { return new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }); } catch { return s; }
}
function fmtAmount(n) {
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency: "EUR" }).format(n || 0); } catch { return `€${(n || 0).toFixed(2)}`; }
}

function StatusPill({ status }) {
  const kind = STATUS_KIND[status] || "muted";
  return <span className={`pill pill-${kind}`} data-testid={`expense-status-${status}`}>{status}</span>;
}

function monthKey(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function shiftMonth(m, delta) {
  const [y, mm] = m.split("-").map(Number);
  const d = new Date(y, mm - 1 + delta, 1);
  return monthKey(d);
}

export default function Expenses() {
  const { user } = useAuth();
  // Phase L — SeniorTM is a hybrid: they log their OWN expenses AND oversee
  // their sub-team's expenses. Toggle between the two views (default = team,
  // matching the Dashboard's SeniorTM toggle default).
  const isSeniorTM = user.role === "SeniorTM";
  const [seniorView, setSeniorView] = useState("team"); // "team" | "personal"
  return (
    <div data-testid="expenses-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Expenses</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          {user.role === "TM" || (isSeniorTM && seniorView === "personal")
            ? <>Your <span className="font-medium">monthly receipts.</span></>
            : <>Team <span className="font-medium">expenses.</span></>}
        </h1>
      </div>
      {isSeniorTM && (
        <div
          className="inline-flex rounded-md border p-0.5 mb-6"
          data-testid="seniortm-expenses-view-toggle"
          style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}
        >
          {[
            { key: "team", label: "Team view" },
            { key: "personal", label: "My expenses" },
          ].map((opt) => {
            const active = seniorView === opt.key;
            return (
              <button
                key={opt.key}
                type="button"
                onClick={() => setSeniorView(opt.key)}
                data-testid={`seniortm-expenses-view-${opt.key}`}
                aria-pressed={active}
                className="text-xs px-4 py-1.5 rounded font-medium transition-colors"
                style={{
                  background: active ? "var(--brand-primary)" : "transparent",
                  color: active ? "white" : "var(--text-secondary)",
                }}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      )}
      {user.role === "TM" && <TMExpenses />}
      {isSeniorTM && seniorView === "personal" && <TMExpenses personal />}
      {isSeniorTM && seniorView === "team" && <ManagerExpenses />}
      {!isSeniorTM && user.role !== "TM" && <ManagerExpenses />}
    </div>
  );
}

// ===================== TM VIEW =====================
function TMExpenses() {
  const [month, setMonth] = useState(monthKey());
  const [list, setList] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const load = async (m = month) => {
    setLoading(true);
    try {
      const [a, b] = await Promise.all([
        api.get(`/expenses?month=${m}`),
        api.get(`/expenses/summary?month=${m}`),
      ]);
      setList(a.data.expenses || []);
      setSummary(b.data || null);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(month); }, [month]);

  const submitMonth = async () => {
    if (!summary?.submittable_drafts) {
      toast.info("No drafts to submit this month");
      return;
    }
    if (!window.confirm(`Submit ${summary.submittable_drafts} draft(s) for ${fmtMonth(month)}? They will be locked from editing.`)) return;
    setSubmitting(true);
    try {
      const { data } = await api.post("/expenses/submit-month", { month });
      toast.success(`Submitted ${data.submitted} expense(s) for ${fmtMonth(month)}`);
      load(month);
    } catch {
      toast.error("Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this draft expense?")) return;
    try {
      await api.delete(`/expenses/${id}`);
      toast.success("Deleted");
      load(month);
    } catch {
      toast.error("Cannot delete (only Drafts)");
    }
  };

  return (
    <>
      <div className="rounded-md border p-5 mb-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="expenses-month-card">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <button onClick={() => setMonth(shiftMonth(month, -1))} data-testid="month-prev" className="p-1.5 rounded hover:bg-[var(--bg-paper)]"><ChevronLeft className="w-4 h-4" /></button>
            <div className="font-display text-xl font-medium min-w-[180px] text-center" style={{ color: "var(--brand-primary)" }} data-testid="current-month">{fmtMonth(month)}</div>
            <button onClick={() => setMonth(shiftMonth(month, 1))} data-testid="month-next" className="p-1.5 rounded hover:bg-[var(--bg-paper)]"><ChevronRight className="w-4 h-4" /></button>
          </div>
          <div className="flex gap-2">
            <Link to="/expenses/log" data-testid="add-expense-btn">
              <Button style={{ background: "var(--brand-secondary)", color: "white" }}>
                <Plus className="w-4 h-4 mr-1" /> Add expense
              </Button>
            </Link>
            <Button variant="outline" onClick={submitMonth} disabled={submitting || !summary?.submittable_drafts} data-testid="submit-month-btn">
              <Send className="w-4 h-4 mr-1" /> Submit month
            </Button>
          </div>
        </div>
        {summary && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
            <Stat label="Total" value={fmtAmount(summary.total)} testId="stat-total" />
            <Stat label="Receipts" value={summary.count} testId="stat-count" />
            <Stat label="Petrol" value={fmtAmount(summary.by_category?.Petrol || 0)} testId="stat-petrol" />
            <Stat label="Food" value={fmtAmount(summary.by_category?.Food || 0)} testId="stat-food" />
          </div>
        )}
      </div>

      {loading ? (
        <div className="text-sm py-12 text-center" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : list.length === 0 ? (
        <div className="rounded-md border p-10 text-center" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }}>
          <Receipt className="w-8 h-8 mx-auto mb-2" style={{ color: "var(--text-muted)" }} />
          <div className="text-sm" style={{ color: "var(--text-secondary)" }}>No expenses for {fmtMonth(month)}. Tap &quot;Add expense&quot; to log your first receipt.</div>
        </div>
      ) : (
        <div className="rounded-md border overflow-hidden" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }} data-testid="expenses-list">
          {list.map((e) => (
            <ExpenseRow key={e.id} expense={e} onDelete={() => remove(e.id)} />
          ))}
        </div>
      )}
    </>
  );
}

function Stat({ label, value, testId }) {
  return (
    <div className="rounded p-3" style={{ background: "var(--bg-paper)" }} data-testid={testId}>
      <div className="text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="font-display text-xl font-medium mt-0.5" style={{ color: "var(--brand-primary)" }}>{value}</div>
    </div>
  );
}

function ReceiptThumb({ expense, size = 56 }) {
  const [err, setErr] = useState(false);
  if (!expense.receipt_image_id || err) {
    return (
      <div className="rounded flex items-center justify-center flex-shrink-0" style={{ width: size, height: size, background: "var(--bg-paper)" }}>
        <Receipt className="w-5 h-5" style={{ color: "var(--text-muted)" }} />
      </div>
    );
  }
  const token = localStorage.getItem("fip_token");
  // We use an Authorization header via axios, but <img> tags can't pass headers — so we fetch as blob client-side.
  return <ReceiptBlobImg expenseId={expense.id} size={size} onError={() => setErr(true)} />;
}

function ReceiptBlobImg({ expenseId, size, onError }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let revoked = null;
    api.get(`/expenses/${expenseId}/receipt`, { responseType: "blob" })
      .then((r) => {
        const url = URL.createObjectURL(r.data);
        revoked = url;
        setSrc(url);
      })
      .catch(() => onError && onError());
    return () => { if (revoked) URL.revokeObjectURL(revoked); };
  }, [expenseId, onError]);
  if (!src) {
    return <div className="rounded flex items-center justify-center flex-shrink-0" style={{ width: size, height: size, background: "var(--bg-paper)" }}><Receipt className="w-5 h-5" style={{ color: "var(--text-muted)" }} /></div>;
  }
  return <img src={src} alt="receipt" data-testid={`receipt-thumb-${expenseId}`} className="rounded object-cover flex-shrink-0" style={{ width: size, height: size }} />;
}

function ExpenseRow({ expense, onDelete, isManager }) {
  return (
    <div className="px-4 py-3 flex items-center gap-3 border-b last:border-b-0" style={{ borderColor: "var(--border-default)" }} data-testid={`expense-row-${expense.id}`}>
      <ReceiptThumb expense={expense} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium" style={{ color: "var(--brand-primary)" }}>{expense.vendor || "(no vendor)"}</span>
          <span className={`pill pill-${expense.category === "Petrol" ? "info" : "warning"}`}>{expense.category}</span>
          <StatusPill status={expense.status} />
          {isManager && expense.tm_name && <span className="text-xs" style={{ color: "var(--text-muted)" }}>· {expense.tm_name}</span>}
        </div>
        <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
          {fmtDate(expense.expense_date)}{expense.notes ? ` · ${expense.notes}` : ""}
        </div>
      </div>
      <div className="text-right flex-shrink-0">
        <div className="font-display text-lg font-medium" style={{ color: "var(--brand-primary)" }}>
          {fmtAmount(expense.amount)}
        </div>
        {!isManager && expense.status === "Draft" && (
          <button onClick={onDelete} data-testid={`expense-delete-${expense.id}`} title="Delete draft" className="p-1 rounded hover:bg-[var(--bg-paper)] mt-1">
            <Trash2 className="w-3.5 h-3.5" style={{ color: "var(--status-danger)" }} />
          </button>
        )}
      </div>
    </div>
  );
}

// ===================== MANAGER VIEW =====================
function ManagerExpenses() {
  const [month, setMonth] = useState(monthKey());
  const [team, setTeam] = useState(null);
  const [tmId, setTmId] = useState("");      // selected TM (for drill-down)
  const [statusFilter, setStatusFilter] = useState("");
  const [list, setList] = useState([]);
  const [loadingTeam, setLoadingTeam] = useState(true);
  const [loadingList, setLoadingList] = useState(false);
  const [downloading, setDownloading] = useState(false);

  // team summary
  useEffect(() => {
    setLoadingTeam(true);
    api.get(`/expenses/team-summary?month=${month}`)
      .then((r) => setTeam(r.data))
      .finally(() => setLoadingTeam(false));
  }, [month]);

  // per-TM drill-down
  useEffect(() => {
    if (!tmId) { setList([]); return; }
    setLoadingList(true);
    const params = new URLSearchParams({ month });
    params.set("tm_user_id", tmId);
    if (statusFilter) params.set("status", statusFilter);
    api.get(`/expenses?${params.toString()}`)
      .then((r) => setList(r.data.expenses || []))
      .finally(() => setLoadingList(false));
  }, [month, tmId, statusFilter]);

  const downloadAll = async (tmFilter = null) => {
    setDownloading(true);
    try {
      const params = new URLSearchParams({ month });
      if (tmFilter) params.set("tm_user_id", tmFilter);
      const res = await api.get(`/expenses/receipts.zip?${params.toString()}`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      const cd = res.headers?.["content-disposition"] || "";
      const match = /filename="?([^"]+)"?/i.exec(cd);
      a.download = match ? match[1] : `receipts_${month}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      toast.success("Receipts downloaded");
    } catch (e) {
      toast.error(e?.response?.status === 404 ? "No receipts to download" : "Could not download");
    } finally {
      setDownloading(false);
    }
  };

  const selectedTm = team?.by_tm?.find((t) => t.tm_user_id === tmId);

  return (
    <>
      {/* Month navigator + grand total */}
      <div className="rounded-md border p-5 mb-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="manager-month-card">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <button onClick={() => setMonth(shiftMonth(month, -1))} data-testid="manager-month-prev" className="p-1.5 rounded hover:bg-[var(--bg-paper)]"><ChevronLeft className="w-4 h-4" /></button>
            <div className="font-display text-xl font-medium min-w-[180px] text-center" style={{ color: "var(--brand-primary)" }} data-testid="manager-current-month">{fmtMonth(month)}</div>
            <button onClick={() => setMonth(shiftMonth(month, 1))} data-testid="manager-month-next" className="p-1.5 rounded hover:bg-[var(--bg-paper)]"><ChevronRight className="w-4 h-4" /></button>
          </div>
          <Button variant="outline" onClick={() => downloadAll()} disabled={downloading || !team?.count} data-testid="download-all-receipts-btn">
            <Download className="w-4 h-4 mr-1" /> Download all as PDFs (ZIP)
          </Button>
        </div>
        {team && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
            <Stat label="Team total" value={fmtAmount(team.grand_total)} testId="manager-stat-total" />
            <Stat label="Receipts" value={team.count} testId="manager-stat-count" />
            <Stat label="Submitted" value={team.submitted_count} testId="manager-stat-submitted" />
            <Stat label="TMs reporting" value={team.by_tm?.length || 0} testId="manager-stat-tms" />
          </div>
        )}
      </div>

      {/* Per-TM table */}
      <div className="rounded-md border mb-5 overflow-hidden" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="manager-by-tm-table">
        <div className="px-4 py-2 border-b text-xs uppercase tracking-widest font-medium" style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}>
          By Territory Manager · {fmtMonth(month)}
        </div>
        {loadingTeam ? (
          <div className="text-sm py-8 text-center" style={{ color: "var(--text-muted)" }}>Loading…</div>
        ) : !team?.by_tm?.length ? (
          <div className="text-sm py-8 text-center" style={{ color: "var(--text-muted)" }}>No expenses recorded for this month yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: "var(--bg-paper)", color: "var(--text-muted)" }}>
                <th className="px-4 py-2 text-left text-[11px] uppercase tracking-widest">Territory Manager</th>
                <th className="px-4 py-2 text-right text-[11px] uppercase tracking-widest">Petrol</th>
                <th className="px-4 py-2 text-right text-[11px] uppercase tracking-widest">Food</th>
                <th className="px-4 py-2 text-right text-[11px] uppercase tracking-widest">Total</th>
                <th className="px-4 py-2 text-center text-[11px] uppercase tracking-widest">Receipts</th>
                <th className="px-4 py-2 text-center text-[11px] uppercase tracking-widest">Submitted</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {team.by_tm.map((row) => (
                <tr key={row.tm_user_id}
                    onClick={() => setTmId(tmId === row.tm_user_id ? "" : row.tm_user_id)}
                    data-testid={`tm-row-${row.tm_user_id}`}
                    className="cursor-pointer"
                    style={{ background: tmId === row.tm_user_id ? "var(--status-info-bg)" : "transparent", borderTop: "1px solid var(--border-default)" }}>
                  <td className="px-4 py-2 font-medium" style={{ color: "var(--brand-primary)" }}>{row.tm_name}</td>
                  <td className="px-4 py-2 text-right">{fmtAmount(row.petrol)}</td>
                  <td className="px-4 py-2 text-right">{fmtAmount(row.food)}</td>
                  <td className="px-4 py-2 text-right font-medium" style={{ color: "var(--brand-primary)" }}>{fmtAmount(row.total)}</td>
                  <td className="px-4 py-2 text-center">{row.count}</td>
                  <td className="px-4 py-2 text-center">
                    {row.submitted_count > 0 ? (
                      <span className="pill pill-info">{row.submitted_count}</span>
                    ) : (
                      <span style={{ color: "var(--text-muted)" }}>—</span>
                    )}
                    {row.draft_count > 0 && <span className="ml-1 text-[11px]" style={{ color: "var(--text-muted)" }}>+ {row.draft_count} draft</span>}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={(e) => { e.stopPropagation(); downloadAll(row.tm_user_id); }}
                      disabled={downloading || row.count === 0}
                      data-testid={`download-tm-receipts-${row.tm_user_id}`}
                      className="text-xs px-2 py-1 rounded hover:bg-[var(--bg-paper)]"
                      style={{ color: "var(--brand-primary)" }}
                      title="Download this TM's receipts">
                      <Download className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Drill-down list */}
      {tmId && (
        <div className="rounded-md border" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="manager-drilldown">
          <div className="px-4 py-2 border-b flex items-center justify-between gap-2 flex-wrap" style={{ borderColor: "var(--border-default)" }}>
            <div className="text-xs uppercase tracking-widest font-medium" style={{ color: "var(--text-muted)" }}>
              {selectedTm?.tm_name || "Receipts"} · {selectedTm?.count || 0} receipt{(selectedTm?.count || 0) !== 1 ? "s" : ""}
            </div>
            <div className="flex items-center gap-2">
              <Select value={statusFilter || "all"} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
                <SelectTrigger className="bg-white h-8 text-xs w-[140px]" data-testid="manager-status-select"><SelectValue placeholder="All statuses" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  {["Draft", "Submitted"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
              <button onClick={() => setTmId("")} className="text-xs px-2 py-1 rounded hover:bg-[var(--bg-paper)]" data-testid="close-drilldown" style={{ color: "var(--text-muted)" }}>
                Close
              </button>
            </div>
          </div>
          {loadingList ? (
            <div className="text-sm py-8 text-center" style={{ color: "var(--text-muted)" }}>Loading…</div>
          ) : list.length === 0 ? (
            <div className="text-sm py-8 text-center" style={{ color: "var(--text-muted)" }}>No receipts match the filter.</div>
          ) : (
            <div data-testid="manager-expenses-list">
              {list.map((e) => <ExpenseRow key={e.id} expense={e} isManager />)}
            </div>
          )}
        </div>
      )}
    </>
  );
}
