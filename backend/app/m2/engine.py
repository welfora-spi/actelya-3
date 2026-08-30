"""Milestone 2 — Blocco 4: motore approvazioni/execution/task/lease/resume (SIMULAZIONE).
Le funzioni core accettano `db` (testabilità deterministica); il router usa il db globale.
Nessuna chiamata reale, nessuna azione esterna. Costi/deliverable simulati e idempotenti."""
import os
import asyncio
from datetime import datetime, timezone, timedelta

from ..models import now_iso, new_id
from .models import new_plan, new_task
from .planner import plan_skeleton
from .agents_registry import select_agent, AGENT_CONTRACTS, assert_action_allowed, ContractError
from .deliverables import produce_deliverable, validate_deliverable, create_deliverable_version
from .reviews import review_deliverable
from ..domains.estimator import estimate_for_agents, PRICE_PER_TOKEN

MAX_ATTEMPTS = int(os.environ.get("M2_MAX_ATTEMPTS", "3"))
LEASE_SECONDS = int(os.environ.get("M2_LEASE_SECONDS", "30"))

# --------- Macchina a stati: transizioni consentite ---------
ALLOWED_TASK_TRANSITIONS = {
    "IN_ATTESA_APPROVAZIONE": {"PIANIFICATA", "IN_CODA", "ARRESTATA", "SALTATA", "BLOCCATA"},
    "PIANIFICATA": {"IN_CODA", "ARRESTATA", "SALTATA", "BLOCCATA"},
    "IN_CODA": {"IN_ESECUZIONE", "ARRESTATA", "BLOCCATA", "SALTATA"},
    "IN_ESECUZIONE": {"COMPLETATA", "FALLITA", "IN_CODA", "ARRESTATA", "BLOCCATA"},
    "ARRESTATA": {"IN_CODA"},
    "COMPLETATA": set(), "FALLITA": set(), "BLOCCATA": set(), "SALTATA": set(),
}
TERMINAL = {"COMPLETATA", "FALLITA", "BLOCCATA", "SALTATA"}


class InvalidTransition(Exception):
    pass


_FORBIDDEN_AUDIT = {"api_key", "password", "access_token", "authorization", "secret"}


async def _audit(db, *, org_id, actor, action, entity_type="", entity_id="", details=None, status="OK", reason=""):
    det = {k: ("[REDACTED]" if k.lower() in _FORBIDDEN_AUDIT else v) for k, v in (details or {}).items()}
    await db.audit_logs.insert_one({
        "id": new_id("audit"), "organization_id": org_id, "actor": actor, "action": action,
        "entity_type": entity_type, "entity_id": entity_id, "details": det,
        "status": status, "reason": reason, "at": now_iso(),
    })


async def set_task_status(db, task, new_status, extra=None):
    cur = task["task_status"]
    if new_status != cur and new_status not in ALLOWED_TASK_TRANSITIONS.get(cur, set()):
        raise InvalidTransition(f"Transizione non consentita {cur} -> {new_status}")
    upd = {"task_status": new_status, "updated_at": now_iso()}
    if extra:
        upd.update(extra)
    await db.tasks.update_one({"id": task["id"]}, {"$set": upd})
    task.update(upd)
    return task


# --------- Creazione piano + preventivo ---------
async def create_plan(db, org_id, user_id, goal_id, goal_text):
    sk = plan_skeleton(goal_text)
    if sk["requires_clarification"] or not sk["valid"] or not sk["tasks"]:
        return {"plan": None, "requires_clarification": True, "objective_type": sk["objective_type"],
                "validation_errors": sk["validation_errors"]}
    agent_ids = [select_agent(t["deliverable_type"])["agent_id"] for t in sk["tasks"]]
    estimate = estimate_for_agents(agent_ids, AGENT_CONTRACTS)
    plan = new_plan(org_id, user_id, goal_id, sk["objective_type"], sk["dag"], sk["topo_order"], estimate, version=1)
    plan["plan_status"] = "IN_ATTESA_APPROVAZIONE"
    plan["approved_cap"] = estimate["approvable_cap"]
    plan["stopped"] = False
    await db.plans.insert_one(plan)
    key_to_id = {}
    for seq, spec in enumerate(sk["tasks"], start=1):
        # Costo simulato coerente con il preventivo (cost_probable dell'agente): la somma
        # dei costi per-task resta entro l'approved_cap (total_max * margine di sicurezza).
        sim_cost = estimate["per_agent"][seq - 1]["cost_probable"]
        t = new_task(org_id, user_id, plan["id"], goal_id, plan["version"], seq, spec["name"],
                     select_agent(spec["deliverable_type"])["agent_id"], spec["deliverable_type"],
                     inputs={"cost": sim_cost}, depends_on=[], artifact_slot=f"{spec['deliverable_type']}-{seq}")
        t["_local_key"] = spec["key"]
        t["_local_deps"] = spec["depends_on"]
        key_to_id[spec["key"]] = t["id"]
        await db.tasks.insert_one(t)
    # risolvi depends_on da chiavi locali a id
    for spec in sk["tasks"]:
        deps = [key_to_id[d] for d in spec["depends_on"]]
        await db.tasks.update_one({"id": key_to_id[spec["key"]]}, {"$set": {"depends_on": deps}})
    await _audit(db, org_id=org_id, actor=user_id, action="CREATE_PLAN", entity_type="plan",
                 entity_id=plan["id"], details={"objective_type": sk["objective_type"], "tasks": len(sk["tasks"])})
    plan.pop("_id", None)
    return {"plan": plan, "requires_clarification": False}


# --------- Execution unica per versione (idempotente) ---------
async def create_execution(db, plan, actor="system"):
    ex = {
        "id": new_id("exec"), "organization_id": plan["organization_id"], "plan_id": plan["id"],
        "plan_version": plan["version"], "execution_status": "IN_ESECUZIONE",
        "deliverable_status": None, "action_status": "NON_RICHIESTA",
        "real_cost": 0.0, "approved_cap": plan.get("approved_cap", 0.0),
        "created_by": actor, "updated_by": actor, "created_at": now_iso(), "updated_at": now_iso(),
        "change_history": [], "mode": "SIMULAZIONE",
    }
    try:
        await db.executions.insert_one(ex)
        await _audit(db, org_id=plan["organization_id"], actor=actor, action="CREATE_EXECUTION",
                     entity_type="execution", entity_id=ex["id"],
                     details={"plan_id": plan["id"], "version": plan["version"]})
        ex.pop("_id", None)
        return ex
    except Exception:
        existing = await db.executions.find_one({"plan_id": plan["id"], "plan_version": plan["version"]}, {"_id": 0})
        return existing


async def _get_execution(db, plan):
    return await db.executions.find_one({"plan_id": plan["id"], "plan_version": plan["version"]}, {"_id": 0})


# --------- Approvazioni ---------
async def _deps_all(db, task, field_pred):
    for did in task.get("depends_on", []):
        d = await db.tasks.find_one({"id": did})
        if not d or not field_pred(d):
            return False
    return True


async def refresh_gates(db, plan_id):
    """Promuove i task: IN_ATTESA->PIANIFICATA (deps approvate), PIANIFICATA->IN_CODA (deps COMPLETATA).
    Propaga BLOCCATA/FALLITA ai dipendenti come SALTATA."""
    plan = await db.plans.find_one({"id": plan_id})
    if plan and plan.get("stopped"):
        return
    tasks = await db.tasks.find({"plan_id": plan_id}).to_list(500)
    by_id = {t["id"]: t for t in tasks}
    for t in tasks:
        # propagazione: se una dipendenza è FALLITA/BLOCCATA/SALTATA -> SALTATA
        if t["task_status"] in ("IN_ATTESA_APPROVAZIONE", "PIANIFICATA", "IN_CODA"):
            if any(by_id.get(d, {}).get("task_status") in ("FALLITA", "BLOCCATA", "SALTATA") for d in t.get("depends_on", [])):
                await set_task_status(db, t, "SALTATA", {"warnings": t.get("warnings", []) + ["Dipendenza non completata"]})
                await _audit(db, org_id=t["organization_id"], actor="system", action="TASK_SKIPPED",
                             entity_type="task", entity_id=t["id"], reason="dipendenza fallita/bloccata")
                continue
        if not t.get("approved"):
            continue
        deps_approved = await _deps_all(db, t, lambda d: d.get("approved"))
        deps_done = await _deps_all(db, t, lambda d: d.get("task_status") == "COMPLETATA")
        if t["task_status"] == "IN_ATTESA_APPROVAZIONE" and deps_approved:
            await set_task_status(db, t, "PIANIFICATA")
        if t["task_status"] == "PIANIFICATA" and deps_done:
            await set_task_status(db, t, "IN_CODA")


async def approve_plan(db, plan_id, actor):
    plan = await db.plans.find_one({"id": plan_id})
    if not plan:
        return None
    await db.tasks.update_many({"plan_id": plan_id}, {"$set": {"approved": True, "updated_at": now_iso()}})
    await db.plans.update_one({"id": plan_id}, {"$set": {"plan_status": "APPROVATO", "updated_at": now_iso()}})
    plan["plan_status"] = "APPROVATO"
    ex = await create_execution(db, plan, actor)
    await refresh_gates(db, plan_id)
    await _audit(db, org_id=plan["organization_id"], actor=actor, action="APPROVE_PLAN",
                 entity_type="plan", entity_id=plan_id, details={"execution_id": ex["id"]})
    return {"plan_id": plan_id, "execution_id": ex["id"], "plan_status": "APPROVATO"}


async def approve_task(db, plan_id, task_id, actor):
    plan = await db.plans.find_one({"id": plan_id})
    task = await db.tasks.find_one({"id": task_id, "plan_id": plan_id})
    if not plan or not task:
        return None
    await db.tasks.update_one({"id": task_id}, {"$set": {"approved": True, "updated_at": now_iso()}})
    ex = await create_execution(db, plan, actor)
    total = await db.tasks.count_documents({"plan_id": plan_id})
    approved = await db.tasks.count_documents({"plan_id": plan_id, "approved": True})
    new_ps = "APPROVATO" if approved == total else "APPROVATO_PARZIALE"
    await db.plans.update_one({"id": plan_id}, {"$set": {"plan_status": new_ps, "updated_at": now_iso()}})
    await refresh_gates(db, plan_id)
    await _audit(db, org_id=plan["organization_id"], actor=actor, action="APPROVE_TASK",
                 entity_type="task", entity_id=task_id, details={"plan_status": new_ps, "execution_id": ex["id"]})
    return {"plan_id": plan_id, "task_id": task_id, "plan_status": new_ps, "execution_id": ex["id"]}


async def reject_task(db, plan_id, task_id, actor, reason):
    """Rifiuta un task con motivazione obbligatoria. Non cancella risultati gia' prodotti:
    imposta BLOCCATA e propaga SALTATA ai dipendenti via refresh_gates. Task in stato
    terminale (COMPLETATA/FALLITA/...) non e' rifiutabile (preserva deliverable prodotti)."""
    if not reason or not str(reason).strip():
        raise ValueError("Motivazione obbligatoria per il rifiuto")
    task = await db.tasks.find_one({"id": task_id, "plan_id": plan_id})
    if not task:
        return None
    if task["task_status"] in TERMINAL:
        raise InvalidTransition(
            f"Task in stato terminale {task['task_status']}: rifiuto non consentito (risultati preservati)")
    reason = str(reason).strip()
    await set_task_status(db, task, "BLOCCATA",
                          {"warnings": task.get("warnings", []) + [f"Rifiutata: {reason}"],
                           "rejected_reason": reason})
    await refresh_gates(db, plan_id)
    await _audit(db, org_id=task["organization_id"], actor=actor, action="REJECT_TASK",
                 entity_type="task", entity_id=task_id, reason=reason)
    return {"task_id": task_id, "task_status": "BLOCCATA", "reason": reason}


# --------- Budget ---------
async def budget_check(db, org_id, execution, next_cost):
    if execution["real_cost"] + next_cost > execution.get("approved_cap", 0.0) + 1e-9:
        return False, "tetto approvato insufficiente"
    budget = await db.budgets.find_one({"id": org_id}) or {}
    limit = budget.get("general_limit", 0.0)
    spent = 0.0
    async for e in db.executions.find({"organization_id": org_id}, {"_id": 0, "real_cost": 1}):
        spent += e.get("real_cost", 0.0)
    if limit and spent + next_cost > limit + 1e-9:
        return False, "budget generale insufficiente"
    return True, ""


# --------- Claim atomico + lease ---------
async def claim_task(db, task_id):
    now = datetime.now(timezone.utc)
    exp = (now + timedelta(seconds=LEASE_SECONDS)).isoformat()
    owner = new_id("worker")
    claimed = await db.tasks.find_one_and_update(
        {"id": task_id, "task_status": "IN_CODA"},
        {"$set": {"task_status": "IN_ESECUZIONE", "lease_owner": owner,
                  "lease_expires_at": exp, "started_at": now_iso(), "updated_at": now_iso()},
         "$inc": {"attempt": 1}},
        return_document=True,
    )
    if not claimed:
        return None
    await db.worker_leases.update_one(
        {"task_id": task_id},
        {"$set": {"task_id": task_id, "plan_id": claimed["plan_id"], "owner": owner,
                  "acquired_at": now_iso(), "expires_at": exp, "heartbeat_at": now_iso()}},
        upsert=True,
    )
    claimed.pop("_id", None)
    return claimed


async def renew_lease(db, task_id):
    exp = (datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)).isoformat()
    await db.tasks.update_one({"id": task_id}, {"$set": {"lease_expires_at": exp}})
    await db.worker_leases.update_one({"task_id": task_id},
                                      {"$set": {"expires_at": exp, "heartbeat_at": now_iso()}})
    return exp


# --------- Esecuzione simulata (idempotente, costo una-volta-per-tentativo) ---------
async def _sim_cost(task):
    return round(float(task.get("inputs", {}).get("cost", 0.005)), 6)


async def _execute(db, task, resume=False):
    plan = await db.plans.find_one({"id": task["plan_id"]})
    if plan and plan.get("stopped"):
        return {"task_id": task["id"], "result": "stopped"}
    execution = await db.executions.find_one({"plan_id": task["plan_id"], "plan_version": task["version"]})
    org_id = task["organization_id"]
    attempt = task["attempt"]
    next_cost = await _sim_cost(task)

    ok, why = await budget_check(db, org_id, execution, next_cost if task.get("last_costed_attempt", 0) < attempt else 0.0)
    if not ok:
        await set_task_status(db, task, "BLOCCATA", {"warnings": task.get("warnings", []) + [f"Budget: {why}"]})
        await _audit(db, org_id=org_id, actor="system", action="TASK_BLOCKED_BUDGET",
                     entity_type="task", entity_id=task["id"], status="ERROR", reason=why)
        await refresh_gates(db, task["plan_id"])
        return {"task_id": task["id"], "result": "budget_blocked"}

    # Costo registrato UNA sola volta per tentativo (anche se poi invalido o fallisce)
    if task.get("last_costed_attempt", 0) < attempt:
        await db.tasks.update_one({"id": task["id"]},
                                  {"$inc": {"cost": next_cost}, "$set": {"last_costed_attempt": attempt}})
        await db.executions.update_one({"id": execution["id"]}, {"$inc": {"real_cost": next_cost}})
        task["cost"] = task.get("cost", 0.0) + next_cost
        task["last_costed_attempt"] = attempt
        await _audit(db, org_id=org_id, actor="system", action="TASK_COST",
                     entity_type="task", entity_id=task["id"], details={"attempt": attempt, "cost": next_cost})

    sim = task.get("inputs", {}).get("simulate")
    crash = task.get("inputs", {}).get("crash")

    # Crash simulato PRIMA della persistenza del deliverable (solo prima esecuzione)
    if crash == "before_deliverable" and not resume:
        return {"task_id": task["id"], "result": "crash_before"}  # task resta IN_ESECUZIONE

    if sim == "fail":
        # Fallimento: retry fino a MAX_ATTEMPTS, poi FALLITA (nessun loop infinito)
        if attempt >= MAX_ATTEMPTS:
            await set_task_status(db, task, "FALLITA", {"warnings": task.get("warnings", []) + ["Max tentativi superato"]})
            await _audit(db, org_id=org_id, actor="system", action="TASK_FAILED",
                         entity_type="task", entity_id=task["id"], status="ERROR", reason="max tentativi")
            await refresh_gates(db, task["plan_id"])
            return {"task_id": task["id"], "result": "failed"}
        await set_task_status(db, task, "IN_CODA", {"lease_owner": None})
        await _audit(db, org_id=org_id, actor="system", action="TASK_RETRY",
                     entity_type="task", entity_id=task["id"], details={"attempt": attempt})
        return {"task_id": task["id"], "result": "retry"}

    # Produzione (simulata, deterministica) + validazione + versionamento atomico.
    org_profile = await db.organizations.find_one({"id": org_id}, {"_id": 0}) or {}
    if task.get("confirmed") and task.get("deliverable_id"):
        deliverable = await db.deliverables.find_one({"id": task["deliverable_id"]}, {"_id": 0})
    else:
        override = task.get("inputs", {}).get("deliverable_override")
        content = override if override is not None else produce_deliverable(
            task["deliverable_type"], task, plan, org_profile)
        validation = validate_deliverable(task["deliverable_type"], content)
        deliverable = await create_deliverable_version(
            db, org_id=org_id, plan=plan, task=task, content=content,
            validation=validation, agent_id=task.get("agent_id"))
        await db.tasks.update_one(
            {"id": task["id"]},
            {"$set": {"deliverable_id": deliverable["id"], "confirmed": True,
                      "warnings": task.get("warnings", []) + validation.get("warnings", [])}})
        task["confirmed"] = True
        # Revisori NON distruttivi (Compliance + Auditor): producono record persistiti,
        # non modificano né sostituiscono il deliverable.
        await review_deliverable(db, deliverable, task)
    dstatus = deliverable["status"]

    # Crash simulato DOPO la persistenza (deliverable confermato) — task resta IN_ESECUZIONE
    if crash == "after_deliverable" and not resume:
        return {"task_id": task["id"], "result": "crash_after"}

    final = "COMPLETATA"  # tecnica; il deliverable puo' essere BLOCCATO
    await set_task_status(db, task, final, {"finished_at": now_iso(), "lease_owner": None})
    await db.worker_leases.delete_one({"task_id": task["id"]})
    await _audit(db, org_id=org_id, actor="system", action="TASK_COMPLETED",
                 entity_type="task", entity_id=task["id"], details={"deliverable_status": dstatus})
    await refresh_gates(db, task["plan_id"])
    await _maybe_finish_plan(db, task["plan_id"])
    return {"task_id": task["id"], "result": "completed", "deliverable_status": dstatus}


async def process_task(db, task_id):
    task = await claim_task(db, task_id)
    if not task:
        return None
    return await _execute(db, task, resume=False)


async def run_ready_tasks(db, plan_id):
    await refresh_gates(db, plan_id)
    plan = await db.plans.find_one({"id": plan_id})
    if plan and plan.get("stopped"):
        return {"processed": 0, "stopped": True}
    processed = []
    for _ in range(50):
        t = await db.tasks.find_one({"plan_id": plan_id, "task_status": "IN_CODA"})
        if not t:
            break
        r = await process_task(db, t["id"])
        processed.append(r)
        await refresh_gates(db, plan_id)
    await _maybe_finish_plan(db, plan_id)
    return {"processed": len(processed), "results": processed}


async def _maybe_finish_plan(db, plan_id):
    tasks = await db.tasks.find({"plan_id": plan_id}).to_list(500)
    if any(t["task_status"] not in TERMINAL for t in tasks):
        return
    blocked_deliv = await db.deliverables.count_documents({"plan_id": plan_id, "status": "BLOCCATO", "is_current": True})
    # Un piano NON e' completato con successo se qualche task e' FALLITA/BLOCCATA/SALTATA
    # o se un deliverable obbligatorio e' BLOCCATO: UI deve dire "terminato, non completato".
    blocked_task = any(t["task_status"] in ("FALLITA", "BLOCCATA", "SALTATA") for t in tasks)
    is_blocked = bool(blocked_deliv) or blocked_task
    ps = "BLOCCATO" if is_blocked else "COMPLETATO"
    await db.plans.update_one({"id": plan_id}, {"$set": {"plan_status": ps, "updated_at": now_iso()}})
    ex = await db.executions.find_one({"plan_id": plan_id})
    if ex:
        dstatus = "BLOCCATO" if is_blocked else "COMPLETATO"
        await db.executions.update_one({"id": ex["id"]}, {"$set": {
            "execution_status": "COMPLETATA", "deliverable_status": dstatus, "updated_at": now_iso()}})


# --------- Arresto e recovery ---------
async def stop_plan(db, plan_id, actor):
    await db.plans.update_one({"id": plan_id}, {"$set": {"stopped": True, "updated_at": now_iso()}})
    await _audit(db, org_id=(await db.plans.find_one({"id": plan_id}))["organization_id"],
                 actor=actor, action="STOP_PLAN", entity_type="plan", entity_id=plan_id)
    return {"plan_id": plan_id, "stopped": True}


async def _acquire_lock(db, name, ttl=120):
    """Lock persistente per leader election: garantisce che un solo processo esegua la
    sezione critica. Riacquisibile solo se scaduto. Ritorna l'owner token o None."""
    now_s = datetime.now(timezone.utc).isoformat()
    exp = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
    owner = new_id("lock")
    doc = await db.m2_locks.find_one_and_update(
        {"_id": name, "expires_at": {"$lte": now_s}},
        {"$set": {"owner": owner, "expires_at": exp, "acquired_at": now_s}},
        return_document=True,
    )
    if doc:
        return owner
    try:
        await db.m2_locks.insert_one({"_id": name, "owner": owner, "expires_at": exp, "acquired_at": now_s})
        return owner
    except Exception:
        return None


async def _release_lock(db, name, owner):
    await db.m2_locks.delete_one({"_id": name, "owner": owner})


async def recover_m2(db):
    """Resume sicuro e IDEMPOTENTE dopo riavvio, protetto da lock persistente
    (leader election): se piu' processi backend partono insieme, solo uno recupera.
    - deliverable confermato -> COMPLETATA (nessun ricalcolo costi).
    - altrimenti -> riprende lo STESSO tentativo (costo non raddoppiato)."""
    owner = await _acquire_lock(db, "m2_recover")
    if not owner:
        return {"recovered": 0, "skipped": True, "reason": "lock non acquisito"}
    try:
        return await _recover_m2_inner(db)
    finally:
        await _release_lock(db, "m2_recover", owner)


async def _recover_m2_inner(db):
    now = datetime.now(timezone.utc)
    stuck = await db.tasks.find({"task_status": "IN_ESECUZIONE"}).to_list(500)
    recovered = 0
    for t in stuck:
        exp = t.get("lease_expires_at")
        expired = True
        if exp:
            try:
                expired = datetime.fromisoformat(exp) <= now
            except Exception:
                expired = True
        if not expired:
            continue
        if t.get("confirmed"):
            await set_task_status(db, t, "COMPLETATA", {"finished_at": now_iso(), "lease_owner": None})
            await db.worker_leases.delete_one({"task_id": t["id"]})
            await _audit(db, org_id=t["organization_id"], actor="system", action="TASK_RESUME_CONFIRMED",
                         entity_type="task", entity_id=t["id"])
            await refresh_gates(db, t["plan_id"])
            await _maybe_finish_plan(db, t["plan_id"])
        else:
            await _audit(db, org_id=t["organization_id"], actor="system", action="TASK_RESUME",
                         entity_type="task", entity_id=t["id"], details={"attempt": t["attempt"]})
            await _execute(db, t, resume=True)
        recovered += 1
    return {"recovered": recovered}


# ===================== ROUTER (usa db globale, RBAC server-side) =====================
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..db import db as _global_db
from ..deps import get_current_user, require_roles
from ..models import base_record
from ..config import DEFAULT_ORG_ID

router = APIRouter(prefix="/m2", tags=["m2-engine"])


def _authz_org(record, user):
    """RBAC/tenant server-side: verifica che il record appartenga all'organizzazione
    dell'utente. Mai fidarsi di stato/ruolo lato frontend."""
    rec_org = record.get("organization_id")
    usr_org = user.get("organization_id")
    if rec_org and usr_org and rec_org != usr_org:
        raise HTTPException(403, "Accesso negato: organizzazione non corrispondente")


async def _load_plan_authz(plan_id, user):
    plan = await _global_db.plans.find_one({"id": plan_id})
    if not plan:
        raise HTTPException(404, "Piano non trovato")
    _authz_org(plan, user)
    return plan


async def _assert_simulation(org_id):
    """M2 opera esclusivamente in SIMULAZIONE: blocco sicuro se la modalità non è simulata."""
    s = await _global_db.settings.find_one({"id": org_id}) or {}
    if s.get("ai_real_mode"):
        raise HTTPException(409, "Strumento di SIMULAZIONE: disponibile solo in modalità SIMULAZIONE (modalità attuale: REALE).")


class PlanBody(BaseModel):
    text: str


class RejectBody(BaseModel):
    reason: str


@router.post("/plans")
async def http_create_plan(body: PlanBody, user: dict = Depends(require_roles("OPERATORE", "ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    await _assert_simulation(org_id)
    goal_id = new_id("goal")
    await _global_db.goals.insert_one({**base_record(org_id, user["id"]), "id": goal_id,
                                       "text": body.text, "status": "IN_APPROVAZIONE", "mode": "SIMULAZIONE"})
    res = await create_plan(_global_db, org_id, user["id"], goal_id, body.text)
    if res.get("requires_clarification"):
        return {"requires_clarification": True, "objective_type": res["objective_type"]}
    return res


@router.get("/plans/{plan_id}")
async def http_get_plan(plan_id: str, user: dict = Depends(get_current_user)):
    plan = await _load_plan_authz(plan_id, user)
    plan.pop("_id", None)
    tasks = await _global_db.tasks.find({"plan_id": plan_id}, {"_id": 0}).sort("seq", 1).to_list(500)
    ex = await _get_execution(_global_db, plan)
    return {"plan": plan, "tasks": tasks, "execution": ex}


@router.get("/plans")
async def http_list_plans(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    plans = await _global_db.plans.find(
        {"organization_id": org_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"plans": plans, "mode": "SIMULAZIONE"}


@router.get("/stats")
async def http_m2_stats(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    db = _global_db
    plans = await db.plans.find({"organization_id": org_id}, {"_id": 0, "plan_status": 1}).to_list(500)
    by_status = {}
    for p in plans:
        by_status[p["plan_status"]] = by_status.get(p["plan_status"], 0) + 1
    valid = await db.deliverables.count_documents({"organization_id": org_id, "is_current": True, "valid": True})
    blocked = await db.deliverables.count_documents({"organization_id": org_id, "is_current": True, "status": "BLOCCATO"})
    high_compliance = await db.reviews.count_documents(
        {"organization_id": org_id, "review_type": "compliance", "severity": "high"})
    return {
        "plans_total": len(plans), "plans_by_status": by_status,
        "deliverables_valid": valid, "deliverables_blocked": blocked,
        "reviews_high_compliance": high_compliance, "mode": "SIMULAZIONE",
    }


@router.get("/plans/{plan_id}/deliverables")
async def http_list_deliverables(plan_id: str, user: dict = Depends(get_current_user)):
    await _load_plan_authz(plan_id, user)
    delivs = await _global_db.deliverables.find(
        {"plan_id": plan_id}, {"_id": 0}).sort([("task_id", 1), ("version", 1)]).to_list(500)
    return {"deliverables": delivs, "mode": "SIMULAZIONE"}


@router.get("/plans/{plan_id}/reviews")
async def http_list_reviews(plan_id: str, user: dict = Depends(get_current_user)):
    await _load_plan_authz(plan_id, user)
    rows = await _global_db.reviews.find({"plan_id": plan_id}, {"_id": 0}).sort("created_at", 1).to_list(500)
    return {"reviews": rows, "mode": "SIMULAZIONE"}


@router.post("/plans/{plan_id}/tasks/{task_id}/review")
async def http_review_task(plan_id: str, task_id: str,
                           user: dict = Depends(require_roles("ADMIN", "APPROVATORE"))):
    plan = await _load_plan_authz(plan_id, user)
    await _assert_simulation(plan.get("organization_id"))
    task = await _global_db.tasks.find_one({"id": task_id, "plan_id": plan_id})
    if not task:
        raise HTTPException(404, "Task non trovato")
    deliv = await _global_db.deliverables.find_one(
        {"plan_id": plan_id, "task_id": task_id, "is_current": True}, {"_id": 0})
    if not deliv:
        raise HTTPException(409, "Nessun deliverable corrente da revisionare")
    res = await review_deliverable(_global_db, deliv, task, actor=user["email"])
    return {"reviews": res, "mode": "SIMULAZIONE"}


@router.post("/plans/{plan_id}/approve")
async def http_approve_plan(plan_id: str, user: dict = Depends(require_roles("APPROVATORE", "ADMIN"))):
    await _load_plan_authz(plan_id, user)
    r = await approve_plan(_global_db, plan_id, user["email"])
    if not r:
        raise HTTPException(404, "Piano non trovato")
    return r


@router.post("/plans/{plan_id}/tasks/{task_id}/approve")
async def http_approve_task(plan_id: str, task_id: str, user: dict = Depends(require_roles("APPROVATORE", "ADMIN"))):
    await _load_plan_authz(plan_id, user)
    r = await approve_task(_global_db, plan_id, task_id, user["email"])
    if not r:
        raise HTTPException(404, "Task non trovato")
    return r


@router.post("/plans/{plan_id}/tasks/{task_id}/reject")
async def http_reject_task(plan_id: str, task_id: str, body: RejectBody,
                           user: dict = Depends(require_roles("ADMIN", "APPROVATORE"))):
    await _load_plan_authz(plan_id, user)
    if not body.reason or not body.reason.strip():
        raise HTTPException(422, "Motivazione obbligatoria per il rifiuto")
    try:
        r = await reject_task(_global_db, plan_id, task_id, user["email"], body.reason)
    except InvalidTransition as e:
        raise HTTPException(409, str(e))
    if not r:
        raise HTTPException(404, "Task non trovato")
    return r


@router.post("/plans/{plan_id}/stop")
async def http_stop_plan(plan_id: str, user: dict = Depends(require_roles("ADMIN"))):
    await _load_plan_authz(plan_id, user)
    return await stop_plan(_global_db, plan_id, user["email"])


@router.post("/plans/{plan_id}/tick")
async def http_tick(plan_id: str, user: dict = Depends(require_roles("OPERATORE", "APPROVATORE", "ADMIN"))):
    plan = await _load_plan_authz(plan_id, user)
    await _assert_simulation(plan.get("organization_id"))
    res = await run_ready_tasks(_global_db, plan_id)
    return {**res, "mode": "SIMULAZIONE", "simulation_tool": True}
