# ACTELYA 2 — PRD

## Problem statement (originale)
Sistema operativo AI web per marketing e vendite (non un chatbot, non una demo). Riceve un obiettivo, lo interpreta, prepara un piano, stima costi e rischi, chiede approvazioni ed esegue tramite agenti e integrazioni autorizzate. Progetto nuovo e indipendente `actelya-2`. Nessun accesso al progetto ACTELYA precedente. Nessun segreto nel codice. Nessuna chiamata AI reale senza azione esplicita. Modalità SIMULAZIONE e REALE sempre distinguibili.

## Architettura
- Frontend: React (CRA + Tailwind + shadcn/ui, tema scuro tattico). Fonts: Outfit / IBM Plex Sans / JetBrains Mono.
- Backend: FastAPI modulare per dominio (`app/domains/*`), MongoDB (motor).
- Auth: JWT custom (cookie httpOnly + fallback Bearer), bcrypt, cambio password obbligatorio al primo accesso, brute-force lockout, rate limiting.
- Segreti: cifratura Fernet con MASTER_KEY da env (mai in DB), mascheramento, mai in audit/log/API dopo il salvataggio.
- Coda esecuzioni persistente: worker DB-polling recuperabile dopo riavvio; idempotenza tramite indice unico su `approval_id`.
- Provider AI: SIMULATO (Milestone 1), chiaramente marcato.

## Personas / Ruoli
ADMIN, OPERATORE, APPROVATORE, SOLA_LETTURA. Rilascio mono-organizzazione, predisposto multi-tenant (`organization_id` su ogni record).

## Macchina a stati (3 stati separati)
- execution_status: IN_CODA / IN_ESECUZIONE / COMPLETATA / FALLITA / ARRESTATA
- deliverable_status: COMPLETATO / COMPLETATO_CON_AVVISI / BLOCCATO
- action_status: NON_RICHIESTA / IN_ATTESA_APPROVAZIONE / AUTORIZZATA / BLOCCATA / ESEGUITA / FALLITA

## Modelli dati principali
users, organizations, ai_connections, integrations, goals, approvals, executions(+agent_runs), deliverables, audit_logs, budgets, settings, login_attempts. Ogni record dominio: organization_id, created_by, updated_by, created_at, updated_at, change_history.

## Implementato (Milestone 1) — 2026-08-21 — OPERATIVO e verificato (testing agent iter.1 e 2)
- Auth completa (login/logout/me/refresh/change-password), seed admin IDEMPOTENTE (reset solo con FORCE_RESET_ADMIN=true), RBAC centralizzato.
- Classificazione intento ibrida (regole deterministiche + gestione negazione "non inviare"; AI simulata per ambiguità). Tipi: PRODUZIONE/AZIONE_ESTERNA/MISTO/AMBIGUO.
- Preventivi (min/probabile/max, tetto approvabile, dettaglio per agente) senza chiamate reali.
- Centro Approvazioni idempotente (APPROVA/RIFIUTA/APPROVA TUTTE/RIFIUTA TUTTE), doppio-click non duplica esecuzioni.
- Esecuzione singola persistita → worker → agenti simulati → validazione contratto EMAIL → deliverable persistito.
- Contratto EMAIL: hook/oggetto, contenuto_completo, cta non vuoti; policy placeholder (BLOCCATO se prevalgono placeholder).
- Azione esterna: bozza prodotta ma invio BLOCCATO se mancano destinatari/consenso/integrazione/approvazione; richiesta AZIONE_ESTERNA non approvabile (409).
- Connessioni e API: CRUD provider AI, api key cifrata+mascherata, TESTA CONNESSIONE a 2 step (anteprima+conferma) SIMULATA, nessun test automatico al salvataggio. Integrazioni future predisposte con stati (NON_CONFIGURATA...).
- Profilo aziendale, Utenti e ruoli (export/delete con conferma+audit), Budget e costi (Recharts), Audit Log (nessun segreto), Impostazioni con interruttore AI REALE (prerequisiti: connessione verificata + budget + conferma + ADMIN; nessuna chiamata automatica).
- UI: Dashboard, Nuovo Obiettivo, Approvazioni, Esecuzioni (timeline 3 sezioni), Deliverable, Operatori AI (10 agenti con contratto), Connessioni, Profilo, Utenti, Budget, Audit, Impostazioni. Banner/bordo SIMULAZIONE(amber)/REALE(red).
- Test automatici backend: 12/12 pytest (auth/ruoli, mascheramento segreti, intent, bozza vs azione esterna, campi non vuoti, placeholder, 3 stati, doppio click, idempotenza, budget, audit, durabilità password su riavvio).

## Predisposto ma NON operativo (per design Milestone 1)
- Provider AI reali (chiamate reali): l'utente li configurerà e testerà personalmente dopo la Milestone 1.
- Integrazioni: email/SMTP, Microsoft 365, Gmail, Google Calendar, Meta, Instagram, LinkedIn, Google Ads, Meta Ads, CRM, webhook, prospect B2B, RPO, analytics → mostrate come "Non ancora collegata".

## Backlog (prossime milestone)
- P0: Integrazione provider AI reale (una connessione verificata) con flusso di primo test reale (provider/modello/agenti/tetto/dati/conferma) — dopo verifica utente.
- P1: Integrazione invio email reale (SMTP/Gmail) per abilitare AZIONE_ESTERNA con consenso/RPO check.
- P1: Estendere la stessa correzione dimensioni Recharts ad eventuali altri grafici; rimuovere residui warning console.
- P2: TTL index su login_attempts; multi-tenant reale; analytics/performance agent operativo.

## Note tecniche
- Env backend: MONGO_URL, DB_NAME, JWT_SECRET, MASTER_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, FRONTEND_URL, (FORCE_RESET_ADMIN opzionale). `.env.example` fornito senza valori reali.
- Credenziali test: `/app/memory/test_credentials.md`.

## Milestone 2 (branch `M2`) — SIMULAZIONE — avanzamento
Design: `/app/memory/MILESTONE2_DESIGN.md`. Nuove collezioni: plans, tasks, deliverables(estesi), executions(estesi), worker_leases, reviews, handoffs, m2_locks.

### Blocco 1 — modelli/indici/migrazione (agent-tested)
`app/m2/models.py`: enum, costruttori, indici partial additivi (non distruttivi su M1), unique `(plan_id,task_id,version)` e `(plan_id,deliverable_type,artifact_slot,version)`, unique execution `(plan_id,plan_version)`, unique current-version per goal, `swap_current_version()` transazione+fallback con ripristino.

### Blocco 2 — planner/DAG/classificazione (testing agent iter.4)
`app/m2/planner.py`: funzioni pure/deterministiche, classificazione PRODUZIONE/AZIONE_ESTERNA/MISTO/AMBIGUO, DAG aciclico, EMAIL→piano a 1 attività.

### Blocco 3 — agent registry/contratti (testing agent iter.5)
`app/m2/agents_registry.py`: AGENT_CONTRACTS, REGISTRY_VERSION m2-1.0.0, select_agent deterministico, assert_action_allowed, validazione allo startup.

### Blocco 4 — approvazioni/execution/task/lease/resume — 2026-08-21 — COMPLETATO (testing agent iter.6)
`app/m2/engine.py` (core + router `/api/m2`), registrato in `server.py`; `recover_m2(db)` chiamato allo startup con lock persistente (leader election, collezione `m2_locks`).
- RBAC server-side su ogni route (`require_roles` + `_authz_org`): mai fidarsi del frontend.
- Endpoint: POST `/plans` (OPERATORE,ADMIN), GET `/plans/{id}`, POST `/plans/{id}/approve` (APPROVATORE,ADMIN), POST `/plans/{id}/tasks/{tid}/approve` (APPROVATORE,ADMIN), POST `/plans/{id}/tasks/{tid}/reject` (ADMIN,APPROVATORE, reason OBBLIGATORIA), POST `/plans/{id}/stop` (ADMIN), POST `/plans/{id}/tick` (OPERATORE,APPROVATORE,ADMIN).
- Una execution per (plan,version); doppio click/concorrenza idempotenti; claim atomico singolo worker; lease persistente con scadenza; `renew_lease` INTERNA (nessun endpoint pubblico, come richiesto).
- recovery restart idempotente (confermato→COMPLETATA senza ricosto; non confermato→stesso tentativo, costo non raddoppiato); max attempts→FALLITA; blocco/salto dipendenti; stop manuale; budget pre-task + tetto approvato; costo una volta per attempt; transizioni validate; audit senza segreti.
- reject blocca/salta i dipendenti SENZA cancellare deliverable già prodotti; reject su task terminale→409.
- Fix da iter.6: costo simulato per-task allineato al preventivo (cost_probable) per stare entro l'approved_cap; `_maybe_finish_plan` marca BLOCCATO se un task è FALLITA/BLOCCATA/SALTATA (non solo deliverable BLOCCATO).
- Test: `tests/test_m2_block4.py` (17 core) + `tests/test_m2_block4_http.py` (14 e2e). Suite completa 65/65.

### Blocco 5 — sei deliverable versionati e validati — 2026-08-21 — COMPLETATO (testing agent iter.7)
`app/m2/deliverables.py`: produttori DETERMINISTICI (nessuna AI) + validatori SEPARATI per tipo (marketing_strategy, editorial_plan, social_content, ad_campaign_draft, lead_gen_plan, kpi_report) + email M1.
- Campi sostanziali: rifiuto di vuoti/UNKNOWN/TODO/N/A/rifiuti/contenuti non producibili (REFUSAL_RE, FORBIDDEN_VALUES); placeholder ammessi SOLO nei campi variabili (altrove → BLOCCATO).
- ad_campaign_draft sempre `status=DRAFT`/`published=false`; lead_gen_plan senza PII (PII_EMAIL_RE/PII_PHONE_RE → BLOCCATO); kpi_report con `source` in {SIMULATO, NON_DISPONIBILE}.
- Stato COMPLETATO/COMPLETATO_CON_AVVISI/BLOCCATO deciso dal validatore; deliverable invalido → `valid=false`, non conta come valido ma costo/tentativo del task restano registrati; piano marcato BLOCCATO.
- Versionamento atomico non sovrascrivente: `create_deliverable_version()` usa unique `(plan_id,task_id,version)` (retry su collisione) + `is_current` esclusivo (indice unique partial `(plan_id,task_id)` su is_current). Più deliverable dello stesso tipo via task/artifact slot.
- Deliverable con link a plan/task/agent/organization + audit; solo SIMULAZIONE.
- Guard SIMULAZIONE: `_assert_simulation()` su POST `/plans` e POST `/tick` → 409 se modalità REALE; `/tick` risponde `mode=SIMULAZIONE, simulation_tool=true`. Nuovo endpoint read-only GET `/plans/{id}/deliverables`.
- Fix isolamento M1↔M2: il worker/recovery M1 (`domains/engine.py`) ora filtra solo execution con campo `agents`, così non processa più le execution M2 (bug KeyError risolto).
- Test: `tests/test_m2_block5.py` (19 core, incl. guard 409) + `tests/test_m2_block5_http.py` (11 e2e). Suite completa 94 passed, 1 skip legittimo.

### Blocco 6 — revisori non distruttivi Compliance/Auditor — 2026-08-21 — COMPLETATO (testing agent iter.8)
`app/m2/reviews.py`: `run_compliance` (PII, GDPR/consenso, campagna DRAFT, placeholder, deliverable BLOCCATO) e `run_audit` (coerenza valid/status, link mancanti, mode, segreti, TRACE costo/tentativo).
- `review_deliverable` esegue Compliance + Auditor e persiste record `reviews` collegati a plan/task/deliverable/agente/organizzazione; `assert_action_allowed('revisione')` garantisce che i reviewer non modifichino/cancellino (forbidden modifica/cancellazione_deliverable).
- NON distruttivo: le revisioni non toccano mai i deliverable (content/status/valid invariati). `create_review` idempotente per (deliverable_id, review_type) con indice unique partial.
- Integrazione motore: `_execute` genera automaticamente le due revisioni dopo ogni deliverable. Endpoint read-only GET `/plans/{id}/reviews`; POST `/plans/{id}/tasks/{task_id}/review` (ADMIN/APPROVATORE, guard SIMULAZIONE) per re-review idempotente.
- Test: `tests/test_m2_block6.py` (10 core) + `tests/test_m2_block6_http.py` (11 e2e). Suite completa 104 passed, 1 skip legittimo.

### Blocco 7 — interfaccia frontend M2 — 2026-08-21 — COMPLETATO (testing agent iter.9)
- Nuove pagine: `pages/Plans.jsx` (lista + creazione piani, gestione obiettivo AMBIGUO) e `pages/PlanDetail.jsx` (DAG con dipendenze, approvazione piano/attività, rifiuto con motivazione obbligatoria, esecuzione on-demand `tick`, arresto, anteprima 6 deliverable con stato/versione, pannello revisioni Compliance/Auditor con severità, banner "esecuzione terminata, risultato non completato", polling che si ferma allo stato terminale).
- Nav `Piani (M2)`; Dashboard con KPI M2 (piani, deliverable validi/bloccati, **contatore rilievi compliance high**) e CTA.
- Endpoint backend aggiunti: GET `/m2/plans` (lista), GET `/m2/stats`. StatusBadge esteso ai nuovi stati M2 e alle severità revisione.
- RBAC UI+backend verificata (OPERATORE crea/esegue ma non approva; SOLA_LETTURA sola lettura). Guard SIMULAZIONE su create/tick.
- Testing Agent iter.9: 13/13 scenari, 0 problemi.

**Milestone 2 COMPLETA (Blocchi 1–7)**: backend + frontend in SIMULAZIONE, 104 test backend + verifica frontend. Nessun push/deploy/chiamata reale.

### Backlog M3 (futuro, richiede approvazione utente)
- Versionamento visibile in UI (storico versioni deliverable), tracciabilità estesa.
- Integrazione provider AI reale + azioni esterne (email/social/ads) solo dopo consenso esplicito e integration_expert.
