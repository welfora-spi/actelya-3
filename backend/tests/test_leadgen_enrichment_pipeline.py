"""Lead Generation — test di integrazione (MongoDB locale, nessuna rete) del
ciclo di arricchimento per-lead: richiesta esplicita con capability astratte,
applicazione del risultato (da un adapter di TEST — nessun provider reale
oggi), ricalcolo di scoring/qualificazione/prossima azione."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.domains.leadgen.pipeline import apply_enrichment_result_for_lead, request_enrichment, run_import_job
from app.models import new_id, now_iso


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, org):
    for c in ("lead_import_jobs", "lead_companies", "lead_persons", "lead_campaigns", "lead_enrichment_requests"):
        await db[c].delete_many({"organization_id": org})


def _job(org, *, columns, rows, mapping, campaign_id=None):
    return {
        "id": new_id("leadjob"), "organization_id": org, "created_by": "user-test",
        "campaign_id": campaign_id, "columns": columns, "rows": rows, "mapping": mapping,
        "status": "UPLOADED", "created_at": now_iso(), "updated_at": now_iso(),
    }


async def _importa_azienda_senza_contatto(db, org, *, settore="software", citta="Milano", con_icp_qualificante=False):
    campaign_id = None
    if con_icp_qualificante:
        campaign_id = new_id("leadcamp")
        await db.lead_campaigns.insert_one({
            "id": campaign_id, "organization_id": org, "name": "Campagna test", "status": "BOZZA",
            "icp": {"settori_inclusi": [settore], "localita": [citta]},
            "exclude_existing_customers": True, "created_at": now_iso(), "updated_at": now_iso(),
        })
    job = _job(org, columns=["Ragione Sociale", "Settore", "Città", "Dipendenti", "Sito"],
              rows=[["Acme Srl", settore, citta, "50", "https://acme.it"]],
              mapping={"Ragione Sociale": "ragione_sociale", "Settore": "settore", "Città": "citta",
                      "Dipendenti": "dipendenti", "Sito": "sito"},
              campaign_id=campaign_id)
    await db.lead_import_jobs.insert_one(job)
    await run_import_job(db, job)
    return await db.lead_companies.find_one({"organization_id": org}, {"_id": 0})


def test_request_enrichment_richiede_capability_coerenti_con_next_action():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _importa_azienda_senza_contatto(db, org)
            assert lead["next_action"]["azione"] in ("CONTINUA_ENRICHMENT",)
            richiesta = await request_enrichment(db, org_id=org, lead_type="aziende", lead_id=lead["id"], actor="user-test")
            assert richiesta["status"] == "IN_ATTESA"
            assert set(richiesta["capability_richieste"]) == set(lead["next_action"]["capability_richieste"])
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_request_enrichment_rifiutata_se_nessuna_capability_necessaria():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _importa_azienda_senza_contatto(db, org, con_icp_qualificante=True)
            # Applico subito un contatto: nessuna capability rimane necessaria.
            richiesta = await request_enrichment(db, org_id=org, lead_type="aziende", lead_id=lead["id"], actor="user-test")
            esito = await apply_enrichment_result_for_lead(
                db, richiesta, result_fields={"email": "info@acme.it", "telefono": "0212345678"},
                source="adapter-di-test", actor="user-test",
            )
            aggiornato = esito["lead"]
            assert aggiornato["next_action"]["azione"] in ("PRONTO_PER_SALES",)

            with pytest.raises(ValueError):
                await request_enrichment(db, org_id=org, lead_type="aziende", lead_id=lead["id"], actor="user-test")
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_apply_enrichment_result_aggiorna_lead_e_marca_richiesta_completata():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _importa_azienda_senza_contatto(db, org)
            richiesta = await request_enrichment(db, org_id=org, lead_type="aziende", lead_id=lead["id"], actor="user-test")

            esito = await apply_enrichment_result_for_lead(
                db, richiesta, result_fields={"email": "info@acme.it"}, source="adapter-di-test", actor="user-test",
            )
            assert esito["lead"]["email"]["value"] == "info@acme.it"
            assert esito["request"]["status"] == "COMPLETATA"
            assert esito["request"]["result_source"] == "adapter-di-test"
            assert esito["conflitti"] == []
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_apply_enrichment_result_su_richiesta_gia_evasa_rifiutato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _importa_azienda_senza_contatto(db, org)
            richiesta = await request_enrichment(db, org_id=org, lead_type="aziende", lead_id=lead["id"], actor="user-test")
            await apply_enrichment_result_for_lead(
                db, richiesta, result_fields={"email": "info@acme.it"}, source="adapter-di-test", actor="user-test")
            richiesta_evasa = await db.lead_enrichment_requests.find_one({"id": richiesta["id"]}, {"_id": 0})

            with pytest.raises(ValueError):
                await apply_enrichment_result_for_lead(
                    db, richiesta_evasa, result_fields={"email": "altra@acme.it"}, source="adapter-di-test", actor="user-test")
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_enrichment_rileva_conflitto_con_dato_gia_verificato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _importa_azienda_senza_contatto(db, org)
            await db.lead_companies.update_one({"id": lead["id"]}, {"$set": {
                "email": {"value": "verificata@acme.it", "method": "VERIFICATO"},
            }})
            richiesta = await request_enrichment(db, org_id=org, lead_type="aziende", lead_id=lead["id"], actor="user-test")

            esito = await apply_enrichment_result_for_lead(
                db, richiesta, result_fields={"email": "trovata-altrove@acme.it"}, source="adapter-di-test", actor="user-test")
            assert esito["lead"]["email"]["value"] == "verificata@acme.it"  # mai declassato
            assert len(esito["conflitti"]) == 1
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())
