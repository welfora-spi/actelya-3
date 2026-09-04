"""Social Media Manager — pubblicazione (domains/social_publishing.py).
Mongo locale reale, MAI rete reale: il connector (brain/gateways/
connector_gateway.py) e' per costruzione sempre dry_run/bloccato, mai
mockato qui (verificarne il comportamento REALE e' proprio il punto)."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME
from app.domains import social_publishing as sp
from app.models import base_record, now_iso, new_id
from app.brain.gateways.connector_gateway import get_connector_gateway


def run(coro):
    return asyncio.run(coro)


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client[DB_NAME]


def _user(org_id, role, tag="a"):
    return {"id": f"user-pub-{tag}", "email": f"{tag}@test.local", "role": role, "organization_id": org_id}


async def _seed_reel_project(fresh_db, org_id, *, approved=True, media_approved=True, compliance_ok=True,
                              video_url="https://cdn.example/video.mp4"):
    rec = base_record(org_id, "system")
    rec.update({
        "id": new_id("reel"), "brief": "test", "status": "PROGETTO_PRONTO", "progetto_pronto": True,
        "content": {
            "concept": "c", "hook": "h", "sceneggiatura": "s", "storyboard": [], "voice_over_completo": "v",
            "testi_a_schermo": ["t"], "caption": "Guarda il nostro nuovo reel!", "hashtags": ["#novita", "#weekend"],
            "cta": "Scopri di più", "durata_secondi": 20, "formato": "9:16", "prompt_video_generativo": "p",
        },
        "fact_snapshot": {}, "generazione": {}, "progetto_approvato": approved,
        "progetto_approvato_da": "admin" if approved else None, "progetto_approvato_at": now_iso() if approved else None,
        "nota_revisione": None,
        "semantic_check": {"status": "OK" if compliance_ok else "CONTESTATO", "affermazioni_contestate": []},
        "video_status": "VIDEO_PRONTO" if media_approved else "NON_RICHIESTO",
        "video_url": video_url if media_approved else None,
        "video_approvato": media_approved, "video_approvato_da": "admin" if media_approved else None,
        "video_approvato_at": now_iso() if media_approved else None, "video_nota_revisione": None,
    })
    await fresh_db.reel_projects.insert_one(rec)
    return rec


async def _scenario(fn):
    client, fresh_db = _db()
    org_id = f"org-test-pub-{uuid.uuid4().hex[:8]}"
    import app.audit as audit_mod
    from app.domains import meta_connections
    old_db, old_audit_db, old_meta_db = sp.db, audit_mod.db, meta_connections.db
    sp.db = fresh_db
    audit_mod.db = fresh_db
    meta_connections.db = fresh_db
    try:
        return await fn(fresh_db, org_id)
    finally:
        sp.db = old_db
        audit_mod.db = old_audit_db
        meta_connections.db = old_meta_db
        for coll in ("organizations", "reel_projects", "flyer_projects", "social_publishing_packages",
                    "social_analytics_snapshots", "social_memory_entries", "audit_logs"):
            await fresh_db[coll].delete_many({"organization_id": org_id} if coll != "organizations" else {"id": org_id})
        client.close()


# ---------------- creazione pacchetto ----------------

def test_create_package_blocca_se_testo_non_approvato():
    async def scenario(fresh_db, org_id):
        p = await _seed_reel_project(fresh_db, org_id, approved=False)
        with pytest.raises(Exception) as ei:
            await sp.create_package(
                sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p["id"], channel="instagram"),
                _user(org_id, "OPERATORE"),
            )
        assert getattr(ei.value, "status_code", None) == 409

    run(_scenario(scenario))


def test_create_package_blocca_se_media_non_approvato():
    async def scenario(fresh_db, org_id):
        p = await _seed_reel_project(fresh_db, org_id, media_approved=False)
        with pytest.raises(Exception) as ei:
            await sp.create_package(
                sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p["id"], channel="instagram"),
                _user(org_id, "OPERATORE"),
            )
        assert getattr(ei.value, "status_code", None) == 409

    run(_scenario(scenario))


def test_create_package_estrae_i_campi_dal_progetto():
    async def scenario(fresh_db, org_id):
        p = await _seed_reel_project(fresh_db, org_id)
        pkg = await sp.create_package(
            sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p["id"], channel="instagram"),
            _user(org_id, "OPERATORE"),
        )
        assert pkg["status"] == "AWAITING_APPROVAL"
        assert pkg["caption"] == "Guarda il nostro nuovo reel!"
        assert pkg["hashtags"] == ["#novita", "#weekend"]
        assert pkg["asset_url"] == "https://cdn.example/video.mp4"
        assert pkg["channel"] == "instagram"
        assert pkg["idempotency_key"]

    run(_scenario(scenario))


def test_create_package_channel_invalido_rifiutato():
    async def scenario(fresh_db, org_id):
        p = await _seed_reel_project(fresh_db, org_id)
        with pytest.raises(Exception) as ei:
            await sp.create_package(
                sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p["id"], channel="twitter"),
                _user(org_id, "OPERATORE"),
            )
        assert getattr(ei.value, "status_code", None) == 422

    run(_scenario(scenario))


# ---------------- approvazione / stati ----------------

async def _pronto_per_pubblicare(fresh_db, org_id):
    """Crea un pacchetto e lo porta fino ad APPROVED (helper riusato)."""
    p = await _seed_reel_project(fresh_db, org_id)
    pkg = await sp.create_package(
        sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p["id"], channel="instagram"),
        _user(org_id, "OPERATORE"),
    )
    pkg = await sp.approve_package(pkg["id"], _user(org_id, "APPROVATORE", "b"))
    return p, pkg


def test_approve_richiede_ruolo_approvatore_o_admin():
    async def scenario(fresh_db, org_id):
        p = await _seed_reel_project(fresh_db, org_id)
        pkg = await sp.create_package(
            sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p["id"], channel="instagram"),
            _user(org_id, "OPERATORE"),
        )
        pkg2 = await sp.approve_package(pkg["id"], _user(org_id, "ADMIN", "b"))
        assert pkg2["status"] == "APPROVED"
        assert pkg2["approved_by"]

    run(_scenario(scenario))


def test_schedule_rifiuta_data_passata():
    async def scenario(fresh_db, org_id):
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        passato = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with pytest.raises(Exception) as ei:
            await sp.schedule_package(pkg["id"], sp.ScheduleBody(scheduled_at=passato), _user(org_id, "OPERATORE"))
        assert getattr(ei.value, "status_code", None) == 422

    run(_scenario(scenario))


def test_schedule_accetta_data_futura():
    async def scenario(fresh_db, org_id):
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        futuro = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        pkg2 = await sp.schedule_package(pkg["id"], sp.ScheduleBody(scheduled_at=futuro), _user(org_id, "OPERATORE"))
        assert pkg2["status"] == "SCHEDULED"
        assert pkg2["scheduled_at"] == futuro

    run(_scenario(scenario))


# ---------------- pubblicazione (sempre dry-run) ----------------

def test_publish_richiede_conferma_esplicita():
    async def scenario(fresh_db, org_id):
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        with pytest.raises(Exception) as ei:
            await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=False), _user(org_id, "ADMIN"))
        assert getattr(ei.value, "status_code", None) == 400

    run(_scenario(scenario))


def test_publish_bloccato_se_compliance_non_ok():
    async def scenario(fresh_db, org_id):
        p, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        # Compliance regredita dopo l'approvazione del pacchetto (es. una
        # nuova verifica semantica): la pubblicazione deve restare bloccata.
        await fresh_db.reel_projects.update_one({"id": p["id"]}, {"$set": {
            "semantic_check": {"status": "CONTESTATO", "affermazioni_contestate": []}}})
        with pytest.raises(Exception) as ei:
            await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        assert getattr(ei.value, "status_code", None) == 409

    run(_scenario(scenario))


def test_publish_ok_sempre_dry_run():
    async def scenario(fresh_db, org_id):
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        pkg2 = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        assert pkg2["status"] == "PUBLISHED"
        assert pkg2["dry_run"] is True
        assert pkg2["connector_attempt_id"]
        assert pkg2["external_post_id"] is None  # nessun id reale: nessun provider reale ha risposto

    run(_scenario(scenario))


def test_publish_e_idempotente_nessun_secondo_tentativo_connector():
    async def scenario(fresh_db, org_id):
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        gateway = get_connector_gateway()
        n_prima = len(gateway.attempts())

        pkg2 = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        n_dopo_primo = len(gateway.attempts())
        assert n_dopo_primo == n_prima + 1

        # Retry sullo stesso pacchetto GIA' pubblicato: nessuna nuova chiamata.
        pkg3 = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        n_dopo_secondo = len(gateway.attempts())
        assert n_dopo_secondo == n_dopo_primo  # nessun nuovo tentativo registrato
        assert pkg3["connector_attempt_id"] == pkg2["connector_attempt_id"]

    run(_scenario(scenario))


def test_publish_stato_non_valido_rifiutato():
    async def scenario(fresh_db, org_id):
        p = await _seed_reel_project(fresh_db, org_id)
        pkg = await sp.create_package(
            sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p["id"], channel="instagram"),
            _user(org_id, "OPERATORE"),
        )
        # Ancora AWAITING_APPROVAL: non ancora pubblicabile.
        with pytest.raises(Exception) as ei:
            await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        assert getattr(ei.value, "status_code", None) == 409

    run(_scenario(scenario))


# ---------------- cancellazione ----------------

def test_cancel_da_awaiting_approval():
    async def scenario(fresh_db, org_id):
        p = await _seed_reel_project(fresh_db, org_id)
        pkg = await sp.create_package(
            sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p["id"], channel="instagram"),
            _user(org_id, "OPERATORE"),
        )
        pkg2 = await sp.cancel_package(pkg["id"], _user(org_id, "OPERATORE"))
        assert pkg2["status"] == "CANCELLED"

    run(_scenario(scenario))


def test_cancel_dopo_pubblicato_rifiutato():
    async def scenario(fresh_db, org_id):
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        with pytest.raises(Exception) as ei:
            await sp.cancel_package(pkg["id"], _user(org_id, "OPERATORE"))
        assert getattr(ei.value, "status_code", None) == 409

    run(_scenario(scenario))


# ---------------- metriche (mai un dato inventato) ----------------

def test_metrics_richiede_pubblicazione():
    async def scenario(fresh_db, org_id):
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        with pytest.raises(Exception) as ei:
            await sp.refresh_metrics(pkg["id"], _user(org_id, "OPERATORE"))
        assert getattr(ei.value, "status_code", None) == 409

    run(_scenario(scenario))


def test_metrics_dry_run_mai_un_valore_inventato():
    async def scenario(fresh_db, org_id):
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        pkg2 = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        snap = await sp.refresh_metrics(pkg2["id"], _user(org_id, "OPERATORE"))
        assert snap["data_available"] is False
        for campo in ("impressions", "reach", "views", "likes", "comments", "shares", "saves", "clicks", "engagement_score"):
            assert snap[campo] is None, f"{campo} non deve mai essere un valore inventato"

        storia = await sp.metrics_history(pkg2["id"], _user(org_id, "OPERATORE"))
        assert len(storia) == 1

    run(_scenario(scenario))


def test_metrics_latest_senza_rilevazioni():
    async def scenario(fresh_db, org_id):
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        pkg2 = await sp.publish_package(pkg["id"], sp.ConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        latest = await sp.latest_metrics(pkg2["id"], _user(org_id, "OPERATORE"))
        assert latest["data_available"] is False

    run(_scenario(scenario))


def test_doppia_approvazione_rifiutata():
    async def scenario(fresh_db, org_id):
        p = await _seed_reel_project(fresh_db, org_id)
        pkg = await sp.create_package(
            sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p["id"], channel="instagram"),
            _user(org_id, "OPERATORE"),
        )
        await sp.approve_package(pkg["id"], _user(org_id, "APPROVATORE", "b"))
        with pytest.raises(Exception) as ei:
            await sp.approve_package(pkg["id"], _user(org_id, "APPROVATORE", "b"))
        assert getattr(ei.value, "status_code", None) == 409

    run(_scenario(scenario))


def test_recovery_da_riavvio_riporta_publishing_in_approved():
    """Item 21 (test negativo 'restart backend'): un pacchetto rimasto in
    PUBLISHING (come dopo un crash a metà pubblicazione) non deve restare
    bloccato per sempre — recover_on_startup() lo riporta APPROVED,
    ritentabile con un normale publish."""
    async def scenario(fresh_db, org_id):
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        await fresh_db.social_publishing_packages.update_one({"id": pkg["id"]}, {"$set": {"status": "PUBLISHING"}})
        await sp.recover_on_startup()
        pkg2 = await sp.get_package(pkg["id"], _user(org_id, "OPERATORE"))
        assert pkg2["status"] == "APPROVED"

    run(_scenario(scenario))


# ---------------- scheduler (idempotente) ----------------

def test_scheduler_pubblica_pacchetti_scaduti_una_sola_volta():
    async def scenario(fresh_db, org_id):
        _, pkg = await _pronto_per_pubblicare(fresh_db, org_id)
        passato = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        await fresh_db.social_publishing_packages.update_one(
            {"id": pkg["id"]}, {"$set": {"status": "SCHEDULED", "scheduled_at": passato}})

        n1 = await sp._tick_scheduler()
        assert n1 == 1
        pkg2 = await sp.get_package(pkg["id"], _user(org_id, "OPERATORE"))
        assert pkg2["status"] == "PUBLISHED"

        # Un secondo tick non trova piu' nulla di SCHEDULED da elaborare.
        n2 = await sp._tick_scheduler()
        assert n2 == 0

    run(_scenario(scenario))


def test_list_packages_filtra_per_source_project_id():
    async def scenario(fresh_db, org_id):
        p1 = await _seed_reel_project(fresh_db, org_id)
        p2 = await _seed_reel_project(fresh_db, org_id)
        await sp.create_package(
            sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p1["id"], channel="instagram"),
            _user(org_id, "OPERATORE"),
        )
        await sp.create_package(
            sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p2["id"], channel="facebook"),
            _user(org_id, "OPERATORE"),
        )
        solo_p1 = await sp.list_packages(p1["id"], _user(org_id, "OPERATORE"))
        assert len(solo_p1) == 1
        assert solo_p1[0]["source_project_id"] == p1["id"]

        tutti = await sp.list_packages(None, _user(org_id, "OPERATORE"))
        assert len(tutti) == 2

    run(_scenario(scenario))


# ---------------- isolamento tenant ----------------

def test_isolamento_tenant():
    async def scenario(fresh_db, org_a):
        org_b = f"org-test-pub-{uuid.uuid4().hex[:8]}"
        p = await _seed_reel_project(fresh_db, org_a)
        pkg = await sp.create_package(
            sp.NewPublishingPackageBody(source_kind="reel", source_project_id=p["id"], channel="instagram"),
            _user(org_a, "OPERATORE"),
        )
        with pytest.raises(Exception) as ei:
            await sp.get_package(pkg["id"], _user(org_b, "OPERATORE", "cross"))
        assert getattr(ei.value, "status_code", None) == 404

    run(_scenario(scenario))
