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
