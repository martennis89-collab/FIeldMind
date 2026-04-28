import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Input } from "../components/ui/input";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";
import { Button } from "../components/ui/button";
import { StatusPill, sentimentKind, cadenceKind, priorityKind, SegmentBadge } from "../components/StatusPill";
import { Search as SearchIcon, MapPin, Plus, Upload, LayoutGrid, List as ListIcon, Trash2 } from "lucide-react";
import { toast } from "sonner";

const ALL = "__ALL__";

export default function Doctors() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [docs, setDocs] = useState([]);
  const [q, setQ] = useState("");
  const [segment, setSegment] = useState(ALL);
  const [cadence, setCadence] = useState(ALL);
  const [city, setCity] = useState(ALL);
  const [loading, setLoading] = useState(true);
  const [taxonomy, setTaxonomy] = useState(null);
  const [view, setView] = useState(() => localStorage.getItem("doctors_view") || "list");
  const [selected, setSelected] = useState(() => new Set());
  const [busy, setBusy] = useState(false);

  const canDelete = user?.role === "TM" || user?.role === "Admin";

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
      // Drop selections for doctors no longer in list
      setSelected((prev) => new Set([...prev].filter((id) => data.some((d) => d.id === id))));
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

  const setViewMode = (m) => {
    setView(m);
    localStorage.setItem("doctors_view", m);
  };

  const toggleOne = (id) => {
    setSelected((prev) => {
      const s = new Set(prev);
      if (s.has(id)) s.delete(id);
      else s.add(id);
      return s;
    });
  };

  const toggleAll = () => {
    setSelected((prev) => {
      if (prev.size === docs.length) return new Set();
      return new Set(docs.map((d) => d.id));
    });
  };

  const deleteOne = async (d) => {
    if (!window.confirm(`Delete ${d.doctor_name}? This also removes all their visits and tasks. This cannot be undone.`)) return;
    setBusy(true);
    try {
      await api.delete(`/doctors/${d.id}`);
      setDocs((prev) => prev.filter((x) => x.id !== d.id));
      setSelected((prev) => { const s = new Set(prev); s.delete(d.id); return s; });
      toast.success(`${d.doctor_name} deleted`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to delete");
    } finally {
      setBusy(false);
    }
  };

  const deleteSelected = async () => {
    if (selected.size === 0) return;
    if (!window.confirm(`Delete ${selected.size} doctor${selected.size > 1 ? "s" : ""}? Their visits and tasks will be removed too. This cannot be undone.`)) return;
    setBusy(true);
    try {
      const ids = [...selected];
      const { data } = await api.post("/doctors/bulk-delete", { ids });
      const deletedSet = new Set(data.deleted_ids || []);
      setDocs((prev) => prev.filter((x) => !deletedSet.has(x.id)));
      setSelected(new Set());
      toast.success(`Deleted ${data.deleted_count} doctor${data.deleted_count !== 1 ? "s" : ""}${(data.skipped_ids || []).length ? ` (${data.skipped_ids.length} skipped)` : ""}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to bulk delete");
    } finally {
      setBusy(false);
    }
  };

  const cities = Array.from(new Set(docs.map((d) => d.city).filter(Boolean))).sort();
  const allSelected = docs.length > 0 && selected.size === docs.length;

  return (
    <div data-testid="doctors-page">
      <div className="flex items-center justify-between mb-6 gap-3 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Roster</div>
          <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Doctors <span className="font-medium">({docs.length})</span>
          </h1>
        </div>
        <div className="flex gap-2 items-center flex-wrap">
          {/* View toggle */}
          <div className="inline-flex rounded-md border" style={{ borderColor: "var(--border-default)", background: "var(--bg-paper)" }} data-testid="doctors-view-toggle">
            <button
              onClick={() => setViewMode("list")}
              data-testid="doctors-view-list"
              className="px-3 py-2 text-xs flex items-center gap-1 rounded-l-md transition-colors"
              style={{ background: view === "list" ? "var(--brand-primary)" : "transparent", color: view === "list" ? "white" : "var(--text-secondary)" }}
            >
              <ListIcon className="w-3.5 h-3.5" /> List
            </button>
            <button
              onClick={() => setViewMode("cards")}
              data-testid="doctors-view-cards"
              className="px-3 py-2 text-xs flex items-center gap-1 rounded-r-md transition-colors"
              style={{ background: view === "cards" ? "var(--brand-primary)" : "transparent", color: view === "cards" ? "white" : "var(--text-secondary)" }}
            >
              <LayoutGrid className="w-3.5 h-3.5" /> Cards
            </button>
          </div>
          {(user?.role === "TM" || user?.role === "Admin") && (
            <>
              <Link to="/doctors/add" data-testid="add-doctor-link">
                <Button style={{ background: "var(--brand-secondary)", color: "white" }}>
                  <Plus className="w-4 h-4 mr-1" /> Add doctor
                </Button>
              </Link>
              <Link to="/doctors/import" data-testid="import-doctors-link">
                <Button variant="outline" style={{ borderColor: "var(--brand-primary)", color: "var(--brand-primary)" }}>
                  <Upload className="w-4 h-4 mr-1" /> Import
                </Button>
              </Link>
            </>
          )}
        </div>
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

      {/* Bulk action bar */}
      {canDelete && selected.size > 0 && (
        <div
          className="flex items-center justify-between rounded-md border px-4 py-2 mb-4"
          style={{ background: "#FFF3EE", borderColor: "var(--brand-secondary)" }}
          data-testid="bulk-action-bar"
        >
          <div className="text-sm" style={{ color: "var(--brand-primary)" }}>
            <span className="font-semibold">{selected.size}</span> selected
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSelected(new Set())}
              data-testid="bulk-clear-btn"
            >
              Clear
            </Button>
            <Button
              size="sm"
              onClick={deleteSelected}
              disabled={busy}
              style={{ background: "var(--status-danger)", color: "white" }}
              data-testid="bulk-delete-btn"
            >
              <Trash2 className="w-3.5 h-3.5 mr-1" />
              Delete {selected.size}
            </Button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : view === "list" ? (
        <div className="rounded-md border overflow-hidden" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid="doctors-list">
          {/* Header */}
          <div
            className="hidden sm:grid items-center px-4 py-2 text-xs uppercase tracking-widest font-medium border-b"
            style={{ gridTemplateColumns: "32px 2fr 1.4fr 0.9fr 0.9fr 1fr 0.7fr 36px", color: "var(--text-muted)", background: "var(--bg-paper)", borderColor: "var(--border-default)" }}
          >
            {canDelete ? (
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleAll}
                className="cursor-pointer"
                data-testid="select-all-doctors"
                aria-label="Select all"
              />
            ) : <span />}
            <div>Doctor</div>
            <div>Clinic · City</div>
            <div>Segment</div>
            <div>Cadence</div>
            <div>Sentiment</div>
            <div className="text-right">Last visit</div>
            <span />
          </div>
          {docs.map((d, idx) => {
            const isSel = selected.has(d.id);
            return (
              <div
                key={d.id}
                data-testid={`doctor-row-${d.id}`}
                className="grid sm:grid-cols-[32px_2fr_1.4fr_0.9fr_0.9fr_1fr_0.7fr_36px] items-center gap-2 sm:gap-0 px-4 py-3 border-b last:border-b-0 fade-up transition-colors"
                style={{
                  borderColor: "var(--border-default)",
                  background: isSel ? "rgba(124, 161, 180, 0.08)" : "transparent",
                  animationDelay: `${Math.min(idx, 30) * 15}ms`,
                }}
              >
                {canDelete ? (
                  <input
                    type="checkbox"
                    checked={isSel}
                    onChange={() => toggleOne(d.id)}
                    className="cursor-pointer"
                    aria-label={`Select ${d.doctor_name}`}
                    data-testid={`select-doctor-${d.id}`}
                  />
                ) : <span />}
                <div
                  className="min-w-0 cursor-pointer"
                  onClick={() => navigate(`/doctors/${d.id}`)}
                  data-testid={`doctor-row-name-${d.id}`}
                >
                  <div className="font-medium truncate" style={{ color: "var(--brand-primary)" }}>{d.doctor_name}</div>
                  <div className="text-xs flex items-center gap-1 sm:hidden truncate" style={{ color: "var(--text-secondary)" }}>
                    <MapPin className="w-3 h-3" /> {d.clinic_name || "—"} · {d.city || "—"}
                  </div>
                </div>
                <div className="text-sm truncate hidden sm:flex items-center gap-1" style={{ color: "var(--text-secondary)" }}>
                  <MapPin className="w-3 h-3" /> {d.clinic_name || "—"} · {d.city || "—"}
                </div>
                <div className="hidden sm:block"><SegmentBadge segment={d.segment} /></div>
                <div className="hidden sm:block">
                  <StatusPill kind={cadenceKind(d.cadence_status)}>{d.cadence_status}</StatusPill>
                </div>
                <div className="hidden sm:block">
                  {d.current_sentiment ? <StatusPill kind={sentimentKind(d.current_sentiment)}>{d.current_sentiment}</StatusPill> : <span className="text-xs" style={{ color: "var(--text-muted)" }}>—</span>}
                </div>
                <div className="hidden sm:block text-sm text-right" style={{ color: "var(--text-secondary)" }}>
                  {d.days_since_last_visit != null ? `${d.days_since_last_visit}d` : "—"}
                </div>
                <div className="flex justify-end">
                  {canDelete && (
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteOne(d); }}
                      disabled={busy}
                      title="Delete doctor"
                      className="p-1.5 rounded-md hover:bg-red-50 transition-colors"
                      data-testid={`delete-doctor-${d.id}`}
                    >
                      <Trash2 className="w-4 h-4" style={{ color: "var(--status-danger)" }} />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {docs.length === 0 && <div className="px-4 py-6 text-sm text-center" style={{ color: "var(--text-muted)" }}>No doctors match your filters.</div>}
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="doctors-grid">
          {docs.map((d, idx) => {
            const isSel = selected.has(d.id);
            return (
              <div
                key={d.id}
                data-testid={`doctor-card-${d.id}`}
                className="relative rounded-md border p-5 card-lift fade-up"
                style={{
                  background: "var(--bg-default)",
                  borderColor: isSel ? "var(--brand-secondary)" : "var(--border-default)",
                  animationDelay: `${idx * 25}ms`,
                  boxShadow: isSel ? "0 0 0 2px rgba(194, 109, 83, 0.25)" : undefined,
                }}
              >
                {canDelete && (
                  <div className="absolute top-3 left-3 z-10">
                    <input
                      type="checkbox"
                      checked={isSel}
                      onChange={(e) => { e.stopPropagation(); toggleOne(d.id); }}
                      className="cursor-pointer w-4 h-4"
                      aria-label={`Select ${d.doctor_name}`}
                      data-testid={`select-doctor-${d.id}`}
                    />
                  </div>
                )}
                {canDelete && (
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteOne(d); }}
                    disabled={busy}
                    title="Delete doctor"
                    className="absolute top-3 right-3 p-1.5 rounded-md hover:bg-red-50 transition-colors"
                    data-testid={`delete-doctor-${d.id}`}
                  >
                    <Trash2 className="w-4 h-4" style={{ color: "var(--status-danger)" }} />
                  </button>
                )}
                <Link to={`/doctors/${d.id}`} className="block" style={{ paddingLeft: canDelete ? 22 : 0, paddingRight: canDelete ? 24 : 0 }}>
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
              </div>
            );
          })}
          {docs.length === 0 && <div className="col-span-full text-sm" style={{ color: "var(--text-muted)" }}>No doctors match your filters.</div>}
        </div>
      )}
    </div>
  );
}
