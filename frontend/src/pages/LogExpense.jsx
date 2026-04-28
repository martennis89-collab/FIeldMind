import React, { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { toast } from "sonner";
import { Camera, Sparkles, ChevronLeft, AlertTriangle, Loader2, Save } from "lucide-react";

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function LogExpense() {
  const navigate = useNavigate();
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [extracting, setExtracting] = useState(false);
  const [extracted, setExtracted] = useState(null);
  const [duplicateOf, setDuplicateOf] = useState(null);

  const [category, setCategory] = useState("Petrol");
  const [date, setDate] = useState(todayISO());
  const [amount, setAmount] = useState("");
  const [vendor, setVendor] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const onPick = () => fileRef.current?.click();

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!/^image\//.test(f.type)) {
      toast.error("Please pick an image");
      return;
    }
    if (f.size > 8 * 1024 * 1024) {
      toast.error("Image too large (max 8 MB)");
      return;
    }
    setFile(f);
    setPreview(URL.createObjectURL(f));
    setExtracting(true);
    setExtracted(null);
    setDuplicateOf(null);
    try {
      const fd = new FormData();
      fd.append("receipt", f);
      const { data } = await api.post("/expenses/extract", fd);
      const ex = data.extracted || {};
      setExtracted(ex);
      if (data.duplicate_of) setDuplicateOf(data.duplicate_of);
      // Pre-fill form with whatever AI returned (currency forced to EUR — ignored)
      if (ex.amount != null) setAmount(String(ex.amount));
      if (ex.expense_date) setDate(ex.expense_date);
      if (ex.vendor) setVendor(ex.vendor);
      if (ex.category_hint) setCategory(ex.category_hint);
      if (ex.notes && !notes) setNotes(ex.notes);
      const conf = ex.confidence != null ? Math.round(ex.confidence * 100) : 0;
      if (conf >= 50) {
        toast.success(`Extracted (${conf}% confidence) — review & save`);
      } else {
        toast.warning("Low confidence — please verify the fields below");
      }
    } catch {
      toast.error("Couldn't read the receipt — fill fields manually");
    } finally {
      setExtracting(false);
    }
  };

  const save = async () => {
    if (!amount || parseFloat(amount) <= 0) { toast.error("Enter the amount"); return; }
    if (!date) { toast.error("Pick a date"); return; }
    if (!category) { toast.error("Pick a category"); return; }
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("expense_date", date);
      fd.append("category", category);
      fd.append("amount", String(amount));
      if (vendor.trim()) fd.append("vendor", vendor.trim());
      if (notes.trim()) fd.append("notes", notes.trim());
      if (file) fd.append("receipt", file);
      const { data } = await api.post("/expenses", fd);
      toast.success(`Saved ${data.expense?.category} expense`);
      navigate("/expenses");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const conf = extracted?.confidence != null ? Math.round(extracted.confidence * 100) : null;

  return (
    <div className="max-w-xl mx-auto" data-testid="log-expense-page">
      <div className="mb-5 flex items-center gap-2">
        <button onClick={() => navigate(-1)} className="p-1.5 rounded hover:bg-[var(--bg-paper)]" data-testid="back-btn"><ChevronLeft className="w-4 h-4" /></button>
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Add receipt</div>
          <h1 className="font-display text-2xl sm:text-3xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Log an <span className="font-medium">expense.</span>
          </h1>
        </div>
      </div>

      {/* Photo / Upload */}
      <div className="rounded-md border p-5 space-y-3" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
        <input ref={fileRef} type="file" accept="image/*" capture="environment" onChange={onFile} className="hidden" data-testid="receipt-file-input" />
        {preview ? (
          <div className="relative">
            <img src={preview} alt="receipt" className="w-full max-h-[260px] object-contain rounded bg-white" data-testid="receipt-preview" />
            <Button variant="outline" size="sm" onClick={onPick} className="absolute top-2 right-2 bg-white" data-testid="retake-btn">
              <Camera className="w-3 h-3 mr-1" /> Retake
            </Button>
          </div>
        ) : (
          <button
            onClick={onPick}
            data-testid="capture-btn"
            className="w-full rounded-md border-2 border-dashed py-12 flex flex-col items-center justify-center gap-2 transition-all hover:bg-[var(--bg-paper)]"
            style={{ borderColor: "var(--border-default)" }}
          >
            <Camera className="w-7 h-7" style={{ color: "var(--brand-primary)" }} />
            <div className="font-medium" style={{ color: "var(--brand-primary)" }}>Take or upload receipt</div>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>AI will read amount, date, vendor automatically</div>
          </button>
        )}

        {extracting && (
          <div className="flex items-center gap-2 text-sm px-3 py-2 rounded" style={{ background: "var(--status-info-bg)", color: "var(--status-info)" }} data-testid="extracting-banner">
            <Loader2 className="w-4 h-4 animate-spin" /> Reading receipt with AI…
          </div>
        )}
        {extracted && !extracting && conf != null && (
          <div className="flex items-center gap-2 text-xs px-3 py-2 rounded" style={{ background: "var(--status-info-bg)", color: "var(--status-info)" }} data-testid="extracted-banner">
            <Sparkles className="w-3.5 h-3.5" /> AI confidence: <strong>{conf}%</strong> · review the fields below
          </div>
        )}
        {duplicateOf && (
          <div className="flex items-start gap-2 text-xs px-3 py-2 rounded" style={{ background: "var(--status-warning-bg)", color: "var(--status-warning)" }} data-testid="duplicate-warning">
            <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>Looks like you already uploaded this receipt — saving it will create a second entry.</span>
          </div>
        )}
      </div>

      {/* Category */}
      <div className="rounded-md border p-5 mt-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="category-section">
        <Label className="mb-2 block">Category</Label>
        <div className="flex gap-2">
          {[
            { v: "Petrol", emoji: "⛽" },
            { v: "Food", emoji: "🍔" },
          ].map((opt) => {
            const active = category === opt.v;
            return (
              <button
                key={opt.v}
                type="button"
                onClick={() => setCategory(opt.v)}
                data-testid={`cat-${opt.v.toLowerCase()}`}
                className="flex-1 px-4 py-3 rounded-md text-sm font-medium transition-all"
                style={{
                  background: active ? "var(--brand-primary)" : "white",
                  color: active ? "white" : "var(--text-secondary)",
                  border: `1px solid ${active ? "var(--brand-primary)" : "var(--border-default)"}`,
                }}
              >
                <span className="mr-1.5">{opt.emoji}</span>{opt.v}
              </button>
            );
          })}
        </div>
      </div>

      {/* Amount & date */}
      <div className="rounded-md border p-5 mt-4 grid grid-cols-2 gap-3" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
        <div className="col-span-2">
          <Label className="mb-1 block">Amount (EUR)</Label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-lg font-medium" style={{ color: "var(--text-muted)" }}>€</span>
            <Input value={amount} onChange={(e) => setAmount(e.target.value)} type="number" step="0.01" min="0" placeholder="0.00" className="bg-white text-lg pl-8" data-testid="amount-input" />
          </div>
          {amount === "" && extracted?.amount == null && (
            <div className="text-xs mt-1 flex items-center gap-1" style={{ color: "var(--status-warning)" }} data-testid="missing-amount-warning">
              <AlertTriangle className="w-3 h-3" /> Amount is required
            </div>
          )}
        </div>
        <div className="col-span-2">
          <Label className="mb-1 block">Date</Label>
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="bg-white" data-testid="date-input" />
        </div>
        <div className="col-span-2">
          <Label className="mb-1 block">Vendor (optional)</Label>
          <Input value={vendor} onChange={(e) => setVendor(e.target.value)} placeholder="e.g. Shell, Starbucks" className="bg-white" data-testid="vendor-input" />
        </div>
        <div className="col-span-2">
          <Label className="mb-1 block">Notes (optional)</Label>
          <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Trip purpose, project code…" className="bg-white" data-testid="notes-input" />
        </div>
      </div>

      <div className="flex justify-end mt-5 gap-2">
        <Button variant="ghost" onClick={() => navigate(-1)} data-testid="cancel-btn">Cancel</Button>
        <Button onClick={save} disabled={saving} data-testid="save-expense-btn" style={{ background: "var(--brand-secondary)", color: "white" }}>
          {saving ? <><Loader2 className="w-4 h-4 mr-1 animate-spin" /> Saving…</> : <><Save className="w-4 h-4 mr-1" /> Save draft</>}
        </Button>
      </div>
    </div>
  );
}
