import { cn } from "@/lib/utils";

const MAP = {
  // execution_status
  IN_CODA: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  IN_ESECUZIONE: "bg-blue-500/15 text-blue-400 border-blue-500/30 animate-pulse",
  COMPLETATA: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  FALLITA: "bg-red-500/15 text-red-400 border-red-500/30",
  ARRESTATA: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  // deliverable_status
  COMPLETATO: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  COMPLETATO_CON_AVVISI: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  BLOCCATO: "bg-red-500/15 text-red-400 border-red-500/30",
  // action_status
  NON_RICHIESTA: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  IN_ATTESA_APPROVAZIONE: "bg-violet-500/15 text-violet-400 border-violet-500/30",
  AUTORIZZATA: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  BLOCCATA: "bg-red-500/15 text-red-400 border-red-500/30",
  ESEGUITA: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  // integration/api status
  NON_CONFIGURATA: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  CONFIGURATA: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  VERIFICATA: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  // stessi stati, forma maschile (Professional Tool Registry, domains/appointments)
  NON_CONFIGURATO: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  CONFIGURATO: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  VERIFICATO: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  ERRORE: "bg-red-500/15 text-red-400 border-red-500/30",
  DISATTIVATA: "bg-slate-600/15 text-slate-500 border-slate-600/30 line-through",
  // approval
  APPROVATA: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  RIFIUTATA: "bg-red-500/15 text-red-400 border-red-500/30",
  PRODUZIONE: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  AZIONE_ESTERNA: "bg-red-500/15 text-red-400 border-red-500/30",
  MISTO: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  AMBIGUO: "bg-violet-500/15 text-violet-400 border-violet-500/30",
  // M2 task_status
  PIANIFICATA: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  SALTATA: "bg-zinc-600/15 text-zinc-400 border-zinc-600/30 line-through",
  // M2 plan_status
  BOZZA: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  APPROVATO: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  APPROVATO_PARZIALE: "bg-teal-500/15 text-teal-400 border-teal-500/30",
  ANNULLATO: "bg-zinc-600/15 text-zinc-400 border-zinc-600/30 line-through",
  // review severity
  info: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  warning: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  high: "bg-red-500/15 text-red-400 border-red-500/30",
  // reel (agente marketing, Requesty reale + video Runway reale)
  GENERAZIONE_IN_CORSO: "bg-blue-500/15 text-blue-400 border-blue-500/30 animate-pulse",
  PROGETTO_PRONTO: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  ESITO_INCERTO: "bg-red-500/15 text-red-400 border-red-500/30 animate-pulse",
  IN_GENERAZIONE: "bg-blue-500/15 text-blue-400 border-blue-500/30 animate-pulse",
  VIDEO_PRONTO: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  FALLITO: "bg-red-500/15 text-red-400 border-red-500/30",
  NON_RICHIESTO: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  NON_VERIFICATO: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  CONTESTATO: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  OK: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  // brain: esito di POST /brain/plans
  READY: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  NEEDS_CLARIFICATION: "bg-violet-500/15 text-violet-400 border-violet-500/30",
  UNSUPPORTED: "bg-zinc-600/15 text-zinc-400 border-zinc-600/30",
  BLOCKED_RISK: "bg-red-500/15 text-red-400 border-red-500/30",
  // Social Media Manager: domains/social_publishing.py (PublishingPackage)
  AWAITING_APPROVAL: "bg-violet-500/15 text-violet-400 border-violet-500/30",
  APPROVED: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  SCHEDULED: "bg-teal-500/15 text-teal-400 border-teal-500/30",
  PUBLISHING: "bg-blue-500/15 text-blue-400 border-blue-500/30 animate-pulse",
  PUBLISHED: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  CANCELLED: "bg-zinc-600/15 text-zinc-400 border-zinc-600/30 line-through",
  FAILED: "bg-red-500/15 text-red-400 border-red-500/30",
  // Lead Generation Specialist: domains/leadgen (file/job/qualificazione/compliance)
  VALIDATO: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  RIFIUTATO: "bg-red-500/15 text-red-400 border-red-500/30",
  UPLOADED: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  PARSING: "bg-blue-500/15 text-blue-400 border-blue-500/30 animate-pulse",
  NORMALIZED: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  SCORING: "bg-blue-500/15 text-blue-400 border-blue-500/30 animate-pulse",
  REVIEW_REQUIRED: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  READY_FOR_APPROVAL: "bg-teal-500/15 text-teal-400 border-teal-500/30",
  ESPORTATA: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  IN_LAVORAZIONE: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  PARTIAL: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  QUALIFIED: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  INCOMPLETE: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  EXCLUDED: "bg-zinc-600/15 text-zinc-400 border-zinc-600/30",
  DO_NOT_CONTACT: "bg-red-500/15 text-red-400 border-red-500/30",
  APPROVAL_REQUIRED: "bg-violet-500/15 text-violet-400 border-violet-500/30",
  // Content Creator: domains/content_creator (content_items)
  IN_ATTESA_ASSET: "bg-teal-500/15 text-teal-400 border-teal-500/30 animate-pulse",
  // Sales Agent: domains/sales (sales_opportunities, pipeline stages)
  NUOVO: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  IN_ANALISI: "bg-blue-500/15 text-blue-400 border-blue-500/30 animate-pulse",
  QUALIFICATO: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  CONTATTATO: "bg-teal-500/15 text-teal-400 border-teal-500/30",
  IN_RELAZIONE: "bg-teal-500/15 text-teal-400 border-teal-500/30",
  FOLLOW_UP: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  RICHIESTA_APPUNTAMENTO: "bg-violet-500/15 text-violet-400 border-violet-500/30",
  APPUNTAMENTO_FISSATO: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  OPPORTUNITA: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  PROPOSTA: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  NEGOZIAZIONE: "bg-emerald-600/15 text-emerald-400 border-emerald-600/30",
  VINTO: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40 font-bold",
  PERSO: "bg-zinc-600/15 text-zinc-400 border-zinc-600/30 line-through",
};

export function StatusBadge({ status, className, testid }) {
  if (!status) return <span className="text-muted-foreground text-xs font-mono">—</span>;
  return (
    <span
      data-testid={testid}
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-[10px] font-mono font-medium tracking-wide whitespace-nowrap",
        MAP[status] || "bg-muted text-muted-foreground border-border",
        className
      )}
    >
      {status}
    </span>
  );
}
