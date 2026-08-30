import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card } from "@/components/Primitives";
import { useAuth } from "@/context/AuthContext";
import { useSystem } from "@/context/SystemContext";
import { toast } from "sonner";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

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

  const chart = [
    { name: "Limite", value: b?.general_limit || 0 },
    { name: "Speso (sim)", value: b?.spent_simulated || 0 },
    { name: "Residuo", value: b?.residual || 0 },
  ];
  const colors = ["#64748b", "#f59e0b", "#22c55e"];

  return (
    <div>
      <PageHeader title="Budget e costi" subtitle="Il budget generale non sostituisce il tetto specifico approvato di ogni preventivo." />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="p-5 lg:col-span-2">
          <div className="label-caps mb-3">Panoramica (SIMULAZIONE)</div>
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
              <Row l="Speso (sim)" v={`$${(b?.spent_simulated || 0).toFixed(5)}`} />
              <Row l="Residuo" v={`$${(b?.residual || 0).toFixed(5)}`} />
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
function Row({ l, v }) { return <div className="flex justify-between"><span className="text-muted-foreground">{l}</span><span className="font-mono">{v}</span></div>; }
