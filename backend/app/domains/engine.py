"""Operating engine: goals -> classification -> estimate -> approval -> single execution ->
agents -> validation -> deliverable. Includes a recoverable background worker (DB-polling)."""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import db
from ..deps import get_current_user, require_roles, assert_same_org
from ..audit import log_audit
from ..models import now_iso, base_record, new_id
from ..config import DEFAULT_ORG_ID
from .intent import classify_intent
from .estimator import estimate_for_agents, PRICE_PER_TOKEN
from .agents import AGENT_REGISTRY, select_agents_for_goal, simulated_email_deliverable
from .validators import validate_email_deliverable, check_external_prerequisites

logger = logging.getLogger("actelya.engine")
router = APIRouter(tags=["engine"])

_worker_task = None


class GoalBody(BaseModel):
    text: str


# ---------------- Goal intake ----------------
@router.post("/goals")
async def create_goal(body: GoalBody, user: dict = Depends(get_current_user)):
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="Obiettivo vuoto")
    org_id = user.get("organization_id") or DEFAULT_ORG_ID

    settings = await db.settings.find_one({"id": org_id}) or {}
    ai_real = settings.get("ai_real_mode", False)

    intent = classify_intent(body.text, ai_real_mode=ai_real)
    agent_ids = select_agents_for_goal(intent["intent_type"])
    estimate = estimate_for_agents(agent_ids, AGENT_REGISTRY)

    goal = base_record(org_id, user["id"])
    goal.update({
        "id": new_id("goal"), "text": body.text.strip(), "intent": intent,
        "agents": agent_ids, "estimate": estimate, "status": "IN_APPROVAZIONE",
        "approval_id": None, "execution_id": None,
        "classified_at": now_iso(), "classified_by": user["id"],
    })
    await db.goals.insert_one(goal)

    risks = list(intent["risk_flags"])
    external_actions = ["Invio email a destinatari reali"] if intent["requires_external_action"] else []
    approval = base_record(org_id, user["id"])
    approval.update({
        "id": new_id("appr"), "type": "PREVENTIVO", "goal_id": goal["id"],
        "title": "Preventivo esecuzione obiettivo",
        "what": body.text.strip(),
        "agent_responsible": "Orchestratore",
        "agents": agent_ids,
        "data_used": ["profilo_aziendale", "obiettivo (solo dati forniti)"],
        "cost_min": estimate["cost_min"], "cost_probable": estimate["cost_probable"],
        "cost_max": estimate["cost_max"], "approved_cap": estimate["approvable_cap"],
        "risks": risks, "prerequisites": [], "external_actions": external_actions,
        "consequences": "Verrà creata una singola esecuzione persistita che produrrà una bozza (SIMULAZIONE). Nessun invio reale.",
        "status": "IN_ATTESA_APPROVAZIONE", "execution_id": None,
        "mode": "SIMULAZIONE",
    })
    await db.approvals.insert_one(approval)
    await db.goals.update_one({"id": goal["id"]}, {"$set": {"approval_id": approval["id"]}})

    await log_audit(org_id=org_id, user=user, action="CREATE_GOAL",
                    entity_type="goal", entity_id=goal["id"],
                    details={"intent": intent["intent_type"], "risk_flags": risks})

    goal.pop("_id", None)
    approval.pop("_id", None)
    return {"goal": goal, "approval": approval}


@router.get("/goals")
async def list_goals(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.goals.find({"organization_id": org_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return rows


@router.get("/goals/{goal_id}")
async def get_goal(goal_id: str, user: dict = Depends(get_current_user)):
    g = await db.goals.find_one({"id": goal_id}, {"_id": 0})
    assert_same_org(g, user, "Obiettivo non trovato")
    return g


# ---------------- Execution creation (called by approvals, idempotent) ----------------
async def create_execution_from_approval(approval: dict, user: dict) -> dict:
    """Create exactly one execution. Guarded by a unique index on approval_id."""
    goal = await db.goals.find_one({"id": approval["goal_id"]})
    if not goal:
        raise HTTPException(status_code=404, detail="Obiettivo collegato non trovato")
    org_id = goal.get("organization_id") or DEFAULT_ORG_ID

    execution = base_record(org_id, user["id"])
    execution.update({
        "id": new_id("exec"), "goal_id": goal["id"], "approval_id": approval["id"],
        "agents": goal["agents"], "estimate": goal["estimate"],
        "execution_status": "IN_CODA", "deliverable_status": None, "action_status": "NON_RICHIESTA",
        "agent_runs": [], "real_cost": 0.0, "tokens_input": 0, "tokens_output": 0,
        "deliverable_id": None, "warnings": [], "missing_prerequisites": [],
        "intent": goal["intent"], "goal_text": goal["text"],
        "started_at": None, "finished_at": None, "mode": "SIMULAZIONE",
        "error": None,
    })
    try:
        await db.executions.insert_one(execution)
    except Exception:
        existing = await db.executions.find_one({"approval_id": approval["id"]}, {"_id": 0})
        if existing:
            return existing
        raise
    await db.goals.update_one({"id": goal["id"]},
                              {"$set": {"execution_id": execution["id"], "status": "APPROVATO"}})
    await db.approvals.update_one({"id": approval["id"]},
                                  {"$set": {"execution_id": execution["id"]}})
    await log_audit(org_id=org_id, user=user, action="CREATE_EXECUTION",
                    entity_type="execution", entity_id=execution["id"],
                    details={"goal_id": goal["id"], "approval_id": approval["id"]})
    execution.pop("_id", None)
    return execution


# ---------------- Execution queries ----------------
@router.get("/executions")
async def list_executions(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.executions.find({"organization_id": org_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return rows


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: str, user: dict = Depends(get_current_user)):
    e = await db.executions.find_one({"id": execution_id}, {"_id": 0})
    assert_same_org(e, user, "Esecuzione non trovata")
    deliverable = None
    if e.get("deliverable_id"):
        deliverable = await db.deliverables.find_one({"id": e["deliverable_id"]}, {"_id": 0})
    return {"execution": e, "deliverable": deliverable}


# ---------------- Worker (recoverable, DB-polling) ----------------
async def _run_agent_simulated(agent_id: str, goal_text: str, org_profile: dict):
    contract = AGENT_REGISTRY.get(agent_id, {})
    tokens_in = int(contract.get("token_limit", 1000) * 0.3)
    tokens_out = int(contract.get("token_limit", 1000) * 0.35)
    cost = round((tokens_in + tokens_out) * PRICE_PER_TOKEN, 6)
    output = {"note": f"Output simulato da {contract.get('name', agent_id)}"}
    deliverable = None
    if agent_id == "content_social":
        deliverable = simulated_email_deliverable(goal_text, org_profile)
        output = {"produced": "email_draft"}
    if agent_id == "compliance_reviewer":
        output = {"warnings": ["Verificare consenso GDPR prima di qualsiasi invio.",
                               "Bozza a scopo dimostrativo con dati fittizi."]}
    return {
        "agent_id": agent_id, "agent_name": contract.get("name", agent_id),
        "status": "COMPLETATA", "confirmed": True,
        "tokens_input": tokens_in, "tokens_output": tokens_out, "cost": cost,
        "output": output, "deliverable": deliverable, "at": now_iso(),
    }


async def process_execution(execution: dict):
    ex_id = execution["id"]
    # Atomic claim: only proceed if still IN_CODA.
    claimed = await db.executions.find_one_and_update(
        {"id": ex_id, "execution_status": "IN_CODA"},
        {"$set": {"execution_status": "IN_ESECUZIONE", "started_at": now_iso()}},
    )
    if not claimed:
        return  # already claimed/processed elsewhere

    org_id = execution.get("organization_id") or DEFAULT_ORG_ID
    org_profile = await db.organizations.find_one({"id": org_id}, {"_id": 0}) or {}
    goal_text = execution.get("goal_text", "")
    done_ids = {r["agent_id"] for r in execution.get("agent_runs", []) if r.get("confirmed")}
    runs = list(execution.get("agent_runs", []))
    real_cost = execution.get("real_cost", 0.0)
    tok_in = execution.get("tokens_input", 0)
    tok_out = execution.get("tokens_output", 0)
    deliverable_payload = None
    warnings = list(execution.get("warnings", []))

    try:
        for agent_id in execution["agents"]:
            if agent_id in done_ids:
                for r in runs:
                    if r["agent_id"] == agent_id and r.get("deliverable"):
                        deliverable_payload = r["deliverable"]
                continue
            run = await _run_agent_simulated(agent_id, goal_text, org_profile)
            runs.append(run)
            real_cost = round(real_cost + run["cost"], 6)
            tok_in += run["tokens_input"]
            tok_out += run["tokens_output"]
            if run.get("deliverable"):
                deliverable_payload = run["deliverable"]
            if agent_id == "compliance_reviewer":
                warnings.extend(run["output"].get("warnings", []))
            # Persist incrementally for restart-safe resume.
            await db.executions.update_one(
                {"id": ex_id},
                {"$set": {"agent_runs": runs, "real_cost": real_cost,
                          "tokens_input": tok_in, "tokens_output": tok_out,
                          "warnings": warnings, "updated_at": now_iso()}},
            )

        # Validate + persist deliverable
        deliverable_status = "BLOCCATO"
        deliverable_id = None
        if deliverable_payload:
            validation = validate_email_deliverable(deliverable_payload)
            deliverable_status = validation["status"]
            warnings.extend(validation["warnings"])
            drec = base_record(org_id, execution["created_by"])
            drec.update({
                "id": new_id("deliv"), "execution_id": ex_id, "goal_id": execution["goal_id"],
                "type": "email", "content": deliverable_payload, "status": deliverable_status,
                "warnings": validation["warnings"], "errors": validation["errors"],
                "sent": False, "mode": "SIMULAZIONE",
            })
            await db.deliverables.insert_one(drec)
            deliverable_id = drec["id"]
        else:
            warnings.append("Nessun deliverable prodotto.")

        # External action handling
        intent = execution.get("intent", {})
        if intent.get("requires_external_action"):
            prereq = check_external_prerequisites(
                has_recipients=False, has_consent=False,
                integration_available=False, has_approval=False, budget_ok=True,
            )
            action_status = "BLOCCATA"
            missing = prereq["missing"]
            # Create a separate approval request for the external action (stays pending/blocked).
            ext_appr = base_record(org_id, execution["created_by"])
            ext_appr.update({
                "id": new_id("appr"), "type": "AZIONE_ESTERNA", "goal_id": execution["goal_id"],
                "title": "Autorizzazione azione esterna (invio email)",
                "what": "Invio della bozza email a destinatari reali",
                "agent_responsible": "Appointment Setter / Content & Social",
                "agents": [], "data_used": ["deliverable"],
                "cost_min": 0.0, "cost_probable": 0.0, "cost_max": 0.0, "approved_cap": 0.0,
                "risks": ["invio", "dati_personali", "consenso"],
                "prerequisites": missing, "external_actions": ["Invio email"],
                "consequences": "L'invio reale NON è collegato in questa milestone.",
                "status": "IN_ATTESA_APPROVAZIONE", "execution_id": ex_id,
                "blocked": True, "mode": "SIMULAZIONE",
            })
            await db.approvals.insert_one(ext_appr)
        else:
            action_status = "NON_RICHIESTA"
            missing = []

        await db.executions.update_one(
            {"id": ex_id},
            {"$set": {
                "execution_status": "COMPLETATA",
                "deliverable_status": deliverable_status,
                "action_status": action_status,
                "deliverable_id": deliverable_id,
                "agent_runs": runs, "real_cost": real_cost,
                "tokens_input": tok_in, "tokens_output": tok_out,
                "warnings": warnings, "missing_prerequisites": missing,
                "finished_at": now_iso(), "updated_at": now_iso(),
            }},
        )
        await db.goals.update_one({"id": execution["goal_id"]}, {"$set": {"status": "ESEGUITO"}})
        await log_audit(org_id=org_id, user={"email": "system"}, action="EXECUTION_COMPLETED",
                        entity_type="execution", entity_id=ex_id,
                        details={"deliverable_status": deliverable_status, "action_status": action_status,
                                 "real_cost": real_cost, "tokens_input": tok_in, "tokens_output": tok_out})
    except Exception as e:
        logger.exception("Esecuzione fallita")
        await db.executions.update_one(
            {"id": ex_id},
            {"$set": {"execution_status": "FALLITA", "error": "Errore interno sanificato",
                      "finished_at": now_iso(), "updated_at": now_iso()}},
        )
        await log_audit(org_id=org_id, user={"email": "system"}, action="EXECUTION_FAILED",
                        entity_type="execution", entity_id=ex_id, status="ERROR",
                        reason="Errore interno sanificato")


async def worker_loop():
    logger.info("ACTELYA engine worker avviato")
    while True:
        try:
            pending = await db.executions.find(
                {"execution_status": "IN_CODA", "agents": {"$exists": True}}, {"_id": 0}).sort("created_at", 1).to_list(10)
            for ex in pending:
                await process_execution(ex)
        except Exception:
            logger.exception("Errore nel worker loop")
        await asyncio.sleep(1)


async def recover_on_startup():
    """Resume executions interrupted by a restart. Confirmed agent runs are skipped (no duplicate spend)."""
    res = await db.executions.update_many(
        {"execution_status": "IN_ESECUZIONE", "agents": {"$exists": True}},
        {"$set": {"execution_status": "IN_CODA", "updated_at": now_iso()}},
    )
    if res.modified_count:
        logger.info("Recovery: %s esecuzioni riportate in coda", res.modified_count)


def start_worker():
    global _worker_task
    if _worker_task is None:
        _worker_task = asyncio.create_task(worker_loop())
