
# Professional Tool Registry v1.0 — Checkpoint

**Data:** 2026-09-05
**Branch:** master
**Stato:** infrastruttura e catalogo completi lato codice; ogni provider elencato è censito, con stato onesto (12 già REALI, 51 predisposti). Costruire i restanti adapter reali resta lavoro futuro, per priorità.

## Cosa è

`backend/app/tools/registry.py` è la fonte di verità canonica, lato backend, di **63 strumenti professionali in 22 categorie** (il catalogo completo indicato: cervello/IA, ricerca web, monitoraggio, media/audio, brand, social, advertising, CRM, prospect research, comunicazioni individuali, email marketing, calendari, analytics/SEO, SMS, prenotazione, attività locali, siti, e-commerce, documenti, OCR, automazioni). Il frontend non duplica mai queste informazioni: le legge da `GET /api/tool-registry` (`backend/app/tools/router.py`).

## Principio di onestà

Ogni voce (`ToolSpec`) dichiara `code_complete: bool` — **non basta il nome nel catalogo**: `base_mode` può essere `REAL` SOLO se `code_complete=True` (verificato strutturalmente da `validate_registry()`, che blocca l'avvio con un errore esplicito se qualcuno lo violasse). Lo stato dinamico (`GET /tool-registry`, campo `status`) verifica per organizzazione la STESSA fonte di verità già usata dal dominio reale (nessuna seconda logica di readiness): connessioni AI/video/Meta/calendario esistenti, mai un provider senza codice dichiarato disponibile.

### Già REALI oggi (12/63)

`requesty_llm`, `openai_llm`, `anthropic_llm`, `gemini_llm` (brain/llm_gateway.py) · `runway_video` (integrations/runway_gateway.py) · `meta_graph_social`, `meta_insights` (integrations/meta/) · `google_calendar`, `microsoft_calendar`, `calendly_booking` (domains/appointments) · `actelya_audit_log` (audit.py) · `local_document_parsers` (domains/leadgen/parsers.py).

### Predisposti (51/63)

Tutti gli altri: censiti con categoria, provider, agenti autorizzati, capability, scopes, variabili d'ambiente previste (mai un valore, mai un segreto) — sempre `NON_CONFIGURATO` finché non viene costruito un adapter reale.

## API

- `GET /tool-registry` — lista completa, filtrabile per `agent_id` e `category`.
- `GET /tool-registry/{tool_id}` — dettaglio singolo strumento con stato calcolato per l'organizzazione corrente.

## Frontend

`frontend/src/pages/ToolRegistry.jsx` ("Registro strumenti", ADMIN): elenco raggruppato per categoria, badge di stato, filtro per categoria/agente, variabili d'ambiente previste per i provider non ancora implementati.

## Test

- Backend: **23 passed** (16 diretti + 7 HTTP live: coerenza registro, filtro per agente/categoria, stato calcolato reale per organizzazione, isolamento multi-tenant dello stato).
- Frontend: **4 passed**.

## Per riprendere lo sviluppo da qui

Il registro è la base su cui costruire i prossimi adapter reali, nell'ordine di priorità che si deciderà (es. Tavily/Brave per la ricerca web di Lead Generation/Marketing, HubSpot come primo CRM, Brevo per il Nurturing). Aggiungere un provider: un nuovo `ToolSpec` in `registry.py` con `code_complete=True` solo a implementazione ultimata, un adapter reale nel dominio pertinente, ed eventualmente una voce in `status.py::computed_status_for()` se la connessione ha una propria collezione di stato.
