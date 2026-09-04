"""Brain (CEO Agent) — test per i gap chiusi nel blocco "100% reale":
idempotenza di create_plan_with_brain() su session_id duplicato, persistenza
reale su MongoDB di audit trail e snapshot sessione (audit/memory_audit.py e
memory/session.py restano PURI: la persistenza avviene in service.py), e
collegamento reale di mark_result_ready_for_approval() tramite
refresh_plan_readiness()/inspect_session_async(). Richiede MongoDB locale
(stesso requisito di test_brain_focaccine.py)."""
import asyncio
import uuid

import pytest
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

from app.brain import router as brain_router
from app.brain import service as SVC
from app.brain.audit.memory_audit import EVENT_RESULT_READY_FOR_APPROVAL, get_audit_log
from app.brain.memory.session import get_session_store
from app.m2 import models as M

FOCACCINE_GOAL = (
    "Prepara una campagna social per pubblicizzare le focaccine artigianali del "
    "Bakery & Coffee di Merate. Crea una strategia locale, un piano editoriale e "
    "tre post per Instagram e Facebook rivolti alle famiglie e ai lavoratori della "
    "zona. Usa dati simulati, non contattare clienti e non pubblicare nulla."
)
GOAL_AMBIGUO = "Fai qualcosa di utile per me"


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


async def _cleanup(db, org):
    for c in ("plans", "tasks", "executions", "deliverables", "audit_logs", "goals",
              "brain_audit_events", "brain_sessions"):
        await db[c].delete_many({"organization_id": org})


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def reset_singleton_stores():
    get_session_store().reset()
    get_audit_log().reset()
    yield
    get_session_store().reset()
    get_audit_log().reset()


# ---------------- idempotenza (item 13) ----------------
def test_stesso_session_id_non_crea_un_secondo_piano():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            sid = f"s-idem-{uuid.uuid4().hex[:8]}"
            res1 = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL, session_id=sid)
            assert res1["plan"] is not None
            assert res1.get("idempotent_replay") is not True
            plan_id = res1["plan"]["id"]

            res2 = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL, session_id=sid)
            assert res2["idempotent_replay"] is True
            assert res2["plan"]["id"] == plan_id
            assert res2["tasks"] == res1["tasks"] or {t["id"] for t in res2["tasks"]} == {t["id"] for t in res1["tasks"]}

            piani = await db.plans.count_documents({"organization_id": org})
            assert piani == 1, "una submit duplicata con lo stesso session_id non deve creare un secondo piano"
            goals = await db.goals.count_documents({"organization_id": org})
            assert goals == 1
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_session_id_diversi_creano_piani_distinti():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            res1 = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL,
                                                      session_id=f"s-a-{uuid.uuid4().hex[:8]}")
            res2 = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL,
                                                      session_id=f"s-b-{uuid.uuid4().hex[:8]}")
            assert res1["plan"]["id"] != res2["plan"]["id"]
            piani = await db.plans.count_documents({"organization_id": org})
            assert piani == 2
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- persistenza audit trail + sessione (item 2/3) ----------------
def test_audit_trail_persistito_su_mongo_con_organization_id():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            sid = f"s-audit-{uuid.uuid4().hex[:8]}"
            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL, session_id=sid)
            assert res["plan"] is not None

            eventi_memoria = get_audit_log().filter(session_id=sid)
            assert eventi_memoria

            persistiti = await db.brain_audit_events.find({"session_id": sid}, {"_id": 0}).to_list(200)
            assert len(persistiti) == len(eventi_memoria)
            assert all(e["organization_id"] == org for e in persistiti)
            id_memoria = {e["event_id"] for e in eventi_memoria}
            id_persistiti = {e["event_id"] for e in persistiti}
            assert id_memoria == id_persistiti

            snap = await db.brain_sessions.find_one({"session_id": sid}, {"_id": 0})
            assert snap is not None
            assert snap["organization_id"] == org
            assert snap["plan_id"] == res["plan"]["id"]
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_audit_persistito_anche_su_percorso_needs_clarification():
    """La persistenza deve avvenire ad OGNI punto di ritorno, non solo sul
    percorso READY finale: un obiettivo ambiguo produce comunque eventi
    audit (CLARIFICATION_REQUIRED) che devono restare tracciabili anche
    dopo un eventuale riavvio del processo."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            sid = f"s-ambiguo-{uuid.uuid4().hex[:8]}"
            res = await SVC.create_plan_with_brain(db, org, "user-test", GOAL_AMBIGUO, session_id=sid)
            assert res["requires_clarification"] is True

            persistiti = await db.brain_audit_events.find({"session_id": sid}, {"_id": 0}).to_list(200)
            assert persistiti, "anche un esito NEEDS_CLARIFICATION deve persistere il suo audit trail"
            snap = await db.brain_sessions.find_one({"session_id": sid}, {"_id": 0})
            assert snap is not None
            assert snap["status"] == "NEEDS_CLARIFICATION"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- collegamento reale mark_result_ready_for_approval (item 1) ----------------
def test_refresh_plan_readiness_raggiunge_davvero_ready_for_approval():
    """Prima di questo blocco, mark_result_ready_for_approval() non era mai
    invocata da alcun percorso di produzione (solo dai test). Qui si
    verifica che, completando/approvando realmente i task e i deliverable
    su MongoDB (esattamente come farebbe l'esecuzione M2 reale), la
    funzione pura venga raggiunta con lo stato vero e produca un evento
    RESULT_READY_FOR_APPROVAL genuino, idempotente su chiamate ripetute."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            sid = f"s-ready-{uuid.uuid4().hex[:8]}"
            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL, session_id=sid)
            plan = res["plan"]
            tasks = res["tasks"]
            assert tasks

            esito_precoce = await SVC.refresh_plan_readiness(db, org, plan["id"])
            assert esito_precoce["ready"] is False  # nessun task ancora completato/approvato

            for t in tasks:
                await db.tasks.update_one(
                    {"id": t["id"]},
                    {"$set": {"task_status": "COMPLETATA", "approved": True}},
                )
                await db.deliverables.insert_one({
                    "id": f"deliv-{t['id']}", "organization_id": org, "plan_id": plan["id"],
                    "task_id": t["id"], "is_current": True, "valid": True,
                    "status": "COMPLETATO", "content": {"nota": "test"}, "version": 1,
                })

            esito = await SVC.refresh_plan_readiness(db, org, plan["id"])
            assert esito["ready"] is True, esito["missing_conditions"]
            assert esito["already_marked"] is False
            primo_event_id = esito["event_id"]

            eventi_ready = await db.brain_audit_events.find(
                {"session_id": sid, "event_type": EVENT_RESULT_READY_FOR_APPROVAL}, {"_id": 0}
            ).to_list(10)
            assert len(eventi_ready) == 1

            # idempotenza: richiamata di nuovo, nessun secondo evento
            esito2 = await SVC.refresh_plan_readiness(db, org, plan["id"])
            assert esito2["ready"] is True
            assert esito2["already_marked"] is True
            assert esito2["event_id"] == primo_event_id
            eventi_ready2 = await db.brain_audit_events.find(
                {"session_id": sid, "event_type": EVENT_RESULT_READY_FOR_APPROVAL}, {"_id": 0}
            ).to_list(10)
            assert len(eventi_ready2) == 1
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- resilienza a riavvio del processo (item 5/18) ----------------
def test_inspect_session_async_recupera_da_mongo_dopo_perdita_memoria():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            sid = f"s-restart-{uuid.uuid4().hex[:8]}"
            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL, session_id=sid)
            plan_id = res["plan"]["id"]

            # Simula un riavvio del processo: la memoria in-process va persa,
            # lo snapshot su Mongo resta.
            get_session_store().reset()
            get_audit_log().reset()
            assert SVC.inspect_session(sid)["found"] is False

            risultato = await SVC.inspect_session_async(db, org, sid)
            assert risultato["found"] is True
            assert risultato["plan_id"] == plan_id
            assert risultato["from_persisted_snapshot"] is True
            assert risultato["audit_events"]
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- endpoint GET /brain/sessions/{id} (item 5/18) ----------------
def test_endpoint_get_session_trova_sessione_e_404_su_inesistente(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        monkeypatch.setattr(brain_router, "_global_db", db)
        try:
            await M.create_m2_indexes(db)
            sid = f"s-endpoint-{uuid.uuid4().hex[:8]}"
            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL, session_id=sid)
            plan_id = res["plan"]["id"]

            user = {"id": "user-test", "organization_id": org}
            body = await brain_router.http_get_session(sid, user=user)
            assert body["found"] is True
            assert body["plan_id"] == plan_id

            with pytest.raises(HTTPException) as excinfo:
                await brain_router.http_get_session("session-inesistente-xyz", user=user)
            assert excinfo.value.status_code == 404
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_inspect_session_async_sessione_inesistente():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            risultato = await SVC.inspect_session_async(db, org, "session-mai-esistita")
            assert risultato["found"] is False
            return True
        finally:
            client.close()

    assert run(scenario())
