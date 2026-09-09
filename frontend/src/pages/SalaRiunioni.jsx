import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Users2 } from "lucide-react";
import RoomShell from "@/components/meeting-room/RoomShell";
import RoomBackdrop from "@/components/meeting-room/RoomBackdrop";
import DeliverableCard from "@/components/meeting-room/DeliverableCard";
import RequestBar from "@/components/meeting-room/RequestBar";
import CollaboratorPanel from "@/components/meeting-room/CollaboratorPanel";
import { Card } from "@/components/Primitives";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMeetingRoomData, useMeetingRoomDataFromPlan, TEAM_MODES } from "@/components/meeting-room/adapter";
import { cn } from "@/lib/utils";

const EMPTY_ROOM_DATA = { objective: "", seats: [], activeAgentIds: [], deliverables: [] };

const TEAM_MODE_OPTIONS = [
  { value: TEAM_MODES.RICHIESTA, label: "Squadra richiesta" },
  { value: TEAM_MODES.COMPLETA, label: "Tutta la squadra" },
];

// Sotto i 1024px il pannello collaboratore diventa un drawer (Sheet) invece
// di una colonna fissa, come richiesto per i monitor piccoli.
function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(
    typeof window !== "undefined" ? window.matchMedia("(min-width: 1024px)").matches : true
  );
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const handler = (e) => setIsDesktop(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);
  return isDesktop;
}

export default function SalaRiunioni() {
  const [searchParams] = useSearchParams();
  const planId = searchParams.get("planId");
  const usingRealPlan = Boolean(planId);

  const [teamMode, setTeamMode] = useState(TEAM_MODES.RICHIESTA);
  const [refetchToken, setRefetchToken] = useState(0);
  const demoData = useMeetingRoomData(teamMode);
  const realPlan = useMeetingRoomDataFromPlan(planId, refetchToken);

  const { objective, seats, activeAgentIds, deliverables, planStatus, estimate, approvedCap, planMode, tasksCount } = usingRealPlan
    ? (realPlan.data || EMPTY_ROOM_DATA)
    : demoData;

  // Aggiornamento periodico dello stato reale (task in coda/al lavoro/
  // bloccato/completato ora possono avanzare da soli sul server dopo
  // l'approvazione, non solo su un refresh manuale — vedi
  // m2/engine.py::auto_dispatch_worker_loop). Si ferma su uno stato
  // conclusivo o su un errore gia' segnalato: mai un polling su un piano
  // che non tornera' piu' utilizzabile.
  useEffect(() => {
    if (!usingRealPlan || realPlan.error) return;
    if (planStatus && ["COMPLETATO", "BLOCCATO", "ANNULLATO"].includes(planStatus)) return;
    const t = setInterval(() => setRefetchToken((v) => v + 1), 3000);
    return () => clearInterval(t);
  }, [usingRealPlan, realPlan.error, planStatus]);

  const [selectedId, setSelectedId] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isDesktop = useIsDesktop();

  const selectedCollaborator = seats.find((s) => s.id === selectedId) || null;

  const changeTeamMode = (mode) => {
    setTeamMode(mode);
    setSelectedId(null);
  };

  // Riepilogo riunione (calcolato dai dati, non un testo fisso): mostrato nel
  // pannello destro quando nessun collaboratore è selezionato.
  const summary = {
    collaboratorsCount: seats.filter((s) => s.kind === "collaborator").length,
    activeCount: seats.filter((s) => s.kind === "collaborator" && s.status === "AL_LAVORO").length,
    pendingApprovalCount: deliverables.filter((d) => d.status === "IN_APPROVAZIONE").length,
    tasksCount: tasksCount ?? null,
    planStatus: usingRealPlan ? (planStatus ?? null) : null,
    estimatedCost: estimate?.cost_probable ?? null,
    // Tetto REALMENTE autorizzato dal click "Approva" (plan.approved_cap):
    // puo' differire dalla sola stima sopra (vedi adapter.js) — mostrato
    // sempre distintamente, mai sostituito dalla stima.
    approvedCap: approvedCap ?? null,
    // Stessa modalità mostrata nel dettaglio piano (lib/planMode.js) — mai
    // una seconda etichetta che puo' discordare per lo stesso piano.
    planMode: usingRealPlan ? (planMode ?? null) : null,
  };

  const selectSeat = (seat) => {
    setSelectedId(seat.id);
    if (!isDesktop) setDrawerOpen(true);
  };

  const selectDeliverable = (deliverable) => {
    if (deliverable.ownerId) selectSeat({ id: deliverable.ownerId });
  };

  return (
    <RoomShell>
      <div data-testid="sala-riunioni-page" className="lg:flex-1 lg:flex lg:flex-col lg:min-h-0">
        <div className="mb-3 shrink-0 flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-1.5 text-[11px] font-medium text-primary mb-0.5">
              <Users2 className="w-3.5 h-3.5" strokeWidth={1.75} />
              Obiettivo attuale
            </div>
            <h1 className="font-display text-base sm:text-lg font-semibold tracking-tight truncate" data-testid="meeting-objective">
              {usingRealPlan && realPlan.loading ? "Caricamento piano…" : objective}
            </h1>
          </div>

          {!usingRealPlan && (
            <div className="inline-flex items-center rounded-full border border-border/60 bg-card p-0.5 shrink-0" data-testid="team-mode-toggle">
              {TEAM_MODE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  data-testid={`team-mode-${opt.value}`}
                  onClick={() => changeTeamMode(opt.value)}
                  aria-pressed={teamMode === opt.value}
                  className={cn(
                    "px-3 py-1 text-xs font-medium rounded-full transition-colors duration-200",
                    teamMode === opt.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}
        </div>

        {usingRealPlan && realPlan.error && (
          <div data-testid="sala-riunioni-plan-error" className="mb-3 text-sm border border-red-500/30 bg-red-500/10 text-red-400 rounded-sm px-3 py-2">
            Impossibile caricare il piano richiesto. Riprova o torna ai piani.
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-3 lg:flex-1 lg:min-h-0">
          <div className="min-w-0 flex flex-col gap-3 lg:min-h-0">
            <RoomBackdrop
              activeAgentIds={activeAgentIds}
              seats={seats}
              selectedId={selectedId}
              onSelectSeat={selectSeat}
            />

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 shrink-0" data-testid="deliverable-strip">
              {deliverables.map((d) => (
                <DeliverableCard
                  key={d.id}
                  deliverable={d}
                  selected={selectedId === d.ownerId}
                  onSelect={selectDeliverable}
                />
              ))}
            </div>

            <div className="shrink-0">
              <RequestBar />
            </div>
          </div>

          <div className="hidden lg:flex lg:flex-col lg:min-h-0">
            <Card className="flex-1 min-h-0 flex flex-col overflow-hidden">
              <div className="flex-1 min-h-0 overflow-y-auto">
                <CollaboratorPanel collaborator={selectedCollaborator} summary={summary}
                  planId={usingRealPlan ? planId : null} onActionDone={() => setRefetchToken((t) => t + 1)} />
              </div>
            </Card>
          </div>
        </div>
      </div>

      <Sheet open={!isDesktop && drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="right" className="w-full sm:max-w-sm p-0 overflow-y-auto">
          <SheetHeader className="sr-only">
            <SheetTitle>Collaboratore selezionato</SheetTitle>
          </SheetHeader>
          <CollaboratorPanel collaborator={selectedCollaborator} summary={summary}
            planId={usingRealPlan ? planId : null} onActionDone={() => setRefetchToken((t) => t + 1)} />
        </SheetContent>
      </Sheet>
    </RoomShell>
  );
}
