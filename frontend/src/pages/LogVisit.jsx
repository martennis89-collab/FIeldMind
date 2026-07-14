import React, { useEffect, useMemo, useState, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Command, CommandInput, CommandList, CommandItem, CommandEmpty } from "../components/ui/command";
import { Popover, PopoverTrigger, PopoverContent } from "../components/ui/popover";
import { StatusPill, sentimentKind, SegmentBadge } from "../components/StatusPill";
import { toast } from "sonner";
import { Brain, ChevronRight, ChevronLeft, Sparkles, Check, AlertTriangle, X, Clock, Plus, Mic, Square, Loader2, UserPlus } from "lucide-react";
import InlineAddDoctor from "../components/InlineAddDoctor";

const VISIT_TYPES = ["In-person visit", "Phone call", "Online meeting", "Event conversation", "Training/session", "Other"];
const SENTIMENTS = ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"];
const OP_STATES = ["Blocked", "Stuck", "Advancing", "Unknown"];

export default function LogVisit() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const initialDoctorId = params.get("doctor") || params.get("doctor_id");
  const meetingId = params.get("meeting_id");

  const [step, setStep] = useState(1); // 1 note (voice-first), 2 review (doctor + tags + save)
  const [doctorAutoMatched, setDoctorAutoMatched] = useState(false);
  const [doctors, setDoctors] = useState([]);
  const [taxonomy, setTaxonomy] = useState(null);
  const [doctorId, setDoctorId] = useState(initialDoctorId || "");
  const [docPickerOpen, setDocPickerOpen] = useState(false);
  const [docPickerQuery, setDocPickerQuery] = useState("");
  const [addingDoctor, setAddingDoctor] = useState(false);
  const [visitType, setVisitType] = useState("In-person visit");
  const [visitDate, setVisitDate] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  });
  const [note, setNote] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [ai, setAi] = useState(null);
  const [topics, setTopics] = useState([]);
  const [barriers, setBarriers] = useState([]);
  const [sentiment, setSentiment] = useState("Neutral");
  const [opportunity, setOpportunity] = useState("Unknown");
  const [nextStep, setNextStep] = useState("");
  const [promises, setPromises] = useState([]);
  const [saving, setSaving] = useState(false);
  const [skipAi, setSkipAi] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [recElapsed, setRecElapsed] = useState(0);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const recTimerRef = useRef(null);
  const [trackType, setTrackType] = useState("BOTH");
  const [iteroActions, setIteroActions] = useState({
    demo_discussed: false,
    demo_booked: false,
    demo_completed: false,
    demo_booked_date: null,
    demo_completed_date: null,
    scanner_interest_level: "None",
    scanner_concerns: [],
  });
  const [invisalignActions, setInvisalignActions] = useState({
    growth_program_explained: false,
    certification_interest: false,
    tps_discussed: false,
    p2p_suggested: false,
    staff_training_needed: false,
    clinical_confidence: "Unknown",
    business_confidence: "Unknown",
    patient_affordability_perception: "Unknown",
  });
  const [commercial, setCommercial] = useState({
    demo_discussed: false, demo_booked: false, demo_booked_date: "",
    demo_completed: false, demo_completed_date: "",
    boost_discussed: false, trade_in_discussed: false, trade_in_interest: false,
    growth_program_explained: false,
    proposal_discussed: false, proposal_sent: false, proposal_sent_date: "",
    proposal_follow_up_done: false,
  });

  useEffect(() => {
    api.get("/doctors").then((r) => setDoctors(r.data));
    api.get("/taxonomy").then((r) => setTaxonomy(r.data));
  }, []);

  const doctor = useMemo(() => doctors.find((d) => d.id === doctorId), [doctors, doctorId]);

  const runAi = async (noteOverride) => {
    const text = (noteOverride ?? note).trim();
    if (!text) { toast.error("Add a note first"); return; }
    setAnalyzing(true);
    try {
      const { data } = await api.post("/visits/analyze", { note: text, doctor_id: doctorId || undefined });
      setAi(data);
      if (data.doctor_id && !doctorId) {
        setDoctorId(data.doctor_id);
        setDoctorAutoMatched(true);
      }
      setTopics(data.topics || []);
      setBarriers(data.barriers || []);
      setSentiment(data.sentiment || "Neutral");
      setOpportunity(data.opportunity_state || "Unknown");
      setNextStep(data.suggested_next_action || "");
      setPromises((data.promises_detected || []).map((p) => ({ ...p, _accepted: true })));
      if (data.commercial_actions) {
        setCommercial({ ...commercial, ...data.commercial_actions,
          proposal_sent_date: data.commercial_actions.proposal_sent_date || "",
        });
      }
      if (data.itero_actions) {
        setIteroActions({ ...iteroActions, ...data.itero_actions,
          demo_booked_date: data.itero_actions.demo_booked_date || "",
          demo_completed_date: data.itero_actions.demo_completed_date || "",
          scanner_concerns: data.itero_actions.scanner_concerns || [],
        });
      }
      if (data.invisalign_actions) {
        setInvisalignActions({ ...invisalignActions, ...data.invisalign_actions });
      }
      if (Array.isArray(data.track_types) && data.track_types.length > 0) {
        const ts = data.track_types;
        if (ts.includes("ITERO") && ts.includes("INVISALIGN")) setTrackType("BOTH");
        else if (ts.includes("ITERO")) setTrackType("ITERO");
        else if (ts.includes("INVISALIGN")) setTrackType("INVISALIGN");
      }
      setStep(2);
    } catch (err) {
      toast.error("AI analysis failed — you can still save manually");
      setStep(2);
    } finally {
      setAnalyzing(false);
    }
  };

  const skipToReview = () => {
    setAi(null);
    setSkipAi(true);
    setStep(2);
  };

  const togglePromise = (i) => {
    setPromises((arr) => arr.map((p, idx) => idx === i ? { ...p, _accepted: !p._accepted } : p));
  };
  const editPromise = (i, patch) => {
    setPromises((arr) => arr.map((p, idx) => idx === i ? { ...p, ...patch } : p));
  };
  const addPromise = () => {
    const today = new Date(); today.setDate(today.getDate() + 3);
    setPromises((arr) => [...arr, { task_title: "", task_description: "", suggested_due_date: today.toISOString().slice(0, 10), priority: "Medium", _accepted: true }]);
  };

  const startRec = async () => {
    if (recording || transcribing) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      toast.error("Voice capture not supported on this device");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      const rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (recTimerRef.current) { clearInterval(recTimerRef.current); recTimerRef.current = null; }
        setRecording(false);
        setRecElapsed(0);
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        if (blob.size === 0) { toast.error("No audio captured"); return; }
        setTranscribing(true);
        try {
          const fd = new FormData();
          const ext = (rec.mimeType || "").includes("webm") ? "webm" : "wav";
          fd.append("audio", blob, `voice.${ext}`);
          const { data } = await api.post("/visits/transcribe", fd);
          const text = (data?.text || "").trim();
          if (!text) { toast.error("Couldn't pick up any speech — try again"); return; }
          const fullText = note ? `${note.trim()} ${text}` : text;
          setNote(fullText);
          toast.success(`Transcribed · ${text.length} chars`);
          // Voice is the fast path — go straight to AI analysis instead of requiring
          // a separate "Analyze" tap. Typed notes still need an explicit tap (the
          // TM may still be composing).
          runAi(fullText);
        } catch (err) {
          toast.error("Transcription failed — please type or try again");
        } finally {
          setTranscribing(false);
        }
      };
      recorderRef.current = rec;
      rec.start();
      setRecording(true);
      setRecElapsed(0);
      recTimerRef.current = setInterval(() => {
        setRecElapsed((s) => {
          if (s + 1 >= 110) { try { rec.stop(); } catch { /* ignore */ } } // auto-stop near 2 min cap
          return s + 1;
        });
      }, 1000);
    } catch (err) {
      toast.error("Microphone permission denied");
    }
  };

  const stopRec = () => {
    if (!recording) return;
    try { recorderRef.current?.stop(); } catch { /* ignore */ }
  };

  const save = async () => {
    if (!doctorId) { toast.error("Pick a doctor"); return; }
    if (!note.trim() && topics.length === 0) { toast.error("Add note or pick a topic"); return; }
    setSaving(true);
    try {
      const payload = {
        doctor_id: doctorId,
        visit_type: visitType,
        visit_date: (() => {
          // Combine selected date with current time so backend gets a full ISO timestamp
          if (!visitDate) return undefined;
          const now = new Date();
          const [y, m, d] = visitDate.split("-").map(Number);
          const dt = new Date(y, m - 1, d, now.getHours(), now.getMinutes(), now.getSeconds());
          return dt.toISOString();
        })(),
        free_text_note: note,
        confirmed_topics: topics,
        confirmed_barriers: barriers,
        sentiment,
        opportunity_state: opportunity,
        next_step: nextStep,
        promises: promises.filter((p) => p._accepted && p.task_title).map((p) => ({
          task_title: p.task_title,
          task_description: p.task_description || "",
          suggested_due_date: p.suggested_due_date,
          priority: p.priority || "Medium",
        })),
        ai_extraction: ai || null,
        track_type: trackType,
        itero_actions: trackType === "INVISALIGN" ? undefined : {
          ...iteroActions,
          demo_booked_date: iteroActions.demo_booked_date || null,
          demo_completed_date: iteroActions.demo_completed_date || null,
        },
        invisalign_actions: trackType === "ITERO" ? undefined : invisalignActions,
        commercial_actions: {
          ...commercial,
          proposal_sent_date: commercial.proposal_sent_date || null,
        },
        meeting_id: meetingId || undefined,
      };
      const { data } = await api.post("/visits", payload);
      toast.success(`Visit saved · ${data.created_tasks.length} promise(s) tracked`);
      navigate(`/doctors/${doctorId}`);
    } catch (err) {
      toast.error("Save failed");
    } finally {
      setSaving(false);
    }
  };

  const allTopics = taxonomy ? Object.values(taxonomy.topics).flat() : [];
  const allBarriers = taxonomy ? Object.values(taxonomy.barriers).flat() : [];

  return (
    <div className="max-w-3xl mx-auto" data-testid="log-visit-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Capture conversation</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          Log a <span className="font-medium">visit</span>
        </h1>
        <div className="mt-3 flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
          {[1, 2].map((n) => (
            <React.Fragment key={n}>
              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium ${step >= n ? "" : ""}`}
                style={{ background: step >= n ? "var(--brand-primary)" : "var(--bg-muted)", color: step >= n ? "white" : "var(--text-muted)" }}>{n}</div>
              {n < 2 && <div className="flex-1 h-px" style={{ background: step > n ? "var(--brand-primary)" : "var(--border-default)" }} />}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* Step 1: note — voice-first. No doctor needed yet; AI will try to detect
          who it was from what you say, and you'll confirm on the next screen. */}
      {step === 1 && (
        <div className="rounded-md border p-6 space-y-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="flex items-start gap-2 px-3 py-2 rounded text-xs" style={{ background: "var(--status-warning-bg)", color: "var(--status-warning)" }}>
            <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>Do not include patient names, patient medical details, confidential pricing, or pipeline values.</span>
          </div>
          <div>
            <div className="flex items-center justify-between mb-2">
              <Label className="block">What did you discuss? Mention the doctor's name and we'll find them for you.</Label>
              <button
                type="button"
                onClick={recording ? stopRec : startRec}
                disabled={transcribing}
                data-testid={recording ? "voice-stop-btn" : "voice-record-btn"}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all"
                style={{
                  background: recording ? "var(--status-danger)" : transcribing ? "var(--bg-muted)" : "var(--brand-primary)",
                  color: "white",
                  opacity: transcribing ? 0.7 : 1,
                }}
              >
                {transcribing ? (
                  <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Transcribing…</>
                ) : recording ? (
                  <><Square className="w-3 h-3" fill="white" /> Stop · {String(Math.floor(recElapsed / 60)).padStart(1, "0")}:{String(recElapsed % 60).padStart(2, "0")}</>
                ) : (
                  <><Mic className="w-3.5 h-3.5" /> Voice note</>
                )}
              </button>
            </div>
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Free text — write naturally, or tap Voice note to dictate. e.g. 'Just met with Dr. Ivanov, he's excited about the iTero demo…'"
              rows={9}
              className="bg-white"
              data-testid="visit-note-textarea"
            />
            <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{note.length} chars</div>
          </div>
          <div className="flex justify-end items-center gap-2 pt-2">
            <Button variant="outline" onClick={skipToReview} data-testid="step2-skip-ai-btn">Skip AI</Button>
            <Button onClick={() => runAi()} disabled={analyzing || !note.trim()} data-testid="step2-analyze-btn" style={{ background: "var(--brand-primary)", color: "white" }}>
              <Sparkles className="w-4 h-4 mr-1" />
              {analyzing ? "Analyzing…" : "Analyze with AI"}
            </Button>
          </div>
        </div>
      )}

      {/* Step 2: doctor confirm + review + save */}
      {step === 2 && (
        <div className="space-y-5" data-testid="review-step">
          <div className="rounded-md border p-6 space-y-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
            <div>
              <div className="flex items-center justify-between mb-2">
                <Label className="block">Doctor</Label>
                {doctorAutoMatched && doctorId && (
                  <span className="text-xs flex items-center gap-1" style={{ color: "var(--status-success)" }} data-testid="doctor-auto-matched-badge">
                    <Check className="w-3.5 h-3.5" /> Detected from your note
                  </span>
                )}
              </div>
              <Popover open={docPickerOpen} onOpenChange={setDocPickerOpen}>
                <PopoverTrigger asChild>
                  <Button variant="outline" className="w-full justify-between h-11 bg-white" data-testid="doctor-picker-btn">
                    {doctor ? (
                      <span className="flex items-center gap-2">
                        <span className="font-medium">{doctor.doctor_name}</span>
                        <span className="text-xs" style={{ color: "var(--text-muted)" }}>· {doctor.clinic_name}</span>
                      </span>
                    ) : (
                      <span style={{ color: "var(--text-muted)" }}>Select a doctor…</span>
                    )}
                    <ChevronRight className="w-4 h-4 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-[--radix-popover-trigger-width] p-0">
                  <Command>
                    <CommandInput
                      placeholder="Search doctor…"
                      data-testid="doctor-picker-input"
                      value={docPickerQuery}
                      onValueChange={setDocPickerQuery}
                    />
                    <CommandList className="max-h-72">
                      <CommandEmpty>No doctors</CommandEmpty>
                      {doctors.map((d) => (
                        <CommandItem key={d.id} onSelect={() => { setDoctorId(d.id); setDoctorAutoMatched(false); setDocPickerOpen(false); }} data-testid={`doctor-option-${d.id}`}>
                          <div className="flex flex-col">
                            <span className="font-medium">{d.doctor_name}</span>
                            <span className="text-xs" style={{ color: "var(--text-muted)" }}>{d.clinic_name} · {d.city} · {d.segment}</span>
                          </div>
                        </CommandItem>
                      ))}
                    </CommandList>
                    <div className="border-t p-2" style={{ borderColor: "var(--border-default)" }}>
                      <button
                        type="button"
                        onClick={() => { setDocPickerOpen(false); setAddingDoctor(true); }}
                        data-testid="log-visit-add-doctor"
                        className="w-full text-xs flex items-center gap-1 px-2 py-1.5 rounded hover:bg-[var(--bg-paper)] transition-colors"
                        style={{ color: "var(--brand-primary)" }}
                      >
                        <UserPlus className="w-3.5 h-3.5" />
                        <span>Can&apos;t find them? Add new doctor{docPickerQuery ? ` "${docPickerQuery}"` : ""}</span>
                      </button>
                    </div>
                  </Command>
                </PopoverContent>
              </Popover>
            </div>

            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <Label className="mb-2 block">Visit type</Label>
                <Select value={visitType} onValueChange={setVisitType}>
                  <SelectTrigger className="h-11 bg-white" data-testid="visit-type-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {VISIT_TYPES.map((v) => <SelectItem key={v} value={v}>{v}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="mb-2 block">Visit date</Label>
                <Input
                  type="date"
                  value={visitDate}
                  onChange={(e) => setVisitDate(e.target.value)}
                  max={(() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; })()}
                  className="h-11 bg-white"
                  data-testid="visit-date-input"
                />
              </div>
            </div>
          </div>

          {ai?.ai_error && (
            <div
              className="rounded-md border p-4"
              style={{
                background: "var(--status-warning-bg)",
                borderColor: "var(--status-warning)",
                color: "var(--text-primary)",
              }}
              data-testid="ai-error-notice"
            >
              <div className="font-medium flex items-center gap-2" style={{ color: "var(--status-warning)" }}>
                <AlertTriangle className="w-4 h-4" />
                AI analysis couldn&apos;t run for this note
              </div>
              <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
                You can still log the visit — just confirm or pick the topics, barriers, and
                sentiment manually below. Your note is saved untouched.
              </p>
              <p className="text-[11px] mt-2 font-mono" style={{ color: "var(--text-muted)" }}>
                {ai.ai_error}
              </p>
            </div>
          )}
          {ai?.privacy_warnings?.length > 0 && (
            <div className="rounded-md border p-4" style={{ background: "var(--status-danger-bg)", borderColor: "var(--status-danger)", color: "var(--status-danger)" }} data-testid="privacy-warning">
              <div className="font-medium flex items-center gap-2"><AlertTriangle className="w-4 h-4" />Privacy warnings</div>
              <ul className="text-sm mt-1 list-disc list-inside">
                {ai.privacy_warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          {ai?.summary && (
            <div className="rounded-md border p-4" style={{ background: "var(--status-info-bg)", borderColor: "var(--status-info)" }}>
              <div className="text-xs uppercase tracking-widest mb-1 flex items-center gap-1" style={{ color: "var(--status-info)" }}>
                <Brain className="w-3 h-3" /> AI summary
              </div>
              <div className="text-sm" style={{ color: "var(--text-primary)" }} data-testid="ai-summary">{ai.summary}</div>
            </div>
          )}

          <div className="rounded-md border p-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Topics — confirm or edit</div>
            <ChipPicker selected={topics} onChange={setTopics} groups={taxonomy?.topics || {}} testIdPrefix="topic" />
          </div>

          <div className="rounded-md border p-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Barriers — confirm or edit</div>
            <ChipPicker selected={barriers} onChange={setBarriers} groups={taxonomy?.barriers || {}} testIdPrefix="barrier" />
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <div className="rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
              <Label className="mb-2 block">Sentiment</Label>
              <Select value={sentiment} onValueChange={setSentiment}>
                <SelectTrigger className="bg-white" data-testid="sentiment-select"><SelectValue /></SelectTrigger>
                <SelectContent>{SENTIMENTS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
              <Label className="mb-2 block">Opportunity state</Label>
              <Select value={opportunity} onValueChange={setOpportunity}>
                <SelectTrigger className="bg-white" data-testid="opportunity-select"><SelectValue /></SelectTrigger>
                <SelectContent>{OP_STATES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>

          <div className="rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
            <Label className="mb-2 block">Suggested next action</Label>
            <Input value={nextStep} onChange={(e) => setNextStep(e.target.value)} placeholder="What's the natural next step?" className="bg-white" data-testid="next-step-input" />
          </div>

          <div className="rounded-md border p-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Promises detected</div>
                <div className="font-display text-base font-medium" style={{ color: "var(--brand-primary)" }}>Confirm follow-ups to track</div>
              </div>
              <Button variant="outline" size="sm" onClick={addPromise} data-testid="add-promise-btn"><Plus className="w-3 h-3 mr-1" />Add</Button>
            </div>
            <div className="space-y-2">
              {promises.map((p, i) => (
                <div key={i} className="rounded border p-3 flex flex-col sm:flex-row gap-3" style={{ background: p._accepted ? "var(--status-success-bg)" : "var(--bg-paper)", borderColor: "var(--border-default)" }} data-testid={`promise-${i}`}>
                  <button onClick={() => togglePromise(i)} className="flex-shrink-0 mt-1 w-5 h-5 rounded border flex items-center justify-center" style={{ background: p._accepted ? "var(--status-success)" : "white", borderColor: p._accepted ? "var(--status-success)" : "var(--border-default)" }} data-testid={`toggle-promise-${i}`}>
                    {p._accepted && <Check className="w-3 h-3 text-white" />}
                  </button>
                  <div className="flex-1 grid sm:grid-cols-2 gap-2">
                    <Input value={p.task_title} onChange={(e) => editPromise(i, { task_title: e.target.value })} placeholder="Task title" className="bg-white" data-testid={`promise-title-${i}`} />
                    <Input type="date" value={p.suggested_due_date || ""} onChange={(e) => editPromise(i, { suggested_due_date: e.target.value })} className="bg-white" data-testid={`promise-due-${i}`} />
                    <Input value={p.task_description || ""} onChange={(e) => editPromise(i, { task_description: e.target.value })} placeholder="Notes (optional)" className="bg-white sm:col-span-1" />
                    <Select value={p.priority || "Medium"} onValueChange={(v) => editPromise(i, { priority: v })}>
                      <SelectTrigger className="bg-white"><SelectValue /></SelectTrigger>
                      <SelectContent>{["Low", "Medium", "High"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <button onClick={() => setPromises((arr) => arr.filter((_, idx) => idx !== i))} className="text-xs" style={{ color: "var(--text-muted)" }} data-testid={`remove-promise-${i}`}>
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
              {promises.length === 0 && <div className="text-xs" style={{ color: "var(--text-muted)" }}>No follow-ups detected. Add one if needed.</div>}
            </div>
          </div>

          {ai?.market_signals?.length > 0 && (
            <div className="rounded-md border p-4" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
              <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>Market signals</div>
              <div className="flex flex-wrap gap-1.5">
                {ai.market_signals.map((m, i) => <span key={i} className="pill pill-info">{m}</span>)}
              </div>
            </div>
          )}

          <div className="rounded-md border p-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="track-selector">
            <div className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>What did this visit cover?</div>
            <div className="flex gap-2 flex-wrap">
              {[
                { v: "ITERO", label: "iTero only", color: "var(--brand-accent)" },
                { v: "INVISALIGN", label: "Invisalign only", color: "var(--brand-secondary)" },
                { v: "BOTH", label: "Both tracks", color: "var(--brand-primary)" },
              ].map((opt) => {
                const active = trackType === opt.v;
                return (
                  <button
                    key={opt.v}
                    type="button"
                    onClick={() => setTrackType(opt.v)}
                    data-testid={`track-${opt.v.toLowerCase()}`}
                    className="px-4 py-2 rounded-md text-sm font-medium transition-all"
                    style={{
                      background: active ? opt.color : "white",
                      color: active ? "white" : "var(--text-secondary)",
                      border: `1px solid ${active ? opt.color : "var(--border-default)"}`,
                    }}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
            <div className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>iTero fields appear only for iTero/Both. Invisalign fields appear only for Invisalign/Both.</div>
          </div>

          {(trackType === "ITERO" || trackType === "BOTH") && (
            <div className="rounded-md border p-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="itero-actions-section">
              <div className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--brand-accent)" }}>iTero · scanner</div>
              <div className="font-display text-base font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Demo & engagement</div>
              <div className="grid sm:grid-cols-2 gap-5">
                <div>
                  <CommercialCheck label="Demo discussed" checked={iteroActions.demo_discussed} onChange={(v) => setIteroActions({ ...iteroActions, demo_discussed: v })} testId="ca-demo-discussed" />
                  <CommercialCheck label="Demo booked" checked={iteroActions.demo_booked} onChange={(v) => setIteroActions({ ...iteroActions, demo_booked: v })} testId="ca-demo-booked" />
                  {iteroActions.demo_booked && (
                    <Input type="date" value={iteroActions.demo_booked_date} onChange={(e) => setIteroActions({ ...iteroActions, demo_booked_date: e.target.value })} className="bg-white mt-1 mb-2 h-8 text-xs" data-testid="ca-demo-booked-date" />
                  )}
                  <CommercialCheck label="Demo completed" checked={iteroActions.demo_completed} onChange={(v) => setIteroActions({ ...iteroActions, demo_completed: v })} testId="ca-demo-completed" />
                  {iteroActions.demo_completed && (
                    <Input type="date" value={iteroActions.demo_completed_date} onChange={(e) => setIteroActions({ ...iteroActions, demo_completed_date: e.target.value })} className="bg-white mt-1 h-8 text-xs" data-testid="ca-demo-completed-date" />
                  )}
                </div>
                <div>
                  <Label className="mb-2 block">Scanner interest level</Label>
                  <Select value={iteroActions.scanner_interest_level} onValueChange={(v) => setIteroActions({ ...iteroActions, scanner_interest_level: v })}>
                    <SelectTrigger className="bg-white" data-testid="scanner-interest-select"><SelectValue /></SelectTrigger>
                    <SelectContent>{["None", "Low", "Medium", "High"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              </div>
            </div>
          )}

          {(trackType === "INVISALIGN" || trackType === "BOTH") && (
            <div className="rounded-md border p-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="invisalign-actions-section">
              <div className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--brand-secondary)" }}>Invisalign · growth</div>
              <div className="font-display text-base font-medium mb-4" style={{ color: "var(--brand-primary)" }}>Programs, certification & confidence</div>
              <div className="grid sm:grid-cols-2 gap-5">
                <div>
                  <CommercialCheck label="Growth program explained" checked={invisalignActions.growth_program_explained} onChange={(v) => setInvisalignActions({ ...invisalignActions, growth_program_explained: v })} testId="ca-growth" />
                  <CommercialCheck label="Certification interest" checked={invisalignActions.certification_interest} onChange={(v) => setInvisalignActions({ ...invisalignActions, certification_interest: v })} testId="ca-cert" />
                  <CommercialCheck label="TPS discussed" checked={invisalignActions.tps_discussed} onChange={(v) => setInvisalignActions({ ...invisalignActions, tps_discussed: v })} testId="ca-tps" />
                  <CommercialCheck label="P2P suggested" checked={invisalignActions.p2p_suggested} onChange={(v) => setInvisalignActions({ ...invisalignActions, p2p_suggested: v })} testId="ca-p2p" />
                  <CommercialCheck label="Staff training needed" checked={invisalignActions.staff_training_needed} onChange={(v) => setInvisalignActions({ ...invisalignActions, staff_training_needed: v })} testId="ca-training" />
                </div>
                <div className="space-y-3">
                  <div>
                    <Label className="mb-1 block text-xs">Clinical confidence</Label>
                    <Select value={invisalignActions.clinical_confidence} onValueChange={(v) => setInvisalignActions({ ...invisalignActions, clinical_confidence: v })}>
                      <SelectTrigger className="bg-white h-9" data-testid="clinical-conf-select"><SelectValue /></SelectTrigger>
                      <SelectContent>{["Unknown", "Low", "Medium", "High"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs">Business confidence</Label>
                    <Select value={invisalignActions.business_confidence} onValueChange={(v) => setInvisalignActions({ ...invisalignActions, business_confidence: v })}>
                      <SelectTrigger className="bg-white h-9" data-testid="business-conf-select"><SelectValue /></SelectTrigger>
                      <SelectContent>{["Unknown", "Low", "Medium", "High"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs">Patient affordability perception</Label>
                    <Select value={invisalignActions.patient_affordability_perception} onValueChange={(v) => setInvisalignActions({ ...invisalignActions, patient_affordability_perception: v })}>
                      <SelectTrigger className="bg-white h-9" data-testid="affordability-select"><SelectValue /></SelectTrigger>
                      <SelectContent>{["Unknown", "Concerned", "Neutral", "Confident"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="rounded-md border p-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="commercial-actions-section">
            <div className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>Pricing & proposal (track-agnostic)</div>
            <div className="grid sm:grid-cols-2 gap-5">
              <div>
                <CommercialCheck label="Boost discussed" checked={commercial.boost_discussed} onChange={(v) => setCommercial({ ...commercial, boost_discussed: v })} testId="ca-boost" />
                <CommercialCheck label="Trade-in discussed" checked={commercial.trade_in_discussed} onChange={(v) => setCommercial({ ...commercial, trade_in_discussed: v })} testId="ca-tradein" />
                <CommercialCheck label="Trade-in interest" checked={commercial.trade_in_interest} onChange={(v) => setCommercial({ ...commercial, trade_in_interest: v })} testId="ca-tradein-interest" />
              </div>
              <div>
                <CommercialCheck label="Proposal discussed" checked={commercial.proposal_discussed} onChange={(v) => setCommercial({ ...commercial, proposal_discussed: v })} testId="ca-prop-discussed" />
                <CommercialCheck label="Proposal sent" checked={commercial.proposal_sent} onChange={(v) => setCommercial({ ...commercial, proposal_sent: v })} testId="ca-prop-sent" />
                {commercial.proposal_sent && (
                  <Input type="date" value={commercial.proposal_sent_date} onChange={(e) => setCommercial({ ...commercial, proposal_sent_date: e.target.value })} className="bg-white mt-1 mb-2 h-8 text-xs" data-testid="ca-prop-sent-date" />
                )}
                <CommercialCheck label="Follow-up done" checked={commercial.proposal_follow_up_done} onChange={(v) => setCommercial({ ...commercial, proposal_follow_up_done: v })} testId="ca-prop-followup" />
              </div>
            </div>
          </div>

          <div className="flex justify-between items-center gap-2 pt-2">
            <Button variant="ghost" onClick={() => setStep(1)} data-testid="step3-back-btn">
              <ChevronLeft className="w-4 h-4 mr-1" /> Back to note
            </Button>
            <Button onClick={save} disabled={saving} data-testid="save-visit-btn" className="font-medium" style={{ background: "var(--brand-secondary)", color: "white" }}>
              {saving ? "Saving…" : "Save visit"}
            </Button>
          </div>
        </div>
      )}

      <InlineAddDoctor
        open={addingDoctor}
        prefillName={docPickerQuery}
        onClose={() => setAddingDoctor(false)}
        onCreated={(d) => {
          setDoctors((prev) => [d, ...prev]);
          setDoctorId(d.id);
          setDocPickerQuery("");
          setAddingDoctor(false);
        }}
      />
    </div>
  );
}

function ChipPicker({ selected, onChange, groups, testIdPrefix }) {
  const [open, setOpen] = useState(false);
  const toggle = (v) => {
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  };
  const remove = (v) => onChange(selected.filter((x) => x !== v));
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {selected.map((s) => (
          <button key={s} onClick={() => remove(s)} className="pill pill-info" data-testid={`${testIdPrefix}-chip-${s}`}>
            {s} <X className="w-3 h-3" />
          </button>
        ))}
        {selected.length === 0 && <span className="text-xs" style={{ color: "var(--text-muted)" }}>None selected</span>}
      </div>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" data-testid={`${testIdPrefix}-add-btn`}>
            <Plus className="w-3 h-3 mr-1" /> Add {testIdPrefix}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[320px] p-0">
          <Command>
            <CommandInput placeholder={`Search ${testIdPrefix}…`} />
            <CommandList className="max-h-72">
              {Object.entries(groups).map(([cat, items]) => (
                <div key={cat} className="px-2 py-1">
                  <div className="text-[10px] uppercase tracking-widest px-2" style={{ color: "var(--text-muted)" }}>{cat}</div>
                  {items.map((it) => (
                    <CommandItem key={it} onSelect={() => toggle(it)} data-testid={`${testIdPrefix}-option-${it}`}>
                      <span className="flex-1">{it}</span>
                      {selected.includes(it) && <Check className="w-3 h-3" />}
                    </CommandItem>
                  ))}
                </div>
              ))}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}



function CommercialCheck({ label, checked, onChange, testId }) {
  return (
    <label className="flex items-center gap-2 py-1.5 cursor-pointer" data-testid={testId}>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className="w-4 h-4 rounded border flex items-center justify-center flex-shrink-0"
        style={{ background: checked ? "var(--brand-primary)" : "white", borderColor: checked ? "var(--brand-primary)" : "var(--border-default)" }}
      >
        {checked && <Check className="w-3 h-3 text-white" />}
      </button>
      <span className="text-sm" style={{ color: checked ? "var(--brand-primary)" : "var(--text-secondary)" }}>{label}</span>
    </label>
  );
}
