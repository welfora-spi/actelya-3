import { useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useSystem } from "@/context/SystemContext";
import { toast } from "sonner";

const EXAMPLES = [
  "Scrivi una breve email commerciale per un'azienda immaginaria che offre consulenza previdenziale. Usa esclusivamente dati fittizi. Non inviare l'email.",
  "Scrivi e invia una mail ai prospect pensionistici.",
];

export default function NewGoal() {
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  const navigate = useNavigate();
  const { refresh } = useSystem();

  const submit = async () => {
    if (!text.trim()) return;
    setLoading(true); setResult(null);
    try {
      const { data } = await api.post("/goals", { text });
      setResult(data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setLoading(false); }
  };

  const approve = async () => {
    if (!result) return;
    setApproving(true);
    try {
      const { data } = await api.post(`/approvals/${result.approval.id}/approve`);
      toast.success("Approvato: esecuzione creata");
      await refresh();
      if (data.execution_id) navigate(`/esecuzioni?focus=${data.execution_id}`);
      else navigate("/esecuzioni");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setApproving(false); }
  };

  const est = result?.approval;
  const intent = result?.goal?.intent;

  return (
    <div>
      <PageHeader title="Nuovo Obiettivo"
        subtitle="Il sistema classifica l'intento, prepara un piano e un preventivo. Nessuna azione esterna viene eseguita senza approvazione." />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-5">
          <label className="label-caps block mb-2">Obiettivo</label>
          <textarea
            data-testid="goal-input"
            value={text} onChange={(e) => setText(e.target.value)} rows={5}
            placeholder="Es: Scrivi una breve email commerciale…"
            className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none resize-none"
          />
          <div className="mt-3 space-y-1.5">
            <div className="label-caps">Esempi</div>
            {EXAMPLES.map((ex, i) => (
              <button key={i} data-testid={`goal-example-${i}`} onClick={() => setText(ex)}
                className="block text-left text-xs text-muted-foreground hover:text-foreground border border-border/60 rounded-sm px-2 py-1.5 w-full transition-colors duration-200">
                {ex}
              </button>
            ))}
          </div>
          <button data-testid="goal-classify" onClick={submit} disabled={loading || !text.trim()}
            className="mt-4 bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm font-medium hover:opacity-90 active:scale-[0.98] transition-colors duration-200 disabled:opacity-50">
            {loading ? "Analisi…" : "Classifica e preventiva"}
          </button>
        </Card>

        <Card className="p-5">
          <h2 className="font-display text-lg font-medium mb-3">Piano & Preventivo</h2>
          {!result && <p className="text-sm text-muted-foreground">Inserisci un obiettivo per generare classificazione e preventivo (nessuna chiamata reale).</p>}
          {result && (
            <div className="space-y-4" data-testid="goal-result">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="label-caps">Intento</span>
                <StatusBadge status={intent.intent_type} testid="goal-intent" />
                {intent.risk_flags.map((r) => (
                  <span key={r} className="text-[10px] font-mono border border-red-500/30 bg-red-500/10 text-red-400 rounded-sm px-1.5 py-0.5">{r}</span>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">{intent.intent_reason}</p>

              <div className="grid grid-cols-3 gap-px bg-border/60 border border-border/60 rounded-sm overflow-hidden">
                {[["Minimo", est.cost_min], ["Probabile", est.cost_probable], ["Massimo", est.cost_max]].map(([l, v]) => (
                  <div key={l} className="bg-card p-3">
                    <div className="label-caps">{l}</div>
                    <div className="font-mono text-sm mt-1">${v.toFixed(5)}</div>
                  </div>
                ))}
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Tetto approvabile</span>
                <span className="font-mono">${est.approved_cap.toFixed(5)}</span>
              </div>

              <div>
                <div className="label-caps mb-1">Agenti coinvolti</div>
                <div className="flex flex-wrap gap-1.5">
                  {result.goal.agents.map((a) => (
                    <span key={a} className="text-[11px] font-mono border border-border rounded-sm px-2 py-0.5">{a}</span>
                  ))}
                </div>
              </div>

              {est.external_actions.length > 0 && (
                <div className="text-xs border border-amber-500/30 bg-amber-500/10 text-amber-400 rounded-sm px-3 py-2">
                  Azioni esterne previste: {est.external_actions.join(", ")} — richiederanno un'ulteriore approvazione e resteranno bloccate senza prerequisiti.
                </div>
              )}

              <button data-testid="goal-approve" onClick={approve} disabled={approving}
                className="w-full bg-emerald-600 text-white rounded-sm px-4 py-2.5 text-sm font-medium hover:bg-emerald-500 active:scale-[0.98] transition-colors duration-200 disabled:opacity-50">
                {approving ? "Approvazione…" : "APPROVA preventivo e crea esecuzione"}
              </button>
              <p className="text-[11px] text-muted-foreground text-center">L'approvazione è idempotente: un solo click crea una sola esecuzione.</p>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
