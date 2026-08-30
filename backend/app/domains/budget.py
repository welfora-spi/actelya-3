from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..db import db
from ..deps import require_roles, get_current_user
from ..audit import log_audit
from ..models import now_iso
from ..config import DEFAULT_ORG_ID

router = APIRouter(prefix="/budget", tags=["budget"])


class BudgetBody(BaseModel):
    general_limit: float
    daily_limit: float = 0.0


@router.get("")
async def get_budget(user: dict = Depends(get_current_user)):
    b = await db.budgets.find_one({"id": DEFAULT_ORG_ID}, {"_id": 0}) or {
        "id": DEFAULT_ORG_ID, "general_limit": 0.0, "daily_limit": 0.0}
    spent_rows = await db.executions.find(
        {"organization_id": DEFAULT_ORG_ID}, {"_id": 0, "real_cost": 1}).to_list(1000)
    spent = round(sum(r.get("real_cost", 0.0) for r in spent_rows), 6)
    b["spent_simulated"] = spent
    b["residual"] = round(b.get("general_limit", 0.0) - spent, 6)
    b["mode"] = "SIMULAZIONE"
    return b


@router.put("")
async def set_budget(body: BudgetBody, user: dict = Depends(require_roles("ADMIN"))):
    await db.budgets.update_one(
        {"id": DEFAULT_ORG_ID},
        {"$set": {"id": DEFAULT_ORG_ID, "general_limit": body.general_limit,
                  "daily_limit": body.daily_limit, "updated_at": now_iso(), "updated_by": user["id"]}},
        upsert=True,
    )
    await log_audit(org_id=DEFAULT_ORG_ID, user=user, action="SET_BUDGET",
                    entity_type="budget", entity_id=DEFAULT_ORG_ID,
                    details={"general_limit": body.general_limit, "daily_limit": body.daily_limit})
    return await get_budget(user)
