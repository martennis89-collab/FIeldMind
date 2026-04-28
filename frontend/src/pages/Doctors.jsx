import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Input } from "../components/ui/input";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Button } from "../components/ui/button";
import { StatusPill, sentimentKind, cadenceKind, priorityKind, SegmentBadge } from "../components/StatusPill";
import { Search as SearchIcon, MapPin, Filter, Plus, Upload } from "lucide-react";

const ALL = "__ALL__";

export default function Doctors() {
  const { user } = useAuth();
  const [docs, setDocs] = useState([]);
  const [q, setQ] = useState("");
  const [segment, setSegment] = useState(ALL);
  const [cadence, setCadence] = useState(ALL);
  const [city, setCity] = useState(ALL);
  const [loading, setLoading] = useState(true);
  const [taxonomy, setTaxonomy] = useState(null);

  useEffect(() => {
    api.get("/taxonomy").then((r) => setTaxonomy(r.data));
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const params = {};
      if (q) params.q = q;
      if (segment !== ALL) params.segment = segment;
      if (cadence !== ALL) params.cadence = cadence;
      if (city !== ALL) params.city = city;
      const { data } = await api.get("/doctors", { params });
      setDocs(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line
  }, [segment, cadence, city]);

  useEffect(() => {
    const t = setTimeout(() => load(), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line
  }, [q]);

  const cities = Array.from(new Set(docs.map((d) => d.city).filter(Boolean))).sort();

  return (
    <div data-testid="doctors-page">
      <div className="flex items-center justify-between mb-6 gap-3 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Roster</div>
          <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Doctors <span className="font-medium">({docs.length})</span>
          </h1>
        </div>
        {user?.role === "TM" && (
          <Link to="/doctors/import" data-testid="import-doctors-link">
            <Button variant="outline" style={{ borderColor: "var(--brand-primary)", color: "var(--brand-primary)" }}>
              <Upload className="w-4 h-4 mr-1" /> Import doctors
            </Button>
          </Link>
        )}
      </div>

      <div className="rounded-md border p-4 mb-5 grid grid-cols-1 md:grid-cols-12 gap-3" style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)" }}>
        <div className="md:col-span-5 relative">
          <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: "var(--text-muted)" }} />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name, clinic, city…"
            className="pl-9 h-10 bg-white"
            data-testid="doctors-search-input"
          />
        </div>
        <div className="md:col-span-2">
          <Select value={segment} onValueChange={setSegment}>
            <SelectTrigger className="h-10 bg-white" data-testid="filter-segment"><SelectValue placeholder="Segment" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All segments</SelectItem>
              {(taxonomy?.segments || []).map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="md:col-span-2">
          <Select value={cadence} onValueChange={setCadence}>
            <SelectTrigger className="h-10 bg-white" data-testid="filter-cadence"><SelectValue placeholder="Cadence" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All cadence</SelectItem>
              {["Good", "Due Soon", "Overdue", "Critical"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="md:col-span-3">
          <Select value={city} onValueChange={setCity}>
            <SelectTrigger className="h-10 bg-white" data-testid="filter-city"><SelectValue placeholder="City" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All cities</SelectItem>
              {cities.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="doctors-grid">
          {docs.map((d, idx) => (
            <Link
              key={d.id}
              to={`/doctors/${d.id}`}
              data-testid={`doctor-card-${d.id}`}
              className="rounded-md border p-5 card-lift fade-up block"
              style={{ background: "var(--bg-default)", borderColor: "var(--border-default)", animationDelay: `${idx * 25}ms` }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-display text-lg font-semibold truncate" style={{ color: "var(--brand-primary)" }}>{d.doctor_name}</div>
                  <div className="text-sm flex items-center gap-1 truncate" style={{ color: "var(--text-secondary)" }}>
                    <MapPin className="w-3 h-3" /> {d.clinic_name || "—"} · {d.city || "—"}
                  </div>
                </div>
                <SegmentBadge segment={d.segment} />
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <StatusPill kind={priorityKind(d.visit_priority_label)}>{d.visit_priority_label} {d.visit_priority_score}</StatusPill>
                <StatusPill kind={cadenceKind(d.cadence_status)}>{d.cadence_status}</StatusPill>
                {d.current_sentiment && <StatusPill kind={sentimentKind(d.current_sentiment)}>{d.current_sentiment}</StatusPill>}
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                <div>
                  <div className="uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Last</div>
                  <div>{d.days_since_last_visit ?? "—"}d</div>
                </div>
                <div>
                  <div className="uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Promises</div>
                  <div>{d.open_promises} {d.overdue_promises > 0 && <span style={{ color: "var(--status-danger)" }}>({d.overdue_promises} late)</span>}</div>
                </div>
                <div>
                  <div className="uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Q visits</div>
                  <div>{d.visits_this_quarter}</div>
                </div>
              </div>
              {d.top_barriers?.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {d.top_barriers.slice(0, 2).map((b) => (
                    <span key={b} className="pill pill-muted">{b}</span>
                  ))}
                </div>
              )}
            </Link>
          ))}
          {docs.length === 0 && <div className="col-span-full text-sm" style={{ color: "var(--text-muted)" }}>No doctors match your filters.</div>}
        </div>
      )}
    </div>
  );
}
