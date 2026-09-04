import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { toast } from "sonner";
import { Search, CheckCircle2, AlertTriangle } from "lucide-react";

const METHOD_LABEL = { DICHIARATO: "Dichiarato", ESTRATTO: "Estratto", DEDOTTO: "Dedotto", VERIFICATO: "Verificato" };

export default function Onboarding() {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [facts, setFacts] = useState({});
  const [conflicts, setConflicts] = useState({});
  const [discoveryRun, setDiscoveryRun] = useState(null);
  const [running, setRunning] = useState(false);
  const pollRef = useRef(null);

  const load = useCallback(async () => {
    const [s, f, c] = await Promise.all([
      api.get("/onboarding/status"), api.get("/knowledge/facts/current"), api.get("/knowledge/conflicts"),
    ]);
    setStatus(s.data); setFacts(f.data); setConflicts(c.data);
  }, []);

  useEffect(() => { load().catch(() => {}); }, [load]);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const runDiscovery = async () => {
    setRunning(true);
    try {
      const { data } = await api.post("/discovery/run");
      setDiscoveryRun(data);
      pollRef.current = setInterval(async () => {
        const r = await api.get(`/discovery/runs/${data.id}`);
        setDiscoveryRun(r.data);
        if (["COMPLETATO", "FALLITO"].includes(r.data.status)) {
          clearInterval(pollRef.current);
          setRunning(false);
          await load();
          toast.success(r.data.status === "COMPLETATO" ? "Discovery completata" : "Discovery fallita");
        }
      }, 1500);
    } catch (e) {
      setRunning(false);
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const confirmFact = async (factId) => {
    try {
      await api.post(`/knowledge/facts/${factId}/confirm`);
      toast.success("Contraddizione risolta");
      await load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const completeOnboarding = async () => {
    try {
      await api.post("/onboarding/complete");
      toast.success("Onboarding completato");
      navigate("/");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (!status) return null;

  const factRows = Object.values(facts).sort((a, b) => a.field.localeCompare(b.field));
  const conflictFields = Object.keys(conflicts);

  return (
    <div>
      <PageHeader
        title="Conoscenza azienda"
        subtitle="Profilo Azienda e Fact Ledger: ogni informazione con fonte, metodo di acquisizione e affidabilità."
        actions={
          <button data-testid="onboarding-run-discovery" onClick={runDiscovery} disabled={running}
            className="inline-flex items-center gap-2 bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm hover:opacity-90 active:scale-[0.98] transition-colors duration-200 disabled:opacity-50">
            <Search className="w-4 h-4" /> {running ? "Ricerca in corso…" : "Avvia Discovery"}
          </button>
        }
      />

      {discoveryRun && (
        <Card className="p-4 mb-4 text-sm">
          <span className="label-caps mr-2">Discovery (SIMULATO)</span>
          <span className="font-mono">{discoveryRun.status}</span>
          {discoveryRun.warnings?.length > 0 && (
            <span className="text-amber-500 ml-3">{discoveryRun.warnings.join(" · ")}</span>
          )}
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <Card className="p-5">
          <div className="label-caps mb-2">Stato onboarding</div>
          <div className="text-sm font-mono mb-1">{status.onboarding_status}</div>
          <div className="text-xs text-muted-foreground">
            {status.missing_core_fields.length > 0
              ? `Campi mancanti: ${status.missing_core_fields.join(", ")}`
              : "Tutti i campi base sono presenti."}
          </div>
        </Card>
        <Card className="p-5">
          <div className="label-caps mb-2">Contraddizioni aperte</div>
          <div className="text-2xl font-mono">{status.open_conflicts}</div>
        </Card>
        <Card className="p-5 flex flex-col justify-between">
          <div>
            <div className="label-caps mb-2">Completamento</div>
            <div className="text-xs text-muted-foreground mb-3">
              {status.ready_to_complete ? "Pronto per essere completato." : "Risolvi i campi mancanti e le contraddizioni prima di completare."}
            </div>
          </div>
          <button data-testid="onboarding-complete" onClick={completeOnboarding} disabled={!status.ready_to_complete}
            className="w-full inline-flex items-center justify-center gap-2 bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm hover:opacity-90 active:scale-[0.98] transition-colors duration-200 disabled:opacity-40">
            <CheckCircle2 className="w-4 h-4" /> Completa onboarding
          </button>
        </Card>
      </div>

      {conflictFields.length > 0 && (
        <Card className="p-5 mb-4 border-amber-500/40">
          <div className="label-caps mb-3 text-amber-500 flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> Contraddizioni da risolvere</div>
          <div className="space-y-3">
            {conflictFields.map((field) => (
              <div key={field} className="text-sm">
                <div className="font-mono text-xs text-muted-foreground mb-1">{field}</div>
                <div className="flex flex-wrap gap-2">
                  {conflicts[field].map((f) => (
                    <button key={f.id} data-testid={`conflict-confirm-${f.id}`} onClick={() => confirmFact(f.id)}
                      className="text-left border border-border/60 rounded-sm px-3 py-2 hover:border-primary transition-colors">
                      <div className="font-medium">{f.value}</div>
                      <div className="text-xs text-muted-foreground">{METHOD_LABEL[f.method]} · fonte: {f.source}</div>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card className="p-5">
        <div className="label-caps mb-3">Fact Ledger — profilo aziendale condiviso</div>
        {factRows.length === 0 ? <Empty text="Nessun fatto registrato." /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground label-caps text-xs">
                  <th className="py-2 pr-4">Campo</th><th className="py-2 pr-4">Valore</th>
                  <th className="py-2 pr-4">Metodo</th><th className="py-2 pr-4">Fonte</th>
                  <th className="py-2 pr-4">Affidabilità</th>
                </tr>
              </thead>
              <tbody>
                {factRows.map((f) => (
                  <tr key={f.id} className="border-t border-border/40">
                    <td className="py-2 pr-4 font-mono text-xs">{f.field}</td>
                    <td className="py-2 pr-4">{f.value}</td>
                    <td className="py-2 pr-4">{METHOD_LABEL[f.method] || f.method}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{f.source}</td>
                    <td className="py-2 pr-4 font-mono">{Math.round((f.confidence || 0) * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
