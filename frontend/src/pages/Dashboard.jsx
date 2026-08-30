import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { PageHeader, Card } from "@/components/Primitives";
import { useSystem } from "@/context/SystemContext";
import { Target, CheckSquare, FileText, Wallet, PlayCircle, AlertTriangle, Network, ShieldAlert } from "lucide-react";

function Kpi({ label, value, sub, icon: Icon, tone = "" }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="label-caps">{label}</span>
        <Icon className="w-4 h-4 text-muted-foreground" strokeWidth={1.75} />
      </div>
      <div className={`font-display text-3xl font-semibold tracking-tight mt-2 ${tone}`}>{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-1 font-mono">{sub}</div>}
    </Card>
  );
}

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [m2, setM2] = useState(null);
  const { mode } = useSystem();
  const navigate = useNavigate();

  useEffect(() => {
    const load = () => {
      api.get("/dashboard").then((r) => setData(r.data)).catch(() => {});
      api.get("/m2/stats").then((r) => setM2(r.data)).catch(() => {});
    };
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  const d = data || {};
  const m = m2 || {};
  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Panoramica operativa. Un contenuto è conteggiato solo se esiste un deliverable persistito e valido."
        actions={
          <button data-testid="dashboard-new-goal" onClick={() => navigate("/nuovo-obiettivo")}
            className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm font-medium hover:opacity-90 active:scale-[0.98] transition-colors duration-200">
            + Nuovo obiettivo
          </button>
        }
      />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi label="Esecuzioni" value={d.executions_total ?? 0} icon={PlayCircle}
          sub={Object.entries(d.executions_by_status || {}).map(([k, v]) => `${k}:${v}`).join("  ")} />
        <Kpi label="Deliverable validi" value={d.valid_deliverables ?? 0} icon={FileText} tone="text-emerald-400"
          sub={`${d.blocked_deliverables ?? 0} bloccati`} />
        <Kpi label="Approvazioni pendenti" value={d.pending_approvals ?? 0} icon={CheckSquare} tone="text-violet-400" />
        <Kpi label="Costo (simulato)" value={`$${(d.total_cost_simulated ?? 0).toFixed(4)}`} icon={Wallet}
          sub={`Residuo $${(d.budget_residual ?? 0).toFixed(4)}`} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-4">
        <Card className="p-5 lg:col-span-2">
          <div className="flex items-center gap-2 mb-3">
            <Network className="w-4 h-4 text-muted-foreground" />
            <h2 className="font-display text-lg font-medium">Milestone 2 — Pianificazione multi-attività</h2>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4" data-testid="m2-kpis">
            <div className="border border-border/60 rounded-sm p-3">
              <div className="label-caps">Piani</div>
              <div className="font-display text-2xl font-semibold mt-1" data-testid="m2-plans-total">{m.plans_total ?? 0}</div>
            </div>
            <div className="border border-border/60 rounded-sm p-3">
              <div className="label-caps">Deliverable validi</div>
              <div className="font-display text-2xl font-semibold mt-1 text-emerald-400">{m.deliverables_valid ?? 0}</div>
            </div>
            <div className="border border-border/60 rounded-sm p-3">
              <div className="label-caps">Deliverable bloccati</div>
              <div className="font-display text-2xl font-semibold mt-1 text-red-400">{m.deliverables_blocked ?? 0}</div>
            </div>
            <div className={`border rounded-sm p-3 ${(m.reviews_high_compliance ?? 0) > 0 ? "border-red-500/40 bg-red-500/5" : "border-border/60"}`}>
              <div className="label-caps flex items-center gap-1"><ShieldAlert className="w-3 h-3" /> Rilievi compliance</div>
              <div className={`font-display text-2xl font-semibold mt-1 ${(m.reviews_high_compliance ?? 0) > 0 ? "text-red-400" : ""}`} data-testid="m2-high-compliance">{m.reviews_high_compliance ?? 0}</div>
            </div>
          </div>
          <button data-testid="dashboard-plans-cta" onClick={() => navigate("/piani")}
            className="rounded-sm border border-border px-4 py-2 text-sm hover:bg-muted/50 active:scale-[0.98] transition-colors duration-200">
            Vai ai piani →
          </button>
        </Card>
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-4 h-4 text-amber-500" />
            <h2 className="font-display text-lg font-medium">Stato sistema</h2>
          </div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Modalità</span><span className="font-mono">{mode}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Budget</span><span className="font-mono">${(d.budget_limit ?? 0).toFixed(2)}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Provider AI</span><span className="font-mono text-amber-500">SIMULATO</span></div>
          </div>
        </Card>
      </div>
    </div>
  );
}
