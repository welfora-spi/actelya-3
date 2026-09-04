"""Onboarding CEO: stato guidato del primo utilizzo. Non raccoglie dati esso stesso
(la registrazione già dichiara i fatti base, la Discovery li arricchisce): espone
solo cosa manca/e' in conflitto, cosi' il frontend puo' guidare l'utente senza
chiedere di nuovo cio' che il sistema puo' dedurre o verificare da solo."""
from fastapi import APIRouter, Depends, HTTPException

from ..db import db
from ..deps import get_current_user, require_roles
from ..audit import log_audit
from ..models import now_iso
from ..config import DEFAULT_ORG_ID
from .knowledge import current_facts_map

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

CORE_FIELDS = ["ragione_sociale", "settore", "sito_web", "obiettivi_commerciali"]


@router.get("/status")
async def onboarding_status(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0}) or {}
    current = await current_facts_map(db, org_id)
    missing = [f for f in CORE_FIELDS if f not in current or not current[f].get("value")]
    conflicts = await db.facts.count_documents({"organization_id": org_id, "state": "CONTRADDITTORIO"})
    last_discovery = await db.discovery_runs.find_one(
        {"organization_id": org_id}, {"_id": 0}, sort=[("created_at", -1)])
    return {
        "onboarding_status": org.get("onboarding_status", "COMPLETATO"),
        "missing_core_fields": missing,
        "open_conflicts": conflicts,
        "last_discovery_run": last_discovery,
        "ready_to_complete": not missing and conflicts == 0,
    }


@router.post("/complete")
async def complete_onboarding(user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    conflicts = await db.facts.count_documents({"organization_id": org_id, "state": "CONTRADDITTORIO"})
    if conflicts:
        raise HTTPException(status_code=400,
                            detail=f"Risolvi prima {conflicts} contraddizioni nel Fact Ledger.")
    await db.organizations.update_one(
        {"id": org_id},
        {"$set": {"onboarding_status": "COMPLETATO", "updated_at": now_iso(), "updated_by": user["id"]}},
    )
    await log_audit(org_id=org_id, user=user, action="ONBOARDING_COMPLETE",
                    entity_type="organization", entity_id=org_id)
    return {"onboarding_status": "COMPLETATO"}
