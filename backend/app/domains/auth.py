from fastapi import APIRouter, Request, Response, HTTPException, Depends
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, timezone
from bson import ObjectId

from ..db import db
from ..config import FRONTEND_URL, ACCESS_TOKEN_MINUTES, REFRESH_TOKEN_DAYS, DEFAULT_ORG_ID
from ..security import (hash_password, verify_password, create_access_token,
                        create_refresh_token, decode_token, set_auth_cookies)
from ..deps import get_current_user, rate_limit
from ..audit import log_audit
from ..models import now_iso

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILED = 5
LOCK_MINUTES = 15


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


def _public_user(u: dict) -> dict:
    return {
        "id": str(u.get("_id") or u.get("id")),
        "email": u["email"],
        "first_name": u.get("first_name", ""),
        "last_name": u.get("last_name", ""),
        "role": u.get("role"),
        "active": u.get("active", True),
        "must_change_password": u.get("must_change_password", False),
        "last_login": u.get("last_login"),
        "organization_id": u.get("organization_id", DEFAULT_ORG_ID),
    }


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    email = body.email.lower().strip()
    rate_limit(f"login:{ip}", max_calls=30, window_seconds=60)

    key = f"{ip}:{email}"
    attempt = await db.login_attempts.find_one({"identifier": key})
    if attempt and attempt.get("count", 0) >= MAX_FAILED:
        locked_at = datetime.fromisoformat(attempt["locked_at"])
        elapsed = (datetime.now(timezone.utc) - locked_at).total_seconds()
        if elapsed < LOCK_MINUTES * 60:
            raise HTTPException(status_code=429, detail="Account temporaneamente bloccato. Riprova più tardi.")
        await db.login_attempts.delete_one({"identifier": key})

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        await db.login_attempts.update_one(
            {"identifier": key},
            {"$inc": {"count": 1}, "$set": {"locked_at": now_iso()}},
            upsert=True,
        )
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Utente disattivato")

    await db.login_attempts.delete_one({"identifier": key})
    uid = str(user["_id"])
    access = create_access_token(uid, user["email"], user["role"])
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login": now_iso()}})
    user["last_login"] = now_iso()
    await log_audit(org_id=user.get("organization_id", DEFAULT_ORG_ID), user=user,
                    action="LOGIN", entity_type="user", entity_id=uid)
    return {"user": _public_user(user), "access_token": access}


@router.post("/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    await log_audit(org_id=user["organization_id"], user=user, action="LOGOUT",
                    entity_type="user", entity_id=user["id"])
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    """Soft auth bootstrap: returns 200 with {"user": null} when not authenticated,
    so the initial app load never triggers a 401 for protected business data."""
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        return {"user": None}
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return {"user": None}
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user or not user.get("active", True):
            return {"user": None}
        return {"user": _public_user(user)}
    except Exception:
        return {"user": None}


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Nessun refresh token")
    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Tipo token non valido")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="Utente non trovato")
        access = create_access_token(str(user["_id"]), user["email"], user["role"])
        response.set_cookie("access_token", access, httponly=True, secure=True,
                            samesite="none", max_age=ACCESS_TOKEN_MINUTES * 60, path="/")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh token non valido")


@router.post("/change-password")
async def change_password(body: ChangePasswordBody, user: dict = Depends(get_current_user)):
    full = await db.users.find_one({"_id": ObjectId(user["id"])})
    if not verify_password(body.current_password, full.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Password attuale non corretta")
    await db.users.update_one(
        {"_id": full["_id"]},
        {"$set": {"password_hash": hash_password(body.new_password),
                  "must_change_password": False, "updated_at": now_iso()}},
    )
    await log_audit(org_id=user["organization_id"], user=user, action="CHANGE_PASSWORD",
                    entity_type="user", entity_id=user["id"])
    return {"ok": True}
