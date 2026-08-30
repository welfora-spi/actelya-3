import { Target, FileText, CheckCircle2, Circle, MessageSquareText, CheckCircle } from "lucide-react";
import { toast } from "sonner";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Empty } from "@/components/Primitives";
import { SEAT_STATUS_META, DELIVERABLE_STATUS_META, isValidDeliverable } from "./adapter";
import SeatStatusBadge from "./SeatStatusBadge";

function initials(name) {
  if (!name) return "?";
  return name.trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
}

function HistoryDot({ state }) {
  if (state === "done") return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" strokeWidth={1.75} />;
  if (state === "active") return <Circle className="w-3.5 h-3.5 text-sky-400 shrink-0" strokeWidth={1.75} />;
  return <Circle className="w-3.5 h-3.5 text-muted-foreground/40 shrink-0" strokeWidth={1.75} />;
}

export default function CollaboratorPanel({ collaborator }) {
  if (!collaborator) {
    return (
      <div className="p-5">
        <h2 className="font-display text-lg font-medium mb-3">Collaboratore selezionato</h2>
        <Empty text="Seleziona un collaboratore in sala riunioni per vedere l'attività in corso." />
      </div>
    );
  }

  const canAct = isValidDeliverable(collaborator.document);
  const docMeta = collaborator.document && DELIVERABLE_STATUS_META[collaborator.document.status];

  const requestChange = () => {
    toast.info("Richiesta di modifica registrata (demo): non è ancora collegata alla squadra reale.");
  };
  const approve = () => {
    toast.success("Approvazione registrata (demo): non è ancora collegata al motore M2.");
  };

  return (
    <div className="p-5 flex flex-col h-full" data-testid="collaborator-panel">
      <h2 className="font-display text-lg font-medium mb-4">Collaboratore selezionato</h2>

      <div className="flex items-center gap-3 mb-5">
        <Avatar className="w-11 h-11">
          <AvatarFallback className="bg-secondary text-sm font-semibold">{initials(collaborator.name)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <div className="text-sm font-medium truncate">{collaborator.name}</div>
          <SeatStatusBadge {...SEAT_STATUS_META[collaborator.status]} testid="panel-seat-status" />
        </div>
      </div>

      {collaborator.activity && (
        <div className="mb-5">
          <div className="label-caps mb-2">Attività attuale</div>
          <div className="flex items-start gap-2.5">
            <div className="w-7 h-7 rounded-md bg-muted grid place-items-center shrink-0 mt-0.5">
              <Target className="w-3.5 h-3.5 text-muted-foreground" strokeWidth={1.75} />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-medium">{collaborator.activity.title}</div>
              <p className="text-xs text-muted-foreground mt-0.5">{collaborator.activity.detail}</p>
            </div>
          </div>
        </div>
      )}

      <div className="mb-5">
        <div className="label-caps mb-2">Documento in produzione</div>
        {collaborator.document ? (
          <div className="flex items-center gap-2.5" data-testid="panel-document">
            <div className="w-7 h-7 rounded-md bg-muted grid place-items-center shrink-0">
              <FileText className="w-3.5 h-3.5 text-muted-foreground" strokeWidth={1.75} />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-medium">{collaborator.document.title}</div>
              {docMeta && <div className="text-xs text-primary">{docMeta.label}</div>}
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">Nessun documento ancora prodotto.</p>
        )}
      </div>

      {collaborator.history?.length > 0 && (
        <div className="mb-5">
          <div className="label-caps mb-2">Cronologia attività</div>
          <ul className="space-y-2" data-testid="panel-history">
            {collaborator.history.map((h, i) => (
              <li key={i} className="flex items-center justify-between gap-3 text-xs">
                <span className="flex items-center gap-2 min-w-0">
                  <HistoryDot state={h.state} />
                  <span className={h.state === "pending" ? "text-muted-foreground" : ""}>{h.label}</span>
                </span>
                <span className="text-muted-foreground font-mono shrink-0">{h.time}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-auto pt-4 space-y-2">
        {!canAct && (
          <p className="text-[11px] text-muted-foreground text-center">
            Azioni disponibili solo quando è pronto un deliverable valido.
          </p>
        )}
        <button
          type="button"
          data-testid="panel-request-change"
          disabled={!canAct}
          onClick={requestChange}
          className="w-full flex items-center justify-center gap-2 rounded-sm border border-primary/50 text-primary px-4 py-2 text-sm font-medium hover:bg-primary/10 active:scale-[0.98] transition-colors duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <MessageSquareText className="w-4 h-4" strokeWidth={1.75} /> Chiedi una modifica
        </button>
        <button
          type="button"
          data-testid="panel-approve"
          disabled={!canAct}
          onClick={approve}
          className="w-full flex items-center justify-center gap-2 rounded-sm bg-primary text-primary-foreground px-4 py-2.5 text-sm font-medium hover:opacity-90 active:scale-[0.98] transition-colors duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <CheckCircle className="w-4 h-4" strokeWidth={1.75} /> Approva
        </button>
      </div>
    </div>
  );
}
