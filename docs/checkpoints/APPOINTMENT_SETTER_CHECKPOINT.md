
# Appointment Setter v1.0 — Checkpoint

**Data:** 2026-09-05
**Branch:** master
**Stato:** completo lato codice; restano soltanto app OAuth (Google/Microsoft), credenziali e verifica live.

## Stato raggiunto

L'Appointment Setter è passato da capability `UNAVAILABLE` (nessun codice) a dominio reale completo (`backend/app/domains/appointments/`): propone slot da un calendario reale, richiede approvazione umana esplicita, prenota davvero (o dichiara `ESITO_INCERTO`, mai una conferma inventata), previene doppie prenotazioni, gestisce cancellazione/riprogrammazione, con coda persistente e recovery da riavvio.

## Architettura

```
backend/app/domains/appointments/
  models.py              costanti, stati, corpi Pydantic
  calendar_adapters.py   adapter Google Calendar/Microsoft Graph/Calendly + OAuth (authorize-url/exchange)
  scheduling.py          calcolo slot liberi timezone-aware (zoneinfo, stdlib)
  pipeline.py            idempotenza, prevenzione doppie prenotazioni, coda+worker+recovery, cancel/reschedule
  router.py              ~16 endpoint REST

brain/agent_map.py:      "appointments" execution_mode UNAVAILABLE -> REAL
brain/service.py:        task 'appointment_setter_task' collegato al laboratorio (nessuna proposta/prenotazione pre-creata: richiede la scelta di un lead, azione utente)
brain/skills.py:         nuova skill 'appointment_scheduling'
frontend/AppointmentSetter.jsx: laboratorio (connessioni, proposte, slot, approvazione, prenotazione, cancellazione)
```

## Sicurezza e garanzie

- Un lead con `compliance_status`/`qualification_status` bloccante (opt-out, DO_NOT_CONTACT, EXCLUDED) non entra MAI in una proposta (`_fetch_lead()` in router.py).
- Nessuna prenotazione è mai `CONFERMATA` senza una risposta `OK` reale dell'adapter (o del fake nei test): un errore di rete produce `ESITO_INCERTO`, mai una conferma.
- Prevenzione doppie prenotazioni: verifica di sovrapposizione sulla stessa connessione prima di ogni claim (`pipeline.create_booking`/`reschedule_booking`).
- Idempotenza: stessa proposta+slot -> stessa prenotazione (`idempotency_key` univoco indicizzato).
- Recovery: prenotazioni bloccate `IN_ESECUZIONE` allo startup tornano `IN_CODA`.
- Isolamento multi-tenant su ogni endpoint (404, non 403, su risorsa di un'altra organizzazione).

## Test

- Backend: **40 passed** (7 scheduling + 10 calendar_adapters + 8 pipeline + 15 router HTTP).
- Frontend: **9 passed** (`AppointmentSetter.test.jsx`).
- Nessuna chiamata di rete reale in alcun test (socket bloccato attivamente dove rilevante; fake adapter deterministico per la pipeline).

## Configurazione esterna necessaria

- App OAuth Google Calendar (`GOOGLE_CALENDAR_CLIENT_ID/SECRET/REDIRECT_URI`) e/o Microsoft Graph (`MS_GRAPH_CLIENT_ID/SECRET/REDIRECT_URI`), registrata una volta dall'operatore ACTELYA presso il provider.
- Calendly: Personal Access Token inserito per organizzazione (no OAuth in questa fase); prenotazione diretta non predisposta (richiede una Scheduling Link pubblicata dal cliente).
- Senza queste variabili, il flusso resta `NON_CONFIGURATO` in modo esplicito, mai un errore generico.

## File principali

- `backend/app/domains/appointments/` (models, calendar_adapters, scheduling, pipeline, router)
- `backend/app/brain/agents/agent_map.py`, `backend/app/brain/service.py`, `backend/app/brain/skills.py`
- `frontend/src/pages/AppointmentSetter.jsx`
- `frontend/src/components/meeting-room/{adapter.js,CollaboratorPanel.jsx}` (collegamento Sala Riunioni generalizzato a `LAB_LINK_BY_DELIVERABLE_TYPE`)
