// Riepilogo leggibile del piano normalizzato (priorita'/urgenza/budget/
// scadenza/pubblico/canali/rischi/KPI/approvazioni/assunzioni), MAI JSON
// grezzo (item 14, CEO Agent 100% reale). normalizedPlan e' sempre
// presente quando result.status === "READY" (origine "LLM" o
// "DETERMINISTICO", entrambi hanno la stessa forma).
const LIVELLO_COLORE = {
  ALTA: "text-red-400 border-red-500/30 bg-red-500/10",
  MEDIA: "text-amber-400 border-amber-500/30 bg-amber-500/10",
  BASSA: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
};

function Livello({ label, valore }) {
  if (!valore) return null;
  return (
    <span className={`text-[11px] font-mono rounded-sm border px-1.5 py-0.5 ${LIVELLO_COLORE[valore] || "text-muted-foreground border-border"}`}>
      {label}: {valore}
    </span>
  );
}

function Sezione({ titolo, children }) {
  return (
    <div className="space-y-1">
      <div className="label-caps">{titolo}</div>
      {children}
    </div>
  );
}

export default function PlanInsightsPanel({ normalizedPlan }) {
  if (!normalizedPlan) return null;
  const p = normalizedPlan;
  const haRischi = p.rischi_valutati?.length > 0;
  const haCorrezioni = p.correzioni?.length > 0;

  return (
    <div data-testid="plan-insights" className="space-y-3 border border-border/60 rounded-sm p-3">
      <div className="flex items-center gap-2 flex-wrap">
        <Livello label="Priorita'" valore={p.priorita} />
        <Livello label="Urgenza" valore={p.urgenza} />
        {p.scadenza && <span className="text-[11px] font-mono rounded-sm border border-border px-1.5 py-0.5">Scadenza: {p.scadenza}</span>}
      </div>

      {p.budget_status !== "NON_APPLICABILE" && (
        <Sezione titolo="Budget">
          <p className="text-xs text-muted-foreground">
            {p.budget_totale != null ? `${p.budget_totale} ${" "}` : "Non indicato — "}
            <span className="font-mono">{p.budget_status}</span>
            {p.budget_allocato != null && ` · allocato: ${p.budget_allocato}`}
            {p.budget_residuo_operativo != null && ` · residuo operativo: ${p.budget_residuo_operativo}`}
          </p>
          {p.allocazioni_budget?.length > 0 && (
            <ul className="text-xs text-muted-foreground list-disc list-inside">
              {p.allocazioni_budget.map((a, i) => <li key={i}>{a.etichetta}: {a.importo}</li>)}
            </ul>
          )}
        </Sezione>
      )}

      {(p.pubblico || p.canali?.length > 0) && (
        <Sezione titolo="Pubblico e canali">
          <p className="text-xs text-muted-foreground">
            {p.pubblico && <span>{p.pubblico}</span>}
            {p.canali?.length > 0 && <span>{p.pubblico ? " — " : ""}{p.canali.join(", ")}</span>}
          </p>
        </Sezione>
      )}

      {p.strategia_proposta && (
        <Sezione titolo="Strategia proposta">
          <p className="text-xs text-muted-foreground">{p.strategia_proposta}</p>
        </Sezione>
      )}

      {haRischi && (
        <Sezione titolo="Rischi valutati">
          <div className="space-y-1">
            {p.rischi_valutati.map((r, i) => (
              <div key={i} className="text-xs text-muted-foreground flex items-center gap-1.5 flex-wrap">
                <span className="font-mono text-foreground">{r.categoria}</span>
                <Livello valore={r.severita} label="" />
                <span className="text-[10px] font-mono rounded-sm border border-border px-1 py-0.5">{r.azione}</span>
              </div>
            ))}
          </div>
        </Sezione>
      )}

      {p.kpi?.length > 0 && (
        <Sezione titolo="KPI">
          <div className="flex flex-wrap gap-1">
            {p.kpi.map((k, i) => (
              <span key={i} className="text-[11px] font-mono rounded-sm border border-border px-1.5 py-0.5">{k}</span>
            ))}
          </div>
        </Sezione>
      )}

      {p.approvazioni_necessarie?.length > 0 && (
        <Sezione titolo="Approvazioni necessarie">
          <p className="text-xs text-muted-foreground">{p.approvazioni_necessarie.join(", ")}</p>
        </Sezione>
      )}

      {p.assunzioni?.length > 0 && (
        <Sezione titolo="Assunzioni">
          <ul className="text-xs text-muted-foreground list-disc list-inside">
            {p.assunzioni.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        </Sezione>
      )}

      {haCorrezioni && (
        <Sezione titolo="Correzioni applicate dal validatore">
          <ul className="text-xs text-muted-foreground list-disc list-inside">
            {p.correzioni.map((c, i) => <li key={i}>{c.dettaglio}</li>)}
          </ul>
        </Sezione>
      )}
    </div>
  );
}
