"""Test mirati — avvio automatico M2 dopo approvazione (m2/engine.py::
_trigger_auto_dispatch/auto_dispatch_worker_loop) e percorso REALE del task
'content_item' (m2/real_content_creator.py).

Nessuna chiamata reale o a pagamento: il trasporto verso Requesty e' un
doppio di test (content_creator.pipeline.requesty_gateway.genera_json
monkeypatchato), stesso stile di test_m2_real_content.py. Database dedicato
di test (mai il DB di sviluppo/produzione)."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.m2 import models as M
from app.m2 import engine as E
from app.domains.content_creator import pipeline as cc_pipeline
from app.tools.cost_ledger import set_daily_cap
from app import audit as audit_module


def _db(monkeypatch=None):
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27020")
    db = client["actelya3_test_m2auto"]
    if monkeypatch is not None:
        # tool_gateway.authorize()/log_audit scrivono sul db GLOBALE
        # (app/audit.py: 'from .db import db', legato a MONGO_URL/.env —
        # oggi actelya3_dev, il database reale preservato): mai lasciare che
        # i test scrivano li'. Reindirizzato sul db di test isolato.
        monkeypatch.setattr(audit_module, "db", db)
    return client, db


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, *orgs):
    for org in orgs:
        for c in ("plans", "tasks", "executions", "deliverables", "audit_logs", "worker_leases",
                  "goals", "reviews", "ai_connections", "budgets", "content_items",
                  "content_item_versions", "tool_cost_events", "organization_budgets", "m2_locks"):
            await db[c].delete_many({"organization_id": org})
        await db.settings.delete_many({"id": org})


def _new_org():
    return f"org-test-auto-{uuid.uuid4().hex[:8]}"


async def _make_plan(db, org, text):
    goal_id = M.new_id("goal")
    await db.goals.insert_one({"id": goal_id, "organization_id": org, "text": text})
    return await E.create_plan(db, org, "user-test", goal_id, text)


CONTENUTO_TEXT = "Piano editoriale con post per Instagram e Facebook della Caffetteria Due Sorsi"


# ==================== 1. Avvio automatico, nessun /tick manuale, dipendenze rispettate ====================
def test_approvazione_avvia_i_task_senza_tick_manuale_e_rispetta_dipendenze():
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            await M.create_m2_indexes(db)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            t2 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 2})
            assert t2["depends_on"] == [t1["id"]], "precondizione: il secondo task dipende dal primo"

            r = await E.approve_plan(db, plan["id"], "appr@test")
            assert r["plan_status"] == "APPROVATO"
            # Nessun E.run_ready_tasks/tick chiamato qui: solo l'approvazione,
            # poi il SOLO giro del worker di poll (mai un tick manuale).
            await E._auto_dispatch_scan_once(db)

            t1_after = await db.tasks.find_one({"id": t1["id"]})
            t2_after = await db.tasks.find_one({"id": t2["id"]})
            assert t1_after["task_status"] == "COMPLETATA", t1_after
            assert t1_after["attempt"] >= 1
            assert t2_after["task_status"] == "COMPLETATA", t2_after
            assert t2_after["attempt"] >= 1
            # La dipendenza e' stata rispettata: t2 non puo' essere partito
            # prima che t1 fosse completato (started_at coerente).
            assert t2_after["started_at"] >= t1_after["finished_at"]
        finally:
            await _cleanup(db, org)
            client.close()
    run(scenario())


# ==================== 2. Task non approvato: mai eseguito ====================
def test_task_non_approvato_mai_eseguito():
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            await M.create_m2_indexes(db)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            t2 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 2})

            await E.approve_task(db, plan["id"], t1["id"], "appr@test")  # solo t1
            await E._auto_dispatch_scan_once(db)

            t1_after = await db.tasks.find_one({"id": t1["id"]})
            t2_after = await db.tasks.find_one({"id": t2["id"]})
            assert t1_after["task_status"] == "COMPLETATA", t1_after
            assert t2_after["approved"] is not True
            assert t2_after["task_status"] != "IN_CODA" and t2_after["task_status"] != "COMPLETATA"
            assert t2_after["attempt"] == 0
        finally:
            await _cleanup(db, org)
            client.close()
    run(scenario())


# ==================== 3. Vecchia coda (senza marcatore): mai raccolta ====================
def test_vecchia_coda_senza_marcatore_non_raccolta_dal_worker():
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            await M.create_m2_indexes(db)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})

            # Simula un'approvazione PRIMA di questa correzione: stesso stato
            # persistito dei piani reali osservati (approved=True, IN_CODA,
            # execution gia' creata), ma SENZA auto_dispatch_requested_at.
            await db.tasks.update_one({"id": t1["id"]}, {"$set": {
                "approved": True, "approved_mode": "SIMULAZIONE", "task_status": "IN_CODA",
            }})
            await db.executions.insert_one({
                "id": M.new_id("exec"), "organization_id": org, "plan_id": plan["id"], "plan_version": 1,
                "execution_status": "IN_ESECUZIONE", "deliverable_status": None, "action_status": "NON_RICHIESTA",
                "real_cost": 0.0, "approved_cap": 1.0, "mode": "SIMULAZIONE",
            })

            # Stessa query usata da auto_dispatch_worker_loop per decidere
            # quali piani processare.
            plan_ids = await db.tasks.distinct(
                "plan_id", {"task_status": "IN_CODA", "auto_dispatch_requested_at": {"$exists": True}})
            assert plan["id"] not in plan_ids, "un task senza marcatore non deve mai essere raccolto"

            # Un giro REALE del worker non deve toccarlo.
            await E._auto_dispatch_scan_once(db)
            t1_after = await db.tasks.find_one({"id": t1["id"]})
            assert t1_after["task_status"] == "IN_CODA" and t1_after["attempt"] == 0  # invariato, mai eseguito

            # Controprova: lo stesso task, marcato come lo sarebbe da
            # un'approvazione passata dal codice corrente, viene raccolto.
            await db.tasks.update_one({"id": t1["id"]}, {"$set": {"auto_dispatch_requested_at": "2026-01-01T00:00:00Z"}})
            await E._auto_dispatch_scan_once(db)
            t1_marked = await db.tasks.find_one({"id": t1["id"]})
            assert t1_marked["task_status"] == "COMPLETATA", t1_marked
        finally:
            await _cleanup(db, org)
            client.close()
    run(scenario())


# ==================== 4. Doppia approvazione: nessuna duplicazione ====================
def test_doppia_approvazione_non_duplica_esecuzione():
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            await M.create_m2_indexes(db)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})

            # Doppio click: due approvazioni concorrenti dello stesso piano.
            await asyncio.gather(
                E.approve_plan(db, plan["id"], "appr@test"),
                E.approve_plan(db, plan["id"], "appr@test"),
            )
            # Due giri del worker (come due tick del poll loop): il secondo
            # non deve trovare più nulla da fare sullo stesso task.
            await E._auto_dispatch_scan_once(db)
            await E._auto_dispatch_scan_once(db)

            t1_after = await db.tasks.find_one({"id": t1["id"]})
            assert t1_after["task_status"] == "COMPLETATA"
            assert t1_after["attempt"] == 1, "un solo tentativo nonostante due approvazioni concorrenti e due giri del worker"
            executions = await db.executions.find({"plan_id": plan["id"]}).to_list(10)
            assert len(executions) == 1, "nessuna execution duplicata (indice unico plan_id+plan_version)"
        finally:
            await _cleanup(db, org)
            client.close()
    run(scenario())


# ==================== Content Creator: setup condiviso ====================
async def _setup_content_org(db, org, *, daily_cap=None):
    await M.create_m2_indexes(db)
    await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
    await db.ai_connections.insert_one({
        "id": f"aiconn-{uuid.uuid4().hex[:8]}", "organization_id": org,
        "provider_type": "requesty", "effective_model": "anthropic/claude-sonnet-4-5",
        "priority": 1, "verified": True, "active": True,
        "timeout": 20, "max_tokens": 1200, "api_key_encrypted": None,
        "created_at": "2026-01-01T00:00:00Z",
    })
    await db.organizations.update_one(
        {"id": org}, {"$set": {"id": org, "ragione_sociale": "SPI Tool", "settore": "servizi informatici"}},
        upsert=True)
    if daily_cap is not None:
        await set_daily_cap(db, org, daily_cap, "test")


async def _make_content_item_task(db, org, *, content=None, cost=0.01):
    """Costruisce un task M2 'content_item' con la stessa forma osservata in
    produzione (agent_id 'content-creator', deliverable_override con
    content_item_ids), collegato a un plan/goal reali. 'cost' di default
    riflette la stima realistica ora prodotta da brain/service.py (0.01 USD
    per elemento) — un task con riserva a zero e' uno scenario esplicito
    (vedi test_content_item_budget_insufficiente_bloccato_senza_retry),
    non lo stato normale di un task appena creato."""
    goal_id = M.new_id("goal")
    await db.goals.insert_one({"id": goal_id, "organization_id": org, "text": "tre post per SPI Tool"})
    piano = await cc_pipeline.create_content_item(
        db, org_id=org, actor="user-test", objective="Promuovere SPI Tool", channel="Instagram",
        funnel_stage="TOFU", content_type="post_social", campaign_id=None, tone_override=None,
        constraints="", brief="tre post testuali in bozza",
    )
    item = piano["items"][0]

    plan_id = M.new_id("plan")
    await db.plans.insert_one({
        "id": plan_id, "organization_id": org, "goal_id": goal_id, "objective_type": "CONTENUTO",
        "plan_status": "IN_ATTESA_APPROVAZIONE", "dag": {"nodes": ["t1"], "edges": []}, "topo_order": ["t1"],
        "estimate": {}, "version": 1, "is_current": True, "created_by": "user-test", "updated_by": "user-test",
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z", "stopped": False,
        # 'approved_cap' rispecchia l'incremento reale che brain/service.py
        # applica al piano quando crea il task 'content_item' (stessa stima
        # del costo del task): senza questo, create_execution erediterebbe
        # un tetto a zero e la riserva atomica su execution.approved_cap
        # (engine.py::_reserve_execution_budget) bloccherebbe qualunque
        # spesa anche quando il task dichiara una riserva sufficiente.
        "approved_cap": cost,
    })
    task_id = M.new_id("task")
    await db.tasks.insert_one({
        "id": task_id, "organization_id": org, "plan_id": plan_id, "goal_id": goal_id, "version": 1, "seq": 1,
        "name": "Content Creator — produzione contenuti", "agent_id": "content-creator",
        "deliverable_type": "content_item",
        "inputs": {"cost": cost, "deliverable_override": {"content_item_ids": [item["id"]], "mode": "REALE",
                                                          "note": "Genera e approva il contenuto in Content Creator."}},
        "depends_on": [], "task_status": "IN_ATTESA_APPROVAZIONE", "approved": False, "attempt": 0,
        "idempotency_key": f"{plan_id}:1:{task_id}", "lease_owner": None, "lease_expires_at": None,
        "tokens_input": 0, "tokens_output": 0, "cost": 0.0, "deliverable_id": None, "warnings": [],
        "confirmed": False, "started_at": None, "finished_at": None, "mode": "SIMULAZIONE",
        "created_by": "user-test", "updated_by": "user-test",
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    })
    return plan_id, task_id, item["id"]


CONTENT_JSON_OK = (
    '{"titolo": "", "corpo": "Scopri i servizi informatici di SPI Tool, pensati per la tua azienda.", '
    '"cta": "Contattaci oggi", "hashtags": ["#SPI", "#servizi"], '
    '"varianti": ["Affidati a SPI Tool per i tuoi servizi informatici."]}'
)


def _adapter_ok(payload):
    def fake_genera_json(**kwargs):
        from app.integrations.requesty_gateway import RisultatoGenerazioneRequesty
        return RisultatoGenerazioneRequesty(testo=payload, modello_effettivo="anthropic/claude-sonnet-4-5",
                                            latenza_ms=42, input_tokens=80, output_tokens=40, troncata=False)
    return fake_genera_json


# ==================== 5. Content Creator: generazione reale riuscita, deliverable con contenuto vero ====================
def test_content_item_generazione_reale_collegata_al_piano(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = _new_org()
        try:
            await _setup_content_org(db, org)
            plan_id, task_id, item_id = await _make_content_item_task(db, org)
            monkeypatch.setattr(cc_pipeline.requesty_gateway, "genera_json", _adapter_ok(CONTENT_JSON_OK))

            await E.approve_plan(db, plan_id, "appr@test")
            await E._auto_dispatch_scan_once(db)

            task_after = await db.tasks.find_one({"id": task_id})
            assert task_after["task_status"] == "COMPLETATA", task_after
            item_after = await db.content_items.find_one({"id": item_id})
            # Bozza reale pronta, MAI approvata automaticamente: l'approvazione
            # del piano autorizza solo la spesa di generazione (vedi
            # m2/real_content_creator.py) — resta IN_ATTESA_APPROVAZIONE finche'
            # un umano non decide nel laboratorio Content Creator.
            assert item_after["status"] == "IN_ATTESA_APPROVAZIONE", item_after
            assert item_after["approved"] is False
            assert item_after["content"] is not None

            deliverable = await db.deliverables.find_one({"id": task_after["deliverable_id"]})
            assert deliverable["mode"] == "REALE"
            assert deliverable["content"]["items"][0]["content"] is not None, \
                "il deliverable M2 deve portare il contenuto reale, non solo il puntatore"
            assert deliverable["content"]["items"][0]["status"] == "IN_ATTESA_APPROVAZIONE"
        finally:
            await _cleanup(db, org)
            client.close()
    run(scenario())


# ==================== 6. Content Creator: budget insufficiente -> bloccato, nessun retry ====================
def test_content_item_budget_insufficiente_bloccato_senza_retry(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = _new_org()
        try:
            await _setup_content_org(db, org, daily_cap=0.0)  # tetto a zero: qualunque spesa lo supera
            plan_id, task_id, item_id = await _make_content_item_task(db, org)
            calls = []
            def fake_genera_json(**kwargs):
                calls.append(kwargs)
                raise AssertionError("non deve mai chiamare Requesty se il budget e' gia' superato")
            monkeypatch.setattr(cc_pipeline.requesty_gateway, "genera_json", fake_genera_json)

            await E.approve_plan(db, plan_id, "appr@test")
            await E._auto_dispatch_scan_once(db)

            task_after = await db.tasks.find_one({"id": task_id})
            assert task_after["task_status"] == "BLOCCATA", task_after
            assert any("BUDGET_SUPERATO" in w or "budget" in w.lower() for w in task_after["warnings"])
            assert calls == [], "nessuna chiamata reale deve partire con budget gia' superato"
            assert task_after["attempt"] == 1, "nessun retry automatico su un blocco di budget"
        finally:
            await _cleanup(db, org)
            client.close()
    run(scenario())
