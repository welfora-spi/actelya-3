# CEO Agent v1.0 — Checkpoint

**Data:** 2026-09-04  
**Branch:** master  
**Commit applicativo:** `af57f22c60d6814cbb1d07c21f56de4610c820bf`  
**Stato:** completo lato codice; restano soltanto configurazione e verifica delle credenziali/provider esterni.

## Stato raggiunto

Il CEO Agent comprende richieste in linguaggio naturale tramite un gateway LLM astratto multi-provider, propone un piano strutturato e lo sottopone ai guardrail deterministici prima dell'esecuzione. In assenza di provider o credenziali, degrada esplicitamente al planner deterministico senza simulare un successo LLM.

Flusso operativo:

`richiesta → contesto e Fact Ledger → precheck rischio/dominio → proposta LLM o fallback deterministico → validazione capability/compliance/budget → normalizzazione → agenti → DAG M2 → deliverable → approvazione`

## Funzioni completate

- Gateway comune per OpenAI/GPT, Anthropic/Claude, Google/Gemini, Requesty e provider OpenAI-compatible.
- Configurazione per organizzazione con provider primario, fallback ordinati, modello, timeout e retry controllati.
- Contesto minimizzato con Company Profile, Fact Ledger e provenienza, sessione, capability e vincoli.
- Pipeline esplicita `propose → validate → normalize → execute`.
- Registry e policy deterministiche autoritative: agenti o capability inesistenti non entrano nel piano.
- Priorità, urgenza, deadline, budget, rischi, agenti, task e dipendenze influenzano realmente piano e DAG M2.
- Budget totale, allocato e residuo con chiarimento, blocco o approvazione quando necessario.
- Deduplica dei chiarimenti e riuso dei dati già presenti.
- Audit e sessioni persistenti, idempotenza e resume dopo refresh/riavvio.
- Discovery sito protetta da SSRF con estrazione e provenienza dei dati essenziali.
- UI Nuovo Obiettivo leggibile per modalità, provider, priorità, budget, rischi, agenti, KPI e approvazioni.

## Verifica

- Backend: **631 passed, 1 skipped, 0 failed**.
- Brain mirato: **297 passed, 0 failed**.
- Frontend: **28 passed, 0 failed**, incluse 23 verifiche dedicate al CEO.
- Build frontend di produzione: riuscita.
- `git diff --check`: nessun errore.
- Secret scan: nessun segreto rilevato.
- ACTELYA v1 e ACTELYA 2: nessuna modifica.

Il browser E2E letterale non è stato eseguito perché lo strumento non era disponibile. Non è stato dichiarato superato; contratto HTTP e interfaccia sono stati verificati rispettivamente live e con Testing Library.

## Configurazione esterna necessaria

Per attivare il ragionamento LLM reale, un amministratore deve configurare e verificare almeno una connessione OpenAI, Anthropic, Gemini o Requesty e abilitare la modalità AI reale. Le credenziali non sono incluse nel repository. Il CEO core resta operativo senza credenziali tramite fallback deterministico.

## File principali

- `backend/app/brain/llm_gateway.py`
- `backend/app/brain/llm_schema.py`
- `backend/app/brain/llm_context_builder.py`
- `backend/app/brain/llm_understanding.py`
- `backend/app/brain/llm_validator.py`
- `backend/app/brain/risk_registry.py`
- `backend/app/brain/service.py`
- `frontend/src/pages/NewGoal.jsx`
- `frontend/src/components/new-goal/`

## Punto di ripartenza

Il checkpoint applicativo è il commit `af57f22c60d6814cbb1d07c21f56de4610c820bf`. I prossimi passi richiedono credenziali reali e smoke controllati sui provider; non restano interventi funzionali del CEO Agent nel repository.
