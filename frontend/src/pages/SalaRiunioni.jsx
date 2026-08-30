import { useEffect, useState } from "react";
import { Users2 } from "lucide-react";
import RoomShell from "@/components/meeting-room/RoomShell";
import RoomBackdrop from "@/components/meeting-room/RoomBackdrop";
import DeliverableCard from "@/components/meeting-room/DeliverableCard";
import RequestBar from "@/components/meeting-room/RequestBar";
import CollaboratorPanel from "@/components/meeting-room/CollaboratorPanel";
import { Card } from "@/components/Primitives";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMeetingRoomData } from "@/components/meeting-room/adapter";

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
  const { objective, seats, deliverables } = useMeetingRoomData();
  const [selectedId, setSelectedId] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isDesktop = useIsDesktop();

  const selectedCollaborator = seats.find((s) => s.id === selectedId) || null;

  const selectSeat = (seat) => {
    setSelectedId(seat.id);
    if (!isDesktop) setDrawerOpen(true);
  };

  const selectDeliverable = (deliverable) => {
    if (deliverable.ownerId) selectSeat({ id: deliverable.ownerId });
  };

  return (
    <RoomShell>
      <div data-testid="sala-riunioni-page">
        <div className="mb-6">
          <div className="flex items-center gap-1.5 text-xs font-medium text-primary mb-1">
            <Users2 className="w-3.5 h-3.5" strokeWidth={1.75} />
            Obiettivo attuale
          </div>
          <h1 className="font-display text-xl sm:text-2xl font-semibold tracking-tight" data-testid="meeting-objective">
            {objective}
          </h1>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6">
          <div className="min-w-0 space-y-4">
            <RoomBackdrop seats={seats} selectedId={selectedId} onSelectSeat={selectSeat} />

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3" data-testid="deliverable-strip">
              {deliverables.map((d) => (
                <DeliverableCard
                  key={d.id}
                  deliverable={d}
                  selected={selectedId === d.ownerId}
                  onSelect={selectDeliverable}
                />
              ))}
            </div>

            <RequestBar />
          </div>

          <div className="hidden lg:block">
            <Card className="sticky top-6 max-h-[calc(100vh-3rem)] overflow-y-auto">
              <CollaboratorPanel collaborator={selectedCollaborator} />
            </Card>
          </div>
        </div>
      </div>

      <Sheet open={!isDesktop && drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="right" className="w-full sm:max-w-sm p-0 overflow-y-auto">
          <SheetHeader className="sr-only">
            <SheetTitle>Collaboratore selezionato</SheetTitle>
          </SheetHeader>
          <CollaboratorPanel collaborator={selectedCollaborator} />
        </SheetContent>
      </Sheet>
    </RoomShell>
  );
}
