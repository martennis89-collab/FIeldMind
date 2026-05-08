import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "./ui/dialog";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "./ui/select";
import { UserPlus, Loader2 } from "lucide-react";
import { toast } from "sonner";

const DOCTOR_TYPES = ["GP", "Ortho", "Other"];
const SEGMENTS = ["New", "Lapsed", "Occasional", "Active", "Engaged", "Expert"];

/**
 * Tiny modal to create a doctor inline from any picker.
 * - Pre-fills the doctor name from whatever the user already typed in the search box.
 * - On success, calls onCreated(doctor) so the parent can both refresh its list and select it.
 */
export default function InlineAddDoctor({ open, onClose, onCreated, prefillName = "" }) {
  const [name, setName] = useState("");
  const [clinic, setClinic] = useState("");
  const [city, setCity] = useState("");
  const [doctorType, setDoctorType] = useState("GP");
  const [segment, setSegment] = useState("Occasional");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setName(prefillName || "");
      setClinic("");
      setCity("");
      setDoctorType("GP");
      setSegment("Occasional");
    }
  }, [open, prefillName]);

  const save = async () => {
    const n = name.trim();
    if (!n) {
      toast.error("Doctor name is required");
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.post("/doctors", {
        doctor_name: n,
        clinic_name: clinic.trim() || null,
        city: city.trim() || null,
        doctor_type: doctorType,
        segment,
      });
      toast.success(`Added ${data.doctor_name}`);
      onCreated?.(data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not add doctor");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !saving && onClose?.()}>
      <DialogContent className="max-w-md" data-testid="inline-add-doctor-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserPlus className="w-5 h-5" style={{ color: "var(--brand-primary)" }} />
            Add doctor
          </DialogTitle>
          <DialogDescription>
            Quick-add — you can fine-tune the rest later from the doctor's profile.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="iad-name">Doctor name *</Label>
            <Input
              id="iad-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Dr. Petrov"
              data-testid="inline-add-doctor-name"
              autoFocus
              className="mt-1"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="iad-clinic">Clinic</Label>
              <Input
                id="iad-clinic"
                value={clinic}
                onChange={(e) => setClinic(e.target.value)}
                placeholder="Smile Studio"
                data-testid="inline-add-doctor-clinic"
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="iad-city">City</Label>
              <Input
                id="iad-city"
                value={city}
                onChange={(e) => setCity(e.target.value)}
                placeholder="Sofia"
                data-testid="inline-add-doctor-city"
                className="mt-1"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Type</Label>
              <Select value={doctorType} onValueChange={setDoctorType}>
                <SelectTrigger data-testid="inline-add-doctor-type" className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {DOCTOR_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Segment</Label>
              <Select value={segment} onValueChange={setSegment}>
                <SelectTrigger data-testid="inline-add-doctor-segment" className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {SEGMENTS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button
            onClick={save}
            disabled={saving || !name.trim()}
            data-testid="inline-add-doctor-save"
            style={{ background: "var(--brand-primary)", color: "white" }}
          >
            {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <UserPlus className="w-4 h-4 mr-1" />}
            {saving ? "Adding…" : "Add doctor"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
