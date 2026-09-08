import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { ArrowRight } from "lucide-react";

// Sola lettura: i piani si creano SOLO tramite il brain (pagina "Nuovo
// Obiettivo" -> POST /brain/plans), mai qui direttamente su POST /m2/plans
// grezzo — altrimenti si aggirerebbero triage, selezione agenti e le
// verifiche di sicurezza del brain (vedi service.py::create_plan_with_brain).
export default function Plans() {
  const [plans, setPlans] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.get("/m2/plans").then((r) => setPlans(r.data.plans)).catch(() => {});
  }, []);

  return (
    <div data-testid="plans-page">
      <PageHeader title="Piani (M2)"
        subtitle="Elenco dei piani prodotti dal brain: DAG di attività, preventivo e stato. Modalità reale/simulazione indicata nel dettaglio di ciascun piano."
        actions={
          <button data-testid="plans-new-goal-cta" onClick={() => navigate("/nuovo-obiettivo")}
            className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm font-medium hover:opacity-90 active:scale-[0.98] transition-colors duration-200">
            + Nuovo obiettivo <ArrowRight className="w-4 h-4" />
          </button>
        }
      />

      <Card className="p-5">
        {!plans && <p className="text-sm text-muted-foreground">Caricamento…</p>}
        {plans && plans.length === 0 && (
          <Empty text='Nessun piano ancora. Creane uno dalla pagina "Nuovo Obiettivo".' />
        )}
        {plans && plans.length > 0 && (
          <div className="space-y-2" data-testid="plans-list">
            {plans.map((p) => (
              <button key={p.id} data-testid={`plan-row-${p.id}`} onClick={() => navigate(`/piani/${p.id}`)}
                className="w-full text-left border border-border/60 rounded-sm px-3 py-2.5 hover:bg-muted/40 transition-colors duration-200">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{p.objective_type}</span>
                  <div className="flex items-center gap-2">
                    {/* Item #10: un piano senza plan_generation e' antecedente alla
                        correzione item #6 (squadra M2 allineata alla selezione del
                        brain) — mai cancellato, solo etichettato come storico per
                        non confonderlo con un piano prodotto dal flusso corrente. */}
                    {p.plan_generation !== "brain_single_team_v2" && (
                      <span className="text-[10px] font-mono border border-border/60 text-muted-foreground rounded-sm px-1.5 py-0.5" title="Piano creato prima della correzione della selezione squadra: dati storici, non confrontabili con i piani correnti.">
                        storico
                      </span>
                    )}
                    {p.active_agent_ids?.length > 0 && (
                      <span className="text-[10px] font-mono text-muted-foreground">{p.active_agent_ids.length} agenti</span>
                    )}
                    <StatusBadge status={p.plan_status} testid={`plan-status-${p.id}`} />
                  </div>
                </div>
                <div className="text-[11px] text-muted-foreground font-mono mt-1">
                  v{p.version} · {new Date(p.created_at).toLocaleString("it-IT")}
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
