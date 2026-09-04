from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from ..db import db
from ..deps import get_current_user, require_roles
from ..audit import log_audit
from ..models import now_iso, base_record, touch
from ..config import DEFAULT_ORG_ID

router = APIRouter(prefix="/org", tags=["organization"])

PROFILE_FIELDS = [
    "ragione_sociale", "nome_commerciale", "settore", "descrizione_attivita",
    "prodotti_servizi", "proposta_valore", "pubblico_target", "territori_serviti",
    "tono_di_voce", "linee_guida_brand", "obiettivi_commerciali", "canali_utilizzati",
    "sito_web", "contatti_aziendali", "firma_email", "disclaimer",
    "informazioni_compliance", "limiti_operativi", "attivita_vietate", "budget",
    "orari", "kpi_principali",
]


class ProfileBody(BaseModel):
    ragione_sociale: Optional[str] = ""
    nome_commerciale: Optional[str] = ""
    settore: Optional[str] = ""
    descrizione_attivita: Optional[str] = ""
    prodotti_servizi: Optional[str] = ""
    proposta_valore: Optional[str] = ""
    pubblico_target: Optional[str] = ""
    territori_serviti: Optional[str] = ""
    tono_di_voce: Optional[str] = ""
    linee_guida_brand: Optional[str] = ""
    obiettivi_commerciali: Optional[str] = ""
    canali_utilizzati: Optional[str] = ""
    sito_web: Optional[str] = ""
    contatti_aziendali: Optional[str] = ""
    firma_email: Optional[str] = ""
    disclaimer: Optional[str] = ""
    informazioni_compliance: Optional[str] = ""
    limiti_operativi: Optional[str] = ""
    attivita_vietate: Optional[str] = ""
    budget: Optional[str] = ""
    orari: Optional[str] = ""
    kpi_principali: Optional[str] = ""


@router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    doc = await db.organizations.find_one({"id": org_id}, {"_id": 0})
    if not doc:
        doc = {"id": org_id, **{f: "" for f in PROFILE_FIELDS}}
    return doc


@router.put("/profile")
async def update_profile(body: ProfileBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    existing = await db.organizations.find_one({"id": org_id})
    data = body.model_dump()
    if existing:
        touch(existing, user["id"], "Aggiornato profilo aziendale")
        existing.update(data)
        await db.organizations.replace_one({"id": org_id}, existing)
    else:
        rec = base_record(org_id, user["id"])
        rec.update({"id": org_id, **data})
        await db.organizations.insert_one(rec)
    await log_audit(org_id=org_id, user=user, action="UPDATE_PROFILE",
                    entity_type="organization", entity_id=org_id)
    out = await db.organizations.find_one({"id": org_id}, {"_id": 0})
    return out
