import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Plus, KeyRound, Trash2, Zap } from "lucide-react";

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

export default function Connections() {
  const [ai, setAi] = useState([]);
  const [integrations, setIntegrations] = useState([]);
  const [form, setForm] = useState(null);
  const [testResult, setTestResult] = useState(null);
  const { hasRole } = useAuth();
  const isAdmin = hasRole("ADMIN");

  const load = useCallback(() => {
    api.get("/connections/ai").then((r) => setAi(r.data)).catch(() => {});
    api.get("/connections/integrations").then((r) => setIntegrations(r.data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

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
    try { const { data } = await api.post(`/connections/ai/${c.id}/test-preview`); setPreview({ conn: c, ...data }); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const confirmTest = async () => {
    try {
      const { data } = await api.post(`/connections/ai/${preview.conn.id}/test-confirm`, { confirm: true });
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
                <div className="mt-3 text-xs font-mono border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 rounded-sm px-3 py-2">
                  {testResult.mode}: {testResult.effective_model} · {testResult.tokens_input}/{testResult.tokens_output} tok · ${testResult.cost} · {testResult.latency_ms}ms
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
            <Line l="Token stimati" v={preview.estimated_tokens} />
            <Line l="Costo possibile" v={`$${preview.possible_cost}`} />
            <Line l="Modalità" v={preview.mode} />
          </div>
          <p className="text-xs text-muted-foreground mt-3">{preview.message}</p>
          <div className="flex gap-2 mt-4">
            <button data-testid="test-confirm" onClick={confirmTest} className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm">Conferma ed esegui una chiamata minima</button>
            <button onClick={() => setPreview(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
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
