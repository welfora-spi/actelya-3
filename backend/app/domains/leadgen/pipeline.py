"""Lead Generation — orchestrazione della pipeline reale:
upload -> validazione -> parsing -> mapping -> normalizzazione -> deduplica
-> compliance -> scoring -> segmentazione -> review -> approval ->
export/handoff.

Il job di import gira come coda persistente con un worker recuperabile
(stesso pattern di domains/discovery.py::worker_loop/recover_on_startup):
un import puo' restare IN_CODA (stato 'UPLOADED') mentre l'utente continua
a lavorare altrove, e un riavvio del processo non perde il lavoro (i job
bloccati in uno stato intermedio vengono riportati a UPLOADED, mai persi,
mai duplicati)."""
from __future__ import annotations

import asyncio
import logging

from ...models import new_id, now_iso
from .compliance import evaluate_compliance
from .dedup import apply_merge, find_exact_duplicates, find_probable_duplicates
from .enrichment import apply_enrichment_result, rescore_after_enrichment
from .mapping import apply_mapping
from .next_action import decide_next_action
from .normalize import normalize_record
from .scoring import score_record

logger = logging.getLogger("actelya.leadgen")

_worker_task = None
RUN_DELAY_SECONDS = 1  # simula "elaborazione in corso" cosi' lo stato e' osservabile


def _is_person_record(campo_mapping: dict) -> bool:
    """Un record e' 'persona' quando il mapping produce almeno un campo
    identificativo di un individuo (nome/cognome/ruolo/email/telefono
    diretti): un file di sole aziende non genera mai automaticamente
    persone -- item 7, mai dedurre un contatto umano da soli dati aziendali."""
    campi_persona = {"nome", "cognome", "ruolo"}
    return bool(campi_persona & set(campo_mapping.keys()))


async def run_import_job(db, job: dict) -> None:
    """Elabora UN job di import: claim atomico (find_one_and_update sullo
    stato UPLOADED), poi parsing gia' effettuato a monte (righe gia' salvate
    sul job da router.py al momento della creazione, per evitare di tenere
    il file intero in memoria per tutta la coda) -> mapping -> normalizza
    -> dedup -> compliance -> scoring -> persist. Idempotente: un job gia'
    COMPLETATO/FALLITO non viene mai rielaborato da qui."""
    job_id = job["id"]
    claimed = await db.lead_import_jobs.find_one_and_update(
        {"id": job_id, "status": "UPLOADED"},
        {"$set": {"status": "PARSING", "updated_at": now_iso()}},
    )
    if not claimed:
        return
    org_id = job["organization_id"]
    actor_id = job["created_by"]
    await asyncio.sleep(RUN_DELAY_SECONDS)

    try:
        righe_mappate = apply_mapping(job["columns"], job["rows"], job["mapping"])
        record_normalizzati = []
        for riga in righe_mappate:
            if not any((v or "").strip() for v in riga.values()):
                continue
            normalizzato = normalize_record(riga, method="ESTRATTO")
            if not normalizzato:
                continue
            record_normalizzati.append({
                "id": new_id("lead"), "is_person": _is_person_record(riga), **normalizzato,
            })

        await db.lead_import_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "NORMALIZED", "updated_at": now_iso(),
                                      "counts.parsed": len(job["rows"]), "counts.normalized": len(record_normalizzati)}},
        )

        by_id = {r["id"]: r for r in record_normalizzati}
        esatti = find_exact_duplicates(record_normalizzati)
        probabili = find_probable_duplicates(record_normalizzati)
        for gruppo in esatti:
            is_person = bool(by_id.get(gruppo["record_ids"][0], {}).get("is_person"))
            await db.lead_dedup_reviews.insert_one({
                "id": new_id("dedup"), "organization_id": org_id, "campaign_id": job.get("campaign_id"),
                "import_job_id": job_id, "tipo": gruppo["tipo"], "match_type": "ESATTO", "is_person": is_person,
                "record_ids": gruppo["record_ids"], "status": "PENDING",
                "created_at": now_iso(), "created_by": actor_id,
            })
        for coppia in probabili:
            is_person = bool(by_id.get(coppia["record_a"], {}).get("is_person"))
            await db.lead_dedup_reviews.insert_one({
                "id": new_id("dedup"), "organization_id": org_id, "campaign_id": job.get("campaign_id"),
                "import_job_id": job_id, "tipo": coppia["tipo"], "match_type": "PROBABILE", "is_person": is_person,
                "record_ids": [coppia["record_a"], coppia["record_b"]], "similarita": coppia["similarita"],
                "status": "PENDING", "created_at": now_iso(), "created_by": actor_id,
            })

        campagna = await db.lead_campaigns.find_one({"id": job.get("campaign_id")}, {"_id": 0}) or {}
        icp = campagna.get("icp") or {}
        escludi_clienti = campagna.get("exclude_existing_customers", True)

        await db.lead_import_jobs.update_one({"id": job_id}, {"$set": {"status": "SCORING", "updated_at": now_iso()}})

        conteggi = {"qualified": 0, "review_required": 0, "incomplete": 0, "excluded": 0, "do_not_contact": 0}
        for record in record_normalizzati:
            is_person = record.pop("is_person")
            decisione = evaluate_compliance(record, is_person=is_person)
            esito = score_record(record, icp, is_person=is_person, compliance_status=decisione.status,
                                 exclude_existing_customers=escludi_clienti)
            azione = decide_next_action(qualification_status=esito.qualification_status,
                                        missing_data=esito.dati_mancanti, record=record)
            documento = {
                **record, "organization_id": org_id, "campaign_id": job.get("campaign_id"),
                "import_job_id": job_id, "is_person": is_person,
                "score": esito.score, "score_components": [c.come_dict() for c in esito.componenti],
                "confidence": esito.confidence, "missing_data": esito.dati_mancanti,
                "qualification_status": esito.qualification_status,
                "compliance_status": decisione.status, "compliance_motivi": decisione.motivi,
                "rules_applied": esito.regole_applicate, "next_action": azione,
                "merge_history": [], "merged_from_ids": [],
                "created_at": now_iso(), "created_by": actor_id, "updated_at": now_iso(),
            }
            collezione = db.lead_persons if is_person else db.lead_companies
            await collezione.insert_one(documento)
            chiave = esito.qualification_status.lower()
            if chiave in conteggi:
                conteggi[chiave] += 1

        stato_finale = "REVIEW_REQUIRED" if (esatti or probabili) else "READY_FOR_APPROVAL"
        await db.lead_import_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": stato_finale, "updated_at": now_iso(), "finished_at": now_iso(),
                      "counts.qualified": conteggi["qualified"], "counts.review_required": conteggi["review_required"],
                      "counts.incomplete": conteggi["incomplete"], "counts.excluded": conteggi["excluded"],
                      "counts.do_not_contact": conteggi["do_not_contact"],
                      "counts.duplicates_exact": len(esatti), "counts.duplicates_probable": len(probabili)}},
        )
        if job.get("campaign_id"):
            await db.lead_campaigns.update_one(
                {"id": job["campaign_id"]}, {"$set": {"status": "REVIEW_REQUIRED" if (esatti or probabili) else "READY_FOR_APPROVAL",
                                                       "updated_at": now_iso()}},
            )
    except Exception:
        logger.exception("Import lead gen fallito (job_id=%s)", job_id)
        await db.lead_import_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "FAILED", "updated_at": now_iso(), "finished_at": now_iso()}},
        )


async def apply_merge_decision(db, review: dict, *, action: str, actor: str) -> dict:
    """Applica la decisione di review su un duplicato ESATTO (mai su uno
    PROBABILE senza revisione umana esplicita — il chiamante, router.py,
    verifica gia' che 'review' esista e non sia gia' decisa). action:
    'MERGE' unisce i record (il primo id della lista resta il superstite,
    gli altri vengono marcati merged); 'KEEP_SEPARATE' chiude la review
    senza modificare alcun record."""
    ids = review["record_ids"]
    collezione = db.lead_persons if review.get("is_person") else db.lead_companies
    if action == "MERGE" and len(ids) >= 2:
        primario = await collezione.find_one({"id": ids[0]}, {"_id": 0})
        for altro_id in ids[1:]:
            secondario = await collezione.find_one({"id": altro_id}, {"_id": 0})
            if not primario or not secondario:
                continue
            esito = apply_merge(primario, secondario, actor=actor, now_iso=now_iso())
            primario = esito.merged
            await collezione.update_one({"id": altro_id}, {"$set": {"qualification_status": "MERGED_INTO_ALTRO",
                                                                     "merged_into": ids[0], "updated_at": now_iso()}})
        if primario:
            await collezione.update_one({"id": ids[0]}, {"$set": primario})
    await db.lead_dedup_reviews.update_one(
        {"id": review["id"]},
        {"$set": {"status": "MERGED" if action == "MERGE" else "KEPT_SEPARATE",
                  "decided_by": actor, "decided_at": now_iso()}},
    )
    return {"id": review["id"], "status": "MERGED" if action == "MERGE" else "KEPT_SEPARATE"}


async def request_enrichment(db, *, org_id: str, lead_type: str, lead_id: str, actor: str) -> dict:
    """Crea una richiesta esplicita di arricchimento per un lead con dati
    mancanti, con le capability ASTRATTE necessarie (next_action.py — mai un
    nome di provider). Resta IN_ATTESA finché un adapter reale (quando un
    provider sarà collegato al Tool Registry) o un adapter di test (nei
    test) non produce un risultato da applicare con
    apply_enrichment_result_for_lead()."""
    if lead_type not in ("aziende", "persone"):
        raise ValueError(f"Tipo di lead sconosciuto: '{lead_type}'.")
    collezione = db.lead_persons if lead_type == "persone" else db.lead_companies
    lead = await collezione.find_one({"id": lead_id, "organization_id": org_id}, {"_id": 0})
    if not lead:
        raise ValueError("Lead non trovato.")
    capability = (lead.get("next_action") or {}).get("capability_richieste") or []
    if not capability:
        raise ValueError("Nessuna capability di arricchimento necessaria per questo lead (vedi next_action).")
    richiesta = {
        "id": new_id("enrich"), "organization_id": org_id, "lead_type": lead_type, "lead_id": lead_id,
        "capability_richieste": capability, "status": "IN_ATTESA", "conflitti": [],
        "created_by": actor, "created_at": now_iso(), "updated_at": now_iso(),
        "fulfilled_at": None, "result_source": None,
    }
    await db.lead_enrichment_requests.insert_one(richiesta)
    return {k: v for k, v in richiesta.items() if k != "_id"}


async def apply_enrichment_result_for_lead(db, request: dict, *, result_fields: dict, source: str, actor: str) -> dict:
    """Applica il risultato di un arricchimento (oggi sempre da un adapter di
    TEST — nessun provider reale collegato in questa fase, vedi
    enrichment.py) a un lead: valida/normalizza/rileva conflitti, ricalcola
    scoring e prossima azione, marca la richiesta COMPLETATA. Questa logica
    resta identica quando un adapter reale (Apollo/Hunter/...) sarà
    collegato al Tool Registry: cambia solo la provenienza di result_fields."""
    if request["status"] != "IN_ATTESA":
        raise ValueError(f"Richiesta già evasa (stato attuale: {request['status']}).")
    lead_type = request["lead_type"]
    collezione = db.lead_persons if lead_type == "persone" else db.lead_companies
    lead = await collezione.find_one(
        {"id": request["lead_id"], "organization_id": request["organization_id"]}, {"_id": 0})
    if not lead:
        raise ValueError("Lead non trovato.")

    esito = apply_enrichment_result(lead, result_fields=result_fields, source_method="ESTRATTO")
    aggiornato = esito["record"]
    campagna = await db.lead_campaigns.find_one({"id": lead.get("campaign_id")}, {"_id": 0}) or {}
    ricalcolo = rescore_after_enrichment(
        aggiornato, icp=campagna.get("icp") or {}, is_person=lead.get("is_person", False),
        exclude_existing_customers=campagna.get("exclude_existing_customers", True),
    )
    aggiornato.update(ricalcolo)
    aggiornato["updated_at"] = now_iso()
    await collezione.update_one({"id": lead["id"]}, {"$set": aggiornato})

    await db.lead_enrichment_requests.update_one(
        {"id": request["id"]},
        {"$set": {"status": "COMPLETATA", "fulfilled_at": now_iso(), "result_source": source,
                  "conflitti": esito["conflitti"], "updated_at": now_iso()}},
    )
    return {
        "lead": await collezione.find_one({"id": lead["id"]}, {"_id": 0}),
        "conflitti": esito["conflitti"],
        "request": await db.lead_enrichment_requests.find_one({"id": request["id"]}, {"_id": 0}),
    }


async def worker_loop(db) -> None:
    logger.info("Lead Generation worker avviato")
    while True:
        try:
            pending = await db.lead_import_jobs.find({"status": "UPLOADED"}, {"_id": 0}).sort("created_at", 1).to_list(10)
            for job in pending:
                await run_import_job(db, job)
        except Exception:
            logger.exception("Errore nel worker Lead Generation")
        await asyncio.sleep(1)


async def recover_on_startup(db) -> None:
    stati_non_terminali = ["PARSING", "NORMALIZED", "SCORING"]
    res = await db.lead_import_jobs.update_many(
        {"status": {"$in": stati_non_terminali}},
        {"$set": {"status": "UPLOADED", "updated_at": now_iso()}},
    )
    if res.modified_count:
        logger.info("Lead Generation recovery: %s job riportati in coda", res.modified_count)


def start_worker(db) -> None:
    global _worker_task
    if _worker_task is None:
        _worker_task = asyncio.create_task(worker_loop(db))
