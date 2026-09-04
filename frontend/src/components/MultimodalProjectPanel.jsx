import { useEffect, useState, useCallback } from "react";
import api, { formatApiError, absoluteAssetUrl } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { MediaPlayer } from "@/components/MediaPlayer";
import SocialPublishingPanel from "@/components/SocialPublishingPanel";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Sparkles, CheckCircle2, MessageSquareWarning, AlertTriangle, ShieldCheck, ShieldAlert, RefreshCw } from "lucide-react";

// Renderer universale per un progetto multimodale REALE (reel/flyer, stesso
// pattern: obiettivo -> grounding -> skill -> provider -> validazione ->
// approvazione -> media finale). Usato SIA nella pagina Deliverable SIA nel
// pannello Collaboratore di Sala Riunioni: nessuna duplicazione, nessuna
// navigazione verso una pagina laboratorio separata per completare il
// flusso -- generazione e approvazione avvengono qui.
const KIND_CONFIG = {
  reel: {
    base: (id) => `/reel/projects/${id}`,
    label: "Reel (testo + video)",
    mediaKind: "video", mediaStatusField: "video_status", mediaUrlField: "video_url",
    mediaReadyStatus: "VIDEO_PRONTO", mediaApprovedField: "video_approvato",
    textGeneratePreview: "generate/preview", textGenerate: "generate",
    textApprove: "approve", textRequestChange: "richiedi-modifica",
    mediaPreview: "video/preview", mediaGenerate: "video/generate",
    mediaApprove: "video/approve", mediaRequestChange: "video/richiedi-modifica",
    semanticCheck: "verifica-semantica",
  },
  flyer: {
    base: (id) => `/flyer/projects/${id}`,
    label: "Flyer (copy + immagine)",
    mediaKind: "image", mediaStatusField: "image_status", mediaUrlField: "image_url",
    mediaReadyStatus: "IMMAGINE_PRONTA", mediaApprovedField: "image_approvata",
    textGeneratePreview: "generate/preview", textGenerate: "generate",
    textApprove: "approve", textRequestChange: "richiedi-modifica",
    mediaPreview: "image/preview", mediaGenerate: "image/generate",
    mediaApprove: "image/approve", mediaRequestChange: "image/richiedi-modifica",
    semanticCheck: "verifica-semantica",
  },
};

function ContentFields({ kind, content }) {
  if (!content) return null;
  if (kind === "reel") {
    return (
      <div className="space-y-2 text-sm">
        <F l="Concept" v={content.concept} /><F l="Hook" v={content.hook} />
        <F l="Sceneggiatura" v={content.sceneggiatura} />
        {content.storyboard?.length > 0 && (
          <div>
            <div className="label-caps mb-1">Storyboard</div>
            {content.storyboard.map((s, i) => (
              <div key={i} className="text-xs border border-border/60 rounded-sm p-2 mb-1">
                Scena {s.numero_scena ?? i + 1} ({s.durata_secondi}s) — {s.descrizione_visiva}
              </div>
            ))}
          </div>
        )}
        <F l="Caption" v={content.caption} /><F l="CTA" v={content.cta} />
        {content.hashtags?.length > 0 && (
          <div>
            <div className="label-caps">Hashtag</div>
            <div className="mt-0.5 flex flex-wrap gap-1.5">
              {content.hashtags.map((h, i) => (
                <span key={i} className="text-xs font-mono text-primary bg-primary/10 rounded-sm px-1.5 py-0.5">{h}</span>
              ))}
            </div>
          </div>
        )}
        <F l="Durata/Formato" v={`${content.durata_secondi ?? "—"}s · ${content.formato ?? "—"}`} />
      </div>
    );
  }
  return (
    <div className="space-y-2 text-sm">
      <F l="Headline" v={content.headline} /><F l="Sottotitolo" v={content.subheadline} />
      <F l="Testo" v={content.body_text} /><F l="CTA" v={content.cta} />
      {content.hashtags?.length > 0 && (
        <div>
          <div className="label-caps">Hashtag</div>
          <div className="mt-0.5 flex flex-wrap gap-1.5">
            {content.hashtags.map((h, i) => (
              <span key={i} className="text-xs font-mono text-primary bg-primary/10 rounded-sm px-1.5 py-0.5">{h}</span>
            ))}
          </div>
        </div>
      )}
      <F l="Formato" v={content.formato} />
      <F l="Prompt immagine" v={content.prompt_immagine} mono />
    </div>
  );
}
function F({ l, v, mono }) {
  return <div><div className="label-caps">{l}</div><div className={`mt-0.5 whitespace-pre-wrap ${mono ? "font-mono text-xs" : ""}`}>{v || "—"}</div></div>;
}

export default function MultimodalProjectPanel({ kind, projectId, compact = false }) {
  const cfg = KIND_CONFIG[kind];
  const [project, setProject] = useState(null);
  const [preview, setPreview] = useState(null); // {which: "text"|"media", data}
  const [busy, setBusy] = useState(false);
  const [reviseWhich, setReviseWhich] = useState(null);
  const [reviseNote, setReviseNote] = useState("");
  const { hasRole } = useAuth();
  const isAdmin = hasRole("ADMIN");
  const canApprove = hasRole("ADMIN") || hasRole("APPROVATORE");

  const load = useCallback(() => {
    if (!projectId) return;
    api.get(cfg.base(projectId)).then((r) => setProject(r.data)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, kind]);
  useEffect(() => { load(); }, [load]);

  if (!projectId) return null;
  if (!project) return <p className="text-xs text-muted-foreground">Caricamento…</p>;

  const openPreview = async (which, path) => {
    setBusy(true);
    try { const { data } = await api.post(`${cfg.base(projectId)}/${path}`); setPreview({ which, data }); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const confirmGenerate = async (which, path) => {
    setBusy(true);
    try {
      const { data } = await api.post(`${cfg.base(projectId)}/${path}`, { confirm: true });
      setPreview(null); setProject(data);
      toast.success(which === "text" ? "Testo generato." : "Media generato.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const runSemanticCheck = async () => {
    setBusy(true);
    try { const { data } = await api.post(`${cfg.base(projectId)}/${cfg.semanticCheck}`); setProject(data); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const approve = async (path) => {
    try { const { data } = await api.post(`${cfg.base(projectId)}/${path}`); setProject(data); toast.success("Approvato."); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const submitRevise = async () => {
    try {
      const { data } = await api.post(`${cfg.base(projectId)}/${reviseWhich === "text" ? cfg.textRequestChange : cfg.mediaRequestChange}`, { nota: reviseNote });
      setProject(data); setReviseWhich(null); setReviseNote("");
      toast.success("Modifica richiesta.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const semantic = project.semantic_check;
  const mediaStatus = project[cfg.mediaStatusField];
  const mediaReady = mediaStatus === cfg.mediaReadyStatus && Boolean(project[cfg.mediaUrlField]);
  const canGenerateMedia = project.progetto_pronto && semantic?.status === "OK" && ["NON_RICHIESTO", "BLOCCATO", "FALLITO"].includes(mediaStatus);
  const mediaActive = ["IN_CODA", "IN_GENERAZIONE"].includes(mediaStatus);

  return (
    <div className={compact ? "space-y-3" : "space-y-4"}>
      {/* In modalita' 'compact' (dentro il pannello collaboratore) lo stato
          della postazione e' gia' mostrato dal chiamante: qui si mostra SOLO
          lo stato specifico del progetto, mai due badge ridondanti per la
          stessa informazione. */}
      <div className="flex items-center gap-2 flex-wrap">
        {!compact && <span className="label-caps">{cfg.label}</span>}
        <StatusBadge status={project.status} />
        {project.progetto_approvato && <span className="text-[11px] flex items-center gap-1 text-emerald-400"><CheckCircle2 className="w-3.5 h-3.5" /> Testo approvato</span>}
      </div>

      {(project.status === "BOZZA" || project.status === "BLOCCATO") && isAdmin && (
        <button onClick={() => openPreview("text", cfg.textGeneratePreview)} disabled={busy}
          className="flex items-center gap-1.5 rounded-sm border border-amber-500/40 text-amber-400 px-3 py-1.5 text-sm hover:bg-amber-500/10 transition-colors duration-200">
          <Sparkles className="w-3.5 h-3.5" /> Genera testo (reale)
        </button>
      )}
      {project.status === "ESITO_INCERTO" && (
        <div className="text-xs rounded-sm border border-red-500/30 bg-red-500/10 text-red-400 px-3 py-2 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" /> Esito incerto: verificare manualmente prima di riprovare.
        </div>
      )}
      {project.status === "BLOCCATO" && project.generazione?.errori_validazione?.length > 0 && (
        <div className="text-xs rounded-sm border border-red-500/30 bg-red-500/10 text-red-400 px-3 py-2">
          <ul className="list-disc pl-4">{project.generazione.errori_validazione.map((e, i) => <li key={i}>{e}</li>)}</ul>
        </div>
      )}

      {project.content && <ContentFields kind={kind} content={project.content} />}

      {project.content && (
        <div className="flex items-center gap-2 flex-wrap">
          <ShieldCheckOrAlert status={semantic?.status} />
          <StatusBadge status={semantic?.status || "NON_VERIFICATO"} />
          <button onClick={runSemanticCheck} disabled={busy} className="flex items-center gap-1 rounded-sm border border-border px-2 py-1 text-xs hover:bg-muted/50">
            <RefreshCw className="w-3 h-3" /> Verifica
          </button>
        </div>
      )}
      {semantic?.status === "CONTESTATO" && (
        <ul className="text-xs text-amber-400 list-disc pl-4 space-y-0.5">
          {semantic.affermazioni_contestate.map((a, i) => <li key={i}>{a.categoria} ({a.campo}): "{a.frase}"</li>)}
        </ul>
      )}

      {project.status === "PROGETTO_PRONTO" && (
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => setReviseWhich("text")} className="flex items-center gap-1.5 rounded-sm border border-border px-2.5 py-1.5 text-xs hover:bg-muted/50">
            <MessageSquareWarning className="w-3.5 h-3.5" /> Richiedi modifica testo
          </button>
          {canApprove && !project.progetto_approvato && (
            <button onClick={() => approve(cfg.textApprove)} className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-2.5 py-1.5 text-xs">
              <CheckCircle2 className="w-3.5 h-3.5" /> Approva testo
            </button>
          )}
        </div>
      )}

      <div className="border-t border-border/60 pt-3 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <StatusBadge status={mediaStatus} />
          {project[cfg.mediaApprovedField] && <span className="text-[11px] flex items-center gap-1 text-emerald-400"><CheckCircle2 className="w-3.5 h-3.5" /> Approvato</span>}
          {mediaActive && <button onClick={load} className="flex items-center gap-1 rounded-sm border border-blue-500/40 text-blue-400 px-2 py-1 text-xs"><RefreshCw className="w-3 h-3" /> Aggiorna</button>}
          {canGenerateMedia && isAdmin && (
            <button onClick={() => openPreview("media", cfg.mediaPreview)} disabled={busy}
              className="flex items-center gap-1.5 rounded-sm border border-amber-500/40 text-amber-400 px-2.5 py-1.5 text-xs">
              <Sparkles className="w-3.5 h-3.5" /> Genera {cfg.mediaKind === "video" ? "video" : "immagine"} (reale)
            </button>
          )}
          {/* mediaReady (status + URL non vuoto), MAI il solo status: un
              'pronto' senza asset reale non deve mai offrire l'approvazione
              (verificato anche lato backend, vedi domains/flyer.py). */}
          {mediaReady && (
            <>
              <button onClick={() => setReviseWhich("media")} className="flex items-center gap-1.5 rounded-sm border border-border px-2.5 py-1.5 text-xs">
                <MessageSquareWarning className="w-3.5 h-3.5" /> Richiedi modifica
              </button>
              {canApprove && !project[cfg.mediaApprovedField] && (
                <button onClick={() => approve(cfg.mediaApprove)} className="flex items-center gap-1.5 bg-primary text-primary-foreground rounded-sm px-2.5 py-1.5 text-xs">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Approva {cfg.mediaKind === "video" ? "video" : "immagine"}
                </button>
              )}
            </>
          )}
        </div>
        {(mediaStatus === "FALLITO" || mediaStatus === "BLOCCATO") && project.image_errore_messaggio && (
          <div className="text-xs rounded-sm border border-red-500/30 bg-red-500/10 text-red-400 px-3 py-2">
            [{project.image_errore_codice}] {project.image_errore_messaggio}
          </div>
        )}
        <MediaPlayer kind={cfg.mediaKind} src={mediaReady ? absoluteAssetUrl(project[cfg.mediaUrlField]) : null} status={mediaStatus} downloadable
          message={mediaActive ? "Generazione in corso." : mediaStatus === "FALLITO" ? "Generazione fallita (vedi errore sopra); il costo eventuale resta registrato nel budget." : "Nessun media ancora generato."} />
        {(project.generazione_immagine?.stima_costo_usd != null || project.generazione?.stima_costo_usd != null) && (
          <div className="text-[11px] text-muted-foreground font-mono">
            Costo testo: {project.generazione?.stima_costo_usd != null ? `$${project.generazione.stima_costo_usd}` : "non disponibile"}
            {project.generazione_immagine?.stima_costo_usd != null && <> · Costo immagine: ${project.generazione_immagine.stima_costo_usd}</>}
          </div>
        )}
      </div>

      {project.progetto_approvato && project[cfg.mediaApprovedField] && (
        <SocialPublishingPanel sourceKind={kind} sourceProjectId={projectId} />
      )}

      {preview && (
        <Modal onClose={() => setPreview(null)}>
          <h3 className="font-display text-base font-medium mb-2">Conferma chiamata reale</h3>
          <div className="text-xs space-y-1 mb-3">
            <div>Provider: <b>{preview.data.provider}</b></div>
            <div>Modello: <b>{preview.data.modello_effettivo || "—"}</b></div>
            {preview.data.budget_residuo != null && <div>Budget residuo: <b>${preview.data.budget_residuo}</b></div>}
            <div>Pronto: <b>{preview.data.pronto ? "Sì" : "No"}</b></div>
          </div>
          {!preview.data.pronto && <ul className="text-xs text-red-400 list-disc pl-4 mb-2">{preview.data.motivi.map((m, i) => <li key={i}>{m}</li>)}</ul>}
          <p className="text-xs text-muted-foreground mb-3">{preview.data.message}</p>
          <div className="flex gap-2">
            <button disabled={busy || !preview.data.pronto}
              onClick={() => confirmGenerate(preview.which, preview.which === "text" ? cfg.textGenerate : cfg.mediaGenerate)}
              className="bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm disabled:opacity-40">Conferma ed esegui</button>
            <button onClick={() => setPreview(null)} className="border border-border rounded-sm px-3 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}
      {reviseWhich && (
        <Modal onClose={() => setReviseWhich(null)}>
          <h3 className="font-display text-base font-medium mb-2">Richiedi modifica</h3>
          <textarea value={reviseNote} onChange={(e) => setReviseNote(e.target.value)} rows={3}
            className="w-full bg-background border border-border rounded-sm px-3 py-2 text-sm" />
          <div className="flex gap-2 mt-3">
            <button disabled={!reviseNote.trim()} onClick={submitRevise} className="bg-primary text-primary-foreground rounded-sm px-3 py-2 text-sm disabled:opacity-40">Invia</button>
            <button onClick={() => setReviseWhich(null)} className="border border-border rounded-sm px-3 py-2 text-sm">Annulla</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ShieldCheckOrAlert({ status }) {
  return status === "OK" ? <ShieldCheck className="w-4 h-4 text-emerald-400" /> : <ShieldAlert className="w-4 h-4 text-amber-400" />;
}
function Modal({ children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-sm p-5 w-full max-w-md shadow-xl" onClick={(e) => e.stopPropagation()}>{children}</div>
    </div>
  );
}
