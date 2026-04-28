import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { Textarea } from "../components/ui/textarea";
import { toast } from "sonner";
import { Receipt, Plus, ChevronLeft, ChevronRight, CheckCircle2, XCircle, Clock, FileText, Trash2, Send } from "lucide-react";

const STATUS_KIND = { Draft: "muted", Submitted: "info", Approved: "success", Rejected: "danger" };

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
function fmtAmount(n, ccy = "USD") {
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency: ccy || "USD" }).format(n || 0); } catch { return `${n} ${ccy}`; }
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
  return (
    <div data-testid="expenses-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Expenses</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          {user.role === "TM" ? <>Your <span className="font-medium">monthly receipts.</span></> : <>Team <span className="font-medium">expenses.</span></>}
        </h1>
      </div>
      {user.role === "TM" ? <TMExpenses /> : <ManagerExpenses />}
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
  useEffect(() => { load(month); /* eslint-disable-next-line */ }, [month]);

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
            <Stat label="Total" value={fmtAmount(summary.total, summary.currency)} testId="stat-total" />
            <Stat label="Receipts" value={summary.count} testId="stat-count" />
            <Stat label="Petrol" value={fmtAmount(summary.by_category?.Petrol || 0, summary.currency)} testId="stat-petrol" />
            <Stat label="Food" value={fmtAmount(summary.by_category?.Food || 0, summary.currency)} testId="stat-food" />
          </div>
        )}
      </div>

      {loading ? (
        <div className="text-sm py-12 text-center" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : list.length === 0 ? (
        <div className="rounded-md border p-10 text-center" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }}>
          <Receipt className="w-8 h-8 mx-auto mb-2" style={{ color: "var(--text-muted)" }} />
          <div className="text-sm" style={{ color: "var(--text-secondary)" }}>No expenses for {fmtMonth(month)}. Tap "Add expense" to log your first receipt.</div>
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

function ExpenseRow({ expense, onDelete, onApprove, onReject, isManager }) {
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
          {expense.manager_comment ? ` · Manager: ${expense.manager_comment}` : ""}
        </div>
      </div>
      <div className="text-right flex-shrink-0">
        <div className="font-display text-lg font-medium" style={{ color: "var(--brand-primary)" }}>
          {fmtAmount(expense.amount, expense.currency)}
        </div>
        <div className="flex gap-1 justify-end mt-1">
          {!isManager && expense.status === "Draft" && (
            <button onClick={onDelete} data-testid={`expense-delete-${expense.id}`} title="Delete draft" className="p-1 rounded hover:bg-[var(--bg-paper)]">
              <Trash2 className="w-3.5 h-3.5" style={{ color: "var(--status-danger)" }} />
            </button>
          )}
          {isManager && (expense.status === "Submitted" || expense.status === "Rejected") && (
            <button onClick={onApprove} data-testid={`approve-expense-${expense.id}`} className="text-xs px-2 py-0.5 rounded" style={{ background: "var(--status-success)", color: "white" }}>Approve</button>
          )}
          {isManager && (expense.status === "Submitted" || expense.status === "Approved") && (
            <button onClick={onReject} data-testid={`reject-expense-${expense.id}`} className="text-xs px-2 py-0.5 rounded" style={{ background: "var(--status-danger)", color: "white" }}>Reject</button>
          )}
        </div>
      </div>
    </div>
  );
}

// ===================== MANAGER VIEW =====================
function ManagerExpenses() {
  const [month, setMonth] = useState(monthKey());
  const [tms, setTms] = useState([]);
  const [tmId, setTmId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [rejectFor, setRejectFor] = useState(null);
  const [comment, setComment] = useState("");

  useEffect(() => {
    api.get("/users").then((r) => {
      setTms((r.data || []).filter((u) => u.role === "TM"));
    });
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (month) params.set("month", month);
      if (tmId) params.set("tm_user_id", tmId);
      if (statusFilter) params.set("status", statusFilter);
      const { data } = await api.get(`/expenses?${params.toString()}`);
      setList(data.expenses || []);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [month, tmId, statusFilter]);

  const totals = useMemo(() => {
    const t = list.reduce((s, e) => s + (e.amount || 0), 0);
    return { total: t, count: list.length, currency: list[0]?.currency || "USD" };
  }, [list]);

  const approve = async (id) => {
    try { await api.post(`/expenses/${id}/approve`); toast.success("Approved"); load(); }
    catch { toast.error("Could not approve"); }
  };
  const reject = async () => {
    if (!rejectFor) return;
    try {
      await api.post(`/expenses/${rejectFor.id}/reject`, { comment: comment.trim() || null });
      toast.success("Rejected");
      setRejectFor(null); setComment("");
      load();
    } catch {
      toast.error("Could not reject");
    }
  };

  return (
    <>
      <div className="rounded-md border p-5 mb-5 grid sm:grid-cols-4 gap-3 items-end" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="manager-expenses-filters">
        <div>
          <div className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>Month</div>
          <div className="flex items-center gap-1">
            <button onClick={() => setMonth(shiftMonth(month, -1))} data-testid="manager-month-prev" className="p-1.5 rounded hover:bg-[var(--bg-paper)]"><ChevronLeft className="w-4 h-4" /></button>
            <div className="flex-1 text-center font-medium" style={{ color: "var(--brand-primary)" }} data-testid="manager-current-month">{fmtMonth(month)}</div>
            <button onClick={() => setMonth(shiftMonth(month, 1))} data-testid="manager-month-next" className="p-1.5 rounded hover:bg-[var(--bg-paper)]"><ChevronRight className="w-4 h-4" /></button>
          </div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>TM</div>
          <Select value={tmId || "all"} onValueChange={(v) => setTmId(v === "all" ? "" : v)}>
            <SelectTrigger className="bg-white" data-testid="manager-tm-select"><SelectValue placeholder="All TMs" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All TMs</SelectItem>
              {tms.map((t) => <SelectItem key={t.id} value={t.id}>{t.full_name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <div className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>Status</div>
          <Select value={statusFilter || "all"} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
            <SelectTrigger className="bg-white" data-testid="manager-status-select"><SelectValue placeholder="All statuses" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {["Draft", "Submitted", "Approved", "Rejected"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="rounded p-3" style={{ background: "var(--bg-paper)" }} data-testid="manager-totals">
          <div className="text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Total · {totals.count} receipt{totals.count !== 1 ? "s" : ""}</div>
          <div className="font-display text-xl font-medium" style={{ color: "var(--brand-primary)" }}>{fmtAmount(totals.total, totals.currency)}</div>
        </div>
      </div>

      {loading ? (
        <div className="text-sm py-12 text-center" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : list.length === 0 ? (
        <div className="rounded-md border p-10 text-center" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }}>
          <FileText className="w-8 h-8 mx-auto mb-2" style={{ color: "var(--text-muted)" }} />
          <div className="text-sm" style={{ color: "var(--text-secondary)" }}>No expenses match the current filters.</div>
        </div>
      ) : (
        <div className="rounded-md border overflow-hidden" style={{ borderColor: "var(--border-default)", background: "var(--bg-default)" }} data-testid="manager-expenses-list">
          {list.map((e) => (
            <ExpenseRow key={e.id} expense={e} isManager onApprove={() => approve(e.id)} onReject={() => { setRejectFor(e); setComment(""); }} />
          ))}
        </div>
      )}

      <Dialog open={!!rejectFor} onOpenChange={(v) => { if (!v) { setRejectFor(null); setComment(""); } }}>
        <DialogContent data-testid="reject-dialog">
          <DialogHeader>
            <DialogTitle>Reject expense</DialogTitle>
          </DialogHeader>
          <div className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
            {rejectFor && <>Rejecting <strong>{rejectFor.vendor || rejectFor.category}</strong> ({fmtAmount(rejectFor.amount, rejectFor.currency)}) from {rejectFor.tm_name}.</>}
          </div>
          <Textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Optional reason for the TM…" className="bg-white" data-testid="reject-comment" />
          <DialogFooter>
            <Button variant="ghost" onClick={() => { setRejectFor(null); setComment(""); }}>Cancel</Button>
            <Button onClick={reject} data-testid="confirm-reject" style={{ background: "var(--status-danger)", color: "white" }}><XCircle className="w-4 h-4 mr-1" /> Reject</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
