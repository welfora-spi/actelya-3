"""Connessioni Meta (Facebook Page + Instagram Business) — item 4/5/11/12/14,
DECISIONE UFFICIALE "100% REALE". Stesso pattern ESATTO di
domains/video_connections.py (Runway): multi-tenant, chiave cifrata lato
server (Fernet + MASTER_KEY, app/security.py), mai in chiaro in Mongo, mai
restituita per intero al frontend, mai in un log o nell'audit — nessuna
architettura parallela, lo stesso meccanismo gia' verificato per Requesty/
Runway, solo applicato a un terzo provider.

Multi-tenant per costruzione (item 14): ogni organizzazione ha le proprie
righe in 'meta_connections' (organization_id, come ogni altra collezione
dell'app) — MAI un singleton globale legato a una sola azienda, MAI un
fallback a variabili d'ambiente per le credenziali (che sarebbe per
definizione process-wide, non per-organizzazione: sbagliato in un sistema
multi-tenant). Le SOLE variabili d'ambiente coinvolte nel percorso reale
sono quelle di brain/config.py (REAL_EXTERNAL_ACTIONS, CONNECTOR_MODE — un
interruttore di sicurezza globale, mai una credenziale) e
PUBLIC_BACKEND_URL (per rendere pubblicamente raggiungibili gli asset
serviti da questo stesso backend, vedi _resolve_public_asset_url() in
social_publishing.py): ogni credenziale Meta vera e propria (access token,
app secret) passa SEMPRE da qui, cifrata per organizzazione."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import db
from ..deps import get_current_user, require_roles, rate_limit, assert_same_org
from ..audit import log_audit
from ..security import encrypt_secret, decrypt_secret, mask_secret, vault_available
from ..models import now_iso, base_record, new_id, touch
from ..config import DEFAULT_ORG_ID
from ..integrations.meta import auth as meta_auth
from ..integrations.meta.errors import MetaConnectorError

router = APIRouter(prefix="/meta-connections", tags=["meta-connections"])
status_router = APIRouter(prefix="/social/connectors/meta", tags=["meta-connections"])

DEFAULT_GRAPH_API_VERSION = "v21.0"

# Stati di connessione mostrabili in UI (item 11): mai il token, mai un
# dettaglio tecnico grezzo — solo uno di questi 6 valori espliciti.
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_INVALID = "INVALID"
STATUS_CONNECTED = "CONNECTED"
STATUS_EXPIRED = "EXPIRED"
STATUS_MISSING_PERMISSION = "MISSING_PERMISSION"
STATUS_ERROR = "ERROR"


class MetaConnectionBody(BaseModel):
    name: str
    mode: str = "dry_run"  # "dry_run" | "real" — preferenza PER QUESTA connessione (comunque subordinata ai gate globali)
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    access_token: Optional[str] = None  # Page/User token a lunga scadenza
    page_id: Optional[str] = None
    instagram_business_account_id: Optional[str] = None
    graph_api_version: str = DEFAULT_GRAPH_API_VERSION
    active: bool = True


def _public(c: dict) -> dict:
    return {
        "id": c["id"], "name": c["name"], "mode": c.get("mode", "dry_run"),
        "has_access_token": bool(c.get("access_token_encrypted")),
        "access_token_masked": c.get("access_token_masked", ""),
        "has_app_secret": bool(c.get("app_secret_encrypted")),
        "app_id": c.get("app_id", ""), "page_id": c.get("page_id", ""),
        "page_name": c.get("page_name", ""),
        "instagram_business_account_id": c.get("instagram_business_account_id", ""),
        "instagram_username": c.get("instagram_username", ""),
        "graph_api_version": c.get("graph_api_version", DEFAULT_GRAPH_API_VERSION),
        "active": c.get("active", True),
        "facebook_status": c.get("facebook_status", STATUS_NOT_CONFIGURED),
        "instagram_status": c.get("instagram_status", STATUS_NOT_CONFIGURED),
        "last_test_at": c.get("last_test_at"), "last_test_result": c.get("last_test_result"),
        "created_at": c.get("created_at"), "updated_at": c.get("updated_at"),
    }


@router.get("")
async def list_meta_connections(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.meta_connections.find({"organization_id": org_id}, {"_id": 0}).to_list(20)
    return [_public(c) for c in rows]


@router.post("")
async def create_meta_connection(body: MetaConnectionBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    if body.mode not in ("dry_run", "real"):
        raise HTTPException(status_code=422, detail="mode deve essere 'dry_run' o 'real'.")
    if (body.access_token or body.app_secret) and not vault_available():
        raise HTTPException(status_code=503, detail="MASTER_KEY non configurata: impossibile salvare segreti in modo sicuro.")
    rec = base_record(org_id, user["id"])
    rec.update({
        "id": new_id("metaconn"), "name": body.name, "mode": body.mode,
        "app_id": body.app_id or "", "app_secret_encrypted": None,
        "access_token_encrypted": None, "access_token_masked": "",
        "page_id": body.page_id or "", "page_name": "",
        "instagram_business_account_id": body.instagram_business_account_id or "", "instagram_username": "",
        "graph_api_version": body.graph_api_version or DEFAULT_GRAPH_API_VERSION, "active": body.active,
        "facebook_status": STATUS_NOT_CONFIGURED, "instagram_status": STATUS_NOT_CONFIGURED,
        "last_test_at": None, "last_test_result": None,
    })
    if body.access_token:
        rec["access_token_encrypted"] = encrypt_secret(body.access_token)
        rec["access_token_masked"] = mask_secret(body.access_token)
    if body.app_secret:
        rec["app_secret_encrypted"] = encrypt_secret(body.app_secret)
    await db.meta_connections.insert_one(rec)
    await log_audit(org_id=org_id, user=user, action="CREATE_META_CONNECTION",
                    entity_type="meta_connection", entity_id=rec["id"], details={"name": body.name, "mode": body.mode})
    return _public(rec)


@router.put("/{conn_id}")
async def update_meta_connection(conn_id: str, body: MetaConnectionBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    c = await db.meta_connections.find_one({"id": conn_id})
    assert_same_org(c, user, "Connessione Meta non trovata")
    if body.mode not in ("dry_run", "real"):
        raise HTTPException(status_code=422, detail="mode deve essere 'dry_run' o 'real'.")
    data = body.model_dump()
    access_token = data.pop("access_token", None)
    app_secret = data.pop("app_secret", None)
    c.update(data)
    # Config cambiata -> va riverificata: mai uno stato CONNECTED che
    # descrive credenziali/pagina/account gia' superati.
    c["facebook_status"] = STATUS_NOT_CONFIGURED
    c["instagram_status"] = STATUS_NOT_CONFIGURED
    if access_token or app_secret:
        if not vault_available():
            raise HTTPException(status_code=503, detail="MASTER_KEY non configurata.")
    if access_token:
        c["access_token_encrypted"] = encrypt_secret(access_token)
        c["access_token_masked"] = mask_secret(access_token)
    if app_secret:
        c["app_secret_encrypted"] = encrypt_secret(app_secret)
    touch(c, user["id"], "Aggiornata connessione Meta")
    await db.meta_connections.replace_one({"id": conn_id}, c)
    await log_audit(org_id=org_id, user=user, action="UPDATE_META_CONNECTION", entity_type="meta_connection",
                    entity_id=conn_id, details={"access_token_changed": bool(access_token)})
    return _public(c)


@router.delete("/{conn_id}")
async def delete_meta_connection(conn_id: str, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    c = await db.meta_connections.find_one({"id": conn_id})
    assert_same_org(c, user, "Connessione Meta non trovata")
    await db.meta_connections.delete_one({"id": conn_id})
    await log_audit(org_id=org_id, user=user, action="DELETE_META_CONNECTION", entity_type="meta_connection", entity_id=conn_id)
    return {"ok": True}


class TestConfirmBody(BaseModel):
    confirm: bool = False


@router.post("/{conn_id}/test")
async def test_meta_connection(conn_id: str, body: TestConfirmBody, user: dict = Depends(require_roles("ADMIN"))):
    """Verifica REALE ma di sola lettura (item 11): token valido, Pagina
    raggiungibile, eventuale Instagram Business Account collegato. Nessuna
    pubblicazione, nessun costo — richiede comunque conferma esplicita,
    stesso principio di ogni altra chiamata reale dell'app."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rate_limit(f"testmetaconn:{conn_id}", max_calls=5, window_seconds=60)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta")
    c = await db.meta_connections.find_one({"id": conn_id})
    assert_same_org(c, user, "Connessione Meta non trovata")
    if not c.get("access_token_encrypted"):
        raise HTTPException(status_code=400, detail="Nessun access token configurato su questa connessione.")
    token = decrypt_secret(c["access_token_encrypted"])
    api_version = c.get("graph_api_version") or DEFAULT_GRAPH_API_VERSION

    fb_status, ig_status = STATUS_NOT_CONFIGURED, STATUS_NOT_CONFIGURED
    page_name, ig_username = c.get("page_name", ""), c.get("instagram_username", "")
    dettagli_errore = None

    validazione = meta_auth.validate_token(token, api_version=api_version)
    if not validazione.valido:
        fb_status = ig_status = STATUS_INVALID
        dettagli_errore = validazione.messaggio
    elif c.get("page_id"):
        try:
            info = meta_auth.verify_page(token, c["page_id"], api_version=api_version)
            fb_status = STATUS_CONNECTED
            page_name = info.page_name
            ig_account = c.get("instagram_business_account_id") or info.instagram_business_account_id
            if ig_account:
                try:
                    ig_info = meta_auth.verify_instagram_account(token, ig_account, api_version=api_version)
                    ig_status = STATUS_CONNECTED
                    ig_username = ig_info.username
                    c["instagram_business_account_id"] = ig_account
                except MetaConnectorError as exc:
                    ig_status = STATUS_ERROR if exc.codice != "permesso_negato" else STATUS_MISSING_PERMISSION
                    dettagli_errore = exc.messaggio
        except MetaConnectorError as exc:
            fb_status = STATUS_ERROR if exc.codice != "permesso_negato" else STATUS_MISSING_PERMISSION
            dettagli_errore = exc.messaggio
    else:
        fb_status = STATUS_NOT_CONFIGURED  # token valido ma nessuna Pagina indicata

    ora_verificato = fb_status == STATUS_CONNECTED
    await db.meta_connections.update_one({"id": conn_id}, {"$set": {
        "facebook_status": fb_status, "instagram_status": ig_status,
        "page_name": page_name, "instagram_username": ig_username,
        "last_test_at": now_iso(), "last_test_result": "OK_REALE" if ora_verificato else f"ERRORE_{fb_status}",
        "updated_at": now_iso(),
    }})
    await log_audit(org_id=org_id, user=user, action="TEST_META_CONNECTION", entity_type="meta_connection",
                    entity_id=conn_id, details={"facebook_status": fb_status, "instagram_status": ig_status})
    c2 = await db.meta_connections.find_one({"id": conn_id}, {"_id": 0})
    out = _public(c2)
    if dettagli_errore:
        out["dettagli_errore"] = dettagli_errore
    return out


# ==================== stato aggregato (item 12) ====================
async def _active_connection(org_id: str) -> Optional[dict]:
    """La connessione Meta ATTIVA per l'organizzazione (item 14: multi-
    tenant per costruzione — ogni org ha le proprie righe). Nessun fallback
    a variabili d'ambiente qui: quello resta un dettaglio del solo dispatch
    reale (domains/social_publishing.py), mai dello stato mostrato in UI,
    per non mostrare 'connesso' per una configurazione che nessuna
    organizzazione ha davvero salvato."""
    return await db.meta_connections.find_one(
        {"organization_id": org_id, "active": True}, {"_id": 0}, sort=[("updated_at", -1)])


@status_router.get("/status")
async def meta_connector_status(user: dict = Depends(get_current_user)):
    """GET /social/connectors/meta/status — item 12. Risposta SEMPRE
    redatta: nessun token, nessun secret, solo lo stato gia' calcolato
    dall'ultimo test esplicito (mai una nuova chiamata Meta qui: questo
    endpoint e' istantaneo e gratuito, richiamabile dal frontend ad ogni
    caricamento del pannello di pubblicazione)."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    conn = await _active_connection(org_id)
    if not conn:
        return {
            "configured": False, "mode": "dry_run",
            "facebook_page": {"connected": False, "page_name": None},
            "instagram": {"connected": False, "username": None},
            "message": "Nessuna connessione Meta configurata: la pubblicazione resta in modalità dry-run.",
        }
    fb_connected = conn.get("facebook_status") == STATUS_CONNECTED
    ig_connected = conn.get("instagram_status") == STATUS_CONNECTED
    return {
        "configured": True, "mode": conn.get("mode", "dry_run"),
        "facebook_page": {
            "connected": fb_connected, "page_name": conn.get("page_name") or None,
            "status": conn.get("facebook_status", STATUS_NOT_CONFIGURED),
        },
        "instagram": {
            "connected": ig_connected, "username": conn.get("instagram_username") or None,
            "status": conn.get("instagram_status", STATUS_NOT_CONFIGURED),
        },
        "last_verified_at": conn.get("last_test_at"),
        "message": None if (fb_connected or ig_connected) else
                   "Connessione configurata ma non ancora verificata con successo: apri Connessioni e API.",
    }
