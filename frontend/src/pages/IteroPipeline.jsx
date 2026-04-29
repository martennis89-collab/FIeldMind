import React, { useEffect, useMemo, useState } from "react";
import api from "../lib/api";
import { Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { ChevronRight, ScanLine, MapPin, RefreshCw, Trophy, XCircle } from "lucide-react";
import { toast } from "sonner";

const STAGES = [
  "None",
  "Demo Discussed",
  "Demo Booked",
  "Demo Completed",
  "Proposal Sent",
  "Contract Sent",
  "Contract Signed",
  "Lost",
];

const STAGE_COLOR = {
  None: "#7CA1B4",
  "Demo Discussed": "#7CA1B4",
  "Demo Booked": "#5C8AA4",
  "Demo Completed": "#4A7B95",
  "Proposal Sent": "#C26D53",
  "Contract Sent": "#A8542F",
  "Contract Signed": "#3F7D58",
  Lost: "#9C9388",
};

function nextStageOf(s) {
  const i = STAGES.indexOf(s);
  if (i < 0 || i >= STAGES.length - 2) return null; // skip Lost auto-next
  return STAGES[i + 1] === "Lost" ? null : STAGES[i + 1];
}

export default function IteroPipeline() {
  const { user } = useAuth();
  const [data, setData] = useState({ stages: STAGES, groups: {}, counts: {}, total: 0 });
  const [loading, setLoading] = useState(true);
  const [stageDialog, setStageDialog] = useState(null); // { card, currentStage, targetStage, note }

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/itero/pipeline");
      setData(data);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const openMove = (card, target = null) => {
    setStageDialog({
      card,
      currentStage: card.stage,
      targetStage: target || nextStageOf(card.stage) || "Contract Signed",
      note: "",
    });
  };

  const submitStage = async () => {
    if (!stageDialog) return;
    try {
      await api.post(`/doctors/${stageDialog.card.id}/itero-stage`, {
        stage: stageDialog.targetStage,
        note: stageDialog.note || null,
      });
      toast.success(`${stageDialog.card.doctor_name} → ${stageDialog.targetStage}`);
      setStageDialog(null);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed");
    }
  };

  const visibleStages = useMemo(() => STAGES.filter((s) => s !== "None" || (data.counts?.None || 0) > 0), [data.counts]);

  const isManager = user?.role === "Manager";

  return (
    <div data-testid="itero-pipeline-page">
      <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
        <div>
          <div className="text-xs uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>iTero</div>
          <h1 className="font-display text-3xl sm:text-4xl font-light tracking-tight" style={{ color: "var(--brand-primary)" }}>
            Pipeline <span className="font-medium">({data.total || 0})</span>
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            {isManager ? "Team-wide deal flow." : "Move doctors through demo → proposal → contract."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={load} data-testid="pipeline-refresh">
            <RefreshCw className="w-4 h-4 mr-1" /> Refresh
          </Button>
          <Link to="/itero">
            <Button variant="outline" style={{ borderColor: "var(--brand-primary)", color: "var(--brand-primary)" }}>
              <ScanLine className="w-4 h-4 mr-1" /> Funnel view
            </Button>
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : (
        <div
          className="flex gap-3 overflow-x-auto pb-3 scrollbar-thin"
          data-testid="pipeline-columns"
          style={{ scrollSnapType: "x mandatory" }}
        >
          {visibleStages.map((s) => {
            const cards = data.groups?.[s] || [];
            const accent = STAGE_COLOR[s] || "var(--brand-primary)";
            return (
              <div
                key={s}
                data-testid={`pipeline-col-${s.replace(/\s+/g, "-").toLowerCase()}`}
                className="shrink-0 w-72 sm:w-80 rounded-md border flex flex-col"
                style={{ background: "var(--bg-paper)", borderColor: "var(--border-default)", borderTop: `3px solid ${accent}`, scrollSnapAlign: "start", maxHeight: "calc(100vh - 220px)" }}
              >
                <div className="px-3 py-2 flex items-center justify-between border-b" style={{ borderColor: "var(--border-default)" }}>
                  <div>
                    <div className="text-xs uppercase tracking-widest font-semibold" style={{ color: accent }}>{s}</div>
                    <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>{cards.length} doctor{cards.length !== 1 ? "s" : ""}</div>
                  </div>
                  {s === "Contract Signed" && <Trophy className="w-4 h-4" style={{ color: "var(--status-success)" }} />}
                  {s === "Lost" && <XCircle className="w-4 h-4" style={{ color: "var(--text-muted)" }} />}
                </div>
                <div className="flex-1 overflow-y-auto p-2 space-y-2">
                  {cards.length === 0 ? (
                    <div className="text-xs italic px-2 py-3" style={{ color: "var(--text-muted)" }}>No doctors here.</div>
                  ) : (
                    cards.map((c) => (
                      <div
                        key={c.id}
                        data-testid={`pipeline-card-${c.id}`}
                        className="rounded-md border p-3 fade-up"
                        style={{ background: "var(--bg-default)", borderColor: "var(--border-default)" }}
                      >
                        <div className="flex items-start justify-between gap-2 mb-1">
                          <Link to={`/doctors/${c.id}`} className="font-medium text-sm hover:underline truncate" style={{ color: "var(--brand-primary)" }} data-testid={`pipeline-card-link-${c.id}`}>
                            {c.doctor_name}
                          </Link>
                          {c.segment && <span className="pill pill-info text-[10px]">{c.segment}</span>}
                        </div>
                        <div className="text-xs flex items-center gap-1 mb-2 truncate" style={{ color: "var(--text-secondary)" }}>
                          <MapPin className="w-3 h-3 shrink-0" /> {[c.clinic_name, c.city].filter(Boolean).join(" · ") || "—"}
                        </div>
                        <div className="flex items-center justify-between text-[11px]" style={{ color: "var(--text-muted)" }}>
                          <span>{c.tm_name ? `TM: ${c.tm_name}` : ""}</span>
                          <span>{c.days_since_last_visit != null ? `${c.days_since_last_visit}d since visit` : "no visits"}</span>
                        </div>
                        <div className="mt-2 flex gap-1">
                          <Button
                            size="sm"
                            variant="outline"
                            className="flex-1 h-8"
                            onClick={() => openMove(c)}
                            data-testid={`pipeline-move-${c.id}`}
                          >
                            {nextStageOf(c.stage) ? (<><ChevronRight className="w-3 h-3 mr-1" /> Move forward</>) : "Change stage"}
                          </Button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Dialog open={!!stageDialog} onOpenChange={(o) => !o && setStageDialog(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Move {stageDialog?.card?.doctor_name}</DialogTitle></DialogHeader>
          {stageDialog && (
            <div className="space-y-4">
              <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
                Current stage: <strong>{stageDialog.currentStage}</strong>
              </div>
              <div>
                <div className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>Move to</div>
                <Select
                  value={stageDialog.targetStage}
                  onValueChange={(v) => setStageDialog({ ...stageDialog, targetStage: v })}
                >
                  <SelectTrigger data-testid="stage-target-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {STAGES.filter((s) => s !== "None").map((s) => (
                      <SelectItem key={s} value={s}>{s}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <div className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>Note (optional)</div>
                <Textarea
                  rows={3}
                  value={stageDialog.note}
                  onChange={(e) => setStageDialog({ ...stageDialog, note: e.target.value })}
                  placeholder={
                    stageDialog.targetStage === "Lost" ? "Why was this lost?" :
                    stageDialog.targetStage === "Contract Signed" ? "Any handover notes?" :
                    "Optional note for the stage history…"
                  }
                  data-testid="stage-note-input"
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setStageDialog(null)}>Cancel</Button>
            <Button
              onClick={submitStage}
              data-testid="stage-submit-btn"
              style={{
                background: stageDialog?.targetStage === "Lost" ? "var(--text-muted)" : "var(--brand-secondary)",
                color: "white",
              }}
            >
              Move to {stageDialog?.targetStage}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
