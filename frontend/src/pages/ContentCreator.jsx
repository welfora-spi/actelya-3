import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Plus, Sparkles, CheckCircle2, XCircle, RefreshCw, Link as LinkIcon } from "lucide-react";
import { ContentItemBody, ContentItemStatusNotices } from "@/components/content-items/ContentItemBody";

const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 10, pages: 0 };
const CONTENT_TYPES = [
  "post_social", "caption", "carosello_testuale", "reel_script", "storyboard", "video_script",
  "voiceover_script", "ad_copy", "headline", "cta", "landing_copy", "email", "newsletter",
  "articolo_blog", "contenuto_seo", "comunicazione_commerciale", "offerta", "contenuto_informativo",
  "brief_immagine", "brief_video", "brief_audio",
];
const MEDIA_DEPENDENT = new Set(["storyboard", "video_script", "voiceover_script", "brief_video", "brief_immagine"]);

function Pager({ data, onPage }) {
  if (!data || data.pages <= 1) return null;
  return (
    <div className="flex items-center justify-between mt-2 text-[11px] text-muted-foreground">
      <span>{`Pagina ${data.page} di ${data.pages}`}</span>
      <div className="flex gap-1.5">
        <button disabled={data.page <= 1} onClick={() => onPage(data.page - 1)}
          className="rounded-sm border border-border px-2 py-0.5 disabled:opacity-40">Precedente</button>
        <button disabled={data.page >= data.pages} onClick={() => onPage(data.page + 1)}
          className="rounded-sm border border-border px-2 py-0.5 disabled:opacity-40">Successiva</button>
      </div>
    </div>
  );
}

export default function ContentCreator() {
  const [items, setItems] = useState(EMPTY_PAGE);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [deepLinkError, setDeepLinkError] = useState(null);
  const { hasRole } = useAuth();
  const canApprove = hasRole("ADMIN") || hasRole("APPROVATORE");
  const canGenerate = hasRole("ADMIN");
  const [searchParams] = useSearchParams();

  const loadItems = useCallback((page = 1) => {
    api.get("/content-creator/items", { params: { page, page_size: 10 } })
      .then((r) => setItems(r.data)).catch(() => {});
  }, []);

  useEffect(() => { loadItems(); }, [loadItems]);

  // Collegamento diretto da Risultati/dettaglio piano (?item=<id>): apre
  // subito il contenuto corretto, in sola lettura — nessuna azione avviata
  // automaticamente. Un id inesistente o non raggiungibile mostra un
  // avviso esplicito, mai una scheda vuota.
  useEffect(() => {
    const itemId = searchParams.get("item");
    if (!itemId) return;
    setDeepLinkError(null);
    api.get(`/content-creator/items/${itemId}`)
      .then((r) => setSelected(r.data))
      .catch(() => setDeepLinkError(itemId));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get("item")]);

  const refreshSelected = async (id) => {
    const { data } = await api.get(`/content-creator/items/${id}`);
    setSelected(data);
  };

  // ---------- Creazione ----------
  const [form, setForm] = useState({ objective: "", channel: "generico", funnel_stage: "MOFU", content_type: "", brief: "" });
  const createItems = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/content-creator/items", {
        objective: form.objective, channel: form.channel, funnel_stage: form.funnel_stage,
        content_type: form.content_type || null, brief: form.brief,
      });
      toast.success(`Deciso: ${data.content_types_decisi.join(", ")}`);
      setCreating(false); loadItems();
      if (data.items?.[0]) setSelected(data.items[0]);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  // ---------- Azioni sull'item selezionato ----------
  const generate = async () => {
    setBusy(true);
    try {
      await api.post(`/content-creator/items/${selected.id}/generate`, { confirm: true });
      toast.success("Generazione completata.");
      await refreshSelected(selected.id); loadItems();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const approve = async (approveFlag) => {
    setBusy(true);
    try {
      await api.post(`/content-creator/items/${selected.id}/approve`, { approve: approveFlag, note: "" });
      toast.success(approveFlag ? "Contenuto approvato." : "Contenuto rifiutato.");
      await refreshSelected(selected.id); loadItems();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const requestRevision = async () => {
    const note = window.prompt("Cosa va cambiato?");
    if (!note || !note.trim()) return;
    setBusy(true);
    try {
      await api.post(`/content-creator/items/${selected.id}/request-revision`, { note });
      toast.success("Modifica richiesta: torna in bozza.");
      await refreshSelected(selected.id); loadItems();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const resolveUncertain = async () => {
    setBusy(true);
    try {
      await api.post(`/content-creator/items/${selected.id}/resolve-uncertain`, { note: "" });
      toast.success("Esito incerto risolto: si può rigenerare.");
      await refreshSelected(selected.id); loadItems();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const linkMedia = async () => {
    const kind = MEDIA_DEPENDENT.has(selected.content_type) && ["brief_immagine"].includes(selected.content_type) ? "flyer" : "reel";
    const project_id = window.prompt(`ID progetto ${kind} già creato in laboratorio (Video creator/Creative designer):`);
    if (!project_id || !project_id.trim()) return;
    setBusy(true);
    try {
      await api.post(`/content-creator/items/${selected.id}/link-media`, { kind, project_id });
      toast.success("Progetto multimediale collegato.");
      await refreshSelected(selected.id); loadItems();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const syncMedia = async () => {
    setBusy(true);
    try {
      await api.post(`/content-creator/items/${selected.id}/sync-media`);
      toast.info("Stato asset aggiornato.");
      await refreshSelected(selected.id); loadItems();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title="Content Creator — laboratorio"
        subtitle="Decide cosa produrre, genera davvero il contenuto (grounded sul Fact Ledger) e lo porta fino al deliverable finale."
        actions={
          <button data-testid="new-content-item" onClick={() => setCreating(true)}
            className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm hover:opacity-90 transition-colors duration-200">
            <Plus className="w-4 h-4" /> Nuova richiesta
          </button>
        } />

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">
        <div>
          <h2 className="font-display text-sm label-caps mb-2">Contenuti</h2>
          {items.items.length === 0 ? <Empty text="Nessun contenuto ancora." /> : (
            <>
              <div className="space-y-2" data-testid="content-items-list">
                {items.items.map((it) => (
                  <Card key={it.id} className={`p-3 cursor-pointer ${selected?.id === it.id ? "border-primary" : ""}`}
                    onClick={() => setSelected(it)}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs truncate">{it.content_type}</span>
                      <StatusBadge status={it.status} />
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1 truncate">{it.objective}</div>
                  </Card>
                ))}
              </div>
              <Pager data={items} onPage={loadItems} />
            </>
          )}
        </div>

        <div>
          {deepLinkError && !selected && (
            <div className="mb-3 text-xs rounded-sm border border-red-500/30 bg-red-500/10 text-red-400 px-3 py-2"
              data-testid="content-item-deep-link-error">
              Contenuto {deepLinkError} non disponibile: potrebbe essere stato rimosso o non è raggiungibile.
            </div>
          )}
          {!selected ? <Empty text="Seleziona o crea una richiesta di contenuto." /> : (
            <Card className="p-5">
              <div className="flex items-center justify-between flex-wrap gap-3 mb-2">
                <div>
                  <h3 className="font-display text-lg font-medium">{selected.content_type}</h3>
                  <div className="text-xs text-muted-foreground mt-1">Canale: {selected.channel} · Fase: {selected.funnel_stage}</div>
                </div>
                <StatusBadge status={selected.status} />
              </div>
              <div className="text-xs text-muted-foreground mb-4">{selected.motivazione_tipo}</div>

              <div className="flex flex-wrap gap-2 mb-4">
                {selected.status === "BOZZA" && canGenerate && (
                  <button data-testid="content-generate-btn" onClick={generate} disabled={busy}
                    className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-1.5 text-sm hover:opacity-90">
                    <Sparkles className="w-3.5 h-3.5" /> Genera
                  </button>
                )}
                {selected.status === "ESITO_INCERTO" && canGenerate && (
                  <button onClick={resolveUncertain} disabled={busy}
                    className="flex items-center gap-1.5 border border-border rounded-sm px-3 py-1.5 text-sm hover:bg-muted/50">
                    <RefreshCw className="w-3.5 h-3.5" /> Risolvi esito incerto
                  </button>
                )}
                {selected.status === "IN_ATTESA_APPROVAZIONE" && canApprove && (
                  <>
                    <button data-testid="content-approve-btn" onClick={() => approve(true)} disabled={busy}
                      className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-1.5 text-sm hover:opacity-90">
                      <CheckCircle2 className="w-3.5 h-3.5" /> Approva
                    </button>
                    <button onClick={() => approve(false)} disabled={busy}
                      className="flex items-center gap-1.5 border border-red-500/40 text-red-400 rounded-sm px-3 py-1.5 text-sm hover:bg-red-500/10">
                      <XCircle className="w-3.5 h-3.5" /> Rifiuta
                    </button>
                  </>
                )}
                {["IN_ATTESA_APPROVAZIONE", "RIFIUTATO", "BLOCCATO", "APPROVATO", "IN_ATTESA_ASSET"].includes(selected.status) && (
                  <button onClick={requestRevision} disabled={busy}
                    className="border border-border rounded-sm px-3 py-1.5 text-sm hover:bg-muted/50">Richiedi modifica</button>
                )}
                {selected.status === "IN_ATTESA_ASSET" && (
                  <>
                    <button onClick={linkMedia} disabled={busy}
                      className="flex items-center gap-1.5 border border-border rounded-sm px-3 py-1.5 text-sm hover:bg-muted/50">
                      <LinkIcon className="w-3.5 h-3.5" /> Collega progetto multimediale
                    </button>
                    {selected.media_link && (
                      <button onClick={syncMedia} disabled={busy}
                        className="flex items-center gap-1.5 border border-border rounded-sm px-3 py-1.5 text-sm hover:bg-muted/50">
                        <RefreshCw className="w-3.5 h-3.5" /> Aggiorna stato asset
                      </button>
                    )}
                  </>
                )}
              </div>

              <ContentItemStatusNotices item={selected} />
              {selected.content && <ContentItemBody content={selected.content} />}
            </Card>
          )}
        </div>
      </div>

      {creating && (
        <Modal onClose={() => setCreating(false)}>
          <h3 className="font-display text-lg font-medium mb-3">Nuova richiesta di contenuto</h3>
          <div className="space-y-3">
            <Field label="Obiettivo" value={form.objective} onChange={(v) => setForm({ ...form, objective: v })} />
            <Field label="Canale" value={form.channel} onChange={(v) => setForm({ ...form, channel: v })} />
            <div>
              <div className="label-caps mb-1">Fase di funnel</div>
              <select value={form.funnel_stage} onChange={(e) => setForm({ ...form, funnel_stage: e.target.value })}
                className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm">
                <option value="TOFU">TOFU</option>
                <option value="MOFU">MOFU</option>
                <option value="BOFU">BOFU</option>
                <option value="RETENTION">RETENTION</option>
              </select>
            </div>
            <div>
              <div className="label-caps mb-1">Tipo di contenuto (lascia vuoto: decide l'agente)</div>
              <select value={form.content_type} onChange={(e) => setForm({ ...form, content_type: e.target.value })}
                className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm">
                <option value="">— lascia decidere l'agente —</option>
                {CONTENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <Field label="Brief aggiuntivo" value={form.brief} onChange={(v) => setForm({ ...form, brief: v })} />
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={createItems} disabled={busy || !form.objective.trim()}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">Crea</button>
            <button onClick={() => setCreating(false)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Field({ label, value, onChange }) {
  return (
    <div>
      <div className="label-caps mb-1">{label}</div>
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none" />
    </div>
  );
}
function Modal({ children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-sm p-6 w-full max-w-2xl shadow-xl max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>{children}</div>
    </div>
  );
}
