import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Plus, KeyRound, Trash2, Zap, Video, Share2 } from "lucide-react";

const PROVIDERS = [
  { v: "requesty", l: "Requesty" },
  { v: "anthropic", l: "Anthropic diretto" },
  { v: "openai", l: "OpenAI" },
  { v: "openai_compatible", l: "OpenAI-compatibile" },
];

const EMPTY = {
  name: "", provider_type: "openai", base_url: "", api_key: "", logical_model: "",
  effective_model: "", timeout: 60, max_tokens: 2000, max_budget_per_task: 1,
  daily_budget: 10, active: true, priority: 1,
};

const VIDEO_EMPTY = {
  name: "", provider_type: "runway", api_key: "", effective_model: "gen4.5",
  default_ratio: "720:1280", max_cost_per_generation: 20, timeout: 60, active: true, priority: 1,
};

const META_MODES = [{ v: "dry_run", l: "Simulata (dry-run)" }, { v: "real", l: "Reale" }];
const META_EMPTY = {
  name: "", mode: "dry_run", access_token: "", app_id: "", app_secret: "",
  page_id: "", instagram_business_account_id: "", graph_api_version: "v21.0", active: true,
};

export default function Connections() {
  const [ai, setAi] = useState([]);
  const [integrations, setIntegrations] = useState([]);
  const [video, setVideo] = useState([]);
  const [videoForm, setVideoForm] = useState(null);
  const [videoTestResult, setVideoTestResult] = useState(null);
  const [videoPreview, setVideoPreview] = useState(null);
  const [meta, setMeta] = useState([]);
  const [metaForm, setMetaForm] = useState(null);
  const [metaTestResult, setMetaTestResult] = useState(null);
  const [metaPreview, setMetaPreview] = useState(null);
  const [form, setForm] = useState(null);
  const [testResult, setTestResult] = useState(null);
  const { hasRole } = useAuth();
  const isAdmin = hasRole("ADMIN");

  const load = useCallback(() => {
    api.get("/connections/ai").then((r) => setAi(r.data)).catch(() => {});
    api.get("/connections/integrations").then((r) => setIntegrations(r.data)).catch(() => {});
    api.get("/video-connections").then((r) => setVideo(r.data)).catch(() => {});
    api.get("/meta-connections").then((r) => setMeta(r.data)).catch(() => {});
  }, []);

  const saveMeta = async () => {
    try {
      const payload = { ...metaForm };
      if (metaForm.id && !payload.access_token) delete payload.access_token;
      if (metaForm.id && !payload.app_secret) delete payload.app_secret;
      if (metaForm.id) await api.put(`/meta-connections/${metaForm.id}`, payload);
      else await api.post("/meta-connections", payload);
      toast.success("Connessione Meta salvata (nessun test automatico)");
      setMetaForm(null); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const delMeta = async (id) => {
    try { await api.delete(`/meta-connections/${id}`); toast.success("Eliminata"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const openMetaTest = (c) => {
    setMetaTestResult(null);
    setMetaPreview({ conn: c, provider: "meta", message: "Verrà eseguita una verifica reale di sola lettura (token, Pagina, eventuale account Instagram collegato): nessuna pubblicazione, nessun costo." });
  };
  const confirmMetaTest = async () => {
    try {
      const { data } = await api.post(`/meta-connections/${metaPreview.conn.id}/test`, { confirm: true });
      setMetaTestResult(data); setMetaPreview(null); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  useEffect(() => { load(); }, [load]);

  const saveVideo = async () => {
    try {
      const payload = { ...videoForm };
      if (videoForm.id && !payload.api_key) delete payload.api_key;
      if (videoForm.id) await api.put(`/video-connections/${videoForm.id}`, payload);
      else await api.post("/video-connections", payload);
      toast.success("Connessione video salvata (nessun test automatico)");
      setVideoForm(null); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const delVideo = async (id) => {
    try { await api.delete(`/video-connections/${id}`); toast.success("Eliminata"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const openVideoTest = (c) => {
    setVideoTestResult(null);
    setVideoPreview({ conn: c, provider: "runway", effective_model: c.effective_model,
      message: "Verrà eseguita UNA chiamata reale a Runway (organization.retrieve: sola lettura del saldo crediti, costo $0, nessuna generazione video)." });
  };
  const confirmVideoTest = async () => {
    try {
      const { data } = await api.post(`/video-connections/${videoPreview.conn.id}/test`, { confirm: true });
      setVideoTestResult(data); setVideoPreview(null); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const save = async () => {
    try {
      const payload = { ...form };
      if (form.id && !payload.api_key) delete payload.api_key;
      if (form.id) await api.put(`/connections/ai/${form.id}`, payload);
      else await api.post("/connections/ai", payload);
      toast.success("Connessione salvata (nessun test automatico)");
      setForm(null); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const del = async (id) => {
    try { await api.delete(`/connections/ai/${id}`); toast.success("Eliminata"); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const [preview, setPreview] = useState(null);
  const openTest = async (c) => {
    setTestResult(null);
    if (c.provider_type === "requesty") {
      // Nessuna anteprima simulata per Requesty: unica chiamata REALE, mai automatica.
      setPreview({ conn: c, reale: true, provider: "requesty", effective_model: c.effective_model,
        mode: "REALE", message: "Verrà eseguita UNA chiamata reale a Requesty (costo minimo, prompt fisso di diagnostica)." });
      return;
    }
    try { const { data } = await api.post(`/connections/ai/${c.id}/test-preview`); setPreview({ conn: c, ...data }); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const confirmTest = async () => {
    try {
      const path = preview.reale ? "test-real" : "test-confirm";
      const { data } = await api.post(`/connections/ai/${preview.conn.id}/${path}`, { confirm: true });
      setTestResult(data); setPreview(null); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div>
      <PageHeader title="Connessioni e API"
        subtitle="Le API key sono cifrate lato server, mai restituite in chiaro. Il test non parte automaticamente al salvataggio."
        actions={isAdmin && <button data-testid="add-ai-conn" onClick={() => { setForm({ ...EMPTY }); setTestResult(null); }}
          className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm hover:opacity-90 active:scale-[0.98] transition-colors duration-200"><Plus className="w-4 h-4" /> Provider AI</button>} />

      <h2 className="font-display text-lg font-medium mb-3">Provider AI</h2>
      {ai.length === 0 ? <Empty text="Nessun provider AI configurato." /> : (
        <div className="space-y-2" data-testid="ai-connections-list">
          {ai.map((c) => (
            <Card key={c.id} className="p-4">
              <div className="flex items-center justify-between gap-4 flex-wrap">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-display font-medium">{c.name}</span>
                    <span className="text-[10px] font-mono border border-border rounded-sm px-1.5 py-0.5">{c.provider_type}</span>
                    {c.verified ? <StatusBadge status="VERIFICATA" /> : <StatusBadge status={c.has_key ? "CONFIGURATA" : "NON_CONFIGURATA"} />}
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-2 text-xs">
                    <F l="Modello logico" v={c.logical_model || "—"} />
                    <F l="API key" v={c.api_key_masked || "—"} mono />
                    <F l="Budget/task" v={`$${c.max_budget_per_task}`} mono />
                    <F l="Ultimo test" v={c.last_test_result || "mai"} />
                  </div>
                </div>
                {isAdmin && (
                  <div className="flex gap-2 shrink-0">
                    <button data-testid={`test-${c.id}`} onClick={() => openTest(c)} className="flex items-center gap-1 rounded-sm border border-amber-500/40 text-amber-400 px-3 py-1.5 text-sm hover:bg-amber-500/10 transition-colors duration-200"><Zap className="w-3.5 h-3.5" /> TESTA</button>
                    <button onClick={() => { setForm({ ...c, api_key: "" }); }} className="rounded-sm border border-border px-3 py-1.5 text-sm hover:bg-muted/50 transition-colors duration-200">Modifica</button>
                    <button data-testid={`del-${c.id}`} onClick={() => del(c.id)} className="rounded-sm border border-red-500/40 text-red-400 px-2 py-1.5 hover:bg-red-500/10 transition-colors duration-200"><Trash2 className="w-4 h-4" /></button>
                  </div>
                )}
              </div>
              {testResult && preview === null && (
                testResult.esito !== undefined ? (
                  <div className={`mt-3 text-xs font-mono border rounded-sm px-3 py-2 ${testResult.esito === "OK" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" : "border-red-500/30 bg-red-500/10 text-red-400"}`}>
                    {testResult.mode} {testResult.esito}: {testResult.esito === "OK"
                      ? `${testResult.modello_effettivo} · ${testResult.input_tokens}/${testResult.output_tokens} tok · ${testResult.latenza_ms}ms`
                      : `[${testResult.codice_errore}] ${testResult.messaggio}`}
                  </div>
                ) : (
                  <div className="mt-3 text-xs font-mono border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 rounded-sm px-3 py-2">
                    {testResult.mode}: {testResult.effective_model} · {testResult.tokens_input}/{testResult.tokens_output} tok · ${testResult.cost} · {testResult.latency_ms}ms
                  </div>
                )
              )}
            </Card>
          ))}
        </div>
      )}

      <h2 className="font-display text-lg font-medium mt-8 mb-3 flex items-center justify-between">
        Video generativo
        {isAdmin && <button data-testid="add-video-conn" onClick={() => { setVideoForm({ ...VIDEO_EMPTY }); setVideoTestResult(null); }}
          className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm hover:opacity-90 active:scale-[0.98] transition-colors duration-200"><Plus className="w-4 h-4" /> Provider video</button>}
      </h2>
      {video.length === 0 ? <Empty text="Nessun provider video configurato." /> : (
        <div className="space-y-2" data-testid="video-connections-list">
          {video.map((c) => (
            <Card key={c.id} className="p-4">
              <div className="flex items-center justify-between gap-4 flex-wrap">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-display font-medium">{c.name}</span>
                    <span className="text-[10px] font-mono border border-border rounded-sm px-1.5 py-0.5">{c.provider_type}</span>
                    {c.verified ? <StatusBadge status="VERIFICATA" /> : <StatusBadge status={c.has_key ? "CONFIGURATA" : "NON_CONFIGURATA"} />}
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-2 text-xs">
                    <F l="Modello effettivo" v={c.effective_model || "—"} />
                    <F l="API key" v={c.api_key_masked || "—"} mono />
                    <F l="Tetto/generazione" v={`${c.max_cost_per_generation} crediti`} mono />
                    <F l="Saldo (ultimo test)" v={c.credit_balance_ultima_verifica ?? "—"} mono />
                  </div>
                </div>
                {isAdmin && (
                  <div className="flex gap-2 shrink-0">
                    <button data-testid={`test-video-${c.id}`} onClick={() => openVideoTest(c)} className="flex items-center gap-1 rounded-sm border border-amber-500/40 text-amber-400 px-3 py-1.5 text-sm hover:bg-amber-500/10 transition-colors duration-200"><Zap className="w-3.5 h-3.5" /> TESTA</button>
                    <button onClick={() => { setVideoForm({ ...c, api_key: "" }); }} className="rounded-sm border border-border px-3 py-1.5 text-sm hover:bg-muted/50 transition-colors duration-200">Modifica</button>
                    <button data-testid={`del-video-${c.id}`} onClick={() => delVideo(c.id)} className="rounded-sm border border-red-500/40 text-red-400 px-2 py-1.5 hover:bg-red-500/10 transition-colors duration-200"><Trash2 className="w-4 h-4" /></button>
                  </div>
                )}
              </div>
              {videoTestResult && videoPreview === null && (
                <div className={`mt-3 text-xs font-mono border rounded-sm px-3 py-2 ${videoTestResult.esito === "OK" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" : "border-red-500/30 bg-red-500/10 text-red-400"}`}>
                  {videoTestResult.mode} {videoTestResult.esito}: {videoTestResult.esito === "OK"
                    ? `saldo ${videoTestResult.credit_balance} crediti · ${videoTestResult.latenza_ms}ms`
                    : `[${videoTestResult.codice_errore}] ${videoTestResult.messaggio}`}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      <h2 className="font-display text-lg font-medium mt-8 mb-3 flex items-center justify-between">
        Social (Meta — Facebook/Instagram)
        {isAdmin && <button data-testid="add-meta-conn" onClick={() => { setMetaForm({ ...META_EMPTY }); setMetaTestResult(null); }}
          className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm hover:opacity-90 active:scale-[0.98] transition-colors duration-200"><Plus className="w-4 h-4" /> Connessione Meta</button>}
      </h2>
      {meta.length === 0 ? <Empty text="Nessuna connessione Meta configurata: la pubblicazione social resta in modalità simulata." /> : (
        <div className="space-y-2" data-testid="meta-connections-list">
          {meta.map((c) => (
            <Card key={c.id} className="p-4">
              <div className="flex items-center justify-between gap-4 flex-wrap">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-display font-medium">{c.name}</span>
                    <span className="text-[10px] font-mono border border-border rounded-sm px-1.5 py-0.5">{c.mode}</span>
                    <StatusBadge status={c.facebook_status} />
                    <StatusBadge status={c.instagram_status} />
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-2 text-xs">
                    <F l="Pagina Facebook" v={c.page_name || c.page_id || "—"} />
                    <F l="Account Instagram" v={c.instagram_username || c.instagram_business_account_id || "—"} />
                    <F l="Access token" v={c.access_token_masked || "—"} mono />
                    <F l="Ultimo test" v={c.last_test_result || "mai"} />
                  </div>
                </div>
                {isAdmin && (
                  <div className="flex gap-2 shrink-0">
                    <button data-testid={`test-meta-${c.id}`} onClick={() => openMetaTest(c)} className="flex items-center gap-1 rounded-sm border border-amber-500/40 text-amber-400 px-3 py-1.5 text-sm hover:bg-amber-500/10 transition-colors duration-200"><Zap className="w-3.5 h-3.5" /> TESTA</button>
                    <button onClick={() => { setMetaForm({ ...c, access_token: "", app_secret: "" }); }} className="rounded-sm border border-border px-3 py-1.5 text-sm hover:bg-muted/50 transition-colors duration-200">Modifica</button>
                    <button data-testid={`del-meta-${c.id}`} onClick={() => delMeta(c.id)} className="rounded-sm border border-red-500/40 text-red-400 px-2 py-1.5 hover:bg-red-500/10 transition-colors duration-200"><Trash2 className="w-4 h-4" /></button>
                  </div>
                )}
              </div>
              {metaTestResult && metaPreview === null && metaTestResult.id === c.id && (
                <div className={`mt-3 text-xs font-mono border rounded-sm px-3 py-2 ${metaTestResult.facebook_status === "CONNECTED" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" : "border-red-500/30 bg-red-500/10 text-red-400"}`}>
                  Facebook: {metaTestResult.facebook_status} · Instagram: {metaTestResult.instagram_status}
                  {metaTestResult.dettagli_errore && <> · {metaTestResult.dettagli_errore}</>}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      <h2 className="font-display text-lg font-medium mt-8 mb-3">Integrazioni (predisposte, non ancora collegate)</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2" data-testid="integrations-list">
        {integrations.map((i) => (
          <Card key={i.key} className="p-3 flex items-center justify-between">
            <div>
              <div className="text-sm">{i.label}</div>
              <div className="text-[11px] text-muted-foreground">{i.note}</div>
            </div>
            <StatusBadge status={i.status} />
          </Card>
        ))}
      </div>

      {/* Test preview modal */}
      {preview && (
        <Modal onClose={() => setPreview(null)}>
          <h3 className="font-display text-lg font-medium mb-2">Conferma test connessione</h3>
          <div className="space-y-1.5 text-sm">
            <Line l="Provider" v={preview.provider} />
            <Line l="Modello" v={preview.effective_model || preview.logical_model || "—"} />
            {!preview.reale && <Line l="Token stimati" v={preview.estimated_tokens} />}
            {!preview.reale && <Line l="Costo possibile" v={`$${preview.possible_cost}`} />}
            <Line l="Modalità" v={preview.mode} />
          </div>
          <p className="text-xs text-muted-foreground mt-3">{preview.message}</p>
          <div className="flex gap-2 mt-4">
            <button data-testid="test-confirm" onClick={confirmTest} className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm">Conferma ed esegui una chiamata minima</button>
            <button onClick={() => setPreview(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {/* Video test confirm modal */}
      {videoPreview && (
        <Modal onClose={() => setVideoPreview(null)}>
          <h3 className="font-display text-lg font-medium mb-2">Conferma test connessione video</h3>
          <div className="space-y-1.5 text-sm">
            <Line l="Provider" v={videoPreview.provider} />
            <Line l="Modello" v={videoPreview.effective_model || "—"} />
          </div>
          <p className="text-xs text-muted-foreground mt-3">{videoPreview.message}</p>
          <div className="flex gap-2 mt-4">
            <button data-testid="test-video-confirm" onClick={confirmVideoTest} className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm">Conferma ed esegui la verifica reale</button>
            <button onClick={() => setVideoPreview(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {/* Video form modal */}
      {videoForm && (
        <Modal onClose={() => setVideoForm(null)}>
          <h3 className="font-display text-lg font-medium mb-4 flex items-center gap-2"><Video className="w-4 h-4" /> {videoForm.id ? "Modifica" : "Nuovo"} provider video</h3>
          <div className="grid grid-cols-2 gap-3">
            <Inp l="Nome connessione" v={videoForm.name} on={(v) => setVideoForm({ ...videoForm, name: v })} testid="video-conn-name" />
            <Inp l="Modello effettivo" v={videoForm.effective_model} on={(v) => setVideoForm({ ...videoForm, effective_model: v })} />
            <Inp l={videoForm.id ? "API key (lascia vuoto per non cambiare)" : "API key"} v={videoForm.api_key} on={(v) => setVideoForm({ ...videoForm, api_key: v })} type="password" testid="video-conn-apikey" full />
            <Inp l="Formato (ratio)" v={videoForm.default_ratio} on={(v) => setVideoForm({ ...videoForm, default_ratio: v })} />
            <Inp l="Tetto costo/generazione (crediti)" v={videoForm.max_cost_per_generation} on={(v) => setVideoForm({ ...videoForm, max_cost_per_generation: +v })} type="number" />
            <Inp l="Timeout (s)" v={videoForm.timeout} on={(v) => setVideoForm({ ...videoForm, timeout: +v })} type="number" />
            <Inp l="Priorità" v={videoForm.priority} on={(v) => setVideoForm({ ...videoForm, priority: +v })} type="number" />
          </div>
          <p className="text-xs text-muted-foreground mt-3">Il tetto di costo è in CREDITI Runway (non $): Runway non converte i crediti in valuta via API. Sopra il tetto, la generazione viene bloccata e il task annullato automaticamente.</p>
          <div className="flex gap-2 mt-4">
            <button data-testid="video-conn-save" onClick={saveVideo} className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm">Salva (nessun test automatico)</button>
            <button onClick={() => setVideoForm(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {/* Meta test confirm modal */}
      {metaPreview && (
        <Modal onClose={() => setMetaPreview(null)}>
          <h3 className="font-display text-lg font-medium mb-2">Conferma verifica connessione Meta</h3>
          <p className="text-xs text-muted-foreground mt-1">{metaPreview.message}</p>
          <div className="flex gap-2 mt-4">
            <button data-testid="test-meta-confirm" onClick={confirmMetaTest} className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm">Conferma ed esegui la verifica reale</button>
            <button onClick={() => setMetaPreview(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {/* Meta form modal */}
      {metaForm && (
        <Modal onClose={() => setMetaForm(null)}>
          <h3 className="font-display text-lg font-medium mb-4 flex items-center gap-2"><Share2 className="w-4 h-4" /> {metaForm.id ? "Modifica" : "Nuova"} connessione Meta</h3>
          <div className="grid grid-cols-2 gap-3">
            <Inp l="Nome connessione" v={metaForm.name} on={(v) => setMetaForm({ ...metaForm, name: v })} testid="meta-conn-name" />
            <Sel l="Modalità" v={metaForm.mode} opts={META_MODES} on={(v) => setMetaForm({ ...metaForm, mode: v })} />
            <Inp l={metaForm.id ? "Access token (lascia vuoto per non cambiare)" : "Access token (Pagina/Utente)"} v={metaForm.access_token} on={(v) => setMetaForm({ ...metaForm, access_token: v })} type="password" testid="meta-conn-token" full />
            <Inp l="Facebook Page ID" v={metaForm.page_id} on={(v) => setMetaForm({ ...metaForm, page_id: v })} />
            <Inp l="Instagram Business Account ID" v={metaForm.instagram_business_account_id} on={(v) => setMetaForm({ ...metaForm, instagram_business_account_id: v })} />
            <Inp l="App ID (opzionale)" v={metaForm.app_id} on={(v) => setMetaForm({ ...metaForm, app_id: v })} />
            <Inp l={metaForm.id ? "App secret (lascia vuoto per non cambiare)" : "App secret (opzionale)"} v={metaForm.app_secret} on={(v) => setMetaForm({ ...metaForm, app_secret: v })} type="password" />
            <Inp l="Versione Graph API" v={metaForm.graph_api_version} on={(v) => setMetaForm({ ...metaForm, graph_api_version: v })} />
          </div>
          <p className="text-xs text-muted-foreground mt-3">L'Instagram Business Account ID viene anche rilevato automaticamente dal test se la Pagina lo ha già collegato. La pubblicazione reale resta comunque disponibile solo con REAL_EXTERNAL_ACTIONS abilitato lato server.</p>
          <div className="flex gap-2 mt-4">
            <button data-testid="meta-conn-save" onClick={saveMeta} className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm">Salva (nessun test automatico)</button>
            <button onClick={() => setMetaForm(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {/* AI form modal */}
      {form && (
        <Modal onClose={() => setForm(null)}>
          <h3 className="font-display text-lg font-medium mb-4 flex items-center gap-2"><KeyRound className="w-4 h-4" /> {form.id ? "Modifica" : "Nuovo"} provider AI</h3>
          <div className="grid grid-cols-2 gap-3">
            <Inp l="Nome connessione" v={form.name} on={(v) => setForm({ ...form, name: v })} testid="conn-name" />
            <Sel l="Tipo provider" v={form.provider_type} opts={PROVIDERS} on={(v) => setForm({ ...form, provider_type: v })} />
            <Inp l="URL base" v={form.base_url} on={(v) => setForm({ ...form, base_url: v })} full />
            <Inp l="Modello logico" v={form.logical_model} on={(v) => setForm({ ...form, logical_model: v })} />
            <Inp l="Modello effettivo" v={form.effective_model} on={(v) => setForm({ ...form, effective_model: v })} />
            <Inp l={form.id ? "API key (lascia vuoto per non cambiare)" : "API key"} v={form.api_key} on={(v) => setForm({ ...form, api_key: v })} type="password" testid="conn-apikey" full />
            <Inp l="Timeout (s)" v={form.timeout} on={(v) => setForm({ ...form, timeout: +v })} type="number" />
            <Inp l="Max token" v={form.max_tokens} on={(v) => setForm({ ...form, max_tokens: +v })} type="number" />
            <Inp l="Budget max / task" v={form.max_budget_per_task} on={(v) => setForm({ ...form, max_budget_per_task: +v })} type="number" />
            <Inp l="Budget giornaliero" v={form.daily_budget} on={(v) => setForm({ ...form, daily_budget: +v })} type="number" />
            <Inp l="Priorità" v={form.priority} on={(v) => setForm({ ...form, priority: +v })} type="number" />
          </div>
          <div className="flex gap-2 mt-4">
            <button data-testid="conn-save" onClick={save} className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm">Salva (nessun test automatico)</button>
            <button onClick={() => setForm(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function F({ l, v, mono }) { return <div><div className="label-caps">{l}</div><div className={`mt-0.5 ${mono ? "font-mono" : ""}`}>{v}</div></div>; }
function Line({ l, v }) { return <div className="flex justify-between"><span className="text-muted-foreground">{l}</span><span className="font-mono">{v}</span></div>; }
function Modal({ children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-sm p-6 w-full max-w-2xl shadow-xl" onClick={(e) => e.stopPropagation()}>{children}</div>
    </div>
  );
}
function Inp({ l, v, on, type = "text", full, testid }) {
  return (
    <div className={full ? "col-span-2" : ""}>
      <label className="label-caps block mb-1">{l}</label>
      <input data-testid={testid} type={type} value={v} onChange={(e) => on(e.target.value)}
        className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none" />
    </div>
  );
}
function Sel({ l, v, on, opts }) {
  return (
    <div>
      <label className="label-caps block mb-1">{l}</label>
      <select value={v} onChange={(e) => on(e.target.value)}
        className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none">
        {opts.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
      </select>
    </div>
  );
}
