"""Content Creator — test di integrazione della pipeline reale (MongoDB
locale): decisione, generazione (Requesty mockato, MAI una chiamata di rete),
validazione strutturale+semantica, approvazione, versionamento, esito
incerto, collegamento asset multimediale, recovery. log_audit() e' sempre
intercettato (scrive nel db condiviso dell'app, non in quello passato dal
chiamante — stesso accorgimento di test_tool_gateway.py)."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.domains.content_creator import pipeline as CC
from app.integrations.requesty_gateway import RequestyErroreSanificato, RisultatoGenerazioneRequesty
from app.models import base_record, new_id, now_iso


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, org):
    for c in ("organizations", "facts", "settings", "ai_connections", "content_items",
              "content_item_versions", "reel_projects", "flyer_projects"):
        await db[c].delete_many({"organization_id": org} if c != "organizations" else {"id": org})


async def _no_audit(**kwargs):
    return {"id": "audit-spia", **kwargs}


async def _seed_org(db, org_id):
    org = base_record(org_id, "system")
    org.update({"id": org_id, "ragione_sociale": "Acme S.r.l.", "nome_commerciale": "Acme",
               "settore": "software B2B", "sito_web": "https://acme.example"})
    await db.organizations.insert_one(org)


async def _seed_ready(db, org_id, *, model="anthropic/claude-sonnet-4-5"):
    await db.settings.update_one({"id": org_id}, {"$set": {"id": org_id, "ai_real_mode": True}}, upsert=True)
    conn = base_record(org_id, "system")
    conn.update({"id": f"aiconn-{uuid.uuid4().hex[:8]}", "name": "Requesty", "provider_type": "requesty",
                "effective_model": model, "timeout": 60, "max_tokens": 900, "verified": True, "active": True})
    await db.ai_connections.insert_one(conn)


def _fake_result(content_json: str, troncata=False):
    return RisultatoGenerazioneRequesty(
        testo=content_json, modello_effettivo="anthropic/claude-sonnet-4-5",
        latenza_ms=120, input_tokens=200, output_tokens=180, troncata=troncata,
    )


VALID_POST = (
    '{"titolo": "", "corpo": "Scopri come Acme risolve il tuo problema quotidiano in pochi minuti ogni giorno.", '
    '"cta": "Scopri di più", "hashtags": ["#acme"], '
    '"varianti": ["Una variante alternativa abbastanza lunga del corpo del post.", '
    '"Una seconda variante alternativa altrettanto lunga e sostanziale."]}'
)
INVALID_POST = '{"titolo": "", "corpo": "", "cta": "", "hashtags": [], "varianti": []}'


def test_create_content_item_decide_e_persiste_motivazione(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            risultato = await CC.create_content_item(
                db, org_id=org, actor="user-test", objective="Aumentare il traffico al blog",
                channel="blog", funnel_stage="TOFU", content_type=None, campaign_id=None,
                tone_override=None, constraints="", brief="",
            )
            assert risultato["content_types_decisi"] == ["articolo_blog", "contenuto_seo"]
            assert len(risultato["items"]) == 2
            for item in risultato["items"]:
                assert item["status"] == "BOZZA"
                assert item["motivazione_tipo"]
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_generate_bloccato_se_ai_non_reale(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _seed_org(db, org)
            risultato = await CC.create_content_item(
                db, org_id=org, actor="user-test", objective="Post per Instagram", channel="instagram",
                funnel_stage="MOFU", content_type=None, campaign_id=None, tone_override=None,
                constraints="", brief="",
            )
            item = risultato["items"][0]
            with pytest.raises(CC.ContentCreatorError) as exc:
                await CC.generate_content_item(db, item, actor="user-test")
            assert exc.value.code == "AI_NON_REALE"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_generate_bloccato_se_connessione_non_verificata(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _seed_org(db, org)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            risultato = await CC.create_content_item(
                db, org_id=org, actor="user-test", objective="Post per Instagram", channel="instagram",
                funnel_stage="MOFU", content_type=None, campaign_id=None, tone_override=None,
                constraints="", brief="",
            )
            item = risultato["items"][0]
            with pytest.raises(CC.ContentCreatorError) as exc:
                await CC.generate_content_item(db, item, actor="user-test")
            assert exc.value.code == "CONNESSIONE_NON_VERIFICATA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_generate_successo_porta_in_attesa_approvazione(monkeypatch):
    monkeypatch.setattr("app.tools.gateway.log_audit", _no_audit)
    monkeypatch.setattr(CC.requesty_gateway, "genera_json", lambda **kw: _fake_result(VALID_POST))

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _seed_org(db, org)
            await _seed_ready(db, org)
            risultato = await CC.create_content_item(
                db, org_id=org, actor="user-test", objective="Post per Instagram", channel="instagram",
                funnel_stage="MOFU", content_type=None, campaign_id=None, tone_override=None,
                constraints="", brief="",
            )
            item = risultato["items"][0]
            aggiornato = await CC.generate_content_item(db, item, actor="user-test")
            assert aggiornato["status"] == "IN_ATTESA_APPROVAZIONE"
            assert aggiornato["content"]["corpo"]
            assert aggiornato["semantic_check"]["status"] in ("OK", "CONTESTATO")
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_generate_contenuto_non_valido_blocca(monkeypatch):
    monkeypatch.setattr("app.tools.gateway.log_audit", _no_audit)
    monkeypatch.setattr(CC.requesty_gateway, "genera_json", lambda **kw: _fake_result(INVALID_POST))

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _seed_org(db, org)
            await _seed_ready(db, org)
            risultato = await CC.create_content_item(
                db, org_id=org, actor="user-test", objective="Post per Instagram", channel="instagram",
                funnel_stage="MOFU", content_type=None, campaign_id=None, tone_override=None,
                constraints="", brief="",
            )
            item = risultato["items"][0]
            aggiornato = await CC.generate_content_item(db, item, actor="user-test")
            assert aggiornato["status"] == "BLOCCATO"
            assert aggiornato["generazione"]["errori_validazione"]
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_generate_risposta_troncata_blocca(monkeypatch):
    monkeypatch.setattr("app.tools.gateway.log_audit", _no_audit)
    monkeypatch.setattr(CC.requesty_gateway, "genera_json", lambda **kw: _fake_result(VALID_POST, troncata=True))

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _seed_org(db, org)
            await _seed_ready(db, org)
            risultato = await CC.create_content_item(
                db, org_id=org, actor="user-test", objective="Post", channel="instagram", funnel_stage="MOFU",
                content_type=None, campaign_id=None, tone_override=None, constraints="", brief="",
            )
            item = risultato["items"][0]
            aggiornato = await CC.generate_content_item(db, item, actor="user-test")
            assert aggiornato["status"] == "BLOCCATO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_generate_esito_incerto_poi_risolvibile(monkeypatch):
    monkeypatch.setattr("app.tools.gateway.log_audit", _no_audit)

    def _boom(**kw):
        raise RequestyErroreSanificato("esito_incerto", "Richiesta inviata ma nessuna risposta entro il timeout.")

    monkeypatch.setattr(CC.requesty_gateway, "genera_json", _boom)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _seed_org(db, org)
            await _seed_ready(db, org)
            risultato = await CC.create_content_item(
                db, org_id=org, actor="user-test", objective="Post", channel="instagram", funnel_stage="MOFU",
                content_type=None, campaign_id=None, tone_override=None, constraints="", brief="",
            )
            item = risultato["items"][0]
            with pytest.raises(CC.ContentCreatorError) as exc:
                await CC.generate_content_item(db, item, actor="user-test")
            assert exc.value.code == "esito_incerto"
            incerto = await db.content_items.find_one({"id": item["id"]}, {"_id": 0})
            assert incerto["status"] == "ESITO_INCERTO"

            risolto = await CC.resolve_uncertain(db, incerto, actor="user-test")
            assert risolto["status"] == "BOZZA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_approve_tipo_non_dipendente_da_asset_diventa_approvato(monkeypatch):
    monkeypatch.setattr("app.tools.gateway.log_audit", _no_audit)
    monkeypatch.setattr(CC.requesty_gateway, "genera_json", lambda **kw: _fake_result(VALID_POST))

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _seed_org(db, org)
            await _seed_ready(db, org)
            risultato = await CC.create_content_item(
                db, org_id=org, actor="user-test", objective="Post", channel="instagram", funnel_stage="MOFU",
                content_type=None, campaign_id=None, tone_override=None, constraints="", brief="",
            )
            item = risultato["items"][0]
            generato = await CC.generate_content_item(db, item, actor="user-test")
            approvato = await CC.approve_content_item(db, generato, actor="admin-test", approve=True, note="ok")
            assert approvato["status"] == "APPROVATO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_approve_tipo_dipendente_da_asset_va_in_attesa_asset_poi_completa(monkeypatch):
    monkeypatch.setattr("app.tools.gateway.log_audit", _no_audit)
    monkeypatch.setattr(CC.requesty_gateway, "genera_json", lambda **kw: _fake_result(VALID_POST))

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _seed_org(db, org)
            await _seed_ready(db, org)
            risultato = await CC.create_content_item(
                db, org_id=org, actor="user-test", objective="Reel", channel="tiktok", funnel_stage="MOFU",
                content_type="storyboard", campaign_id=None, tone_override=None, constraints="", brief="",
            )
            item = risultato["items"][0]
            generato = await CC.generate_content_item(db, item, actor="user-test")
            approvato = await CC.approve_content_item(db, generato, actor="admin-test", approve=True, note="ok")
            assert approvato["status"] == "IN_ATTESA_ASSET"

            reel_project_id = new_id("reel")
            await db.reel_projects.insert_one({
                "id": reel_project_id, "organization_id": org, "video_status": "NON_RICHIESTO", "video_url": None,
            })
            collegato = await CC.link_media_project(db, approvato, kind="reel", project_id=reel_project_id, actor="user-test")
            assert collegato["status"] == "IN_ATTESA_ASSET"  # il video non e' ancora pronto

            await db.reel_projects.update_one({"id": reel_project_id}, {"$set": {
                "video_status": "VIDEO_PRONTO", "video_url": "https://cdn.example/reel-video.mp4",
            }})
            sincronizzato = await CC.sync_media_status(db, collegato["id"])
            assert sincronizzato["status"] == "COMPLETATO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_request_revision_fotografa_versione_e_torna_in_bozza(monkeypatch):
    monkeypatch.setattr("app.tools.gateway.log_audit", _no_audit)
    monkeypatch.setattr(CC.requesty_gateway, "genera_json", lambda **kw: _fake_result(VALID_POST))

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _seed_org(db, org)
            await _seed_ready(db, org)
            risultato = await CC.create_content_item(
                db, org_id=org, actor="user-test", objective="Post", channel="instagram", funnel_stage="MOFU",
                content_type=None, campaign_id=None, tone_override=None, constraints="", brief="",
            )
            item = risultato["items"][0]
            generato = await CC.generate_content_item(db, item, actor="user-test")
            rivisto = await CC.request_revision(db, generato, actor="user-test", note="Rendi il tono più diretto")
            assert rivisto["status"] == "BOZZA"
            assert rivisto["nota_revisione"] == "Rendi il tono più diretto"

            versioni = await db.content_item_versions.find({"content_item_id": item["id"]}, {"_id": 0}).to_list(10)
            assert len(versioni) == 1
            assert versioni[0]["content"]["corpo"]
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_recover_on_startup_riporta_in_bozza_generazioni_interrotte():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            item = {
                "id": new_id("content"), "organization_id": org, "content_type": "post_social",
                "status": "GENERAZIONE_IN_CORSO", "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.content_items.insert_one(item)
            await CC.recover_on_startup(db)
            aggiornato = await db.content_items.find_one({"id": item["id"]}, {"_id": 0})
            assert aggiornato["status"] == "BOZZA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())
