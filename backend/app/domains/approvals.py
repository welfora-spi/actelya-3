from fastapi import APIRouter, Depends, HTTPException

from ..db import db
from ..deps import require_roles, get_current_user
from ..audit import log_audit
from ..models import now_iso
from ..config import DEFAULT_ORG_ID
from .engine import create_execution_from_approval

router = APIRouter(prefix="/approvals", tags=["approvals"])

APPROVER_ROLES = ("ADMIN", "APPROVATORE")


@router.get("")
async def list_approvals(status: str = "IN_ATTESA_APPROVAZIONE", user: dict = Depends(get_current_user)):
    q = {"organization_id": DEFAULT_ORG_ID}
    if status and status != "ALL":
        q["status"] = status
    rows = await db.approvals.find(q, {"_id": 0}).sort("created_at", -1).to_list(300)
    return rows


async def _approve_one(approval_id: str, user: dict) -> dict:
    # Idempotent: only the request that flips IN_ATTESA -> APPROVATA creates the execution.
    updated = await db.approvals.find_one_and_update(
        {"id": approval_id, "status": "IN_ATTESA_APPROVAZIONE"},
        {"$set": {"status": "APPROVATA", "approved_by": user["email"],
                  "approved_at": now_iso(), "updated_at": now_iso()}},
        return_document=True,
    )
    if not updated:
        current = await db.approvals.find_one({"id": approval_id}, {"_id": 0})
        if not current:
            raise HTTPException(status_code=404, detail="Richiesta non trovata")
        # Already handled -> idempotent no-op
        return {"approval_id": approval_id, "status": current["status"],
                "execution_id": current.get("execution_id"), "idempotent": True}

    updated.pop("_id", None)
    execution = None
    if updated["type"] == "PREVENTIVO":
        execution = await create_execution_from_approval(updated, user)
    await log_audit(org_id=DEFAULT_ORG_ID, user=user, action="APPROVE",
                    entity_type="approval", entity_id=approval_id,
                    details={"type": updated["type"]})
    return {"approval_id": approval_id, "status": "APPROVATA",
            "execution_id": (execution or {}).get("id"), "idempotent": False}


@router.post("/{approval_id}/approve")
async def approve(approval_id: str, user: dict = Depends(require_roles(*APPROVER_ROLES))):
    appr = await db.approvals.find_one({"id": approval_id})
    if appr and appr.get("type") == "AZIONE_ESTERNA" and appr.get("blocked"):
        raise HTTPException(status_code=409,
                            detail="Azione esterna bloccata: prerequisiti mancanti o integrazione non collegata.")
    return await _approve_one(approval_id, user)


@router.post("/{approval_id}/reject")
async def reject(approval_id: str, user: dict = Depends(require_roles(*APPROVER_ROLES))):
    updated = await db.approvals.find_one_and_update(
        {"id": approval_id, "status": "IN_ATTESA_APPROVAZIONE"},
        {"$set": {"status": "RIFIUTATA", "approved_by": user["email"],
                  "approved_at": now_iso(), "updated_at": now_iso()}},
        return_document=True,
    )
    if not updated:
        current = await db.approvals.find_one({"id": approval_id}, {"_id": 0})
        if not current:
            raise HTTPException(status_code=404, detail="Richiesta non trovata")
        return {"approval_id": approval_id, "status": current["status"], "idempotent": True}
    if updated.get("goal_id"):
        await db.goals.update_one({"id": updated["goal_id"]}, {"$set": {"status": "RIFIUTATO"}})
    await log_audit(org_id=DEFAULT_ORG_ID, user=user, action="REJECT",
                    entity_type="approval", entity_id=approval_id)
    return {"approval_id": approval_id, "status": "RIFIUTATA", "idempotent": False}


@router.post("/approve-all")
async def approve_all(user: dict = Depends(require_roles(*APPROVER_ROLES))):
    rows = await db.approvals.find(
        {"organization_id": DEFAULT_ORG_ID, "status": "IN_ATTESA_APPROVAZIONE",
         "type": "PREVENTIVO"}, {"_id": 0}).to_list(300)
    results = []
    for r in rows:
        results.append(await _approve_one(r["id"], user))
    return {"processed": len(results), "results": results}


@router.post("/reject-all")
async def reject_all(user: dict = Depends(require_roles(*APPROVER_ROLES))):
    rows = await db.approvals.find(
        {"organization_id": DEFAULT_ORG_ID, "status": "IN_ATTESA_APPROVAZIONE"}, {"_id": 0}).to_list(300)
    count = 0
    for r in rows:
        await reject(r["id"], user)  # reuse logic
        count += 1
    return {"processed": count}
