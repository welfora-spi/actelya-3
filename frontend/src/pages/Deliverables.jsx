import { useEffect, useState } from "react";
import api from "@/lib/api";
import { PageHeader, Card, Empty } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { EmailPreview } from "@/pages/Executions";
import MultimodalProjectPanel from "@/components/MultimodalProjectPanel";
import { ContentItemDeliverablePreview } from "@/components/content-items/ContentItemDeliverablePreview";

// Deliverable multimodale (video/immagine) prodotto da una skill REALE (vedi
// brain/skills.py): renderizzato QUI, per intero (contenuto, verifica
// semantica, generazione/approvazione) tramite il renderer universale
// condiviso con Sala Riunioni -- MAI solo un rimando a una pagina laboratorio.
const REAL_SKILL_PANEL_KIND = { video_reel_project: "reel", flyer_project: "flyer" };

function RealSkillDeliverableCard({ d }) {
  const kind = REAL_SKILL_PANEL_KIND[d.deliverable_type];
  const projectId = d.content?.reel_project_id || d.content?.flyer_project_id;
  return (
    <Card className="p-5">
      <MultimodalProjectPanel kind={kind} projectId={projectId} />
    </Card>
  );
}

// editorial_plan/social_content (M2) non sono email: campi propri (calendario
// editoriale / post con hook+body+cta+hashtag), mai oggetto/contenuto_completo.
// Anteprima minima e leggibile dedicata, invece del renderer email generico
// (che li mostrava con "Oggetto"/corpo sempre vuoti — nessun campo in comune).
function EditorialPlanPreview({ d }) {
  const c = d.content || {};
  return (
    <Card className="p-0 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border/60 bg-muted/30">
        <span className="label-caps">Piano editoriale</span>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded-sm ${d.mode === "REALE" ? "bg-emerald-500/15 text-emerald-500" : "bg-muted text-muted-foreground"}`}>
            {d.mode === "REALE" ? "REALE" : "SIMULAZIONE"}
          </span>
          <StatusBadge status={d.status} testid="deliverable-status-badge" />
        </div>
      </div>
      <div className="p-5 space-y-3" data-testid="editorial-plan-preview">
        <div><span className="label-caps">Titolo</span><div className="text-sm font-medium mt-0.5">{c.title}</div></div>
        <div className="flex gap-6 text-sm">
          <div><span className="label-caps">Cadenza</span><div className="mt-0.5">{c.cadence}</div></div>
        </div>
        <div><span className="label-caps">Tono di voce</span><div className="text-sm mt-0.5 text-foreground/90">{c.tone_of_voice}</div></div>
        {c.pillars?.length > 0 && (
          <div><span className="label-caps">Pilastri</span>
            <ul className="text-sm mt-1 list-disc pl-4 space-y-0.5">{c.pillars.map((p, i) => <li key={i}>{p}</li>)}</ul>
          </div>
        )}
        {c.calendar?.length > 0 && (
          <div><span className="label-caps">Calendario</span>
            <div className="mt-1 space-y-1.5">
              {c.calendar.map((item, i) => (
                <div key={i} className="text-sm border-l-2 border-border pl-3">
                  <span className="font-medium">{item.slot}</span> — {item.topic}
                  <span className="text-xs text-muted-foreground"> ({item.format} · {item.channel})</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {d.warnings?.length > 0 && <div className="text-xs text-yellow-400">Avvisi: {d.warnings.join(" ")}</div>}
      </div>
    </Card>
  );
}

function SocialContentPreview({ d }) {
  const c = d.content || {};
  return (
    <Card className="p-0 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border/60 bg-muted/30">
        <span className="label-caps">Post social — {c.platform}</span>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded-sm ${d.mode === "REALE" ? "bg-emerald-500/15 text-emerald-500" : "bg-muted text-muted-foreground"}`}>
            {d.mode === "REALE" ? "REALE" : "SIMULAZIONE"}
          </span>
          <StatusBadge status={d.status} testid="deliverable-status-badge" />
        </div>
      </div>
      <div className="p-5 space-y-3" data-testid="social-content-preview">
        {(c.posts || []).map((p, i) => (
          <div key={i} className="border border-border/60 rounded-sm px-3 py-2.5 space-y-1.5">
            <div className="text-sm font-medium">{p.hook}</div>
            <div className="text-sm text-foreground/90 whitespace-pre-wrap">{p.body}</div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              {p.channel && <span>Canale: {p.channel}</span>}
              {p.cta && <span>CTA: {p.cta}</span>}
              {p.objective && <span>Obiettivo: {p.objective}</span>}
              {p.success_metric && <span>Criterio di successo (simulato): {p.success_metric}</span>}
            </div>
            {p.hashtags?.length > 0 && <div className="text-xs text-primary">{p.hashtags.join(" ")}</div>}
          </div>
        ))}
        {d.warnings?.length > 0 && <div className="text-xs text-yellow-400">Avvisi: {d.warnings.join(" ")}</div>}
      </div>
    </Card>
  );
}

const CUSTOM_PREVIEW = {
  editorial_plan: EditorialPlanPreview, social_content: SocialContentPreview,
  content_item: ContentItemDeliverablePreview,
};

// EmailPreview legge SOLO campi a forma di email (oggetto/contenuto_completo/
// cta, vedi pages/Executions.jsx): usarlo per un tipo diverso produce una
// scheda "vuota" fuorviante (campi sempre assenti), non un'anteprima onesta.
// Va usato SOLO per il tipo che ha davvero quella forma.
const EMAIL_SHAPED_TYPES = new Set(["email"]);

// Fallback neutro per un deliverable_type senza renderer dedicato: mai
// EmailPreview come jolly universale. Mostra ciò che il payload contiene
// davvero (titolo/testo se presenti, altrimenti la struttura grezza) invece
// di dichiarare "vuoto" un contenuto solo perché non c'è un renderer
// specifico per quella forma.
function GenericDeliverablePreview({ d }) {
  const c = d.content && typeof d.content === "object" ? d.content : {};
  const title = c.title || c.titolo || c.nome || c.subject || c.oggetto || null;
  const text = c.contenuto_completo || c.body || c.body_text || c.testo || c.summary || c.description || null;
  const hasStructured = Object.keys(c).length > 0;
  return (
    <Card className="p-0 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border/60 bg-muted/30">
        <span className="label-caps">{d.deliverable_type}</span>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded-sm ${d.mode === "REALE" ? "bg-emerald-500/15 text-emerald-500" : "bg-muted text-muted-foreground"}`}>
            {d.mode === "REALE" ? "REALE" : "SIMULAZIONE"}
          </span>
          <StatusBadge status={d.status} testid="deliverable-status-badge" />
        </div>
      </div>
      <div className="p-5 space-y-3" data-testid="generic-deliverable-preview">
        <div className="text-xs text-muted-foreground">Anteprima specifica non disponibile per questo tipo di deliverable.</div>
        {title && <div><span className="label-caps">Titolo</span><div className="text-sm font-medium mt-0.5">{title}</div></div>}
        {text && <div className="whitespace-pre-wrap text-sm text-foreground/90 border-l-2 border-border pl-4">{text}</div>}
        {!text && hasStructured && (
          <details>
            <summary className="text-xs text-muted-foreground cursor-pointer">Contenuto grezzo</summary>
            <pre className="mt-2 bg-background border border-border/60 rounded-sm p-3 text-[11px] overflow-auto max-h-72 whitespace-pre-wrap break-words">
              {JSON.stringify(c, null, 2)}
            </pre>
          </details>
        )}
        {!text && !hasStructured && <div className="text-xs text-muted-foreground" data-testid="generic-deliverable-empty">Nessun contenuto ricevuto per questo deliverable.</div>}
        {d.warnings?.length > 0 && <div className="text-xs text-yellow-400">Avvisi: {d.warnings.join(" ")}</div>}
      </div>
    </Card>
  );
}

// Riepilogo di sola lettura dello stato editoriale di ciascuna bozza di un
// deliverable multi-item (es. social_content) — la decisione si registra in
// Piani (dettaglio piano), qui serve solo a rendere lo stato visibile anche
// da Risultati, cosi' le due pagine non mostrano mai informazioni diverse
// sulla stessa bozza (vedi m2/deliverable_review.py).
function ItemDecisionsSummary({ decisions }) {
  if (!decisions?.length) return null;
  return (
    <div className="px-4 py-2.5 border-t border-border/60 space-y-1" data-testid="item-decisions-summary">
      <div className="label-caps">Stato editoriale bozze</div>
      {decisions.map((it) => (
        <div key={it.item_index} className="flex items-center justify-between gap-2 text-xs"
          data-testid={`item-decisions-summary-row-${it.item_index}`}>
          <span className="text-muted-foreground">Bozza {it.item_index + 1} · v{it.current_version}</span>
          <StatusBadge status={it.decision?.status || "IN_ATTESA_REVISIONE"} />
        </div>
      ))}
    </div>
  );
}

function deliverablePreview(d) {
  const corpo = REAL_SKILL_PANEL_KIND[d.deliverable_type] ? <RealSkillDeliverableCard d={d} />
    : CUSTOM_PREVIEW[d.deliverable_type] ? (() => { const Custom = CUSTOM_PREVIEW[d.deliverable_type]; return <Custom d={d} />; })()
    : EMAIL_SHAPED_TYPES.has(d.deliverable_type) ? <EmailPreview d={d} />
    : <GenericDeliverablePreview d={d} />;
  return (
    <div key={d.id}>
      {corpo}
      <ItemDecisionsSummary decisions={d.item_decisions} />
    </div>
  );
}

export default function Deliverables() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/deliverables").then((r) => setRows(r.data)).catch(() => {}); }, []);
  return (
    <div>
      <PageHeader title="Deliverable / Contenuti"
        subtitle="Solo i deliverable persistiti e validi sono conteggiati come contenuto prodotto." />
      {rows.length === 0 ? <Empty text="Nessun deliverable prodotto." /> : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="deliverables-list">
          {rows.map(deliverablePreview)}
        </div>
      )}
    </div>
  );
}
