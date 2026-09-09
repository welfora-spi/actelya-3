import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { toast } from "sonner";
import { Search, CheckCircle2, AlertTriangle } from "lucide-react";

const METHOD_LABEL = { DICHIARATO: "Dichiarato", ESTRATTO: "Estratto", DEDOTTO: "Dedotto", VERIFICATO: "Verificato" };

// Esiti del fetch reale (domains/discovery.py: ESITO_LETTO/…) — un'etichetta
// leggibile per ciascuno, mai un generico "trovato/non trovato".
const REAL_FETCH_ESITO_LABEL = {
  CONTENUTO_LETTO: "Pagina letta realmente",
  CONTENUTO_INSUFFICIENTE_RICHIEDE_JS: "Pagina raggiunta ma richiede JavaScript: contenuto insufficiente",
  ACCESSO_IMPEDITO: "Accesso impedito",
  NESSUN_RISULTATO: "Pagina raggiunta ma senza contenuto utilizzabile",
};

export default function Onboarding() {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [facts, setFacts] = useState({});
  const [conflicts, setConflicts] = useState({});
  const [discoveryRun, setDiscoveryRun] = useState(null);
  const [running, setRunning] = useState(false);
  const pollRef = useRef(null);

  const load = useCallback(async () => {
    const [s, f, c, runs] = await Promise.all([
      api.get("/onboarding/status"), api.get("/knowledge/facts/current"), api.get("/knowledge/conflicts"),
      // Ultima ricerca gia' persistita (mai solo lo stato in memoria dalla
      // risposta di un POST precedente): cosi' l'esito resta consultabile
      // anche dopo un refresh della pagina, senza avviare nulla di nuovo.
      api.get("/discovery/runs").catch(() => ({ data: [] })),
    ]);
    setStatus(s.data); setFacts(f.data); setConflicts(c.data);
    if (runs.data?.length > 0) setDiscoveryRun(runs.data[0]);
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
        <Card className="p-4 mb-4 text-sm" data-testid="discovery-summary">
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className="label-caps">Ultima Discovery</span>
            <span className="font-mono">{discoveryRun.status}</span>
          </div>
          {/* 'mode' del run resta sempre "SIMULATO" per costruzione (vedi
              domains/discovery.py): descrive SOLO la stima euristica di
              tono/pubblico (sempre calcolata, mai una lettura reale). La
              lettura reale del sito e' una fase A SE' STANTE, tracciata
              SOLO in real_fetch.esito — le due etichette convivono apposta,
              non sono in contraddizione: due fasi diverse dello stesso run. */}
          <div className="grid sm:grid-cols-2 gap-2 mb-2">
            <div className="border border-border/60 rounded-sm px-3 py-2">
              <div className="text-[10px] font-mono text-muted-foreground mb-0.5">FASE 1 · stima tono/pubblico</div>
              <div className="text-xs">Sempre simulata (euristica per dominio, mai una lettura reale) — vedi affidabilità 70% in tabella, senza evidenza.</div>
            </div>
            <div className="border border-border/60 rounded-sm px-3 py-2">
              <div className="text-[10px] font-mono text-muted-foreground mb-0.5">FASE 2 · lettura reale del sito</div>
              <span
                data-testid="discovery-fetch-badge"
                className={`inline-block text-[10px] font-mono px-1.5 py-0.5 rounded-sm ${discoveryRun.real_fetch?.esito === "CONTENUTO_LETTO" ? "bg-emerald-500/15 text-emerald-500" : discoveryRun.real_fetch ? "bg-amber-500/15 text-amber-500" : "bg-muted text-muted-foreground"}`}
              >
                {discoveryRun.real_fetch
                  ? (REAL_FETCH_ESITO_LABEL[discoveryRun.real_fetch.esito] || discoveryRun.real_fetch.esito)
                  : "Permesso non concesso: nessun tentativo di lettura reale"}
              </span>
            </div>
          </div>
          {discoveryRun.warnings?.length > 0 && (
            <div className="text-amber-500 text-xs mb-2">{discoveryRun.warnings.join(" · ")}</div>
          )}
          {discoveryRun.status === "COMPLETATO" && (
            discoveryRun.real_fetch ? (
              <div className="text-xs text-muted-foreground space-y-1" data-testid="discovery-real-fetch">
                <div>
                  Fonte: <a href={discoveryRun.real_fetch.url} target="_blank" rel="noreferrer"
                    className="underline hover:text-foreground">{discoveryRun.real_fetch.url}</a>
                  {discoveryRun.real_fetch.acquisito_il ? ` · acquisita il ${discoveryRun.real_fetch.acquisito_il}` : ""}
                  {discoveryRun.real_fetch.via_rendering_js ? " · via rendering JS (fallback)" : ""}
                </div>
                <div data-testid="discovery-social-found">
                  {discoveryRun.real_fetch.social_links?.length > 0
                    ? `Collegamenti social individuati sulla pagina esaminata: ${discoveryRun.real_fetch.social_links.join(", ")}`
                    : "Nessun collegamento social trovato nella pagina esaminata (non significa che l'azienda non abbia social)."}
                </div>
              </div>
            ) : (
              <div className="text-xs text-muted-foreground" data-testid="discovery-no-real-fetch">
                Nessuna pagina web è stata letta realmente in questa ricerca (permesso Discovery non concesso in
                quel momento): tono e pubblico sopra restano una stima euristica, non un'estrazione dal sito.
              </div>
            )
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
        <div className="label-caps mb-1">Fact Ledger — profilo aziendale condiviso</div>
        <div className="text-xs text-muted-foreground mb-3">
          "Estratto" = candidato letto da una fonte reale (mai una dichiarazione confermata dall'utente); "Estratto
          (euristica)" = stima automatica senza lettura reale, nessuna evidenza puntuale disponibile.
        </div>
        {factRows.length === 0 ? <Empty text="Nessun fatto registrato." /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground label-caps text-xs">
                  <th className="py-2 pr-4">Campo</th><th className="py-2 pr-4">Valore</th>
                  <th className="py-2 pr-4">Provenienza</th><th className="py-2 pr-4">Evidenza</th>
                  <th className="py-2 pr-4">Affidabilità</th>
                </tr>
              </thead>
              <tbody>
                {factRows.map((f) => {
                  const evidenze = f.evidence || [];
                  const ultima = evidenze.length > 0 ? evidenze[evidenze.length - 1] : null;
                  const provenienza = f.method === "DICHIARATO"
                    ? "Dichiarato dall'utente"
                    : evidenze.length > 0
                      ? `${METHOD_LABEL[f.method] || f.method} · con evidenza`
                      : `${METHOD_LABEL[f.method] || f.method} · euristica, senza evidenza`;
                  return (
                    <tr key={f.id} className="border-t border-border/40" data-testid={`fact-row-${f.field}`}>
                      <td className="py-2 pr-4 font-mono text-xs align-top">{f.field}</td>
                      <td className="py-2 pr-4 align-top">{f.value}</td>
                      <td className="py-2 pr-4 align-top text-xs" data-testid={`fact-provenance-${f.field}`}>
                        {provenienza}
                        <div className="text-muted-foreground">fonte: {f.source}</div>
                      </td>
                      <td className="py-2 pr-4 align-top text-xs max-w-xs" data-testid={`fact-evidence-${f.field}`}>
                        {ultima ? (
                          <div className="space-y-0.5">
                            <a href={ultima.url} target="_blank" rel="noreferrer"
                              className="underline hover:text-foreground break-all">{ultima.url}</a>
                            <div className="text-muted-foreground">acquisita il {ultima.acquisito_il}</div>
                            {ultima.estratto && (
                              <div className="text-muted-foreground italic">"{ultima.estratto.slice(0, 140)}{ultima.estratto.length > 140 ? "…" : ""}"</div>
                            )}
                          </div>
                        ) : (
                          <span className="text-muted-foreground" data-testid={`fact-no-evidence-${f.field}`}>
                            Nessuna evidenza puntuale disponibile{f.method === "DICHIARATO" ? "" : " (stima euristica)"}.
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-4 font-mono align-top">{Math.round((f.confidence || 0) * 100)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
