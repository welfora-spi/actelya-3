import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

const EXAMPLES = [
  "Prepara una campagna social e adv per il lancio di un nuovo prodotto (dati fittizi).",
  "Costruisci un piano di lead generation per prospect B2B (solo criteri, nessun contatto reale).",
  "Genera un report KPI del trimestre con dati simulati.",
];

export default function Plans() {
  const [plans, setPlans] = useState(null);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [clarify, setClarify] = useState(null);
  const { hasRole } = useAuth();
  const navigate = useNavigate();
  const canCreate = hasRole("OPERATORE", "ADMIN");

  const load = () => api.get("/m2/plans").then((r) => setPlans(r.data.plans)).catch(() => {});
  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!text.trim()) return;
    setLoading(true); setClarify(null);
    try {
      const { data } = await api.post("/m2/plans", { text });
      if (data.requires_clarification) {
        setClarify(data.objective_type);
        toast.warning("Obiettivo ambiguo: serve un chiarimento, nessuna azione avviata");
      } else {
        toast.success("Piano creato in bozza (SIMULAZIONE)");
        navigate(`/piani/${data.plan.id}`);
      }
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setLoading(false); }
  };

  return (
    <div data-testid="plans-page">
      <PageHeader title="Piani (M2)"
        subtitle="Pianificazione multi-attività: il sistema scompone l'obiettivo in un DAG di attività con preventivo. Tutto in SIMULAZIONE, nessuna azione esterna." />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-5">
          <label className="label-caps block mb-2">Nuovo piano</label>
          <textarea
            data-testid="plan-input" value={text} onChange={(e) => setText(e.target.value)} rows={4}
            disabled={!canCreate}
            placeholder="Es: Prepara una campagna social e adv per il lancio…"
            className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none resize-none disabled:opacity-50"
          />
          <div className="mt-3 space-y-1.5">
            <div className="label-caps">Esempi</div>
            {EXAMPLES.map((ex, i) => (
              <button key={i} data-testid={`plan-example-${i}`} onClick={() => setText(ex)} disabled={!canCreate}
                className="block text-left text-xs text-muted-foreground hover:text-foreground border border-border/60 rounded-sm px-2 py-1.5 w-full transition-colors duration-200 disabled:opacity-50">
                {ex}
              </button>
            ))}
          </div>
          {clarify && (
            <div data-testid="plan-clarify" className="mt-3 text-xs border border-violet-500/30 bg-violet-500/10 text-violet-300 rounded-sm px-3 py-2">
              Obiettivo classificato come <b>{clarify}</b>: riformula con un verbo di produzione chiaro (es. "prepara", "scrivi", "genera"). Nessuna attività è stata creata.
            </div>
          )}
          {!canCreate && <p className="mt-3 text-xs text-muted-foreground">Il tuo ruolo non consente la creazione di piani.</p>}
          <button data-testid="plan-create-btn" onClick={create} disabled={loading || !text.trim() || !canCreate}
            className="mt-4 bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm font-medium hover:opacity-90 active:scale-[0.98] transition-colors duration-200 disabled:opacity-50">
            {loading ? "Creazione…" : "Crea piano e preventivo"}
          </button>
        </Card>

        <Card className="p-5">
          <h2 className="font-display text-lg font-medium mb-3">Piani esistenti</h2>
          {!plans && <p className="text-sm text-muted-foreground">Caricamento…</p>}
          {plans && plans.length === 0 && <Empty text="Nessun piano ancora. Creane uno a sinistra." />}
          {plans && plans.length > 0 && (
            <div className="space-y-2" data-testid="plans-list">
              {plans.map((p) => (
                <button key={p.id} data-testid={`plan-row-${p.id}`} onClick={() => navigate(`/piani/${p.id}`)}
                  className="w-full text-left border border-border/60 rounded-sm px-3 py-2.5 hover:bg-muted/40 transition-colors duration-200">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{p.objective_type}</span>
                    <StatusBadge status={p.plan_status} testid={`plan-status-${p.id}`} />
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
    </div>
  );
}
