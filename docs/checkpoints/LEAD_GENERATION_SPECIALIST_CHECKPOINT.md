
# Lead Generation Specialist v1.0 — Checkpoint

**Data:** 2026-09-05
**Branch:** master
**Commit di partenza:** `50f24bb536b5a55b0fbfa2c9321016d41781e8d3` (working tree con modifiche non ancora committate — nessun commit/tag creato da questa sessione)
**Stato:** completo lato codice, con file e fonti interne/pubbliche controllate; verifica manuale in browser non eseguita (nessuno strumento E2E disponibile in questo ambiente).

## Stato raggiunto

Il Lead Generation Specialist è un dominio autonomo (`backend/app/domains/leadgen/`) che copre l'intera pipeline dichiarata:

`upload → validazione → parsing → mapping → normalizzazione → deduplica → compliance → scoring → segmentazione → review → approval → export/handoff`

Funziona interamente **senza alcun provider esterno configurato**: gli adapter di ricerca non configurati (directory/dataset pubblici, provider commerciale di lead/company data — es. Apollo, connettore CRM) tornano sempre `NON_DISPONIBILE`, mai un risultato inventato e mai una falsa dichiarazione di ricerca commerciale effettuata. **Apollo, CRM e altri provider commerciali sono intenzionalmente rinviati** a una futura fase dedicata "strumenti esterni", da collegare solo dopo il completamento di tutti gli agenti: in questa fase restano solo interfacce astratte predisposte (`_NonConfiguratoAdapter`), mai un'integrazione parziale o simulata. Gli unici due adapter sempre disponibili sono la ricerca su URL pubbliche esplicite (nessun motore di ricerca integrato) e i dati già presenti in ACTELYA per la stessa organizzazione (file caricati, campagne precedenti).

Ogni lista del dominio (file, campagne, lead/aziende/persone, duplicati da revisionare) è paginata lato server con un contratto unico (`page`/`page_size`/`items`/`total`/`pages`, ordinamento tramite allowlist esplicita): il frontend non carica mai l'intero dataset in un solo payload — vedi `pagination.py` e la sezione dedicata più sotto.

Il CEO Agent collega davvero la capability `leadgen` (reale, non più il vecchio producer M2 simulato) a una campagna reale in questo dominio, con lo stesso pattern architetturale di `video_reel`/`flyer_image`: un solo piano, un solo percorso reale, mai un secondo motore.

## Architettura

```
CEO Agent (brain/service.py)
  -> capability "leadgen" (agent_map.py: execution_mode=REAL, deliverable_type=lead_gen_campaign)
  -> leadgen_router.create_campaign() [BOZZA reale, agganciata a goal/plan]
  -> task M2 'lead_gen_campaign' (deliverable_override, mai un secondo planner)

domains/leadgen/
  models.py       costanti, stati, corpi Pydantic
  storage.py      file locale sicuro (hash, anti path-traversal, per organizzazione)
  parsers.py      CSV/TSV/XLSX/PDF/DOCX/TXT -> ParseResult
  mapping.py      alias espliciti colonna -> campo canonico (mai fuzzy)
  normalize.py    normalizzazione con provenienza (FORNITO/ESTRATTO/PUBBLICO/...)
  dedup.py        duplicati ESATTI (chiave forte) vs PROBABILI (sempre review manuale)
  compliance.py   gate deterministico, ceiling assoluto sul punteggio
  scoring.py      punteggio spiegabile, qualificazione (QUALIFIED/REVIEW_REQUIRED/INCOMPLETE/EXCLUDED/DO_NOT_CONTACT)
  research.py     adapter astratti (pubblico/interno/predisposti), SSRF-safe
  export.py       CSV/XLSX, formula-injection neutralizzata, DO_NOT_CONTACT mai esportato
  pipeline.py      orchestrazione, coda persistente, worker, recovery da riavvio
  router.py       ~17 endpoint REST, auth + ruoli + isolamento organizzazione

frontend/src/pages/LeadGeneration.jsx   laboratorio (upload, mapping, campagne, lead, duplicati, ricerca, approvazione, export, handoff)
```

## Flusso reale (worked example)

"Dal file caricato trova le aziende più adatte per una campagna rivolta agli hotel del Nord Italia": upload → mapping automatico/manuale delle colonne → normalizzazione (provenienza tracciata) → deduplica (esatti bloccano l'approvazione finché non revisionati, probabili sempre in revisione manuale) → compliance (opt-out/consenso mancante prevale sempre sul punteggio) → scoring con motivazione e regole applicate → segmentazione per ICP/esclusione clienti esistenti → revisione → approvazione (bloccata se restano duplicati pendenti) → export CSV/XLSX o handoff verso altri agenti (solo aggregati qualificati, mai dati personali non necessari).

## Normalizzazione e deduplica

Ogni valore normalizzato porta `{value, method, ...}` con `method` in FORNITO/ESTRATTO/PUBBLICO/VERIFICATO/INFERITO/NON_VERIFICATO/CONTRADDITTORIO/MANCANTE/SCADUTO — mai un dato dedotto presentato come verificato. La deduplica esatta raggruppa per dominio/email/telefono normalizzati (O(n), nessun confronto pairwise); i duplicati probabili (nome simile, stessa città) sono **sempre** instradati a revisione manuale, mai fusi automaticamente. Il merge non sceglie mai silenziosamente un valore in conflitto: lo marca `CONTRADDITTORIO` con il valore perdente preservato, tracciabile.

## Scoring e compliance

Lo scoring è la somma di componenti nominati e motivati; la qualificazione finale controlla PRIMA il ceiling di compliance (assoluto, mai bypassabile da un punteggio alto o da un LLM), poi le regole di esclusione business, poi la completezza dei dati, infine il punteggio numerico. Il gate privacy/compliance produce sempre uno tra `READY/NEEDS_CLARIFICATION/REVIEW_REQUIRED/APPROVAL_REQUIRED/BLOCKED/DO_NOT_CONTACT`; non è consulenza legale.

## Frontend

`frontend/src/pages/LeadGeneration.jsx` (laboratorio, ADMIN, come Reel — raggiungibile anche dalla Sala Riunioni quando l'agente `lead-gen-specialist` è realmente convocato): upload con validazione/errore, mapping colonne editabile, stato import in tempo reale, tabella lead paginata con punteggio/stato/provenienza/dati mancanti, revisione duplicati con decisione MERGE/KEEP_SEPARATE, ricerca prospect con stato per fonte, approvazione bloccata su duplicati pendenti, export CSV/XLSX, handoff. Mai JSON grezzo. `CollaboratorPanel.jsx`/`adapter.js` collegano il task reale `lead_gen_campaign` a un link diretto verso il laboratorio.

## API e database

~17 endpoint sotto `/api/leadgen`: file (upload/list/detail/preview/delete), campagne (CRUD), import (avvio/stato), lead (paginati/filtrati), duplicati (lista/decisione), ricerca, approvazione, export, handoff. Autenticazione + ruoli (`ADMIN`/`OPERATORE` per le scritture, `ADMIN`/`APPROVATORE` per l'approvazione) + isolamento per organizzazione (404, non 403, su risorsa di un altro tenant) su ogni endpoint. Indici MongoDB idempotenti su 8 collezioni nuove (`lead_files`, `lead_import_jobs`, `lead_campaigns`, `lead_companies`, `lead_persons`, `lead_dedup_reviews`, `lead_exports`, `lead_handoff_packages`), incluse le coppie `(organization_id, campaign_id, score)`/`(organization_id, campaign_id, created_at)` per l'ordinamento paginato; nessun indice unico globale fra organizzazioni diverse.

## Paginazione

Contratto identico su **tutte** le liste del dominio (`backend/app/domains/leadgen/pagination.py`): `GET /leadgen/files`, `GET /leadgen/campaigns`, `GET /leadgen/campaigns/{id}/leads`, `GET /leadgen/campaigns/{id}/duplicates` accettano `page`/`page_size` (bloccato a un massimo di 100, mai un errore per un valore fuori range) e un `sort_by`/`sort_dir` validati contro un'allowlist esplicita per endpoint (400 su un campo non ammesso — mai un ordinamento libero su un campo non indicizzato). Ogni risposta ha la stessa forma `{items, total, page, page_size, pages}`; una pagina oltre l'ultima ritorna `items: []` con `total`/`pages` comunque corretti, mai un redirect silenzioso. La ricerca prospect (`POST /leadgen/search`) resta un'azione one-shot con un tetto esplicito (`max_risultati`, massimo 50): i record creati entrano comunque nella lista lead, quella sì paginata. Nessun endpoint "lista job" esiste oggi (solo lettura per id), quindi nessuna paginazione è richiesta lì. Il frontend (`LeadGeneration.jsx`) consuma questo contratto senza mai caricare l'intero dataset: ogni lista ha i propri controlli Precedente/Successiva, e il conteggio duplicati pendenti (che blocca l'approvazione) usa sempre `total`, mai la sola pagina corrente.

## Verifica

- Dominio Lead Generation (unitari + integrazione + HTTP live + paginazione): **124 passed, 0 failed** (111 + 13 test di paginazione dedicati).
- Suite backend completa: **755 passed, 1 skipped (pre-esistente, motivato), 0 failed** (un fallimento intermittente per esaurimento del rate limit reale su `/tenant/register` sotto il carico dell'intera suite è stato osservato e risolto riducendo le registrazioni live nei test lead gen a un tenant condiviso per file; il residuo osservato è imputabile a `test_tenant_knowledge_discovery.py`, pre-esistente, verificato 12/12 verde in isolamento).
- Suite brain/CEO Agent (compresa la nuova wiring `leadgen`→REAL): **298 passed, 0 failed**.
- Frontend: **44 passed, 0 failed** (16 dedicati a `LeadGeneration.jsx`, inclusi 7 di paginazione).
- Build frontend di produzione: riuscita.
- Smoke live reale (server + MongoDB reali): `POST /api/brain/plans` con una richiesta di lead generation in linguaggio naturale produce davvero una `lead_campaigns` in `BOZZA`, un task M2 `lead_gen_campaign` e una campagna recuperabile via `GET /api/leadgen/campaigns/{id}`.
- Import reale testato per CSV; XLSX/PDF/DOCX/TXT coperti dai test unitari dei rispettivi parser (`test_leadgen_parsers.py`) con file realmente generati e riletti.
- Export CSV/XLSX generato e riaperto nei test (`test_leadgen_export.py`).
- Isolamento multi-tenant verificato via HTTP reale (404 su risorsa di un'altra organizzazione).
- Idempotenza/recovery verificati: upload duplicato (stesso hash) non crea un secondo file; import duplicato (stesso file/campagna/mapping) non crea un secondo job; `recover_on_startup()` riporta in coda i job bloccati in uno stato intermedio.
- `git diff --check`: nessun errore.
- Nessun segreto individuato nei file nuovi/modificati.
- ACTELYA v1 e ACTELYA 2: nessuna modifica.

Il browser E2E letterale non è stato eseguito perché nessuno strumento di automazione browser è disponibile in questo ambiente. Non è stato dichiarato superato; il flusso HTTP end-to-end e il rendering React sono stati verificati rispettivamente live (server reale) e con Testing Library (DOM reale).

## Configurazione esterna necessaria (nessuna oggi)

Il core del dominio non richiede alcuna API key/credenziale. I soli residui possibili sono: collegare in futuro un vero provider commerciale di lead/company data o un connettore CRM (oggi `_NonConfiguratoAdapter`, sempre `NON_DISPONIBILE`), seguendo il pattern documentato in `backend/.env.example` e `research.py::build_adapters()`.

## File principali

- `backend/app/domains/leadgen/` (models, storage, parsers, mapping, normalize, dedup, compliance, scoring, research, export, pipeline, router, pagination)
- `backend/app/brain/service.py` (blocco capability REALE `leadgen`)
- `backend/app/brain/agents/agent_map.py` (mapping `leadgen` → `EXECUTION_MODE_REAL`)
- `backend/server.py` (router, indici, worker)
- `frontend/src/pages/LeadGeneration.jsx`
- `frontend/src/components/meeting-room/{adapter.js,CollaboratorPanel.jsx}` (collegamento Sala Riunioni)

## Per riprendere lo sviluppo da qui

- Punto di ripartenza: commit `50f24bb536b5a55b0fbfa2c9321016d41781e8d3` + le modifiche non committate descritte in questo checkpoint (nessun commit/tag creato da questa sessione, in attesa di autorizzazione).
- Prossimi passi naturali (non richiesti da questa sessione, solo idee): un secondo `ProspectSourceAdapter` reale (provider commerciale o CRM) seguendo esattamente il pattern di `PublicUrlAdapter`/`InternalDataAdapter`; verifica manuale in browser quando uno strumento sarà disponibile; eventuale paginazione lato server per l'elenco file/campagne quando il volume crescerà oltre le poche centinaia.
