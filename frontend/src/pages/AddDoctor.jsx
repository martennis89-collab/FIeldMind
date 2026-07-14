import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Switch } from "../components/ui/switch";
import { toast } from "sonner";
import { ChevronLeft, Save, Loader2, UserPlus } from "lucide-react";

const DOCTOR_TYPES = ["GP", "Ortho", "Other"];
const SEGMENTS = ["New", "Lapsed", "Occasional", "Active", "Engaged", "Expert"];

export default function AddDoctor() {
  const navigate = useNavigate();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [clinicName, setClinicName] = useState("");
  const [city, setCity] = useState("");
  const [region, setRegion] = useState("");
  const [doctorType, setDoctorType] = useState("GP");
  const [segment, setSegment] = useState("Occasional");
  const [generalNotes, setGeneralNotes] = useState("");
  const [inGrowthProgram, setInGrowthProgram] = useState(false);
  const [saving, setSaving] = useState(false);

  const save = async (andLogVisit = false) => {
    const fn = firstName.trim();
    const ln = lastName.trim();
    const name = `${fn} ${ln}`.trim();
    if (!name) { toast.error("Doctor name is required"); return; }
    setSaving(true);
    try {
      const { data } = await api.post("/doctors", {
        doctor_name: name,
        clinic_name: clinicName.trim() || null,
        city: city.trim() || null,
        region: region.trim() || null,
        doctor_type: doctorType,
        segment,
        general_notes: generalNotes.trim() || null,
        in_growth_program: inGrowthProgram,
      });
      toast.success(`Added ${data.doctor_name}`);
      if (andLogVisit) {
        navigate(`/log-visit?doctor_id=${data.id}`);
      } else {
        navigate(`/doctors/${data.id}`);
      }
    } catch (err) {
      const detail = err?.response?.data?.detail;
      // Duplicate doctor: offer to open the existing profile instead of a dead-end toast.
      if (err?.response?.status === 409 && detail && typeof detail === "object" && detail.code === "DUPLICATE_DOCTOR") {
        toast.error(detail.message || "Doctor already exists", {
          description: "Open the existing profile instead?",
          duration: 8000,
          action: {
            label: "Open existing",
            onClick: () => navigate(`/doctors/${detail.existing_id}`),
          },
        });
      } else {
        toast.error(typeof detail === "string" ? detail : "Could not add doctor");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto" data-testid="add-doctor-page">
      <div className="mb-5 flex items-center gap-2">
        <button onClick={() => navigate(-1)} className="p-1.5 rounded hover:bg-[var(--bg-paper)]" data-testid="add-doctor-back"><ChevronLeft className="w-4 h-4" /></button>
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Roster</div>
          <h1 className="font-display text-2xl sm:text-3xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Add a <span className="font-medium">doctor.</span>
          </h1>
        </div>
      </div>

      <div className="rounded-md border p-5 space-y-3" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="mb-1 block">First name <span style={{ color: "var(--status-danger)" }}>*</span></Label>
            <Input value={firstName} onChange={(e) => setFirstName(e.target.value)} placeholder="Ivan" className="bg-white" data-testid="doctor-first-name-input" autoFocus />
          </div>
          <div>
            <Label className="mb-1 block">Last name</Label>
            <Input value={lastName} onChange={(e) => setLastName(e.target.value)} placeholder="Petrova" className="bg-white" data-testid="doctor-last-name-input" />
          </div>
        </div>
        <div>
          <Label className="mb-1 block">Clinic / practice</Label>
          <Input value={clinicName} onChange={(e) => setClinicName(e.target.value)} placeholder="Bright Dental" className="bg-white" data-testid="clinic-name-input" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="mb-1 block">City</Label>
            <Input value={city} onChange={(e) => setCity(e.target.value)} placeholder="Sofia" className="bg-white" data-testid="doctor-city-input" />
          </div>
          <div>
            <Label className="mb-1 block">Region</Label>
            <Input value={region} onChange={(e) => setRegion(e.target.value)} placeholder="Sofia" className="bg-white" data-testid="doctor-region-input" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="mb-1 block">Type</Label>
            <Select value={doctorType} onValueChange={setDoctorType}>
              <SelectTrigger className="bg-white" data-testid="doctor-type-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                {DOCTOR_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="mb-1 block">Segment</Label>
            <Select value={segment} onValueChange={setSegment}>
              <SelectTrigger className="bg-white" data-testid="doctor-segment-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                {SEGMENTS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="flex items-center justify-between rounded-md border px-3 py-2.5" style={{ borderColor: "var(--border-default)" }}>
          <div>
            <Label className="block">Growth programme</Label>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>Requires at least a monthly visit</div>
          </div>
          <Switch checked={inGrowthProgram} onCheckedChange={setInGrowthProgram} data-testid="doctor-growth-program-switch" />
        </div>
        <div>
          <Label className="mb-1 block">General notes</Label>
          <Textarea
            rows={3}
            value={generalNotes}
            onChange={(e) => setGeneralNotes(e.target.value)}
            placeholder="Anything worth knowing — interests, communication preferences, family run-business…"
            className="bg-white"
            data-testid="doctor-notes-input"
          />
        </div>
      </div>

      <div className="flex flex-wrap justify-between gap-2 mt-5">
        <Button variant="ghost" onClick={() => navigate(-1)} data-testid="add-doctor-cancel">Cancel</Button>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => save(true)} disabled={saving || !(firstName.trim() || lastName.trim())} data-testid="add-doctor-save-and-log">
            <UserPlus className="w-4 h-4 mr-1" /> Save &amp; log a visit
          </Button>
          <Button onClick={() => save(false)} disabled={saving || !(firstName.trim() || lastName.trim())} data-testid="add-doctor-save-btn" style={{ background: "var(--brand-secondary)", color: "white" }}>
            {saving ? <><Loader2 className="w-4 h-4 mr-1 animate-spin" /> Saving…</> : <><Save className="w-4 h-4 mr-1" /> Save doctor</>}
          </Button>
        </div>
      </div>
    </div>
  );
}
