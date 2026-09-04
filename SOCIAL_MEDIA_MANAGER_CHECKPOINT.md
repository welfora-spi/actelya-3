# Social Media Manager v1.0 — Checkpoint

**Data:** 2026-09-04
**Branch:** master
**Tag:** `social-media-manager-v1.0` (punta esattamente al commit descritto qui — vedi `git show social-media-manager-v1.0` per lo SHA esatto)
**Stato:** production-ready lato codice; pubblicazione reale bloccata solo dalla mancanza di credenziali Meta autorizzate in questo ambiente (nessuna azione di sviluppo residua).

## Cosa fa oggi il Social Media Manager

Un imprenditore scrive in linguaggio naturale ("Fammi un Reel per promuovere le focaccine questo weekend") e ACTELYA 3 porta la richiesta, senza alcuna manipolazione manuale del database o chiamata API manuale, fino a:

1. comprensione linguaggio naturale (`app/brain/planning/agent_selector.py`, `app/brain/context.py`) — nessuna parola canonica rigida richiesta, una sola domanda mirata quando il formato non è specificato;
2. contesto aziendale dal Fact Ledger (`app/domains/knowledge.py`, invariato), mai richiesto due volte;
3. selezione dinamica degli agenti (Video creator + Responsabile compliance per un reel) e un **solo** piano M2 (`app/brain/service.py`);
4. generazione reale testo (Requesty) con hashtag, caption, CTA (`app/domains/reel.py`, `app/domains/flyer.py`);
5. validazione semantica/compliance deterministica (`app/domains/reel_semantic.py`) e quality gate strutturale;
6. generazione reale video (Runway) o immagine (Requesty);
7. due approvazioni distinte (testo, media) + versioning del contenuto (`reel_content_versions`/`flyer_content_versions`);
8. memoria persistente cross-sessione (`app/domains/social_memory.py`): preferenze di formato, pattern di revisione, esiti di pubblicazione, suggerimenti di apprendimento derivati da dati misurati;
9. `PublishingPackage` (`app/domains/social_publishing.py`): approvazione della pubblicazione **distinta** da quella del contenuto, scheduling con worker dedicato e recovery da riavvio, idempotenza verificata anche sul percorso reale;
10. dispatch verso **Meta Graph API reale** (`app/integrations/meta/`) — Facebook Page e Instagram Professional (flusso a container) — sempre attraverso `ConnectorGateway` (`app/brain/gateways/connector_gateway.py`), mai bypassato;
11. metriche reali mappate (mai un valore inventato: `null` quando Meta non le fornisce) e un suggerimento di apprendimento quando ci sono abbastanza dati misurati per un confronto onesto.

## Connector Meta — architettura

```
Social Media Manager (domains/social_publishing.py)
  -> ConnectorGateway (brain/gateways/connector_gateway.py, invariato nella logica di sicurezza)
  -> adapter reale registrato (register_meta_adapters(), da server.py allo startup)
  -> app/integrations/meta/{facebook,instagram}.py
  -> app/integrations/meta/client.py (HTTP via `requests`, retry solo per condizioni transitorie)
  -> Meta Graph API (https://graph.facebook.com)
```

`connector_gateway.py` non importa mai una libreria HTTP (verificato da un test dedicato che ispeziona l'AST del file): l'unico modo per raggiungere Meta per davvero è tramite l'adapter registrato, e anche allora SOLO quando **tutte** queste condizioni sono vere insieme:

1. `REAL_EXTERNAL_ACTIONS=true` (variabile d'ambiente, processo);
2. `CONNECTOR_MODE=real` (variabile d'ambiente, processo);
3. un adapter reale registrato sull'istanza del gateway in uso (sempre vero in produzione dopo lo startup di `server.py`, mai vero di default nei test);
4. una connessione Meta configurata **per l'organizzazione**, con `mode="real"` e stato verificato `CONNECTED` (collezione `meta_connections`, multi-tenant);
5. l'asset da pubblicare pubblicamente raggiungibile (URL assoluto, o relativo con `PUBLIC_BACKEND_URL` configurato).

Se anche una sola manca, la pubblicazione resta **dry-run** (mai bloccata del tutto: percorso sempre disponibile e sicuro) — mai un'azione reale con una condizione mancante. Approvazione del pacchetto e compliance del contenuto sorgente restano **sempre** gate bloccanti (409), indipendenti dalla modalità reale/dry-run.

## Configurazione richiesta per abilitare la pubblicazione reale

Nessun secret in questo repository. Per attivare (vedi anche `backend/.env.example`):

1. Variabili d'ambiente del processo backend:
   - `REAL_EXTERNAL_ACTIONS=true`
   - `CONNECTOR_MODE=real`
   - `PUBLIC_BACKEND_URL=https://<dominio-pubblico-del-backend>` (solo se si pubblicano asset serviti da questo backend, es. flyer; non serve per asset già su CDN esterno come i video Runway).
2. Riavviare il backend (i due flag sono letti una sola volta all'avvio del modulo `app/brain/config.py`).
3. Da **Connessioni e API** (solo ADMIN) → sezione "Social (Meta — Facebook/Instagram)": creare una connessione con `mode=real`, l'access token della Pagina, il Page ID (l'Instagram Business Account ID viene anche rilevato automaticamente dal test se collegato).
4. Premere **TESTA**: verifica reale, sola lettura, gratuita (token, Pagina, account Instagram collegato).
5. Verificare `GET /social/connectors/meta/status` (o il pannello di pubblicazione nella Sala Riunioni/Deliverable): `facebook_page.connected` / `instagram.connected` devono risultare `true`.
6. Da questo momento, creare un contenuto → approvarlo → creare un pacchetto di pubblicazione → approvarlo → pubblicare: la pubblicazione sarà **realmente eseguita** (`dry_run: false`, `external_post_id` valorizzato da Meta).

**Nessuna modifica al codice è necessaria per questo passaggio: solo configurazione.**

## Test

- Backend: **479 passed, 1 skipped (motivato, pre-esistente), 0 failed** (`pytest tests/`, ~5 minuti).
- Frontend: build di produzione verde, 5/5 test Jest verdi.
- Trasporto HTTP verso Meta sempre mockato nei test automatici — mai una chiamata di rete reale (verificato attivamente bloccando i socket in alcuni test, per costruzione nel connector gateway per tutti gli altri).
- Scenario end-to-end "Bakery & Coffee" coperto due volte: una in dry-run puro, una con il dispatch Meta reale (trasporto mockato) fino a un `external_post_id` genuinamente restituito, metriche reali mappate e un suggerimento di apprendimento derivato da dati misurati (`backend/tests/test_social_e2e_bakery.py`).

## Limiti esterni reali (non risolvibili da codice)

- **Credenziali Meta autorizzate** (App Facebook/Instagram, Page Access Token, Page ID, Instagram Business Account ID): non disponibili in questo ambiente di sviluppo. L'adapter è completo e testato con trasporto mockato; non è mai stato invocato contro l'API reale di Meta.
- Le metriche Graph API reali (nomi esatti delle insight metric) sono implementate secondo la documentazione ufficiale corrente ma non verificate contro una risposta live: Meta rinomina/deprecare periodicamente alcune metriche — il codice degrada sempre a `data_available: false` per una metrica non riconosciuta, mai un errore bloccante o un valore inventato.

## Per riprendere lo sviluppo da qui

- Punto di ripartenza: tag `social-media-manager-v1.0`.
- Codice del connector: `backend/app/integrations/meta/` (client, auth, facebook, instagram, errors, models).
- Orchestrazione: `backend/app/domains/social_publishing.py` (readiness, dispatch, FSM, scheduler, resolve-uncertain).
- Credenziali multi-tenant: `backend/app/domains/meta_connections.py` (+ UI in `frontend/src/pages/Connections.jsx`, sezione "Social (Meta)").
- Stato connessione in UI: `frontend/src/components/SocialPublishingPanel.jsx`.
- Prossimi passi naturali (non richiesti da questa sessione, solo idee): supporto multi-pagina/multi-account per organizzazione dalla UI (il modello dati lo supporta già); un adapter TikTok/LinkedIn seguendo lo stesso pattern (`app/integrations/<provider>/`, un secondo `register_*_adapter()`); upload multipart diretto invece di `image_url`/`video_url` per asset non pubblicamente ospitabili.
