from fastapi import APIRouter, Depends

from ..db import db
from ..deps import get_current_user, assert_same_org
from ..config import DEFAULT_ORG_ID
from .agents import AGENT_REGISTRY
from .budget import compute_spent
from ..m2.engine import enrich_content_item_deliverables_live
from ..m2.deliverable_review import (
    MULTI_ITEM_FIELD, enrich_multi_item_deliverables_with_decisions, get_item_decisions,
    STATO_IN_ATTESA_REVISIONE,
)

router = APIRouter(tags=["stats"])


@router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    executions = await db.executions.find({"organization_id": org_id}, {"_id": 0}).to_list(1000)
    # A content counts ONLY if a persisted, valid deliverable exists.
    valid_deliverables = await db.deliverables.count_documents(
        {"organization_id": org_id, "status": {"$in": ["COMPLETATO", "COMPLETATO_CON_AVVISI"]}})

    # Approvazioni pendenti: TRE categorie distinte, mai fuse in un solo
    # numero senza dettaglio (mostravano 0 nonostante un piano M2 e tre
    # content_item in attesa, perche' questo endpoint contava SOLO la
    # collezione 'approvals' — flusso M1/Reel/Flyer, mai popolata dai piani
    # M2 ne' dal laboratorio Content Creator, architetture distinte che non
    # scrivono mai in quella collezione).
    pending_plans = await db.plans.count_documents(
        {"organization_id": org_id, "plan_status": "IN_ATTESA_APPROVAZIONE", "is_current": True})
    pending_content_items = await db.content_items.count_documents(
        {"organization_id": org_id, "status": "IN_ATTESA_APPROVAZIONE"})
    pending_approvals_legacy = await db.approvals.count_documents(
        {"organization_id": org_id, "status": "IN_ATTESA_APPROVAZIONE"})

    # Bozze di deliverable multi-item (es. social_content -> "posts") la cui
    # VERSIONE CORRENTE e' ancora senza decisione editoriale: stesso
    # principio di pending_content_items, ma per il ramo che non passa dal
    # laboratorio Content Creator (vedi m2/deliverable_review.py). Una
    # bozza appena modificata (nuova versione) torna pendente anche se una
    # versione precedente era gia' stata decisa — mai contata come
    # approvata implicitamente solo perche' una versione passata lo era.
    pending_deliverable_items = 0
    tipi_multi_bozza = list(MULTI_ITEM_FIELD.keys())
    if tipi_multi_bozza:
        deliverable_correnti = await db.deliverables.find(
            {"organization_id": org_id, "is_current": True, "deliverable_type": {"$in": tipi_multi_bozza}},
            {"_id": 0}).to_list(500)
        for d in deliverable_correnti:
            decisioni = await get_item_decisions(db, d)
            pending_deliverable_items += sum(
                1 for it in decisioni if it["decision"]["status"] == STATO_IN_ATTESA_REVISIONE)

    pending_approvals = pending_plans + pending_content_items + pending_approvals_legacy + pending_deliverable_items

    # Stessa definizione di spesa/residuo di GET /budget (domains/budget.py)
    # — mai una seconda somma che puo' divergere dalla pagina Budget.
    speso = await compute_spent(db, org_id)
    budget = await db.budgets.find_one({"id": org_id}) or {}
    settings = await db.settings.find_one({"id": org_id}) or {}

    # execution_status manca su alcune 'executions' storiche di dominii
    # diversi da M2 (es. domains/reel.py, che scrive in questa stessa
    # collezione senza mai impostare questo campo). None serializzato in
    # JSON diventa la CHIAVE STRINGA "null" — mostrata letteralmente come
    # "null:2" in Dashboard.jsx. Mai trasformato in "COMPLETATA" (non lo
    # sappiamo davvero): etichettato esplicitamente come sconosciuto.
    by_status = {}
    for e in executions:
        stato = e.get("execution_status") or "SCONOSCIUTO"
        by_status[stato] = by_status.get(stato, 0) + 1

    blocked_deliverables = await db.deliverables.count_documents(
        {"organization_id": org_id, "status": "BLOCCATO"})

    return {
        # 'mode': interruttore ORGANIZZAZIONE (settings.ai_real_mode, "puo'
        # fare chiamate reali ORA"), invariato — concetto distinto da
        # 'spent_mode' sotto ("la spesa gia' registrata era reale/simulata/
        # mista"), che e' quello usato dalla pagina Budget.
        "mode": "REALE" if settings.get("ai_real_mode") else "SIMULAZIONE",
        "spent_mode": speso["mode"],
        "executions_total": len(executions),
        "executions_by_status": by_status,
        "valid_deliverables": valid_deliverables,
        "blocked_deliverables": blocked_deliverables,
        "pending_approvals": pending_approvals,
        "pending_plans": pending_plans,
        "pending_content_items": pending_content_items,
        "pending_deliverable_items": pending_deliverable_items,
        "pending_approvals_legacy": pending_approvals_legacy,
        "total_cost_simulated": speso["spent_simulated"],
        "budget_limit": budget.get("general_limit", 0.0),
        "budget_residual": round(budget.get("general_limit", 0.0) - speso["spent_simulated"], 6),
    }


@router.get("/deliverables")
async def list_deliverables(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.deliverables.find({"organization_id": org_id}, {"_id": 0}).sort("created_at", -1).to_list(300)
    rows = await enrich_content_item_deliverables_live(db, rows)
    rows = await enrich_multi_item_deliverables_with_decisions(db, rows)
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
