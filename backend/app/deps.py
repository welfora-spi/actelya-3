import time
from fastapi import Request, HTTPException, Depends
from bson import ObjectId
from .db import db
from .security import decode_token


def assert_same_org(record: dict | None, user: dict, not_found_detail: str = "Risorsa non trovata"):
    """Tenant isolation guard: 404 (not 403) so cross-tenant probing can't distinguish
    'exists in another org' from 'does not exist'. Mai fidarsi di un id senza questo controllo."""
    if not record or record.get("organization_id") != user.get("organization_id"):
        raise HTTPException(status_code=404, detail=not_found_detail)


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Non autenticato")
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Tipo token non valido")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="Utente non trovato")
        if not user.get("active", True):
            raise HTTPException(status_code=403, detail="Utente disattivato")
        user["id"] = str(user["_id"])
        user.pop("_id", None)
        user.pop("password_hash", None)
        return user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Token non valido o scaduto")


def require_roles(*roles):
    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Autorizzazione insufficiente per questo ruolo")
        return user
    return checker


# ---------- Simple in-memory rate limiter for sensitive endpoints ----------
_buckets: dict[str, list[float]] = {}


def rate_limit(key: str, max_calls: int, window_seconds: int):
    now = time.time()
    arr = [t for t in _buckets.get(key, []) if now - t < window_seconds]
    if len(arr) >= max_calls:
        raise HTTPException(status_code=429, detail="Troppe richieste, riprova più tardi.")
    arr.append(now)
    _buckets[key] = arr
