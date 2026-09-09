import { Link } from "react-router-dom";
import { Card } from "@/components/Primitives";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { ContentItemBody, ContentItemStatusNotices } from "@/components/content-items/ContentItemBody";

// Deliverable 'content_item' (Content Creator): il task M2 referenzia N
// content_item tramite 'content_item_ids', ciascuno con il proprio
// content/stato/contestazione. Un id referenziato ma assente dal payload
// (mai osservato con l'attuale contratto backend, ma non escludibile per
// costruzione) mostra un avviso esplicito — mai una scheda vuota, ne'
// approvata, ne' completata.
//
// Esportato in due forme cosi' la STESSA lista di elementi si usa sia dove
// serve una scheda autonoma con intestazione (Risultati/Deliverables.jsx,
// come gli altri CUSTOM_PREVIEW) sia dove l'intestazione (stato/modalita'/
// versione) e' gia' mostrata dal contenitore (dettaglio piano/PlanDetail.jsx)
// — mai due logiche diverse per leggere content_item_ids/items/contested_ids.
export function ContentItemDeliverableItemsList({ d }) {
  const { hasRole } = useAuth() || {};
  // /content-creator e' una route riservata (App.js: ADMIN_ONLY): il
  // collegamento diretto si mostra solo a chi puo' davvero raggiungerla,
  // mai un rimando che porta a un redirect fuori pagina.
  const canOpenLab = typeof hasRole === "function" && hasRole("ADMIN");
  const c = d.content && typeof d.content === "object" ? d.content : {};
  const items = Array.isArray(c.items) ? c.items : [];
  const byId = new Map(items.map((it) => [it.content_item_id, it]));
  const ids = Array.isArray(c.content_item_ids) && c.content_item_ids.length > 0
    ? c.content_item_ids
    : items.map((it) => it.content_item_id);
  const contestedIds = new Set(c.contested_ids || []);

  return (
    <div className="space-y-4" data-testid="content-item-deliverable-preview">
      {ids.length === 0 && (
        <div className="text-xs text-muted-foreground" data-testid="content-item-deliverable-empty">
          Nessun content_item referenziato da questo deliverable.
        </div>
      )}
      {ids.map((id, idx) => {
        const item = byId.get(id);
        if (!item) {
          return (
            <div key={id || idx} className="border border-red-500/30 bg-red-500/5 rounded-sm px-3 py-2.5 text-xs text-red-400"
              data-testid="content-item-unavailable">
              Contenuto {id || `#${idx + 1}`} non disponibile: referenziato dal task ma assente in questo deliverable.
              Non è né vuoto né approvato — verificare nel laboratorio Content Creator.
            </div>
          );
        }
        return (
          <div key={id} className="border border-border/60 rounded-sm px-3 py-2.5" data-testid={`content-item-${id}`}>
            <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
              <span className="text-xs font-medium">{item.content_type}</span>
              <div className="flex items-center gap-2">
                <StatusBadge status={item.status} testid={`content-item-status-${id}`} />
                {contestedIds.has(id) && (
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-sm bg-amber-500/15 text-amber-500"
                    data-testid={`content-item-contested-badge-${id}`}>CONTESTATO</span>
                )}
                {canOpenLab && (
                  <Link to={`/content-creator?item=${id}`} className="text-[11px] text-primary hover:underline"
                    data-testid={`content-item-open-lab-${id}`}>
                    Apri nel laboratorio
                  </Link>
                )}
              </div>
            </div>
            <ContentItemStatusNotices item={item} />
            {item.content ? (
              <ContentItemBody content={item.content} />
            ) : (
              <div className="text-xs text-muted-foreground" data-testid={`content-item-no-content-${id}`}>
                Nessun contenuto disponibile per questo elemento (stato: {item.status}).
              </div>
            )}
          </div>
        );
      })}
      {d.warnings?.length > 0 && <div className="text-xs text-yellow-400">Avvisi: {d.warnings.join(" ")}</div>}
      <details>
        <summary className="text-xs text-muted-foreground cursor-pointer">Dettaglio tecnico (JSON)</summary>
        <pre className="mt-2 bg-background border border-border/60 rounded-sm p-3 text-[11px] overflow-auto max-h-72 whitespace-pre-wrap break-words">
          {JSON.stringify(d.content, null, 2)}
        </pre>
      </details>
    </div>
  );
}

// Scheda autonoma con intestazione (stato/modalità/quantità) — stessa forma
// degli altri CUSTOM_PREVIEW di Deliverables.jsx (EditorialPlanPreview,
// SocialContentPreview).
export function ContentItemDeliverablePreview({ d }) {
  const c = d.content && typeof d.content === "object" ? d.content : {};
  const items = Array.isArray(c.items) ? c.items : [];
  const idsCount = Array.isArray(c.content_item_ids) ? c.content_item_ids.length : items.length;
  return (
    <Card className="p-0 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border/60 bg-muted/30">
        <span className="label-caps">Content item — {c.produced_count ?? items.length}/{c.requested_quantity ?? idsCount} bozze</span>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded-sm ${d.mode === "REALE" ? "bg-emerald-500/15 text-emerald-500" : "bg-muted text-muted-foreground"}`}>
            {d.mode === "REALE" ? "REALE" : "SIMULAZIONE"}
          </span>
          <StatusBadge status={d.status} testid="deliverable-status-badge" />
        </div>
      </div>
      <div className="p-5">
        <ContentItemDeliverableItemsList d={d} />
      </div>
    </Card>
  );
}
