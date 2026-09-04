"""Blocco 4 — motore approvazioni/execution/task/lease/resume (SIMULAZIONE).
Test a livello core (funzioni con `db` iniettato) su MongoDB locale. Nessuna chiamata reale.
La verifica RBAC/HTTP end-to-end e' delegata al Testing Agent (server live + auth)."""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.m2 import models as M
from app.m2 import engine as E


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


async def _cleanup(db, org):
    for c in ("plans", "tasks", "executions", "deliverables", "audit_logs",
              "worker_leases", "goals"):
        await db[c].delete_many({"organization_id": org})


async def _new_org():
    return f"org-test-{uuid.uuid4().hex[:8]}"


async def _make_plan(db, org, text):
    await M.create_m2_indexes(db)
    goal_id = M.new_id("goal")
    return await E.create_plan(db, org, "user-test", goal_id, text)


async def _set_cost_and_cap(db, plan, cap=1.0, cost=0.001):
    """Rende i test deterministici sul budget: tetto ampio + costo unitario piccolo."""
    await db.tasks.update_many({"plan_id": plan["id"]}, {"$set": {"inputs.cost": cost}})
    ex = await E._get_execution(db, plan)
    if ex:
        await db.executions.update_one({"id": ex["id"]}, {"$set": {"approved_cap": cap}})


def run(coro):
    return asyncio.run(coro)


# ---------------- Approvazioni / gating ----------------
def test_task_non_approvato_non_entra_in_coda():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Prepara una campagna social e adv per il lancio")
            plan = res["plan"]
            # nessuna approvazione -> nessun task in coda
            r = await E.run_ready_tasks(db, plan["id"])
            tasks = await db.tasks.find({"plan_id": plan["id"]}).to_list(50)
            in_coda = [t for t in tasks if t["task_status"] == "IN_CODA"]
            return r["processed"], len(in_coda), all(t["task_status"] == "IN_ATTESA_APPROVAZIONE" for t in tasks)
        finally:
            await _cleanup(db, org); client.close()
    processed, in_coda, all_attesa = run(scenario())
    assert processed == 0 and in_coda == 0 and all_attesa


def test_approvazione_parziale_e_dipendenze_in_attesa():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Prepara una campagna social e adv per il lancio")
            plan = res["plan"]
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            r = await E.approve_task(db, plan["id"], t1["id"], "appr@test")
            tasks = {t["seq"]: t for t in await db.tasks.find({"plan_id": plan["id"]}).to_list(50)}
            return (r["plan_status"], tasks[1]["task_status"], tasks[2]["task_status"])
        finally:
            await _cleanup(db, org); client.close()
    plan_status, t1_status, t2_status = run(scenario())
    assert plan_status == "APPROVATO_PARZIALE"
    assert t1_status == "IN_CODA"            # t1 approvato, senza dipendenze -> in coda
    assert t2_status == "IN_ATTESA_APPROVAZIONE"  # t2 dipende da t1, non approvato -> attende


def test_piano_completo_happy_path():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Prepara una campagna social e adv per il lancio")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            await _set_cost_and_cap(db, plan, cap=1.0, cost=0.001)
            await E.run_ready_tasks(db, plan["id"])
            tasks = await db.tasks.find({"plan_id": plan["id"]}).to_list(50)
            p = await db.plans.find_one({"id": plan["id"]})
            ex = await E._get_execution(db, plan)
            return ([t["task_status"] for t in tasks], p["plan_status"],
                    ex["execution_status"], round(ex["real_cost"], 4))
        finally:
            await _cleanup(db, org); client.close()
    statuses, plan_status, ex_status, cost = run(scenario())
    assert all(s == "COMPLETATA" for s in statuses), statuses
    assert plan_status == "COMPLETATO"
    assert ex_status == "COMPLETATA"
    assert cost == 0.005  # 5 task x 0.001, costo una volta ciascuno


# ---------------- Una execution per (plan, version) + concorrenza ----------------
def test_una_execution_per_versione_concorrente():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Scrivi una breve email commerciale")
            plan = res["plan"]
            a, b = await asyncio.gather(
                E.create_execution(db, plan, "sys"),
                E.create_execution(db, plan, "sys"),
            )
            count = await db.executions.count_documents({"plan_id": plan["id"]})
            return a["id"], b["id"], count
        finally:
            await _cleanup(db, org); client.close()
    id_a, id_b, count = run(scenario())
    assert id_a == id_b and count == 1


def test_doppio_click_approvazione_idempotente():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Scrivi una breve email commerciale")
            plan = res["plan"]
            r1, r2 = await asyncio.gather(
                E.approve_plan(db, plan["id"], "appr@test"),
                E.approve_plan(db, plan["id"], "appr@test"),
            )
            count = await db.executions.count_documents({"plan_id": plan["id"]})
            return r1["execution_id"], r2["execution_id"], count
        finally:
            await _cleanup(db, org); client.close()
    e1, e2, count = run(scenario())
    assert e1 == e2 and count == 1


# ---------------- Claim atomico singolo worker ----------------
def test_claim_atomico_singolo_worker():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Scrivi una breve email commerciale")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            assert t1["task_status"] == "IN_CODA"
            a, b = await asyncio.gather(E.claim_task(db, t1["id"]), E.claim_task(db, t1["id"]))
            winners = [x for x in (a, b) if x is not None]
            leases = await db.worker_leases.count_documents({"task_id": t1["id"]})
            claimed = await db.tasks.find_one({"id": t1["id"]})
            return len(winners), leases, claimed["attempt"]
        finally:
            await _cleanup(db, org); client.close()
    winners, leases, attempt = run(scenario())
    assert winners == 1 and leases == 1 and attempt == 1


# ---------------- Lease / recovery ----------------
def test_recover_task_confermato_completa_senza_ricosto():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Scrivi una breve email commerciale")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            await _set_cost_and_cap(db, plan, cost=0.001)
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            await E.claim_task(db, t1["id"])
            # simula deliverable confermato + lease scaduto (crash dopo persistenza)
            past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
            await db.tasks.update_one({"id": t1["id"]},
                                      {"$set": {"confirmed": True, "cost": 0.001,
                                                "last_costed_attempt": 1, "lease_expires_at": past}})
            await E.recover_m2(db)
            t = await db.tasks.find_one({"id": t1["id"]})
            return t["task_status"], round(t["cost"], 4)
        finally:
            await _cleanup(db, org); client.close()
    status, cost = run(scenario())
    assert status == "COMPLETATA"
    assert cost == 0.001  # nessun ri-addebito


def test_recover_riprende_stesso_tentativo_costo_una_volta():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Scrivi una breve email commerciale")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            await _set_cost_and_cap(db, plan, cost=0.002)
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            await db.tasks.update_one({"id": t1["id"]}, {"$set": {"inputs.crash": "before_deliverable"}})
            # prima esecuzione: crash prima del deliverable -> resta IN_ESECUZIONE, costo addebitato 1 volta
            await E.process_task(db, t1["id"])
            mid = await db.tasks.find_one({"id": t1["id"]})
            # scade il lease e recupera: STESSO tentativo, nessun raddoppio costo
            past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
            await db.tasks.update_one({"id": t1["id"]}, {"$set": {"lease_expires_at": past}})
            await E.recover_m2(db)
            fin = await db.tasks.find_one({"id": t1["id"]})
            ex = await E._get_execution(db, plan)
            return (mid["task_status"], mid["attempt"], round(mid["cost"], 4),
                    fin["task_status"], round(fin["cost"], 4), round(ex["real_cost"], 4))
        finally:
            await _cleanup(db, org); client.close()
    mid_status, mid_attempt, mid_cost, fin_status, fin_cost, ex_cost = run(scenario())
    assert mid_status == "IN_ESECUZIONE" and mid_attempt == 1 and mid_cost == 0.002
    assert fin_status == "COMPLETATA"
    assert fin_cost == 0.002 and ex_cost == 0.002  # costo contato UNA sola volta


def test_recover_concorrente_non_raddoppia():
    """Due recover concorrenti non devono raddoppiare costo/esecuzione dello stesso task
    (garanzia di idempotenza sotto lock, indipendente dal timing di rilascio)."""
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            await db.m2_locks.delete_one({"_id": "m2_recover"})
            res = await _make_plan(db, org, "Scrivi una breve email commerciale")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            await _set_cost_and_cap(db, plan, cost=0.002)
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            await db.tasks.update_one({"id": t1["id"]}, {"$set": {"inputs.crash": "before_deliverable"}})
            await E.process_task(db, t1["id"])  # crash pre-deliverable -> IN_ESECUZIONE, costo 1x
            past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
            await db.tasks.update_one({"id": t1["id"]}, {"$set": {"lease_expires_at": past}})
            a, b = await asyncio.gather(E.recover_m2(db), E.recover_m2(db))
            fin = await db.tasks.find_one({"id": t1["id"]})
            ex = await E._get_execution(db, plan)
            delivs = await db.deliverables.count_documents({"plan_id": plan["id"], "task_id": t1["id"]})
            return fin["task_status"], round(fin["cost"], 4), round(ex["real_cost"], 4), delivs
        finally:
            await _cleanup(db, org); client.close()
    status, cost, ex_cost, delivs = run(scenario())
    assert status == "COMPLETATA"
    assert cost == 0.002 and ex_cost == 0.002   # costo NON raddoppiato
    assert delivs == 1                          # un solo deliverable


def test_recover_lock_leader_election():
    """Lock persistente: acquisizione concorrente -> un solo leader alla volta."""
    async def scenario():
        client, db = _db()
        try:
            await db.m2_locks.delete_one({"_id": "m2_recover"})
            a, b = await asyncio.gather(E._acquire_lock(db, "m2_recover"),
                                        E._acquire_lock(db, "m2_recover"))
            owners = [x for x in (a, b) if x]
            await db.m2_locks.delete_one({"_id": "m2_recover"})
            return len(owners)
        finally:
            client.close()
    assert run(scenario()) == 1


# ---------------- Max attempts / dipendenti saltati ----------------
def test_max_attempts_poi_fallita_e_dipendenti_saltati():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Prepara una campagna social e adv per il lancio")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            await _set_cost_and_cap(db, plan, cap=1.0, cost=0.001)
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            await db.tasks.update_one({"id": t1["id"]}, {"$set": {"inputs.simulate": "fail"}})
            # esegue fino ad esaurire i tentativi
            for _ in range(E.MAX_ATTEMPTS + 2):
                await E.run_ready_tasks(db, plan["id"])
            tasks = {t["seq"]: t for t in await db.tasks.find({"plan_id": plan["id"]}).to_list(50)}
            p = await db.plans.find_one({"id": plan["id"]})
            return (tasks[1]["task_status"], tasks[1]["attempt"], round(tasks[1]["cost"], 4),
                    tasks[2]["task_status"], tasks[4]["task_status"], p["plan_status"])
        finally:
            await _cleanup(db, org); client.close()
    t1_status, t1_attempt, t1_cost, t2_status, t4_status, plan_status = run(scenario())
    assert t1_status == "FALLITA" and t1_attempt == E.MAX_ATTEMPTS
    assert round(t1_cost, 4) == round(0.001 * E.MAX_ATTEMPTS, 4)  # costo 1 volta per tentativo
    assert t2_status == "SALTATA" and t4_status == "SALTATA"       # dipendenti saltati
    assert plan_status == "BLOCCATO"


# ---------------- Budget ----------------
def test_budget_tetto_approvato_blocca_task():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Scrivi una breve email commerciale")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            await db.tasks.update_one({"id": t1["id"]}, {"$set": {"inputs.cost": 0.5}})
            ex = await E._get_execution(db, plan)
            await db.executions.update_one({"id": ex["id"]}, {"$set": {"approved_cap": 0.01}})
            await E.run_ready_tasks(db, plan["id"])
            t = await db.tasks.find_one({"id": t1["id"]})
            return t["task_status"], t.get("warnings", [])
        finally:
            await _cleanup(db, org); client.close()
    status, warnings = run(scenario())
    assert status == "BLOCCATA"
    assert any("Budget" in w for w in warnings)


# ---------------- Stop manuale ----------------
def test_stop_plan_impedisce_esecuzione():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Prepara una campagna social e adv per il lancio")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            await E.stop_plan(db, plan["id"], "admin@test")
            r = await E.run_ready_tasks(db, plan["id"])
            done = await db.tasks.count_documents({"plan_id": plan["id"], "task_status": "COMPLETATA"})
            return r.get("stopped"), done
        finally:
            await _cleanup(db, org); client.close()
    stopped, done = run(scenario())
    assert stopped is True and done == 0


# ---------------- Reject con motivazione + preservazione risultati ----------------
def test_reject_richiede_motivazione():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Prepara una campagna social e adv per il lancio")
            plan = res["plan"]
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            err = None
            try:
                await E.reject_task(db, plan["id"], t1["id"], "appr@test", "")
            except ValueError as e:
                err = str(e)
            return err
        finally:
            await _cleanup(db, org); client.close()
    err = run(scenario())
    assert err is not None and "Motivazione" in err


def test_reject_blocca_dipendenti_e_preserva_risultati():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Prepara una campagna social e adv per il lancio")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            await _set_cost_and_cap(db, plan, cap=1.0, cost=0.001)
            # completa t1 (produce deliverable), poi rifiuta t2 (dipende da t1)
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            await E.process_task(db, t1["id"])
            deliv_before = await db.deliverables.count_documents({"plan_id": plan["id"]})
            t2 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 2})
            r = await E.reject_task(db, plan["id"], t2["id"], "appr@test", "Contenuto non conforme")
            tasks = {t["seq"]: t for t in await db.tasks.find({"plan_id": plan["id"]}).to_list(50)}
            deliv_after = await db.deliverables.count_documents({"plan_id": plan["id"]})
            return (r["reason"], tasks[1]["task_status"], tasks[2]["task_status"],
                    tasks[3]["task_status"], deliv_before, deliv_after)
        finally:
            await _cleanup(db, org); client.close()
    reason, t1_s, t2_s, t3_s, dbefore, dafter = run(scenario())
    assert reason == "Contenuto non conforme"
    assert t1_s == "COMPLETATA"          # risultato prodotto preservato
    assert t2_s == "BLOCCATA"            # rifiutato
    assert t3_s == "SALTATA"             # dipende da t2 -> saltato
    assert dbefore == 1 and dafter == 1  # deliverable di t1 NON cancellato


def test_reject_su_task_terminale_non_consentito():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Scrivi una breve email commerciale")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            await _set_cost_and_cap(db, plan, cost=0.001)
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            await E.process_task(db, t1["id"])  # -> COMPLETATA
            err = None
            try:
                await E.reject_task(db, plan["id"], t1["id"], "appr@test", "troppo tardi")
            except E.InvalidTransition as e:
                err = str(e)
            return err
        finally:
            await _cleanup(db, org); client.close()
    err = run(scenario())
    assert err is not None  # non si puo' rifiutare un task gia' completato (risultati preservati)


# ---------------- Transizioni di stato ----------------
def test_transizione_non_valida_sollevata():
    async def scenario():
        client, db = _db()
        org = await _new_org()
        try:
            res = await _make_plan(db, org, "Scrivi una breve email commerciale")
            plan = res["plan"]
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            err = None
            try:
                # IN_ATTESA_APPROVAZIONE -> COMPLETATA non e' consentita
                await E.set_task_status(db, t1, "COMPLETATA")
            except E.InvalidTransition as e:
                err = str(e)
            return err
        finally:
            await _cleanup(db, org); client.close()
    err = run(scenario())
    assert err is not None and "Transizione non consentita" in err
