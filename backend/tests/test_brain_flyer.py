"""Brain — capability 'flyer_image' (skill REALE, Creative/Graphic Designer):
UN SOLO piano M2, con un task 'flyer_project' aggiuntivo collegato a un
progetto reale in domains/flyer.py. Stesso pattern di test_brain_video_reel.py.
Nessuna chiamata reale a Requesty (mai raggiunta da questi test)."""
import asyncio
import uuid

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME
from app.models import base_record
from app.brain.planning.agent_selector import select_agents, STATUS_READY
from app.brain.memory.session import get_session_store
from app.brain.audit.memory_audit import get_audit_log
from app.brain import service as brain_service


def run(coro):
    return asyncio.run(coro)


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client[DB_NAME]


def _reset_singletons():
    get_session_store().reset()
    get_audit_log().reset()


async def _seed_org(fresh_db, org_id, *, ragione_sociale="Bakery & Coffee S.r.l.", settore="panetteria"):
    org = base_record(org_id, "system")
    org.update({"id": org_id, "ragione_sociale": ragione_sociale, "nome_commerciale": ragione_sociale, "settore": settore})
    await fresh_db.organizations.insert_one(org)


async def _scenario(fn):
    client, fresh_db = _db()
    org_id = f"org-test-brainflyer-{uuid.uuid4().hex[:8]}"
    import app.domains.flyer as flyer_mod
    import app.audit as audit_mod
    old_db, old_audit_db = flyer_mod.db, audit_mod.db
    flyer_mod.db = fresh_db
    audit_mod.db = fresh_db
    _reset_singletons()
    try:
        return await fn(fresh_db, org_id)
    finally:
        flyer_mod.db = old_db
        audit_mod.db = old_audit_db
        _reset_singletons()
        await fresh_db.organizations.delete_many({"id": org_id})
        await fresh_db.flyer_projects.delete_many({"organization_id": org_id})
        await fresh_db.goals.delete_many({"organization_id": org_id})
        await fresh_db.plans.delete_many({"organization_id": org_id})
        await fresh_db.tasks.delete_many({"organization_id": org_id})
        await fresh_db.audit_logs.delete_many({"organization_id": org_id})
        client.close()


GOAL_FLYER = "Crea un flyer per pubblicizzare i panini del Bakery & Coffee di Merate"


def test_select_agents_rileva_flyer_image():
    r = select_agents(GOAL_FLYER)
    assert r.status == STATUS_READY
    assert "flyer_image" in r.detected_intents
    assert "creative-designer" in r.activeAgentIds
    assert "video-creator" not in r.activeAgentIds  # ruoli distinti


def test_create_plan_con_brain_e_un_solo_piano_con_task_flyer_collegato():
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        res = await brain_service.create_plan_with_brain(fresh_db, org_id, "user-brain-test", GOAL_FLYER)
        assert res["requires_clarification"] is False
        assert res["plan"] is not None
        assert res["flyer_project"] is not None
        assert res["flyer_project"]["status"] == "BOZZA"

        flyer_tasks = [t for t in res["tasks"] if t["deliverable_type"] == "flyer_project"]
        assert len(flyer_tasks) == 1
        assert flyer_tasks[0]["inputs"]["deliverable_override"]["flyer_project_id"] == res["flyer_project"]["id"]
        assert flyer_tasks[0]["agent_id"] == "creative-designer"

    run(_scenario(scenario))


def test_piano_flyer_contiene_solo_task_necessari_mai_una_campagna_intera():
    """Correzione item #6 (DECISIONE UFFICIALE): per una richiesta di solo
    flyer il piano deve contenere SOLO i task necessari (qui: 'flyer_project'),
    MAI l'intera campagna che M2 costruiva prima aggiungendo autonomamente
    'editorial_plan'/'social_content' (classify_objective/decompose sul solo
    testo, che riconosce 'flyer' nella regola CONTENUTO indipendentemente
    dalla selezione del brain). La Compliance, essendo contenuto rivolto al
    pubblico, resta convocata come AGENTE (activeAgentIds) senza pero'
    comparire come task proprio (deliverable_type=None, revisione automatica
    m2/reviews.py — vedi agent_map.py)."""
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        res = await brain_service.create_plan_with_brain(fresh_db, org_id, "user-brain-test", GOAL_FLYER)
        assert res["requires_clarification"] is False
        assert res["plan"] is not None

        types_present = {t["deliverable_type"] for t in res["tasks"]}
        assert types_present == {"flyer_project"}, (
            f"Il piano deve contenere SOLO 'flyer_project', trovati invece: {types_present}"
        )

        assert "review_compliance" in res["detected_intents"]
        assert "resp-compliance" in res["activeAgentIds"]
        # Piano, agenti selezionati e Sala Riunioni devono descrivere la stessa
        # squadra: nessun agente di campagna/editoriale/social/advertising/
        # analytics convocato per una richiesta di solo flyer.
        for estraneo in ("resp-marketing", "social-media-manager", "copywriter", "resp-advertising", "analista-performance"):
            assert estraneo not in res["activeAgentIds"], f"Agente estraneo convocato: {estraneo}"

    run(_scenario(scenario))


def test_flyer_e_reel_nello_stesso_obiettivo_creano_due_task_nello_stesso_piano():
    goal = "Crea un flyer e un reel per pubblicizzare i panini del Bakery & Coffee di Merate"

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        import app.domains.reel as reel_mod
        old_reel_db = reel_mod.db
        reel_mod.db = fresh_db
        try:
            res = await brain_service.create_plan_with_brain(fresh_db, org_id, "user-brain-test", goal)
        finally:
            reel_mod.db = old_reel_db
        assert res["plan"] is not None
        assert res["flyer_project"] is not None
        assert res["reel_project"] is not None
        types_present = {t["deliverable_type"] for t in res["tasks"]}
        assert "flyer_project" in types_present
        assert "video_reel_project" in types_present
        # UN SOLO piano per entrambi.
        plan_ids = {t["plan_id"] for t in res["tasks"]}
        assert plan_ids == {res["plan"]["id"]}

        for coll in ("reel_projects",):
            await fresh_db[coll].delete_many({"organization_id": org_id})

    run(_scenario(scenario))
