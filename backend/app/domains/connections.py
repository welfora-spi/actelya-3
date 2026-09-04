from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import time

from ..db import db
from ..deps import get_current_user, require_roles, rate_limit, assert_same_org
from ..audit import log_audit
from ..security import encrypt_secret, mask_secret, vault_available
from ..models import now_iso, base_record, new_id, touch
from ..config import DEFAULT_ORG_ID
from ..integrations import requesty_secrets
from ..brain import llm_gateway

router = APIRouter(prefix="/connections", tags=["connections"])

PROVIDER_TYPES = ["requesty", "anthropic", "openai", "openai_compatible", "gemini"]

INTEGRATION_CATALOG = [
    ("email_smtp", "Email / SMTP"), ("microsoft365", "Microsoft 365"),
    ("gmail", "Gmail"), ("google_calendar", "Google Calendar"), ("meta", "Meta"),
    ("instagram", "Instagram"), ("linkedin", "LinkedIn"), ("google_ads", "Google Ads"),
    ("meta_ads", "Meta Ads"), ("crm", "CRM"), ("webhook", "Webhook"),
    ("prospect_b2b", "Provider Prospect B2B"),
    ("rpo", "Registro Pubblico delle Opposizioni"), ("analytics", "Analytics"),
]


class AIConnectionBody(BaseModel):
    name: str
    provider_type: str
    base_url: str = ""
    api_key: Optional[str] = None
    logical_model: str = ""
    effective_model: str = ""
    timeout: int = 60
    max_tokens: int = 2000
    max_budget_per_task: float = 1.0
    daily_budget: float = 10.0
    active: bool = True
    priority: int = 1


def _public_conn(c: dict) -> dict:
    # Requesty: la credenziale vive SOLO nel Credential Manager di Windows (mai in
    # Mongo, vedi app/integrations/requesty_secrets.py) -- e' un'unica credenziale
    # condivisa da processo/PC, non per-connessione: se piu' righe "requesty"
    # esistono, riflettono tutte lo stesso stato reale (mai un valore inventato).
    if c["provider_type"] == "requesty":
        api_key_masked = requesty_secrets.requesty_api_key_mascherata() or ""
        has_key = requesty_secrets.requesty_configurata()
    else:
        api_key_masked = c.get("api_key_masked", "")
        has_key = bool(c.get("api_key_encrypted"))
    return {
        "id": c["id"],
        "name": c["name"],
        "provider_type": c["provider_type"],
        "base_url": c.get("base_url", ""),
        "api_key_masked": api_key_masked,
        "has_key": has_key,
        "logical_model": c.get("logical_model", ""),
        "effective_model": c.get("effective_model", ""),
        "timeout": c.get("timeout", 60),
        "max_tokens": c.get("max_tokens", 2000),
        "max_budget_per_task": c.get("max_budget_per_task", 1.0),
        "daily_budget": c.get("daily_budget", 10.0),
        "active": c.get("active", True),
        "priority": c.get("priority", 1),
        "last_test_at": c.get("last_test_at"),
        "last_test_result": c.get("last_test_result"),
        "provider_returned_model": c.get("provider_returned_model"),
        "verified": c.get("verified", False),
    }


# ---------- AI Providers ----------
@router.get("/ai")
async def list_ai(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.ai_connections.find({"organization_id": org_id}, {"_id": 0}).to_list(100)
    return [_public_conn(c) for c in rows]


@router.post("/ai")
async def create_ai(body: AIConnectionBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    if body.provider_type not in PROVIDER_TYPES:
        raise HTTPException(status_code=400, detail="Tipo provider non supportato")
    if body.api_key and body.provider_type != "requesty" and not vault_available():
        raise HTTPException(status_code=503, detail="MASTER_KEY non configurata: impossibile salvare segreti in modo sicuro.")
    rec = base_record(org_id, user["id"])
    rec.update({
        "id": new_id("aiconn"), "name": body.name, "provider_type": body.provider_type,
        "base_url": body.base_url, "logical_model": body.logical_model,
        "effective_model": body.effective_model, "timeout": body.timeout,
        "max_tokens": body.max_tokens, "max_budget_per_task": body.max_budget_per_task,
        "daily_budget": body.daily_budget, "active": body.active, "priority": body.priority,
        "last_test_at": None, "last_test_result": None, "provider_returned_model": None,
        "verified": False, "api_key_encrypted": None, "api_key_masked": "",
    })
    if body.api_key:
        if body.provider_type == "requesty":
            # Credential Manager di Windows, MAI Mongo (vedi app/integrations/requesty_secrets.py).
            requesty_secrets.salva_api_key_requesty(body.api_key)
        else:
            rec["api_key_encrypted"] = encrypt_secret(body.api_key)
            rec["api_key_masked"] = mask_secret(body.api_key)
    await db.ai_connections.insert_one(rec)
    await log_audit(org_id=org_id, user=user, action="CREATE_AI_CONNECTION",
                    entity_type="ai_connection", entity_id=rec["id"],
                    details={"name": body.name, "provider_type": body.provider_type})
    return _public_conn(rec)


@router.put("/ai/{conn_id}")
async def update_ai(conn_id: str, body: AIConnectionBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    c = await db.ai_connections.find_one({"id": conn_id})
    assert_same_org(c, user, "Connessione non trovata")
    data = body.model_dump()
    api_key = data.pop("api_key", None)
    c.update(data)
    c["verified"] = False  # config changed -> must re-test
    if api_key:
        if c["provider_type"] == "requesty":
            requesty_secrets.salva_api_key_requesty(api_key)
        else:
            if not vault_available():
                raise HTTPException(status_code=503, detail="MASTER_KEY non configurata.")
            c["api_key_encrypted"] = encrypt_secret(api_key)
            c["api_key_masked"] = mask_secret(api_key)
    touch(c, user["id"], "Aggiornata connessione AI")
    await db.ai_connections.replace_one({"id": conn_id}, c)
    await log_audit(org_id=org_id, user=user, action="UPDATE_AI_CONNECTION",
                    entity_type="ai_connection", entity_id=conn_id,
                    details={"api_key_changed": bool(api_key)})
    return _public_conn(c)


@router.delete("/ai/{conn_id}")
async def delete_ai(conn_id: str, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    c = await db.ai_connections.find_one({"id": conn_id})
    assert_same_org(c, user, "Connessione non trovata")
    await db.ai_connections.delete_one({"id": conn_id})
    await log_audit(org_id=org_id, user=user, action="DELETE_AI_CONNECTION",
                    entity_type="ai_connection", entity_id=conn_id)
    return {"ok": True}


@router.post("/ai/{conn_id}/test-preview")
async def test_preview(conn_id: str, user: dict = Depends(require_roles("ADMIN"))):
    """Step 1: show provider, model and possible cost. No call is made."""
    c = await db.ai_connections.find_one({"id": conn_id}, {"_id": 0})
    assert_same_org(c, user, "Connessione non trovata")
    est_tokens = 40
    possible_cost = round(est_tokens * 0.000002, 6)
    return {
        "provider": c["provider_type"],
        "logical_model": c.get("logical_model"),
        "effective_model": c.get("effective_model"),
        "estimated_tokens": est_tokens,
        "possible_cost": possible_cost,
        "mode": "SIMULAZIONE",
        "message": "Verrà effettuata una singola chiamata minima (simulata in questa milestone). Nessun retry automatico.",
    }


class TestConfirmBody(BaseModel):
    confirm: bool = False


@router.post("/ai/{conn_id}/test-confirm")
async def test_confirm(conn_id: str, body: TestConfirmBody, user: dict = Depends(require_roles("ADMIN"))):
    """Step 2: single minimal call. SIMULATED in this milestone (no real network call)."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rate_limit(f"testconn:{conn_id}", max_calls=5, window_seconds=60)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta")
    c = await db.ai_connections.find_one({"id": conn_id})
    assert_same_org(c, user, "Connessione non trovata")

    t0 = time.time()
    # SIMULATED single minimal call — no real provider call in milestone 1.
    tokens_in, tokens_out = 12, 8
    effective = c.get("effective_model") or c.get("logical_model") or "simulato"
    cost = round((tokens_in + tokens_out) * 0.000002, 6)
    latency_ms = int((time.time() - t0) * 1000) + 5
    result = {
        "ok": True, "mode": "SIMULAZIONE",
        "tokens_input": tokens_in, "tokens_output": tokens_out,
        "cost": cost, "latency_ms": latency_ms, "effective_model": effective,
        "message": "Test simulato riuscito. Attiva la modalità AI REALE per test reali.",
    }
    await db.ai_connections.update_one(
        {"id": conn_id},
        {"$set": {"last_test_at": now_iso(), "last_test_result": "OK_SIMULATO",
                  "provider_returned_model": effective, "verified": True,
                  "updated_at": now_iso()}},
    )
    await log_audit(org_id=org_id, user=user, action="TEST_AI_CONNECTION",
                    entity_type="ai_connection", entity_id=conn_id,
                    details={"result": "OK_SIMULATO", "cost": cost, "latency_ms": latency_ms})
    return result


@router.post("/ai/{conn_id}/test-real")
async def test_real(conn_id: str, body: TestConfirmBody, user: dict = Depends(require_roles("ADMIN"))):
    """Una singola chiamata REALE a costo minimo, mai automatica -- richiede
    sempre conferma esplicita del chiamante (body.confirm=True). Esteso a
    QUALUNQUE provider registrato in brain/llm_gateway.py (non solo
    Requesty): la credenziale si risolve qui (keyring per Requesty,
    api_key_encrypted per gli altri, mai in chiaro), la chiamata vera passa
    sempre dall'adapter comune — nessuna credenziale ne' traceback grezzo
    arrivano mai in questa risposta; nessuna eccezione grezza e' mai
    loggata (vedi app/brain/llm_gateway.py)."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rate_limit(f"testconn_real:{conn_id}", max_calls=5, window_seconds=60)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta")
    c = await db.ai_connections.find_one({"id": conn_id})
    assert_same_org(c, user, "Connessione non trovata")
    if llm_gateway.get_adapter(c["provider_type"]) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Test REALE per '{c['provider_type']}' non disponibile: nessun adapter registrato.",
        )
    model_id = (c.get("effective_model") or "").strip()
    if not model_id:
        raise HTTPException(
            status_code=400,
            detail="Nessun 'modello effettivo' configurato su questa connessione: impostalo prima di testare.",
        )

    if c["provider_type"] == "requesty":
        api_key = "keyring" if requesty_secrets.requesty_configurata() else None
    elif c.get("api_key_encrypted"):
        from ..security import decrypt_secret, SecretVaultError
        try:
            api_key = decrypt_secret(c["api_key_encrypted"])
        except SecretVaultError:
            api_key = None
    else:
        api_key = None

    risultato = llm_gateway.diagnostic_test(
        c["provider_type"], api_key, model_id, base_url=c.get("base_url") or None,
    )
    now_verified = risultato["esito"] == "OK"
    await db.ai_connections.update_one(
        {"id": conn_id},
        {"$set": {"last_test_at": now_iso(), "last_test_result": "OK_REALE" if now_verified else f"ERRORE_{risultato['codice_errore']}",
                  "provider_returned_model": risultato["modello_effettivo"],
                  "verified": now_verified, "updated_at": now_iso()}},
    )
    await log_audit(org_id=org_id, user=user, action="TEST_AI_CONNECTION_REAL",
                    entity_type="ai_connection", entity_id=conn_id,
                    details={"esito": risultato["esito"], "codice_errore": risultato["codice_errore"],
                             "latenza_ms": risultato["latenza_ms"], "input_tokens": risultato["input_tokens"],
                             "output_tokens": risultato["output_tokens"], "modello_effettivo": risultato["modello_effettivo"]})
    return {"mode": "REALE", **risultato}


# ---------- Integrations (predisposed, not operative) ----------
@router.get("/integrations")
async def list_integrations(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    existing = {i["key"]: i for i in await db.integrations.find(
        {"organization_id": org_id}, {"_id": 0}).to_list(100)}
    out = []
    for key, label in INTEGRATION_CATALOG:
        row = existing.get(key, {"key": key, "status": "NON_CONFIGURATA"})
        out.append({
            "key": key, "label": label,
            "status": row.get("status", "NON_CONFIGURATA"),
            "operative": False,
            "note": "Non ancora collegata",
            "last_updated": row.get("updated_at"),
        })
    return out


class IntegrationStatusBody(BaseModel):
    status: str


@router.put("/integrations/{key}")
async def set_integration_status(key: str, body: IntegrationStatusBody,
                                 user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    valid_keys = {k for k, _ in INTEGRATION_CATALOG}
    if key not in valid_keys:
        raise HTTPException(status_code=404, detail="Integrazione sconosciuta")
    from ..models import INTEGRATION_STATUS
    if body.status not in INTEGRATION_STATUS:
        raise HTTPException(status_code=400, detail="Stato non valido")
    # Only allow toggling between NON_CONFIGURATA / DISATTIVATA in milestone 1
    if body.status not in ("NON_CONFIGURATA", "DISATTIVATA"):
        raise HTTPException(status_code=400, detail="Integrazione non ancora collegata: stato non impostabile in questa milestone.")
    existing = await db.integrations.find_one({"organization_id": org_id, "key": key})
    if existing:
        touch(existing, user["id"], f"Stato integrazione -> {body.status}")
        existing["status"] = body.status
        await db.integrations.replace_one({"_id": existing["_id"]}, existing)
    else:
        rec = base_record(org_id, user["id"])
        rec.update({"key": key, "status": body.status})
        await db.integrations.insert_one(rec)
    await log_audit(org_id=org_id, user=user, action="UPDATE_INTEGRATION_STATUS",
                    entity_type="integration", entity_id=key, details={"status": body.status})
    return {"key": key, "status": body.status}
