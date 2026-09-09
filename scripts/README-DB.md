# Database ACTELYA 3 — assetto dopo la migrazione del 2026-09-09

Questo file sostituisce, per ACTELYA 3, il precedente
`recupero-actelya3-20260906\README-DB.md` (verificato 2026-09-08, ancora
corretto come **cronologia**, ma non più come configurazione attiva).

## Istanza attiva (usata da `backend/.env`)

- **Porta 27030**, dbpath `C:\Users\pata0\ActelyaRuntime\data\actelya3_dev`
  (fuori dal repository, fuori da OneDrive).
- Contiene **solo** `actelya3_dev` — nessun altro database co-locato.
- Migrata da `mongodb://127.0.0.1:27020/actelya3_dev` (vedi sotto) il
  2026-09-09 via `mongodump`/`mongorestore` (backup logico nativo, mai una
  copia a caldo dei file WiredTiger).
- Verificata dopo il ripristino: 51/51 collezioni, 57.282/57.282 documenti,
  stessi indici, e confronto byte-per-byte di record chiave (utente
  `raffaele.patarino@spitool.it`, organizzazione
  `org-8217fe159054488c831a`, piano `plan-9d6c1fe7d3104729bb14` con il suo
  deliverable `content_item` e i 3 content_item referenziati) tra sorgente
  e destinazione — tutti identici.
- Avvio: `scripts\start_mongo.ps1` (idempotente).

## Sorgente originale (conservata come rollback, NON cancellare)

- **Porta 27020**, dbpath
  `recupero-actelya3-20260906\data-seconda` (dentro OneDrive — per questo
  la migrazione sopra esiste).
- Contiene ANCHE `actelya2_db` (progetto diverso, fuori perimetro di questo
  intervento): per questo la migrazione è stata fatta a livello di singolo
  database (`mongodump --db actelya3_dev`), mai spostando l'intera cartella.
- **ACTELYA 2 continua a dipendere da questa istanza/porta/cartella**: non
  è stata toccata, spostata né riconfigurata. Se in futuro va spostata
  anche quella, è una decisione/attività separata che riguarda ACTELYA 2.
- Rollback per ACTELYA 3: riportare `MONGO_URL` in `backend/.env` a
  `mongodb://127.0.0.1:27020` e avviare questa istanza con lo stesso
  binario (vedi sotto) puntato su `data-seconda` — i dati storici di
  `actelya3_dev` sono ancora lì, invariati.

## Copia storica più piccola (invariata, non riguardata da questa attività)

- **Porta 27019**, dbpath `recupero-actelya3-20260906\data` — copia più
  piccola e più vecchia di `actelya3_dev` (14 collezioni, 47 documenti),
  mai stata quella reale. Non toccata da questa migrazione.

## Binari (portable, MAI versionati in git)

- `C:\Users\pata0\ActelyaRuntime\bin\mongod-7.0.14\mongod.exe` — stessa
  versione (7.0.14) che ha creato originariamente `data-seconda`
  (verificato dal campo `buildInfo.version` nei log storici prima di
  usarlo, per evitare un mismatch di formato dati). Trovato nello
  scratchpad di una sessione Claude Code precedente e copiato qui per
  persistenza (uno scratchpad `AppData\Local\Temp\claude\...` NON è
  garantito sopravvivere). Se questo file dovesse mancare in futuro: va
  procurato un mongod Windows x86_64 versione 7.0.x (server community,
  build "windows" sul sito ufficiale) — MAI un binario più recente puntato
  direttamente su `data-seconda` senza prima verificarne di nuovo la
  compatibilità.
- `C:\Users\pata0\ActelyaRuntime\bin\mongodump.exe`,
  `mongorestore.exe`, `bsondump.exe` — MongoDB Database Tools 100.9.4
  (scaricati dal sito ufficiale MongoDB il 2026-09-09).

## Backup nativo della migrazione

- `C:\Users\pata0\ActelyaRuntime\backups\20260909-102327\actelya3_dev\`
  — dump `mongodump` completo (solo `actelya3_dev`, BSON nativo con tipi,
  indici e opzioni delle collezioni), prodotto dalla sorgente 27020 PRIMA
  del cutover. È la fonte usata sia per la verifica in isolamento (istanza
  temporanea, poi eliminata) sia per il ripristino nell'istanza definitiva
  27030. Non cancellare: è la prova che la migrazione è verificabile.

## Osservazione non risolta in questa attività

Sull'istanza 27020 esistono anche database di test residui
(`actelya3_test`, `actelya3_test_m2auto`, `actelya3_test_m2real`,
`actelya3_test_m2real_regress`, `actelya3_test_m2real_smoke`,
`actelya3_test_unused`), probabilmente creati da esecuzioni storiche della
suite pytest puntate per errore su questa istanza invece che su un
database/servizio dedicato ai test. Non toccati, non necessari per questa
migrazione — segnalato per eventuale pulizia futura, decisione dell'utente.

## Come verificare di nuovo

```text
mongodb://127.0.0.1:27030/actelya3_dev  -> istanza dedicata ACTELYA 3 (usa questa)
mongodb://127.0.0.1:27020/actelya3_dev  -> sorgente/rollback (contiene ANCHE actelya2_db)
mongodb://127.0.0.1:27019/actelya3_dev  -> copia storica, non usarla
```
