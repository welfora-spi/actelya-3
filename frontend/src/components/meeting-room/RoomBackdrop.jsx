import { Fragment } from "react";
import { ImageOff } from "lucide-react";
import { AGENT_REGISTRY } from "./agentRegistry";
import PersonLayer from "./PersonLayer";
import AgentTag from "./AgentTag";
import CoordinatorScreen from "./CoordinatorScreen";

// Quando l'immagine reale esiste, sostituire con:
//   import ROOM_BASE_PHOTO from "@/assets/meeting-room/layers/meeting-room-base-empty.webp";
const ROOM_BASE_PHOTO = null;

// Sfondo della sala — architettura a LIVELLI (non più due fotografie
// diverse per modalità):
//   1. livello base: fotografia fissa (sala, tavolo, tutte le sedie/
//      postazioni vuote, imprenditore a capotavola) — sempre la stessa,
//      qualunque sia activeAgentIds.
//   2. livelli collaboratore: per ciascuna voce di AGENT_REGISTRY il cui
//      agent_id è in activeAgentIds, un PersonLayer (ritaglio trasparente a
//      piena tela) + una AgentTag, entrambi ancorati alle coordinate del
//      registry. Un ruolo non attivo non viene renderizzato affatto: tavolo,
//      sedie e collaboratori non si spostano mai.
//   3. Coordinatore ACTELYA: presenza digitale separata, sempre visibile,
//      non fa mai parte di activeAgentIds.
// Tutto vive dentro lo stesso stage 16:9 (fotografia e overlay condividono
// il sistema di coordinate, si ritagliano/scalano insieme a qualunque
// dimensione della finestra).
export default function RoomBackdrop({ activeAgentIds, seats, selectedId, onSelectSeat }) {
  const coordinator = seats.find((s) => s.kind === "coordinator");
  const activeSet = new Set(activeAgentIds || []);
  const seatByAgentId = Object.fromEntries(
    seats.filter((s) => s.kind === "collaborator").map((s) => [s.agent_id, s])
  );

  return (
    <div
      data-testid="room-backdrop"
      className="relative w-full h-[38vh] lg:h-auto lg:flex-1 min-h-0 rounded-xl border border-border/60 overflow-hidden bg-[#0b0f15]"
    >
      <div
        data-testid="room-stage"
        className="absolute w-full aspect-video top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2"
      >
        {ROOM_BASE_PHOTO ? (
          <img
            src={ROOM_BASE_PHOTO}
            alt="Sala riunioni ACTELYA 3"
            className="absolute inset-0 w-full h-full object-cover"
          />
        ) : (
          <div
            className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-muted-foreground bg-[#11161f]"
            data-testid="room-backdrop-missing"
          >
            <ImageOff className="w-6 h-6" strokeWidth={1.5} />
            <p className="text-xs text-center max-w-xs">
              Sfondo della sala non disponibile in questo momento.
            </p>
          </div>
        )}

        {/* Overlay molto leggero: solo per la leggibilità delle targhette */}
        <div className="absolute inset-0 bg-black/15 pointer-events-none" />

        {AGENT_REGISTRY.map((agent) => {
          if (!activeSet.has(agent.agent_id)) return null;
          const seat = seatByAgentId[agent.agent_id];
          return (
            <Fragment key={agent.agent_id}>
              <PersonLayer agent={agent} />
              <AgentTag
                agent={agent}
                status={seat?.status}
                selected={selectedId === agent.agent_id}
                onSelect={() => seat && onSelectSeat(seat)}
              />
            </Fragment>
          );
        })}

        {/* Coordinatore ACTELYA: presenza digitale sullo schermo, non una persona seduta */}
        {coordinator && (
          <CoordinatorScreen seat={coordinator} selected={selectedId === coordinator.id} onSelect={onSelectSeat} />
        )}
      </div>
    </div>
  );
}
