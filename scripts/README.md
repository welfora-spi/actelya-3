# Script operativi ACTELYA 3

Avvio/arresto locale dell'ambiente (Windows/PowerShell). Sostituiscono
`recupero-actelya3-20260906\avvio-recuperato.py` (mantenuto lì solo come
riferimento storico) — vedi [`README-DB.md`](README-DB.md) per l'assetto
del database dopo la migrazione del 2026-09-09.

## Uso

```powershell
# Avvia tutto (mongo dedicato -> backend -> frontend), idempotente
.\scripts\start_all.ps1

# Oppure singolarmente
.\scripts\start_mongo.ps1
.\scripts\start_backend.ps1
.\scripts\start_frontend.ps1

# Arresto controllato (shutdown pulito di mongo, mai un kill diretto)
.\scripts\stop_all.ps1
```

Ogni script rileva un processo già in ascolto sulla propria porta e non ne
avvia uno duplicato. Nessuno script contiene credenziali: il backend legge
tutto da `backend\.env` (già presente, non versionato).

## Porte

| Servizio | Porta | Note |
|---|---|---|
| MongoDB (dedicato ACTELYA 3) | 27030 | `data\actelya3_dev`, esterno al repo — vedi README-DB.md |
| Backend (FastAPI/uvicorn) | 8001 | `http://127.0.0.1:8001/api`, OpenAPI su `/docs` |
| Frontend (CRA/craco) | 3000 | `http://127.0.0.1:3000` |

## Log

`..\logs\backend-<timestamp>.{out,err}.log` e
`..\logs\frontend-<timestamp>.{out,err}.log` dentro il repository (già
ignorati da git via `*.log`). I log di MongoDB restano fuori dal
repository, in `C:\Users\pata0\ActelyaRuntime\logs\` (vedi README-DB.md).

## Cosa NON fanno questi script

- Non approvano piani, non generano contenuti, non chiamano `/tick`.
- Non avviano nulla se non è già stato verificato (prima di ogni avvio in
  questa attività) che non ci siano task `IN_CODA` con marcatore di
  auto-dispatch né task `IN_ESECUZIONE` da riprendere: il recovery del
  backend (`server.py::startup`) riprende solo l'esecuzione IN_ESECUZIONE
  interrotta da un riavvio, mai la coda storica — ma se in futuro tale
  coda dovesse contenere qualcosa, avviare il backend la farebbe partire
  per davvero (costi API reali se l'organizzazione è in modalità REALE).
  Verificare sempre prima con una query di sola lettura sulla collezione
  `tasks`, come fatto qui, prima di un avvio non presidiato.
