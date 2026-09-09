// Interpretazione UNICA del contenuto/stato di un content_item (Content
// Creator): usata dal laboratorio (pages/ContentCreator.jsx), da Risultati
// (pages/Deliverables.jsx) e dal dettaglio piano (pages/PlanDetail.jsx) —
// mai una seconda logica che potrebbe divergere su come si legge un
// content_item nelle tre pagine.

// Avvisi di stato (errori di validazione strutturale, contestazione
// semantica): stessa lettura ovunque appaia un content_item.
export function ContentItemStatusNotices({ item }) {
  const errori = item?.generazione?.errori_validazione || [];
  const sc = item?.semantic_check;
  return (
    <>
      {errori.length > 0 && (
        <div className="mb-3 text-xs rounded-sm border border-red-500/30 bg-red-500/10 text-red-400 px-3 py-2"
          data-testid="content-item-validation-errors">
          {errori.join(" · ")}
        </div>
      )}
      {sc?.status === "CONTESTATO" && (
        <div className="mb-3 text-xs rounded-sm border border-amber-500/30 bg-amber-500/10 text-amber-400 px-3 py-2"
          data-testid="content-item-contested-notice">
          Affermazioni non riconducibili al Fact Ledger: {(sc.affermazioni_contestate || []).map((a) => a.frase).join(" · ")}
        </div>
      )}
    </>
  );
}

// Corpo testuale: titolo/corpo/CTA/hashtag nella sezione principale, le
// varianti SEMPRE in una sezione separata (non sono post aggiuntivi).
export function ContentItemBody({ content }) {
  if (!content) return null;
  return (
    <div className="space-y-3 text-sm" data-testid="content-item-body">
      {content.titolo && <div><div className="label-caps mb-1">Titolo</div>{content.titolo}</div>}
      {content.corpo && <div><div className="label-caps mb-1">Corpo</div><p className="whitespace-pre-wrap">{content.corpo}</p></div>}
      {content.cta && <div><div className="label-caps mb-1">CTA</div>{content.cta}</div>}
      {content.hashtags?.length > 0 && (
        <div><div className="label-caps mb-1">Hashtag</div>{content.hashtags.join(" ")}</div>
      )}
      {content.varianti?.length > 0 && (
        <div data-testid="content-item-variants">
          <div className="label-caps mb-1">Varianti (non contate come post separati)</div>
          <ul className="list-disc list-inside space-y-1">
            {content.varianti.map((v, i) => <li key={i}>{v}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
