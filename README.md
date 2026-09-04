# ACTELYA 3

Sistema operativo AI multi-tenant per marketing e vendite. Trasforma obiettivi in linguaggio naturale in piani verificabili, seleziona agenti, applica controlli di budget e compliance, produce contenuti e governa separatamente ogni azione esterna tramite approvazioni esplicite.

Il percorso ordinario resta sicuro: il Brain usa contenuti mock e i connector social lavorano in `dry_run`. Requesty, Runway e Meta possono raggiungere servizi reali soltanto dai flussi dedicati, dopo configurazione, readiness check e conferma esplicita. Nessun segreto è incluso nel repository.

## Stato del prodotto

- Milestone 1: autenticazione, ruoli, obiettivi, preventivi, approvazioni, esecuzioni, deliverable, budget e audit.
- Milestone 2: planner DAG, registry agenti, lease/recovery, deliverable versionati e revisioni Compliance/Auditor.
- Brain: comprensione della richiesta, Fact Ledger, selezione dinamica degli agenti, memoria, handoff e Sala Riunioni.
- Contenuti: workflow Reel e Flyer con versioni, validazione semantica e approvazioni separate per testo e media.
- Social Media Manager: memoria persistente, pacchetti di pubblicazione, scheduling, idempotenza, recovery, gestione dell'esito incerto e metriche.
- Meta connector: adapter Facebook Page e Instagram Professional completo lato codice e verificato con trasporto HTTP mockato. La validazione contro un account Meta reale non è stata eseguita.

Il checkpoint Social è in [`docs/checkpoints/SOCIAL_MEDIA_MANAGER_CHECKPOINT.md`](docs/checkpoints/SOCIAL_MEDIA_MANAGER_CHECKPOINT.md); il PRD corrente è in [`docs/PRD.md`](docs/PRD.md).

## Struttura

```text
backend/        API FastAPI, domini, Brain, integrazioni e test pytest
frontend/       applicazione React, componenti e test Jest
design/         riferimenti visuali, linee guida e prototipi
docs/           PRD, architettura, checkpoint, report e materiale storico
```

`docs/archive/` conserva, invariati, alcuni artefatti root storici non più in uso diretto (es. il vecchio package `tests/` root, oggi senza suite propria — i test attivi vivono in `backend/tests/`).

`.emergent`, `.gitconfig` e `.venv` sono metadati o ambiente locale, non componenti del runtime distribuito.

## Requisiti

- Python 3.11+
- Node.js 18+
- Yarn 1.22
- MongoDB

## Configurazione locale

```powershell
Copy-Item backend/.env.example backend/.env
Copy-Item frontend/.env.example frontend/.env
```

Valorizzare almeno `MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `MASTER_KEY` e `REACT_APP_BACKEND_URL`. `JWT_SECRET` e `MASTER_KEY` devono essere valori casuali robusti e non devono mai essere committati. Le credenziali provider si configurano lato server tramite i flussi dedicati: non inserirle nel frontend o nei template.

Default di sicurezza:

```dotenv
REAL_EXTERNAL_ACTIONS="false"
CONNECTOR_MODE="dry_run"
BRAIN_PROVIDER_GATEWAY="mock"
```

Con questi valori il Social Media Manager non pubblica esternamente. L'interruttore applicativo `ai_real_mode` è distinto dai gate dei connector e non li sostituisce.

## Installazione e avvio

```powershell
cd backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

```powershell
cd frontend
yarn install --frozen-lockfile
yarn start
```

API: `http://localhost:8001/api`; OpenAPI: `http://localhost:8001/docs`.

## Verifica sicura

```powershell
$env:REAL_EXTERNAL_ACTIONS="false"
$env:CONNECTOR_MODE="dry_run"
$env:BRAIN_PROVIDER_GATEWAY="mock"
cd backend
python -m pytest tests
```

I test provider sostituiscono il trasporto HTTP con mock e non devono contenere credenziali reali.

```powershell
cd frontend
$env:CI="true"
yarn test --watchAll=false
yarn build
```

## Sicurezza e Git

- `.env`, chiavi, certificati, database locali, dump, log, cache, build e credenziali sono ignorati.
- Soltanto `.env.example`, con valori non sensibili, deve essere versionato.
- API key e token persistiti sono cifrati e restituiti alla UI solo mascherati.
- Le azioni irreversibili richiedono approvazioni distinte; un timeout di pubblicazione diventa `PUBLISH_UNCERTAIN`, senza retry alla cieca.
- Prima di un commit verificare stato Git, suite backend, test frontend, build e assenza di segreti nel diff.

## Limiti noti

- Il connector Meta deve ancora essere validato in modo controllato con account reale; questa attività non fa parte dei test automatici.
- Le metriche Meta Insights richiedono verifica periodica perché soggette a deprecazione.
- La copertura frontend va estesa oltre registrazione e onboarding, soprattutto per ruoli, Sala Riunioni, Reel e Social Publishing.
- Mancano una pipeline CI versionata e una procedura completa di deployment, backup e restore.
- I moduli backend più grandi sono candidati a una futura separazione router/service/repository.
