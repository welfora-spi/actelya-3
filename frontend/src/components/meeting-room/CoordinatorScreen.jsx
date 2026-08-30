import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { SEAT_STATUS_META } from "./adapter";
import SeatStatusBadge from "./SeatStatusBadge";

// Il Coordinatore ACTELYA non è una persona seduta: è una presenza digitale
// mostrata come un riquadro ordinato nella zona dello schermo sul fondo
// sala — nessun indicatore/linea verso un corpo, nessun avatar. Stessa
// posizione (seat.label_position) in entrambe le modalità, non fa mai parte
// di activeAgentIds (sempre visibile — vedi agentRegistry.js/adapter.js).
export default function CoordinatorScreen({ seat, selected, onSelect }) {
  const statusMeta = SEAT_STATUS_META[seat.status];
  const pos = seat.label_position;

  return (
    <button
      type="button"
      data-testid={`hotspot-${seat.id}`}
      onClick={() => onSelect(seat)}
      aria-pressed={selected}
      style={{ top: pos.top, left: pos.left }}
      className={cn(
        "absolute -translate-x-1/2 -translate-y-1/2 flex items-center gap-1.5 rounded-md border px-2 py-1 backdrop-blur-sm shadow-sm whitespace-nowrap transition-colors duration-200",
        "bg-primary/15 border-primary/40 hover:bg-primary/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
        selected && "ring-2 ring-primary"
      )}
    >
      <Sparkles className="w-3 h-3 text-primary shrink-0" strokeWidth={2} />
      <span className="text-[10px] font-medium text-white leading-none">{seat.role_name}</span>
      {statusMeta && <SeatStatusBadge {...statusMeta} className="px-1.5 py-0" testid={`hotspot-status-${seat.id}`} />}
    </button>
  );
}
