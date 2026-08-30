# ACTELYA 2 — Progetto tecnico Milestone 2 (SIMULAZIONE) — IN ATTESA DI APPROVAZIONE

Stato: PROPOSTA. Nessun codice implementato. Compatibile con M1. Release v0.1.0-milestone1 invariata.

## 1. Architettura M2
Estende il motore M1 da "singolo flusso email" a "piano operativo multi-attività".
Nuovi moduli backend (in aggiunta, senza rompere M1):
- `domains/planner.py`: classifica l'obiettivo marketing (objective_type) e lo scompone in attività costruendo un DAG con dipendenze e ordine topologico.
- `domains/plan.py`: CRUD piano/attività, endpoint, approvazione dell'intero piano o delle singole attività.
- `domains/agents_registry.py`: estende il registro agenti con capabilities dichiarate e mapping capability→deliverable; selezione dinamica.
- `domains/deliverable_schemas.py`: schemi + validatori reali per i 6 deliverable.
- `engine` esteso: coda a livello ATTIVITÀ (non solo esecuzione), handoff tracciati, resume per attività, deliverable versionati.
Frontend: vista Piano (timeline/DAG attività con 3 stati), anteprime specifiche per i 6 deliverable, approvazione piano/attività.
Principio: una execution per piano approvato (retro-compatibile); il flusso email M1 diventa un piano a 1 attività.

## 2. Nuovi modelli / modifiche MongoDB
Campi comuni OBBLIGATORI su OGNI nuovo record: `organization_id`, `created_by`/`updated_by` (o `actor` per agenti/sistema), `created_at`/`updated_at`, `change_history[]`, e voce corrispondente in `audit_logs`.
Nuove collezioni:
- `plans`: id, goal_id, organization_id, base fields, objective_type, plan_status, dag (nodi+archi), topo_order[], estimate, **version**, is_current(bool), superseded_by, approvals_mode. Chiave logica versionata: `(goal_id, version)`.
- `tasks`: id, plan_id, goal_id, org_id, base fields, seq, name, agent_id, deliverable_type, inputs, depends_on[], task_status, **attempt**, **idempotency_key** = `"{plan_id}:{version}:{task_id}"`, lease_owner, lease_expires_at, tokens, cost, deliverable_id, warnings, started_at, finished_at, confirmed(bool).
- `handoffs`: id, plan_id, org_id, from_task, to_task, from_agent, to_agent, payload_summary, actor, at.
- `reviews` (NUOVA): id, org_id, plan_id, task_id, deliverable_id, reviewer_agent (compliance/auditor), review_type, findings[], severity, non_destructive=true (sempre), actor, created_at. I record di revisione NON modificano/sostituiscono il deliverable.
- `worker_leases` (NUOVA): id, task_id, plan_id, owner, acquired_at, expires_at, heartbeat_at. Lock persistente del worker.
Estensioni:
- `deliverables`: + type ∈ {marketing_strategy, editorial_plan, social_content, ad_campaign_draft, lead_gen_plan, kpi_report, email}, + plan_id, + task_id, + **version**, + previous_version_id, + schema_version, + campi audit comuni.
- `executions`: + plan_id, + **plan_version**; una sola execution per versione del piano (vedi §6b); `agent_runs` → `task_runs` (retro-compatibili).
Indici UNIVOCI: `plans.id` unique; `plans(goal_id, version)` unique; `tasks.id` unique; `tasks(plan_id, seq)` unique; `tasks.idempotency_key` unique; **`deliverables(plan_id, deliverable_type, version)` unique**; `executions(plan_id, plan_version)` unique; `executions.approval_id` unique (M1); `worker_leases.task_id` unique; `reviews.id` unique.
Creazione ATOMICA della nuova versione: nuovo documento `plans` con `version = prev.version + 1` inserito con `plans(goal_id, version)` unique (insert-once); la creazione simultanea della stessa versione fallisce su duplicate-key → un solo vincitore, nessun duplicato. Contestualmente `is_current` viene spostato in modo atomico sul nuovo piano e `superseded_by` valorizzato sul vecchio.
Migrazione: dati M1 restano validi; goal senza plan = piano implicito a 1 attività (version=1). Nessuna riscrittura distruttiva.

## 3. Struttura del piano operativo e delle attività
Plan = obiettivo + objective_type + attività (DAG) + ordine topologico + preventivo aggregato dal piano EFFETTIVO.
Task = { agent, deliverable_type, inputs (da profilo aziendale + output di task precedenti via handoff), depends_on, criteri successo/blocco, limiti token/budget/timeout }.
Esempio CAMPAGNA: strategy → editorial_plan → (social_content ∥ ad_campaign_draft) → lead_gen_plan → kpi_report.
Validazione DAG: aciclicità obbligatoria; ordine topologico calcolato; task eseguibile solo quando tutte le dipendenze sono COMPLETATA.

## 4. Agenti previsti e contratti (estensione dei 10 di M1)
- Marketing Strategist → capability: strategy → marketing_strategy
- Content & Social → editorial, social → editorial_plan, social_content
- Advertising → ads → ad_campaign_draft (solo DRAFT)
- Lead Generation/SDR → leadgen → lead_gen_plan (nessun contatto reale)
- Analytics & Performance → analytics → kpi_report
- Compliance Reviewer, Auditor, Tech Lead → revisione/handoff, NON distruttivi: producono **record di revisione persistiti** (collezione `reviews`) collegati a task e deliverable; aggiungono findings/avvisi ma **non modificano né sostituiscono** il contenuto prodotto dall'agente responsabile.
- Appointment Setter, Nurturing → predisposti (nessun deliverable core M2)
Contratto per agente: id, mission, capabilities[], allowed_deliverables[], input_schema, output_schema (→ schema deliverable), required_fields, success/block/handoff criteria, token_limit, budget, timeout.
Selezione dinamica: objective_type → capabilities richieste → agenti → task.

## 5. Schemi dei 6 deliverable (validazione REALE: no vuoti, no UNKNOWN, no rifiuti/motivazioni al posto del contenuto)
Regole comuni: ogni stringa obbligatoria non vuota e "sostanziale"; vietati valori tipo `UNKNOWN|N/A|TODO|—|"non disponibile"|"rifiuto"|motivazioni`; placeholder ammessi SOLO in campi variabili designati (date, nomi, link, budget numerici) e mai prevalenti nei campi chiave.
1) marketing_strategy: { objective, target_segments[≥1]{name,pains,desires}, value_proposition, positioning, key_messages[≥3], channels[≥1], funnel_stages[≥1], success_metrics[≥2] }
2) editorial_plan: { period, cadence, pillars[≥2], items[≥4]{date_placeholder, channel, format, topic, hook, cta} }
3) social_content: { platform, posts[≥3]{hook, body(sostanziale), cta, hashtags[≥1], visual_brief} }
4) ad_campaign_draft: { objective, platform, audience{targeting_criteria[≥2]}, budget_plan{daily_placeholder,total_placeholder,currency}, ad_variants[≥2]{headline,primary_text,cta,visual_brief}, status:"DRAFT" } — status SEMPRE DRAFT, nessun account/ID reale
5) lead_gen_plan: { icp{criteria[≥3]}, sourcing_strategy, qualification_criteria[≥3], outreach_sequence[≥3]{step,channel,message_template(placeholder)}, kpis[≥2], compliance_notes } — NESSUNA PII/persona reale, nessun contatto
6) kpi_report: { period, metrics[≥4]{name,definition,formula,target_placeholder, value_status ∈ {SIMULATO, NON_DISPONIBILE}, current: null | numero_simulato, source:"SIMULAZIONE"}, insights[≥2], recommendations[≥2] } — NON inventare risultati reali: `current` deve essere `null` oppure esplicitamente simulato; il report DISTINGUE sempre target vs dato simulato vs dato non disponibile.
Esito validazione: COMPLETATO / COMPLETATO_CON_AVVISI (placeholder in campi variabili) / BLOCCATO (campi chiave vuoti o soli placeholder/valori vietati).

## 6. Macchina a stati delle attività e del piano, rapporto con i 3 stati esistenti
**task_status**: `PIANIFICATA → IN_ATTESA_APPROVAZIONE → IN_CODA → IN_ESECUZIONE → COMPLETATA | FALLITA | BLOCCATA | SALTATA | ARRESTATA`.
- Un'attività **non approvata NON può essere messa in coda**: da `IN_ATTESA_APPROVAZIONE` passa a `IN_CODA` solo dopo approvazione esplicita (piano o singola attività).
- **Dipendenza non approvata**: un'attività approvata la cui dipendenza NON è approvata/COMPLETATA **resta in `IN_ATTESA_APPROVAZIONE`** (o `PIANIFICATA`) e non viene mai eseguita saltando la dipendenza. Diventa `IN_CODA` solo quando tutte le `depends_on` sono `COMPLETATA`.
- `SALTATA` = dipendenza `FALLITA`/`BLOCCATA` che rende l'attività non eseguibile.

**plan_status** (macchina a stati del piano): `BOZZA → IN_ATTESA_APPROVAZIONE → {APPROVATO_PARZIALE | APPROVATO} → IN_ESECUZIONE → {COMPLETATO | BLOCCATO} ; ANNULLATO` (transizione possibile da qualsiasi stato non terminale).
- `BOZZA`: piano generato, preventivo calcolato, non ancora inviato ad approvazione.
- `IN_ATTESA_APPROVAZIONE`: richiesta creata nel Centro Approvazioni.
- `APPROVATO_PARZIALE`: solo alcune attività approvate; le altre restano in attesa.
- `APPROVATO`: tutte le attività approvate.
- `IN_ESECUZIONE`: ≥1 task in coda/esecuzione.
- `COMPLETATO`: tutti i task terminali in COMPLETATA/BLOCCATA/SALTATA.
- `BLOCCATO`: un deliverable OBBLIGATORIO è BLOCCATO.
- `ANNULLATO`: piano annullato o sostituito da una nuova versione.
Qualsiasi **modifica dopo l'approvazione** porta a una NUOVA versione (plan_status della vecchia → `ANNULLATO`/superseded) e richiede nuovo preventivo e nuova approvazione (vedi §6b). Un piano approvato **non è modificabile in-place**.

Rapporto con i 3 stati M1 (invariati):
- **execution_status** (piano, derivato): IN_ESECUZIONE finché ≥1 task attivo; COMPLETATA quando tutti i terminali sono COMPLETATA/BLOCCATA/SALTATA; FALLITA se un task critico FALLITA; ARRESTATA su stop.
- **deliverable_status**: per singolo deliverable (invariato); a livello piano aggregato (CON_AVVISI o BLOCCATO se un deliverable obbligatorio è BLOCCATO).
- **action_status**: azioni esterne → in M2 sempre NON_RICHIESTA o BLOCCATA (nessuna pubblicazione/invio).
Regola UI: se un deliverable obbligatorio è BLOCCATO, `execution_status` può essere tecnicamente `COMPLETATA`, ma la UI mostra chiaramente **"esecuzione terminata, risultato non completato"** e **non** indica in alcun modo un successo complessivo.

## 6b. Execution per versione, idempotenza task/attempt, worker lease
- **Una sola execution per VERSIONE del piano**: chiave unica `executions(plan_id, plan_version)`. Le approvazioni parziali successive (stessa versione) **aggiornano** la stessa execution aggiungendo i task appena approvati alla coda, **senza duplicare** i task/deliverable già eseguiti. Nessuna seconda execution per la stessa versione.
- **Idempotenza a livello task/attempt** (oltre ad `approval_id`): ogni task ha `idempotency_key = "{plan_id}:{version}:{task_id}"` (indice unico). Il deliverable è vincolato da `deliverables(plan_id, deliverable_type, version)` unique → riavvio, doppio clic o worker concorrenti **non riproducono deliverable né costi**. Il costo è registrato una sola volta per attempt confermato (`confirmed=true`).
- **Claim atomico + lease persistente**: il worker acquisisce un task via `find_one_and_update({task_status:IN_CODA}, {task_status:IN_ESECUZIONE, lease_owner, lease_expires_at})`; scrive/aggiorna `worker_leases` (owner, expires_at, heartbeat). Solo un worker vince il claim.
- **Scadenza lease e recupero sicuro**: heartbeat periodico estende il lease. Al riavvio/recovery, i task `IN_ESECUZIONE` con **lease scaduto** e **deliverable non confermato** tornano a `IN_CODA` (nuovo attempt = attempt+1); i task con **deliverable già confermato** vengono chiusi come `COMPLETATA` senza ri-esecuzione. Nessuna doppia spesa.

## 7. Flussi end-to-end di prova (SIMULAZIONE)
Classificazione **deterministica e dichiarata** (stesse regole di M1, estese): l'obiettivo è mappato a objective_type con regole esplicite; gli obiettivi **ambigui** sono classificati `AMBIGUO` e **richiedono chiarimento**, senza creare automaticamente attività di azione esterna.
A) "Prepara una strategia di marketing…" → STRATEGIA → [strategy] → marketing_strategy COMPLETATO · action NON_RICHIESTA.
B) "Prepara una campagna social e adv per un lancio" → CAMPAGNA → [strategy→editorial→(social∥ads)] → ad_campaign_draft status=DRAFT · action BLOCCATA per pubblicazione (mai pubblicata).
C) "Costruisci un piano di lead generation" → LEAD_GEN → lead_gen_plan (strategia/criteri/sequenze con placeholder) · nessun contatto reale.
D) "Genera un report KPI del trimestre" → REPORT → kpi_report con placeholder dichiarati.
E) Resume dopo riavvio: task IN_ESECUZIONE → riportati IN_CODA; task COMPLETATA preservati; deliverable versionati non riprodotti; nessun duplicato/doppia spesa.
F) Approvazione parziale: approvando solo alcune attività, vengono eseguite solo quelle; le altre restano PIANIFICATA. Doppio click su approvazione piano → una sola execution.

## 8. Funzioni operative vs solo predisposte (M2)
Operative (SIMULAZIONE): planner, piano DAG, selezione dinamica agenti, 6 deliverable con schema+validazione, handoff tracciati, preventivo su piano effettivo, approvazione piano/attività, resume, versioning deliverable.
Solo predisposte ("Non ancora collegata"): pubblicazione campagne, invii, raccolta/contatto lead reale, provider AI reale, integrazioni social/ads/CRM. action_status di pubblicazione resta BLOCCATA.

## 9. Criteri di accettazione e test
- Classificazione multi-obiettivo corretta (STRATEGIA/CAMPAGNA/LEAD_GEN/REPORT/CONTENUTO/AMBIGUO).
- Scomposizione DAG: aciclicità, dipendenze e ordine topologico corretti.
- Selezione agenti coerente con objective_type.
- Ogni deliverable rispetta lo schema e rifiuta vuoti/UNKNOWN/rifiuti/motivazioni.
- ad_campaign_draft status SEMPRE DRAFT (mai PUBLISHED); nessun account reale.
- lead_gen_plan senza PII/persone reali/contatti.
- handoff registrati con from/to (agente e task).
- preventivo = somma delle attività effettive del piano.
- approvazione piano idempotente (una sola execution per versione); approvazione parziale esegue solo i task scelti.
- **task IN_ATTESA_APPROVAZIONE non entra mai in coda** senza approvazione.
- **approvazione con dipendenza non approvata**: il task resta in attesa e non salta la dipendenza.
- **modifica di un piano già approvato** crea una nuova versione, con nuovo preventivo e nuova approvazione; il piano precedente non è modificato in-place.
- **due worker concorrenti** sullo stesso task: un solo claim vince (lease), nessun deliverable/costo duplicato.
- **creazione contemporanea della stessa versione** del piano: solo un insert vince su `plans(goal_id, version)` unique; l'altro fallisce senza duplicati.
- **resume durante un task**: lease scaduto + deliverable non confermato → ri-accodato (attempt+1); deliverable confermato → chiuso COMPLETATA senza ri-esecuzione.
- **idempotenza task/attempt**: riavvio/doppio clic non riproducono deliverable né costi (indice `deliverables(plan_id, deliverable_type, version)` + `tasks.idempotency_key`).
- **reviews non distruttive**: Compliance/Auditor creano record collegati a task/deliverable senza alterare il contenuto.
- **kpi_report**: `current` = null o simulato dichiarato; distinzione target/simulato/non disponibile.
- resume dopo riavvio senza duplicati né doppie spese.
- 3 stati separati coerenti; piano COMPLETATA + deliverable obbligatorio BLOCCATO ⇒ UI "esecuzione terminata, risultato non completato" (nessun successo complessivo).
- nessuna azione esterna senza approvazione; nessun deliverable contato se non persistito e valido.
- versioning: nuova esecuzione crea nuova versione (previous_version_id), non sovrascrive.
Accettazione: tutti i test verdi + flussi A–F verificati end-to-end (frontend→persistenza→ritorno) in SIMULAZIONE.

## 10. Rischi, assunzioni, compatibilità con M1
Rischi: complessità/aciclicità DAG (mitigare con validazione), esplosione degli stati, validatori troppo rigidi che bloccano deliverable producibili (bilanciare warning vs block), storage per versioning, scostamento preventivo/reale quando in futuro si passerà al reale.
Assunzioni: SIMULAZIONE, dati fittizi/placeholder, singola organizzazione, provider simulato, nessuna azione esterna.
Compatibilità M1: flusso email = piano a 1 attività (retro-compatibile); idempotenza execution/approval invariata; i 3 stati invariati; API M1 mantenute; nessuna modifica alla release v0.1.0-milestone1 (M2 su branch dedicato in futuro). Migrazione non distruttiva (goal senza plan = piano implicito).
