"""Milestone 2 — Blocco 4: motore approvazioni/execution/task/lease/resume (SIMULAZIONE).
Le funzioni core accettano `db` (testabilità deterministica); il router usa il db globale.
Nessuna chiamata reale, nessuna azione esterna. Costi/deliverable simulati e idempotenti."""
import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from ..models import now_iso, new_id
from .models import new_plan, new_task
from .planner import plan_skeleton, build_dag, validate_dag, topological_order
from .agents_registry import select_agent, AGENT_CONTRACTS, assert_action_allowed, ContractError
from .deliverables import produce_deliverable, validate_deliverable, create_deliverable_version
from .reviews import review_deliverable
from ..domains.estimator import estimate_for_agents, PRICE_PER_TOKEN
from .real_content import REAL_ELIGIBLE_TYPES, check_readiness, generate_editorial_plan, generate_social_content
from .real_content_creator import CONTENT_ITEM_TYPE, execute_content_item_task, resume_blocked_content_item_tasks
from .deliverable_review import (
    DecisionError, decide_item, enrich_multi_item_deliverables_with_decisions,
    preview_edit_cost, apply_edit,
)

logger = logging.getLogger("actelya.m2")

MAX_ATTEMPTS = int(os.environ.get("M2_MAX_ATTEMPTS", "3"))
LEASE_SECONDS = int(os.environ.get("M2_LEASE_SECONDS", "30"))
# Intervallo del worker di avvio automatico (poll di riserva/resilienza a un
# riavvio — il trigger primario e' immediato, alla stessa approvazione).
AUTO_DISPATCH_POLL_SECONDS = int(os.environ.get("M2_AUTO_DISPATCH_POLL_SECONDS", "5"))

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
async def create_plan(db, org_id, user_id, goal_id, goal_text, *, task_specs=None):
    """task_specs (opzionale): quando fornito da brain/service.py (SpecTask
    [{key, name, deliverable_type, depends_on}], stessa forma di
    planner.decompose()), SOSTITUISCE la classificazione/scomposizione
    indipendente di M2 (planner.classify_objective + decompose): il piano
    riflette ESATTAMENTE la squadra gia' selezionata dal brain
    (agent_selector.select_agents), mai una riclassificazione del solo testo
    che potrebbe aggiungere task estranei (es. l'intera campagna quando e'
    stato chiesto solo un flyer). objective_type/intent restano comunque
    quelli di plan_skeleton(goal_text): sono solo un'etichetta descrittiva
    del piano, non influenzano quali task vengono creati in questo ramo.
    Un task_specs vuoto e' legittimo (tutte le capability richieste sono
    REALI — video_reel/flyer_image — e vengono aggiunte subito dopo da
    brain/service.py come task collegati a un progetto reale, non da qui):
    in quel caso qui NON si richiede chiarimento, a differenza del percorso
    testuale invariato (task_specs=None) dove un piano senza alcun task resta
    un errore di classificazione."""
    sk = plan_skeleton(goal_text)
    if task_specs is not None:
        validation = validate_dag(task_specs)
        topo = topological_order(task_specs) if validation["ok"] else []
        sk = {
            **sk, "tasks": task_specs, "dag": build_dag(task_specs),
            "topo_order": topo, "valid": validation["ok"], "validation_errors": validation["errors"],
            "requires_clarification": not validation["ok"],
        }
    if sk["requires_clarification"] or not sk["valid"] or (task_specs is None and not sk["tasks"]):
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


async def _current_approval_mode(db, org_id) -> str:
    """Modalita' REALE/SIMULAZIONE dell'organizzazione nel momento esatto in cui
    un'approvazione viene concessa: stampata sul task (campo 'approved_mode'),
    MAI ricalcolata dopo — un'approvazione data mentre l'org era in SIMULAZIONE
    non autorizza mai una spesa reale, anche se l'org passa REALE in seguito
    (vedi real_content.py). Un task senza questo campo (piano approvato PRIMA
    di questa funzionalita') e' trattato allo stesso modo: mai REALE."""
    settings = await db.settings.find_one({"id": org_id}) or {}
    return "REALE" if settings.get("ai_real_mode") else "SIMULAZIONE"


async def approve_plan(db, plan_id, actor):
    plan = await db.plans.find_one({"id": plan_id})
    if not plan:
        return None
    approved_mode = await _current_approval_mode(db, plan["organization_id"])
    # auto_dispatch_requested_at: marcatore PERSISTITO, mai retroattivo — solo
    # le approvazioni che passano da QUESTO codice lo impostano. E' la sola
    # cosa che rende un task idoneo all'avvio automatico (vedi
    # auto_dispatch_worker_loop): un piano approvato prima di questa
    # correzione non lo ha mai e resta quindi escluso per sempre, anche dopo
    # un riavvio del backend — nessuna esecuzione retroattiva della vecchia coda.
    await db.tasks.update_many({"plan_id": plan_id},
                               {"$set": {"approved": True, "approved_mode": approved_mode,
                                        "auto_dispatch_requested_at": now_iso(), "updated_at": now_iso()}})
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
    approved_mode = await _current_approval_mode(db, plan["organization_id"])
    await db.tasks.update_one({"id": task_id},
                              {"$set": {"approved": True, "approved_mode": approved_mode,
                                       "auto_dispatch_requested_at": now_iso(), "updated_at": now_iso()}})
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
    """Controllo 'leggi poi decidi' (non atomico): mantenuto invariato per
    compatibilita' con chiamanti esistenti. Per il tetto approvato di
    un'execution, preferire _reserve_execution_budget (atomico) — vedi
    _execute(), che lo usa al posto di questo per la propria decisione."""
    if execution["real_cost"] + next_cost > execution.get("approved_cap", 0.0) + 1e-9:
        return False, "tetto approvato insufficiente"
    ok, why = await _general_budget_check(db, org_id, next_cost, already_reserved=False)
    return ok, why


async def _reserve_execution_budget(db, execution_id, amount):
    """Riserva atomicamente 'amount' sul tetto approvato dell'execution: UN
    solo comando find_one_and_update con filtro condizionale sul documento
    stesso, mai un 'leggi poi decidi' in due passaggi separati — cosi' due
    esecuzioni concorrenti sulla STESSA execution (es. il worker di poll e
    una chiamata /tick manuale, su due task diversi dello stesso piano) non
    possono entrambe superare la verifica sullo stesso tetto residuo: solo
    una riesce ad incrementare real_cost, l'altra vede il filtro fallire e
    riceve None. Ritorna l'execution AGGIORNATA se la riserva riesce, None
    se il tetto residuo non basta (nessuna scrittura in quel caso)."""
    if amount <= 0:
        return await db.executions.find_one({"id": execution_id})
    return await db.executions.find_one_and_update(
        {"id": execution_id,
         "$expr": {"$lte": [{"$add": ["$real_cost", amount]}, {"$add": ["$approved_cap", 1e-9]}]}},
        {"$inc": {"real_cost": amount}},
        return_document=True,
    )


async def _release_execution_budget(db, execution_id, amount):
    """Rilascia una riserva fatta con _reserve_execution_budget quando il
    controllo successivo (es. budget generale org-wide) blocca comunque
    l'esecuzione — mai una riserva 'fantasma' rimasta a occupare il tetto
    senza che la chiamata corrispondente sia mai partita."""
    if amount > 0:
        await db.executions.update_one({"id": execution_id}, {"$inc": {"real_cost": -amount}})


async def _apply_actual_cost_delta(db, execution, task, delta):
    """Applica la differenza fra il costo EFFETTIVO (noto solo DOPO la
    risposta reale, dai token davvero restituiti) e la stima riservata PRIMA
    della chiamata (next_cost/_sim_cost). LIMITE DICHIARATO: la riserva
    atomica (_reserve_execution_budget) protegge solo la DECISIONE di
    partire con la chiamata, sulla base della stima — non puo' proteggere
    contro un consumo di token superiore al previsto, perche' quel numero è
    noto solo a chiamata gia' avvenuta e gia' addebitata (non annullabile a
    posteriori). Se il totale risultante supera il tetto approvato del
    piano, il superamento non resta un delta silenzioso: l'execution viene
    marcata 'budget_overrun_detected' cosi' che _execute() blocchi ogni
    ULTERIORE task dello stesso piano finche' un umano non decide
    esplicitamente (mai un tetto aumentato automaticamente). Ritorna un
    avviso testuale se e' stato rilevato un superamento in QUESTA chiamata,
    altrimenti None."""
    if not delta:
        return None
    await db.tasks.update_one({"id": task["id"]}, {"$inc": {"cost": delta}})
    updated = await db.executions.find_one_and_update(
        {"id": execution["id"]}, {"$inc": {"real_cost": delta}}, return_document=True)
    if updated is None:
        return None
    execution["real_cost"] = updated.get("real_cost", 0.0)
    cap = updated.get("approved_cap", 0.0)
    if updated.get("real_cost", 0.0) > cap + 1e-9 and not updated.get("budget_overrun_detected"):
        await db.executions.update_one({"id": execution["id"]}, {"$set": {"budget_overrun_detected": True}})
        return (f"Budget: costo reale ({updated['real_cost']:.6f} USD) ha superato il tetto approvato del "
                f"piano ({cap:.6f} USD) dopo la riconciliazione post-chiamata (stima pre-chiamata insufficiente "
                "rispetto ai token realmente consumati). Nessuna nuova chiamata reale su questo piano finche' un "
                "umano non decide esplicitamente: il tetto non viene aumentato automaticamente.")
    return None


async def _general_budget_check(db, org_id, next_cost, *, already_reserved: bool):
    """Budget GENERALE (org-wide, sommato su TUTTE le execution dell'org):
    verifica best-effort, NON atomica multi-documento — MongoDB non offre
    una transazione cross-documento senza replica set/sessioni, fuori
    perimetro qui. Una corsa fra esecuzioni concorrenti su EXECUTION DIVERSE
    della stessa organizzazione resta teoricamente possibile: dichiarato
    espressamente, non presentato come un tetto rigido (vedi rapporto).
    'already_reserved' indica se 'next_cost' e' gia' stato sommato altrove
    (es. da _reserve_execution_budget, gia' committato sull'execution prima
    di questa chiamata) — in tal caso non va sommato una seconda volta al
    totale letto da db.executions."""
    budget = await db.budgets.find_one({"id": org_id}) or {}
    limit = budget.get("general_limit", 0.0)
    if not limit:
        return True, ""
    spent = 0.0
    async for e in db.executions.find({"organization_id": org_id}, {"_id": 0, "real_cost": 1}):
        spent += e.get("real_cost", 0.0)
    proiettato = spent if already_reserved else spent + next_cost
    if proiettato > limit + 1e-9:
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

    # Un precedente task dello STESSO piano ha gia' fatto emergere un
    # superamento del tetto in fase di riconciliazione costo stimato/reale
    # (vedi _apply_actual_cost_delta): mai una nuova chiamata reale finche'
    # un umano non decide, mai un blocco silenzioso — il motivo resta
    # esplicito nell'avviso.
    if execution and execution.get("budget_overrun_detected"):
        await set_task_status(db, task, "BLOCCATA", {"warnings": task.get("warnings", []) + [
            "Budget: un task precedente di questo piano ha gia' superato il tetto approvato in fase di "
            "riconciliazione costo reale — nessuna nuova chiamata avviata finche' un umano non decide "
            "esplicitamente (il tetto non viene aumentato automaticamente)."],
            "blocked_reason_code": "budget_overrun_rilevato"})
        await _audit(db, org_id=org_id, actor="system", action="TASK_BLOCKED_BUDGET_OVERRUN",
                     entity_type="task", entity_id=task["id"], status="ERROR",
                     reason="budget_overrun_detected sull'execution del piano")
        await refresh_gates(db, task["plan_id"])
        return {"task_id": task["id"], "result": "budget_overrun_blocked"}

    attempt = task["attempt"]
    next_cost = await _sim_cost(task)

    # Costo registrato UNA sola volta per tentativo (anche se poi invalido o
    # fallisce). La riserva sul tetto approvato dell'execution e' ATOMICA
    # (_reserve_execution_budget: un solo find_one_and_update condizionale) —
    # mai una finestra 'leggi il tetto, poi decidi, poi scrivi' in cui due
    # esecuzioni concorrenti sulla stessa execution (task diversi dello
    # stesso piano, es. worker di poll + /tick manuale) potrebbero entrambe
    # vedere budget sufficiente sullo stesso tetto residuo.
    if task.get("last_costed_attempt", 0) < attempt:
        reserved = await _reserve_execution_budget(db, execution["id"], next_cost)
        if reserved is None:
            await set_task_status(db, task, "BLOCCATA", {"warnings": task.get("warnings", []) + [
                "Budget: tetto approvato insufficiente"]})
            await _audit(db, org_id=org_id, actor="system", action="TASK_BLOCKED_BUDGET",
                         entity_type="task", entity_id=task["id"], status="ERROR",
                         reason="tetto approvato insufficiente")
            await refresh_gates(db, task["plan_id"])
            return {"task_id": task["id"], "result": "budget_blocked"}
        execution = reserved
        # Budget GENERALE (org-wide): verifica best-effort, non atomica tra
        # execution diverse (limite noto e dichiarato, vedi
        # _general_budget_check) — controllata DOPO la riserva atomica sul
        # tetto del piano, che resta il gate principale.
        ok, why = await _general_budget_check(db, org_id, next_cost, already_reserved=True)
        if not ok:
            await _release_execution_budget(db, execution["id"], next_cost)  # nessuna spesa reale ancora avvenuta
            await set_task_status(db, task, "BLOCCATA", {"warnings": task.get("warnings", []) + [f"Budget: {why}"]})
            await _audit(db, org_id=org_id, actor="system", action="TASK_BLOCKED_BUDGET",
                         entity_type="task", entity_id=task["id"], status="ERROR", reason=why)
            await refresh_gates(db, task["plan_id"])
            return {"task_id": task["id"], "result": "budget_blocked"}
        await db.tasks.update_one({"id": task["id"]},
                                  {"$inc": {"cost": next_cost}, "$set": {"last_costed_attempt": attempt}})
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

    # Produzione: REALE (gateway LLM esistente) per editorial_plan/social_content
    # quando l'org e' in modalita' reale E il task e' stato approvato in quella
    # stessa modalita' (mai un'approvazione simulata a coprire una spesa reale,
    # mai un piano pre-esistente eseguito in reale automaticamente — vedi
    # real_content.py); altrimenti produzione simulata deterministica invariata.
    org_profile = await db.organizations.find_one({"id": org_id}, {"_id": 0}) or {}
    dtype = task["deliverable_type"]
    if task.get("confirmed") and task.get("deliverable_id"):
        deliverable = await db.deliverables.find_one({"id": task["deliverable_id"]}, {"_id": 0})
    elif dtype in REAL_ELIGIBLE_TYPES and task.get("approved_mode") == "REALE":
        readiness = await check_readiness(db, org_id)
        if not readiness.pronto:
            await set_task_status(db, task, "BLOCCATA", {
                "warnings": task.get("warnings", []) + [f"Percorso reale non disponibile: {'; '.join(readiness.motivi)}"]})
            await _audit(db, org_id=org_id, actor="system", action="TASK_BLOCKED_REAL_UNAVAILABLE",
                         entity_type="task", entity_id=task["id"], status="ERROR", reason="; ".join(readiness.motivi))
            await refresh_gates(db, task["plan_id"])
            return {"task_id": task["id"], "result": "real_unavailable"}

        goal = await db.goals.find_one({"id": task.get("goal_id")}, {"_id": 0, "text": 1}) or {}
        goal_text = goal.get("text", "")
        if dtype == "social_content":
            upstream = await db.deliverables.find_one(
                {"plan_id": task["plan_id"], "deliverable_type": "editorial_plan", "is_current": True}, {"_id": 0})
            outcome = await generate_social_content(db, org_id, readiness.ref, goal_text, (upstream or {}).get("content"))
        else:
            outcome = await generate_editorial_plan(db, org_id, readiness.ref, goal_text)

        if outcome.esito != "OK":
            # Se il provider ha comunque risposto (token noti), la chiamata e' stata
            # elaborata/addebitata: il costo reale va sempre registrato, anche su un
            # esito bloccato (mai una spesa reale non tracciata) — stesso principio
            # di domains/flyer.py. Sostituisce (delta) la stima simulata gia' caricata
            # sopra con il costo reale, mai una doppia contabilizzazione.
            if outcome.stima_costo_usd is not None:
                delta = round(outcome.stima_costo_usd - next_cost, 6)
                overrun_warning = await _apply_actual_cost_delta(db, execution, task, delta)
                if overrun_warning:
                    task["warnings"] = task.get("warnings", []) + [overrun_warning]
            if outcome.codice_errore == "esito_incerto":
                await set_task_status(db, task, "BLOCCATA", {"warnings": task.get("warnings", []) + [
                    "Esito incerto dal provider reale: richiede verifica manuale, nessun nuovo tentativo automatico "
                    "(evita chiamate duplicate su un esito non noto)."]})
                await _audit(db, org_id=org_id, actor="system", action="TASK_REAL_UNCERTAIN",
                             entity_type="task", entity_id=task["id"], status="ERROR", reason=outcome.messaggio,
                             details={"codice_errore": outcome.codice_errore, "stima_costo_usd": outcome.stima_costo_usd})
                await refresh_gates(db, task["plan_id"])
                return {"task_id": task["id"], "result": "real_uncertain"}
            if outcome.codice_errore == "rete":
                # Richiesta mai partita: sicuro ritentare (stesso principio di
                # llm_gateway.py), fino a MAX_ATTEMPTS come il ramo simulato
                # sim=="fail" -> poi FALLITA (nessun loop infinito).
                if attempt >= MAX_ATTEMPTS:
                    await set_task_status(db, task, "FALLITA", {"warnings": task.get("warnings", []) + [
                        f"Rete (max tentativi superato): {outcome.messaggio}"]})
                    await _audit(db, org_id=org_id, actor="system", action="TASK_REAL_FAILED",
                                 entity_type="task", entity_id=task["id"], status="ERROR", reason=outcome.messaggio,
                                 details={"codice_errore": outcome.codice_errore})
                    await refresh_gates(db, task["plan_id"])
                    return {"task_id": task["id"], "result": "failed"}
                await set_task_status(db, task, "IN_CODA", {"lease_owner": None, "warnings": task.get("warnings", []) + [
                    f"Rete: {outcome.messaggio}"]})
                await _audit(db, org_id=org_id, actor="system", action="TASK_REAL_RETRY",
                             entity_type="task", entity_id=task["id"],
                             details={"attempt": attempt, "codice_errore": outcome.codice_errore})
                return {"task_id": task["id"], "result": "retry"}
            # Ogni altro codice (config/permessi/modello/limite frequenza/risposta non
            # valida/sconosciuto): mai un retry cieco, richiede intervento umano.
            await set_task_status(db, task, "BLOCCATA", {"warnings": task.get("warnings", []) + [
                f"Generazione reale fallita ({outcome.codice_errore}): {outcome.messaggio}"]})
            await _audit(db, org_id=org_id, actor="system", action="TASK_REAL_FAILED",
                         entity_type="task", entity_id=task["id"], status="ERROR", reason=outcome.messaggio,
                         details={"codice_errore": outcome.codice_errore, "stima_costo_usd": outcome.stima_costo_usd})
            await refresh_gates(db, task["plan_id"])
            return {"task_id": task["id"], "result": "real_failed"}

        if outcome.stima_costo_usd is not None:
            delta = round(outcome.stima_costo_usd - next_cost, 6)
            overrun_warning = await _apply_actual_cost_delta(db, execution, task, delta)
            if overrun_warning:
                task["warnings"] = task.get("warnings", []) + [overrun_warning]
        content = outcome.content
        validation = validate_deliverable(dtype, content)
        deliverable = await create_deliverable_version(
            db, org_id=org_id, plan=plan, task=task, content=content, validation=validation,
            agent_id=task.get("agent_id"), mode="REALE",
            generation={"provider": outcome.provider, "modello_effettivo": outcome.modello_effettivo,
                        "input_tokens": outcome.input_tokens, "output_tokens": outcome.output_tokens,
                        "latenza_ms": outcome.latenza_ms, "stima_costo_usd": outcome.stima_costo_usd})
        await db.tasks.update_one(
            {"id": task["id"]},
            {"$set": {"deliverable_id": deliverable["id"], "confirmed": True,
                      "warnings": task.get("warnings", []) + validation.get("warnings", [])}})
        task["confirmed"] = True
        await review_deliverable(db, deliverable, task)
    elif dtype == CONTENT_ITEM_TYPE and task.get("approved_mode") == "REALE":
        # content_item non genera dentro M2 (a differenza di editorial_plan/
        # social_content sopra): il task e' un puntatore a uno o piu'
        # content_item del laboratorio Content Creator, che ha la propria
        # pipeline reale (real_content_creator.py la richiama, non la duplica).
        outcome = await execute_content_item_task(db, task)
        if outcome.stima_costo_usd:
            delta = round(outcome.stima_costo_usd - next_cost, 6)
            overrun_warning = await _apply_actual_cost_delta(db, execution, task, delta)
            if overrun_warning:
                task["warnings"] = task.get("warnings", []) + [overrun_warning]

        if outcome.esito != "OK":
            if outcome.retryable:
                if attempt >= MAX_ATTEMPTS:
                    await set_task_status(db, task, "FALLITA", {"warnings": task.get("warnings", []) + [
                        f"Rete (max tentativi superato): {outcome.messaggio}"]})
                    await _audit(db, org_id=org_id, actor="system", action="TASK_REAL_FAILED",
                                 entity_type="task", entity_id=task["id"], status="ERROR", reason=outcome.messaggio,
                                 details={"codice_errore": outcome.codice_errore})
                    await refresh_gates(db, task["plan_id"])
                    return {"task_id": task["id"], "result": "failed"}
                await set_task_status(db, task, "IN_CODA", {"lease_owner": None, "warnings": task.get("warnings", []) + [
                    f"Rete: {outcome.messaggio}"]})
                await _audit(db, org_id=org_id, actor="system", action="TASK_REAL_RETRY",
                             entity_type="task", entity_id=task["id"],
                             details={"attempt": attempt, "codice_errore": outcome.codice_errore})
                return {"task_id": task["id"], "result": "retry"}
            # Config/permessi/contesto incompleto/esito incerto/validazione
            # bloccata/budget del task esaurito: mai un retry cieco, richiede
            # intervento umano (stesso principio del ramo REAL_ELIGIBLE_TYPES
            # sopra). Il numero di contenuti gia' completati resta esplicito
            # nell'avviso — un risultato parziale non e' mai silenziosamente
            # perso. blocked_reason_code distingue i blocchi TECNICI, che
            # possono riprendere da soli una volta risolti nel laboratorio
            # (vedi real_content_creator.py::resume_blocked_content_item_tasks),
            # da quelli di budget/pianificazione, che restano fermi finche'
            # un umano non decide esplicitamente (mai un cap aumentato da soli).
            await set_task_status(db, task, "BLOCCATA", {"warnings": task.get("warnings", []) + [
                f"Content Creator: {outcome.produced_count}/{outcome.requested_quantity} contenuti completati "
                f"({outcome.codice_errore}): {outcome.messaggio}"],
                "blocked_reason_code": outcome.codice_errore})
            await _audit(db, org_id=org_id, actor="system", action="TASK_REAL_FAILED",
                         entity_type="task", entity_id=task["id"], status="ERROR", reason=outcome.messaggio,
                         details={"codice_errore": outcome.codice_errore, "stima_costo_usd": outcome.stima_costo_usd,
                                  "produced_count": outcome.produced_count, "requested_quantity": outcome.requested_quantity})
            await refresh_gates(db, task["plan_id"])
            return {"task_id": task["id"], "result": "real_failed"}

        # esito == "OK": tutti i content_item richiesti sono bozze reali
        # pronte (IN_ATTESA_APPROVAZIONE) — mai un COMPLETATA con meno
        # contenuti di quelli richiesti: se produced_count < requested_quantity
        # a questo punto e' un difetto di pianificazione (content_item_ids
        # piu' corto del richiesto), non un'esecuzione riuscita.
        if outcome.produced_count < outcome.requested_quantity:
            await set_task_status(db, task, "BLOCCATA", {"warnings": task.get("warnings", []) + [
                f"Pianificazione incompleta: solo {outcome.produced_count}/{outcome.requested_quantity} "
                "content_item creati per questa richiesta (verificare il task di creazione del piano)."],
                "blocked_reason_code": "pianificazione_incompleta"})
            await _audit(db, org_id=org_id, actor="system", action="TASK_PARTIAL_PLANNING",
                         entity_type="task", entity_id=task["id"], status="ERROR",
                         details={"produced_count": outcome.produced_count, "requested_quantity": outcome.requested_quantity})
            await refresh_gates(db, task["plan_id"])
            return {"task_id": task["id"], "result": "partial_planning"}

        # Le bozze sono pronte MA NON approvate: l'approvazione del piano ha
        # autorizzato solo la spesa di generazione, mai la decisione
        # editoriale (vedi real_content_creator.py). Distinzione esplicita,
        # mai nascosta dietro un generico "completato" — e mai equiparata a
        # un fallimento se ci sono contestazioni semantiche da rivedere.
        avvisi_extra = [f"{outcome.produced_count}/{outcome.requested_quantity} bozze generate: in attesa di "
                        "approvazione editoriale umana nel laboratorio Content Creator (non approvate automaticamente)."]
        if outcome.contested_ids:
            avvisi_extra.append(
                f"{len(outcome.contested_ids)} contenuto/i con affermazioni contestate dalla verifica semantica "
                f"({', '.join(outcome.contested_ids)}): verificare prima di approvare.")
        content = {
            "content_item_ids": [i["id"] for i in outcome.items],
            "mode": "REALE", "requested_quantity": outcome.requested_quantity, "produced_count": outcome.produced_count,
            "contested_ids": outcome.contested_ids,
            "items": [
                {"content_item_id": i["id"], "content_type": i["content_type"], "status": i["status"],
                 "content": i.get("content"), "semantic_check": i.get("semantic_check")}
                for i in outcome.items
            ],
        }
        validation = validate_deliverable(dtype, content)
        deliverable = await create_deliverable_version(
            db, org_id=org_id, plan=plan, task=task, content=content, validation=validation,
            agent_id=task.get("agent_id"), mode="REALE",
            generation={"provider": "requesty", "stima_costo_usd": outcome.stima_costo_usd})
        # I warning del task usano SOLO avvisi_extra (gia' piu' specifici, con
        # gli id dei content_item contestati): validation.get("warnings")
        # ripete lo stesso messaggio in forma generica per il record del
        # deliverable (validate_content_item) — mai duplicato anche qui.
        await db.tasks.update_one(
            {"id": task["id"]},
            {"$set": {"deliverable_id": deliverable["id"], "confirmed": True,
                      "warnings": task.get("warnings", []) + avvisi_extra}})
        task["confirmed"] = True
        await review_deliverable(db, deliverable, task)
    else:
        override = task.get("inputs", {}).get("deliverable_override")
        content = override if override is not None else produce_deliverable(
            dtype, task, plan, org_profile)
        validation = validate_deliverable(dtype, content)
        deliverable = await create_deliverable_version(
            db, org_id=org_id, plan=plan, task=task, content=content,
            validation=validation, agent_id=task.get("agent_id"), mode="SIMULAZIONE")
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


# --------- Avvio automatico dopo approvazione (persistente, indipendente dal browser) ---------
# Deliberatamente UNA sola via di attivazione (il worker di poll qui sotto),
# mai anche un trigger sincrono dentro approve_plan/approve_task: un
# secondo innesco immediato lì creerebbe una corsa con qualunque chiamante
# che, come questo stesso motore nei suoi test, invoca run_ready_tasks/tick
# subito dopo l'approvazione — claim atomico o no, un caller del genere
# vedrebbe occasionalmente "nessun task da processare" perché il worker lo
# ha già preso in carico un istante prima, un risultato non deterministico
# che non esisteva prima di questa correzione. Il worker di poll (avviato
# una sola volta allo startup, MAI dentro approve_plan/approve_task) resta
# comunque "persistente e indipendente dal browser": un piano approvato
# parte da solo entro AUTO_DISPATCH_POLL_SECONDS, senza alcuna azione
# lato client.
async def _auto_dispatch_scan_once(db):
    """Un solo giro di scansione — usato sia dal loop sotto sia dai test
    (deterministico, senza dipendere da tempistiche/sleep)."""
    owner = await _acquire_lock(db, "m2_auto_dispatch", ttl=AUTO_DISPATCH_POLL_SECONDS * 4)
    if not owner:
        return {"scanned": 0, "skipped": True}
    try:
        # SOLO task il cui approve_plan/approve_task e' passato da questo
        # codice (marcatore persistito): mai la vecchia coda storica,
        # nessuna esecuzione retroattiva di piani approvati prima di
        # questa correzione, anche dopo un riavvio del backend.
        plan_ids = await db.tasks.distinct(
            "plan_id", {"task_status": "IN_CODA", "auto_dispatch_requested_at": {"$exists": True}})
        for pid in plan_ids:
            await run_ready_tasks(db, pid)
        # Ripresa: task 'content_item' bloccati per un motivo TECNICO
        # (esito incerto/validazione bloccata risolti nel laboratorio) —
        # MAI i piani storici (nessun marcatore coinvolto, la ripresa agisce
        # solo su task gia' esistenti e gia' approvati in precedenza da
        # QUESTO stesso motore, individuati per stato tecnico risolto, non
        # per eta'/provenienza) e MAI un blocco di budget/pianificazione
        # (quelli restano fermi finche' un umano non decide esplicitamente).
        ripresi = await resume_blocked_content_item_tasks(db)
        for tid in ripresi:
            t = await db.tasks.find_one({"id": tid})
            if t:
                await run_ready_tasks(db, t["plan_id"])
        return {"scanned": len(plan_ids), "resumed": len(ripresi)}
    finally:
        await _release_lock(db, "m2_auto_dispatch", owner)


_auto_dispatch_worker_task = None


async def auto_dispatch_worker_loop(db):
    logger.info("ACTELYA M2 auto-dispatch worker avviato")
    while True:
        try:
            await _auto_dispatch_scan_once(db)
        except Exception:
            logger.exception("Errore nel worker di auto-dispatch M2")
        await asyncio.sleep(AUTO_DISPATCH_POLL_SECONDS)


def start_auto_dispatch_worker(db):
    global _auto_dispatch_worker_task
    if _auto_dispatch_worker_task is None:
        _auto_dispatch_worker_task = asyncio.create_task(auto_dispatch_worker_loop(db))


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
    """M2 produce sempre contenuto deterministico 'SIMULAZIONE' (invariato):
    QUESTO non e' mai cambiato.

    Correzione (allineamento implementazione/test): il guard e' invocato
    SOLO da http_create_plan() — l'endpoint HTTP che crea un piano
    DIRETTAMENTE su M2 grezzo, bypassando triage/selezione agenti/
    compliance del Brain (nessun percorso prodotto oggi lo chiama:
    Plans.jsx crea sempre da "Nuovo Obiettivo" -> POST /brain/plans).
    Restare disponibile per questo solo scopo tecnico/di test ha senso:
    uno "strumento di simulazione grezzo" non deve restare invocabile
    quando l'organizzazione ha attivato la modalita' reale.

    Il guard NON e' invocato da:
    - create_plan() (funzione core, usata internamente da
      brain/service.py::create_plan_with_brain): il Brain deve poter
      creare/approvare/eseguire un piano — comprensione, pianificazione,
      DAG, handoff, stati, audit — anche quando l'org ha capability REALI
      attive per ALTRE parti dello stesso piano (es. domains/reel.py/
      flyer.py/leadgen);
    - http_tick() (POST /plans/{id}/tick): fa progredire un piano GIA'
      creato, di qualunque origine (Brain o grezzo) — bloccarlo
      impedirebbe di completare anche i task M2 simulati di un piano
      Brain in un'organizzazione REALE, contraddicendo il punto sopra."""
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
    # Percorso HTTP DIRETTO su M2 grezzo (bypassa triage/selezione agenti/
    # compliance del Brain): guardato in SIMULAZIONE, vedi _assert_simulation().
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
    # Modalita' effettiva mostrata dal frontend (mai hardcoded): l'org puo' essere
    # in REALE ma un piano/task pre-esistente resta SIMULAZIONE (approved_mode
    # assente o diverso da REALE, vedi approve_plan/approve_task/real_content.py) —
    # "Esegui (reale)" va mostrato SOLO se il percorso reale e' davvero disponibile
    # ORA per almeno un task idoneo di QUESTO piano.
    settings = await _global_db.settings.find_one({"id": plan["organization_id"]}) or {}
    ai_real_mode = bool(settings.get("ai_real_mode"))
    real_tasks_approved_real = [
        t for t in tasks if t["deliverable_type"] in REAL_ELIGIBLE_TYPES and t.get("approved_mode") == "REALE"
    ]
    real_ready, real_reasons = False, []
    if ai_real_mode and real_tasks_approved_real:
        r = await check_readiness(_global_db, plan["organization_id"])
        real_ready, real_reasons = r.pronto, r.motivi
    return {"plan": plan, "tasks": tasks, "execution": ex, "mode": {
        "ai_real_mode": ai_real_mode,
        "real_eligible_tasks_approved_real": len(real_tasks_approved_real),
        "real_ready": real_ready,
        "reasons": real_reasons,
    }}


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


async def enrich_content_item_deliverables_live(db_conn, deliverables: list) -> list:
    """Il deliverable 'content_item' porta uno SNAPSHOT di content/status per
    ciascun content_item, preso al momento della generazione (vedi il blocco
    'content' in _execute() sopra) — mai piu' aggiornato quando l'utente
    approva/rifiuta/richiede una modifica nel laboratorio Content Creator
    (quell'azione scrive SOLO su db.content_items, mai sul deliverable gia'
    versionato, per costruzione: un deliverable versionato non si riscrive).
    Senza questo arricchimento, Risultati e il dettaglio piano
    continuerebbero a mostrare "IN_ATTESA_APPROVAZIONE" anche dopo una
    decisione editoriale reale — la stessa organizzazione vedrebbe stati
    diversi tra laboratorio e Risultati. Sovrascrive SOLO status/content/
    semantic_check con il valore LIVE da content_items (mai il resto del
    deliverable, che resta uno storico immutabile); un content_item
    referenziato ma non piu' esistente resta assente (gestito gia' lato UI
    come 'non disponibile', mai un dato inventato)."""
    ids = set()
    for d in deliverables:
        if d.get("deliverable_type") != "content_item":
            continue
        c = d.get("content") or {}
        for it in (c.get("items") or []):
            if it.get("content_item_id"):
                ids.add(it["content_item_id"])
    if not ids:
        return deliverables
    live = {i["id"]: i async for i in db_conn.content_items.find(
        {"id": {"$in": list(ids)}}, {"_id": 0, "id": 1, "status": 1, "content": 1, "semantic_check": 1})}
    for d in deliverables:
        if d.get("deliverable_type") != "content_item":
            continue
        c = d.get("content") or {}
        for it in (c.get("items") or []):
            aggiornato = live.get(it.get("content_item_id"))
            if aggiornato:
                it["status"] = aggiornato.get("status", it.get("status"))
                it["content"] = aggiornato.get("content", it.get("content"))
                it["semantic_check"] = aggiornato.get("semantic_check", it.get("semantic_check"))
    return deliverables


@router.get("/plans/{plan_id}/deliverables")
async def http_list_deliverables(plan_id: str, user: dict = Depends(get_current_user)):
    await _load_plan_authz(plan_id, user)
    delivs = await _global_db.deliverables.find(
        {"plan_id": plan_id}, {"_id": 0}).sort([("task_id", 1), ("version", 1)]).to_list(500)
    delivs = await enrich_content_item_deliverables_live(_global_db, delivs)
    delivs = await enrich_multi_item_deliverables_with_decisions(_global_db, delivs)
    return {"deliverables": delivs, "mode": "SIMULAZIONE"}


class ItemDecisionBody(BaseModel):
    decision: str
    reason: str | None = None


@router.post("/plans/{plan_id}/deliverables/{deliverable_id}/items/{item_index}/decision")
async def http_decide_deliverable_item(
    plan_id: str, deliverable_id: str, item_index: int, body: ItemDecisionBody,
    user: dict = Depends(require_roles("ADMIN", "APPROVATORE")),
):
    """Approva/Rifiuta/Richiedi modifica su UNA bozza di un deliverable
    multi-bozza (es. social_content). Stessa RBAC della decisione editoriale
    di content_item (ADMIN/APPROVATORE, vedi content_creator/router.py). Non
    genera, non rigenera, non pubblica: solo persistenza della decisione."""
    plan = await _load_plan_authz(plan_id, user)
    deliverable = await _global_db.deliverables.find_one(
        {"id": deliverable_id, "plan_id": plan_id}, {"_id": 0})
    if not deliverable:
        raise HTTPException(404, "Deliverable non trovato")
    try:
        rec = await decide_item(
            _global_db, org_id=plan["organization_id"], plan_id=plan_id, deliverable=deliverable,
            item_index=item_index, decision=body.decision, actor=user["email"], reason=body.reason,
        )
    except DecisionError as e:
        raise HTTPException(409, str(e))
    await _audit(
        _global_db, org_id=plan["organization_id"], actor=user["email"], action="DECIDE_DELIVERABLE_ITEM",
        entity_type="deliverable_item_decision", entity_id=rec["id"],
        details={"deliverable_id": deliverable_id, "item_index": item_index, "decision": body.decision,
                 "deliverable_version": deliverable.get("version")},
    )
    return rec


@router.get("/plans/{plan_id}/deliverables/{deliverable_id}/items/{item_index}/edit-cost")
async def http_preview_edit_cost(
    plan_id: str, deliverable_id: str, item_index: int,
    user: dict = Depends(require_roles("ADMIN", "APPROVATORE")),
):
    """SOLA stima del costo di una revisione (mai un addebito, mai una
    chiamata reale): da mostrare all'utente PRIMA di chiedere la conferma
    esplicita di applicazione (POST .../apply-edit)."""
    await _load_plan_authz(plan_id, user)
    deliverable = await _global_db.deliverables.find_one(
        {"id": deliverable_id, "plan_id": plan_id}, {"_id": 0})
    if not deliverable:
        raise HTTPException(404, "Deliverable non trovato")
    try:
        return await preview_edit_cost(deliverable, item_index)
    except DecisionError as e:
        raise HTTPException(409, str(e))


class ApplyEditBody(BaseModel):
    confirm: bool = False


@router.post("/plans/{plan_id}/deliverables/{deliverable_id}/items/{item_index}/apply-edit")
async def http_apply_deliverable_item_edit(
    plan_id: str, deliverable_id: str, item_index: int, body: ApplyEditBody,
    user: dict = Depends(require_roles("ADMIN", "APPROVATORE")),
):
    """Applica la richiesta di modifica CORRENTE di una bozza, producendo
    una NUOVA VERSIONE indipendente (IN_ATTESA_REVISIONE, mai approvata
    automaticamente) — richiede confirm=True esplicito (stessa
    autorizzazione applicativa di content_creator/pipeline.py::generate).
    Mai avviata da una semplice richiesta di modifica: solo da questa
    azione umana esplicita."""
    plan = await _load_plan_authz(plan_id, user)
    deliverable = await _global_db.deliverables.find_one(
        {"id": deliverable_id, "plan_id": plan_id}, {"_id": 0})
    if not deliverable:
        raise HTTPException(404, "Deliverable non trovato")
    try:
        nuova_versione = await apply_edit(
            _global_db, org_id=plan["organization_id"], plan_id=plan_id, deliverable=deliverable,
            item_index=item_index, actor=user["email"], confirm=body.confirm,
        )
    except DecisionError as e:
        raise HTTPException(409, str(e))
    await _audit(
        _global_db, org_id=plan["organization_id"], actor=user["email"], action="APPLY_DELIVERABLE_ITEM_EDIT",
        entity_type="deliverable_item_version", entity_id=nuova_versione["id"],
        details={"deliverable_id": deliverable_id, "item_index": item_index,
                 "version": nuova_versione["version"], "mode": nuova_versione["mode"]},
    )
    return nuova_versione


@router.get("/plans/{plan_id}/reviews")
async def http_list_reviews(plan_id: str, user: dict = Depends(get_current_user)):
    await _load_plan_authz(plan_id, user)
    rows = await _global_db.reviews.find({"plan_id": plan_id}, {"_id": 0}).sort("created_at", 1).to_list(500)
    return {"reviews": rows, "mode": "SIMULAZIONE"}


@router.post("/plans/{plan_id}/tasks/{task_id}/review")
async def http_review_task(plan_id: str, task_id: str,
                           user: dict = Depends(require_roles("ADMIN", "APPROVATORE"))):
    plan = await _load_plan_authz(plan_id, user)
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
    res = await run_ready_tasks(_global_db, plan_id)
    settings = await _global_db.settings.find_one({"id": plan["organization_id"]}) or {}
    return {**res, "mode": "REALE" if settings.get("ai_real_mode") else "SIMULAZIONE"}
