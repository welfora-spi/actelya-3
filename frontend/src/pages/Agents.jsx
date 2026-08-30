import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, Card } from "@/components/Primitives";
import { cn } from "@/lib/utils";

export default function Agents() {
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(null);
  useEffect(() => { api.get("/agents").then((r) => setRows(r.data)).catch(() => {}); }, []);
  return (
    <div>
      <PageHeader title="Operatori AI" subtitle="Orchestratore + agenti con contratto strutturato. Compliance e Auditor valutano senza distruggere il deliverable." />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="agents-list">
        {rows.map((a) => (
          <Card key={a.id} className="p-4">
            <div className="flex items-center justify-between">
              <span className="font-display font-medium">{a.name}</span>
              <span className={cn("text-[10px] font-mono rounded-sm px-1.5 py-0.5 border",
                a.operative ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" : "border-slate-500/30 bg-slate-500/10 text-slate-400")}>
                {a.operative ? "OPERATIVO" : "PREDISPOSTO"}
              </span>
            </div>
            <p className="text-xs text-muted-foreground mt-1 min-h-[32px]">{a.mission}</p>
            <div className="grid grid-cols-3 gap-2 mt-3 text-[11px] font-mono">
              <div><div className="label-caps">Token</div>{a.token_limit}</div>
              <div><div className="label-caps">Budget</div>${a.budget}</div>
              <div><div className="label-caps">Timeout</div>{a.timeout}s</div>
            </div>
            <button data-testid={`agent-detail-${a.id}`} onClick={() => setOpen(open === a.id ? null : a.id)}
              className="mt-3 text-xs rounded-sm border border-border px-2 py-1 hover:bg-muted/50 transition-colors duration-200">
              {open === a.id ? "Nascondi contratto" : "Vedi contratto"}
            </button>
            {open === a.id && (
              <div className="mt-3 space-y-2 text-xs border-t border-border/60 pt-3">
                <Row label="Responsabilità" items={a.responsibilities} />
                <Row label="Attività vietate" items={a.forbidden} tone="text-red-400" />
                <Row label="Input richiesti" items={a.required_inputs} />
                <Row label="Campi obbligatori output" items={a.required_fields} />
                <Row label="Criteri di blocco" items={a.block_criteria} tone="text-amber-400" />
              </div>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}

function Row({ label, items, tone }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <div className="label-caps">{label}</div>
      <div className={cn("mt-0.5", tone)}>{items.join(", ")}</div>
    </div>
  );
}
