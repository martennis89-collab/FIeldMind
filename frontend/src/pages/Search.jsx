import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { Link } from "react-router-dom";
import { Input } from "../components/ui/input";
import { StatusPill, sentimentKind } from "../components/StatusPill";
import { Search as SearchIcon, MessageSquare, Users, ClipboardList } from "lucide-react";

export default function Search() {
  const [q, setQ] = useState("");
  const [data, setData] = useState({ doctors: [], visits: [], tasks: [] });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (q.trim().length < 2) { setData({ doctors: [], visits: [], tasks: [] }); return; }
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const { data } = await api.get("/search", { params: { q } });
        setData(data);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div data-testid="search-page">
      <div className="mb-6">
        <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>Field memory</div>
        <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
          Search <span className="font-medium">conversations.</span>
        </h1>
      </div>

      <div className="relative mb-6">
        <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: "var(--text-muted)" }} />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Try 'extraction', 'price', 'P2P', 'certification', 'overdue', a doctor name…"
          className="pl-9 h-12 text-base"
          data-testid="search-input"
        />
      </div>

      {loading && <div className="text-sm" style={{ color: "var(--text-muted)" }}>Searching…</div>}

      {q.trim().length >= 2 && !loading && (
        <div className="space-y-8">
          <Section title="Doctors" icon={Users} count={data.doctors.length}>
            {data.doctors.map((d) => (
              <Link key={d.id} to={`/doctors/${d.id}`} data-testid={`search-doctor-${d.id}`} className="block rounded-md border p-4 card-lift" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}>
                <div className="font-medium" style={{ color: "var(--brand-primary)" }}>{d.doctor_name}</div>
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>{d.clinic_name} · {d.city} · {d.segment}</div>
              </Link>
            ))}
          </Section>

          <Section title="Visit notes" icon={MessageSquare} count={data.visits.length}>
            {data.visits.map((v) => (
              <Link key={v.id} to={`/doctors/${v.doctor_id}`} className="block rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={`search-visit-${v.id}`}>
                <div className="flex items-center justify-between text-xs mb-1" style={{ color: "var(--text-muted)" }}>
                  <span>{new Date(v.visit_date).toLocaleDateString()} · {v.visit_type}</span>
                  {v.sentiment && <StatusPill kind={sentimentKind(v.sentiment)}>{v.sentiment}</StatusPill>}
                </div>
                <div className="line-clamp-2 text-sm" style={{ color: "var(--text-primary)" }}>{v.free_text_note}</div>
                {(v.confirmed_topics?.length > 0 || v.confirmed_barriers?.length > 0) && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {v.confirmed_topics?.slice(0, 4).map((t) => <span key={t} className="pill pill-info">{t}</span>)}
                    {v.confirmed_barriers?.slice(0, 4).map((b) => <span key={b} className="pill pill-warning">{b}</span>)}
                  </div>
                )}
              </Link>
            ))}
          </Section>

          <Section title="Promises" icon={ClipboardList} count={data.tasks.length}>
            {data.tasks.map((t) => (
              <Link key={t.id} to={`/doctors/${t.doctor_id}`} className="block rounded-md border p-4" style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }} data-testid={`search-task-${t.id}`}>
                <div className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>{t.task_title}</div>
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>Due {t.due_date} · {t.priority} · {t.status}</div>
              </Link>
            ))}
          </Section>

          {data.doctors.length + data.visits.length + data.tasks.length === 0 && (
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>No results.</div>
          )}
        </div>
      )}

      {q.trim().length < 2 && (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>Type at least 2 characters to search across doctors, visit notes, and promises.</div>
      )}
    </div>
  );
}

function Section({ title, icon: Icon, count, children }) {
  if (count === 0) return null;
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-4 h-4" style={{ color: "var(--text-secondary)" }} />
        <h3 className="font-display text-lg font-medium" style={{ color: "var(--brand-primary)" }}>{title}</h3>
        <span className="pill pill-muted">{count}</span>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}
