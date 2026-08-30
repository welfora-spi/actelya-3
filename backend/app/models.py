import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    return (prefix + "-" if prefix else "") + uuid.uuid4().hex[:20]


def base_record(org_id: str, user_id: str) -> dict:
    """Common fields required on every domain record."""
    ts = now_iso()
    return {
        "organization_id": org_id,
        "created_by": user_id,
        "updated_by": user_id,
        "created_at": ts,
        "updated_at": ts,
        "change_history": [],
    }


def touch(record: dict, user_id: str, change: str | None = None) -> dict:
    record["updated_by"] = user_id
    record["updated_at"] = now_iso()
    if change:
        record.setdefault("change_history", []).append(
            {"at": now_iso(), "by": user_id, "change": change}
        )
    return record


# ---------- State enums (as constants) ----------
EXECUTION_STATUS = ["IN_CODA", "IN_ESECUZIONE", "COMPLETATA", "FALLITA", "ARRESTATA"]
DELIVERABLE_STATUS = ["COMPLETATO", "COMPLETATO_CON_AVVISI", "BLOCCATO"]
ACTION_STATUS = ["NON_RICHIESTA", "IN_ATTESA_APPROVAZIONE", "AUTORIZZATA", "BLOCCATA", "ESEGUITA", "FALLITA"]
INTENT_TYPES = ["PRODUZIONE", "AZIONE_ESTERNA", "MISTO", "AMBIGUO"]
INTEGRATION_STATUS = ["NON_CONFIGURATA", "CONFIGURATA", "VERIFICATA", "ERRORE", "DISATTIVATA"]
