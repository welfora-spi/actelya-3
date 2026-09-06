# Sales Agent — checkpoint

Nuovo dominio costruito da zero (confermato: nessun agente Sales esisteva
prima), con lo stesso rigore di Appointment Setter/Lead Generation.

## Confine di responsabilità (confermato dall'utente)

**Sales decide, Content Creator scrive.** Sales Agent non chiama mai
Requesty direttamente: decide strategia/canale/timing/next-best-action e
delega la scrittura del messaggio a Content Creator (`content_type =
"comunicazione_commerciale"`), poi legge (mai duplica) lo stato di quel
content_item. Stesso principio per Appointment Setter: Sales collega in
lettura l'esito reale di una prenotazione, non crea mai una proposta/booking
lui stesso.

## Pipeline commerciale implementata

`NUOVO → QUALIFICATO → CONTATTATO → IN_RELAZIONE/FOLLOW_UP →
RICHIESTA_APPUNTAMENTO → APPUNTAMENTO_FISSATO → OPPORTUNITA → PROPOSTA →
NEGOZIAZIONE → VINTO` (o `PERSO` da qualunque stato non terminale).

- **Analisi lead** (`strategy.py::analyze_lead`): pain point e value
  proposition dai componenti di scoring già calcolati da Lead Generation
  (mai una nuova inferenza sui dati grezzi); canale scelto in base al primo
  contatto disponibile (email o telefono); stima interesse dal punteggio ICP.
- **Gestione risposte** (`strategy.py::decide_next_action`): tabella di
  transizione esplicita per POSITIVA/NEGATIVA/RICHIESTA_INFORMAZIONI/
  OBIEZIONE_PREZZO/NON_INTERESSATO/RICONTATTO_FUTURO/NESSUNA_RISPOSTA/
  ESCALATION/RICHIESTA_APPUNTAMENTO — nessuna combinazione non prevista
  produce una transizione: ricade sempre in `ESCALATION_UMANA` esplicita.
- **Conferma di contatto manuale**: nessun invio automatico esiste in questa
  fase (canali di comunicazione individuali non configurati nel Tool
  Registry) — `mark_contacted` richiede che il messaggio sia già
  APPROVATO/COMPLETATO in Content Creator, poi un umano conferma di averlo
  davvero inviato.
- **Handoff con Appointment Setter**: `link_appointment` collega (mai crea)
  una proposta già esistente; `sync_appointment_status` legge lo stato reale
  della prenotazione e avanza (CONFERMATA → APPUNTAMENTO_FISSATO) o
  retrocede (CANCELLATA/INCERTA/FALLITA → FOLLOW_UP) di conseguenza.
- **Avanzamento tardivo** (`advance_stage`): OPPORTUNITA→PROPOSTA→
  NEGOZIAZIONE→VINTO solo in sequenza di uno stage alla volta (mai un
  salto), PERSO sempre ammesso da qualunque stato non terminale, mai da uno
  stato già terminale.

## Handoff da Lead Generation

`create_opportunity` accetta solo un lead con `next_action.azione ==
PRONTO_PER_SALES` (deciso da Lead Generation in questo stesso lavoro):
altrimenti rifiuta esplicitamente con il motivo. Idempotente: un lead ha al
più un'opportunità (indice unico `(organization_id, lead_type, lead_id)`).

## File

- `backend/app/domains/sales/{models,strategy,pipeline,router}.py`
- `backend/app/brain/skills.py` — skill `sales_pipeline_management`
- `backend/app/brain/agents/agent_map.py` — AgentMapping capability `sales`
- `backend/app/brain/planning/agent_selector.py` — keyword `_SALES_KW`
- `backend/app/brain/service.py` — task REALE nel DAG M2 (stesso pattern di
  `appointments`: nessun'opportunità auto-creata, richiede una scelta umana)
- `backend/server.py` — router, indici
- `frontend/src/pages/Sales.jsx` (+`.test.jsx`)
- `frontend/src/App.js`/`Layout.jsx` — route/nav ADMIN
- `frontend/src/components/meeting-room/{agentRegistry,adapter}.js` —
  postazione condivisa con lead-gen-specialist (nessuna postazione libera —
  vedi commento nel file)
- `frontend/src/components/StatusBadge.jsx` — 13 nuovi stati pipeline

## Test

36 nuovi (17 strategy, 12 pipeline, 7 HTTP) + 7 frontend. Nessuna chiamata
reale (Sales non chiama mai un provider esterno direttamente).

## Debito residuo

Nessuno sulla logica applicativa. L'invio effettivo dei messaggi resta
manuale (nessun canale di comunicazione individuale — email/WhatsApp/SMS —
è collegato nel Tool Registry in questa fase): quando un canale reale verrà
collegato, `mark_contacted` potrà diventare automatico senza cambiare il
resto della pipeline.
