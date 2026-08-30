"""Brain — endpoint HTTP dell'integrazione verticale minima. Espone SOLO la
creazione del piano arricchita dal brain; lettura/approvazione/esecuzione
restano sugli endpoint gia' esistenti di m2/engine.py (router /m2/plans/...),
qui MAI duplicati ne' modificati."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import DEFAULT_ORG_ID
from ..db import db as _global_db
from ..deps import require_roles
from ..m2.engine import _assert_simulation
from .service import create_plan_with_brain

router = APIRouter(prefix="/brain", tags=["brain"])


class GoalBody(BaseModel):
    text: str


@router.post("/plans")
async def http_create_plan_with_brain(body: GoalBody, user: dict = Depends(require_roles("OPERATORE", "ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    await _assert_simulation(org_id)  # riusato da m2/engine.py: stesso blocco sicuro, nessuna duplicazione
    return await create_plan_with_brain(_global_db, org_id, user["id"], body.text)
