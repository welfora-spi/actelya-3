import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { ArrowLeft, ShieldCheck, ScanSearch, Presentation } from "lucide-react";
import { ContentItemDeliverableItemsList } from "@/components/content-items/ContentItemDeliverablePreview";
import { derivePlanMode } from "@/lib/planMode";

// Stati espliciti del caricamento: mai un "Caricamento..." indefinito e mai
// un polling che continua a interrogare una risorsa che non tornerà mai
// utilizzabile (piano inesistente/vietato/sessione scaduta).
//   loading            -> primo caricamento in corso
//   loaded             -> dati presenti, polling attivo
//   unauthenticated    -> 401 (refresh già tentato e fallito, vedi lib/api.js)
//   forbidden          -> 403, piano di un'altra organizzazione/ruolo
//   not_found          -> 404, piano inesistente
//   transient_error    -> rete/5xx sul PRIMO caricamento (nessun dato ancora mostrato)
//   fatal_error        -> errore 4xx non altrimenti classificato
const VIEW = {
  LOADING: "loading", LOADED: "loaded", UNAUTHENTICATED: "unauthenticated",
  FORBIDDEN: "forbidden", NOT_FOUND: "not_found", TRANSIENT_ERROR: "transient_error",
  FATAL_ERROR: "fatal_error",
};
const TERMINAL_VIEWS = [VIEW.UNAUTHENTICATED, VIEW.FORBIDDEN, VIEW.NOT_FOUND, VIEW.TRANSIENT_ERROR, VIEW.FATAL_ERROR];
// Sottoinsieme che può coesistere con dati già caricati in precedenza
// (401/403/404/fatal su un piano che si era già aperto correttamente):
// TRANSIENT_ERROR, per costruzione in load(), scatta SOLO quando non è
// mai stato caricato nulla, quindi non compare mai qui.
const STALE_NOTICE_VIEWS = [VIEW.UNAUTHENTICATED, VIEW.FORBIDDEN, VIEW.NOT_FOUND, VIEW.FATAL_ERROR];

// deliverable_type -> campo array delle bozze indipendenti da decidere una a
// una (backend: m2/deliverable_review.py::MULTI_ITEM_FIELD, stessa mappa).
// Solo social_content oggi: editorial_plan e' un unico documento strategico
// interno, mai bozze distinte da approvare singolarmente.
const MULTI_ITEM_ARRAY_FIELD = { social_content: "posts" };

// Stessa classificazione di backend/app/domains/budget.py::
// _real_cost_per_execution_corretto: SOLO editorial_plan/social_content
// approvati in modalità REALE vengono davvero riconciliati al costo VERO
// (m2/engine.py::_apply_actual_cost_delta) dopo la chiamata al provider —
// per qualunque altro task (compreso content_item, il cui costo vero vive
// nel laboratorio Content Creator) "t.cost" resta solo la riserva stimata
// iniziale, mai un importo davvero addebitato: mai etichettato "sostenuto".
const TIPI_COSTO_RICONCILIATO = new Set(["editorial_plan", "social_content"]);
const costoRealeRiconciliato = (t) => TIPI_COSTO_RICONCILIATO.has(t.deliverable_type) && t.approved_mode === "REALE";

function PostCard({ content }) {
  return (
    <div className="text-xs text-muted-foreground space-y-0.5">
      {content?.hook && <div className="text-foreground font-medium">{content.hook}</div>}
      {content?.body && <div>{content.body}</div>}
      {content?.cta && <div className="italic">{content.cta}</div>}
      {content?.hashtags?.length > 0 && <div>{content.hashtags.join(" ")}</div>}
    </div>
  );
}

// Revisione editoriale UMANA sulle singole bozze di un deliverable
// multi-bozza — distinta dalle "Revisioni" automatiche non distruttive
// (compliance/auditor) mostrate subito sotto nello stesso pannello: qui si
// registra una DECISIONE (Approva/Rifiuta/Richiedi modifica) sulla VERSIONE
// corrente di ciascuna bozza, e — solo da una richiesta di modifica in
// attesa — si può applicare esplicitamente la modifica (con stima di costo
// e conferma PRIMA di ogni eventuale chiamata reale), producendo una nuova
// versione IN_ATTESA_REVISIONE, mai approvata automaticamente. Le versioni
// precedenti e le loro decisioni restano sempre consultabili nello storico.
function MultiItemDecisionList({ d, planId, canDecide, onChanged }) {
  const [busyIndex, setBusyIndex] = useState(null);
  const [preview, setPreview] = useState({}); // { [index]: {cost_probable, cost_max} | "loading" }
  const [openHistory, setOpenHistory] = useState({});
  const campo = MULTI_ITEM_ARRAY_FIELD[d.deliverable_type];
  const decisions = d.item_decisions || [];
  if (!campo) return null;

  const decide = async (index, decision, reason) => {
    setBusyIndex(index);
    try {
      await api.post(`/m2/plans/${planId}/deliverables/${d.id}/items/${index}/decision`, { decision, reason });
      toast.success("Decisione editoriale registrata.");
      await onChanged();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusyIndex(null); }
  };
  const chiediMotivoEDecidi = (index, decision, etichetta) => {
    const motivo = window.prompt(`Motivazione per "${etichetta}" (obbligatoria — una modifica editoriale concreta, non un pretesto):`);
    if (!motivo || !motivo.trim()) return;
    decide(index, decision, motivo.trim());
  };

  const mostraStimaModifica = async (index) => {
    setPreview((s) => ({ ...s, [index]: "loading" }));
    try {
      const { data } = await api.get(`/m2/plans/${planId}/deliverables/${d.id}/items/${index}/edit-cost`);
      setPreview((s) => ({ ...s, [index]: data }));
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
      setPreview((s) => { const n = { ...s }; delete n[index]; return n; });
    }
  };

  const applicaModifica = async (index) => {
    const stima = preview[index];
    const testoStima = stima && stima !== "loading"
      ? `Costo previsto: fino a $${stima.cost_max.toFixed(5)} (probabile $${stima.cost_probable.toFixed(5)}).`
      : "Stima non disponibile.";
    if (!window.confirm(`Applicare la modifica a questa bozza? ${testoStima}\n\nQuesta azione può comportare una chiamata reale a pagamento, entro il budget esistente.`)) {
      return;
    }
    setBusyIndex(index);
    try {
      await api.post(`/m2/plans/${planId}/deliverables/${d.id}/items/${index}/apply-edit`, { confirm: true });
      toast.success("Modifica applicata: nuova versione creata, in attesa di revisione.");
      setPreview((s) => { const n = { ...s }; delete n[index]; return n; });
      await onChanged();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusyIndex(null); }
  };

  return (
    <div className="space-y-2" data-testid={`item-decisions-${d.deliverable_type}`}>
      <div className="label-caps">Bozze e decisione editoriale ({decisions.length})</div>
      {decisions.map((it) => {
        const i = it.item_index;
        const dec = it.decision || { status: "IN_ATTESA_REVISIONE" };
        const decisa = dec.status !== "IN_ATTESA_REVISIONE";
        const stima = preview[i];
        return (
          <div key={i} className="border border-border/60 rounded-sm p-2.5 space-y-1.5"
            data-testid={`item-${d.deliverable_type}-${i}`}>
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <span className="text-xs font-medium">
                Bozza {i + 1}{it.content?.channel ? ` · ${it.content.channel}` : ""}
                {" "}<span className="text-muted-foreground font-mono text-[10px]" data-testid={`item-version-${d.deliverable_type}-${i}`}>v{it.current_version}</span>
              </span>
              <StatusBadge status={dec.status} testid={`item-status-${d.deliverable_type}-${i}`} />
            </div>
            <PostCard content={it.content} />
            {dec.reason && (
              <div className="text-[11px] text-amber-500" data-testid={`item-reason-${d.deliverable_type}-${i}`}>
                Motivazione: {dec.reason}
              </div>
            )}
            {dec.decided_by && (
              <div className="text-[11px] text-muted-foreground">
                Deciso da {dec.decided_by} il {dec.decided_at}
              </div>
            )}
            {canDecide && !decisa && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                <button data-testid={`item-approve-${d.deliverable_type}-${i}`} disabled={busyIndex === i}
                  onClick={() => decide(i, "APPROVATO", null)}
                  className="text-xs bg-primary text-primary-foreground rounded-sm px-2.5 py-1 hover:opacity-90 disabled:opacity-50">
                  Approva
                </button>
                <button data-testid={`item-reject-${d.deliverable_type}-${i}`} disabled={busyIndex === i}
                  onClick={() => chiediMotivoEDecidi(i, "RIFIUTATO", "Rifiuta")}
                  className="text-xs border border-red-500/40 text-red-400 rounded-sm px-2.5 py-1 hover:bg-red-500/10 disabled:opacity-50">
                  Rifiuta
                </button>
                <button data-testid={`item-request-changes-${d.deliverable_type}-${i}`} disabled={busyIndex === i}
                  onClick={() => chiediMotivoEDecidi(i, "MODIFICA_RICHIESTA", "Richiedi modifica")}
                  className="text-xs border border-border rounded-sm px-2.5 py-1 hover:bg-muted/50 disabled:opacity-50">
                  Richiedi modifica
                </button>
              </div>
            )}
            {canDecide && dec.status === "MODIFICA_RICHIESTA" && (
              <div className="pt-1.5 border-t border-border/40 mt-1.5 space-y-1.5" data-testid={`item-edit-pending-${d.deliverable_type}-${i}`}>
                <div className="text-[11px] text-amber-500">Lavoro ancora da svolgere: modifica richiesta, non ancora applicata.</div>
                <div className="flex items-center gap-1.5 flex-wrap">
                  {!stima && (
                    <button data-testid={`item-preview-edit-${d.deliverable_type}-${i}`} onClick={() => mostraStimaModifica(i)}
                      className="text-xs border border-border rounded-sm px-2.5 py-1 hover:bg-muted/50">
                      Mostra costo previsto
                    </button>
                  )}
                  {stima === "loading" && <span className="text-xs text-muted-foreground">Calcolo stima…</span>}
                  {stima && stima !== "loading" && (
                    <>
                      <span className="text-[11px] font-mono text-muted-foreground" data-testid={`item-edit-cost-${d.deliverable_type}-${i}`}>
                        fino a ${stima.cost_max.toFixed(5)}
                      </span>
                      <button data-testid={`item-apply-edit-${d.deliverable_type}-${i}`} disabled={busyIndex === i}
                        onClick={() => applicaModifica(i)}
                        className="text-xs bg-primary text-primary-foreground rounded-sm px-2.5 py-1 hover:opacity-90 disabled:opacity-50">
                        Applica modifica (nuova versione)
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
            {it.history?.length > 0 && (
              <div className="pt-1">
                <button className="text-[11px] text-muted-foreground hover:text-foreground"
                  data-testid={`item-history-toggle-${d.deliverable_type}-${i}`}
                  onClick={() => setOpenHistory((s) => ({ ...s, [i]: !s[i] }))}>
                  {openHistory[i] ? "Nascondi" : "Mostra"} versioni precedenti ({it.history.length})
                </button>
                {openHistory[i] && (
                  <div className="mt-1.5 space-y-1.5" data-testid={`item-history-${d.deliverable_type}-${i}`}>
                    {it.history.map((h) => (
                      <div key={h.version} className="border border-border/40 rounded-sm p-2 bg-muted/20">
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                          <span className="text-[11px] font-mono text-muted-foreground">v{h.version}{h.edit_note ? ` · modifica: ${h.edit_note}` : ""}</span>
                          <StatusBadge status={h.decision?.status || "IN_ATTESA_REVISIONE"} />
                        </div>
                        <PostCard content={h.content} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function PlanDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { hasRole } = useAuth();
  const [data, setData] = useState(null);
  const [delivs, setDelivs] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState("");
  const [openDeliv, setOpenDeliv] = useState({});
  const [view, setView] = useState(VIEW.LOADING);
  const timerRef = useRef(null);
  const hasDataRef = useRef(false);

  const canApprove = hasRole("APPROVATORE", "ADMIN");
  const canReject = hasRole("APPROVATORE", "ADMIN");
  const canRun = hasRole("OPERATORE", "APPROVATORE", "ADMIN");
  const canStop = hasRole("ADMIN");

  const stopPolling = () => { if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; } };

  const load = useCallback(async () => {
    try {
      const [p, d, r] = await Promise.all([
        api.get(`/m2/plans/${id}`),
        api.get(`/m2/plans/${id}/deliverables`),
        api.get(`/m2/plans/${id}/reviews`),
      ]);
      setData(p.data); setDelivs(d.data.deliverables); setReviews(r.data.reviews);
      hasDataRef.current = true;
      setView(VIEW.LOADED);
      if (["COMPLETATO", "BLOCCATO", "ANNULLATO"].includes(p.data.plan?.plan_status)) stopPolling();
    } catch (e) {
      const code = e.response?.status;
      // 401/403/404 sono definitivi per questa risorsa: interrompono SEMPRE
      // il polling, anche se un caricamento precedente era riuscito.
      if (code === 401) { setView(VIEW.UNAUTHENTICATED); stopPolling(); return; }
      if (code === 403) { setView(VIEW.FORBIDDEN); stopPolling(); return; }
      if (code === 404) { setView(VIEW.NOT_FOUND); stopPolling(); return; }
      if (!code || code >= 500) {
        // Rete/5xx: se un caricamento era già riuscito in precedenza, resta
        // un blip transitorio del polling in corso (comportamento esistente,
        // invariato) — solo sul PRIMO caricamento (nessun dato mai mostrato)
        // si esce dal polling automatico e si chiede un retry esplicito,
        // per non lasciare l'utente su "Caricamento..." all'infinito.
        if (!hasDataRef.current) { setView(VIEW.TRANSIENT_ERROR); stopPolling(); }
        return;
      }
      // Altro errore 4xx (400/409/422/...): definitivo, non riprovabile da
      // solo, nessun retry automatico.
      setView(VIEW.FATAL_ERROR);
      stopPolling();
    }
  }, [id]);

  const retry = useCallback(() => {
    setView(VIEW.LOADING);
    load();
    if (!timerRef.current) timerRef.current = setInterval(load, 3000);
  }, [load]);

  useEffect(() => {
    hasDataRef.current = false;
    setData(null);
    setView(VIEW.LOADING);
    load();
    timerRef.current = setInterval(load, 3000);
    return () => stopPolling();
  }, [load]);

  const act = async (fn, ok) => {
    setBusy(true);
    try { await fn(); if (ok) toast.success(ok); await load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const approvePlan = () => act(() => api.post(`/m2/plans/${id}/approve`), "Piano approvato");
  const approveTask = (tid) => act(() => api.post(`/m2/plans/${id}/tasks/${tid}/approve`), "Attività approvata");
  const tick = () => act(() => api.post(`/m2/plans/${id}/tick`), "Esecuzione avanzata");
  const stop = () => act(() => api.post(`/m2/plans/${id}/stop`), "Piano arrestato");
  const confirmReject = (tid) =>
    act(async () => { await api.post(`/m2/plans/${id}/tasks/${tid}/reject`, { reason }); setRejecting(null); setReason(""); }, "Attività rifiutata");

  if (view === VIEW.LOADING && !data) {
    return <div className="text-sm text-muted-foreground" data-testid="plan-state-loading">Caricamento…</div>;
  }

  if (TERMINAL_VIEWS.includes(view) && !hasDataRef.current) {
    const NOTICE = {
      [VIEW.UNAUTHENTICATED]: {
        testid: "plan-session-expired",
        text: "Sessione scaduta: accedi di nuovo per continuare a vedere questo piano.",
        retryable: false,
      },
      [VIEW.FORBIDDEN]: {
        testid: "plan-forbidden",
        text: "Non hai i permessi per accedere a questo piano.",
        retryable: false,
      },
      [VIEW.NOT_FOUND]: {
        testid: "plan-not-found",
        text: "Questo piano non esiste (più).",
        retryable: false,
      },
      [VIEW.TRANSIENT_ERROR]: {
        testid: "plan-transient-error",
        text: "Errore temporaneo di rete: non è stato possibile caricare il piano.",
        retryable: true,
      },
      [VIEW.FATAL_ERROR]: {
        testid: "plan-fatal-error",
        text: "Si è verificato un errore imprevisto nel caricare il piano.",
        retryable: true,
      },
    }[view];
    return (
      <div data-testid="plan-state-notice" className="text-sm border border-amber-500/30 bg-amber-500/10 text-amber-500 rounded-sm px-4 py-3 space-y-3">
        <div data-testid={NOTICE.testid}>{NOTICE.text}</div>
        <div className="flex items-center gap-3">
          <button data-testid="plan-state-back" onClick={() => navigate("/piani")}
            className="text-xs border border-border rounded-sm px-2.5 py-1 hover:bg-muted/50 active:scale-[0.98] transition-colors">
            Torna ai piani
          </button>
          {NOTICE.retryable && (
            <button data-testid="plan-state-retry" onClick={retry}
              className="text-xs bg-primary text-primary-foreground rounded-sm px-2.5 py-1 hover:opacity-90 active:scale-[0.98] transition-colors">
              Riprova
            </button>
          )}
        </div>
      </div>
    );
  }

  if (!data) return <div className="text-sm text-muted-foreground" data-testid="plan-state-loading">Caricamento…</div>;
  const { plan, tasks, execution, mode } = data;
  const seqById = Object.fromEntries(tasks.map((t) => [t.id, t.seq]));
  const reviewsByDeliv = reviews.reduce((m, r) => { (m[r.deliverable_id] = m[r.deliverable_id] || []).push(r); return m; }, {});
  const notCompleted = plan.plan_status === "BLOCCATO";
  const realReady = !!mode?.real_ready;
  // Modalità del PIANO (intestazione, preventivo, Sala Riunioni): derivata
  // dai suoi task, mai dalla sola impostazione ai_real_mode corrente
  // dell'organizzazione (vedi lib/planMode.js) — quest'ultima resta invece
  // corretta per 'mode?.real_ready' sopra, che riguarda davvero
  // l'organizzazione ORA (se il percorso reale e' disponibile per
  // l'esecuzione), un concetto diverso dalla modalità con cui QUESTO piano
  // e' stato configurato.
  const planMode = derivePlanMode(tasks);
  const modeLabel = planMode.label;
  const runLabel = realReady ? "Esegui (reale)" : "Esegui (simulazione)";

  return (
    <div data-testid="plan-detail">
      <button onClick={() => navigate("/piani")} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-4 transition-colors">
        <ArrowLeft className="w-4 h-4" /> Torna ai piani
      </button>

      <PageHeader
        title={<span className="flex items-center gap-3">{plan.objective_type}<StatusBadge status={plan.plan_status} testid="plan-detail-status" /></span>}
        subtitle={`Versione v${plan.version} · modalità ${modeLabel} · una sola esecuzione per versione`}
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            {plan.active_agent_ids?.length > 0 && (
              <button data-testid="plan-sala-riunioni-btn" onClick={() => navigate(`/sala-riunioni?planId=${plan.id}`)}
                className="flex items-center gap-1.5 border border-border rounded-sm px-3 py-1.5 text-sm hover:bg-muted/50 active:scale-[0.98] transition-colors">
                <Presentation className="w-3.5 h-3.5" /> Sala riunioni
              </button>
            )}
            {canApprove && <button data-testid="approve-plan-btn" onClick={approvePlan} disabled={busy}
              className="bg-emerald-600 text-white rounded-sm px-3 py-1.5 text-sm font-medium hover:bg-emerald-500 active:scale-[0.98] disabled:opacity-50 transition-colors">Approva piano</button>}
            {canRun && <button data-testid="tick-btn" onClick={tick} disabled={busy}
              className="bg-primary text-primary-foreground rounded-sm px-3 py-1.5 text-sm font-medium hover:opacity-90 active:scale-[0.98] disabled:opacity-50 transition-colors">{runLabel}</button>}
            {canStop && <button data-testid="stop-btn" onClick={stop} disabled={busy}
              className="border border-red-500/40 text-red-400 rounded-sm px-3 py-1.5 text-sm hover:bg-red-500/10 active:scale-[0.98] disabled:opacity-50 transition-colors">Arresta</button>}
          </div>
        }
      />

      {STALE_NOTICE_VIEWS.includes(view) && (
        <div data-testid="plan-stale-notice" className="mb-4 text-sm border border-amber-500/30 bg-amber-500/10 text-amber-500 rounded-sm px-4 py-2.5">
          {view === VIEW.UNAUTHENTICATED && "Sessione scaduta: i dati mostrati sotto non si aggiornano più. Accedi di nuovo per riprendere da qui."}
          {view === VIEW.FORBIDDEN && "Accesso non più consentito a questo piano: i dati mostrati sotto sono gli ultimi disponibili."}
          {view === VIEW.NOT_FOUND && "Questo piano non risulta più esistente: i dati mostrati sotto sono gli ultimi disponibili."}
          {view === VIEW.FATAL_ERROR && "Si è verificato un errore nell'ultimo aggiornamento: i dati mostrati sotto potrebbero non essere recenti."}
        </div>
      )}

      {mode?.ai_real_mode && !realReady && mode?.real_eligible_tasks_approved_real > 0 && (
        <div data-testid="plan-real-not-ready" className="mb-4 text-sm border border-amber-500/30 bg-amber-500/10 text-amber-500 rounded-sm px-4 py-2.5">
          Percorso reale non ancora disponibile per questo piano: {(mode.reasons || []).join("; ") || "verifica connessione e budget."}
          {" "}Le attività reali resteranno bloccate (mai completate in simulazione silenziosa) finché non risolto.
        </div>
      )}

      {notCompleted && (
        <div data-testid="plan-not-completed" className="mb-4 text-sm border border-red-500/30 bg-red-500/10 text-red-400 rounded-sm px-4 py-2.5">
          Esecuzione terminata, risultato <b>non completato</b>: alcune attività sono bloccate o saltate.
        </div>
      )}

      {/* Preventivo visibile PRIMA dell'approvazione: nessuna esecuzione
          esiste ancora a questo punto (il blocco 'execution' sotto compare
          solo dopo), quindi e' l'UNICO punto dove l'utente puo' vedere
          stima e tetto prima di autorizzare la spesa — stessi campi
          (plan.estimate, plan.approved_cap) usati anche in Sala Riunioni
          (vedi CollaboratorPanel.jsx), mai una seconda logica di calcolo. */}
      {plan.plan_status === "IN_ATTESA_APPROVAZIONE" && (() => {
        const stimaStorica = plan.estimate?.cost_probable ?? 0;
        const tetto = plan.approved_cap ?? 0;
        // Stima ricostruita dai task ATTUALI del piano (somma di
        // task.inputs.cost, la stessa cifra riservata sul tetto per
        // ciascuno — vedi PlanInsightsPanel/riga per-task sotto): MAI la
        // stima storica del piano (plan.estimate), che puo' restare quella
        // calcolata al momento della creazione anche se un task e' stato
        // aggiunto dopo senza aggiornarla (vedi brain/service.py, blocco
        // 'content'). Etichettata esplicitamente come ricostruzione, mai
        // spacciata per la stima originale.
        const stimaRicostruita = tasks.reduce((tot, t) => tot + (t.inputs?.cost ?? 0), 0);
        const stimaStoricaNonAggiornata = Math.abs(stimaStorica - stimaRicostruita) > 1e-9;
        return (
          <Card className="p-4 mb-4" data-testid="plan-preventivo">
            <div className="label-caps mb-2">Preventivo</div>
            <div className="flex items-center gap-6 flex-wrap text-sm">
              <span>Stima storica del piano <span className="font-mono" data-testid="plan-estimate-probable">${stimaStorica.toFixed(5)}</span></span>
              <span>Tetto che approvi <span className="font-mono" data-testid="plan-approved-cap">${tetto.toFixed(5)}</span></span>
              <span className="text-xs text-muted-foreground">
                margine {(plan.estimate?.safety_margin != null) ? `${Math.round(plan.estimate.safety_margin * 100)}%` : "n/d"} · {plan.estimate?.currency || "USD"} · modalità {modeLabel}
              </span>
            </div>
            {stimaStoricaNonAggiornata && (
              <div className="mt-2 text-xs text-amber-500" data-testid="plan-estimate-stale-notice">
                La stima storica (${stimaStorica.toFixed(5)}) non è stata aggiornata quando un'attività è stata
                collegata al piano dopo la stima iniziale — non riflette il costo reale previsto. Stima ricostruita
                ora dai task attuali (somma di tutte le attività del piano): <span className="font-mono" data-testid="plan-estimate-reconstructed">${stimaRicostruita.toFixed(5)}</span>.
              </div>
            )}
            {tetto === 0 && (
              <div className="mt-2 text-xs text-amber-500" data-testid="plan-zero-cap-warning">
                Tetto a $0.00000: il preventivo non prevede alcuna spesa reale. Se il piano include attività a
                pagamento, verificare i singoli task sotto prima di approvare.
              </div>
            )}
          </Card>
        );
      })()}

      {execution && (
        <Card className="p-4 mb-4">
          <div className="flex items-center gap-6 flex-wrap text-sm">
            <span className="flex items-center gap-2"><span className="label-caps">Esecuzione</span><StatusBadge status={execution.execution_status} /></span>
            <span className="flex items-center gap-2"><span className="label-caps">Deliverable</span><StatusBadge status={execution.deliverable_status} /></span>
            <span className="flex items-center gap-2"><span className="label-caps">{modeLabel === "REALE" ? "Costo (stima da token reali)" : "Costo simulato"}</span><span className="font-mono">${(execution.real_cost ?? 0).toFixed(5)} / cap ${(execution.approved_cap ?? 0).toFixed(5)}</span></span>
          </div>
        </Card>
      )}

      {/* Attività (DAG) */}
      <Card className="p-5 mb-4">
        <h2 className="font-display text-lg font-medium mb-3">Attività ({tasks.length}) — DAG</h2>
        <div className="space-y-2" data-testid="tasks-list">
          {tasks.map((t) => (
            <div key={t.id} data-testid={`task-${t.seq}`} className="border border-border/60 rounded-sm px-3 py-2.5">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-muted-foreground">#{t.seq}</span>
                    <span className="text-sm font-medium truncate">{t.name}</span>
                    <StatusBadge status={t.task_status} testid={`task-status-${t.seq}`} />
                  </div>
                  <div className="text-[11px] text-muted-foreground font-mono mt-1">
                    {t.deliverable_type} · agente {t.agent_id} · tent. {t.attempt}
                    {t.inputs?.requested_quantity != null ? ` · quantità ${t.inputs.requested_quantity}` : ""}
                    {" · stima "}
                    <span data-testid={`task-cost-estimate-${t.seq}`}>${(t.inputs?.cost ?? 0).toFixed(5)}</span>
                    {costoRealeRiconciliato(t) ? " · sostenuto " : " · impegnato (stima, non ancora una spesa reale addebitata) "}
                    <span data-testid={`task-cost-sostenuto-${t.seq}`}>${(t.cost ?? 0).toFixed(5)}</span>
                    {t.depends_on?.length ? ` · dipende da #${t.depends_on.map((d) => seqById[d]).join(", #")}` : " · nessuna dipendenza"}
                  </div>
                  {t.rejected_reason && <div className="text-[11px] text-red-400 mt-1">Rifiutata: {t.rejected_reason}</div>}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {canApprove && !t.approved && !["COMPLETATA", "FALLITA", "BLOCCATA", "SALTATA"].includes(t.task_status) && (
                    <button data-testid={`approve-task-${t.seq}`} onClick={() => approveTask(t.id)} disabled={busy}
                      className="text-xs bg-emerald-600 text-white rounded-sm px-2.5 py-1 hover:bg-emerald-500 active:scale-[0.98] disabled:opacity-50 transition-colors">Approva</button>
                  )}
                  {canReject && !["COMPLETATA", "FALLITA", "BLOCCATA", "SALTATA"].includes(t.task_status) && (
                    <button data-testid={`reject-task-${t.seq}`} onClick={() => { setRejecting(t.id); setReason(""); }} disabled={busy}
                      className="text-xs border border-red-500/40 text-red-400 rounded-sm px-2.5 py-1 hover:bg-red-500/10 active:scale-[0.98] disabled:opacity-50 transition-colors">Rifiuta</button>
                  )}
                </div>
              </div>
              {rejecting === t.id && (
                <div data-testid={`reject-form-${t.seq}`} className="mt-2 border-t border-border/60 pt-2">
                  <textarea data-testid={`reject-reason-${t.seq}`} value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
                    placeholder="Motivazione obbligatoria del rifiuto…"
                    className="w-full bg-background border border-border rounded-sm px-2 py-1.5 text-xs focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none resize-none" />
                  <div className="flex items-center gap-2 mt-2">
                    <button data-testid={`reject-confirm-${t.seq}`} onClick={() => confirmReject(t.id)} disabled={busy || !reason.trim()}
                      className="text-xs bg-red-600 text-white rounded-sm px-2.5 py-1 hover:bg-red-500 active:scale-[0.98] disabled:opacity-50 transition-colors">Conferma rifiuto</button>
                    <button onClick={() => { setRejecting(null); setReason(""); }} className="text-xs text-muted-foreground hover:text-foreground">Annulla</button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>

      {/* Deliverable + Revisioni */}
      <Card className="p-5">
        <h2 className="font-display text-lg font-medium mb-3">Deliverable & Revisioni</h2>
        {delivs.length === 0 && <Empty text="Nessun deliverable ancora prodotto. Approva ed esegui il piano." />}
        <div className="space-y-3" data-testid="deliverables-list">
          {delivs.filter((d) => d.is_current).map((d) => {
            const revs = reviewsByDeliv[d.id] || [];
            const open = openDeliv[d.id];
            return (
              <div key={d.id} data-testid={`deliverable-${d.deliverable_type}`} className="border border-border/60 rounded-sm">
                <div className="flex items-center justify-between gap-2 px-3 py-2.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium">{d.deliverable_type}</span>
                    <StatusBadge status={d.status} testid={`deliv-status-${d.deliverable_type}`} />
                    <span data-testid={`deliv-mode-${d.deliverable_type}`}
                      className={`text-[10px] font-mono px-1.5 py-0.5 rounded-sm ${d.mode === "REALE" ? "bg-emerald-500/15 text-emerald-500" : "bg-muted text-muted-foreground"}`}>
                      {d.mode === "REALE" ? "REALE" : "SIMULAZIONE"}
                    </span>
                    <span className="text-[10px] font-mono text-muted-foreground">v{d.version}{d.valid ? "" : " · non valido"}</span>
                  </div>
                  <button data-testid={`deliv-toggle-${d.deliverable_type}`} onClick={() => setOpenDeliv((s) => ({ ...s, [d.id]: !s[d.id] }))}
                    className="text-xs text-muted-foreground hover:text-foreground">{open ? "Nascondi" : "Mostra"}</button>
                </div>
                {open && (
                  <div className="px-3 pb-3 space-y-3">
                    {d.mode === "REALE" && d.generation && (
                      <div data-testid={`deliv-generation-${d.deliverable_type}`} className="text-[11px] text-muted-foreground font-mono border border-border/60 rounded-sm px-2.5 py-2">
                        provider {d.generation.provider} · modello {d.generation.modello_effettivo} · token {d.generation.input_tokens}/{d.generation.output_tokens}
                        {d.generation.stima_costo_usd != null ? ` · $${Number(d.generation.stima_costo_usd).toFixed(5)}` : ""}
                      </div>
                    )}
                    {d.deliverable_type === "content_item" ? (
                      <ContentItemDeliverableItemsList d={d} />
                    ) : MULTI_ITEM_ARRAY_FIELD[d.deliverable_type] ? (
                      <MultiItemDecisionList d={d} planId={id} canDecide={canApprove} onChanged={load} />
                    ) : (
                      <pre className="bg-background border border-border/60 rounded-sm p-3 text-[11px] overflow-auto max-h-72 whitespace-pre-wrap break-words">
                        {JSON.stringify(d.content, null, 2)}
                      </pre>
                    )}
                    <div className="space-y-1.5" data-testid={`reviews-${d.deliverable_type}`}>
                      <div className="label-caps">Revisioni (non distruttive)</div>
                      {revs.length === 0 && <div className="text-xs text-muted-foreground">Nessuna revisione.</div>}
                      {revs.map((r) => (
                        <div key={r.id} className="border border-border/60 rounded-sm px-2.5 py-2">
                          <div className="flex items-center gap-2 mb-1">
                            {r.review_type === "compliance" ? <ShieldCheck className="w-3.5 h-3.5 text-muted-foreground" /> : <ScanSearch className="w-3.5 h-3.5 text-muted-foreground" />}
                            <span className="text-xs font-medium">{r.reviewer_agent}</span>
                            <StatusBadge status={r.severity} testid={`review-sev-${d.deliverable_type}-${r.review_type}`} />
                          </div>
                          <ul className="text-[11px] text-muted-foreground space-y-0.5 ml-1">
                            {(r.findings || []).map((f, i) => (
                              <li key={i}><span className="font-mono text-[10px]">[{f.code}]</span> {f.message}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
