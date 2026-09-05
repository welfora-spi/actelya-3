"""Lead Generation — test di integrazione della pipeline reale (MongoDB
locale): normalizza -> deduplica -> compliance -> scoring -> persist,
idempotenza del job, merge dei duplicati esatti."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.domains.leadgen.pipeline import apply_merge_decision, run_import_job
from app.models import new_id, now_iso


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, org):
    for c in ("lead_import_jobs", "lead_companies", "lead_persons", "lead_dedup_reviews", "lead_campaigns"):
        await db[c].delete_many({"organization_id": org})


def _job(org, *, columns, rows, mapping, campaign_id=None):
    return {
        "id": new_id("leadjob"), "organization_id": org, "created_by": "user-test",
        "campaign_id": campaign_id, "columns": columns, "rows": rows, "mapping": mapping,
        "status": "UPLOADED", "created_at": now_iso(), "updated_at": now_iso(),
    }


def test_import_job_normalizza_e_qualifica_record_azienda():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            job = _job(org, columns=["Ragione Sociale", "Email", "Settore", "Città", "Dipendenti"],
                      rows=[["Acme Srl", "info@acme.it", "software", "Milano", "50"]],
                      mapping={"Ragione Sociale": "ragione_sociale", "Email": "email", "Settore": "settore",
                              "Città": "citta", "Dipendenti": "dipendenti"})
            await db.lead_import_jobs.insert_one(job)
            await run_import_job(db, job)

            aggiornato = await db.lead_import_jobs.find_one({"id": job["id"]}, {"_id": 0})
            assert aggiornato["status"] in ("READY_FOR_APPROVAL", "REVIEW_REQUIRED")
            assert aggiornato["counts"]["normalized"] == 1

            aziende = await db.lead_companies.find({"organization_id": org}, {"_id": 0}).to_list(10)
            assert len(aziende) == 1
            assert aziende[0]["ragione_sociale"]["value"] == "Acme Srl"
            assert aziende[0]["is_person"] is False
            assert aziende[0]["score"] > 0
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_import_job_persona_richiede_fonte_e_consenso():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            job = _job(org, columns=["Nome", "Email"], rows=[["Mario", "mario@acme.it"]],
                      mapping={"Nome": "nome", "Email": "email"})
            await db.lead_import_jobs.insert_one(job)
            await run_import_job(db, job)

            persone = await db.lead_persons.find({"organization_id": org}, {"_id": 0}).to_list(10)
            assert len(persone) == 1
            assert persone[0]["is_person"] is True
            assert persone[0]["compliance_status"] == "BLOCKED"  # nessuna 'fonte' dichiarata
            assert persone[0]["qualification_status"] == "EXCLUDED"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_import_job_idempotente_non_rielabora_se_gia_avviato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            job = _job(org, columns=["Ragione Sociale"], rows=[["Acme Srl"]],
                      mapping={"Ragione Sociale": "ragione_sociale"})
            await db.lead_import_jobs.insert_one(job)
            await run_import_job(db, job)
            aziende_prima = await db.lead_companies.count_documents({"organization_id": org})

            # Richiamare run_import_job con lo STESSO job (stato ormai non
            # piu' UPLOADED) non deve produrre un secondo claim/una seconda
            # elaborazione.
            await run_import_job(db, job)
            aziende_dopo = await db.lead_companies.count_documents({"organization_id": org})
            assert aziende_prima == aziende_dopo == 1
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_duplicati_esatti_rilevati_e_review_creata():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            job = _job(org, columns=["Ragione Sociale", "Dominio"],
                      rows=[["Acme Srl", "acme.it"], ["Acme Servizi", "acme.it"]],
                      mapping={"Ragione Sociale": "ragione_sociale", "Dominio": "dominio"})
            await db.lead_import_jobs.insert_one(job)
            await run_import_job(db, job)

            aggiornato = await db.lead_import_jobs.find_one({"id": job["id"]}, {"_id": 0})
            assert aggiornato["status"] == "REVIEW_REQUIRED"
            assert aggiornato["counts"]["duplicates_exact"] == 1

            review = await db.lead_dedup_reviews.find_one({"organization_id": org}, {"_id": 0})
            assert review["match_type"] == "ESATTO"
            assert review["status"] == "PENDING"
            assert len(review["record_ids"]) == 2
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_apply_merge_decision_merge_unisce_record():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            job = _job(org, columns=["Ragione Sociale", "Dominio", "Email"],
                      rows=[["Acme Srl", "acme.it", ""], ["Acme Srl", "acme.it", "info@acme.it"]],
                      mapping={"Ragione Sociale": "ragione_sociale", "Dominio": "dominio", "Email": "email"})
            await db.lead_import_jobs.insert_one(job)
            await run_import_job(db, job)
            review = await db.lead_dedup_reviews.find_one({"organization_id": org}, {"_id": 0})

            esito = await apply_merge_decision(db, review, action="MERGE", actor="user-test")
            assert esito["status"] == "MERGED"

            review_aggiornata = await db.lead_dedup_reviews.find_one({"id": review["id"]}, {"_id": 0})
            assert review_aggiornata["status"] == "MERGED"

            primario = await db.lead_companies.find_one({"id": review["record_ids"][0]}, {"_id": 0})
            assert primario["email"]["value"] == "info@acme.it"  # adottato dal secondario
            secondario = await db.lead_companies.find_one({"id": review["record_ids"][1]}, {"_id": 0})
            assert secondario["qualification_status"] == "MERGED_INTO_ALTRO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_apply_merge_decision_keep_separate_non_modifica_record():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            job = _job(org, columns=["Ragione Sociale", "Dominio"],
                      rows=[["Acme Srl", "acme.it"], ["Acme Bis", "acme.it"]],
                      mapping={"Ragione Sociale": "ragione_sociale", "Dominio": "dominio"})
            await db.lead_import_jobs.insert_one(job)
            await run_import_job(db, job)
            review = await db.lead_dedup_reviews.find_one({"organization_id": org}, {"_id": 0})

            prima = {rid: await db.lead_companies.find_one({"id": rid}, {"_id": 0}) for rid in review["record_ids"]}

            esito = await apply_merge_decision(db, review, action="KEEP_SEPARATE", actor="user-test")
            assert esito["status"] == "KEPT_SEPARATE"

            # KEEP_SEPARATE non deve alterare NESSUNO dei due record, a
            # prescindere da quale dei due id sia in posizione [0]/[1]
            # nella review (l'ordine e' l'ordinamento lessicografico degli
            # id, non l'ordine di importazione delle righe del CSV).
            for rid, originale in prima.items():
                dopo = await db.lead_companies.find_one({"id": rid}, {"_id": 0})
                assert dopo["ragione_sociale"]["value"] == originale["ragione_sociale"]["value"]
                assert dopo.get("qualification_status") != "MERGED_INTO_ALTRO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_icp_settore_escluso_applicato_durante_import():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            campaign_id = new_id("leadcamp")
            await db.lead_campaigns.insert_one({
                "id": campaign_id, "organization_id": org, "name": "Test",
                "icp": {"settori_esclusi": ["gioco d'azzardo"]}, "exclude_existing_customers": True,
                "status": "BOZZA", "created_at": now_iso(), "updated_at": now_iso(),
            })
            job = _job(org, columns=["Ragione Sociale", "Settore"], rows=[["Casino Spa", "gioco d'azzardo"]],
                      mapping={"Ragione Sociale": "ragione_sociale", "Settore": "settore"}, campaign_id=campaign_id)
            await db.lead_import_jobs.insert_one(job)
            await run_import_job(db, job)

            azienda = await db.lead_companies.find_one({"organization_id": org}, {"_id": 0})
            assert azienda["qualification_status"] == "EXCLUDED"
            assert "settore_escluso" in azienda["rules_applied"]
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())
