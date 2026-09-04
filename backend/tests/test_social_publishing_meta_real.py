"""Social Media Manager — dispatch REALE verso Meta (DECISIONE UFFICIALE
"100% REALE"): l'intera catena PublishingService -> ConnectorGateway ->
adapter Meta -> Graph API, con trasporto HTTP SEMPRE mockato (mai una
chiamata di rete reale). Verifica sia il percorso 'tutto configurato'
(pubblicazione reale davvero eseguita) sia che il solo flag globale
REAL_EXTERNAL_ACTIONS=False basti a mantenere tutto in dry-run anche con
una connessione Meta perfettamente configurata (item 20)."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME
from app.models import base_record, now_iso, new_id
from app.security import encrypt_secret
from app.brain import config as brain_config
from app.brain.gateways.connector_gateway import ConnectorGateway
from app.domains import social_publishing as sp
from app.domains import meta_connections


def run(coro):
    return asyncio.run(coro)


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client[DB_NAME]


def _user(org_id, role, tag="a"):
    return {"id": f"user-metareal-{tag}", "email": f"{tag}@test.local", "role": role, "organization_id": org_id}


class _FakeResponse:
    def __init__(self, status_code, json_body, headers=None):
        self.status_code = status_code
        self._json = json_body
        self.headers = headers or {}

    def json(self):
        return self._json


def _patch_requests(monkeypatch, fn):
    import requests
    monkeypatch.setattr(requests, "request", fn)


async def _seed_reel_project_pronto(fresh_db, org_id, *, video_url="https://cdn.runway.example/bakery.mp4"):
    rec = base_record(org_id, "system")
    rec.update({
        "id": new_id("reel"), "brief": "test", "status": "PROGETTO_PRONTO", "progetto_pronto": True,
        "content": {
            "concept": "c", "hook": "h", "sceneggiatura": "s", "storyboard": [], "voice_over_completo": "v",
            "testi_a_schermo": ["t"], "caption": "Le focaccine ti aspettano!", "hashtags": ["#focaccine", "#weekend"],
            "cta": "Vieni a trovarci", "durata_secondi": 12, "formato": "9:16", "prompt_video_generativo": "p",
        },
        "fact_snapshot": {}, "generazione": {}, "progetto_approvato": True,
        "progetto_approvato_da": "admin", "progetto_approvato_at": now_iso(), "nota_revisione": None,
        "semantic_check": {"status": "OK", "affermazioni_contestate": []},
        "video_status": "VIDEO_PRONTO", "video_url": video_url,
        "video_approvato": True, "video_approvato_da": "admin", "video_approvato_at": now_iso(), "video_nota_revisione": None,
    })
    await fresh_db.reel_projects.insert_one(rec)
    return rec


async def _seed_meta_connection_real(fresh_db, org_id, *, channel_status="CONNECTED"):
    conn = base_record(org_id, "system")
    conn.update({
        "id": new_id("metaconn"), "name": "Bakery Meta", "mode": "real",
        "app_id": "app1", "app_secret_encrypted": None,
        "access_token_encrypted": encrypt_secret("real-page-token"), "access_token_masked": "****oken",
        "page_id": "page1", "page_name": "Bakery & Coffee",
        "instagram_business_account_id": "ig1", "instagram_username": "bakerycoffee",
        "graph_api_version": "v21.0", "active": True,
        "facebook_status": channel_status, "instagram_status": channel_status,
        "last_test_at": now_iso(), "last_test_result": "OK_REALE",
    })
    await fresh_db.meta_connections.insert_one(conn)
    return conn


async def _scenario(fn):
    client, fresh_db = _db()
    org_id = f"org-test-metareal-{uuid.uuid4().hex[:8]}"
    import app.audit as audit_mod
    old_sp_db, old_audit_db, old_meta_db = sp.db, audit_mod.db, meta_connections.db
    sp.db = fresh_db
    audit_mod.db = fresh_db
    meta_connections.db = fresh_db
    try:
        return await fn(fresh_db, org_id)
    finally:
        sp.db = old_sp_db
        audit_mod.db = old_audit_db
        meta_connections.db = old_meta_db
        for coll in ("organizations", "reel_projects", "social_publishing_packages", "social_analytics_snapshots",
                    "social_memory_entries", "meta_connections", "audit_logs"):
            await fresh_db[coll].delete_many({"organization_id": org_id})
        client.close()


async def _pronto_per_pubblicare(fresh_db, org_id, *, channel="facebook", video_url="https://cdn.runway.example/bakery.mp4"):
    p = await _seed_reel_project_pronto(fresh_db, org_id, video_url=video_url)
    pkg = await sp.create_package(
        sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p["id"], channel=channel),
        _user(org_id, "OPERATORE"),
    )
    pkg = await sp.approve_package(pkg["id"], _user(org_id, "APPROVATORE", "b"))
    return p, pkg


def test_pubblicazione_reale_facebook_ok(monkeypatch):
    monkeypatch.setattr(brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(brain_config, "CONNECTOR_MODE", "real")
    gw = ConnectorGateway()
    sp.register_meta_adapters(gateway=gw)
    monkeypatch.setattr(sp, "get_connector_gateway", lambda: gw)

    chiamate = []

    def fake(method, url, **kw):
        chiamate.append(url)
        if "/page1/videos" in url:
            assert kw["data"]["file_url"] == "https://cdn.runway.example/bakery.mp4"
            return _FakeResponse(200, {"id": "video123"})
        if url.endswith("/video123"):
            return _FakeResponse(200, {"id": "video123", "permalink_url": "https://facebook.com/bakery/videos/video123"})
        raise AssertionError(f"URL Graph API inatteso: {url}")

    _patch_requests(monkeypatch, fake)

    async def scenario(fresh_db, org_id):
        await _seed_meta_connection_real(fresh_db, org_id)
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id, channel="facebook")
        pkg2 = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        assert pkg2["status"] == "PUBLISHED"
        assert pkg2["dry_run"] is False
        assert pkg2["external_post_id"] == "video123"
        assert pkg2["permalink"] == "https://facebook.com/bakery/videos/video123"

    run(_scenario(scenario))
    assert any("/page1/videos" in u for u in chiamate)


def test_pubblicazione_reale_instagram_container_flow_ok(monkeypatch):
    monkeypatch.setattr(brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(brain_config, "CONNECTOR_MODE", "real")
    gw = ConnectorGateway()
    sp.register_meta_adapters(gateway=gw)
    monkeypatch.setattr(sp, "get_connector_gateway", lambda: gw)

    passi = {"status_calls": 0}

    def fake(method, url, **kw):
        if "/ig1/media" in url and method == "POST" and "media_publish" not in url:
            assert kw["data"]["video_url"] == "https://cdn.runway.example/bakery.mp4"
            assert kw["data"]["media_type"] == "REELS"
            return _FakeResponse(200, {"id": "container1"})
        if url.endswith("/container1") and method == "GET":
            passi["status_calls"] += 1
            return _FakeResponse(200, {"status_code": "FINISHED" if passi["status_calls"] >= 2 else "IN_PROGRESS"})
        if "/ig1/media_publish" in url:
            assert kw["data"]["creation_id"] == "container1"
            return _FakeResponse(200, {"id": "media1"})
        if url.endswith("/media1") and method == "GET":
            return _FakeResponse(200, {"permalink": "https://www.instagram.com/reel/media1/"})
        raise AssertionError(f"URL Graph API inatteso: {method} {url}")

    _patch_requests(monkeypatch, fake)
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)

    async def scenario(fresh_db, org_id):
        await _seed_meta_connection_real(fresh_db, org_id)
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id, channel="instagram")
        pkg2 = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        assert pkg2["status"] == "PUBLISHED"
        assert pkg2["dry_run"] is False
        assert pkg2["external_post_id"] == "media1"
        assert pkg2["permalink"] == "https://www.instagram.com/reel/media1/"

    run(_scenario(scenario))
    assert passi["status_calls"] >= 2  # il polling e' avvenuto davvero (IN_PROGRESS poi FINISHED)


def test_container_mai_pronto_diventa_esito_incerto(monkeypatch):
    monkeypatch.setattr(brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(brain_config, "CONNECTOR_MODE", "real")
    monkeypatch.setattr(sp, "_meta_attendi_container_pronto", lambda *a, **kw:
        __import__("app.integrations.meta.instagram", fromlist=["ContainerStato"]).ContainerStato(
            container_id="container1", status_code="IN_PROGRESS", status=None))
    gw = ConnectorGateway()
    sp.register_meta_adapters(gateway=gw)
    monkeypatch.setattr(sp, "get_connector_gateway", lambda: gw)

    def fake(method, url, **kw):
        if "/ig1/media" in url and "media_publish" not in url:
            return _FakeResponse(200, {"id": "container1"})
        raise AssertionError(f"Non deve pubblicare se il container non e' mai FINISHED: {url}")

    _patch_requests(monkeypatch, fake)

    async def scenario(fresh_db, org_id):
        await _seed_meta_connection_real(fresh_db, org_id)
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id, channel="instagram")
        pkg2 = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        assert pkg2["status"] == "PUBLISH_UNCERTAIN"
        assert pkg2["error_code"] == "esito_incerto"

        # Risoluzione manuale: l'admin verifica su Meta che il post NON esiste -> torna APPROVED.
        risolto = await sp.resolve_uncertain(
            pkg2["id"], sp.ResolveUncertainBody(nota="Verificato su Instagram: nessun post pubblicato."),
            _user(org_id, "ADMIN"),
        )
        assert risolto["status"] == "APPROVED"

    run(_scenario(scenario))


def test_esito_incerto_risolto_come_pubblicato_se_verificato(monkeypatch):
    async def scenario(fresh_db, org_id):
        await _seed_meta_connection_real(fresh_db, org_id)
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id, channel="instagram")
        await sp._set_status(pkg["id"], "PUBLISHING")
        await sp._set_status(pkg["id"], "PUBLISH_UNCERTAIN", extra={"error_code": "esito_incerto", "error_message": "timeout"})

        risolto = await sp.resolve_uncertain(
            pkg["id"], sp.ResolveUncertainBody(nota="Trovato su Instagram.", found_external_post_id="media-trovato-a-mano"),
            _user(org_id, "ADMIN"),
        )
        assert risolto["status"] == "PUBLISHED"
        assert risolto["external_post_id"] == "media-trovato-a-mano"
        assert risolto["dry_run"] is False

    run(_scenario(scenario))


def test_senza_real_external_actions_resta_dry_run_zero_chiamate_http(monkeypatch):
    """item 20: anche con una connessione Meta perfettamente configurata e
    verificata, REAL_EXTERNAL_ACTIONS=False (default) basta da sola a
    impedire QUALUNQUE chiamata HTTP reale — il flag NON viene toccato qui."""
    assert brain_config.REAL_EXTERNAL_ACTIONS is False  # precondizione: default sicuro del processo di test

    gw = ConnectorGateway()
    sp.register_meta_adapters(gateway=gw)
    monkeypatch.setattr(sp, "get_connector_gateway", lambda: gw)

    def fake(method, url, **kw):
        raise AssertionError("Nessuna chiamata HTTP reale deve mai avvenire con REAL_EXTERNAL_ACTIONS=False.")
    _patch_requests(monkeypatch, fake)

    async def scenario(fresh_db, org_id):
        await _seed_meta_connection_real(fresh_db, org_id)
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id, channel="facebook")
        pkg2 = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        assert pkg2["status"] == "PUBLISHED"
        assert pkg2["dry_run"] is True
        assert pkg2["external_post_id"] is None

    run(_scenario(scenario))


def test_metriche_reali_calcolano_engagement_score(monkeypatch):
    monkeypatch.setattr(brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(brain_config, "CONNECTOR_MODE", "real")
    gw = ConnectorGateway()
    sp.register_meta_adapters(gateway=gw)
    monkeypatch.setattr(sp, "get_connector_gateway", lambda: gw)

    def fake(method, url, **kw):
        if "/page1/videos" in url:
            return _FakeResponse(200, {"id": "video123"})
        if url.endswith("/video123") and "insights" not in url:
            return _FakeResponse(200, {"id": "video123", "permalink_url": "https://facebook.com/x"})
        if url.endswith("/video123/insights"):
            return _FakeResponse(200, {"data": [
                {"name": "post_impressions", "values": [{"value": 1000}]},
                {"name": "post_reactions_like_total", "values": [{"value": 100}]},
            ]})
        raise AssertionError(f"URL inatteso: {url}")
    _patch_requests(monkeypatch, fake)

    async def scenario(fresh_db, org_id):
        await _seed_meta_connection_real(fresh_db, org_id)
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id, channel="facebook")
        pkg2 = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        snap = await sp.refresh_metrics(pkg2["id"], _user(org_id, "ADMIN"))
        assert snap["data_available"] is True
        assert snap["impressions"] == 1000
        assert snap["likes"] == 100
        assert snap["engagement_score"] == pytest.approx(10.0)  # 100 like / 1000 impressions * 100

    run(_scenario(scenario))
