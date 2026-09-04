"""Connessioni provider video generativo (Runway) -- pagina Connessioni e API.

A differenza di Requesty (portato 1:1 da ACTELYA v1, chiave nel Credential
Manager di Windows), la chiave Runway vive cifrata LATO SERVER (Fernet +
MASTER_KEY, vedi app/security.py -- stesso meccanismo gia' usato per gli altri
provider AI diretti in domains/connections.py): mai in chiaro in Mongo, mai
restituita per intero al frontend, mai in un log o nell'audit."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..db import db
from ..deps import get_current_user, require_roles, rate_limit, assert_same_org
from ..audit import log_audit
from ..security import encrypt_secret, decrypt_secret, mask_secret, vault_available
from ..models import now_iso, base_record, new_id, touch
from ..config import DEFAULT_ORG_ID
from ..integrations import runway_gateway

router = APIRouter(prefix="/video-connections", tags=["video-connections"])

PROVIDER_TYPES = ["runway"]


class VideoConnectionBody(BaseModel):
    name: str
    provider_type: str = "runway"
    api_key: Optional[str] = None
    effective_model: str = "gen4.5"
    default_ratio: str = "720:1280"  # 9:16 verticale, coerente col reel (vedi domains/reel.py)
    max_cost_per_generation: float = 20.0  # tetto in CREDITI Runway, mai un $ inventato
    timeout: int = 60
    active: bool = True
    priority: int = 1


def _public(c: dict) -> dict:
    return {
        "id": c["id"], "name": c["name"], "provider_type": c["provider_type"],
        "api_key_masked": c.get("api_key_masked", ""), "has_key": bool(c.get("api_key_encrypted")),
        "effective_model": c.get("effective_model", ""), "default_ratio": c.get("default_ratio", "720:1280"),
        "max_cost_per_generation": c.get("max_cost_per_generation", 20.0),
        "timeout": c.get("timeout", 60), "active": c.get("active", True), "priority": c.get("priority", 1),
        "last_test_at": c.get("last_test_at"), "last_test_result": c.get("last_test_result"),
        "credit_balance_ultima_verifica": c.get("credit_balance_ultima_verifica"),
        "verified": c.get("verified", False),
    }


@router.get("")
async def list_video_connections(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.video_connections.find({"organization_id": org_id}, {"_id": 0}).to_list(50)
    return [_public(c) for c in rows]


@router.post("")
async def create_video_connection(body: VideoConnectionBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    if body.provider_type not in PROVIDER_TYPES:
        raise HTTPException(status_code=400, detail="Tipo provider video non supportato")
    if body.api_key and not vault_available():
        raise HTTPException(status_code=503, detail="MASTER_KEY non configurata: impossibile salvare segreti in modo sicuro.")
    rec = base_record(org_id, user["id"])
    rec.update({
        "id": new_id("vidconn"), "name": body.name, "provider_type": body.provider_type,
        "effective_model": body.effective_model, "default_ratio": body.default_ratio,
        "max_cost_per_generation": body.max_cost_per_generation, "timeout": body.timeout,
        "active": body.active, "priority": body.priority,
        "last_test_at": None, "last_test_result": None, "credit_balance_ultima_verifica": None,
        "verified": False, "api_key_encrypted": None, "api_key_masked": "",
    })
    if body.api_key:
        rec["api_key_encrypted"] = encrypt_secret(body.api_key)
        rec["api_key_masked"] = mask_secret(body.api_key)
    await db.video_connections.insert_one(rec)
    await log_audit(org_id=org_id, user=user, action="CREATE_VIDEO_CONNECTION",
                    entity_type="video_connection", entity_id=rec["id"],
                    details={"name": body.name, "provider_type": body.provider_type})
    return _public(rec)


@router.put("/{conn_id}")
async def update_video_connection(conn_id: str, body: VideoConnectionBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    c = await db.video_connections.find_one({"id": conn_id})
    assert_same_org(c, user, "Connessione video non trovata")
    data = body.model_dump()
    api_key = data.pop("api_key", None)
    c.update(data)
    c["verified"] = False  # config cambiata -> va ritestata
    if api_key:
        if not vault_available():
            raise HTTPException(status_code=503, detail="MASTER_KEY non configurata.")
        c["api_key_encrypted"] = encrypt_secret(api_key)
        c["api_key_masked"] = mask_secret(api_key)
    touch(c, user["id"], "Aggiornata connessione video")
    await db.video_connections.replace_one({"id": conn_id}, c)
    await log_audit(org_id=org_id, user=user, action="UPDATE_VIDEO_CONNECTION",
                    entity_type="video_connection", entity_id=conn_id, details={"api_key_changed": bool(api_key)})
    return _public(c)


@router.delete("/{conn_id}")
async def delete_video_connection(conn_id: str, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    c = await db.video_connections.find_one({"id": conn_id})
    assert_same_org(c, user, "Connessione video non trovata")
    await db.video_connections.delete_one({"id": conn_id})
    await log_audit(org_id=org_id, user=user, action="DELETE_VIDEO_CONNECTION", entity_type="video_connection", entity_id=conn_id)
    return {"ok": True}


class TestConfirmBody(BaseModel):
    confirm: bool = False


@router.post("/{conn_id}/test")
async def test_video_connection(conn_id: str, body: TestConfirmBody, user: dict = Depends(require_roles("ADMIN"))):
    """Test diagnostico reale (organization.retrieve(): sola lettura del saldo
    crediti, nessuna generazione, costo $0) -- richiede comunque conferma
    esplicita: nessuna chiamata esterna parte mai senza un comando esplicito,
    indipendentemente dal suo costo."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rate_limit(f"testvideoconn:{conn_id}", max_calls=5, window_seconds=60)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta")
    c = await db.video_connections.find_one({"id": conn_id})
    assert_same_org(c, user, "Connessione video non trovata")
    if not c.get("api_key_encrypted"):
        raise HTTPException(status_code=400, detail="Nessuna API key configurata su questa connessione.")
    api_key = decrypt_secret(c["api_key_encrypted"])

    risultato = runway_gateway.test_diagnostico(api_key)
    now_verified = risultato.esito == "OK"
    await db.video_connections.update_one(
        {"id": conn_id},
        {"$set": {"last_test_at": now_iso(),
                  "last_test_result": "OK_REALE" if now_verified else f"ERRORE_{risultato.codice_errore}",
                  "credit_balance_ultima_verifica": risultato.credit_balance,
                  "verified": now_verified, "updated_at": now_iso()}},
    )
    await log_audit(org_id=org_id, user=user, action="TEST_VIDEO_CONNECTION",
                    entity_type="video_connection", entity_id=conn_id,
                    details={"esito": risultato.esito, "codice_errore": risultato.codice_errore,
                             "latenza_ms": risultato.latenza_ms})
    return {"mode": "REALE", **risultato.come_dict()}
