"""Flusso video reale (Runway) su Mongo locale, MAI una chiamata di rete reale:
il gateway Runway e' sempre mockato (stesso principio delle altre suite reel/
connections). Copre: gating (progetto pronto + verifica semantica + connessione
verificata + budget), tetto di costo, nessuna duplicazione su richieste
concorrenti, distinzione video_pronto/video_approvato, cronologia versionata."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME
from app.domains import reel
from app.models import base_record
from app.security import encrypt_secret
from app.integrations.runway_gateway import TaskAvviato, StatoTask


def run(coro):
    return asyncio.run(coro)


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client[DB_NAME]


def _admin(org_id):
    return {"id": "user-reel-video-admin", "email": "admin-reel-video@test.local", "role": "ADMIN", "organization_id": org_id}


async def _seed_org(fresh_db, org_id):
    org = base_record(org_id, "system")
    org.update({"id": org_id, "ragione_sociale": "Acme S.r.l.", "nome_commerciale": "Acme",
               "settore": "software B2B", "sito_web": "https://acme.example"})
    await fresh_db.organizations.insert_one(org)


async def _seed_text_ready(fresh_db, org_id, model="anthropic/claude-sonnet-4-5"):
    await fresh_db.settings.update_one({"id": org_id}, {"$set": {"id": org_id, "ai_real_mode": True}}, upsert=True)
    await fresh_db.budgets.update_one({"id": org_id}, {"$set": {"id": org_id, "general_limit": 5.0}}, upsert=True)
    conn = base_record(org_id, "system")
    conn.update({"id": f"aiconn-{uuid.uuid4().hex[:8]}", "name": "Requesty", "provider_type": "requesty",
                "effective_model": model, "timeout": 60, "max_tokens": 1800, "active": True, "priority": 1,
                "verified": True, "api_key_encrypted": None, "api_key_masked": ""})
    await fresh_db.ai_connections.insert_one(conn)


async def _seed_video_ready(fresh_db, org_id, *, max_cost=20.0, model="gen4.5"):
    conn = base_record(org_id, "system")
    conn.update({"id": f"vidconn-{uuid.uuid4().hex[:8]}", "name": "Runway", "provider_type": "runway",
                "effective_model": model, "default_ratio": "720:1280", "max_cost_per_generation": max_cost,
                "timeout": 30, "active": True, "priority": 1, "verified": True,
                "api_key_encrypted": encrypt_secret("fake-runway-key"), "api_key_masked": "****fake"})
    await fresh_db.video_connections.insert_one(conn)
    return conn


VALID_CONTENT = {
    "concept": "Un reel che mostra come Acme S.r.l. lavora ogni giorno nel software B2B.",
    "hook": "Ecco come lavoriamo ogni giorno.",
    "sceneggiatura": "Scena 1: apertura. Scena 2: il lavoro sul prodotto. Scena 3: chiusura.",
    "storyboard": [
        {"numero_scena": 1, "descrizione_visiva": "Team al lavoro", "durata_secondi": 4,
         "testo_a_schermo": "Acme", "voice_over": "Ecco chi siamo."},
        {"numero_scena": 2, "descrizione_visiva": "Prodotto in uso", "durata_secondi": 4,
         "testo_a_schermo": "Il nostro lavoro", "voice_over": "Così lavoriamo ogni giorno."},
    ],
    "voice_over_completo": "Ecco chi siamo. Così lavoriamo ogni giorno nel software B2B.",
    "testi_a_schermo": ["Acme", "Il nostro lavoro"],
    "caption": "Acme, ogni giorno.",
    "cta": "Scopri di più",
    "durata_secondi": 8,
    "formato": "9:16",
    "prompt_video_generativo": "Vertical 9:16 video of a small software team at work, clean modern style.",
}


async def _seed_project_progetto_pronto(fresh_db, org_id, *, semantic_ok=True):
    p = await reel.create_project(reel.NewReelBody(brief="reel aziendale"), _admin(org_id))
    from app.domains.reel_semantic import semantic_validate_reel_content
    semantic = {"status": "OK", "affermazioni_contestate": []} if semantic_ok else \
        {"status": "CONTESTATO", "affermazioni_contestate": [{"categoria": "x", "campo": "hook", "frase": "x", "parola_chiave": "x"}]}
    await fresh_db.reel_projects.update_one({"id": p["id"]}, {"$set": {
        "status": "PROGETTO_PRONTO", "progetto_pronto": True, "content": VALID_CONTENT, "semantic_check": semantic,
    }})
    p2 = await fresh_db.reel_projects.find_one({"id": p["id"]}, {"_id": 0})
    return p2


async def _scenario(fn):
    client, fresh_db = _db()
    org_id = f"org-test-reelvideo-{uuid.uuid4().hex[:8]}"
    import app.domains.reel as reel_mod
    import app.audit as audit_mod
    old_db, old_audit_db = reel_mod.db, audit_mod.db
    reel_mod.db = fresh_db
    audit_mod.db = fresh_db
    try:
        return await fn(fresh_db, org_id)
    finally:
        reel_mod.db = old_db
        audit_mod.db = old_audit_db
        for coll in ("organizations", "settings", "budgets", "ai_connections", "video_connections",
                    "reel_projects", "reel_video_jobs", "audit_logs", "executions"):
            await fresh_db[coll].delete_many({"organization_id": org_id} if coll != "organizations" else {"id": org_id})
        client.close()


def test_generate_video_bloccato_senza_verifica_semantica_ok():
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_text_ready(fresh_db, org_id)
        await _seed_video_ready(fresh_db, org_id)
        p = await _seed_project_progetto_pronto(fresh_db, org_id, semantic_ok=False)
        with pytest.raises(Exception) as ei:
            await reel.video_generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 409
        assert "semantica" in ei.value.detail.lower()

    run(_scenario(scenario))


def test_generate_video_bloccato_senza_connessione_runway():
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_text_ready(fresh_db, org_id)
        p = await _seed_project_progetto_pronto(fresh_db, org_id, semantic_ok=True)
        with pytest.raises(Exception) as ei:
            await reel.video_generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 409
        assert "runway" in ei.value.detail.lower()

    run(_scenario(scenario))


def test_generate_video_richiede_conferma_esplicita():
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_text_ready(fresh_db, org_id)
        await _seed_video_ready(fresh_db, org_id)
        p = await _seed_project_progetto_pronto(fresh_db, org_id, semantic_ok=True)
        with pytest.raises(Exception) as ei:
            await reel.video_generate(p["id"], reel.ConfirmBody(confirm=False), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 400

    run(_scenario(scenario))


def test_generate_video_ok_avvia_job_in_generazione(monkeypatch):
    monkeypatch.setattr(reel.runway_gateway, "avvia_generazione_video",
                        lambda **kw: TaskAvviato(task_id="task-abc123", stima_costo_credits=5.0))

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_text_ready(fresh_db, org_id)
        await _seed_video_ready(fresh_db, org_id, max_cost=20.0)
        p = await _seed_project_progetto_pronto(fresh_db, org_id, semantic_ok=True)

        result = await reel.video_generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        assert result["video_status"] == "IN_GENERAZIONE"
        assert result["video_pronto"] is False
        assert result["video_approvato"] is False

        jobs = await fresh_db.reel_video_jobs.find({"reel_project_id": p["id"]}, {"_id": 0}).to_list(10)
        assert len(jobs) == 1
        assert jobs[0]["version"] == 1
        assert jobs[0]["status"] == "IN_GENERAZIONE"
        assert jobs[0]["task_id_remoto"] == "task-abc123"

        # Nessuna seconda generazione mentre una e' gia' in corso (niente duplicati su refresh/doppio click).
        with pytest.raises(Exception) as ei:
            await reel.video_generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 409

    run(_scenario(scenario))


def test_generate_video_tetto_costo_superato_annulla_e_blocca(monkeypatch):
    monkeypatch.setattr(reel.runway_gateway, "avvia_generazione_video",
                        lambda **kw: TaskAvviato(task_id="task-costoso", stima_costo_credits=999.0))
    monkeypatch.setattr(reel.runway_gateway, "annulla_task", lambda *a, **kw: True)

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_text_ready(fresh_db, org_id)
        await _seed_video_ready(fresh_db, org_id, max_cost=20.0)
        p = await _seed_project_progetto_pronto(fresh_db, org_id, semantic_ok=True)

        with pytest.raises(Exception) as ei:
            await reel.video_generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 409
        assert "tetto" in ei.value.detail.lower()

        job = await fresh_db.reel_video_jobs.find_one({"reel_project_id": p["id"]}, {"_id": 0})
        assert job["status"] == "BLOCCATO"
        assert job["errore_codice"] == "tetto_costo_superato"
        proj = await fresh_db.reel_projects.find_one({"id": p["id"]}, {"_id": 0})
        assert proj["video_status"] == "BLOCCATO"

    run(_scenario(scenario))


def test_video_pronto_e_approvazione_distinte_dal_progetto_testo(monkeypatch):
    monkeypatch.setattr(reel.runway_gateway, "avvia_generazione_video",
                        lambda **kw: TaskAvviato(task_id="task-ok", stima_costo_credits=5.0))

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_text_ready(fresh_db, org_id)
        await _seed_video_ready(fresh_db, org_id)
        p = await _seed_project_progetto_pronto(fresh_db, org_id, semantic_ok=True)

        result = await reel.video_generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        job_id = (await fresh_db.reel_video_jobs.find_one({"reel_project_id": p["id"]}, {"_id": 0}))["id"]

        # video ancora IN_GENERAZIONE: approvazione video rifiutata (nessun video riproducibile)
        with pytest.raises(Exception) as ei:
            await reel.video_approve(p["id"], _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 409

        # simula l'esito terminale (come farebbe il poller o l'aggiornamento manuale)
        stato_ok = StatoTask(task_id="task-ok", status="SUCCEEDED",
                             output_urls=["https://cdn.runway.example/video123.mp4"],
                             costo_credits=4.5, progress=1.0, errore_messaggio=None, errore_codice=None)
        await reel._applica_stato_terminale(org_id, p["id"], job_id, stato_ok)

        proj = await fresh_db.reel_projects.find_one({"id": p["id"]}, {"_id": 0})
        assert proj["video_status"] == "VIDEO_PRONTO"
        assert proj["video_url"] == "https://cdn.runway.example/video123.mp4"
        pub = reel._public(proj)
        assert pub["video_pronto"] is True
        assert pub["video_approvato"] is False  # pronto != approvato

        approved = await reel.video_approve(p["id"], _admin(org_id))
        assert approved["video_approvato"] is True
        assert approved["progetto_approvato"] is False  # l'approvazione video non tocca quella del progetto testo

    run(_scenario(scenario))


def test_video_fallito_registra_comunque_il_costo(monkeypatch):
    monkeypatch.setattr(reel.runway_gateway, "avvia_generazione_video",
                        lambda **kw: TaskAvviato(task_id="task-fail", stima_costo_credits=5.0))

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_text_ready(fresh_db, org_id)
        await _seed_video_ready(fresh_db, org_id)
        p = await _seed_project_progetto_pronto(fresh_db, org_id, semantic_ok=True)
        await reel.video_generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        job_id = (await fresh_db.reel_video_jobs.find_one({"reel_project_id": p["id"]}, {"_id": 0}))["id"]

        stato_fail = StatoTask(task_id="task-fail", status="FAILED", output_urls=[], costo_credits=3.0,
                               progress=None, errore_messaggio="Generazione fallita lato Runway", errore_codice="content_policy")
        await reel._applica_stato_terminale(org_id, p["id"], job_id, stato_fail)

        job = await fresh_db.reel_video_jobs.find_one({"id": job_id}, {"_id": 0})
        assert job["status"] == "FALLITO"
        assert job["costo_credits"] == 3.0  # credito consumato anche in caso di fallimento

    run(_scenario(scenario))
