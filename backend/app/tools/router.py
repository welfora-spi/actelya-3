"""Professional Tool Registry — endpoint HTTP di sola lettura. Nessun
segreto qui: solo metadati del catalogo + stato calcolato per
l'organizzazione corrente. Il frontend legge SEMPRE da qui, mai una copia
duplicata lato client."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..audit import log_audit
from ..config import DEFAULT_ORG_ID
from ..db import db
from ..deps import get_current_user, require_roles
from . import cost_ledger
from . import registry as tool_registry
from .status import computed_status_for

router = APIRouter(prefix="/tool-registry", tags=["tool-registry"])


class BudgetBody(BaseModel):
    daily_cap_usd: Optional[float] = None


@router.get("/budget")
async def get_budget(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    cap = await cost_ledger.get_daily_cap(db, org_id)
    speso = await cost_ledger.spent_today(db, org_id)
    return {"daily_cap_usd": cap, "spent_today_usd": speso}


@router.put("/budget")
async def set_budget(body: BudgetBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    if body.daily_cap_usd is not None and body.daily_cap_usd < 0:
        raise HTTPException(status_code=400, detail="Il tetto di spesa non può essere negativo.")
    await cost_ledger.set_daily_cap(db, org_id, body.daily_cap_usd, actor=user["id"])
    await log_audit(org_id=org_id, user=user, action="TOOL_BUDGET_UPDATED",
                    entity_type="organization_budget", entity_id=org_id,
                    details={"daily_cap_usd": body.daily_cap_usd})
    return {"daily_cap_usd": body.daily_cap_usd}


@router.get("")
async def list_tools(agent_id: Optional[str] = None, category: Optional[str] = None,
                     user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    tools = tool_registry.TOOLS.values()
    if agent_id:
        tools = [t for t in tools if agent_id in t.allowed_agents]
    if category:
        tools = [t for t in tools if t.category == category]
    tools = sorted(tools, key=lambda t: (t.category, t.priority))
    out = []
    for t in tools:
        stato = await computed_status_for(t, org_id, db)
        out.append(tool_registry.to_public_dict(t, computed_status=stato))
    return {"tools": out, "categories": list(tool_registry.all_categories()), "version": tool_registry.REGISTRY_VERSION}


@router.get("/{tool_id}")
async def get_tool(tool_id: str, user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    t = tool_registry.get_tool(tool_id)
    if not t:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Strumento non presente nel registro.")
    stato = await computed_status_for(t, org_id, db)
    return tool_registry.to_public_dict(t, computed_status=stato)
