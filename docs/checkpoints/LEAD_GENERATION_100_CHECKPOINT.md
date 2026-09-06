# Lead Generation — checkpoint (verso il 100%)

Audit del dominio già esistente (`backend/app/domains/leadgen/`, costruito in
un blocco precedente) rispetto ai criteri richiesti: ICP, segmenti, query di
ricerca, criteri inclusione/esclusione, lifecycle completo (acquisizione →
normalizzazione → enrichment → dedup → scoring → segmentazione → stato →
priorità → provenance) erano già implementati e testati. **Lacune reali
colmate in questo blocco:**

1. **"Quali dati mancano e quale capability richiedere"** — non esisteva.
   Aggiunto `next_action.py`: decide deterministicamente
   `CONTINUA_ENRICHMENT` (con capability ASTRATTE — `EMAIL_DISCOVERY`,
   `PERSON_ENRICHMENT`, `COMPANY_ENRICHMENT`, mai un nome di provider) /
   `SCARTA` / `NURTURING` / `PRONTO_PER_SALES`. Un lead `QUALIFIED` ma privo
   di un canale di contatto (email O telefono) resta `CONTINUA_ENRICHMENT`:
   Sales non riceve mai un lead non raggiungibile.
2. **Applicazione di un risultato di arricchimento** — non esisteva.
   Aggiunto `enrichment.py::apply_enrichment_result` (valida, normalizza,
   rileva conflitti con la STESSA scala di confidenza per metodo già usata da
   `scoring.py` — un dato VERIFICATO non è mai declassato da un dato
   ESTRATTO) + `rescore_after_enrichment` (ricalcola scoring, compliance,
   qualificazione, prossima azione).
3. **Richiesta/applicazione per-lead** — nuove funzioni pipeline
   (`request_enrichment`, `apply_enrichment_result_for_lead`) + endpoint
   (`POST /leadgen/leads/{tipo}/{id}/request-enrichment`,
   `POST /leadgen/enrichment-requests/{id}/apply-result`).

## Principio verificato

La logica applicativa (validazione → normalizzazione → conflitti →
aggiornamento → ricalcolo → prossima azione) è identica indipendentemente da
chi produce `result_fields`: oggi un adapter di TEST nei test, domani un
adapter reale (Apollo/Hunter/...) dietro il Tool Registry — **nessuna riga
di questa logica cambierà quando il provider verrà collegato.**

## Handoff a Sales

`next_action == PRONTO_PER_SALES` è la condizione — la creazione effettiva
del record nella pipeline Sales (dominio non ancora esistente in questo
punto del lavoro) è implementata nel blocco Sales Agent, che legge
esattamente questo segnale.

## File

- `backend/app/domains/leadgen/{next_action,enrichment}.py` (nuovi)
- `backend/app/domains/leadgen/{models,pipeline,router}.py` (estesi, nessuna
  funzione esistente rimossa o rinominata)
- `backend/server.py` — indici `lead_enrichment_requests`

## Test

151 passed (127 preesistenti invariati + 24 nuovi: 15 unità next_action/
enrichment, 5 integrazione pipeline, 4 E2E HTTP). Nessuna chiamata reale.

## Debito residuo

Nessuno sulla logica applicativa. Il connettore reale (Apollo/Hunter/Tavily/
Firecrawl) resta, come da istruzione esplicita, non implementato in questa
fase — le richieste di arricchimento restano `IN_ATTESA` finché un adapter
reale non sarà collegato al Tool Registry.
