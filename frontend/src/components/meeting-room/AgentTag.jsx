import { cn } from "@/lib/utils";
import { SEAT_STATUS_META } from "./adapter";

// Componente UNICO per le targhette dei 9 collaboratori (sostituisce i
// precedenti Hotspot.jsx/HotspotDot.jsx separati per modalità): con foto e
// posizioni ormai identiche in "Squadra richiesta" e "Tutta la squadra",
// non serve più uno stile diverso per modalità — solo activeAgentIds
// decide se una targhetta compare o no (vedi RoomBackdrop.jsx).
//
// Sempre visibile (mai tooltip), ancorata a agent.label_position: nome breve
// bianco puro (#FFFFFF, esplicito, mai ereditato), piccolo pallino di stato,
// bordo colorato per stato. Al clic: stessa posizione e dimensione, solo il
// bordo diventa più spesso.
const DOT_TONE = {
  slate: "bg-slate-400",
  emerald: "bg-emerald-400",
  amber: "bg-amber-400",
  blue: "bg-sky-400",
};

const BORDER_TONE_DEFAULT = {
  slate: "border-slate-400/60",
  emerald: "border-emerald-400/60",
  amber: "border-amber-400/60",
  blue: "border-sky-400/60",
};

const BORDER_TONE_SELECTED = {
  slate: "border-slate-300",
  emerald: "border-emerald-300",
  amber: "border-amber-300",
  blue: "border-sky-300",
};

export default function AgentTag({ agent, status, selected, onSelect }) {
  const statusMeta = SEAT_STATUS_META[status] || SEAT_STATUS_META.CONVOCATO;
  const tone = statusMeta.tone;
  const pos = agent.label_position;

  return (
    <button
      type="button"
      data-testid={`agent-tag-${agent.agent_id}`}
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`${agent.role_name} — ${statusMeta.label}`}
      style={{
        top: pos.top,
        left: pos.left,
        zIndex: (agent.z_index || 0) + 100,
        backgroundColor: selected ? "rgba(0,0,0,0.94)" : "rgba(0,0,0,0.9)",
      }}
      className={cn(
        "absolute -translate-x-1/2 -translate-y-1/2 flex items-center gap-1.5 rounded-md px-1.5 py-0.5 whitespace-nowrap transition-all duration-150",
        selected ? cn("border-2", BORDER_TONE_SELECTED[tone]) : cn("border", BORDER_TONE_DEFAULT[tone])
      )}
    >
      <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", DOT_TONE[tone])} />
      <span style={{ color: "#FFFFFF", opacity: 1 }} className="text-[10px] font-medium leading-none">
        {agent.short_label}
      </span>
    </button>
  );
}
