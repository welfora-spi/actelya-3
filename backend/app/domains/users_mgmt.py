from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from bson import ObjectId
import json

from ..db import db
from ..deps import get_current_user, require_roles
from ..audit import log_audit
from ..security import hash_password
from ..models import now_iso
from ..config import DEFAULT_ORG_ID, ROLES

router = APIRouter(prefix="/users", tags=["users"])


class CreateUserBody(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    role: str
    password: str = Field(min_length=8)
    active: bool = True


class UpdateUserBody(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    notification_prefs: Optional[dict] = None


def _public(u: dict) -> dict:
    return {
        "id": str(u["_id"]),
        "first_name": u.get("first_name", ""),
        "last_name": u.get("last_name", ""),
        "email": u["email"],
        "role": u.get("role"),
        "active": u.get("active", True),
        "last_login": u.get("last_login"),
        "permissions": u.get("permissions", []),
        "notification_prefs": u.get("notification_prefs", {"email": True, "in_app": True}),
        "created_at": u.get("created_at"),
    }


@router.get("")
async def list_users(user: dict = Depends(get_current_user)):
    users = await db.users.find({"organization_id": DEFAULT_ORG_ID}).to_list(500)
    return [_public(u) for u in users]


@router.post("")
async def create_user(body: CreateUserBody, user: dict = Depends(require_roles("ADMIN"))):
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail="Ruolo non valido")
    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email già registrata")
    doc = {
        "first_name": body.first_name, "last_name": body.last_name, "email": email,
        "role": body.role, "active": body.active,
        "password_hash": hash_password(body.password),
        "must_change_password": True,
        "organization_id": DEFAULT_ORG_ID,
        "permissions": [], "notification_prefs": {"email": True, "in_app": True},
        "last_login": None, "created_by": user["id"], "updated_by": user["id"],
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    res = await db.users.insert_one(doc)
    doc["_id"] = res.inserted_id
    await log_audit(org_id=DEFAULT_ORG_ID, user=user, action="CREATE_USER",
                    entity_type="user", entity_id=str(res.inserted_id),
                    details={"email": email, "role": body.role})
    return _public(doc)


@router.put("/{user_id}")
async def update_user(user_id: str, body: UpdateUserBody, user: dict = Depends(require_roles("ADMIN"))):
    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "role" in updates and updates["role"] not in ROLES:
        raise HTTPException(status_code=400, detail="Ruolo non valido")
    updates["updated_at"] = now_iso()
    updates["updated_by"] = user["id"]
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
    await log_audit(org_id=DEFAULT_ORG_ID, user=user, action="UPDATE_USER",
                    entity_type="user", entity_id=user_id, details=updates)
    out = await db.users.find_one({"_id": ObjectId(user_id)})
    return _public(out)


@router.get("/{user_id}/export")
async def export_user(user_id: str, user: dict = Depends(require_roles("ADMIN"))):
    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    await log_audit(org_id=DEFAULT_ORG_ID, user=user, action="EXPORT_USER_DATA",
                    entity_type="user", entity_id=user_id)
    data = _public(target)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    return Response(content=payload, media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename=user_{user_id}.json"})


@router.delete("/{user_id}")
async def delete_user(user_id: str, confirm: bool = False, user: dict = Depends(require_roles("ADMIN"))):
    if not confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta (confirm=true)")
    target = await db.users.find_one({"_id": ObjectId(user_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    if str(target["_id"]) == user["id"]:
        raise HTTPException(status_code=400, detail="Non puoi eliminare il tuo stesso account")
    await db.users.delete_one({"_id": ObjectId(user_id)})
    await log_audit(org_id=DEFAULT_ORG_ID, user=user, action="DELETE_USER",
                    entity_type="user", entity_id=user_id, details={"email": target["email"]})
    return {"ok": True}
