import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";

const KPI_LABELS = {
  conversion_rate: "Conversion rate", lead_velocity: "Lead velocity", response_rate: "Response rate",
  appointment_rate: "Appointment rate", close_rate: "Close rate", funnel_drop_off: "Abbandono funnel",
  cost_per_lead: "Costo per lead", cost_per_appointment: "Costo per appuntamento",
  cost_per_acquisition: "Costo per acquisizione", engagement: "Engagement", roi: "ROI", roas: "ROAS",
};

const RELIABILITY_COLOR = {
  ALTA: "text-emerald-400", MEDIA: "text-blue-400", BASSA: "text-amber-400", NON_DISPONIBILE: "text-zinc-500",
};

function KpiCard({ kpiId, kpi }) {
  if (!kpi) return null;
  return (
    <Card className="p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium">{KPI_LABELS[kpiId] || kpiId}</span>
        <span className={`text-[10px] font-mono ${RELIABILITY_COLOR[kpi.reliability] || ""}`}>{kpi.reliability}</span>
      </div>
      <div className="text-2xl font-display mt-1">
        {kpi.missing_data || kpi.value == null ? "—" : `${kpi.value}${kpiId.includes("rate") || kpiId === "funnel_drop_off" ? "%" : ""}`}
      </div>
      {kpi.note && <div className="text-[11px] text-muted-foreground mt-1">{kpi.note}</div>}
      <div className="text-[10px] text-muted-foreground mt-2 font-mono">{kpi.formula}</div>
    </Card>
  );
}

export default function Analyst() {
  const [searchParams] = useSearchParams();
  const [reports, setReports] = useState([]);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [days, setDays] = useState(30);

  const loadReports = useCallback(() => {
    api.get("/analyst/reports").then((r) => setReports(r.data)).catch(() => {});
  }, []);

  useEffect(() => { loadReports(); }, [loadReports]);

  useEffect(() => {
    const reportId = searchParams.get("reportId");
    if (reportId) {
      api.get(`/analyst/reports/${reportId}`).then((r) => setSelected(r.data)).catch(() => {});
    }
  }, [searchParams]);

  const generateReport = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/analyst/reports", { time_range_days: Number(days) });
      toast.success(`Report generato — ${data.insights.length} insight.`);
      loadReports(); setSelected(data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title="Analyst — laboratorio"
        subtitle="KPI reali da dati già presenti in ACTELYA, interpretati e indirizzati agli agenti giusti — mai un dato inventato."
        actions={
          <div className="flex items-center gap-2">
            <input type="number" value={days} onChange={(e) => setDays(e.target.value)} min={1} max={365}
              className="w-20 bg-background border border-border rounded-sm px-2 py-2 text-sm" />
            <button data-testid="generate-report-btn" onClick={generateReport} disabled={busy}
              className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm hover:opacity-90 transition-colors duration-200">
              <RefreshCw className="w-4 h-4" /> Genera report
            </button>
          </div>
        } />

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6">
        <div>
          <h2 className="font-display text-sm label-caps mb-2">Report</h2>
          {reports.length === 0 ? <Empty text="Nessun report ancora." /> : (
            <div className="space-y-2" data-testid="reports-list">
              {reports.map((r) => (
                <Card key={r.id} className={`p-3 cursor-pointer ${selected?.id === r.id ? "border-primary" : ""}`}
                  onClick={() => setSelected(r)}>
                  <div className="text-xs">{new Date(r.generated_at).toLocaleString()}</div>
                  <div className="text-[11px] text-muted-foreground mt-1">{r.time_range_days} giorni · {r.insights?.length || 0} insight</div>
                </Card>
              ))}
            </div>
          )}
        </div>

        <div>
          {!selected ? <Empty text="Seleziona o genera un report." /> : (
            <div className="space-y-6">
              <div>
                <h3 className="font-display text-sm label-caps mb-2">KPI</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="kpi-grid">
                  {Object.entries(selected.kpis || {}).map(([kpiId, kpi]) => (
                    <KpiCard key={kpiId} kpiId={kpiId} kpi={kpi} />
                  ))}
                </div>
              </div>

              <div>
                <h3 className="font-display text-sm label-caps mb-2">Insight</h3>
                <div className="space-y-2" data-testid="insights-list">
                  {(selected.insights || []).map((insight, i) => (
                    <Card key={i} className="p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">{insight.titolo}</span>
                        <span className="text-[10px] font-mono text-muted-foreground">{insight.target_agent}</span>
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">{insight.spiegazione}</div>
                    </Card>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
