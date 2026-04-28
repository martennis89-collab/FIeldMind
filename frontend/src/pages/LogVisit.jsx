import React, { useEffect, useMemo, useState } from "react";
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
import { Brain, ChevronRight, ChevronLeft, Sparkles, Check, AlertTriangle, X, Clock, Plus } from "lucide-react";

const VISIT_TYPES = ["In-person visit", "Phone call", "Online meeting", "Event conversation", "Training/session", "Other"];
const SENTIMENTS = ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"];
const OP_STATES = ["Blocked", "Stuck", "Advancing", "Unknown"];

export default function LogVisit() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const initialDoctorId = params.get("doctor");

  const [step, setStep] = useState(1); // 1 doctor, 2 note, 3 review
  const [doctors, setDoctors] = useState([]);
  const [taxonomy, setTaxonomy] = useState(null);
  const [doctorId, setDoctorId] = useState(initialDoctorId || "");
  const [docPickerOpen, setDocPickerOpen] = useState(false);
  const [visitType, setVisitType] = useState("In-person visit");
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

  useEffect(() => {
    api.get("/doctors").then((r) => setDoctors(r.data));
    api.get("/taxonomy").then((r) => setTaxonomy(r.data));
  }, []);

  const doctor = useMemo(() => doctors.find((d) => d.id === doctorId), [doctors, doctorId]);

  const runAi = async () => {
    if (!note.trim()) { toast.error("Add a note first"); return; }
    setAnalyzing(true);
    try {
      const { data } = await api.post("/visits/analyze", { note, doctor_id: doctorId });
      setAi(data);
      setTopics(data.topics || []);
      setBarriers(data.barriers || []);
      setSentiment(data.sentiment || "Neutral");
      setOpportunity(data.opportunity_state || "Unknown");
      setNextStep(data.suggested_next_action || "");
      setPromises((data.promises_detected || []).map((p) => ({ ...p, _accepted: true })));
      setStep(3);
    } catch (err) {
      toast.error("AI analysis failed — you can still save manually");
      setStep(3);
    } finally {
      setAnalyzing(false);
    }
  };

  const skipToReview = () => {
    setAi(null);
    setSkipAi(true);
    setStep(3);
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

  const save = async () => {
    if (!doctorId) { toast.error("Pick a doctor"); return; }
    if (!note.trim() && topics.length === 0) { toast.error("Add note or pick a topic"); return; }
    setSaving(true);
    try {
      const payload = {
        doctor_id: doctorId,
        visit_type: visitType,
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
          {[1, 2, 3].map((n) => (
            <React.Fragment key={n}>
              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium ${step >= n ? "" : ""}`}
                style={{ background: step >= n ? "var(--brand-primary)" : "var(--bg-muted)", color: step >= n ? "white" : "var(--text-muted)" }}>{n}</div>
              {n < 3 && <div className="flex-1 h-px" style={{ background: step > n ? "var(--brand-primary)" : "var(--border-default)" }} />}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* Step 1: pick doctor + type */}
      {step === 1 && (
        <div className="rounded-md border p-6 space-y-5" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div>
            <Label className="mb-2 block">Doctor</Label>
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
                  <CommandInput placeholder="Search doctor…" data-testid="doctor-picker-input" />
                  <CommandList className="max-h-72">
                    <CommandEmpty>No doctors</CommandEmpty>
                    {doctors.map((d) => (
                      <CommandItem key={d.id} onSelect={() => { setDoctorId(d.id); setDocPickerOpen(false); }} data-testid={`pick-doctor-${d.id}`}>
                        <div className="flex flex-col">
                          <span className="font-medium">{d.doctor_name}</span>
                          <span className="text-xs" style={{ color: "var(--text-muted)" }}>{d.clinic_name} · {d.city} · {d.segment}</span>
                        </div>
                      </CommandItem>
                    ))}
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
          </div>

          <div>
            <Label className="mb-2 block">Visit type</Label>
            <Select value={visitType} onValueChange={setVisitType}>
              <SelectTrigger className="h-11 bg-white" data-testid="visit-type-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                {VISIT_TYPES.map((v) => <SelectItem key={v} value={v}>{v}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button onClick={() => setStep(2)} disabled={!doctorId} data-testid="step1-next-btn" style={{ background: "var(--brand-primary)", color: "white" }}>
              Next <ChevronRight className="w-4 h-4 ml-1" />
            </Button>
          </div>
        </div>
      )}

      {/* Step 2: note */}
      {step === 2 && (
        <div className="rounded-md border p-6 space-y-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
          <div className="flex items-start gap-2 px-3 py-2 rounded text-xs" style={{ background: "var(--status-warning-bg)", color: "var(--status-warning)" }}>
            <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>Do not include patient names, patient medical details, confidential pricing, or pipeline values.</span>
          </div>
          <div>
            <Label className="mb-2 block">What did you discuss?</Label>
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Free text — write naturally. AI will extract topics, barriers, sentiment, and promises in the next step."
              rows={9}
              className="bg-white"
              data-testid="visit-note-textarea"
            />
            <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{note.length} chars</div>
          </div>
          <div className="flex justify-between items-center gap-2 pt-2">
            <Button variant="ghost" onClick={() => setStep(1)} data-testid="step2-back-btn">
              <ChevronLeft className="w-4 h-4 mr-1" /> Back
            </Button>
            <div className="flex gap-2">
              <Button variant="outline" onClick={skipToReview} data-testid="skip-ai-btn">Skip AI</Button>
              <Button onClick={runAi} disabled={analyzing || !note.trim()} data-testid="analyze-btn" style={{ background: "var(--brand-primary)", color: "white" }}>
                <Sparkles className="w-4 h-4 mr-1" />
                {analyzing ? "Analyzing…" : "Analyze with AI"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Step 3: review + save */}
      {step === 3 && (
        <div className="space-y-5" data-testid="review-step">
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

          <div className="flex justify-between items-center gap-2 pt-2">
            <Button variant="ghost" onClick={() => setStep(2)} data-testid="step3-back-btn">
              <ChevronLeft className="w-4 h-4 mr-1" /> Back to note
            </Button>
            <Button onClick={save} disabled={saving} data-testid="save-visit-btn" className="font-medium" style={{ background: "var(--brand-secondary)", color: "white" }}>
              {saving ? "Saving…" : "Save visit"}
            </Button>
          </div>
        </div>
      )}
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
