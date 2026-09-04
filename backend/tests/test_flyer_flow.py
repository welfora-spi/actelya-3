"""Flusso reale (Mongo locale, MAI rete reale) del progetto flyer: stesso
pattern collaudato di domains/reel.py (Fact Ledger, generate testo/immagine
con conferma esplicita, validazione semantica). Gateway sempre mockato."""
import asyncio
import uuid

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME
from app.domains import flyer
from app.models import base_record
from app.integrations.requesty_gateway import RisultatoGenerazioneRequesty, RisultatoImmagineRequesty


def run(coro):
    return asyncio.run(coro)


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client[DB_NAME]


def _admin(org_id):
    return {"id": "user-flyer-admin", "email": "admin-flyer@test.local", "role": "ADMIN", "organization_id": org_id}


async def _seed_org(fresh_db, org_id):
    org = base_record(org_id, "system")
    org.update({"id": org_id, "ragione_sociale": "Acme S.r.l.", "nome_commerciale": "Acme", "settore": "software B2B"})
    await fresh_db.organizations.insert_one(org)


async def _seed_ready(fresh_db, org_id):
    await fresh_db.settings.update_one({"id": org_id}, {"$set": {"id": org_id, "ai_real_mode": True}}, upsert=True)
    await fresh_db.budgets.update_one({"id": org_id}, {"$set": {"id": org_id, "general_limit": 5.0}}, upsert=True)
    conn = base_record(org_id, "system")
    conn.update({"id": f"aiconn-{uuid.uuid4().hex[:8]}", "name": "Requesty", "provider_type": "requesty",
                "effective_model": "anthropic/claude-sonnet-4-5", "timeout": 60, "max_tokens": 1200,
                "active": True, "priority": 1, "verified": True, "api_key_encrypted": None, "api_key_masked": ""})
    await fresh_db.ai_connections.insert_one(conn)


async def _scenario(fn):
    client, fresh_db = _db()
    org_id = f"org-test-flyer-{uuid.uuid4().hex[:8]}"
    import app.domains.flyer as flyer_mod
    import app.audit as audit_mod
    old_db, old_audit_db = flyer_mod.db, audit_mod.db
    flyer_mod.db = fresh_db
    audit_mod.db = fresh_db
    try:
        return await fn(fresh_db, org_id)
    finally:
        flyer_mod.db = old_db
        audit_mod.db = old_audit_db
        for coll in ("organizations", "settings", "budgets", "ai_connections", "flyer_projects", "audit_logs", "executions"):
            await fresh_db[coll].delete_many({"organization_id": org_id} if coll != "organizations" else {"id": org_id})
        client.close()


VALID_FLYER = """{
  "formato": "9:16 story", "cta": "Scopri di più",
  "headline": "Acme: soluzioni software per il tuo team",
  "prompt_immagine": "Vertical 9:16 promotional flyer, clean modern corporate style, soft blue palette.",
  "subheadline": "Semplifica il lavoro quotidiano del tuo team",
  "body_text": "Acme aiuta i team a lavorare meglio ogni giorno, con strumenti pensati per il settore software.",
  "hashtags": ["#Acme", "#software"]
}"""


def test_create_project_grounded_su_fact_ledger():
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        p = await flyer.create_project(flyer.NewFlyerBody(brief="promo autunno"), _admin(org_id))
        assert p["status"] == "BOZZA"
        assert p["fact_snapshot"]["ragione_sociale"] == "Acme S.r.l."

    run(_scenario(scenario))


def test_generate_testo_ok_poi_immagine_ok(monkeypatch):
    monkeypatch.setattr(flyer.requesty_gateway, "genera_json", lambda **kw: RisultatoGenerazioneRequesty(
        testo=VALID_FLYER, modello_effettivo="anthropic/claude-sonnet-4-5", latenza_ms=200,
        input_tokens=300, output_tokens=150, troncata=False))

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_ready(fresh_db, org_id)
        p = await flyer.create_project(flyer.NewFlyerBody(brief="promo autunno"), _admin(org_id))

        result = await flyer.generate(p["id"], flyer.ConfirmBody(confirm=True), _admin(org_id))
        assert result["status"] == "PROGETTO_PRONTO"
        assert result["progetto_pronto"] is True
        assert result["image_pronta"] is False
        assert result["semantic_check"]["status"] == "OK"

        monkeypatch.setattr(flyer.requesty_gateway, "genera_immagine", lambda **kw: RisultatoImmagineRequesty(
            url="https://cdn.requesty.example/flyer123.png", b64_json=None, mime_type="image/png",
            modello_effettivo="azure/openai/gpt-image-1", latenza_ms=900, input_tokens=50, output_tokens=1500))
        img_result = await flyer.image_generate(p["id"], flyer.ConfirmBody(confirm=True), _admin(org_id))
        assert img_result["image_status"] == "IMMAGINE_PRONTA"
        assert img_result["image_pronta"] is True
        assert img_result["image_url"] == "https://cdn.requesty.example/flyer123.png"

    run(_scenario(scenario))


def test_image_generate_bloccata_senza_semantica_ok(monkeypatch):
    monkeypatch.setattr(flyer.requesty_gateway, "genera_json", lambda **kw: RisultatoGenerazioneRequesty(
        testo=VALID_FLYER.replace("Semplifica il lavoro quotidiano del tuo team", "Offerta speciale, sconto del 30% solo oggi"),
        modello_effettivo="m", latenza_ms=100, input_tokens=100, output_tokens=100, troncata=False))

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_ready(fresh_db, org_id)
        p = await flyer.create_project(flyer.NewFlyerBody(), _admin(org_id))
        result = await flyer.generate(p["id"], flyer.ConfirmBody(confirm=True), _admin(org_id))
        assert result["semantic_check"]["status"] == "CONTESTATO"  # "sconto" non riconducibile al Fact Ledger/brief

        import pytest
        with pytest.raises(Exception) as ei:
            await flyer.image_generate(p["id"], flyer.ConfirmBody(confirm=True), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 409

    run(_scenario(scenario))
