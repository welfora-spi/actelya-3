from .db import db
from .models import new_id, now_iso

# Keys that must NEVER be written to the audit log.
_FORBIDDEN = {"api_key", "password", "password_hash", "access_token", "refresh_token",
              "authorization", "secret", "api_key_encrypted"}


def _sanitize(data):
    if isinstance(data, dict):
        return {k: ("[REDACTED]" if k.lower() in _FORBIDDEN else _sanitize(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [_sanitize(v) for v in data]
    return data


async def log_audit(*, org_id: str, user, action: str, entity_type: str = "",
                    entity_id: str = "", details: dict | None = None, status: str = "OK",
                    reason: str = ""):
    actor = "system"
    if isinstance(user, dict):
        actor = user.get("email") or user.get("id") or "system"
    entry = {
        "id": new_id("audit"),
        "organization_id": org_id,
        "actor": actor,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "details": _sanitize(details or {}),
        "status": status,
        "reason": reason,
        "at": now_iso(),
    }
    await db.audit_logs.insert_one(entry)
    entry.pop("_id", None)
    return entry
