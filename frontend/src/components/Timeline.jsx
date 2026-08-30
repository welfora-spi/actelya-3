import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import { Factory, ShieldCheck, Send } from "lucide-react";

export function Timeline({ execution }) {
  if (!execution) return null;
  const prodDone = ["COMPLETATA", "FALLITA", "ARRESTATA"].includes(execution.execution_status);
  const sections = [
    {
      key: "prod", title: "1. Produzione", icon: Factory,
      active: true, done: prodDone,
      body: (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="label-caps">Pipeline</span>
          <StatusBadge status={execution.execution_status} testid="tl-execution-status" />
        </div>
      ),
    },
    {
      key: "valid", title: "2. Validazione e approvazione", icon: ShieldCheck,
      active: !!execution.deliverable_status, done: !!execution.deliverable_status,
      body: (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="label-caps">Deliverable</span>
          <StatusBadge status={execution.deliverable_status || "—"} testid="tl-deliverable-status" />
        </div>
      ),
    },
    {
      key: "ext", title: "3. Azione esterna", icon: Send,
      active: execution.action_status && execution.action_status !== "NON_RICHIESTA",
      done: ["ESEGUITA"].includes(execution.action_status),
      body: (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="label-caps">Azione</span>
          <StatusBadge status={execution.action_status} testid="tl-action-status" />
          {execution.action_status === "BLOCCATA" && (
            <span className="text-xs text-red-400">Invio bloccato: {(execution.missing_prerequisites || []).join(", ")}</span>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-border/60 border border-border/60 rounded-sm overflow-hidden" data-testid="execution-timeline">
      {sections.map((s) => (
        <div key={s.key} className={cn("bg-card p-4", !s.active && "opacity-50")}>
          <div className="flex items-center gap-2 mb-3">
            <div className={cn("w-7 h-7 rounded-sm grid place-items-center border",
              s.done ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-400" : "bg-muted border-border text-muted-foreground")}>
              <s.icon className="w-4 h-4" strokeWidth={1.75} />
            </div>
            <div className="font-display font-medium text-sm">{s.title}</div>
          </div>
          {s.body}
        </div>
      ))}
    </div>
  );
}
