# ACTELYA 3 — Product Requirements Document

## Visione

ACTELYA 3 è un sistema operativo AI multi-tenant per marketing e vendite. Trasforma una richiesta in linguaggio naturale in un piano verificabile, seleziona gli agenti necessari, produce deliverable e governa costi, rischi, revisioni e azioni esterne.

Principi non negoziabili:

- nessun segreto nel codice o nel frontend;
- nessuna spesa o pubblicazione senza configurazione e conferma esplicite;
- simulazione, dry-run e operazioni reali sempre distinguibili;
- isolamento per organizzazione su ogni risorsa;
- audit, idempotenza e recovery per i workflow persistenti;
- contenuti e metriche mai presentati come reali quando sono simulati o indisponibili.

## Utenti e ruoli

- `ADMIN`: tenant, utenti, connessioni, budget e configurazione.
- `OPERATORE`: obiettivi, piani e produzione dei contenuti.
- `APPROVATORE`: approvazioni e rifiuti motivati.
- `SOLA_LETTURA`: consultazione.

La registrazione self-service crea una nuova organizzazione e il primo amministratore. Le API applicano l'isolamento tenant lato server.

## Architettura corrente

- Frontend React/CRA/CRACO con Tailwind, Radix/shadcn, Recharts e routing per ruolo.
- Backend FastAPI modulare con MongoDB asincrono tramite Motor.
- Auth JWT con cookie httpOnly e fallback Bearer; password bcrypt; segreti cifrati Fernet.
- Worker persistenti per esecuzioni, discovery e scheduling social.
- Motore M2 con piani DAG, task, lease, budget, recovery e deliverable versionati.
- Brain con classificazione, contesto, registry agenti, handoff e gateway sicuri.
- Adapter separati per Requesty, Runway e Meta.

Il progetto tecnico storico M2 è conservato in [`architecture/MILESTONE2_DESIGN.md`](architecture/MILESTONE2_DESIGN.md).

## Capability completate

### Piattaforma

- autenticazione, refresh, logout, cambio password, RBAC e audit;
- gestione utenti, profilo aziendale, onboarding e Fact Ledger;
- budget, obiettivi, approvazioni ed esecuzioni M1;
- piani M2, DAG, task, revisioni e deliverable;
- Dashboard, Sala Riunioni, piani, connessioni e impostazioni.

### Produzione contenuti

- email e sei contratti deliverable M2;
- Reel con copy, caption, hashtag, validazione, versioni e video;
- Flyer con copy, versioni, asset e immagini;
- approvazioni separate per contenuto e media;
- blocco di output vuoti, placeholder impropri, PII e claim non supportati.

### Social Media Manager

- memoria persistente e suggerimenti derivati da dati misurati;
- pacchetti di pubblicazione, approvazione dedicata e scheduling;
- idempotenza, recovery e risoluzione manuale degli esiti incerti;
- adapter Facebook Page e Instagram Professional;
- stato connessione, permessi ed errori tipizzati;
- metriche nullable ed engagement calcolato solo da dati disponibili.

Il codice Social/Meta è consolidato nel tag `social-media-manager-v1.0`. I test usano trasporto mockato: la validazione live di Meta non è parte della Definition of Done locale.

## Sicurezza operativa

Il Brain resta mock-only con `BRAIN_PROVIDER_GATEWAY=mock`. Una pubblicazione Meta reale richiede contemporaneamente:

1. `REAL_EXTERNAL_ACTIONS=true`;
2. `CONNECTOR_MODE=real`;
3. adapter reale registrato;
4. connessione Meta del tenant configurata e verificata;
5. contenuto, media e pubblicazione approvati;
6. asset accessibile pubblicamente.

Il default è `REAL_EXTERNAL_ACTIONS=false` e `CONNECTOR_MODE=dry_run`. La suite automatica deve mantenere questi valori e mockare ogni trasporto provider.

## Stati principali

- Esecuzione: `IN_CODA`, `IN_ESECUZIONE`, `COMPLETATA`, `FALLITA`, `ARRESTATA`.
- Deliverable: `COMPLETATO`, `COMPLETATO_CON_AVVISI`, `BLOCCATO`.
- Azione esterna: `NON_RICHIESTA`, `IN_ATTESA_APPROVAZIONE`, `AUTORIZZATA`, `BLOCCATA`, `ESEGUITA`, `FALLITA`.
- Pubblicazione social: bozza, approvazione, scheduling, pubblicazione, fallimento e `PUBLISH_UNCERTAIN`.

Lo stato tecnico non sostituisce lo stato del risultato o dell'azione esterna.

## Criteri di rilascio

- suite pytest completa verde con provider mockati;
- test Jest e build frontend verdi;
- nessun `.env`, token, chiave, dump, database o log tracciato;
- `.env.example` completi e privi di credenziali;
- working tree e diff revisionati;
- smoke test con MongoDB isolato dai dati di produzione;
- nessuna chiamata provider reale durante CI.

## Lavoro residuo

1. Pipeline CI con test, build, lint e scansione segreti.
2. Copertura frontend di route protette, Sala Riunioni, Reel e Social Publishing.
3. Procedure di deployment, osservabilità, backup/restore e migrazioni dati.
4. Rate limiting condiviso per deployment multi-processo.
5. Transazione o compensazione esplicita nella registrazione tenant.
6. Separazione dei moduli backend più grandi in router, service, repository e adapter.
7. Verifica Meta manuale e controllata, solo quando autorizzata e provvista di credenziali.

Non sono obiettivi impliciti: configurare Meta reale, pubblicare contenuti, introdurre nuovi provider o migrare dati di ACTELYA 1/2.
