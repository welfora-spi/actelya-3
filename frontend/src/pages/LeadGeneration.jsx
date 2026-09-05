import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import {
  Plus, Upload, RefreshCw, CheckCircle2, Search, Download, Send, Users,
  Building2, AlertTriangle, Filter, ShieldAlert, Copy,
} from "lucide-react";

// Stesso elenco di backend/app/domains/leadgen/models.py::CANONICAL_FIELDS —
// duplicato di proposito (solo per popolare la select di mapping lato UI,
// nessuna logica): il backend resta l'unica fonte di verita' che valida.
const CANONICAL_FIELDS = [
  "ragione_sociale", "nome", "cognome", "ruolo", "email", "telefono", "sito", "dominio",
  "settore", "citta", "provincia", "regione", "paese", "dimensione", "fatturato",
  "dipendenti", "fonte", "consenso", "note", "stato_crm", "cliente_esistente", "ultima_interazione",
];

const JOB_ACTIVE = new Set(["UPLOADED", "PARSING", "NORMALIZED", "SCORING"]);
const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 10, pages: 0 };

function csv(list) { return (list || []).join(", "); }
function parseCsv(text) { return text.split(",").map((s) => s.trim()).filter(Boolean); }

// Il backend pagina TUTTE le liste (mai l'intero dataset caricato in un solo
// payload): questo componente e' condiviso da campagne/file/lead/duplicati,
// ognuno con la propria pagina corrente gestita dal chiamante.
function Pager({ data, onPage, itemLabel, pagerTestId }) {
  if (!data || data.pages <= 1) return null;
  const start = data.total === 0 ? 0 : (data.page - 1) * data.page_size + 1;
  const end = Math.min(data.page * data.page_size, data.total);
  // Testo costruito come UNA sola stringa (mai {valore} letterale adiacente
  // ad altro testo nello stesso nodo): un tool di sviluppo di questo
  // progetto avvolge ogni {espressione} JSX in uno <span>, il che
  // spezzerebbe un testo combinato dinamico+statico in nodi separati.
  const rangeText = data.total > 0
    ? `${start}–${end} di ${data.total}${itemLabel ? " " + itemLabel : ""}`
    : "Nessun risultato";
  const pageText = `Pagina ${data.page} di ${Math.max(1, data.pages)}`;
  return (
    <div className="flex items-center justify-between mt-2 text-[11px] text-muted-foreground" data-testid={pagerTestId}>
      <span data-testid={pagerTestId ? `${pagerTestId}-range` : undefined}>{rangeText}</span>
      <div className="flex gap-1.5">
        <button disabled={data.page <= 1} onClick={() => onPage(data.page - 1)}
          className="rounded-sm border border-border px-2 py-0.5 disabled:opacity-40">Precedente</button>
        <span className="px-1" data-testid={pagerTestId ? `${pagerTestId}-page` : undefined}>{pageText}</span>
        <button disabled={data.page >= data.pages} onClick={() => onPage(data.page + 1)}
          className="rounded-sm border border-border px-2 py-0.5 disabled:opacity-40">Successiva</button>
      </div>
    </div>
  );
}

export default function LeadGeneration() {
  const [searchParams] = useSearchParams();
  const [campaigns, setCampaigns] = useState(EMPTY_PAGE);
  const [selected, setSelected] = useState(null);
  const [files, setFiles] = useState(EMPTY_PAGE);
  const [job, setJob] = useState(null);
  const [leads, setLeads] = useState(EMPTY_PAGE);
  const [tipo, setTipo] = useState("aziende");
  const [qualFilter, setQualFilter] = useState("");
  const [duplicates, setDuplicates] = useState(EMPTY_PAGE);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [mappingFile, setMappingFile] = useState(null); // { file, mapping }
  const [searchResult, setSearchResult] = useState(null);
  const { hasRole } = useAuth();
  const canApprove = hasRole("ADMIN") || hasRole("APPROVATORE");

  const loadCampaigns = useCallback((page = 1) => {
    api.get("/leadgen/campaigns", { params: { page, page_size: 10 } })
      .then((r) => setCampaigns(r.data)).catch(() => {});
  }, []);
  const loadFiles = useCallback((page = 1) => {
    api.get("/leadgen/files", { params: { page, page_size: 10 } })
      .then((r) => setFiles(r.data)).catch(() => {});
  }, []);
  useEffect(() => { loadCampaigns(); loadFiles(); }, [loadCampaigns, loadFiles]);

  // Arrivo diretto da Sala Riunioni (brain -> capability leadgen): ?campaignId=
  useEffect(() => {
    const campaignId = searchParams.get("campaignId");
    if (campaignId) selectCampaign(campaignId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const loadLeads = useCallback(async (campaignId, t, q, page = 1) => {
    try {
      const { data } = await api.get(`/leadgen/campaigns/${campaignId}/leads`, {
        params: { tipo: t, qualification_status: q || undefined, page, page_size: 20 },
      });
      setLeads(data);
    } catch { setLeads(EMPTY_PAGE); }
  }, []);

  const loadDuplicates = useCallback(async (campaignId, page = 1) => {
    try {
      const { data } = await api.get(`/leadgen/campaigns/${campaignId}/duplicates`, { params: { page, page_size: 10 } });
      setDuplicates(data);
    } catch { setDuplicates(EMPTY_PAGE); }
  }, []);

  const selectCampaign = async (id) => {
    try {
      const { data } = await api.get(`/leadgen/campaigns/${id}`);
      setSelected(data); setSearchResult(null);
      loadLeads(id, tipo, qualFilter, 1);
      loadDuplicates(id, 1);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  useEffect(() => {
    if (selected) loadLeads(selected.id, tipo, qualFilter, 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tipo, qualFilter]);

  // ---------- Campagna ----------
  const [form, setForm] = useState({ name: "", channels: "", target_quantity: "", budget: "", deadline: "", settori_esclusi: "" });
  const createCampaign = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/leadgen/campaigns", {
        name: form.name, channels: parseCsv(form.channels),
        target_quantity: form.target_quantity ? Number(form.target_quantity) : null,
        budget: form.budget ? Number(form.budget) : null,
        deadline: form.deadline || null,
        icp: { settori_esclusi: parseCsv(form.settori_esclusi) },
      });
      toast.success("Campagna creata (bozza).");
      setCreating(false); setForm({ name: "", channels: "", target_quantity: "", budget: "", deadline: "", settori_esclusi: "" });
      loadCampaigns(); selectCampaign(data.id);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  // ---------- Upload file ----------
  const uploadFile = async (fileList) => {
    const file = fileList?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const body = new FormData();
      body.append("upload", file);
      const { data } = await api.post("/leadgen/files", body);
      toast.success(data.status === "VALIDATO" ? "File caricato e validato." : "File caricato.");
      loadFiles();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setUploading(false); }
  };

  // ---------- Mapping + import ----------
  const openMapping = (file) => {
    setMappingFile({ file, mapping: { ...(file.suggested_mapping || {}) } });
  };
  const updateMapping = (col, field) => {
    setMappingFile((m) => ({ ...m, mapping: { ...m.mapping, [col]: field || null } }));
  };
  const startImport = async () => {
    if (!selected || !mappingFile) return;
    setBusy(true);
    try {
      const cleanMapping = Object.fromEntries(
        Object.entries(mappingFile.mapping).filter(([, v]) => v)
      );
      const { data } = await api.post(
        `/leadgen/files/${mappingFile.file.id}/import`,
        { mapping: cleanMapping },
        { params: { campaign_id: selected.id } }
      );
      setJob(data);
      toast.success("Import avviato: elaborazione in corso.");
      setMappingFile(null);
      pollJob(data.id);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const pollJob = (jobId) => {
    const tick = async () => {
      try {
        const { data } = await api.get(`/leadgen/import-jobs/${jobId}`);
        setJob(data);
        if (JOB_ACTIVE.has(data.status)) { setTimeout(tick, 1500); return; }
        loadLeads(selected.id, tipo, qualFilter, 1);
        loadDuplicates(selected.id, 1);
        loadCampaigns();
        selectCampaign(selected.id);
      } catch { /* la prossima azione utente puo' comunque aggiornare la vista */ }
    };
    tick();
  };

  // ---------- Duplicati ----------
  const decideDuplicate = async (reviewId, action) => {
    setBusy(true);
    try {
      await api.post(`/leadgen/duplicates/${reviewId}/decision`, { action });
      toast.success(action === "MERGE" ? "Record uniti." : "Record mantenuti separati.");
      loadDuplicates(selected.id, duplicates.page);
      loadLeads(selected.id, tipo, qualFilter, leads.page);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  // ---------- Ricerca prospect ----------
  const runSearch = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/leadgen/search", { campaign_id: selected.id, query: selected.name });
      setSearchResult(data);
      loadLeads(selected.id, tipo, qualFilter, 1);
      toast.success(`Ricerca completata: ${data.created_record_ids.length} nuovi record.`);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  // ---------- Approvazione / export / handoff ----------
  const approveCampaign = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/leadgen/campaigns/${selected.id}/approve`, { approve: true });
      toast.success("Campagna approvata.");
      selectCampaign(data.id); loadCampaigns();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const exportCampaign = async (format) => {
    setBusy(true);
    try {
      const res = await api.post(`/leadgen/campaigns/${selected.id}/export`,
        { campaign_id: selected.id, format }, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url; a.download = `lead_${selected.id}.${format}`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Esportazione completata.");
      selectCampaign(selected.id); loadCampaigns();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const createHandoff = async () => {
    setBusy(true);
    try {
      await api.post(`/leadgen/campaigns/${selected.id}/handoff`);
      toast.success("Pacchetto di handoff preparato per gli altri agenti.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  // Il conteggio dei duplicati pendenti usa SEMPRE 'total' (mai
  // 'items.length', che rifletterebbe solo la pagina corrente): la campagna
  // puo' avere piu' duplicati di quanti ne mostri una singola pagina.
  const pendingDuplicates = duplicates.total;

  return (
    <div>
      <PageHeader title="Lead Generation — laboratorio"
        subtitle="Upload file, ricerca prospect, deduplica, compliance e scoring spiegabile. Nessun contatto reale automatico: ogni esportazione richiede approvazione."
        actions={
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 border border-border rounded-sm px-3 py-2 text-sm hover:bg-muted/50 cursor-pointer transition-colors duration-200">
              <Upload className="w-4 h-4" /> {uploading ? "Caricamento…" : "Carica file"}
              <input type="file" hidden disabled={uploading} accept=".csv,.tsv,.xlsx,.pdf,.docx,.txt"
                onChange={(e) => uploadFile(e.target.files)} />
            </label>
            <button data-testid="new-lead-campaign" onClick={() => setCreating(true)}
              className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm hover:opacity-90 active:scale-[0.98] transition-colors duration-200">
              <Plus className="w-4 h-4" /> Nuova campagna
            </button>
          </div>
        } />

      <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-6">
        <div>
          <h2 className="font-display text-sm label-caps mb-2">Campagne</h2>
          {campaigns.items.length === 0 ? <Empty text="Nessuna campagna ancora." /> : (
            <>
              <div className="space-y-2" data-testid="lead-campaigns-list">
                {campaigns.items.map((c) => (
                  <Card key={c.id} className={`p-3 cursor-pointer ${selected?.id === c.id ? "border-primary" : ""}`}
                    onClick={() => selectCampaign(c.id)}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm truncate">{c.name}</span>
                      <StatusBadge status={c.status} />
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1">
                      {(c.channels || []).join(", ") || "nessun canale"}
                    </div>
                  </Card>
                ))}
              </div>
              <Pager data={campaigns} onPage={loadCampaigns} itemLabel="campagne" />
            </>
          )}

          <h2 className="font-display text-sm label-caps mb-2 mt-6">File caricati</h2>
          {files.items.length === 0 ? <Empty text="Nessun file caricato." /> : (
            <>
              <div className="space-y-2" data-testid="lead-files-list">
                {files.items.map((f) => (
                  <Card key={f.id} className="p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs truncate">{f.filename}</span>
                      <StatusBadge status={f.status} />
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1">
                      {f.row_count != null ? `${f.row_count} righe` : ""} {f.extension}
                    </div>
                    {f.status === "VALIDATO" && selected && (
                      <button className="mt-2 text-[11px] text-primary hover:underline" onClick={() => openMapping(f)}>
                        Importa in "{selected.name}"
                      </button>
                    )}
                    {f.status === "RIFIUTATO" && (
                      <div className="mt-1 text-[11px] text-red-400 flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" /> {f.rejection_reason}
                      </div>
                    )}
                  </Card>
                ))}
              </div>
              <Pager data={files} onPage={loadFiles} itemLabel="file" />
            </>
          )}
        </div>

        <div>
          {!selected ? <Empty text="Seleziona o crea una campagna di lead generation." /> : (
            <Card className="p-5">
              <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-display text-lg font-medium">{selected.name}</h3>
                    <StatusBadge status={selected.status} />
                  </div>
                  <div className="text-xs text-muted-foreground mt-1 space-x-1">
                    <span>Canali: {csv(selected.channels) || "—"}</span>
                    <span>· Target: {selected.target_quantity ?? "—"}</span>
                    <span>· Budget: {selected.budget != null ? `$${selected.budget}` : "—"}</span>
                    <span>· Scadenza: {selected.deadline || "—"}</span>
                  </div>
                </div>
                <div className="flex gap-2 flex-wrap">
                  <button onClick={runSearch} disabled={busy}
                    className="flex items-center gap-1.5 rounded-sm border border-border px-3 py-1.5 text-sm hover:bg-muted/50 transition-colors duration-200">
                    <Search className="w-3.5 h-3.5" /> Cerca prospect
                  </button>
                  {canApprove && selected.status !== "APPROVATA" && selected.status !== "ESPORTATA" && (
                    <button data-testid="lead-approve-btn" onClick={approveCampaign} disabled={busy || pendingDuplicates > 0}
                      title={pendingDuplicates > 0 ? "Risolvi prima i duplicati in sospeso" : ""}
                      className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-1.5 text-sm hover:opacity-90 transition-colors duration-200 disabled:opacity-40">
                      <CheckCircle2 className="w-3.5 h-3.5" /> Approva
                    </button>
                  )}
                  {(selected.status === "APPROVATA" || selected.status === "ESPORTATA") && (
                    <>
                      <button onClick={() => exportCampaign("csv")} disabled={busy}
                        className="flex items-center gap-1.5 rounded-sm border border-border px-3 py-1.5 text-sm hover:bg-muted/50 transition-colors duration-200">
                        <Download className="w-3.5 h-3.5" /> Esporta CSV
                      </button>
                      <button onClick={() => exportCampaign("xlsx")} disabled={busy}
                        className="flex items-center gap-1.5 rounded-sm border border-border px-3 py-1.5 text-sm hover:bg-muted/50 transition-colors duration-200">
                        <Download className="w-3.5 h-3.5" /> Esporta XLSX
                      </button>
                      <button onClick={createHandoff} disabled={busy}
                        className="flex items-center gap-1.5 rounded-sm border border-border px-3 py-1.5 text-sm hover:bg-muted/50 transition-colors duration-200">
                        <Send className="w-3.5 h-3.5" /> Prepara handoff
                      </button>
                    </>
                  )}
                </div>
              </div>

              {pendingDuplicates > 0 && (
                <div className="mb-4 text-xs rounded-sm border border-amber-500/30 bg-amber-500/10 text-amber-400 px-3 py-2">
                  {`${pendingDuplicates} duplicati in attesa di revisione: l'approvazione resta bloccata finche' non sono risolti.`}
                </div>
              )}

              {job && JOB_ACTIVE.has(job.status) && (
                <div className="mb-4 text-xs rounded-sm border border-blue-500/30 bg-blue-500/10 text-blue-400 px-3 py-2 flex items-center gap-2">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Import in corso: {job.status.toLowerCase()}…
                </div>
              )}
              {job && !JOB_ACTIVE.has(job.status) && job.counts && (
                <div className="mb-4 text-xs rounded-sm border border-border/60 px-3 py-2 grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <span>Normalizzati: {job.counts.normalized}</span>
                  <span className="text-emerald-400">Qualificati: {job.counts.qualified}</span>
                  <span className="text-amber-400">Da rivedere: {job.counts.review_required}</span>
                  <span className="text-red-400">Esclusi: {job.counts.excluded}</span>
                </div>
              )}

              {searchResult && (
                <div className="mb-4 text-xs rounded-sm border border-border/60 px-3 py-2 space-y-1">
                  <div className="label-caps mb-1">Fonti di ricerca</div>
                  {Object.entries(searchResult.sources).map(([source, r]) => (
                    <div key={source} className="flex items-center justify-between">
                      <span>{source.replace(/_/g, " ")}</span>
                      {r.status === "OK"
                        ? <span className="text-emerald-400">OK · {r.records.length} risultati</span>
                        : <span className="text-muted-foreground">{r.motivo || "NON_DISPONIBILE"}</span>}
                    </div>
                  ))}
                </div>
              )}

              {duplicates.items.length > 0 && (
                <div className="mb-5 border-t border-border/60 pt-4">
                  <div className="label-caps mb-2 flex items-center gap-1.5"><Copy className="w-3.5 h-3.5" /> Duplicati da revisionare</div>
                  <div className="space-y-2">
                    {duplicates.items.map((d) => (
                      <div key={d.id} className="flex items-center justify-between gap-2 border border-border/60 rounded-sm px-3 py-2 text-xs">
                        <span>{d.match_type} · {d.tipo || "nome_simile"} {d.similarita != null ? `(${Math.round(d.similarita * 100)}%)` : ""} · {d.record_ids.length} record</span>
                        <div className="flex gap-1.5 shrink-0">
                          <button disabled={busy} onClick={() => decideDuplicate(d.id, "MERGE")}
                            className="rounded-sm border border-primary/50 text-primary px-2 py-1 hover:bg-primary/10">Unisci</button>
                          <button disabled={busy} onClick={() => decideDuplicate(d.id, "KEEP_SEPARATE")}
                            className="rounded-sm border border-border px-2 py-1 hover:bg-muted/50">Mantieni separati</button>
                        </div>
                      </div>
                    ))}
                  </div>
                  <Pager data={duplicates} onPage={(p) => loadDuplicates(selected.id, p)} itemLabel="duplicati" />
                </div>
              )}

              <div className="border-t border-border/60 pt-4">
                <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
                  <div className="inline-flex items-center rounded-full border border-border/60 bg-card p-0.5">
                    <button onClick={() => setTipo("aziende")}
                      className={`px-3 py-1 text-xs font-medium rounded-full flex items-center gap-1 ${tipo === "aziende" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}>
                      <Building2 className="w-3 h-3" /> Aziende
                    </button>
                    <button onClick={() => setTipo("persone")}
                      className={`px-3 py-1 text-xs font-medium rounded-full flex items-center gap-1 ${tipo === "persone" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}>
                      <Users className="w-3 h-3" /> Persone
                    </button>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs">
                    <Filter className="w-3.5 h-3.5 text-muted-foreground" />
                    <select value={qualFilter} onChange={(e) => setQualFilter(e.target.value)}
                      className="bg-background border border-border rounded-sm px-2 py-1 text-xs">
                      <option value="">Tutti gli stati</option>
                      <option value="QUALIFIED">Qualificati</option>
                      <option value="REVIEW_REQUIRED">Da rivedere</option>
                      <option value="INCOMPLETE">Incompleti</option>
                      <option value="EXCLUDED">Esclusi</option>
                      <option value="DO_NOT_CONTACT">Non contattare</option>
                    </select>
                  </div>
                </div>

                {leads.items.length === 0 ? <Empty text="Nessun lead ancora importato per questa campagna." /> : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs" data-testid="leads-table">
                      <thead>
                        <tr className="text-muted-foreground text-left border-b border-border/60">
                          <th className="py-1.5 pr-2">Nome</th>
                          <th className="py-1.5 pr-2">Settore/Città</th>
                          <th className="py-1.5 pr-2">Punteggio</th>
                          <th className="py-1.5 pr-2">Stato</th>
                          <th className="py-1.5 pr-2">Compliance</th>
                          <th className="py-1.5 pr-2">Dati mancanti</th>
                        </tr>
                      </thead>
                      <tbody>
                        {leads.items.map((l) => (
                          <tr key={l.id} className="border-b border-border/30">
                            <td className="py-1.5 pr-2">
                              {tipo === "persone"
                                ? `${l.nome?.value || ""} ${l.cognome?.value || ""}`.trim() || "—"
                                : l.ragione_sociale?.value || "—"}
                              <div className="text-[10px] text-muted-foreground">{l.email?.value || l.dominio?.value || ""}</div>
                            </td>
                            <td className="py-1.5 pr-2">{l.settore?.value || "—"} {l.citta?.value ? `· ${l.citta.value}` : ""}</td>
                            <td className="py-1.5 pr-2 font-mono">{l.score}</td>
                            <td className="py-1.5 pr-2"><StatusBadge status={l.qualification_status} /></td>
                            <td className="py-1.5 pr-2">
                              {l.compliance_status === "BLOCKED" || l.compliance_status === "DO_NOT_CONTACT" ? (
                                <span className="text-red-400 flex items-center gap-1"><ShieldAlert className="w-3 h-3" /> {l.compliance_status}</span>
                              ) : <StatusBadge status={l.compliance_status} />}
                            </td>
                            <td className="py-1.5 pr-2 text-muted-foreground">{(l.missing_data || []).join(", ") || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <Pager data={leads} onPage={(p) => loadLeads(selected.id, tipo, qualFilter, p)} itemLabel="lead" />
              </div>
            </Card>
          )}
        </div>
      </div>

      {creating && (
        <Modal onClose={() => setCreating(false)}>
          <h3 className="font-display text-lg font-medium mb-3">Nuova campagna lead generation</h3>
          <div className="space-y-3">
            <Field label="Nome" value={form.name} onChange={(v) => setForm({ ...form, name: v })} placeholder="Es. Hotel Nord Italia" />
            <Field label="Canali (separati da virgola)" value={form.channels} onChange={(v) => setForm({ ...form, channels: v })} placeholder="email, linkedin" />
            <div className="grid grid-cols-2 gap-3">
              <Field label="Quantità target" value={form.target_quantity} onChange={(v) => setForm({ ...form, target_quantity: v })} type="number" />
              <Field label="Budget ($)" value={form.budget} onChange={(v) => setForm({ ...form, budget: v })} type="number" />
            </div>
            <Field label="Scadenza (AAAA-MM-GG)" value={form.deadline} onChange={(v) => setForm({ ...form, deadline: v })} />
            <Field label="Settori esclusi (separati da virgola)" value={form.settori_esclusi} onChange={(v) => setForm({ ...form, settori_esclusi: v })} />
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={createCampaign} disabled={busy || !form.name.trim()}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">Crea bozza</button>
            <button onClick={() => setCreating(false)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {mappingFile && (
        <Modal onClose={() => setMappingFile(null)}>
          <h3 className="font-display text-lg font-medium mb-2">Mapping colonne — {mappingFile.file.filename}</h3>
          <p className="text-xs text-muted-foreground mb-3">
            Il mapping automatico è solo un suggerimento: correggi o rimuovi ("—") ogni colonna prima di avviare l'import.
          </p>
          <div className="space-y-2 max-h-[50vh] overflow-y-auto">
            {mappingFile.file.columns.map((col) => (
              <div key={col} className="flex items-center justify-between gap-3">
                <span className="text-sm truncate flex-1">{col}</span>
                <select value={mappingFile.mapping[col] || ""} onChange={(e) => updateMapping(col, e.target.value)}
                  className="bg-background border border-border rounded-sm px-2 py-1 text-xs w-48">
                  <option value="">— (ignora)</option>
                  {CANONICAL_FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </div>
            ))}
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={startImport} disabled={busy}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">Avvia import</button>
            <button onClick={() => setMappingFile(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Field({ label, value, onChange, placeholder, type = "text" }) {
  return (
    <div>
      <div className="label-caps mb-1">{label}</div>
      <input type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
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
