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


class DiscoveryRealFetchBody(BaseModel):
    enable: bool
    confirm: bool = False


@router.get("")
async def get_settings(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    s = await db.settings.find_one({"id": org_id}, {"_id": 0}) or {
        "id": org_id, "ai_real_mode": False}
    # Report readiness conditions for AI REALE
    verified = await db.ai_connections.count_documents(
        {"organization_id": org_id, "verified": True, "active": True})
    budget = await db.budgets.find_one({"id": org_id})
    s["can_enable_real_mode"] = verified > 0 and bool(budget and budget.get("general_limit", 0) > 0)
    s["verified_connections"] = verified
    s["budget_configured"] = bool(budget and budget.get("general_limit", 0) > 0)
    s["discovery_real_fetch"] = bool(s.get("discovery_real_fetch"))
    return s


@router.put("/real-mode")
async def set_real_mode(body: RealModeBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    if body.enable:
        verified = await db.ai_connections.count_documents(
            {"organization_id": org_id, "verified": True, "active": True})
        budget = await db.budgets.find_one({"id": org_id})
        if verified == 0:
            raise HTTPException(status_code=400, detail="Serve almeno una connessione AI verificata.")
        if not (budget and budget.get("general_limit", 0) > 0):
            raise HTTPException(status_code=400, detail="Serve un budget configurato.")
        if not body.confirm:
            raise HTTPException(status_code=400, detail="Conferma esplicita richiesta per attivare AI REALE.")
    await db.settings.update_one(
        {"id": org_id},
        {"$set": {"id": org_id, "ai_real_mode": body.enable, "updated_at": now_iso(),
                  "updated_by": user["id"]}},
        upsert=True,
    )
    await log_audit(org_id=org_id, user=user, action="SET_AI_REAL_MODE",
                    entity_type="settings", entity_id=org_id,
                    details={"ai_real_mode": body.enable})
    return {"ai_real_mode": body.enable,
            "note": "L'attivazione non effettua alcuna chiamata automatica."}


@router.put("/discovery-real-fetch")
async def set_discovery_real_fetch(body: DiscoveryRealFetchBody, user: dict = Depends(require_roles("ADMIN"))):
    """Permesso SPECIFICO per la sola lettura HTTP reale della pagina
    pubblica dichiarata da Discovery (domains/discovery.py::fetch_sito_reale)
    — indipendente dall'interruttore globale REAL_EXTERNAL_ACTIONS (che
    resta quello che governa connettori/pubblicazione social) e non
    richiede alcuna connessione AI ne' budget (nessuna chiamata LLM
    coinvolta, nessun costo): un GET HTTP verso l'URL gia' dichiarato
    dall'organizzazione, con le stesse protezioni SSRF applicate ad ogni
    hop. Confermato esplicitamente come ogni altro interruttore reale del
    progetto — mai un'attivazione implicita."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    if body.enable and not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta per attivare la lettura reale del sito in Discovery.")
    await db.settings.update_one(
        {"id": org_id},
        {"$set": {"id": org_id, "discovery_real_fetch": body.enable, "updated_at": now_iso(),
                  "updated_by": user["id"]}},
        upsert=True,
    )
    await log_audit(org_id=org_id, user=user, action="SET_DISCOVERY_REAL_FETCH",
                    entity_type="settings", entity_id=org_id,
                    details={"discovery_real_fetch": body.enable})
    return {"discovery_real_fetch": body.enable,
            "note": "Nessuna chiamata AI, nessun costo: solo lettura HTTP pubblica del sito gia' dichiarato."}
