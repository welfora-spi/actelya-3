# RIPARTENZA — ACTELYA 3

Ultimo aggiornamento: 2026-09-09 (sera). Questo file descrive lo stato **effettivo, verificato**
del lavoro al momento del commit — non una dichiarazione di release pronta. Dove non ho potuto
verificare qualcosa di persona, lo dico esplicitamente.

## 1) Configurazione ambiente attuale

- **MongoDB**: `127.0.0.1:27030`, database `actelya3_dev` (istanza dedicata, dbpath fuori
  dal repository/OneDrive — vedi `scripts/README-DB.md` per la cronologia della migrazione
  dalla vecchia istanza 27020, che resta un rollback intatto, mai cancellata).
- **Backend**: FastAPI/uvicorn su `127.0.0.1:8001`.
- **Frontend**: React (craco) su `0.0.0.0:3000`.
- Al momento di questo commit tutti e tre risultano **già in esecuzione** (verificato via
  `netstat`, non riavviati per questa chiusura, come richiesto).

### Script di avvio effettivi (`scripts/`)
- `start_mongo.ps1` — avvia l'istanza dedicata 27030 se non già attiva (idempotente).
- `start_backend.ps1` — avvia uvicorn su 8001 se non già in ascolto (idempotente: se già attivo
  non riavvia, quindi per caricare codice nuovo va **prima fermato** il processo sulla porta 8001).
- `start_frontend.ps1` — avvia il dev server craco su 3000.
- `start_all.ps1` / `stop_all.ps1` — orchestrano i tre sopra; `stop_all.ps1` fa uno shutdown
  Mongo pulito (comando nativo, mai un kill del processo).
- **Prima di ogni riavvio backend**: verificare che non ci siano task `IN_CODA` con
  `auto_dispatch_requested_at` o `IN_ESECUZIONE` (altrimenti un riavvio potrebbe far ripartire
  lavoro reale a pagamento). Pattern usato in questa sessione, non automatizzato in uno script.

## 2) Modifiche implementate in questo lavoro

Riassunto; per il dettaglio vedi i commenti nel codice (ogni file tocca spiega il "perché", non
solo il "cosa") e i messaggi di commit.

- **Ambiente/DB**: migrazione a istanza dedicata 27030, script di avvio, separazione dai dati
  storici di recupero.
- **Discovery**: fetch reale con fallback Playwright/JS, estrazione prodotti da JSON-LD,
  evidenze/provenienza dei fatti nel Fact Ledger.
- **Brain**: costo reale della comprensione tracciato (riserva atomica → chiamata → registrazione
  → riconciliazione), correzione del bug per cui l'azienda/prodotto già noti in testo libero
  venivano comunque richiesti, correzione della mancata persistenza delle domande di chiarimento
  generate dall'LLM in `session.clarifications`.
- **Budget/contabilità** (`domains/budget.py`): `execution.real_cost` include per costruzione la
  riserva stimata di OGNI task, riconciliata al costo vero SOLO per `editorial_plan`/
  `social_content` reali — un task simulato (es. `marketing_strategy`) o `content_item` (costo
  vero tracciato nel Tool Execution Gateway) restava classificato come "reale" per sempre.
  Corretto **a lettura** (mai riscritto il campo storico `real_cost`, mai toccato l'enforcement
  del tetto): nuova funzione `_real_cost_per_execution_corretto`, nuovo bucket generico
  `spent_altri_reali` (nessun agente reale futuro può più sparire silenziosamente dal totale,
  come accadeva prima per `content-creator`).
- **Revisione editoriale su `social_content`** (nuovo modulo `m2/deliverable_review.py`): prima
  non esisteva alcuna decisione post-generazione su questo ramo (solo `content_item` l'aveva).
  Ora: Approva/Rifiuta/Richiedi modifica per singola bozza, **versionamento per bozza**
  (una richiesta di modifica può essere applicata — con stima di costo e conferma esplicita PRIMA
  di ogni eventuale chiamata reale — producendo una nuova versione indipendente, mai una
  riscrittura; le versioni precedenti e le loro decisioni restano sempre consultabili). Percorso
  reale via Tool Execution Gateway (`reserve_budget → chiamata → record_cost →
  reconcile_reservation`), percorso simulato dichiarato esplicitamente tale nel contenuto.
  Propagato a Dashboard (`pending_deliverable_items`), Risultati e dettaglio piano.
- **`m2/reviews.py`**: due falsi positivi corretti (HIGH su ogni deliverable REALE anche
  corretto; "[PLACEHOLDER]" su qualunque campo lista JSON).

## 3) Test realmente eseguiti (in questa sessione, poco prima del commit)

- Backend: `test_verifica_20260909.py` + `_parte2.py` + `_parte3.py` + `test_m2_real_content.py`
  + `test_brain_llm_validator.py` → **88 passati**. Subset puro di `test_m2_block6.py`
  (`compliance`/`audit_rileva`/`reviewer_non_puo`) → **6 passati**. Database di test isolati
  (`127.0.0.1:27020`, database dedicati per file), mai `actelya3_dev`.
- Frontend: suite completa (`craco test`) → **140 passati**, 20 suite.
- **Non eseguibili in questo ambiente**: 33 file di test preesistenti (es.
  `test_brain_ceo_agent_llm_pipeline.py`, `test_content_creator_pipeline.py`) puntano a un
  MongoDB sulla porta **27017**, non in ascolto qui — si bloccano per diversi minuti se lanciati
  senza filtro. Non corretto (fuori perimetro, tocca 33 file). **Mai lanciare la suite intera
  senza filtro `-k`/percorso esplicito.**
- **Non eseguito deliberatamente**: `test_content_creator_router.py` — E2E che scrive via HTTP
  su un server live; rischio di scrivere sul database applicativo reale.

## 4) Verifiche browser — cosa è CONFERMATO e cosa NO

**Confermato per davvero** (letto dal database reale, non assunto): sul piano
`plan-c632efad5881492ea9fe`, deliverable `deliv-1c76200d3a494d76a6ce` (`social_content`, 3 bozze):

- **Bozza 3 (indice 2)**: richiesta di modifica registrata da `raffaele.patarino@spitool.it` alle
  17:44:31 UTC; modifica applicata (percorso **REALE**) alle 17:47:10 UTC → **v2** creata,
  costo reale **$0.003218** (`tool_cost_events`, `agent_id="content_social_revisione"`,
  correttamente incluso in `compute_spent`); **v2 approvata** dallo stesso utente alle 17:52:44
  UTC. v1 e la sua decisione (`MODIFICA_RICHIESTA`) restano intatte nello storico.
- **Bozza 1 e Bozza 2 (indici 0 e 1)**: rimaste `v1`, `IN_ATTESA_REVISIONE`, **non toccate** —
  come richiesto ("preservando le bozze non coinvolte").
- Ho verificato **a livello di funzione/database** (stessa funzione usata dagli endpoint reali)
  che Risultati mostrerebbe correttamente il testo della v2 e il suo stato — **non ho visto
  screenshot o conferma diretta che l'utente abbia effettivamente aperto la pagina Risultati o
  la Dashboard nel browser** per gli ultimi due passi dell'handoff (punti 5-6). Non dichiaro
  quella parte "verificata nel browser": è verificata solo a livello dati.
- Spesa organizzazione attuale (`compute_spent`): `spent_simulated=$0.124578`,
  `spent_execution=$0.028368`, `spent_brain=$0.069964`, `spent_content_creator=$0.023028`,
  `spent_altri_reali=$0.003218`, modalità `MISTA`. Budget generale invariato (`$1.00`).
- **Nota importante**: nella stessa organizzazione esistono **5 deliverable `social_content`
  correnti** (15 bozze pendenti in totale in Dashboard), di cui solo uno è il piano di prova di
  questo lavoro. Gli altri 4 provengono da attività reale indipendente (un'altra sessione/utente
  che ha usato l'app in parallelo) — non toccati, non attribuiti a questo lavoro, ma il numero
  "15" in Dashboard include anche quelli: non stupirsi se non corrisponde a "2" (le sole bozze
  ancora pendenti del piano di prova).

## 5) Limiti residui noti

- Revisione editoriale post-generazione esiste ora sia per `content_item` sia per
  `social_content` (con versionamento). **Non estesa** ad altri eventuali deliverable multi-item
  futuri (oggi non esistono).
- La pagina Risultati mostra lo stato editoriale delle bozze in un riepilogo minimale
  (`ItemDecisionsSummary`), non con la stessa ricchezza del dettaglio piano (nessun pulsante di
  decisione lì — di proposito, per non duplicare l'azione in due punti).
- 33 file di test con porta Mongo 27017 obsoleta (vedi sopra) — manutenzione futura separata.
- Nessuna verifica visiva diretta (screenshot) dell'ultimo tratto dell'handoff Chrome (Risultati
  + Dashboard) — solo verifica dati.

## 6) Prima attività consigliata per domani

**Non ripetere alcuna generazione già effettuata** (Discovery, creazione piano, o un altro ciclo
di modifica sulle bozze già decise). Punto di partenza suggerito, in ordine di rischio crescente:

1. Verifica visiva (screenshot, nessuna azione) di Risultati e Dashboard per chiudere il punto 4
   sopra — sola lettura, nessun costo.
2. Se si vuole proseguire la revisione: Bozza 1 e Bozza 2 (indici 0/1) di questo stesso piano
   restano `IN_ATTESA_REVISIONE` — decidibili senza rigenerare nulla.
3. Eventuale bonifica dei 33 file di test sulla porta 27017 (manutenzione, non legata a un
   incarico specifico).
