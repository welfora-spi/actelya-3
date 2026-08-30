import { MonitorSpeaker } from "lucide-react";
import Seat from "./Seat";

// Composizione della sala: illustrazione CSS statica (nessuna foto, nessuna
// animazione 3D — principio 6), predisposta per una futura fotografia reale
// tramite la prop `photoUrl` (oggi assente: il contenitore mostra solo lo
// sfondo/tavolo disegnati). Quando una foto sarà disponibile basterà
// valorizzare `photoUrl`: il markup dei seggi resta invariato, sovrapposto.
export default function RoomBackdrop({ seats, selectedId, onSelectSeat, photoUrl }) {
  const owner = seats.find((s) => s.kind === "owner");
  const coordinator = seats.find((s) => s.side === "far");
  const leftSeats = seats.filter((s) => s.side === "left");
  const rightSeats = seats.filter((s) => s.side === "right");

  return (
    <div
      data-testid="room-backdrop"
      className="relative rounded-xl border border-border/60 overflow-hidden bg-gradient-to-b from-[#141a24] via-[#10151d] to-[#0b0f15] px-4 py-6 sm:px-8 sm:py-8"
      style={photoUrl ? { backgroundImage: `url(${photoUrl})`, backgroundSize: "cover", backgroundPosition: "center" } : undefined}
    >
      {/* "Schermo" di fondo sala — elemento reale, non testo incorporato in un'immagine */}
      <div className="mx-auto mb-6 max-w-xs rounded-md border border-border/50 bg-black/40 px-4 py-3 text-center">
        <div className="flex items-center justify-center gap-1.5 text-foreground/90">
          <MonitorSpeaker className="w-3.5 h-3.5" strokeWidth={1.75} />
          <span className="font-display text-xs font-semibold tracking-tight">ACTELYA 3</span>
        </div>
        <div className="text-[10px] text-muted-foreground mt-0.5">Il tuo team di esperti al lavoro</div>
      </div>

      {/* Coordinatore — "sul fondo" della sala (principio 3) */}
      <div className="flex justify-center mb-6">
        <Seat seat={coordinator} selected={selectedId === coordinator.id} onSelect={onSelectSeat} />
      </div>

      {/* Tavolo rettangolare con angoli arrotondati + collaboratori sui lati (principio 2) */}
      <div className="flex flex-col md:flex-row items-center md:items-stretch justify-center gap-4 md:gap-6">
        <div className="flex md:flex-col items-center justify-center gap-4 md:gap-6 md:py-6">
          {leftSeats.map((s) => (
            <Seat key={s.id} seat={s} selected={selectedId === s.id} onSelect={onSelectSeat} />
          ))}
        </div>

        <div
          data-testid="meeting-table"
          className="w-full max-w-md md:max-w-none md:w-40 h-16 md:h-auto md:min-h-[220px] rounded-2xl bg-gradient-to-br from-[#6b4a30] via-[#5a3c26] to-[#432c1a] border border-black/30 shadow-inner"
        />

        <div className="flex md:flex-col items-center justify-center gap-4 md:gap-6 md:py-6">
          {rightSeats.map((s) => (
            <Seat key={s.id} seat={s} selected={selectedId === s.id} onSelect={onSelectSeat} />
          ))}
        </div>
      </div>

      {/* Imprenditore — a capotavola, vicino a chi guarda (principio 1) */}
      <div className="flex justify-center mt-6">
        <Seat seat={owner} selected={false} onSelect={onSelectSeat} />
      </div>
    </div>
  );
}
