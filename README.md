# ACTELYA 2

**Sistema operativo AI per marketing e vendite** — non un semplice generatore di email né una demo grafica.

ACTELYA 2 riceve un **obiettivo** in linguaggio naturale, lo **interpreta**, prepara un **piano**, stima **costi e rischi**, richiede **approvazioni** ed **esegue realmente** tramite agenti e integrazioni autorizzate. Ogni azione potenzialmente irreversibile (invio, pubblicazione, spesa, contatto reale) è governata da regole deterministiche e da un Centro Approvazioni: nulla di esterno accade senza autorizzazione umana esplicita.

> **Milestone 1** gira interamente in **MODALITÀ SIMULAZIONE**: nessuna chiamata AI reale e nessun invio vengono effettuati. Il provider AI è simulato e chiaramente marcato.

---

## Architettura

| Livello | Tecnologia |
|---|---|
| Frontend | **React** (CRA + Tailwind + shadcn/ui, tema scuro), Recharts |
| Backend | **FastAPI** modulare per dominio (`backend/app/domains/*`) |
| Database | **MongoDB** (motor async) |
| Esecuzioni | **Coda persistente** su MongoDB con worker in background **recuperabile dopo il riavvio** (nessun duplicato) |
| Auth | JWT (cookie httpOnly + fallback Bearer), bcrypt |

Domini backend principali: `auth`, `org`, `users_mgmt`, `connections` (provider AI + integrazioni), `intent` (classificatore ibrido), `estimator` (preventivi), `approvals` (Centro Approvazioni idempotente), `engine` (coda + esecuzione + deliverable), `agents` (orchestratore + agenti con contratto), `validators` (contratto EMAIL + prerequisiti azione esterna), `budget`, `settings`, `stats`/`audit`.

---

## Requisiti

- Python 3.11+
- Node.js 18+ e **Yarn** (non usare npm)
- MongoDB in esecuzione (locale o remoto)

## Installazione

```bash
# Backend
cd backend
pip install -r requirements.txt

# Frontend
cd ../frontend
yarn install
```

## Configurazione (.env)

I file `.env` **non sono inclusi nel repository**. Copia gli esempi e valorizza le variabili localmente:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env   # se presente
```

`backend/.env.example` (valori dei segreti vuoti — da compilare in locale):

```
MONGO_URL="mongodb://localhost:27017"
DB_NAME="actelya2_db"
CORS_ORIGINS="*"
FRONTEND_URL="http://localhost:3000"
JWT_SECRET=""        # genera una stringa casuale robusta (es. 64 hex)
MASTER_KEY=""        # chiave Fernet base64 urlsafe (32 byte) per cifrare le API key
ADMIN_EMAIL=""       # email dell'account admin iniziale
ADMIN_PASSWORD=""    # password iniziale dell'admin (cambio obbligatorio al primo accesso)
```

Note di sicurezza sulle variabili:
- **`MASTER_KEY`** è fornita **solo** via variabile d'ambiente e **mai** salvata nel database. Se manca o non è valida, la gestione delle credenziali si blocca in modo sicuro.
- **`JWT_SECRET`** firma le sessioni: usa un valore casuale e riservato.
- L'account admin viene creato al primo avvio in modo **idempotente** (create-only). Un reset della password admin avviene **solo** se imposti `FORCE_RESET_ADMIN=true`.

## Avvio

Frontend e backend sono gestiti da un supervisor nell'ambiente di sviluppo. In locale:

```bash
# Backend (porta 8001, prefisso API /api)
cd backend
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# Frontend (porta 3000)
cd frontend
yarn start
```

Documentazione API interattiva: `http://localhost:8001/docs`.

## Test

La suite di regressione **non contiene credenziali**: le password di test si passano via ambiente.

```bash
cd backend
ADMIN_TEST_PASSWORD='<password-admin-corrente>' \
ADMIN_SEED_PASSWORD='<password-seed-iniziale>' \
python -m pytest tests/test_actelya_backend.py -q
```

**Risultato atteso: `12 passed` (12/12 PASS).** Copre: autenticazione e ruoli, mascheramento/protezione segreti, classificazione intento, bozza vs azione esterna, validazione campi non vuoti e placeholder, tre stati separati, doppio click e idempotenza, budget, audit senza segreti, durabilità della password dopo riavvio, nessun contenuto contato senza deliverable, nessuna azione esterna senza approvazione.

---

## Ruoli

| Ruolo | Descrizione |
|---|---|
| `ADMIN` | Configurazione completa: connessioni/API, utenti, budget, modalità AI REALE |
| `OPERATORE` | Crea obiettivi, gestisce profilo aziendale e contenuti |
| `APPROVATORE` | Approva/rifiuta le richieste nel Centro Approvazioni |
| `SOLA_LETTURA` | Sola consultazione |

---

## Flusso completo — Milestone 1

1. L'utente inserisce un **obiettivo**.
2. Il sistema **classifica l'intento** (regole deterministiche + AI simulata solo per l'ambiguità).
3. Prepara un **piano** e seleziona gli **agenti** necessari.
4. Genera un **preventivo** con costo **minimo / probabile / massimo** e **tetto approvabile** (senza chiamate reali).
5. Mostra **rischi**, prerequisiti ed eventuali **azioni esterne**.
6. Crea una richiesta nel **Centro Approvazioni**.
7. Dopo l'**approvazione** (idempotente) viene creata **una sola esecuzione** persistita e messa **in coda**.
8. Il **worker** esegue gli agenti (simulati), **valida** l'output e produce un **deliverable** persistito.
9. Aggiorna **costi simulati, token e audit**; per eventuali azioni esterne richiede un'ulteriore approvazione.

Doppio click, retry, resume e richieste concorrenti **non** creano duplicati o doppie spese (indice unico sull'approvazione + claim atomico + recovery dopo riavvio).

### Contratto minimo EMAIL
Un deliverable email valido richiede stringhe **non vuote** per **oggetto/hook**, **contenuto completo** e **CTA**. I placeholder (es. `[Nome]`, `[Azienda]`, `[Link appuntamento]`, `[Data]`, `[Firma]`) sono ammessi solo per i campi variabili; se oggetto/proposta/CTA sono composti prevalentemente da placeholder → `BLOCCATO`.

---

## Tre stati indipendenti

Non esiste un unico stato generale. Ogni obiettivo espone **tre stati separati**:

- **`execution_status`** (tecnico): `IN_CODA` · `IN_ESECUZIONE` · `COMPLETATA` · `FALLITA` · `ARRESTATA`
- **`deliverable_status`** (risultato): `COMPLETATO` · `COMPLETATO_CON_AVVISI` · `BLOCCATO`
- **`action_status`** (azione esterna): `NON_RICHIESTA` · `IN_ATTESA_APPROVAZIONE` · `AUTORIZZATA` · `BLOCCATA` · `ESEGUITA` · `FALLITA`

Una pipeline può essere `COMPLETATA` mentre il deliverable è `BLOCCATO`: in tal caso la dashboard **non** dichiara l'obiettivo riuscito. Una bozza può essere prodotta anche quando l'invio resta `BLOCCATA` per prerequisiti mancanti (destinatari, consenso/base giuridica, integrazione, approvazione).

---

## Modalità SIMULAZIONE (default)

All'avvio il sistema è in **SIMULAZIONE**: nessuna chiamata AI reale, nessun invio. L'interfaccia distingue sempre visibilmente **SIMULAZIONE** (ambra) da **REALE** (rosso) tramite banner e bordo superiore.

L'interruttore **AI REALE** (solo `ADMIN`) può essere attivato **soltanto** quando: esiste almeno una connessione AI **verificata**, è configurato un **budget**, ed è presente una **conferma esplicita**. L'attivazione **non** effettua alcuna chiamata automatica.

---

## Funzioni operative vs solo predisposte (Milestone 1)

**Operative e verificate:**
- Autenticazione/ruoli, profilo aziendale, utenti (con export/cancellazione e audit)
- Classificazione intento, preventivi, Centro Approvazioni idempotente
- Coda persistente, esecuzione agenti simulati, validazione contratto EMAIL, deliverable
- Connessioni AI: CRUD, API key **cifrata e mascherata**, TESTA CONNESSIONE a due step (anteprima + conferma) **simulato**
- Budget e costi (simulati), Audit Log (senza segreti), interruttore AI REALE con prerequisiti

**Solo predisposte (mostrate come "Non ancora collegata"):**
- Provider AI reali (chiamate reali) — da configurare e testare dall'utente dopo la Milestone 1
- Integrazioni: email/SMTP, Microsoft 365, Gmail, Google Calendar, Meta, Instagram, LinkedIn, Google Ads, Meta Ads, CRM, webhook, provider prospect B2B, Registro Pubblico delle Opposizioni, analytics

---

## Sicurezza e regola sui segreti

- **Non committare mai segreti.** `.env`, master key, password, API key, token, cookie e dump MongoDB sono esclusi tramite `.gitignore`. Nel repository è presente **solo `.env.example`** con valori vuoti.
- Le password sono salvate **esclusivamente** come hash **bcrypt**.
- Le **API key** sono **cifrate lato server** (Fernet con `MASTER_KEY`) prima della persistenza; al frontend tornano **solo mascherate** (ultimi 4 caratteri) e non compaiono mai in log, audit, errori o export.
- Sessioni protette (cookie httpOnly), autorizzazioni centralizzate per ruolo, rate limiting sugli endpoint sensibili, protezione brute-force e audit delle operazioni amministrative.
- Nessun segreto viene restituito dalle API dopo il salvataggio.

---

## Roadmap (milestone successive)

- **M2 — Provider AI reale**: prima connessione verificata e primo test reale con anteprima (provider, modello, agenti, numero massimo chiamate, tetto di spesa, dati inviati, conferma finale).
- **M3 — Invio reale**: integrazione email (SMTP/Gmail) con verifica destinatari, consenso/base giuridica e Registro Opposizioni, per portare l'azione esterna da `BLOCCATA` a `ESEGUITA`.
- **M4 — Canali marketing**: Meta/Instagram/LinkedIn, Google Ads/Meta Ads, CRM e webhook.
- **M5 — Multi-tenant** reale e analytics/performance avanzate.

---

*Milestone 1 stable — simulated end-to-end flow. Tutte le funzioni visibili sono operative oppure chiaramente indicate come "Non ancora collegata".*
