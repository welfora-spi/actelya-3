"""Brain — capability 'video_reel' (skill REALE, agents/agent_map.py +
brain/skills.py): UN SOLO piano M2, con un task 'video_reel_project'
aggiuntivo collegato a un progetto reale in domains/reel.py (mai un secondo
percorso separato). Nessuna chiamata reale a Requesty/Runway (mai raggiunta
da questi test: ci si ferma alla creazione della bozza, grounded sul Fact
Ledger). Stesso pattern di isolamento db di test_reel_flow.py."""
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
    org_id = f"org-test-brainreel-{uuid.uuid4().hex[:8]}"
    import app.domains.reel as reel_mod
    import app.audit as audit_mod
    old_db, old_audit_db = reel_mod.db, audit_mod.db
    reel_mod.db = fresh_db
    audit_mod.db = fresh_db
    _reset_singletons()
    try:
        return await fn(fresh_db, org_id)
    finally:
        reel_mod.db = old_db
        audit_mod.db = old_audit_db
        _reset_singletons()
        await fresh_db.organizations.delete_many({"id": org_id})
        await fresh_db.reel_projects.delete_many({"organization_id": org_id})
        await fresh_db.goals.delete_many({"organization_id": org_id})
        await fresh_db.plans.delete_many({"organization_id": org_id})
        await fresh_db.tasks.delete_many({"organization_id": org_id})
        await fresh_db.audit_logs.delete_many({"organization_id": org_id})
        client.close()


GOAL_REEL = "Crea un reel per Instagram per pubblicizzare i panini del Bakery & Coffee di Merate"


def test_select_agents_rileva_video_reel_non_social():
    r = select_agents(GOAL_REEL)
    assert r.status == STATUS_READY
    assert "video_reel" in r.detected_intents
    assert "social" not in r.detected_intents
    assert "video-creator" in r.activeAgentIds


def test_create_plan_con_brain_e_un_solo_piano_con_task_reel_collegato():
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        res = await brain_service.create_plan_with_brain(fresh_db, org_id, "user-brain-test", GOAL_REEL)
        assert res["requires_clarification"] is False
        # UN SOLO piano (mai un secondo percorso separato).
        assert res["plan"] is not None
        assert res["reel_project"] is not None
        assert res["reel_project"]["status"] == "BOZZA"
        assert res["reel_project"]["fact_snapshot"]["ragione_sociale"] == "Bakery & Coffee S.r.l."

        reel_tasks = [t for t in res["tasks"] if t["deliverable_type"] == "video_reel_project"]
        assert len(reel_tasks) == 1
        override = reel_tasks[0]["inputs"]["deliverable_override"]
        assert override["reel_project_id"] == res["reel_project"]["id"]
        assert reel_tasks[0]["agent_id"] == "video-creator"

        proj = await fresh_db.reel_projects.find_one({"id": res["reel_project"]["id"]})
        assert proj is not None
        # Il task e' parte dello STESSO piano gia' creato da M2 (nessun piano parallelo).
        plan_tasks = await fresh_db.tasks.find({"plan_id": res["plan"]["id"]}).to_list(20)
        assert any(t["id"] == reel_tasks[0]["id"] for t in plan_tasks)

    run(_scenario(scenario))


def test_video_reel_senza_fact_ledger_non_blocca_il_resto_del_piano():
    """Se il Fact Ledger e' incompleto SOLO il task reel viene omesso: il
    resto del piano (le altre capability) prosegue comunque -- mai un
    blocco totale per una parte non disponibile."""
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id, ragione_sociale="", settore="")
        res = await brain_service.create_plan_with_brain(fresh_db, org_id, "user-brain-test", GOAL_REEL)
        assert res["requires_clarification"] is False
        assert res["plan"] is not None
        assert res["reel_project"] is None
        assert not any(t["deliverable_type"] == "video_reel_project" for t in res["tasks"])
        n = await fresh_db.reel_projects.count_documents({"organization_id": org_id})
        assert n == 0

    run(_scenario(scenario))
