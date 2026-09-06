import { useState } from "react";
import { Link } from "react-router-dom";
import { Target, FileText, CheckCircle2, Circle, MessageSquareText, CheckCircle, Users, Activity, Clock3, ListChecks, Coins, PlayCircle, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { SEAT_STATUS_META, DELIVERABLE_STATUS_META, isValidDeliverable } from "./adapter";
import SeatStatusBadge from "./SeatStatusBadge";
import MultimodalProjectPanel from "@/components/MultimodalProjectPanel";

function initials(name) {
  if (!name) return "?";
  return name.trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
}

function SummaryRow({ icon: Icon, label, value, tone = "" }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-md border border-border/60 px-3 py-2">
      <span className="flex items-center gap-2 text-xs text-muted-foreground min-w-0">
        <Icon className="w-3.5 h-3.5 shrink-0" strokeWidth={1.75} />
        <span className="truncate">{label}</span>
      </span>
      <span className={`font-display text-base font-semibold shrink-0 ${tone}`}>{value}</span>
    </div>
  );
}

function HistoryDot({ state }) {
  if (state === "done") return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" strokeWidth={1.75} />;
  if (state === "active") return <Circle className="w-3.5 h-3.5 text-sky-400 shrink-0" strokeWidth={1.75} />;
  return <Circle className="w-3.5 h-3.5 text-muted-foreground/40 shrink-0" strokeWidth={1.75} />;
}

// planId presente => collaboratore di un piano REALE (Sala Riunioni via
// ?planId=): le azioni parlano davvero con M2 (approvazione/rifiuto TASK,
// unica azione che M2 espone prima dell'esecuzione), mai un toast demo.
// Senza planId (modalita' demo locale) le azioni restano simulate.
export default function CollaboratorPanel({ collaborator, summary, planId, onActionDone }) {
  const [busy, setBusy] = useState(false);
  const { hasRole } = useAuth();

  // Item #7 (DECISIONE UFFICIALE): l'utente normale non deve dover aprire
  // "Piani M2" per avviare il lavoro — il piano si approva (tutti i task in
  // un colpo solo, POST /m2/plans/:id/approve, stessa azione di
  // PlanDetail.jsx::approvePlan) direttamente da qui. Visibile solo quando
  // esiste davvero un piano REALE non ancora approvato e il ruolo lo
  // consente (APPROVATORE/ADMIN, stesso gate di PlanDetail.jsx): un
  // OPERATORE vede lo stato ma non il pulsante, mai un 403 silenzioso.
  const canApprovePlan = hasRole("APPROVATORE", "ADMIN");
  const planPendingApproval = Boolean(planId) && summary?.planStatus === "IN_ATTESA_APPROVAZIONE";

  const approvePlan = async () => {
    setBusy(true);
    try {
      await api.post(`/m2/plans/${planId}/approve`);
      toast.success("Piano approvato: il lavoro è avviato.");
      onActionDone?.();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  if (!collaborator) {
    return (
      <div className="p-4" data-testid="collaborator-panel-empty">
        <h2 className="font-display text-base font-medium mb-1">Collaboratore selezionato</h2>
        <p className="text-xs text-muted-foreground mb-4">Seleziona un collaboratore in sala riunioni per vedere l'attività in corso.</p>
        {summary && (
          <div className="space-y-2" data-testid="meeting-summary">
            <div className="label-caps mb-1">Riepilogo riunione</div>
            <SummaryRow icon={Users} label="Collaboratori convocati" value={summary.collaboratorsCount} />
            {summary.tasksCount != null && (
              <SummaryRow icon={ListChecks} label="Attività pianificate" value={summary.tasksCount} />
            )}
            <SummaryRow icon={Activity} label="Attività al lavoro" value={summary.activeCount} tone="text-emerald-400" />
            <SummaryRow icon={Clock3} label="Deliverable in approvazione" value={summary.pendingApprovalCount} tone="text-amber-400" />
            {summary.estimatedCost != null && (
              <SummaryRow icon={Coins} label="Costo stimato" value={`$${summary.estimatedCost.toFixed(5)}`} />
            )}
          </div>
        )}
        {planPendingApproval && (
          <div className="mt-4 pt-4 border-t border-border/60">
            {canApprovePlan ? (
              <button
                type="button"
                data-testid="approve-and-start-plan"
                disabled={busy}
                onClick={approvePlan}
                className="w-full flex items-center justify-center gap-2 rounded-sm bg-primary text-primary-foreground px-4 py-2.5 text-sm font-medium hover:opacity-90 active:scale-[0.98] transition-colors duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <PlayCircle className="w-4 h-4" strokeWidth={1.75} /> Approva e avvia il lavoro
              </button>
            ) : (
              <p className="text-[11px] text-muted-foreground text-center">
                Il piano è in attesa di approvazione da un responsabile (ruolo Approvatore/Admin).
              </p>
            )}
          </div>
        )}
      </div>
    );
  }

  const isReal = Boolean(planId);
  const multimodalKind = collaborator.document?.projectKind || null; // "reel" | "flyer" | null
  const canApproveTask = isReal && collaborator.taskId && collaborator.taskStatus === "IN_ATTESA_APPROVAZIONE";
  const canAct = isReal ? canApproveTask : isValidDeliverable(collaborator.document);
  const docMeta = collaborator.document && DELIVERABLE_STATUS_META[collaborator.document.status];

  const requestChange = async () => {
    if (!isReal) { toast.info("Richiesta di modifica registrata (demo): non è ancora collegata alla squadra reale."); return; }
    const reason = window.prompt("Motivazione del rifiuto (obbligatoria):");
    if (!reason || !reason.trim()) return;
    setBusy(true);
    try {
      await api.post(`/m2/plans/${planId}/tasks/${collaborator.taskId}/reject`, { reason: reason.trim() });
      toast.success("Task rifiutato: i dipendenti verranno saltati, il resto del piano prosegue.");
      onActionDone?.();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const approve = async () => {
    if (!isReal) { toast.success("Approvazione registrata (demo): non è ancora collegata al motore M2."); return; }
    setBusy(true);
    try {
      await api.post(`/m2/plans/${planId}/tasks/${collaborator.taskId}/approve`);
      toast.success("Task approvato: entrerà in coda per l'elaborazione.");
      onActionDone?.();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div className="p-4 flex flex-col h-full" data-testid="collaborator-panel">
      <h2 className="font-display text-base font-medium mb-4">Collaboratore selezionato</h2>

      <div className="flex items-center gap-3 mb-5">
        <Avatar className="w-11 h-11">
          <AvatarFallback className="bg-secondary text-sm font-semibold">{initials(collaborator.role_name)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <div className="text-sm font-medium truncate">{collaborator.role_name}</div>
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
        {collaborator.document?.labPath ? (
          <Link to={collaborator.document.labIdParam && collaborator.document.labId
              ? `${collaborator.document.labPath}?${collaborator.document.labIdParam}=${collaborator.document.labId}`
              : collaborator.document.labPath}
            data-testid="panel-lab-link"
            className="flex items-center gap-2.5 rounded-md border border-primary/40 px-3 py-2 text-sm text-primary hover:bg-primary/10 transition-colors duration-200">
            <ExternalLink className="w-4 h-4 shrink-0" strokeWidth={1.75} />
            Vai al laboratorio {collaborator.document.labLabel}
          </Link>
        ) : multimodalKind && collaborator.document?.projectId ? (
          <MultimodalProjectPanel kind={multimodalKind} projectId={collaborator.document.projectId} compact />
        ) : collaborator.document ? (
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
        {isReal && !canApproveTask && !multimodalKind && (
          <p className="text-[11px] text-muted-foreground text-center">
            {collaborator.taskStatus ? "Nessuna approvazione in attesa per questo task." : "Azioni disponibili solo quando è pronto un deliverable valido."}
          </p>
        )}
        {!isReal && !canAct && (
          <p className="text-[11px] text-muted-foreground text-center">
            Azioni disponibili solo quando è pronto un deliverable valido.
          </p>
        )}
        {multimodalKind && canApproveTask && (
          <button
            type="button"
            onClick={approve}
            disabled={busy}
            className="w-full flex items-center justify-center gap-2 rounded-sm border border-primary/50 text-primary px-4 py-2 text-sm font-medium hover:bg-primary/10 transition-colors duration-200"
          >
            <CheckCircle className="w-4 h-4" strokeWidth={1.75} /> Approva l'avvio del task nel piano
          </button>
        )}
        {!multimodalKind && (
          <>
            <button
              type="button"
              data-testid="panel-request-change"
              disabled={!canAct || busy}
              onClick={requestChange}
              className="w-full flex items-center justify-center gap-2 rounded-sm border border-primary/50 text-primary px-4 py-2 text-sm font-medium hover:bg-primary/10 active:scale-[0.98] transition-colors duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <MessageSquareText className="w-4 h-4" strokeWidth={1.75} /> {isReal ? "Rifiuta" : "Chiedi una modifica"}
            </button>
            <button
              type="button"
              data-testid="panel-approve"
              disabled={!canAct || busy}
              onClick={approve}
              className="w-full flex items-center justify-center gap-2 rounded-sm bg-primary text-primary-foreground px-4 py-2.5 text-sm font-medium hover:opacity-90 active:scale-[0.98] transition-colors duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <CheckCircle className="w-4 h-4" strokeWidth={1.75} /> {isReal ? "Approva l'avvio" : "Approva"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
