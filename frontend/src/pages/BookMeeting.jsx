import React, { useEffect, useMemo, useState } from "react";
import api from "../lib/api";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Search as SearchIcon, CalendarPlus, ChevronLeft } from "lucide-react";
import { toast } from "sonner";

function defaultDateTime() {
  // Tomorrow at 10:00 (local) → input value YYYY-MM-DDTHH:mm
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(10, 0, 0, 0);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function BookMeeting() {
  const [params] = useSearchParams();
  const preDoctorId = params.get("doctor_id");
  const navigate = useNavigate();

  const [doctors, setDoctors] = useState([]);
  const [doctorId, setDoctorId] = useState(preDoctorId || "");
  const [docQuery, setDocQuery] = useState("");
  const [scheduledAt, setScheduledAt] = useState(defaultDateTime());
  const [durationMinutes, setDurationMinutes] = useState(30);
  const [subject, setSubject] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/doctors").then((r) => setDoctors(Array.isArray(r.data) ? r.data : (r.data.doctors || [])));
  }, []);

  const selectedDoctor = useMemo(
    () => doctors.find((d) => d.id === doctorId) || null,
    [doctors, doctorId],
  );

  const filtered = useMemo(() => {
    if (!docQuery.trim()) return doctors.slice(0, 12);
    const q = docQuery.toLowerCase().trim();
    return doctors
      .filter((d) =>
        (d.doctor_name || "").toLowerCase().includes(q) ||
        (d.clinic_name || "").toLowerCase().includes(q) ||
        (d.city || "").toLowerCase().includes(q),
      )
      .slice(0, 20);
  }, [doctors, docQuery]);

  const submit = async () => {
    if (!doctorId) { toast.error("Pick a doctor"); return; }
    if (!scheduledAt) { toast.error("Pick a date and time"); return; }
    setBusy(true);
    try {
      const iso = new Date(scheduledAt).toISOString();
      await api.post("/meetings", {
        doctor_id: doctorId,
        scheduled_at: iso,
        duration_minutes: Number(durationMinutes) || 30,
        subject: subject.trim() || null,
      });
      toast.success("Meeting booked");
      navigate("/meetings");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not book");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl" data-testid="book-meeting-page">
      <button onClick={() => navigate(-1)} data-testid="book-meeting-back" className="text-sm flex items-center gap-1 mb-3" style={{ color: "var(--text-secondary)" }}>
        <ChevronLeft className="w-4 h-4" /> Back
      </button>
      <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Schedule</div>
      <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight mb-6" style={{ color: "var(--brand-primary)" }}>
        Book a <span className="font-medium">meeting.</span>
      </h1>

      <div className="space-y-5 rounded-md border p-5" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
        {/* Doctor */}
        <div>
          <Label className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Doctor</Label>
          {selectedDoctor ? (
            <div className="rounded-md border bg-white p-3 mt-1 flex items-start justify-between gap-3" style={{ borderColor: "var(--border-default)" }} data-testid="selected-doctor">
              <div>
                <div className="font-medium" style={{ color: "var(--brand-primary)" }}>{selectedDoctor.doctor_name}</div>
                <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  {[selectedDoctor.clinic_name, selectedDoctor.city, selectedDoctor.segment].filter(Boolean).join(" · ")}
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={() => { setDoctorId(""); setDocQuery(""); }} data-testid="clear-doctor-btn">
                Change
              </Button>
            </div>
          ) : (
            <>
              <div className="relative mt-1">
                <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: "var(--text-muted)" }} />
                <Input
                  value={docQuery}
                  onChange={(e) => setDocQuery(e.target.value)}
                  placeholder="Search doctor by name, clinic, city…"
                  className="pl-9 bg-white"
                  data-testid="doctor-search-input"
                  autoFocus
                />
              </div>
              <div className="mt-2 max-h-72 overflow-y-auto rounded-md border bg-white" style={{ borderColor: "var(--border-default)" }}>
                {filtered.length === 0 ? (
                  <div className="p-3 text-sm" style={{ color: "var(--text-muted)" }}>No doctors match.</div>
                ) : (
                  filtered.map((d) => (
                    <button
                      key={d.id}
                      onClick={() => setDoctorId(d.id)}
                      data-testid={`doctor-option-${d.id}`}
                      className="w-full text-left px-3 py-2 border-b last:border-b-0 hover:bg-[var(--bg-paper)] transition-colors"
                      style={{ borderColor: "var(--border-default)" }}
                    >
                      <div className="text-sm font-medium" style={{ color: "var(--brand-primary)" }}>{d.doctor_name}</div>
                      <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                        {[d.clinic_name, d.city, d.segment].filter(Boolean).join(" · ") || "—"}
                      </div>
                    </button>
                  ))
                )}
              </div>
            </>
          )}
        </div>

        {/* Date/time + duration */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="sm:col-span-2">
            <Label className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>When</Label>
            <Input
              type="datetime-local"
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
              className="bg-white mt-1"
              data-testid="meeting-datetime"
            />
          </div>
          <div>
            <Label className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Duration (min)</Label>
            <Input
              type="number"
              min={5}
              step={5}
              value={durationMinutes}
              onChange={(e) => setDurationMinutes(e.target.value)}
              className="bg-white mt-1"
              data-testid="meeting-duration"
            />
          </div>
        </div>

        {/* Subject */}
        <div>
          <Label className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Subject (optional)</Label>
          <Textarea
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Why are you meeting? e.g. iTero demo, follow-up on proposal."
            rows={3}
            className="bg-white mt-1"
            data-testid="meeting-subject"
          />
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="outline" onClick={() => navigate(-1)} data-testid="cancel-book-btn">Cancel</Button>
          <Button
            onClick={submit}
            disabled={busy || !doctorId || !scheduledAt}
            data-testid="submit-book-btn"
            style={{ background: "var(--brand-secondary)", color: "white" }}
          >
            <CalendarPlus className="w-4 h-4 mr-1" /> {busy ? "Booking…" : "Book meeting"}
          </Button>
        </div>
      </div>
    </div>
  );
}
