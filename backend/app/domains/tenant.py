"""Registrazione self-service: crea un nuovo tenant (organizzazione) isolato e il
suo primo utente ADMIN (il CEO/imprenditore che si registra). Punto di ingresso
pubblico (nessuna autenticazione richiesta) — distinto da /users (creazione utenti
in un'organizzazione già esistente, riservata ad ADMIN)."""
from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel, EmailStr, Field
from typing import List

from ..db import db
from ..deps import rate_limit
from ..audit import log_audit
from ..security import hash_password, create_access_token, create_refresh_token, set_auth_cookies
from ..models import now_iso, new_id, base_record
from .knowledge import write_fact

router = APIRouter(prefix="/tenant", tags=["tenant"])


class RegisterBody(BaseModel):
    company_name: str = Field(min_length=1)
    sector: str = ""
    website: str = ""
    social_links: List[str] = []
    primary_goal: str = ""
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)


@router.post("/register")
async def register(body: RegisterBody, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    rate_limit(f"register:{ip}", max_calls=10, window_seconds=60)

    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email già registrata")

    org_id = new_id("org")

    user_doc = {
        "email": email, "password_hash": hash_password(body.password),
        "first_name": body.first_name.strip(), "last_name": body.last_name.strip(), "role": "ADMIN",
        "active": True, "must_change_password": False,
        "organization_id": org_id, "permissions": [],
        "notification_prefs": {"email": True, "in_app": True},
        "last_login": None, "created_at": now_iso(), "updated_at": now_iso(),
        "created_by": "self", "updated_by": "self", "change_history": [],
    }
    res = await db.users.insert_one(user_doc)
    user_id = str(res.inserted_id)
    await db.users.update_one({"_id": res.inserted_id}, {"$set": {"created_by": user_id, "updated_by": user_id}})

    org = base_record(org_id, user_id)
    org.update({
        "id": org_id,
        "ragione_sociale": body.company_name.strip(), "nome_commerciale": body.company_name.strip(),
        "settore": body.sector.strip(), "sito_web": body.website.strip(),
        "canali_utilizzati": ", ".join(s.strip() for s in body.social_links if s.strip()),
        "obiettivi_commerciali": body.primary_goal.strip(),
        "onboarding_status": "IN_CORSO",
    })
    await db.organizations.insert_one(org)

    # Declared facts (highest non-verified priority): the CEO stated these directly.
    declared = {
        "ragione_sociale": body.company_name, "settore": body.sector, "sito_web": body.website,
        "obiettivi_commerciali": body.primary_goal,
    }
    for field, value in declared.items():
        if value.strip():
            await write_fact(db, org_id=org_id, user_id=user_id, field=field, value=value,
                             source="onboarding_ceo", method="DICHIARATO", confidence=0.9)
    for i, link in enumerate(s.strip() for s in body.social_links if s.strip()):
        await write_fact(db, org_id=org_id, user_id=user_id, field=f"social_link_{i}", value=link,
                         source="onboarding_ceo", method="DICHIARATO", confidence=0.9)

    access = create_access_token(user_id, email, "ADMIN")
    refresh = create_refresh_token(user_id)
    set_auth_cookies(response, access, refresh)

    await log_audit(org_id=org_id, user={"email": email, "id": user_id}, action="REGISTER_TENANT",
                    entity_type="organization", entity_id=org_id,
                    details={"company_name": body.company_name, "sector": body.sector})

    return {
        "user": {
            "id": user_id, "email": email, "first_name": user_doc["first_name"],
            "last_name": user_doc["last_name"], "role": "ADMIN", "active": True,
            "must_change_password": False, "organization_id": org_id,
        },
        "access_token": access, "organization_id": org_id,
    }
