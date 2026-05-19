import React, { useEffect, useMemo, useState } from "react";
import api from "../lib/api";
import { toast } from "sonner";
import { X, Search, UserRound, Stethoscope } from "lucide-react";

/**
 * Phase I — Intervention create/edit modal.
 *
 * Replaces the previous `window.prompt` flow for create-from-insight and
 * provides a single dialog used by both:
 *   - "Create intervention" on an insight card  → pass `fromInsight={card}`
 *   - "+ New intervention" manual create        → no fromInsight prop
 *
 * Fields:
 *   - Issue title (required, pre-filled from insight)
 *   - Severity (Critical / High / Medium / Low)
 *   - Due date (defaults to today + 7d)
 *   - Manager note (textarea)
 *   - Doctor picker — OPTIONAL. Searchable. Auto-populates from
 *     `fromInsight.related_doctor_id` if the insight carried one.
 *
 * Props:
 *   open: boolean
 *   onClose: () => void
 *   onCreated?: (intervention) => void
 *   fromInsight?: insight card object (id, title, body, suggested_action, severity, related_doctor_id?)
 *   defaultTmUserId?: string — for "+ New intervention" (manager picks a TM in a future enhancement)
 */
export default function InterventionDialog({ open, onClose, onCreated, fromInsight = null, defaultTmUserId = null }) {
  const today7 = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  }, []);

  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState("Medium");
  const [dueDate, setDueDate] = useState(today7);
  const [note, setNote] = useState("");
  const [doctorId, setDoctorId] = useState("");
  const [doctorName, setDoctorName] = useState("");
  const [doctorQuery, setDoctorQuery] = useState("");
  const [doctorResults, setDoctorResults] = useState([]);
  const [showDoctorPicker, setShowDoctorPicker] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Reset / prefill when opening
  useEffect(() => {
    if (!open) return;
    setTitle(fromInsight?.title || "");
    setSeverity(fromInsight?.severity || "Medium");
    setDueDate(today7);
    setNote("");
    // Auto-populate doctor from insight if present (related_doctor_id is reserved
    // for future insight types — today most insights are TM-scoped, so this is
    // a no-op for the V1 metric registry).
    const autoDoctor = fromInsight?.related_doctor_id || "";
    setDoctorId(autoDoctor);
    setDoctorName("");
    setDoctorQuery("");
    setDoctorResults([]);
    setShowDoctorPicker(false);
    setSubmitting(false);
    // If the insight carries a doctor reference, fetch the name for display
    if (autoDoctor) {
      api
        .get(`/doctors/${autoDoctor}`)
        .then((r) => setDoctorName(r.data?.doctor_name || ""))
        .catch(() => {});
    }
  }, [open, fromInsight, today7]);

  // Debounced doctor search
  useEffect(() => {
    if (!showDoctorPicker) return;
    const q = doctorQuery.trim();
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await api.get("/doctors", { params: { q: q || undefined, limit: 25 } });
        const list = Array.isArray(r.data) ? r.data : r.data?.doctors || r.data?.items || [];
        if (!cancelled) setDoctorResults(list);
      } catch {
        if (!cancelled) setDoctorResults([]);
      }
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [doctorQuery, showDoctorPicker]);

  if (!open) return null;

  const submit = async () => {
    if (!title.trim()) {
      toast.error("Title is required.");
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        issue_title: title.trim(),
        severity,
        due_date: dueDate || null,
        manager_note: note.trim() || null,
        doctor_id: doctorId || null,
      };
      let resp;
      if (fromInsight?.id) {
        resp = await api.post(`/interventions/from-insight/${fromInsight.id}`, payload);
      } else {
        resp = await api.post("/interventions", {
          ...payload,
          tm_user_id: defaultTmUserId || null,
          track_type: "General",
        });
      }
      toast.success("Intervention created.");
      onCreated?.(resp.data);
      onClose();
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || "Could not create intervention.";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const pickDoctor = (d) => {
    setDoctorId(d.id);
    setDoctorName(d.doctor_name || "");
    setShowDoctorPicker(false);
    setDoctorQuery("");
  };

  const clearDoctor = () => {
    setDoctorId("");
    setDoctorName("");
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
      style={{ background: "rgba(0,0,0,0.45)" }}
      data-testid="intervention-dialog"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg rounded-md border shadow-2xl my-8"
        style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between p-6 pb-3">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
              {fromInsight ? "From insight" : "Manual"}
            </div>
            <h2 className="font-display text-xl font-medium" style={{ color: "var(--brand-primary)" }}>
              {fromInsight ? "Create intervention" : "New intervention"}
            </h2>
            {fromInsight?.suggested_action && (
              <p className="text-xs mt-1 italic" style={{ color: "var(--text-secondary)" }}>
                → {fromInsight.suggested_action}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            data-testid="intervention-dialog-close"
            className="p-1.5 rounded-full hover:bg-[var(--bg-paper)] flex-shrink-0"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-6 pb-6 space-y-4">
          <Field label="Title" required>
            <input
              type="text"
              data-testid="intervention-dialog-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3 py-2 rounded border"
              style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}
              placeholder="e.g. Schedule follow-up demo with Dr. Ivanov"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Severity">
              <select
                data-testid="intervention-dialog-severity"
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
                className="w-full px-3 py-2 rounded border"
                style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}
              >
                {["Critical", "High", "Medium", "Low"].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Due date">
              <input
                type="date"
                data-testid="intervention-dialog-due"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="w-full px-3 py-2 rounded border"
                style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}
              />
            </Field>
          </div>

          {/* Doctor picker — optional */}
          <Field label="Doctor (optional)">
            {doctorId ? (
              <div
                className="flex items-center justify-between gap-3 px-3 py-2 rounded border"
                style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}
                data-testid="intervention-dialog-selected-doctor"
              >
                <span className="flex items-center gap-2 min-w-0">
                  <Stethoscope className="w-4 h-4 flex-shrink-0" style={{ color: "var(--brand-primary)" }} />
                  <span className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>
                    {doctorName || doctorId.slice(0, 8)}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={clearDoctor}
                  data-testid="intervention-dialog-clear-doctor"
                  aria-label="Clear linked doctor"
                  className="text-xs underline ml-2"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Clear
                </button>
              </div>
            ) : showDoctorPicker ? (
              <div
                className="rounded border"
                style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}
              >
                <div className="flex items-center gap-2 px-3 py-2 border-b" style={{ borderColor: "var(--border-default)" }}>
                  <Search className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
                  <input
                    autoFocus
                    type="text"
                    data-testid="intervention-dialog-doctor-search"
                    value={doctorQuery}
                    onChange={(e) => setDoctorQuery(e.target.value)}
                    placeholder="Search by name or clinic…"
                    className="flex-1 bg-transparent outline-none text-sm"
                    style={{ color: "var(--text-primary)" }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowDoctorPicker(false)}
                    className="text-xs"
                    style={{ color: "var(--text-muted)" }}
                  >
                    Cancel
                  </button>
                </div>
                <div className="max-h-48 overflow-y-auto">
                  {doctorResults.length === 0 ? (
                    <div className="p-3 text-xs" style={{ color: "var(--text-muted)" }}>
                      No doctors match — try a different search.
                    </div>
                  ) : (
                    doctorResults.map((d) => (
                      <button
                        key={d.id}
                        type="button"
                        onClick={() => pickDoctor(d)}
                        data-testid={`intervention-dialog-doctor-${d.id}`}
                        className="w-full text-left px-3 py-2 hover:bg-[var(--bg-muted)] flex items-center gap-2"
                      >
                        <Stethoscope className="w-3.5 h-3.5 flex-shrink-0" style={{ color: "var(--brand-secondary)" }} />
                        <div className="min-w-0">
                          <div className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>
                            {d.doctor_name}
                          </div>
                          <div className="text-xs truncate" style={{ color: "var(--text-muted)" }}>
                            {[d.clinic_name, d.city].filter(Boolean).join(" · ") || "—"}
                          </div>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setShowDoctorPicker(true)}
                data-testid="intervention-dialog-add-doctor"
                className="w-full text-sm px-3 py-2 rounded border border-dashed flex items-center justify-center gap-2 hover:bg-[var(--bg-paper)]"
                style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
              >
                <UserRound className="w-4 h-4" />
                Link a doctor (optional)
              </button>
            )}
          </Field>

          <Field label="Manager note">
            <textarea
              rows={3}
              data-testid="intervention-dialog-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Context for the TM — what to focus on, what you've already tried, deadlines…"
              className="w-full px-3 py-2 rounded border"
              style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }}
            />
          </Field>
        </div>

        <div
          className="flex justify-end gap-2 px-6 pb-6 pt-2 border-t"
          style={{ borderColor: "var(--border-default)" }}
        >
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="text-sm px-4 py-2 rounded border disabled:opacity-50"
            style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting || !title.trim()}
            data-testid="intervention-dialog-submit"
            className="text-sm px-4 py-2 rounded disabled:opacity-50"
            style={{ background: "var(--brand-primary)", color: "white" }}
          >
            {submitting ? "Creating…" : "Create intervention"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, required, children }) {
  return (
    <div>
      <label className="block text-xs uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>
        {label}
        {required && <span style={{ color: "var(--status-danger)" }}> *</span>}
      </label>
      {children}
    </div>
  );
}
