import React, { useMemo, useRef, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { toast } from "sonner";
import {
  Upload, Download, FileSpreadsheet, ChevronLeft, ChevronRight,
  AlertTriangle, CheckCircle2, Loader2, ArrowLeft,
} from "lucide-react";

const TARGET_FIELDS = [
  { key: "first_name", label: "First name", help: "Combined with last name → full name" },
  { key: "last_name", label: "Last name", help: "Combined with first name → full name" },
  { key: "doctor_name", label: "Doctor name (full)", help: "Use this OR first + last name" },
  { key: "clinic_name", label: "Clinic name" },
  { key: "city", label: "City" },
  { key: "region", label: "Region" },
  { key: "doctor_type", label: "Doctor type", help: "GP / Ortho / Other" },
  { key: "segment", label: "Segment", help: "New / Lapsed / Occasional / Active / Engaged / Expert" },
  { key: "general_notes", label: "General notes" },
];

const ALL = "__ALL__";

export default function ImportDoctors() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const fileRef = useRef(null);
  const [step, setStep] = useState(1);                // 1 upload, 2 map, 3 preview, 4 done
  const [file, setFile] = useState(null);
  const [parsing, setParsing] = useState(false);
  const [preview, setPreview] = useState(null);       // server preview response
  const [mapping, setMapping] = useState({});         // {field: header}
  const [strategy, setStrategy] = useState("skip");
  const [committing, setCommitting] = useState(false);
  const [result, setResult] = useState(null);
  const [tms, setTms] = useState([]);
  const [assignedTm, setAssignedTm] = useState("");

  // Admin → load TM list
  React.useEffect(() => {
    if (user?.role === "Admin") {
      api.get("/users").then((r) => setTms((r.data || []).filter((u) => u.role === "TM"))).catch(() => {});
    }
  }, [user]);

  const downloadTemplate = async (fmt) => {
    try {
      const res = await api.get(`/doctors/import/template?format=${fmt}`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `doctor_import_template.${fmt}`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch {
      toast.error("Could not download template");
    }
  };

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!/\.(xlsx|csv)$/i.test(f.name)) {
      toast.error("Please pick a .xlsx or .csv file");
      return;
    }
    setFile(f);
    setParsing(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const { data } = await api.post("/doctors/import/preview", fd);
      setPreview(data);
      setMapping(data.suggested_mapping || {});
      setStep(2);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not parse file");
    } finally {
      setParsing(false);
    }
  };

  // Validation summary based on current mapping
  const validation = useMemo(() => {
    if (!preview) return null;
    const rows = preview.rows || [];
    let valid = 0;
    let invalid = 0;
    const errors = [];
    rows.forEach((row, idx) => {
      const fullRaw = mapping.doctor_name ? (row[mapping.doctor_name] || "").trim() : "";
      const first = mapping.first_name ? (row[mapping.first_name] || "").trim() : "";
      const last = mapping.last_name ? (row[mapping.last_name] || "").trim() : "";
      const composed = `${first} ${last}`.trim();
      const name = fullRaw || composed;
      const segRaw = mapping.segment ? (row[mapping.segment] || "").trim() : "";
      const segOk = !segRaw || ["New", "Lapsed", "Occasional", "Active", "Engaged", "Expert"].includes(segRaw.charAt(0).toUpperCase() + segRaw.slice(1).toLowerCase());
      const rowErrors = [];
      if (!name) rowErrors.push("doctor_name (or first+last) missing");
      if (!segOk) rowErrors.push("segment invalid");
      if (rowErrors.length === 0) valid++;
      else { invalid++; if (errors.length < 10) errors.push({ idx, errors: rowErrors }); }
    });
    return { total: rows.length, valid, invalid, errors };
  }, [preview, mapping]);

  // Quick client-side dupe estimate (within file)
  const duplicates = useMemo(() => {
    if (!preview) return 0;
    const rows = preview.rows || [];
    const seenA = new Set(), seenB = new Set();
    let dupCount = 0;
    rows.forEach((row) => {
      const fullRaw = mapping.doctor_name ? (row[mapping.doctor_name] || "").toLowerCase().trim() : "";
      const first = mapping.first_name ? (row[mapping.first_name] || "").toLowerCase().trim() : "";
      const last = mapping.last_name ? (row[mapping.last_name] || "").toLowerCase().trim() : "";
      const name = fullRaw || `${first} ${last}`.trim();
      const clinic = (mapping.clinic_name ? row[mapping.clinic_name] : "")?.toLowerCase().trim();
      const city = (mapping.city ? row[mapping.city] : "")?.toLowerCase().trim();
      const k1 = name && city ? `${name}|${city}` : null;
      const k2 = clinic && city ? `${clinic}|${city}` : null;
      if ((k1 && seenA.has(k1)) || (k2 && seenB.has(k2))) dupCount++;
      if (k1) seenA.add(k1);
      if (k2) seenB.add(k2);
    });
    return dupCount;
  }, [preview, mapping]);

  const commit = async () => {
    if (user?.role === "Admin" && !assignedTm) {
      toast.error("Pick the TM these doctors belong to");
      return;
    }
    setCommitting(true);
    try {
      const body = {
        filename: preview.filename,
        mapping,
        rows: preview.rows,
        duplicate_strategy: strategy,
      };
      if (user?.role === "Admin") body.assigned_tm_id = assignedTm;
      const { data } = await api.post("/doctors/import/commit", body);
      setResult(data);
      setStep(4);
      toast.success(`Imported ${data.created_count} · skipped ${data.skipped_count} · updated ${data.updated_count}`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Import failed");
    } finally {
      setCommitting(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto" data-testid="import-doctors-page">
      <div className="mb-5 flex items-center gap-2">
        <button onClick={() => navigate("/doctors")} className="p-1.5 rounded hover:bg-[var(--bg-paper)]" data-testid="import-back-btn"><ChevronLeft className="w-4 h-4" /></button>
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Doctors</div>
          <h1 className="font-display text-2xl sm:text-3xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Import your <span className="font-medium">doctor list.</span>
          </h1>
        </div>
      </div>

      {/* Step indicator */}
      <div className="flex gap-2 mb-5 text-xs uppercase tracking-widest">
        {["Upload", "Map columns", "Preview", "Done"].map((label, i) => {
          const idx = i + 1;
          const active = step === idx;
          const done = step > idx;
          return (
            <div key={label} className="flex items-center gap-2 flex-1">
              <span data-testid={`step-${idx}-pill`} className="px-2 py-1 rounded-full" style={{
                background: active ? "var(--brand-primary)" : done ? "var(--status-success-bg)" : "var(--bg-paper)",
                color: active ? "white" : done ? "var(--status-success)" : "var(--text-muted)",
              }}>{idx}. {label}</span>
              {idx < 4 && <span className="flex-1 h-px" style={{ background: "var(--border-default)" }} />}
            </div>
          );
        })}
      </div>

      {step === 1 && (
        <div className="rounded-md border p-6 space-y-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="flex flex-wrap gap-3 items-center justify-between">
            <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-secondary)" }}>
              <FileSpreadsheet className="w-4 h-4" /> Need a starter? Download the template:
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => downloadTemplate("xlsx")} data-testid="download-template-xlsx"><Download className="w-3 h-3 mr-1" /> XLSX</Button>
              <Button variant="ghost" size="sm" onClick={() => downloadTemplate("csv")} data-testid="download-template-csv">CSV</Button>
            </div>
          </div>

          <input type="file" accept=".xlsx,.csv" ref={fileRef} onChange={onFile} className="hidden" data-testid="import-file-input" />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={parsing}
            data-testid="pick-file-btn"
            className="w-full rounded-md border-2 border-dashed py-12 flex flex-col items-center justify-center gap-2 transition-all hover:bg-[var(--bg-paper)]"
            style={{ borderColor: "var(--border-default)" }}
          >
            {parsing ? <Loader2 className="w-7 h-7 animate-spin" style={{ color: "var(--brand-primary)" }} /> : <Upload className="w-7 h-7" style={{ color: "var(--brand-primary)" }} />}
            <div className="font-medium" style={{ color: "var(--brand-primary)" }}>{parsing ? "Reading your file…" : "Pick .xlsx or .csv"}</div>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>Up to 5 MB · 2000 rows max{user?.role === "TM" ? " · doctors will be assigned to you" : ""}</div>
          </button>

          {user?.role === "Admin" && (
            <div className="rounded-md border p-4" style={{ borderColor: "var(--border-default)" }}>
              <Label className="mb-1 block text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Assign these doctors to</Label>
              <Select value={assignedTm || ALL} onValueChange={(v) => setAssignedTm(v === ALL ? "" : v)}>
                <SelectTrigger className="bg-white" data-testid="admin-assign-tm"><SelectValue placeholder="Pick a TM" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>— pick a TM —</SelectItem>
                  {tms.map((t) => <SelectItem key={t.id} value={t.id}>{t.full_name} · {t.email}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
      )}

      {step === 2 && preview && (
        <div className="rounded-md border p-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="map-step">
          <div className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
            We detected <strong>{preview.row_count}</strong> rows in <em>{preview.filename}</em>. Match each system field to a column from your file:
          </div>
          <div className="space-y-3" data-testid="mapping-list">
            {TARGET_FIELDS.map((tf) => (
              <div key={tf.key} className="grid grid-cols-2 gap-3 items-center">
                <div>
                  <div className="text-sm font-medium" style={{ color: "var(--brand-primary)" }}>
                    {tf.label}{tf.required && <span style={{ color: "var(--status-danger)" }}> *</span>}
                  </div>
                  {tf.help && <div className="text-xs" style={{ color: "var(--text-muted)" }}>{tf.help}</div>}
                </div>
                <Select value={mapping[tf.key] || ALL} onValueChange={(v) => setMapping({ ...mapping, [tf.key]: v === ALL ? null : v })}>
                  <SelectTrigger className="bg-white" data-testid={`map-${tf.key}`}><SelectValue placeholder="— skip —" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>— skip —</SelectItem>
                    {(preview.headers || []).map((h) => <SelectItem key={h} value={h}>{h}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            ))}
          </div>
          <div className="flex justify-between mt-5">
            <Button variant="ghost" onClick={() => setStep(1)} data-testid="back-to-upload"><ArrowLeft className="w-4 h-4 mr-1" /> Back</Button>
            <Button onClick={() => setStep(3)} disabled={!mapping.doctor_name} data-testid="next-to-preview" style={{ background: "var(--brand-primary)", color: "white" }}>
              Next <ChevronRight className="w-4 h-4 ml-1" />
            </Button>
          </div>
        </div>
      )}

      {step === 3 && preview && (
        <div className="space-y-4">
          {/* Summary */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="preview-stats">
            <Stat label="Total rows" value={validation?.total || 0} testId="preview-total" />
            <Stat label="Valid" value={validation?.valid || 0} kind="success" testId="preview-valid" />
            <Stat label="Invalid" value={validation?.invalid || 0} kind={validation?.invalid ? "danger" : "muted"} testId="preview-invalid" />
            <Stat label="Possible duplicates" value={duplicates} kind={duplicates ? "warning" : "muted"} testId="preview-dupes" />
          </div>
          {validation?.invalid > 0 && (
            <div className="rounded-md p-3 text-xs flex items-start gap-2" style={{ background: "var(--status-warning-bg)", color: "var(--status-warning)" }} data-testid="invalid-banner">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <div>
                <strong>{validation.invalid}</strong> row(s) will be skipped due to errors. First few:
                <ul className="mt-1 list-disc pl-5">
                  {validation.errors.map((e) => <li key={e.idx}>Row {e.idx + 2}: {e.errors.join(", ")}</li>)}
                </ul>
              </div>
            </div>
          )}

          {/* Strategy */}
          <div className="rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
            <Label className="mb-2 block">Duplicate handling</Label>
            <div className="flex flex-wrap gap-2">
              {[
                { v: "skip", label: "Skip duplicates" },
                { v: "update", label: "Update existing" },
                { v: "import", label: "Import anyway" },
              ].map((opt) => (
                <button
                  key={opt.v}
                  type="button"
                  onClick={() => setStrategy(opt.v)}
                  data-testid={`strategy-${opt.v}`}
                  className="px-3 py-1.5 rounded-full text-xs"
                  style={{
                    background: strategy === opt.v ? "var(--brand-primary)" : "white",
                    color: strategy === opt.v ? "white" : "var(--text-secondary)",
                    border: `1px solid ${strategy === opt.v ? "var(--brand-primary)" : "var(--border-default)"}`,
                  }}
                >{opt.label}</button>
              ))}
            </div>
            <div className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
              Duplicate = same doctor name + city, or same clinic + city, among your existing doctors.
            </div>
          </div>

          {/* Sample rows */}
          <div className="rounded-md border overflow-hidden" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
            <div className="px-4 py-2 border-b text-xs uppercase tracking-widest font-medium" style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}>
              Sample (first {Math.min(preview.sample_rows.length, 5)} rows)
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs" data-testid="preview-table">
                <thead style={{ background: "var(--bg-paper)" }}>
                  <tr>
                    {TARGET_FIELDS.filter((tf) => mapping[tf.key]).map((tf) => (
                      <th key={tf.key} className="text-left px-3 py-2 font-medium" style={{ color: "var(--text-muted)" }}>{tf.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample_rows.slice(0, 5).map((row, i) => (
                    <tr key={i} className="border-t" style={{ borderColor: "var(--border-default)" }}>
                      {TARGET_FIELDS.filter((tf) => mapping[tf.key]).map((tf) => (
                        <td key={tf.key} className="px-3 py-2 align-top" style={{ color: "var(--text-secondary)" }}>{row[mapping[tf.key]] || "—"}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex justify-between">
            <Button variant="ghost" onClick={() => setStep(2)} data-testid="back-to-map"><ArrowLeft className="w-4 h-4 mr-1" /> Back</Button>
            <Button onClick={commit} disabled={committing || !validation?.valid} data-testid="confirm-import-btn" style={{ background: "var(--brand-secondary)", color: "white" }}>
              {committing ? <><Loader2 className="w-4 h-4 mr-1 animate-spin" /> Importing…</> : <>Import {validation?.valid || 0} doctor{validation?.valid !== 1 ? "s" : ""}</>}
            </Button>
          </div>
        </div>
      )}

      {step === 4 && result && (
        <div className="rounded-md border p-6 space-y-4 text-center" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="done-step">
          <CheckCircle2 className="w-10 h-10 mx-auto" style={{ color: "var(--status-success)" }} />
          <div className="font-display text-2xl font-medium" style={{ color: "var(--brand-primary)" }}>Import complete</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Imported" value={result.created_count} kind="success" testId="result-created" />
            <Stat label="Updated" value={result.updated_count} testId="result-updated" />
            <Stat label="Skipped" value={result.skipped_count} kind={result.skipped_count ? "warning" : "muted"} testId="result-skipped" />
            <Stat label="Failed" value={result.failed_count} kind={result.failed_count ? "danger" : "muted"} testId="result-failed" />
          </div>
          <div className="flex justify-center gap-2">
            <Button variant="outline" onClick={() => { setStep(1); setFile(null); setPreview(null); setResult(null); }} data-testid="import-another-btn">Import another file</Button>
            <Link to="/doctors"><Button data-testid="back-to-doctors-btn" style={{ background: "var(--brand-primary)", color: "white" }}>Back to doctors</Button></Link>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, kind, testId }) {
  const colors = {
    success: { bg: "var(--status-success-bg)", fg: "var(--status-success)" },
    warning: { bg: "var(--status-warning-bg)", fg: "var(--status-warning)" },
    danger: { bg: "var(--status-danger-bg)", fg: "var(--status-danger)" },
    muted: { bg: "var(--bg-paper)", fg: "var(--text-secondary)" },
  };
  const c = colors[kind] || colors.muted;
  return (
    <div className="rounded p-3" style={{ background: c.bg }} data-testid={testId}>
      <div className="text-[11px] uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>{label}</div>
      <div className="font-display text-xl font-medium mt-0.5" style={{ color: c.fg }}>{value}</div>
    </div>
  );
}
