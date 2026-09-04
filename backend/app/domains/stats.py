from fastapi import APIRouter, Depends

from ..db import db
from ..deps import get_current_user, assert_same_org
from ..config import DEFAULT_ORG_ID
from .agents import AGENT_REGISTRY

router = APIRouter(tags=["stats"])


@router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    executions = await db.executions.find({"organization_id": org_id}, {"_id": 0}).to_list(1000)
    # A content counts ONLY if a persisted, valid deliverable exists.
    valid_deliverables = await db.deliverables.count_documents(
        {"organization_id": org_id, "status": {"$in": ["COMPLETATO", "COMPLETATO_CON_AVVISI"]}})
    pending_approvals = await db.approvals.count_documents(
        {"organization_id": org_id, "status": "IN_ATTESA_APPROVAZIONE"})
    total_cost = round(sum(e.get("real_cost", 0.0) for e in executions), 6)
    budget = await db.budgets.find_one({"id": org_id}) or {}
    settings = await db.settings.find_one({"id": org_id}) or {}

    by_status = {}
    for e in executions:
        by_status[e.get("execution_status")] = by_status.get(e.get("execution_status"), 0) + 1

    blocked_deliverables = await db.deliverables.count_documents(
        {"organization_id": org_id, "status": "BLOCCATO"})

    return {
        "mode": "REALE" if settings.get("ai_real_mode") else "SIMULAZIONE",
        "executions_total": len(executions),
        "executions_by_status": by_status,
        "valid_deliverables": valid_deliverables,
        "blocked_deliverables": blocked_deliverables,
        "pending_approvals": pending_approvals,
        "total_cost_simulated": total_cost,
        "budget_limit": budget.get("general_limit", 0.0),
        "budget_residual": round(budget.get("general_limit", 0.0) - total_cost, 6),
    }


@router.get("/deliverables")
async def list_deliverables(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.deliverables.find({"organization_id": org_id}, {"_id": 0}).sort("created_at", -1).to_list(300)
    return rows


@router.get("/deliverables/{deliverable_id}")
async def get_deliverable(deliverable_id: str, user: dict = Depends(get_current_user)):
    d = await db.deliverables.find_one({"id": deliverable_id}, {"_id": 0})
    assert_same_org(d, user, "Deliverable non trovato")
    return d


@router.get("/agents")
async def list_agents(user: dict = Depends(get_current_user)):
    return list(AGENT_REGISTRY.values())


@router.get("/audit")
async def list_audit(limit: int = 200, user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.audit_logs.find({"organization_id": org_id}, {"_id": 0}).sort("at", -1).to_list(limit)
    return rows
