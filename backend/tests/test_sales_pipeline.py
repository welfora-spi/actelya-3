"""Sales Agent — test di integrazione della pipeline reale (MongoDB locale,
nessuna rete): handoff da un lead PRONTO_PER_SALES, delega del messaggio a
Content Creator (mai una generazione reale qui — solo creazione del
content_item BOZZA), gestione delle risposte, collegamento con Appointment
Setter (in lettura), avanzamento manuale degli stage tardivi."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.domains.leadgen.pipeline import run_import_job
from app.domains.sales.pipeline import (
    SalesError,
    advance_stage,
    create_opportunity,
    link_appointment,
    mark_contacted,
    record_response,
    request_message,
    resolve_escalation,
    sync_appointment_status,
)
from app.models import new_id, now_iso


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, org):
    for c in ("lead_import_jobs", "lead_companies", "lead_campaigns", "sales_opportunities",
              "content_items", "appointment_proposals", "appointment_bookings"):
        await db[c].delete_many({"organization_id": org})


def _job(org, *, columns, rows, mapping, campaign_id=None):
    return {
        "id": new_id("leadjob"), "organization_id": org, "created_by": "user-test",
        "campaign_id": campaign_id, "columns": columns, "rows": rows, "mapping": mapping,
        "status": "UPLOADED", "created_at": now_iso(), "updated_at": now_iso(),
    }


async def _lead_pronto_per_sales(db, org, *, settore="software", citta="Milano"):
    campaign_id = new_id("leadcamp")
    await db.lead_campaigns.insert_one({
        "id": campaign_id, "organization_id": org, "name": "Campagna test", "status": "BOZZA",
        "icp": {"settori_inclusi": [settore], "localita": [citta]},
        "exclude_existing_customers": True, "created_at": now_iso(), "updated_at": now_iso(),
    })
    job = _job(org, columns=["Ragione Sociale", "Email", "Settore", "Città", "Dipendenti", "Sito"],
              rows=[["Acme Srl", "info@acme.it", settore, citta, "50", "https://acme.it"]],
              mapping={"Ragione Sociale": "ragione_sociale", "Email": "email", "Settore": "settore",
                      "Città": "citta", "Dipendenti": "dipendenti", "Sito": "sito"},
              campaign_id=campaign_id)
    await db.lead_import_jobs.insert_one(job)
    await run_import_job(db, job)
    return await db.lead_companies.find_one({"organization_id": org}, {"_id": 0})


async def _lead_incompleto(db, org):
    job = _job(org, columns=["Ragione Sociale"], rows=[["Acme Incompleta Srl"]],
              mapping={"Ragione Sociale": "ragione_sociale"})
    await db.lead_import_jobs.insert_one(job)
    await run_import_job(db, job)
    return await db.lead_companies.find_one({"organization_id": org}, {"_id": 0})


def test_create_opportunity_da_lead_pronto_per_sales():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _lead_pronto_per_sales(db, org)
            assert lead["next_action"]["azione"] == "PRONTO_PER_SALES"
            opp = await create_opportunity(db, org_id=org, lead_id=lead["id"], lead_type="aziende", actor="user-test")
            assert opp["stage"] == "QUALIFICATO"
            assert opp["analysis"]["canale"] == "email"
            assert opp["next_best_action"] == "CONTATTA_ORA"

            # Idempotente: una seconda chiamata ritorna la STESSA opportunità.
            opp2 = await create_opportunity(db, org_id=org, lead_id=lead["id"], lead_type="aziende", actor="user-test")
            assert opp2["id"] == opp["id"]
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_create_opportunity_lead_non_pronto_rifiutato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _lead_incompleto(db, org)
            assert lead["next_action"]["azione"] != "PRONTO_PER_SALES"
            with pytest.raises(SalesError) as exc:
                await create_opportunity(db, org_id=org, lead_id=lead["id"], lead_type="aziende", actor="user-test")
            assert exc.value.code == "LEAD_NON_PRONTO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_request_message_delega_a_content_creator_senza_generare():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _lead_pronto_per_sales(db, org)
            opp = await create_opportunity(db, org_id=org, lead_id=lead["id"], lead_type="aziende", actor="user-test")

            aggiornata = await request_message(db, opp, actor="user-test")
            assert aggiornata["message_content_item_id"]

            content_item = await db.content_items.find_one({"id": aggiornata["message_content_item_id"]}, {"_id": 0})
            assert content_item["content_type"] == "comunicazione_commerciale"
            assert content_item["status"] == "BOZZA"  # mai generato automaticamente da Sales
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_mark_contacted_richiede_messaggio_approvato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _lead_pronto_per_sales(db, org)
            opp = await create_opportunity(db, org_id=org, lead_id=lead["id"], lead_type="aziende", actor="user-test")
            opp = await request_message(db, opp, actor="user-test")

            with pytest.raises(SalesError) as exc:
                await mark_contacted(db, opp, actor="user-test")
            assert exc.value.code == "MESSAGGIO_NON_PRONTO"

            await db.content_items.update_one({"id": opp["message_content_item_id"]}, {"$set": {"status": "APPROVATO"}})
            contattata = await mark_contacted(db, opp, actor="user-test")
            assert contattata["stage"] == "CONTATTATO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


async def _opportunita_contattata(db, org):
    lead = await _lead_pronto_per_sales(db, org)
    opp = await create_opportunity(db, org_id=org, lead_id=lead["id"], lead_type="aziende", actor="user-test")
    opp = await request_message(db, opp, actor="user-test")
    await db.content_items.update_one({"id": opp["message_content_item_id"]}, {"$set": {"status": "APPROVATO"}})
    return await mark_contacted(db, opp, actor="user-test")


def test_record_response_positiva_porta_a_richiesta_appuntamento_dopo_relazione():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            opp = await _opportunita_contattata(db, org)
            in_relazione = await record_response(db, opp, response_type="POSITIVA", note="Interessato", actor="user-test")
            assert in_relazione["stage"] == "IN_RELAZIONE"
            richiesta = await record_response(db, in_relazione, response_type="RICHIESTA_APPUNTAMENTO", note="", actor="user-test")
            assert richiesta["stage"] == "RICHIESTA_APPUNTAMENTO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_record_response_negativa_chiude_a_perso():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            opp = await _opportunita_contattata(db, org)
            persa = await record_response(db, opp, response_type="NEGATIVA", note="", actor="user-test")
            assert persa["stage"] == "PERSO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_link_appointment_e_sync_prenotazione_confermata_avanza_a_appuntamento_fissato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            opp = await _opportunita_contattata(db, org)
            opp = await record_response(db, opp, response_type="RICHIESTA_APPUNTAMENTO", note="", actor="user-test")
            assert opp["stage"] == "RICHIESTA_APPUNTAMENTO"

            proposal_id = new_id("apptprop")
            await db.appointment_proposals.insert_one({"id": proposal_id, "organization_id": org, "status": "APPROVATA"})
            await db.appointment_bookings.insert_one({
                "id": new_id("appt"), "organization_id": org, "proposal_id": proposal_id,
                "status": "CONFERMATA", "created_at": now_iso(),
            })

            collegata = await link_appointment(db, opp, proposal_id=proposal_id, actor="user-test")
            assert collegata["stage"] == "APPUNTAMENTO_FISSATO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_sync_appointment_cancellata_riporta_a_follow_up():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            opp = await _opportunita_contattata(db, org)
            opp = await record_response(db, opp, response_type="RICHIESTA_APPUNTAMENTO", note="", actor="user-test")

            proposal_id = new_id("apptprop")
            await db.appointment_proposals.insert_one({"id": proposal_id, "organization_id": org, "status": "APPROVATA"})
            await db.appointment_bookings.insert_one({
                "id": new_id("appt"), "organization_id": org, "proposal_id": proposal_id,
                "status": "CANCELLATA", "created_at": now_iso(),
            })

            collegata = await link_appointment(db, opp, proposal_id=proposal_id, actor="user-test")
            assert collegata["stage"] == "FOLLOW_UP"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_advance_stage_sequenziale_solo_di_uno_alla_volta():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            opp = await _opportunita_contattata(db, org)
            await db.sales_opportunities.update_one({"id": opp["id"]}, {"$set": {"stage": "OPPORTUNITA"}})
            opp = await db.sales_opportunities.find_one({"id": opp["id"]}, {"_id": 0})

            with pytest.raises(SalesError) as exc:
                await advance_stage(db, opp, new_stage="NEGOZIAZIONE", actor="admin-test")
            assert exc.value.code == "TRANSIZIONE_NON_VALIDA"

            avanzata = await advance_stage(db, opp, new_stage="PROPOSTA", actor="admin-test", note="Inviata proposta")
            assert avanzata["stage"] == "PROPOSTA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_advance_stage_a_perso_sempre_ammesso():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            opp = await _opportunita_contattata(db, org)
            await db.sales_opportunities.update_one({"id": opp["id"]}, {"$set": {"stage": "OPPORTUNITA"}})
            opp = await db.sales_opportunities.find_one({"id": opp["id"]}, {"_id": 0})
            persa = await advance_stage(db, opp, new_stage="PERSO", actor="admin-test", note="Cliente ha rinunciato")
            assert persa["stage"] == "PERSO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_advance_stage_da_stato_terminale_rifiutato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            opp = await _opportunita_contattata(db, org)
            await db.sales_opportunities.update_one({"id": opp["id"]}, {"$set": {"stage": "PERSO"}})
            opp = await db.sales_opportunities.find_one({"id": opp["id"]}, {"_id": 0})
            with pytest.raises(SalesError) as exc:
                await advance_stage(db, opp, new_stage="OPPORTUNITA", actor="admin-test")
            assert exc.value.code == "STATO_TERMINALE"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_resolve_escalation_richiede_nota_non_vuota():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _lead_pronto_per_sales(db, org)
            opp = await create_opportunity(db, org_id=org, lead_id=lead["id"], lead_type="aziende", actor="user-test")
            # Forza un'escalation per testare la risoluzione (stage QUALIFICATO,
            # risposta senza regola esplicita -> ESCALATION_UMANA).
            escalata = await record_response(db, opp, response_type="POSITIVA", note="", actor="user-test")
            assert escalata["escalation_richiesta"] is True

            with pytest.raises(SalesError) as exc:
                await resolve_escalation(db, escalata, note="", actor="admin-test")
            assert exc.value.code == "NOTA_OBBLIGATORIA"

            risolta = await resolve_escalation(db, escalata, note="Verificato manualmente", actor="admin-test")
            assert risolta["escalation_richiesta"] is False
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())
