from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import db
from ..deps import require_roles, get_current_user
from ..audit import log_audit
from ..models import now_iso
from ..config import DEFAULT_ORG_ID

router = APIRouter(prefix="/settings", tags=["settings"])


class RealModeBody(BaseModel):
    enable: bool
    confirm: bool = False


@router.get("")
async def get_settings(user: dict = Depends(get_current_user)):
    s = await db.settings.find_one({"id": DEFAULT_ORG_ID}, {"_id": 0}) or {
        "id": DEFAULT_ORG_ID, "ai_real_mode": False}
    # Report readiness conditions for AI REALE
    verified = await db.ai_connections.count_documents(
        {"organization_id": DEFAULT_ORG_ID, "verified": True, "active": True})
    budget = await db.budgets.find_one({"id": DEFAULT_ORG_ID})
    s["can_enable_real_mode"] = verified > 0 and bool(budget and budget.get("general_limit", 0) > 0)
    s["verified_connections"] = verified
    s["budget_configured"] = bool(budget and budget.get("general_limit", 0) > 0)
    return s


@router.put("/real-mode")
async def set_real_mode(body: RealModeBody, user: dict = Depends(require_roles("ADMIN"))):
    if body.enable:
        verified = await db.ai_connections.count_documents(
            {"organization_id": DEFAULT_ORG_ID, "verified": True, "active": True})
        budget = await db.budgets.find_one({"id": DEFAULT_ORG_ID})
        if verified == 0:
            raise HTTPException(status_code=400, detail="Serve almeno una connessione AI verificata.")
        if not (budget and budget.get("general_limit", 0) > 0):
            raise HTTPException(status_code=400, detail="Serve un budget configurato.")
        if not body.confirm:
            raise HTTPException(status_code=400, detail="Conferma esplicita richiesta per attivare AI REALE.")
    await db.settings.update_one(
        {"id": DEFAULT_ORG_ID},
        {"$set": {"id": DEFAULT_ORG_ID, "ai_real_mode": body.enable, "updated_at": now_iso(),
                  "updated_by": user["id"]}},
        upsert=True,
    )
    await log_audit(org_id=DEFAULT_ORG_ID, user=user, action="SET_AI_REAL_MODE",
                    entity_type="settings", entity_id=DEFAULT_ORG_ID,
                    details={"ai_real_mode": body.enable})
    return {"ai_real_mode": body.enable,
            "note": "L'attivazione non effettua alcuna chiamata automatica."}
