import React, { useEffect, useRef, useState } from "react";
import api from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "./ui/dialog";
import { Mic, Square, Sparkles, Plus, Loader2, Wand2, UserPlus } from "lucide-react";
import { toast } from "sonner";
import InlineAddDoctor from "./InlineAddDoctor";

const STEP_RECORD = "record";       // pick mic or paste text
const STEP_EXTRACTING = "extract";  // calling AI
const STEP_REVIEW = "review";       // user confirms suggestion
const STEP_SAVING = "saving";

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

  useEffect(() => {
    if (!open) return;
    setStep(STEP_RECORD);
    setNote("");
    setSuggestion(null);
    setDoctorSearch("");
    api.get("/doctors").then((r) => setDoctors(r.data || [])).catch(() => setDoctors([]));
  }, [open]);

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
          } else {
            setNote((prev) => (prev ? prev + " " + txt : txt));
          }
        } catch (e) {
          toast.error(e?.response?.data?.detail || "Transcription failed");
        } finally {
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
      setSuggestion({
        task_title: sug.task_title || "",
        task_description: sug.task_description || "",
        is_promise: !!sug.is_promise,
        // Default to today if AI didn't suggest a date — the TM is capturing right now.
        suggested_due_date: sug.suggested_due_date || todayISO(),
        priority: sug.priority || "Medium",
        doctor_id: sug.doctor_id || defaultDoctorId || "",
        doctor_hint: sug.doctor_hint || "",
      });
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
    if (!suggestion.doctor_id) {
      toast.error("Pick a doctor for this task");
      return;
    }
    setStep(STEP_SAVING);
    try {
      await api.post("/tasks", {
        doctor_id: suggestion.doctor_id,
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
            Record a voice note or type a quick reminder — AI will turn it into a task or promise.
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
              <button
                type="button"
                onClick={() => setAddingDoctor(true)}
                data-testid="quick-capture-add-doctor"
                className="mt-1.5 text-xs flex items-center gap-1 hover:underline"
                style={{ color: "var(--brand-primary)" }}
              >
                <UserPlus className="w-3.5 h-3.5" />
                Can&apos;t find them? Add new doctor{doctorSearch ? ` "${doctorSearch}"` : ""}
              </button>
            </div>
            <label className="flex items-center gap-2 text-sm cursor-pointer" style={{ color: "var(--text-secondary)" }}>
              <input
                type="checkbox"
                checked={suggestion.is_promise}
                onChange={(e) => setSuggestion({ ...suggestion, is_promise: e.target.checked })}
                data-testid="quick-capture-is-promise"
              />
              Mark as a promise to the doctor
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
