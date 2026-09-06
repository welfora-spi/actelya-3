"""Analyst/KPI — test di integrazione (MongoDB locale, nessuna rete):
aggregazione di dati REALI già presenti (Lead Generation, Sales, Appointment
Setter, Tool Execution Gateway) in un report con KPI e insight."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.domains.analyst.pipeline import compute_report, insights_for_agent, list_reports
from app.domains.leadgen.pipeline import run_import_job
from app.domains.sales.pipeline import create_opportunity
from app.models import new_id, now_iso


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, org):
    for c in ("lead_import_jobs", "lead_companies", "lead_campaigns", "sales_opportunities",
              "appointment_bookings", "tool_cost_events", "analyst_reports"):
        await db[c].delete_many({"organization_id": org})


def _job(org, *, columns, rows, mapping, campaign_id=None):
    return {
        "id": new_id("leadjob"), "organization_id": org, "created_by": "user-test",
        "campaign_id": campaign_id, "columns": columns, "rows": rows, "mapping": mapping,
        "status": "UPLOADED", "created_at": now_iso(), "updated_at": now_iso(),
    }


async def _lead_pronto_per_sales(db, org):
    campaign_id = new_id("leadcamp")
    await db.lead_campaigns.insert_one({
        "id": campaign_id, "organization_id": org, "name": "Campagna test", "status": "BOZZA",
        "icp": {"settori_inclusi": ["software"], "localita": ["Milano"]},
        "exclude_existing_customers": True, "created_at": now_iso(), "updated_at": now_iso(),
    })
    job = _job(org, columns=["Ragione Sociale", "Email", "Settore", "Città", "Dipendenti", "Sito"],
              rows=[["Acme Srl", "info@acme.it", "software", "Milano", "50", "https://acme.it"]],
              mapping={"Ragione Sociale": "ragione_sociale", "Email": "email", "Settore": "settore",
                      "Città": "citta", "Dipendenti": "dipendenti", "Sito": "sito"},
              campaign_id=campaign_id)
    await db.lead_import_jobs.insert_one(job)
    await run_import_job(db, job)
    return await db.lead_companies.find_one({"organization_id": org}, {"_id": 0})


def test_compute_report_riflette_i_lead_reali_importati():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _lead_pronto_per_sales(db, org)
            report = await compute_report(db, org_id=org, time_range_days=30, actor="user-test")
            assert report["kpis"]["conversion_rate"]["value"] == 100.0  # unico lead, QUALIFIED
            assert report["kpis"]["lead_velocity"]["missing_data"] is False
            assert report["kpis"]["roas"]["reliability"] == "NON_DISPONIBILE"  # mai inventato
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_compute_report_senza_alcun_dato_dichiara_tutto_non_disponibile():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            report = await compute_report(db, org_id=org, time_range_days=30, actor="user-test")
            assert report["kpis"]["conversion_rate"]["missing_data"] is True
            assert report["kpis"]["close_rate"]["missing_data"] is True
            assert len(report["insights"]) == 1
            assert "insufficienti" in report["insights"][0]["titolo"].lower()
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_compute_report_include_costo_reale_degli_strumenti():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _lead_pronto_per_sales(db, org)
            await db.tool_cost_events.insert_one({
                "id": new_id("costevt"), "organization_id": org, "tool_id": "apollo_prospect",
                "agent_id": "lead-gen-specialist", "amount": 2.5, "currency": "USD",
                "day": now_iso()[:10], "created_at": now_iso(),
            })
            report = await compute_report(db, org_id=org, time_range_days=30, actor="user-test")
            assert report["kpis"]["cost_per_lead"]["value"] == 2.5  # 2.5 / 1 lead
            assert report["kpis"]["cost_per_lead"]["missing_data"] is False
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_compute_report_persiste_e_list_reports_lo_restituisce():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await compute_report(db, org_id=org, time_range_days=30, actor="user-test")
            reports = await list_reports(db, org_id=org)
            assert len(reports) == 1
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_insights_for_agent_filtra_per_target():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await compute_report(db, org_id=org, time_range_days=30, actor="user-test")
            insights_ceo = await insights_for_agent(db, org_id=org, agent_id="coordinatore-actelya")
            insights_sales = await insights_for_agent(db, org_id=org, agent_id="sales-agent")
            assert len(insights_ceo) >= 1  # fallback "dati insufficienti" indirizzato al CEO
            assert all(i["target_agent"] == "coordinatore-actelya" for i in insights_ceo)
            assert insights_sales == []  # nessun insight per Sales in assenza di dati
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_compute_report_conta_opportunita_sales_reali():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            lead = await _lead_pronto_per_sales(db, org)
            await create_opportunity(db, org_id=org, lead_id=lead["id"], lead_type="aziende", actor="user-test")
            report = await compute_report(db, org_id=org, time_range_days=30, actor="user-test")
            assert report["kpis"]["appointment_rate"]["missing_data"] is False
            assert report["kpis"]["close_rate"]["missing_data"] is True  # nessuna chiusura ancora
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())
