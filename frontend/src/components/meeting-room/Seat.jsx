import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import { SEAT_STATUS_META } from "./adapter";
import SeatStatusBadge from "./SeatStatusBadge";

const RING_TONE_CLASSES = {
  slate: "ring-slate-500/50",
  emerald: "ring-emerald-500/60",
  amber: "ring-amber-500/60",
  blue: "ring-sky-500/60",
};

function initials(name) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return parts.slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
}

// Postazione vuota: attenuata, nessun dato, non selezionabile — principio 4
// ("le postazioni inutilizzate restano vuote e attenuate").
function EmptySeat() {
  return (
    <div className="flex flex-col items-center gap-1.5 opacity-35" data-testid="seat-empty">
      <div className="w-11 h-11 rounded-full border border-dashed border-border grid place-items-center">
        <span className="w-2 h-2 rounded-full bg-muted-foreground/50" />
      </div>
      <span className="text-[10px] text-muted-foreground">Postazione libera</span>
    </div>
  );
}

export default function Seat({ seat, selected, onSelect }) {
  if (seat.kind === "empty") return <EmptySeat />;

  const isOwner = seat.kind === "owner";
  const statusMeta = !isOwner ? SEAT_STATUS_META[seat.status] : null;
  const ringClass = statusMeta ? RING_TONE_CLASSES[statusMeta.tone] : "ring-border";

  return (
    <button
      type="button"
      data-testid={`seat-${seat.id}`}
      disabled={isOwner}
      onClick={() => !isOwner && onSelect(seat)}
      aria-pressed={selected}
      className={cn(
        "flex flex-col items-center gap-1.5 rounded-lg px-1.5 py-1 transition-colors duration-200",
        isOwner ? "cursor-default" : "hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
        selected && "bg-muted/50"
      )}
    >
      <Avatar className={cn("w-11 h-11 ring-2", ringClass, isOwner && "ring-foreground/40")}>
        <AvatarFallback className={cn("text-xs font-semibold", isOwner ? "bg-foreground/10" : "bg-secondary")}>
          {initials(seat.name)}
        </AvatarFallback>
      </Avatar>
      <div className="text-center leading-tight">
        <div className="text-[11px] font-medium max-w-[92px] truncate">{seat.name}</div>
        {isOwner ? (
          <div className="text-[10px] text-muted-foreground">{seat.role}</div>
        ) : (
          <SeatStatusBadge {...statusMeta} testid={`seat-status-${seat.id}`} />
        )}
      </div>
    </button>
  );
}
