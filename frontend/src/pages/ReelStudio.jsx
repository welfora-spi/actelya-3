import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { MediaPlayer } from "@/components/MediaPlayer";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import {
  Plus, Sparkles, CheckCircle2, MessageSquareWarning, AlertTriangle, Video,
  FileText, ShieldCheck, ShieldAlert, RefreshCw, Clapperboard,
} from "lucide-react";

const VIDEO_ACTIVE = new Set(["IN_CODA", "IN_GENERAZIONE"]);
const VIDEO_RETRYABLE = new Set(["NON_RICHIESTO", "BLOCCATO", "FALLITO"]);

export default function ReelStudio() {
  const [searchParams] = useSearchParams();
  const [projects, setProjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [creating, setCreating] = useState(false);
  const [brief, setBrief] = useState("");
  const [preview, setPreview] = useState(null);
  const [videoPreview, setVideoPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [revisionNote, setRevisionNote] = useState("");
  const [videoRevisionOpen, setVideoRevisionOpen] = useState(false);
  const [videoRevisionNote, setVideoRevisionNote] = useState("");
  const [uncertainOpen, setUncertainOpen] = useState(false);
  const [uncertainNote, setUncertainNote] = useState("");
  const { hasRole } = useAuth();
  const isAdmin = hasRole("ADMIN");
  const canApprove = hasRole("ADMIN") || hasRole("APPROVATORE");

  const load = useCallback(() => {
    api.get("/reel/projects").then((r) => setProjects(r.data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  // Arrivo diretto da "Nuovo Obiettivo" (brain -> capability video_reel):
  // ?project=<id> seleziona subito il progetto appena creato, senza doverlo
  // ricercare a mano nella lista.
  useEffect(() => {
    const projectId = searchParams.get("project");
    if (projectId) refreshSelected(projectId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const loadJobs = async (id) => {
    try { const { data } = await api.get(`/reel/projects/${id}/video/jobs`); setJobs(data); }
    catch { setJobs([]); }
  };

  const refreshSelected = async (id) => {
    const { data } = await api.get(`/reel/projects/${id}`);
    setSelected(data);
    loadJobs(id);
    load();
  };

  const createProject = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/reel/projects", { brief });
      toast.success("Progetto reel creato (bozza). Dati aziendali presi automaticamente dal Fact Ledger.");
      setCreating(false); setBrief("");
      setSelected(data); setJobs([]);
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  // ---------- Testo (Requesty) ----------
  const openGeneratePreview = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/reel/projects/${selected.id}/generate/preview`);
      setPreview(data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const confirmGenerate = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/reel/projects/${selected.id}/generate`, { confirm: true });
      setPreview(null);
      setSelected(data);
      load();
      if (data.status === "PROGETTO_PRONTO") toast.success("Progetto reel pronto: testo e storyboard generati da Requesty.");
      else if (data.status === "BLOCCATO") toast.error("Generazione completata ma il contenuto non ha superato la validazione.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); await refreshSelected(selected.id); }
    finally { setBusy(false); }
  };

  const approve = async () => {
    try {
      const { data } = await api.post(`/reel/projects/${selected.id}/approve`);
      setSelected(data); load();
      toast.success("Progetto reel approvato.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const submitRevision = async () => {
    try {
      const { data } = await api.post(`/reel/projects/${selected.id}/richiedi-modifica`, { nota: revisionNote });
      setSelected(data); setJobs([]); load();
      setRevisionOpen(false); setRevisionNote("");
      toast.success("Modifica richiesta: il progetto è tornato in bozza, genera di nuovo quando pronto.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const submitResolveUncertain = async () => {
    try {
      const { data } = await api.post(`/reel/projects/${selected.id}/risolvi-esito-incerto`, { nota: uncertainNote });
      setSelected(data); load();
      setUncertainOpen(false); setUncertainNote("");
      toast.success("Esito incerto risolto: puoi riprovare la generazione.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const runSemanticCheck = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/reel/projects/${selected.id}/verifica-semantica`);
      setSelected(data); load();
      toast[data.semantic_check.status === "OK" ? "success" : "error"](
        data.semantic_check.status === "OK" ? "Nessuna affermazione non supportata trovata." : "Trovate affermazioni non riconducibili al Fact Ledger/brief.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  // ---------- Video (Runway) ----------
  const openVideoPreview = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/reel/projects/${selected.id}/video/preview`);
      setVideoPreview(data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const confirmVideoGenerate = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/reel/projects/${selected.id}/video/generate`, { confirm: true });
      setVideoPreview(null);
      setSelected(data);
      loadJobs(selected.id);
      load();
      toast.success("Generazione video avviata su Runway (asincrona): aggiorna lo stato per seguirne l'avanzamento.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); setVideoPreview(null); await refreshSelected(selected.id); }
    finally { setBusy(false); }
  };

  const refreshLatestJob = async () => {
    const latest = jobs[0];
    if (!latest) return;
    setBusy(true);
    try {
      await api.post(`/reel/projects/${selected.id}/video/jobs/${latest.id}/aggiorna-stato`);
      await refreshSelected(selected.id);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const approveVideo = async () => {
    try {
      const { data } = await api.post(`/reel/projects/${selected.id}/video/approve`);
      setSelected(data); load();
      toast.success("Video approvato.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const submitVideoRevision = async () => {
    try {
      const { data } = await api.post(`/reel/projects/${selected.id}/video/richiedi-modifica`, { nota: videoRevisionNote });
      setSelected(data); load();
      setVideoRevisionOpen(false); setVideoRevisionNote("");
      toast.success("Modifica video richiesta: la cronologia resta consultabile, puoi generare una nuova versione.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const semantic = selected?.semantic_check;
  const canGenerateVideo = selected?.progetto_pronto && semantic?.status === "OK" && VIDEO_RETRYABLE.has(selected?.video_status);
  const videoActive = VIDEO_ACTIVE.has(selected?.video_status);

  return (
    <div>
      <PageHeader title="Reel — Agente marketing (Requesty + Runway)"
        subtitle="Testo, storyboard e prompt video via Requesty; video reale via Runway. Azienda/prodotto/settore/sito vengono presi automaticamente dal Fact Ledger."
        actions={<button data-testid="new-reel-project" onClick={() => setCreating(true)}
          className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm hover:opacity-90 active:scale-[0.98] transition-colors duration-200">
          <Plus className="w-4 h-4" /> Nuovo obiettivo reel</button>} />

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">
        <div>
          <h2 className="font-display text-sm label-caps mb-2">Progetti</h2>
          {projects.length === 0 ? <Empty text="Nessun progetto reel ancora." /> : (
            <div className="space-y-2" data-testid="reel-projects-list">
              {projects.map((p) => (
                <Card key={p.id} className={`p-3 cursor-pointer ${selected?.id === p.id ? "border-primary" : ""}`}
                  onClick={() => refreshSelected(p.id)}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm truncate">{p.brief || "(senza brief)"}</span>
                    <StatusBadge status={p.status} />
                  </div>
                  <div className="text-[11px] text-muted-foreground mt-1 flex items-center gap-2 flex-wrap">
                    {p.progetto_pronto ? <span className="text-emerald-400 flex items-center gap-1"><FileText className="w-3 h-3" /> progetto pronto</span>
                      : <span>progetto non pronto</span>}
                    <span className="opacity-50">·</span>
                    {p.video_pronto ? <span className="text-emerald-400 flex items-center gap-1"><Video className="w-3 h-3" /> video pronto</span>
                      : <span className="flex items-center gap-1"><Video className="w-3 h-3" /> {p.video_status.toLowerCase().replace(/_/g, " ")}</span>}
                    {p.video_approvato && <span className="text-emerald-400">· video approvato</span>}
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>

        <div>
          {!selected ? <Empty text="Seleziona o crea un progetto reel." /> : (
            <Card className="p-5">
              <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-display text-lg font-medium">{selected.brief || "(senza brief)"}</h3>
                    <StatusBadge status={selected.status} />
                    {selected.progetto_approvato && <span className="text-[11px] flex items-center gap-1 text-emerald-400"><CheckCircle2 className="w-3.5 h-3.5" /> Progetto approvato</span>}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1 space-x-1">
                    <span>Progetto reel: <b className={selected.progetto_pronto ? "text-emerald-400" : ""}>{selected.progetto_pronto ? "PRONTO" : "non pronto"}</b></span>
                    <span>· Video reel: <b className={selected.video_pronto ? "text-emerald-400" : ""}>{selected.video_pronto ? "PRONTO" : selected.video_status.replace(/_/g, " ")}</b></span>
                    <span>· Video: <b className={selected.video_approvato ? "text-emerald-400" : ""}>{selected.video_approvato ? "APPROVATO" : "non approvato"}</b></span>
                  </div>
                </div>
                <div className="flex gap-2 flex-wrap">
                  {(selected.status === "BOZZA" || selected.status === "BLOCCATO") && isAdmin && (
                    <button data-testid="reel-generate-btn" onClick={openGeneratePreview} disabled={busy}
                      className="flex items-center gap-1.5 rounded-sm border border-amber-500/40 text-amber-400 px-3 py-1.5 text-sm hover:bg-amber-500/10 transition-colors duration-200">
                      <Sparkles className="w-3.5 h-3.5" /> Genera con Requesty
                    </button>
                  )}
                  {selected.status === "ESITO_INCERTO" && isAdmin && (
                    <button onClick={() => setUncertainOpen(true)}
                      className="flex items-center gap-1.5 rounded-sm border border-red-500/40 text-red-400 px-3 py-1.5 text-sm hover:bg-red-500/10 transition-colors duration-200">
                      <AlertTriangle className="w-3.5 h-3.5" /> Risolvi esito incerto
                    </button>
                  )}
                  {selected.status === "PROGETTO_PRONTO" && (
                    <>
                      <button onClick={() => setRevisionOpen(true)}
                        className="flex items-center gap-1.5 rounded-sm border border-border px-3 py-1.5 text-sm hover:bg-muted/50 transition-colors duration-200">
                        <MessageSquareWarning className="w-3.5 h-3.5" /> Richiedi modifica testo
                      </button>
                      {canApprove && !selected.progetto_approvato && (
                        <button data-testid="reel-approve-btn" onClick={approve}
                          className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-1.5 text-sm hover:opacity-90 transition-colors duration-200">
                          <CheckCircle2 className="w-3.5 h-3.5" /> Approva progetto
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>

              {selected.status === "ESITO_INCERTO" && (
                <div className="mb-4 text-xs rounded-sm border border-red-500/30 bg-red-500/10 text-red-400 px-3 py-2">
                  Esito incerto: la richiesta è stata inviata a Requesty ma nessuna risposta è arrivata entro il timeout.
                  Verifica manualmente prima di riprovare (nessun nuovo tentativo automatico).
                </div>
              )}

              {selected.status === "BLOCCATO" && (selected.generazione?.errori_validazione?.length > 0) && (
                <div className="mb-4 text-xs rounded-sm border border-red-500/30 bg-red-500/10 text-red-400 px-3 py-2">
                  <div className="font-medium mb-1">Generazione bloccata dalla validazione:</div>
                  <ul className="list-disc pl-4 space-y-0.5">
                    {selected.generazione.errori_validazione.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                  {selected.generazione.troncata && (
                    <div className="mt-1">Risposta troncata: il modello ha esaurito il budget di token disponibile.</div>
                  )}
                  <div className="mt-1 text-muted-foreground">
                    La chiamata è stata comunque addebitata sul budget (vedi sotto). Puoi generare di nuovo.
                  </div>
                </div>
              )}
              {selected.generazione?.avvisi_validazione?.length > 0 && (
                <div className="mb-4 text-xs rounded-sm border border-amber-500/30 bg-amber-500/10 text-amber-400 px-3 py-2">
                  <div className="font-medium mb-1">Avvisi:</div>
                  <ul className="list-disc pl-4 space-y-0.5">
                    {selected.generazione.avvisi_validazione.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}

              <div className="mb-4">
                <div className="label-caps mb-1.5">Dati aziendali usati (Fact Ledger — mai richiesti di nuovo)</div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                  <F l="Ragione sociale" v={selected.fact_snapshot?.ragione_sociale} />
                  <F l="Settore" v={selected.fact_snapshot?.settore} />
                  <F l="Sito" v={selected.fact_snapshot?.sito_web || "—"} />
                  <F l="Obiettivi" v={selected.fact_snapshot?.obiettivi_commerciali || "—"} />
                </div>
              </div>

              {selected.nota_revisione && (
                <div className="mb-4 text-xs rounded-sm border border-amber-500/30 bg-amber-500/10 text-amber-400 px-3 py-2">
                  Ultima richiesta di modifica testo: {selected.nota_revisione}
                </div>
              )}

              {selected.content ? (
                <>
                  <ReelContent content={selected.content} generazione={selected.generazione} />

                  {/* Validazione semantica */}
                  <div className="mt-5 border-t border-border/60 pt-4">
                    <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
                      <div className="flex items-center gap-2">
                        {semantic?.status === "OK" ? <ShieldCheck className="w-4 h-4 text-emerald-400" /> : <ShieldAlert className="w-4 h-4 text-amber-400" />}
                        <span className="label-caps">Validazione semantica (deterministica, nessuna chiamata AI)</span>
                        <StatusBadge status={semantic?.status || "NON_VERIFICATO"} />
                      </div>
                      <button onClick={runSemanticCheck} disabled={busy}
                        className="flex items-center gap-1.5 rounded-sm border border-border px-2.5 py-1 text-xs hover:bg-muted/50 transition-colors duration-200">
                        <RefreshCw className="w-3 h-3" /> Verifica ora
                      </button>
                    </div>
                    {semantic?.status === "CONTESTATO" && (
                      <div className="text-xs rounded-sm border border-amber-500/30 bg-amber-500/10 text-amber-400 px-3 py-2 space-y-1.5">
                        <div>Affermazioni non riconducibili al Fact Ledger o al brief — correggi il testo o richiedi una modifica prima di generare il video:</div>
                        <ul className="list-disc pl-4 space-y-1">
                          {semantic.affermazioni_contestate.map((a, i) => (
                            <li key={i}><span className="font-mono text-[10px] uppercase">{a.categoria}</span> ({a.campo}): "{a.frase}"</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>

                  {/* Video */}
                  <div className="mt-5 border-t border-border/60 pt-4">
                    <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
                      <div className="flex items-center gap-2">
                        <Clapperboard className="w-4 h-4" />
                        <span className="label-caps">Video (Runway)</span>
                        <StatusBadge status={selected.video_status} />
                        {selected.video_approvato && <span className="text-[11px] flex items-center gap-1 text-emerald-400"><CheckCircle2 className="w-3.5 h-3.5" /> Approvato</span>}
                      </div>
                      <div className="flex gap-2 flex-wrap">
                        {videoActive && (
                          <button onClick={refreshLatestJob} disabled={busy}
                            className="flex items-center gap-1.5 rounded-sm border border-blue-500/40 text-blue-400 px-3 py-1.5 text-sm hover:bg-blue-500/10 transition-colors duration-200">
                            <RefreshCw className="w-3.5 h-3.5" /> Aggiorna stato
                          </button>
                        )}
                        {canGenerateVideo && isAdmin && (
                          <button data-testid="reel-video-generate-btn" onClick={openVideoPreview} disabled={busy}
                            className="flex items-center gap-1.5 rounded-sm border border-amber-500/40 text-amber-400 px-3 py-1.5 text-sm hover:bg-amber-500/10 transition-colors duration-200">
                            <Sparkles className="w-3.5 h-3.5" /> Genera video con Runway
                          </button>
                        )}
                        {selected.video_status === "VIDEO_PRONTO" && (
                          <>
                            <button onClick={() => setVideoRevisionOpen(true)}
                              className="flex items-center gap-1.5 rounded-sm border border-border px-3 py-1.5 text-sm hover:bg-muted/50 transition-colors duration-200">
                              <MessageSquareWarning className="w-3.5 h-3.5" /> Richiedi modifica video
                            </button>
                            {canApprove && !selected.video_approvato && (
                              <button data-testid="reel-video-approve-btn" onClick={approveVideo}
                                className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-3 py-1.5 text-sm hover:opacity-90 transition-colors duration-200">
                                <CheckCircle2 className="w-3.5 h-3.5" /> Approva video
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </div>

                    {!canGenerateVideo && !videoActive && selected.video_status !== "VIDEO_PRONTO" && (
                      <p className="text-xs text-muted-foreground mb-3">
                        {semantic?.status !== "OK" ? "Il video non può essere generato finché la validazione semantica non è OK."
                          : !selected.progetto_pronto ? "Il progetto reel deve essere PRONTO prima di generare il video."
                          : "Video non ancora generabile."}
                      </p>
                    )}

                    <MediaPlayer kind="video" src={selected.video_pronto ? selected.video_url : null}
                      status={selected.video_status} downloadable
                      message={
                        selected.video_status === "IN_CODA" || selected.video_status === "IN_GENERAZIONE"
                          ? "Generazione in corso su Runway. Aggiorna lo stato per seguirne l'avanzamento (sola lettura, gratuito)."
                          : selected.video_status === "FALLITO" ? "La generazione è fallita (il credito consumato resta comunque registrato)."
                          : selected.video_status === "ESITO_INCERTO" ? "Esito incerto: richiesta inviata, risposta non arrivata."
                          : selected.video_status === "BLOCCATO" ? "Generazione bloccata (vedi cronologia sotto)."
                          : "Nessun video ancora richiesto."
                      } />

                    {jobs.length > 0 && (
                      <div className="mt-3">
                        <div className="label-caps mb-1.5">Cronologia video (versionata, mai sovrascritta)</div>
                        <div className="space-y-1.5 text-xs font-mono">
                          {jobs.map((j) => (
                            <div key={j.id} className="flex items-center justify-between border border-border/60 rounded-sm px-2.5 py-1.5">
                              <span>v{j.version} · {j.modello || "—"} · {j.durata_secondi ?? "—"}s {j.ratio || ""}</span>
                              <span className="flex items-center gap-2">
                                {j.costo_credits != null && <span>{j.costo_credits} cr</span>}
                                <StatusBadge status={j.status} />
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <Empty text="Nessun contenuto ancora generato." />
              )}
            </Card>
          )}
        </div>
      </div>

      {/* Create modal */}
      {creating && (
        <Modal onClose={() => setCreating(false)}>
          <h3 className="font-display text-lg font-medium mb-3">Nuovo obiettivo reel</h3>
          <p className="text-xs text-muted-foreground mb-3">
            Azienda, prodotto, settore e sito vengono presi automaticamente dal Fact Ledger: non serve reinserirli.
            Il brief è facoltativo (es. "reel per il lancio della nuova funzione").
          </p>
          <textarea data-testid="reel-brief-input" value={brief} onChange={(e) => setBrief(e.target.value)}
            rows={4} placeholder="Brief creativo (facoltativo)"
            className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none" />
          <div className="flex gap-2 mt-4">
            <button data-testid="reel-create-submit" onClick={createProject} disabled={busy}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm">Crea bozza</button>
            <button onClick={() => setCreating(false)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {/* Generate text preview/confirm modal */}
      {preview && (
        <Modal onClose={() => setPreview(null)}>
          <h3 className="font-display text-lg font-medium mb-2">Conferma generazione reale (testo)</h3>
          <div className="space-y-1.5 text-sm">
            <Line l="Provider" v={preview.provider} />
            <Line l="Modello effettivo" v={preview.modello_effettivo || "—"} />
            <Line l="Budget residuo" v={`$${preview.budget_residuo}`} />
            <Line l="Pronto a generare" v={preview.pronto ? "Sì" : "No"} />
          </div>
          {!preview.pronto && (
            <ul className="mt-3 text-xs text-red-400 list-disc pl-4 space-y-1">
              {preview.motivi.map((m, i) => <li key={i}>{m}</li>)}
            </ul>
          )}
          <p className="text-xs text-muted-foreground mt-3">{preview.message}</p>
          <div className="flex gap-2 mt-4">
            <button data-testid="reel-generate-confirm" onClick={confirmGenerate} disabled={busy || !preview.pronto}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">
              Conferma ed esegui UNA chiamata reale a Requesty
            </button>
            <button onClick={() => setPreview(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {/* Generate video preview/confirm modal */}
      {videoPreview && (
        <Modal onClose={() => setVideoPreview(null)}>
          <h3 className="font-display text-lg font-medium mb-2">Conferma generazione video reale (Runway)</h3>
          <div className="space-y-1.5 text-sm">
            <Line l="Provider" v={videoPreview.provider} />
            <Line l="Modello effettivo" v={videoPreview.modello_effettivo || "—"} />
            <Line l="Durata" v={`${videoPreview.durata_secondi ?? "—"}s`} />
            <Line l="Formato" v={videoPreview.ratio || "—"} />
            <Line l="Costo massimo configurato" v={`${videoPreview.costo_massimo_credits ?? "—"} crediti`} />
            <Line l="Budget residuo (generale, $)" v={`$${videoPreview.budget_residuo}`} />
            <Line l="Pronto a generare" v={videoPreview.pronto ? "Sì" : "No"} />
          </div>
          {!videoPreview.pronto && (
            <ul className="mt-3 text-xs text-red-400 list-disc pl-4 space-y-1">
              {videoPreview.motivi.map((m, i) => <li key={i}>{m}</li>)}
            </ul>
          )}
          <p className="text-xs text-muted-foreground mt-3">{videoPreview.message}</p>
          <div className="flex gap-2 mt-4">
            <button data-testid="reel-video-generate-confirm" onClick={confirmVideoGenerate} disabled={busy || !videoPreview.pronto}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">
              Conferma ed avvia UNA generazione reale su Runway
            </button>
            <button onClick={() => setVideoPreview(null)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {/* Revision modal (testo) */}
      {revisionOpen && (
        <Modal onClose={() => setRevisionOpen(false)}>
          <h3 className="font-display text-lg font-medium mb-3">Richiedi modifica testo</h3>
          <textarea value={revisionNote} onChange={(e) => setRevisionNote(e.target.value)} rows={4}
            placeholder="Cosa va cambiato? (es. hook più diretto, tono più informale...)"
            className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none" />
          <div className="flex gap-2 mt-4">
            <button onClick={submitRevision} disabled={!revisionNote.trim()}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">Invia richiesta</button>
            <button onClick={() => setRevisionOpen(false)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {/* Revision modal (video) */}
      {videoRevisionOpen && (
        <Modal onClose={() => setVideoRevisionOpen(false)}>
          <h3 className="font-display text-lg font-medium mb-3">Richiedi modifica video</h3>
          <p className="text-xs text-muted-foreground mb-3">La cronologia dei video precedenti resta consultabile: questa azione non cancella nulla, permette solo una nuova generazione (nuova versione, nuova conferma).</p>
          <textarea value={videoRevisionNote} onChange={(e) => setVideoRevisionNote(e.target.value)} rows={4}
            placeholder="Cosa va cambiato nel video?"
            className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none" />
          <div className="flex gap-2 mt-4">
            <button onClick={submitVideoRevision} disabled={!videoRevisionNote.trim()}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">Invia richiesta</button>
            <button onClick={() => setVideoRevisionOpen(false)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}

      {/* Resolve uncertain modal */}
      {uncertainOpen && (
        <Modal onClose={() => setUncertainOpen(false)}>
          <h3 className="font-display text-lg font-medium mb-3">Risolvi esito incerto</h3>
          <textarea value={uncertainNote} onChange={(e) => setUncertainNote(e.target.value)} rows={3}
            placeholder="Nota (es. verificato lato Requesty: nessun addebito confermato)"
            className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none" />
          <div className="flex gap-2 mt-4">
            <button onClick={submitResolveUncertain} disabled={!uncertainNote.trim()}
              className="bg-primary text-primary-foreground rounded-sm px-4 py-2 text-sm disabled:opacity-40">Conferma risoluzione</button>
            <button onClick={() => setUncertainOpen(false)} className="border border-border rounded-sm px-4 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ReelContent({ content, generazione }) {
  return (
    <div className="space-y-4 text-sm">
      <Section title="Concept" text={content.concept} />
      <Section title="Hook" text={content.hook} />
      <Section title="Sceneggiatura" text={content.sceneggiatura} />
      <div>
        <div className="label-caps mb-1.5">Storyboard</div>
        <div className="space-y-2">
          {(content.storyboard || []).map((s, i) => (
            <div key={i} className="border border-border/60 rounded-sm p-3">
              <div className="text-xs font-mono text-muted-foreground mb-1">Scena {s.numero_scena ?? i + 1} · {s.durata_secondi}s</div>
              <div><span className="text-muted-foreground">Visivo: </span>{s.descrizione_visiva}</div>
              <div><span className="text-muted-foreground">Testo a schermo: </span>{s.testo_a_schermo}</div>
              <div><span className="text-muted-foreground">Voice-over: </span>{s.voice_over}</div>
            </div>
          ))}
        </div>
      </div>
      <Section title="Voice-over completo" text={content.voice_over_completo} />
      <div>
        <div className="label-caps mb-1.5">Testi a schermo</div>
        <ul className="list-disc pl-5">{(content.testi_a_schermo || []).map((t, i) => <li key={i}>{t}</li>)}</ul>
      </div>
      <Section title="Caption" text={content.caption} />
      <Section title="CTA" text={content.cta} />
      <div className="grid grid-cols-2 gap-3">
        <F l="Durata" v={`${content.durata_secondi ?? "—"}s`} />
        <F l="Formato" v={content.formato} />
      </div>
      <Section title="Prompt per futuro generatore video" text={content.prompt_video_generativo} mono />
      {generazione && (generazione.input_tokens || generazione.output_tokens) && (
        <div className="text-[11px] text-muted-foreground font-mono">
          {generazione.modello_effettivo} · {generazione.input_tokens}/{generazione.output_tokens} tok · {generazione.latenza_ms}ms
          {generazione.stima_costo_usd != null && <> · stima costo ${generazione.stima_costo_usd}</>}
          {generazione.troncata && <span className="text-red-400"> · risposta troncata</span>}
        </div>
      )}
    </div>
  );
}

function Section({ title, text, mono }) {
  return (
    <div>
      <div className="label-caps mb-1">{title}</div>
      <div className={mono ? "font-mono text-xs whitespace-pre-wrap" : "whitespace-pre-wrap"}>{text || "—"}</div>
    </div>
  );
}
function F({ l, v }) { return <div><div className="label-caps">{l}</div><div className="mt-0.5">{v || "—"}</div></div>; }
function Line({ l, v }) { return <div className="flex justify-between"><span className="text-muted-foreground">{l}</span><span className="font-mono">{v}</span></div>; }
function Modal({ children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-sm p-6 w-full max-w-2xl shadow-xl max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>{children}</div>
    </div>
  );
}
