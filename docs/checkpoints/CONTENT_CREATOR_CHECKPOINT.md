# Content Creator — checkpoint

Agente CONSOLIDATO (nuovo `content-creator`), costruito riusando l'infrastruttura
già esistente (Fact Ledger, Requesty gateway, validatore semantico anti-
allucinazione, Tool Execution Gateway) senza rimuovere copywriter/video-creator/
creative-designer.

## Flusso implementato

obiettivo → decisione del formato (decision.py, deterministica, mai un'invenzione
quando il tipo è esplicito) → generazione REALE via Requesty (Tool Execution
Gateway: autorizzazione agente/connessione/budget) → validazione strutturale per
tipo (validation.py) → validazione semantica anti-allucinazione (riusa
`domains/reel_semantic.py`) → approvazione → (se il formato dipende da un asset
multimediale) collegamento al progetto reale reel/flyer → deliverable finale.

## Stati

`BOZZA → GENERAZIONE_IN_CORSO → (ESITO_INCERTO | BLOCCATO | IN_ATTESA_APPROVAZIONE)
→ (RIFIUTATO | APPROVATO | IN_ATTESA_ASSET → COMPLETATO)`

## File

- `backend/app/domains/content_creator/{models,decision,validation,pipeline,router}.py`
- `backend/app/brain/skills.py` — skill `content_creation_requesty`
- `backend/app/brain/agents/agent_map.py` — AgentMapping capability `content`
- `backend/app/brain/planning/agent_selector.py` — keyword `_CONTENT_CREATOR_KW`
  (SOLO formati non già coperti da social/editorial/email/ads/flyer_image/
  video_reel/audio_voiceover — nessuna sovrapposizione con `_EMAIL_KW`)
- `backend/app/brain/service.py` — task REALE nel DAG M2 (stesso pattern di leadgen)
- `backend/app/tools/registry.py` — `content-creator` aggiunto agli `allowed_agents` LLM
- `backend/server.py` — router, indici, recovery all'avvio
- `frontend/src/pages/ContentCreator.jsx` (+`.test.jsx`)
- `frontend/src/App.js`/`Layout.jsx` — route/nav ADMIN
- `frontend/src/components/meeting-room/{agentRegistry,adapter}.js` — postazione
  condivisa con copywriter (nessuna postazione libera nel layout attuale — vedi
  commento nel file: da rivedere con una postazione dedicata)

## Test

79 backend (11 pipeline + 12 decisione/validazione + 14 HTTP + 42 già esistenti
Appointment Setter/Tool Registry/Tool Gateway invariati) + 7 frontend. Nessuna
chiamata reale (Requesty sempre mockato nei test di pipeline; i test HTTP
verificano solo i guardrail — AI non reale, stato, RBAC, isolamento tenant —
mai una generazione reale).

## Debito residuo

- Nessun debito applicativo noto: la logica di decisione, generazione,
  validazione, approvazione, versionamento, collegamento asset e recovery è
  completa e testata con un adapter fittizio.
- Provider esterno non collegato: nessuno oggi oltre Requesty (già REALE).
- Cosmetico: la Sala Riunioni non ha una postazione visiva dedicata (vedi sopra).
