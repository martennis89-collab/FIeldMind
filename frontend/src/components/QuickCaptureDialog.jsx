import React, { useEffect, useRef, useState } from "react";
import api from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "./ui/dialog";
import { Mic, Square, Sparkles, Plus, Loader2, Wand2, UserPlus, CheckCircle2, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import InlineAddDoctor from "./InlineAddDoctor";

const STEP_RECORD = "record";       // pick mic or paste text
const STEP_EXTRACTING = "extract";  // calling AI (typed-text task flow)
const STEP_REVIEW = "review";       // user confirms suggestion (typed-text task flow)
const STEP_SAVING = "saving";
const STEP_ACTING = "acting";       // voice flow: AI figuring out + performing the action
const STEP_DONE = "done";           // voice flow: action performed, show what happened
const STEP_NEEDS_INFO = "needs_info"; // voice flow: AI couldn't confidently act, needs more detail

// Human-readable summary of what /assistant/execute did, for the voice flow's
// "done" screen — mirrors routers/telegram.py's _format_result_message so a
// voice note behaves and reads the same whether it came in via the app or Telegram.
function describeResult(result) {
  const action = result.action;
  if (action === "task") {
    return `Logged task: ${(result.task_titles || []).join("; ")}.`;
  }
  if (action === "meeting" || action === "demo") {
    const doctorName = result.doctor_name || "the doctor";
    const newDoctorLine = result.doctor_auto_created ? " (added as a new doctor)" : "";
    const kind = action === "demo" ? "iTero demo" : "Meeting";
    let when = result.scheduled_at || "";
    try {
      when = new Date(result.scheduled_at).toLocaleString(undefined, {
        month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
      });
    } catch { /* keep raw string */ }
    return `${kind} booked with ${doctorName}${newDoctorLine} for ${when}.`;
  }
  if (action === "visit") {
    const doctorName = result.doctor_name || "the doctor";
    const newDoctorLine = result.doctor_auto_created ? " (added as a new doctor)" : "";
    const promiseLine = result.n_promises ? ` · ${result.n_promises} follow-up${result.n_promises !== 1 ? "s" : ""} tracked` : "";
    const dateLine = result.visit_date ? ` · dated ${result.visit_date}` : "";
    return `Logged visit with ${doctorName}${newDoctorLine} — ${result.sentiment || "Neutral"} sentiment${promiseLine}${dateLine}.`;
  }
  return "Done.";
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function QuickCaptureDialog({ open, onClose, onCreated, defaultDoctorId = null }) {
  const [step, setStep] = useState(STEP_RECORD);
  const [note, setNote] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);

  const [suggestion, setSuggestion] = useState(null); // { task_title, task_description, ... }
  const [doctors, setDoctors] = useState([]);
  const [doctorSearch, setDoctorSearch] = useState("");
  const [addingDoctor, setAddingDoctor] = useState(false);
  const [noDoctor, setNoDoctor] = useState(false);
  const [actionResult, setActionResult] = useState(null);

  useEffect(() => {
    if (!open) return;
    setStep(STEP_RECORD);
    setNote("");
    setSuggestion(null);
    setDoctorSearch("");
    setNoDoctor(false);
    setActionResult(null);
    api.get("/doctors").then((r) => setDoctors(r.data || [])).catch(() => setDoctors([]));
  }, [open]);

  // Voice flow only — types (book a meeting/demo, log a visit, standalone task)
  // are figured out and PERFORMED automatically, same engine as Telegram. Typed
  // text below still goes through the simpler task-only "Suggest task" flow.
  const runSmartAction = async (noteText) => {
    setStep(STEP_ACTING);
    try {
      const { data } = await api.post("/assistant/execute", {
        note: noteText,
        doctor_id: defaultDoctorId || null,
      });
      setActionResult(data);
      if (data.status === "done") {
        setStep(STEP_DONE);
        onCreated?.();
      } else if (data.status === "needs_clarification") {
        setStep(STEP_NEEDS_INFO);
      } else {
        toast.error(data.detail || "Something went wrong");
        setStep(STEP_RECORD);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to process that note");
      setStep(STEP_RECORD);
    }
  };

  const cleanupStream = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  };

  const startRec = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      toast.error("Voice recording isn't supported on this device.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      const rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data && e.data.size > 0 && chunksRef.current.push(e.data);
      rec.onstop = async () => {
        cleanupStream();
        if (chunksRef.current.length === 0) return;
        const blob = new Blob(chunksRef.current, { type: chunksRef.current[0].type || "audio/webm" });
        const fd = new FormData();
        fd.append("audio", blob, "quick.webm");
        setTranscribing(true);
        try {
          const { data } = await api.post("/visits/transcribe", fd);
          const txt = (data?.text || "").trim();
          if (!txt) {
            toast.error("Couldn't pick up any speech — try again.");
            setTranscribing(false);
            return;
          }
          const fullNote = note ? `${note} ${txt}` : txt;
          setNote(fullNote);
          setTranscribing(false);
          // Voice always goes through the smart-action engine — no manual
          // "Suggest task" click needed, it figures out and performs the
          // action directly (visit / meeting / demo / task).
          await runSmartAction(fullNote);
        } catch (e) {
          toast.error(e?.response?.data?.detail || "Transcription failed");
          setTranscribing(false);
        }
      };
      recorderRef.current = rec;
      rec.start();
      setRecording(true);
    } catch (e) {
      toast.error("Mic permission denied");
    }
  };

  const stopRec = () => {
    if (recorderRef.current && recording) {
      recorderRef.current.stop();
      setRecording(false);
    }
  };

  const extract = async () => {
    if (!note.trim()) {
      toast.error("Type or record something first.");
      return;
    }
    setStep(STEP_EXTRACTING);
    try {
      const { data } = await api.post("/ai/extract-task", {
        note: note.trim(),
        doctor_id: defaultDoctorId || null,
      });
      const sug = data.suggestion || {};
      if (!sug.task_title) {
        toast.warning("AI couldn't find an action — please edit manually.");
        sug.task_title = note.trim().slice(0, 120);
      }
      const resolvedDoctorId = sug.doctor_id || defaultDoctorId || "";
      setSuggestion({
        task_title: sug.task_title || "",
        task_description: sug.task_description || "",
        is_promise: !!sug.is_promise,
        // Default to today if AI didn't suggest a date — the TM is capturing right now.
        suggested_due_date: sug.suggested_due_date || todayISO(),
        priority: sug.priority || "Medium",
        doctor_id: resolvedDoctorId,
        doctor_hint: sug.doctor_hint || "",
      });
      // AI found no doctor at all in the note — start in "personal task" mode
      // instead of forcing the user to pick one.
      setNoDoctor(!resolvedDoctorId && !sug.doctor_hint);
      setStep(STEP_REVIEW);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "AI extraction failed");
      setStep(STEP_RECORD);
    }
  };

  const create = async () => {
    if (!suggestion?.task_title?.trim()) {
      toast.error("Task title is required");
      return;
    }
    if (!suggestion.doctor_id && !noDoctor) {
      toast.error("Pick a doctor, or mark this as a personal task");
      return;
    }
    setStep(STEP_SAVING);
    try {
      await api.post("/tasks", {
        doctor_id: noDoctor ? null : suggestion.doctor_id,
        task_title: suggestion.task_title.trim(),
        task_description: suggestion.task_description.trim() || null,
        due_date: suggestion.suggested_due_date || null,
        priority: suggestion.priority || "Medium",
        is_promise: !!suggestion.is_promise,
      });
      toast.success(suggestion.is_promise ? "Promise saved" : "Task created");
      onCreated?.();
      handleClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to create task");
      setStep(STEP_REVIEW);
    }
  };

  const handleClose = () => {
    if (recording) stopRec();
    cleanupStream();
    onClose?.();
  };

  const filteredDoctors = doctorSearch
    ? doctors.filter((d) => (d.doctor_name || "").toLowerCase().includes(doctorSearch.toLowerCase()))
    : doctors.slice(0, 30);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wand2 className="w-5 h-5" style={{ color: "var(--brand-primary)" }} />
            Quick capture
          </DialogTitle>
          <DialogDescription>
            Record a voice note — AI figures out if it's a visit, a meeting/demo to book, or a
            personal task, and does it. Typed text becomes a task suggestion to review.
          </DialogDescription>
        </DialogHeader>

        {step === STEP_RECORD && (
          <div className="space-y-4">
            <div className="rounded-md border p-4 flex items-center justify-between gap-3" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
              <div className="flex-1 text-sm">
                {recording ? (
                  <span className="inline-flex items-center gap-2 font-medium" style={{ color: "var(--status-danger)" }}>
                    <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: "var(--status-danger)" }} />
                    Recording — tap stop when done.
                  </span>
                ) : transcribing ? (
                  <span className="inline-flex items-center gap-2" style={{ color: "var(--text-secondary)" }}>
                    <Loader2 className="w-4 h-4 animate-spin" /> Transcribing…
                  </span>
                ) : (
                  <span style={{ color: "var(--text-secondary)" }}>
                    Tap mic to dictate, or paste text below.
                  </span>
                )}
              </div>
              {recording ? (
                <Button onClick={stopRec} data-testid="quick-capture-stop" style={{ background: "var(--status-danger)", color: "white" }}>
                  <Square className="w-4 h-4 mr-1" /> Stop
                </Button>
              ) : (
                <Button onClick={startRec} disabled={transcribing} data-testid="quick-capture-record" style={{ background: "var(--brand-primary)", color: "white" }}>
                  <Mic className="w-4 h-4 mr-1" /> Record
                </Button>
              )}
            </div>
            <div>
              <Label htmlFor="qc-note">Note</Label>
              <Textarea
                id="qc-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Promise to send Dr. Petrov the certification info by Friday…"
                rows={4}
                data-testid="quick-capture-note"
                className="mt-1"
              />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={handleClose}>Cancel</Button>
              <Button onClick={extract} disabled={!note.trim()} data-testid="quick-capture-extract" style={{ background: "var(--brand-primary)", color: "white" }}>
                <Sparkles className="w-4 h-4 mr-1" /> Suggest task
              </Button>
            </DialogFooter>
          </div>
        )}

        {step === STEP_EXTRACTING && (
          <div className="py-12 flex flex-col items-center gap-3" data-testid="quick-capture-extracting">
            <Loader2 className="w-8 h-8 animate-spin" style={{ color: "var(--brand-primary)" }} />
            <div className="text-sm" style={{ color: "var(--text-secondary)" }}>AI is reading your note…</div>
          </div>
        )}

        {step === STEP_ACTING && (
          <div className="py-12 flex flex-col items-center gap-3" data-testid="quick-capture-acting">
            <Loader2 className="w-8 h-8 animate-spin" style={{ color: "var(--brand-primary)" }} />
            <div className="text-sm" style={{ color: "var(--text-secondary)" }}>Figuring out what to do…</div>
          </div>
        )}

        {step === STEP_DONE && actionResult && (
          <div className="space-y-4" data-testid="quick-capture-done">
            <div className="rounded-md border p-4 flex items-start gap-3" style={{ background: "var(--status-success-bg)", borderColor: "var(--status-success)" }}>
              <CheckCircle2 className="w-5 h-5 shrink-0 mt-0.5" style={{ color: "var(--status-success)" }} />
              <div className="text-sm" style={{ color: "var(--text-primary)" }}>{describeResult(actionResult)}</div>
            </div>
            <DialogFooter>
              <Button onClick={handleClose} data-testid="quick-capture-done-close" style={{ background: "var(--brand-primary)", color: "white" }}>
                Done
              </Button>
            </DialogFooter>
          </div>
        )}

        {step === STEP_NEEDS_INFO && actionResult && (
          <div className="space-y-4" data-testid="quick-capture-needs-info">
            <div className="rounded-md border p-4 flex items-start gap-3" style={{ background: "var(--status-warning-bg)", borderColor: "var(--status-warning)" }}>
              <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" style={{ color: "var(--status-warning)" }} />
              <div className="text-sm" style={{ color: "var(--text-primary)" }}>{actionResult.reason}</div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setStep(STEP_RECORD)} data-testid="quick-capture-try-again">
                Try again
              </Button>
            </DialogFooter>
          </div>
        )}

        {step === STEP_REVIEW && suggestion && (
          <div className="space-y-3" data-testid="quick-capture-review">
            <div className="rounded-md border p-3 text-xs flex items-center gap-2" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)", color: "var(--text-secondary)" }}>
              <Sparkles className="w-3.5 h-3.5 shrink-0" style={{ color: "var(--brand-primary)" }} />
              <span>AI suggestion — tweak anything below before saving.</span>
            </div>
            <div>
              <Label>Task title</Label>
              <Input
                value={suggestion.task_title}
                onChange={(e) => setSuggestion({ ...suggestion, task_title: e.target.value })}
                data-testid="quick-capture-title"
                className="mt-1"
              />
            </div>
            <div>
              <Label>Description</Label>
              <Textarea
                value={suggestion.task_description}
                onChange={(e) => setSuggestion({ ...suggestion, task_description: e.target.value })}
                rows={2}
                data-testid="quick-capture-desc"
                className="mt-1"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Due date</Label>
                <Input
                  type="date"
                  value={suggestion.suggested_due_date || ""}
                  onChange={(e) => setSuggestion({ ...suggestion, suggested_due_date: e.target.value })}
                  data-testid="quick-capture-due"
                  className="mt-1"
                />
              </div>
              <div>
                <Label>Priority</Label>
                <select
                  value={suggestion.priority}
                  onChange={(e) => setSuggestion({ ...suggestion, priority: e.target.value })}
                  data-testid="quick-capture-priority"
                  className="mt-1 w-full h-10 rounded-md border px-3 text-sm bg-white"
                  style={{ borderColor: "var(--border-default)" }}
                >
                  <option>Low</option>
                  <option>Medium</option>
                  <option>High</option>
                </select>
              </div>
            </div>
            <div>
              <Label>Doctor</Label>
              {noDoctor ? (
                <div className="rounded-md border bg-white p-3 mt-1 flex items-center justify-between gap-3" style={{ borderColor: "var(--border-default)" }}>
                  <div className="text-sm" style={{ color: "var(--text-secondary)" }}>Personal / admin task — not linked to a doctor</div>
                  <Button variant="outline" size="sm" onClick={() => setNoDoctor(false)} data-testid="quick-capture-pick-doctor-instead">Pick a doctor instead</Button>
                </div>
              ) : (
                <>
                  <Input
                    value={doctorSearch}
                    onChange={(e) => setDoctorSearch(e.target.value)}
                    placeholder="Search…"
                    className="mt-1 mb-1"
                    data-testid="quick-capture-doctor-search"
                  />
                  <div className="max-h-32 overflow-y-auto rounded border" style={{ borderColor: "var(--border-default)" }}>
                    {filteredDoctors.map((d) => (
                      <button
                        key={d.id}
                        type="button"
                        onClick={() => setSuggestion({ ...suggestion, doctor_id: d.id, doctor_hint: d.doctor_name })}
                        data-testid={`quick-capture-pick-${d.id}`}
                        className="w-full text-left px-2 py-1.5 text-sm border-b last:border-b-0 transition-colors hover:bg-[var(--bg-paper)]"
                        style={{
                          borderColor: "var(--border-default)",
                          background: suggestion.doctor_id === d.id ? "var(--bg-paper)" : "transparent",
                          color: suggestion.doctor_id === d.id ? "var(--brand-primary)" : "var(--text-primary)",
                          fontWeight: suggestion.doctor_id === d.id ? 600 : 400,
                        }}
                      >
                        {d.doctor_name}
                        <span className="text-[11px] ml-1" style={{ color: "var(--text-muted)" }}>
                          {[d.clinic_name, d.city].filter(Boolean).join(" · ")}
                        </span>
                      </button>
                    ))}
                    {filteredDoctors.length === 0 && (
                      <div className="px-2 py-3 text-center text-xs space-y-2" style={{ color: "var(--text-muted)" }}>
                        <div>No doctors match{doctorSearch ? ` "${doctorSearch}"` : ""}.</div>
                      </div>
                    )}
                  </div>
                  <div className="mt-1.5 flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => setAddingDoctor(true)}
                      data-testid="quick-capture-add-doctor"
                      className="text-xs flex items-center gap-1 hover:underline"
                      style={{ color: "var(--brand-primary)" }}
                    >
                      <UserPlus className="w-3.5 h-3.5" />
                      Can&apos;t find them? Add new doctor{doctorSearch ? ` "${doctorSearch}"` : ""}
                    </button>
                    <button
                      type="button"
                      onClick={() => setNoDoctor(true)}
                      data-testid="quick-capture-mark-personal"
                      className="text-xs hover:underline"
                      style={{ color: "var(--text-muted)" }}
                    >
                      This isn&apos;t about a doctor
                    </button>
                  </div>
                </>
              )}
            </div>
            <label className="flex items-center gap-2 text-sm cursor-pointer" style={{ color: "var(--text-secondary)" }}>
              <input
                type="checkbox"
                checked={suggestion.is_promise}
                onChange={(e) => setSuggestion({ ...suggestion, is_promise: e.target.checked })}
                data-testid="quick-capture-is-promise"
              />
              {noDoctor ? "Mark as a promise" : "Mark as a promise to the doctor"}
            </label>
            <DialogFooter>
              <Button variant="outline" onClick={() => setStep(STEP_RECORD)}>Back</Button>
              <Button onClick={create} data-testid="quick-capture-save" style={{ background: "var(--brand-primary)", color: "white" }}>
                <Plus className="w-4 h-4 mr-1" /> {suggestion.is_promise ? "Save promise" : "Create task"}
              </Button>
            </DialogFooter>
          </div>
        )}

        {step === STEP_SAVING && (
          <div className="py-12 flex items-center justify-center">
            <Loader2 className="w-7 h-7 animate-spin" style={{ color: "var(--brand-primary)" }} />
          </div>
        )}
      </DialogContent>
      <InlineAddDoctor
        open={addingDoctor}
        prefillName={doctorSearch}
        onClose={() => setAddingDoctor(false)}
        onCreated={(doc) => {
          setDoctors((prev) => [doc, ...prev]);
          setSuggestion((s) => ({ ...(s || {}), doctor_id: doc.id, doctor_hint: doc.doctor_name }));
          setDoctorSearch("");
          setAddingDoctor(false);
        }}
      />
    </Dialog>
  );
}
