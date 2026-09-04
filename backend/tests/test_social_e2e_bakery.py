"""Social Media Manager — scenario end-to-end completo (item 19/21/27.10,
DECISIONE UFFICIALE "COMPLETAMENTO END-TO-END SOCIAL MEDIA MANAGER").

Utente registrato "Bakery & Coffee" scrive in linguaggio naturale:
    "Fammi un Reel per Bakery & Coffee per promuovere le focaccine questo weekend."

Percorso coperto DAVVERO end-to-end (nessuna chiamata manuale al DB, nessuna
scorciatoia): comprensione linguaggio naturale -> uso del Fact Ledger senza
richiedere di nuovo dati gia' noti -> selezione dinamica Social Media
Manager/Video creator + Compliance -> UN SOLO piano M2 -> generazione reale
testo (Requesty MOCKATO, unico confine esterno) -> hashtag -> validazione
semantica/compliance -> quality gate -> generazione reale video (Runway
MOCKATO) -> approvazione testo E video (distinte) -> memoria persistente
scritta -> pacchetto di pubblicazione -> approvazione pubblicazione (distinta
da quella del contenuto) -> pubblicazione -> audit -> metriche (mai un dato
inventato) -> idempotenza del retry.

DECISIONE UFFICIALE "100% REALE": una seconda versione dello stesso
scenario (test_scenario_bakery_coffee_end_to_end_con_meta_reale) ripete il
percorso con una connessione Meta configurata e REAL_EXTERNAL_ACTIONS
abilitato, dimostrando il dispatch REALE (Graph API sempre mockata a
livello di trasporto HTTP, mai una chiamata di rete vera) fino a un
external_post_id genuinamente restituito dal (finto) provider, metriche
reali mappate e un suggerimento di apprendimento derivato da dati
realmente misurati."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME
from app.models import base_record
from app.brain.planning.agent_selector import select_agents
from app.brain.memory.session import get_session_store
from app.brain.audit.memory_audit import get_audit_log
from app.brain import service as brain_service
from app.domains import reel, social_publishing as sp, social_memory as mem, knowledge, meta_connections
from app.integrations.requesty_gateway import RisultatoGenerazioneRequesty
from app.integrations.runway_gateway import TaskAvviato, StatoTask
from app.brain import config as brain_config
from app.brain.gateways.connector_gateway import ConnectorGateway
from app.security import encrypt_secret
import json


def run(coro):
    return asyncio.run(coro)


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client[DB_NAME]


def _reset_singletons():
    get_session_store().reset()
    get_audit_log().reset()


def _admin(org_id):
    return {"id": "user-e2e-admin", "email": "admin@bakerycoffee.test", "role": "ADMIN", "organization_id": org_id}


def _approvatore(org_id):
    return {"id": "user-e2e-approv", "email": "approvatore@bakerycoffee.test", "role": "APPROVATORE", "organization_id": org_id}


GOAL = "Fammi un Reel per Bakery & Coffee per promuovere le focaccine questo weekend."

REEL_CONTENT = {
    "concept": "Un reel che mostra le focaccine artigianali di Bakery & Coffee appena sfornate, pronte per il weekend.",
    "hook": "Hai gia' deciso cosa fare colazione questo weekend?",
    "sceneggiatura": "Scena 1: forno che si apre. Scena 2: focaccine calde sul bancone. Scena 3: cliente sorridente con il vassoio.",
    "storyboard": [
        {"numero_scena": 1, "descrizione_visiva": "Forno che si apre, vapore e focaccine dorate", "durata_secondi": 4,
         "testo_a_schermo": "Appena sfornate", "voice_over": "Ogni mattina, focaccine fresche."},
        {"numero_scena": 2, "descrizione_visiva": "Bancone con focaccine pronte", "durata_secondi": 4,
         "testo_a_schermo": "Solo questo weekend", "voice_over": "Vieni a provarle questo weekend."},
    ],
    "voice_over_completo": "Ogni mattina, focaccine fresche. Vieni a provarle questo weekend da Bakery & Coffee.",
    "testi_a_schermo": ["Appena sfornate", "Solo questo weekend"],
    "hashtags": ["#focaccine", "#weekend", "#bakerycoffee"],
    "caption": "Le nostre focaccine ti aspettano questo weekend!",
    "cta": "Vieni a trovarci",
    "durata_secondi": 12,
    "formato": "9:16",
    "prompt_video_generativo": "Vertical 9:16 video of fresh focaccine bread coming out of a bakery oven, warm inviting style.",
}


async def _seed_org(fresh_db, org_id):
    org = base_record(org_id, "system")
    org.update({
        "id": org_id, "ragione_sociale": "Bakery & Coffee S.r.l.", "nome_commerciale": "Bakery & Coffee",
        "settore": "panetteria e caffetteria", "sito_web": "https://bakerycoffee.example",
    })
    await fresh_db.organizations.insert_one(org)
    # Fact Ledger reale (item 2/19: "azienda già registrata" — il nome è
    # gia' dichiarato una volta in fase di onboarding/registrazione, MAI
    # richiesto di nuovo). Deliberatamente NON seminiamo qui un fatto
    # 'prodotto': quello di QUESTA richiesta ("le focaccine") deve emergere
    # dal testo libero del messaggio (context.py::_PATTERN_PRODOTTO,
    # corretto in questa fase per gestire un riferimento temporale come
    # "questo weekend" subito dopo il nome del prodotto) — esattamente lo
    # scenario reale: un'azienda non dichiara in anticipo ogni futura offerta.
    await knowledge.write_fact(
        fresh_db, org_id=org_id, user_id="system", field="ragione_sociale",
        value="Bakery & Coffee S.r.l.", source="onboarding", method="DICHIARATO", confidence=0.9,
    )
    await knowledge.write_fact(
        fresh_db, org_id=org_id, user_id="system", field="settore",
        value="panetteria e caffetteria", source="onboarding", method="DICHIARATO", confidence=0.9,
    )


async def _seed_ready(fresh_db, org_id):
    await fresh_db.settings.update_one({"id": org_id}, {"$set": {"id": org_id, "ai_real_mode": True}}, upsert=True)
    await fresh_db.budgets.update_one({"id": org_id}, {"$set": {"id": org_id, "general_limit": 5.0}}, upsert=True)
    conn = base_record(org_id, "system")
    conn.update({"id": f"aiconn-{uuid.uuid4().hex[:8]}", "name": "Requesty", "provider_type": "requesty",
                "effective_model": "anthropic/claude-sonnet-4-5", "timeout": 60, "max_tokens": 1800,
                "active": True, "priority": 1, "verified": True, "api_key_encrypted": None, "api_key_masked": ""})
    await fresh_db.ai_connections.insert_one(conn)
    vconn = base_record(org_id, "system")
    vconn.update({"id": f"vidconn-{uuid.uuid4().hex[:8]}", "name": "Runway", "provider_type": "runway",
                 "effective_model": "gen4.5", "default_ratio": "720:1280", "max_cost_per_generation": 20.0,
                 "timeout": 30, "active": True, "priority": 1, "verified": True,
                 "api_key_encrypted": encrypt_secret("fake-runway-key"), "api_key_masked": "****fake"})
    await fresh_db.video_connections.insert_one(vconn)


async def _scenario(fn):
    client, fresh_db = _db()
    org_id = f"org-test-e2e-{uuid.uuid4().hex[:8]}"
    import app.domains.reel as reel_mod
    import app.audit as audit_mod
    from app.domains import meta_connections
    old_reel_db, old_audit_db, old_sp_db, old_meta_db = reel_mod.db, audit_mod.db, sp.db, meta_connections.db
    reel_mod.db = fresh_db
    audit_mod.db = fresh_db
    sp.db = fresh_db
    meta_connections.db = fresh_db
    _reset_singletons()
    try:
        return await fn(fresh_db, org_id)
    finally:
        reel_mod.db = old_reel_db
        audit_mod.db = old_audit_db
        sp.db = old_sp_db
        meta_connections.db = old_meta_db
        _reset_singletons()
        for coll in ("organizations", "facts", "settings", "budgets", "ai_connections", "video_connections",
                    "reel_projects", "reel_video_jobs", "reel_content_versions", "goals", "plans", "tasks",
                    "audit_logs", "executions", "social_publishing_packages", "social_analytics_snapshots",
                    "social_memory_entries", "meta_connections"):
            await fresh_db[coll].delete_many({"organization_id": org_id} if coll != "organizations" else {"id": org_id})
        client.close()


def test_scenario_bakery_coffee_end_to_end(monkeypatch):
    monkeypatch.setattr(reel.requesty_gateway, "genera_json", lambda **kw: RisultatoGenerazioneRequesty(
        testo=json.dumps(REEL_CONTENT), modello_effettivo="anthropic/claude-sonnet-4-5",
        latenza_ms=250, input_tokens=420, output_tokens=380, troncata=False,
    ))
    monkeypatch.setattr(reel.runway_gateway, "avvia_generazione_video",
                        lambda **kw: TaskAvviato(task_id="task-bakery-1", stima_costo_credits=5.0))

    async def scenario(fresh_db, org_id):
        # 1) Comprensione linguaggio naturale: "reel" viene riconosciuto come
        #    video_reel (mai come 'social' generico) indipendentemente dal
        #    riferimento temporale "questo weekend" nella stessa frase. Lo
        #    stato READY completo (che richiede anche l'azienda) si verifica
        #    al punto 2, dopo l'arricchimento automatico dal Fact Ledger
        #    (create_plan_with_brain) — select_agents() da sola non lo fa,
        #    per costruzione (vedi brain/service.py).
        selezione = select_agents(GOAL)
        assert "video_reel" in selezione.detected_intents

        await _seed_org(fresh_db, org_id)
        await _seed_ready(fresh_db, org_id)

        # 2) Un solo piano, Fact Ledger usato automaticamente (azienda gia'
        #    nota -> nessuna domanda di chiarimento), squadra minima (item #6:
        #    mai una campagna intera per una richiesta di solo reel).
        res = await brain_service.create_plan_with_brain(fresh_db, org_id, "user-e2e", GOAL)
        assert res["requires_clarification"] is False
        assert res["plan"] is not None
        tipi_task = {t["deliverable_type"] for t in res["tasks"]}
        assert tipi_task == {"video_reel_project"}
        reel_project_id = res["reel_project"]["id"]
        assert res["reel_project"]["fact_snapshot"]["ragione_sociale"] == "Bakery & Coffee S.r.l."

        # 3) Generazione testo REALE (Requesty mockato, unico confine esterno):
        #    hashtag, compliance, quality gate.
        r1 = await reel.generate(reel_project_id, reel.ConfirmBody(confirm=True), _admin(org_id))
        assert r1["status"] == "PROGETTO_PRONTO"
        assert r1["content"]["hashtags"] == ["#focaccine", "#weekend", "#bakerycoffee"]
        assert r1["semantic_check"]["status"] == "OK"

        # 4) Video reale (Runway mockato) -> stato terminale simulato come
        #    farebbe il poller (stesso pattern di test_reel_video_flow.py).
        await reel.video_generate(reel_project_id, reel.ConfirmBody(confirm=True), _admin(org_id))
        job = await fresh_db.reel_video_jobs.find_one({"reel_project_id": reel_project_id}, {"_id": 0})
        stato_ok = StatoTask(task_id="task-bakery-1", status="SUCCEEDED",
                             output_urls=["https://cdn.runway.example/bakery-weekend.mp4"],
                             costo_credits=4.2, progress=1.0, errore_messaggio=None, errore_codice=None)
        await reel._applica_stato_terminale(org_id, reel_project_id, job["id"], stato_ok)

        # 5) Due approvazioni DISTINTE (item 8/9): testo e video.
        await reel.approve_project(reel_project_id, _admin(org_id))
        video_ok = await reel.video_approve(reel_project_id, _admin(org_id))
        assert video_ok["progetto_approvato"] is True
        assert video_ok["video_approvato"] is True
        assert video_ok["video_url"] == "https://cdn.runway.example/bakery-weekend.mp4"

        # 6) Memoria persistente (item 13): scritta da entrambe le
        #    approvazioni, consultabile per l'apprendimento futuro.
        memoria = await mem.get_memory_context(fresh_db, org_id)
        assert memoria["format_preferences"]
        assert memoria["n_entries"] >= 2

        # 7) Pubblicazione: PublishingService -> ConnectorGateway (item 14),
        #    approvazione DISTINTA da quella del contenuto/media.
        pkg = await sp.create_package(
            sp.NewPublishingPackageBody(source_kind="reel", source_project_id=reel_project_id, channel="instagram"),
            _admin(org_id),
        )
        assert pkg["status"] == "AWAITING_APPROVAL"
        assert pkg["caption"] == "Le nostre focaccine ti aspettano questo weekend!"
        assert pkg["hashtags"] == ["#focaccine", "#weekend", "#bakerycoffee"]
        assert pkg["asset_url"] == "https://cdn.runway.example/bakery-weekend.mp4"

        pkg = await sp.approve_package(pkg["id"], _approvatore(org_id))
        assert pkg["status"] == "APPROVED"

        pkg = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _admin(org_id))
        assert pkg["status"] == "PUBLISHED"
        assert pkg["dry_run"] is True  # nessuna connessione Meta reale configurata in QUESTO scenario (vedi la versione "_con_meta_reale" sotto)
        assert pkg["connector_attempt_id"]

        # 8) Idempotenza: un secondo tentativo di pubblicazione non pubblica
        #    due volte (item 15).
        pkg_retry = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _admin(org_id))
        assert pkg_retry["connector_attempt_id"] == pkg["connector_attempt_id"]

        # 9) Metriche: mai un dato inventato (item 16).
        snap = await sp.refresh_metrics(pkg["id"], _admin(org_id))
        assert snap["data_available"] is False
        assert snap["likes"] is None

        # 10) Audit: ogni passaggio chiave e' tracciato.
        azioni = {a["action"] for a in await fresh_db.audit_logs.find({"organization_id": org_id}).to_list(200)}
        for attesa in ("CREATE_REEL_PROJECT", "REEL_GENERATED", "REEL_VIDEO_GENERATE_STARTED",
                      "REEL_PROJECT_APPROVED", "REEL_VIDEO_APPROVED", "PUBLISHING_PACKAGE_CREATED",
                      "PUBLISHING_PACKAGE_APPROVED", "PUBLISHING_SUCCEEDED"):
            assert attesa in azioni, f"Azione di audit mancante: {attesa}"

    run(_scenario(scenario))


class _FakeGraphResponse:
    def __init__(self, status_code, json_body):
        self.status_code = status_code
        self._json = json_body
        self.headers = {}

    def json(self):
        return self._json


def test_scenario_bakery_coffee_end_to_end_con_meta_reale(monkeypatch):
    """Stesso scenario, ma con REAL_EXTERNAL_ACTIONS abilitato e una
    connessione Meta configurata/verificata (item 30): dimostra il
    dispatch REALE fino a un external_post_id davvero restituito dal
    (finto, trasporto HTTP mockato) provider, metriche reali mappate e un
    suggerimento di apprendimento derivato da >=2 campioni misurati."""
    monkeypatch.setattr(reel.requesty_gateway, "genera_json", lambda **kw: RisultatoGenerazioneRequesty(
        testo=json.dumps(REEL_CONTENT), modello_effettivo="anthropic/claude-sonnet-4-5",
        latenza_ms=250, input_tokens=420, output_tokens=380, troncata=False,
    ))
    monkeypatch.setattr(reel.runway_gateway, "avvia_generazione_video",
                        lambda **kw: TaskAvviato(task_id="task-bakery-2", stima_costo_credits=5.0))
    monkeypatch.setattr(brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(brain_config, "CONNECTOR_MODE", "real")
    gw = ConnectorGateway()
    sp.register_meta_adapters(gateway=gw)
    monkeypatch.setattr(sp, "get_connector_gateway", lambda: gw)

    def fake_transport(method, url, **kw):
        if "/page-bakery/videos" in url:
            return _FakeGraphResponse(200, {"id": "fbvideo-1"})
        if url.endswith("/fbvideo-1") and "insights" not in url:
            return _FakeGraphResponse(200, {"id": "fbvideo-1", "permalink_url": "https://facebook.com/bakerycoffee/videos/fbvideo-1"})
        if url.endswith("/fbvideo-1/insights"):
            return _FakeGraphResponse(200, {"data": [
                {"name": "post_impressions", "values": [{"value": 2000}]},
                {"name": "post_reactions_like_total", "values": [{"value": 180}]},
            ]})
        raise AssertionError(f"URL Graph API inatteso: {method} {url}")

    import requests
    monkeypatch.setattr(requests, "request", fake_transport)

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_ready(fresh_db, org_id)
        # Campioni gia' misurati in precedenza (learning suggestion, item 17):
        # 2 snapshot 'flyer' (engagement piu' basso) + 1 snapshot 'reel'
        # precedente -- il secondo campione 'reel' arrivera' da questo
        # stesso scenario (refresh_metrics sotto), raggiungendo la soglia
        # minima di 2 campioni per ENTRAMBI i formati, necessaria perche'
        # derive_learning_suggestions() produca un confronto onesto.
        for i in range(2):
            await fresh_db.social_analytics_snapshots.insert_one({
                "id": f"snap-flyer-{i}", "organization_id": org_id, "publishing_package_id": f"pkg-flyer-{i}",
                "source_kind": "flyer", "channel": "facebook", "data_available": True, "engagement_score": 2.0,
                "created_at": "2026-01-01T00:00:00+00:00",
            })
        await fresh_db.social_analytics_snapshots.insert_one({
            "id": "snap-reel-precedente", "organization_id": org_id, "publishing_package_id": "pkg-reel-precedente",
            "source_kind": "reel", "channel": "facebook", "data_available": True, "engagement_score": 7.0,
            "created_at": "2026-01-01T00:00:00+00:00",
        })

        res = await brain_service.create_plan_with_brain(fresh_db, org_id, "user-e2e-2", GOAL)
        reel_project_id = res["reel_project"]["id"]

        await reel.generate(reel_project_id, reel.ConfirmBody(confirm=True), _admin(org_id))
        await reel.video_generate(reel_project_id, reel.ConfirmBody(confirm=True), _admin(org_id))
        job = await fresh_db.reel_video_jobs.find_one({"reel_project_id": reel_project_id}, {"_id": 0})
        stato_ok = StatoTask(task_id="task-bakery-2", status="SUCCEEDED",
                             output_urls=["https://cdn.runway.example/bakery-weekend-2.mp4"],
                             costo_credits=4.2, progress=1.0, errore_messaggio=None, errore_codice=None)
        await reel._applica_stato_terminale(org_id, reel_project_id, job["id"], stato_ok)
        await reel.approve_project(reel_project_id, _admin(org_id))
        await reel.video_approve(reel_project_id, _admin(org_id))

        # Connessione Meta REALE, configurata e gia' verificata per questa organizzazione.
        conn = base_record(org_id, "system")
        conn.update({
            "id": "metaconn-e2e", "name": "Bakery Meta", "mode": "real",
            "app_id": "app1", "app_secret_encrypted": None,
            "access_token_encrypted": encrypt_secret("token-reale-bakery"), "access_token_masked": "****kery",
            "page_id": "page-bakery", "page_name": "Bakery & Coffee",
            "instagram_business_account_id": "", "instagram_username": "",
            "graph_api_version": "v21.0", "active": True,
            "facebook_status": meta_connections.STATUS_CONNECTED, "instagram_status": meta_connections.STATUS_NOT_CONFIGURED,
            "last_test_at": "2026-01-01T00:00:00+00:00", "last_test_result": "OK_REALE",
        })
        await fresh_db.meta_connections.insert_one(conn)

        pkg = await sp.create_package(
            sp.NewPublishingPackageBody(source_kind="reel", source_project_id=reel_project_id, channel="facebook"),
            _admin(org_id),
        )
        pkg = await sp.approve_package(pkg["id"], _approvatore(org_id))
        pkg = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _admin(org_id))

        assert pkg["status"] == "PUBLISHED"
        assert pkg["dry_run"] is False  # dispatch REALE, non piu' dry-run
        assert pkg["external_post_id"] == "fbvideo-1"
        assert pkg["permalink"] == "https://facebook.com/bakerycoffee/videos/fbvideo-1"

        # Idempotenza anche nel percorso reale: un secondo tentativo non ripubblica.
        pkg_retry = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _admin(org_id))
        assert pkg_retry["external_post_id"] == "fbvideo-1"
        assert pkg_retry["connector_attempt_id"] == pkg["connector_attempt_id"]

        snap = await sp.refresh_metrics(pkg["id"], _admin(org_id))
        assert snap["data_available"] is True
        assert snap["impressions"] == 2000
        assert snap["likes"] == 180
        assert snap["engagement_score"] == pytest.approx(9.0)  # 180/2000*100

        suggerimenti = await mem.derive_learning_suggestions(fresh_db, org_id)
        assert len(suggerimenti) == 1
        assert suggerimenti[0]["formato_consigliato"] == "reel"
        assert suggerimenti[0]["base_misurazioni"] == {"flyer": 2, "reel": 2}

    run(_scenario(scenario))
