# Analyst/KPI — checkpoint

L'agente "analista-performance" esisteva già (capability `analytics`) ma era
interamente M2-simulato (`kpi_report_m2`: SIMULATO/NON_DISPONIBILE
statici). **Non è stato creato un nuovo agente**: la capability esistente è
stata portata a REAL, riusando identità/ruolo/postazione già esistenti.

## Cosa calcola davvero

Tutto da dati REALI già presenti in ACTELYA (mai un valore inventato, mai
una chiamata a un provider esterno):

- `conversion_rate`, `lead_velocity` — da `lead_companies`/`lead_persons`
  (Lead Generation, questo stesso lavoro).
- `response_rate`, `appointment_rate`, `close_rate`, `funnel_drop_off` — da
  `sales_opportunities` (Sales Agent), `funnel_drop_off` calcolato sulla
  STORIA reale di ogni opportunità (non solo lo stage attuale).
- `cost_per_lead`, `cost_per_appointment`, `cost_per_acquisition` — dal cost
  ledger reale del Tool Execution Gateway (`tool_cost_events`, Fase 1).
- `engagement`, `roi`, `roas` — dichiarati esplicitamente `NON_DISPONIBILE`
  (nessuna integrazione Meta Insights/GA4/Ads/fatturato collegata in questa
  fase): mai un valore stimato per riempire il report.

Ogni KPI ha sempre `source`, `formula`, `value`, `reliability`
(ALTA/MEDIA/BASSA/NON_DISPONIBILE in base al volume di osservazioni) e
`missing_data`.

## Interpretazione (non solo visualizzazione)

`insights.py` applica regole deterministiche esplicite (mai un'invenzione):
lead sufficienti ma conversione bassa → insight per `sales-agent`;
abbandono elevato in un punto specifico della pipeline → `sales-agent`;
alta percentuale di escalation → `coordinatore-actelya`. Se il campione è
insufficiente per ogni regola, il report lo dichiara onestamente invece di
forzare una conclusione.

## Handoff

`GET /analyst/insights/{agent_id}` — sola lettura, mai una scrittura sugli
altri domini: filtra gli insight già generati indirizzati a un agente
specifico (CEO, Sales, Lead Generation, Content Creator, Marketing).

## File

- `backend/app/domains/analyst/{models,metrics,insights,pipeline,router}.py`
- `backend/app/brain/skills.py` — skill `kpi_analysis_real`
- `backend/app/brain/agents/agent_map.py` — capability `analytics` da
  `EXECUTION_MODE_M2` a `EXECUTION_MODE_REAL`, `deliverable_type`
  `kpi_report` → `analyst_report` (il producer M2 `kpi_report_m2` resta
  invariato per il percorso diretto/simulato, non più usato da questo)
- `backend/app/brain/service.py` — `_M2_NATIVE_DELIVERABLE` non include più
  `analytics`; nuovo blocco REALE (report calcolato subito, come leadgen)
- `backend/server.py` — router, indici
- `frontend/src/pages/Analyst.jsx` (+`.test.jsx`) — nessuna nuova postazione
  Sala Riunioni necessaria (riusa quella già esistente di
  "analista-performance")

## Test

28 nuovi (15 metrics/insights, 6 pipeline, 7 HTTP) + 6 frontend. Nessuna
chiamata reale. Aggiornato un test preesistente
(`test_brain_agent_selector_b1.py`) che asseriva `analytics` come
M2-simulata: correzione necessaria e dichiarata, non una regressione
nascosta.

## Debito residuo

Nessuno sulla logica applicativa. `engagement`/`roi`/`roas` restano
`NON_DISPONIBILE` finché GA4/Search Console/Meta Insights/Ads e un dato di
fatturato reale non saranno collegati — comportamento corretto, non un
difetto.
