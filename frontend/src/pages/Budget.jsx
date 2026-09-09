import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card } from "@/components/Primitives";
import { useAuth } from "@/context/AuthContext";
import { useSystem } from "@/context/SystemContext";
import { toast } from "sonner";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { formatBudgetLine, isBudgetConfigured } from "@/lib/budget";

export default function Budget() {
  const [b, setB] = useState(null);
  const [general, setGeneral] = useState("");
  const [daily, setDaily] = useState("");
  const { hasRole } = useAuth();
  const { refresh } = useSystem();
  const isAdmin = hasRole("ADMIN");

  const load = useCallback(() => {
    api.get("/budget").then((r) => { setB(r.data); setGeneral(String(r.data.general_limit || 0)); setDaily(String(r.data.daily_limit || 0)); }).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try { await api.put("/budget", { general_limit: parseFloat(general), daily_limit: parseFloat(daily) }); toast.success("Budget aggiornato"); load(); refresh(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const configured = isBudgetConfigured(b?.general_limit);
  // Etichette dipendenti da b.mode (REALE/SIMULAZIONE/MISTA — vedi
  // domains/budget.py::compute_spent): "Speso (sim)" era un'etichetta fissa
  // anche quando la spesa era in realta' (in parte o del tutto) reale
  // (es. costi di comprensione del brain, sempre reali quando > 0).
  const speseLabel = b?.mode === "REALE" ? "Speso (reale)" : b?.mode === "MISTA" ? "Speso (misto)" : "Speso (sim)";
  const panoramicaLabel = b?.mode === "REALE" ? "Panoramica (REALE)" : b?.mode === "MISTA" ? "Panoramica (MISTA)" : "Panoramica (SIMULAZIONE)";
  const chart = [
    { name: "Limite", value: b?.general_limit || 0 },
    { name: speseLabel, value: b?.spent_simulated || 0 },
    // Un "Residuo" negativo con limite non configurato (0) sarebbe fuorviante
    // (sembrerebbe uno sforamento): la barra si mostra solo a limite impostato.
    ...(configured ? [{ name: "Residuo", value: b?.residual || 0 }] : []),
  ];
  const colors = ["#64748b", "#f59e0b", "#22c55e"];

  return (
    <div>
      <PageHeader title="Budget e costi" subtitle="Il budget generale non sostituisce il tetto specifico approvato di ogni preventivo." />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="p-5 lg:col-span-2">
          <div className="label-caps mb-3" data-testid="budget-panoramica-label">{panoramicaLabel}</div>
          <div style={{ width: "100%", height: 240, minHeight: 240 }}>
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <BarChart data={chart}>
                <XAxis dataKey="name" stroke="#71717a" fontSize={11} />
                <YAxis stroke="#71717a" fontSize={11} />
                <Tooltip contentStyle={{ background: "#121214", border: "1px solid #2a2a30", borderRadius: 6, fontSize: 12 }} />
                <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                  {chart.map((_, i) => <Cell key={i} fill={colors[i]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card className="p-5">
          <div className="label-caps mb-3">Configurazione</div>
          <div className="space-y-3">
            <div>
              <label className="label-caps block mb-1">Limite generale ($)</label>
              <input data-testid="budget-general" type="number" value={general} disabled={!isAdmin} onChange={(e) => setGeneral(e.target.value)}
                className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm font-mono focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none disabled:opacity-60" />
            </div>
            <div>
              <label className="label-caps block mb-1">Limite giornaliero ($)</label>
              <input data-testid="budget-daily" type="number" value={daily} disabled={!isAdmin} onChange={(e) => setDaily(e.target.value)}
                className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm font-mono focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none disabled:opacity-60" />
            </div>
            {isAdmin && <button data-testid="budget-save" onClick={save} className="w-full bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm hover:opacity-90 active:scale-[0.98] transition-colors duration-200">Salva budget</button>}
            <div className="pt-2 border-t border-border/60 space-y-1.5 text-sm">
              <Row l={speseLabel} v={`$${(b?.spent_simulated || 0).toFixed(5)}`} />
              {b?.spent_brain > 0 && (
                <div data-testid="budget-spent-brain" className="text-xs text-muted-foreground flex justify-between">
                  <span>di cui comprensione brain (prima di ogni piano)</span>
                  <span className="font-mono">${(b.spent_brain).toFixed(5)}</span>
                </div>
              )}
              {b?.spent_content_creator > 0 && (
                <div data-testid="budget-spent-content-creator" className="text-xs text-muted-foreground flex justify-between">
                  <span>di cui laboratorio Content Creator</span>
                  <span className="font-mono">${(b.spent_content_creator).toFixed(5)}</span>
                </div>
              )}
              {b?.spent_altri_reali > 0 && (
                <div data-testid="budget-spent-altri-reali" className="text-xs text-muted-foreground flex justify-between">
                  <span>di cui altre chiamate reali (es. revisione bozze)</span>
                  <span className="font-mono">${(b.spent_altri_reali).toFixed(5)}</span>
                </div>
              )}
              <Row l="Residuo" v={formatBudgetLine(b?.general_limit, b?.residual)} />
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
function Row({ l, v }) { return <div className="flex justify-between"><span className="text-muted-foreground">{l}</span><span className="font-mono">{v}</span></div>; }
