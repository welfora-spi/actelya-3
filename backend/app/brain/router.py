"""Brain — endpoint HTTP dell'integrazione verticale minima. Espone SOLO la
creazione del piano arricchita dal brain; lettura/approvazione/esecuzione
restano sugli endpoint gia' esistenti di m2/engine.py (router /m2/plans/...),
qui MAI duplicati ne' modificati."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import DEFAULT_ORG_ID
from ..db import db as _global_db
from ..deps import require_roles, get_current_user
from .service import create_plan_with_brain
from .agents.agent_map import agent_groups, COORDINATOR_FRONTEND_ID
from . import skills as skills_registry

router = APIRouter(prefix="/brain", tags=["brain"])


@router.get("/agents")
async def http_list_agents(user: dict = Depends(get_current_user)):
    """Fonte canonica backend degli agenti selezionabili dal Brain: agent_id,
    ruolo, capability, skill (con stato REAL/M2_SIMULATION/NOT_CONFIGURED/
    UNAVAILABLE per QUESTA organizzazione), missione, criteri di qualita',
    esclusioni. frontend/agentRegistry.js resta l'unica fonte del layout
    visivo (posizioni/seat), ma id/ruolo/capability/skill vengono sempre
    letti da qui: nessun secondo elenco agenti mantenuto a mano."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    out = []
    for g in agent_groups():
        mappings_public = []
        skill_ids: list[str] = []
        for m in g.mappings:
            mappings_public.append({
                "capability": m.capability, "m2_agent_id": m.m2_agent_id, "deliverable_type": m.deliverable_type,
                "execution_mode": m.execution_mode, "execution_ready": m.execution_ready,
                "mission": m.mission, "quality_criteria": list(m.quality_criteria),
                "excluded_when": list(m.excluded_when), "data_accessible": list(m.data_accessible),
                "typical_use_cases": m.typical_use_cases, "implementation_note": m.implementation_note,
            })
            skill_ids.extend(m.skills)
        skills_public = []
        for sid in dict.fromkeys(skill_ids):  # dedup preservando l'ordine
            skill = skills_registry.get_skill(sid)
            if not skill:
                continue
            status = await skills_registry.skill_status(skill, org_id, _global_db)
            skills_public.append({**skills_registry.skill_to_public_dict(skill), "status": status})
        out.append({
            "agent_id": g.frontend_agent_id, "role_name": g.role_name,
            "capabilities": list(g.capabilities), "mappings": mappings_public, "skills": skills_public,
        })
    out.append({
        "agent_id": COORDINATOR_FRONTEND_ID, "role_name": "Coordinatore ACTELYA",
        "capabilities": [], "mappings": [], "skills": [],
        "note": "Sempre presente, non fa mai parte di activeAgentIds.",
    })
    return {"agents": out}


class ClarificationAnswers(BaseModel):
    # Stesso ordine/lunghezza delle domande a cui rispondono (missing_information
    # e clarifying_questions della risposta NEEDS_CLARIFICATION precedente):
    # nomi di campo coerenti con quelli già usati da planning/agent_selector.py
    # e brain/context.py, mai rinominati qui.
    missing_information: list[str] = []
    questions: list[str] = []
    answers: list[str] = []


class GoalBody(BaseModel):
    text: str
    session_id: Optional[str] = None
    clarification: Optional[ClarificationAnswers] = None


@router.post("/plans")
async def http_create_plan_with_brain(body: GoalBody, user: dict = Depends(require_roles("OPERATORE", "ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    clarification = body.clarification.dict() if body.clarification else None
    return await create_plan_with_brain(
        _global_db, org_id, user["id"], body.text,
        session_id=body.session_id, clarification=clarification,
    )
