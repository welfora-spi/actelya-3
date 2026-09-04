"""Agente marketing — Flyer/immagine (Requesty reale, testo E immagine).

Stesso pattern di domains/reel.py (obiettivo -> grounding -> agente -> skill/
tool -> provider -> validazione -> costo -> approvazione -> media finale),
riusato deliberatamente, non reinventato: seconda prova della stessa
architettura multimodale su una capability diversa (flyer_image), con lo
stesso Video/Creative specialist (agents/agent_map.py) ma un ruolo distinto
lato skill (Creative/Graphic Designer, vedi brain/skills.py).

Requesty supporta DAVVERO immagini (confermato su docs.requesty.ai/api-
reference/endpoint/images-generations-create: POST /v1/images/generations,
OpenAI-compatibile) -- niente da predisporre come NOT_CONFIGURED per il
provider testo/immagine: e' lo STESSO gateway di domains/reel.py
(integrations/requesty_gateway.py), nessun secondo client HTTP.

A differenza del video (Runway, asincrono con job/polling), la generazione
immagine Requesty e' SINCRONA: un'unica chiamata restituisce subito l'URL,
nessun job/polling necessario."""
from __future__ import annotations

import base64
import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..db import db
from ..deps import get_current_user, require_roles, rate_limit, assert_same_org
from ..audit import log_audit
from ..models import now_iso, base_record, new_id
from ..config import DEFAULT_ORG_ID
from .knowledge import current_facts_map
from .estimator import PRICE_PER_TOKEN
from .reel_semantic import semantic_validate_generic_content
from . import social_memory
from ..integrations import requesty_gateway
from ..integrations.requesty_gateway import RequestyErroreSanificato, RequestyNonConfigurato

router = APIRouter(prefix="/flyer", tags=["flyer"])

REQUIRED_ORG_FIELDS = ("ragione_sociale", "settore")
MAX_TOKENS_DEFAULT = 1200

FLYER_SCHEMA = {
    "type": "object",
    "required": ["formato", "cta", "headline", "prompt_immagine", "subheadline", "body_text", "hashtags"],
    "properties": {
        "formato": {"type": "string"},
        "cta": {"type": "string"},
        "headline": {"type": "string"},
        "prompt_immagine": {"type": "string"},
        "subheadline": {"type": "string"},
        "body_text": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
}

_REFUSAL_RE = re.compile(
    r"non posso|non sono in grado|mi dispiace|non è possibile|non e' possibile|"
    r"as an ai|i can'?t|i cannot|i'm sorry|cannot comply",
    re.IGNORECASE,
)


def _is_refusal_or_forbidden(v) -> bool:
    s = str(v or "").strip()
    if not s or s.lower() in ("unknown", "todo", "n/a", "na", "none", "null", "-", "?"):
        return True
    return bool(_REFUSAL_RE.search(s))


def _brand(org: dict) -> str:
    return (org.get("nome_commerciale") or org.get("ragione_sociale") or "l'azienda").strip()


async def _company_context(org_id: str) -> tuple[dict, list[str]]:
    """Identica a domains/reel.py::_company_context (stesso Fact Ledger,
    stessa regola 'mai un valore inventato'): duplicata qui in 3 righe
    volutamente per non introdurre una dipendenza incrociata reel<->flyer,
    non per una logica diversa."""
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0}) or {}
    facts = await current_facts_map(db, org_id)
    contesto = {
        "ragione_sociale": org.get("ragione_sociale") or "",
        "nome_commerciale": org.get("nome_commerciale") or "",
        "settore": org.get("settore") or facts.get("settore", {}).get("value", ""),
        "sito_web": org.get("sito_web") or facts.get("sito_web", {}).get("value", ""),
        "obiettivi_commerciali": org.get("obiettivi_commerciali") or facts.get("obiettivi_commerciali", {}).get("value", ""),
    }
    for extra_field in ("prodotto", "pubblico_target", "tono_di_voce"):
        if extra_field in facts:
            contesto[extra_field] = facts[extra_field]["value"]
    mancanti = [f for f in REQUIRED_ORG_FIELDS if not (contesto.get(f) or "").strip()]
    return contesto, mancanti


async def _registra_spesa_reale(org_id: str, project_id: str, input_tokens, output_tokens, *, source="flyer") -> Optional[float]:
    """Costo STIMATO (non fatturato esatto: Requesty non lo restituisce come
    valuta) a partire da token REALI gia' misurati -- mai una cifra
    inventata quando i token non sono noti (None in quel caso, mai 0)."""
    if input_tokens is None or output_tokens is None:
        return None
    stima = round((input_tokens + output_tokens) * PRICE_PER_TOKEN, 6)
    await db.executions.insert_one({
        "id": new_id("exec"), "organization_id": org_id, "real_cost": stima,
        "source": source, "flyer_project_id": project_id, "created_at": now_iso(),
    })
    return stima


# Byte minimi perche' un asset decodificato sia considerato un'immagine
# plausibile (non una risposta vuota/troncata mascherata da base64 valido):
# un PNG 1024x1536 reale e' sempre di gran lunga sopra questa soglia.
MIN_IMAGE_BYTES = 512


async def _persist_image_asset(org_id: str, project_id: str, b64_data: str, mime_type: str) -> str:
    """Decodifica e verifica l'asset PRIMA di persisterlo (mai un'immagine
    dichiarata pronta senza una verifica lato backend, non solo frontend):
    solleva RequestyErroreSanificato se il base64 non e' valido o troppo
    piccolo per essere un'immagine reale. Persistito in una collezione
    dedicata (mai una stringa enorme nel documento principale del progetto):
    ritorna un percorso interno stabile, servito da GET /flyer/assets/{id}."""
    try:
        raw = base64.b64decode(b64_data, validate=True)
    except Exception as exc:
        raise RequestyErroreSanificato("risposta_non_valida", "L'immagine ricevuta non e' un base64 valido.") from exc
    if len(raw) < MIN_IMAGE_BYTES:
        raise RequestyErroreSanificato("risposta_non_valida", "L'immagine ricevuta e' vuota o troppo piccola per essere valida.")
    asset_id = new_id("flyerimg")
    await db.flyer_media_assets.insert_one({
        "id": asset_id, "organization_id": org_id, "flyer_project_id": project_id,
        "mime_type": mime_type, "data_b64": b64_data, "size_bytes": len(raw), "created_at": now_iso(),
    })
    return f"/api/flyer/assets/{asset_id}"


def validate_flyer_content(c: dict) -> dict:
    errors, warnings = [], []
    if not isinstance(c, dict):
        return {"status": "BLOCCATO", "warnings": [], "errors": ["Contenuto non e' un oggetto JSON valido"]}
    for label, key, min_len in (
        ("Headline", "headline", 5), ("Sottotitolo", "subheadline", 5), ("Testo", "body_text", 15),
        ("CTA", "cta", 3), ("Prompt immagine", "prompt_immagine", 20), ("Formato", "formato", 2),
    ):
        v = c.get(key)
        if not isinstance(v, str) or not v.strip() or _is_refusal_or_forbidden(v):
            errors.append(f"{label}: mancante, vuoto o non producibile")
        elif len(v.strip()) < min_len:
            errors.append(f"{label}: contenuto non sufficientemente sostanziale")
    hashtags = c.get("hashtags")
    if not isinstance(hashtags, list) or len([h for h in hashtags if isinstance(h, str) and h.strip()]) < 2:
        errors.append("hashtags: almeno 2 hashtag pertinenti richiesti")
    if errors:
        return {"status": "BLOCCATO", "warnings": warnings, "errors": errors}
    return {"status": "COMPLETATO", "warnings": warnings, "errors": []}


def _campi_testuali_flyer(content: dict) -> list[tuple[str, str]]:
    campi = [
        ("headline", content.get("headline", "")), ("subheadline", content.get("subheadline", "")),
        ("body_text", content.get("body_text", "")), ("cta", content.get("cta", "")),
    ]
    for h in content.get("hashtags") or []:
        campi.append(("hashtags", str(h)))
    return campi


async def _snapshot_content_version(org_id: str, project_id: str, p_prima: dict, actor: str) -> None:
    """Stesso pattern di domains/reel.py::_snapshot_content_version: fotografa
    il contenuto testuale del flyer PRIMA che una nuova generazione lo
    sovrascriva (mai chiamata sulla primissima generazione)."""
    ultimo = await db.flyer_content_versions.find_one({"flyer_project_id": project_id}, sort=[("version", -1)])
    versione = (ultimo["version"] + 1) if ultimo else 1
    await db.flyer_content_versions.insert_one({
        "id": new_id("flyerver"), "organization_id": org_id, "flyer_project_id": project_id,
        "version": versione, "content": p_prima.get("content"), "generazione": p_prima.get("generazione"),
        "semantic_check": p_prima.get("semantic_check"), "nota_revisione_che_ha_portato_alla_modifica": p_prima.get("nota_revisione"),
        "superseded_at": now_iso(), "created_by": actor,
    })


def _public_content_version(v: dict) -> dict:
    return {
        "version": v["version"], "content": v.get("content"), "generazione": v.get("generazione"),
        "semantic_check": v.get("semantic_check"),
        "nota_revisione_che_ha_portato_alla_modifica": v.get("nota_revisione_che_ha_portato_alla_modifica"),
        "superseded_at": v.get("superseded_at"), "created_by": v.get("created_by"),
    }


def _public(p: dict) -> dict:
    return {
        "id": p["id"], "brief": p.get("brief", ""), "status": p["status"],
        "progetto_pronto": p.get("progetto_pronto", False),
        "progetto_approvato": p.get("progetto_approvato", False),
        "progetto_approvato_da": p.get("progetto_approvato_da"), "progetto_approvato_at": p.get("progetto_approvato_at"),
        "content": p.get("content"), "fact_snapshot": p.get("fact_snapshot", {}),
        "generazione": p.get("generazione", {}), "nota_revisione": p.get("nota_revisione"),
        "semantic_check": p.get("semantic_check", {"status": "NON_VERIFICATO", "affermazioni_contestate": []}),
        "image_status": p.get("image_status", "NON_RICHIESTO"),
        # 'pronta' richiede SEMPRE sia lo stato sia un URL non vuoto: mai
        # un'incoerenza fra badge di stato e media realmente disponibile.
        "image_pronta": p.get("image_status") == "IMMAGINE_PRONTA" and bool((p.get("image_url") or "").strip()),
        "image_url": p.get("image_url"), "image_mime_type": p.get("image_mime_type"),
        "image_errore_codice": p.get("image_errore_codice"), "image_errore_messaggio": p.get("image_errore_messaggio"),
        "generazione_immagine": p.get("generazione_immagine", {}),
        "image_approvata": p.get("image_approvata", False),
        "image_approvata_da": p.get("image_approvata_da"), "image_approvata_at": p.get("image_approvata_at"),
        "image_nota_revisione": p.get("image_nota_revisione"),
        "created_at": p.get("created_at"), "updated_at": p.get("updated_at"),
    }


class NewFlyerBody(BaseModel):
    brief: str = ""


@router.get("/projects")
async def list_projects(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.flyer_projects.find({"organization_id": org_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [_public(p) for p in rows]


@router.get("/projects/{project_id}")
async def get_project(project_id: str, user: dict = Depends(get_current_user)):
    p = await db.flyer_projects.find_one({"id": project_id}, {"_id": 0})
    assert_same_org(p, user, "Progetto flyer non trovato")
    return _public(p)


@router.post("/projects")
async def create_project(body: NewFlyerBody, user: dict = Depends(require_roles("OPERATORE", "ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    contesto, mancanti = await _company_context(org_id)
    if mancanti:
        raise HTTPException(
            status_code=400,
            detail=f"Informazioni aziendali mancanti nel Fact Ledger: {', '.join(mancanti)}. "
                   "Completale in Onboarding/Profilo prima di creare un progetto flyer.",
        )
    rec = base_record(org_id, user["id"])
    rec.update({
        "id": new_id("flyer"), "brief": body.brief.strip(), "status": "BOZZA",
        "progetto_pronto": False, "content": None, "fact_snapshot": contesto, "generazione": {},
        "progetto_approvato": False, "progetto_approvato_da": None, "progetto_approvato_at": None,
        "nota_revisione": None, "semantic_check": {"status": "NON_VERIFICATO", "affermazioni_contestate": []},
        "image_status": "NON_RICHIESTO", "image_url": None, "image_approvata": False,
        "image_approvata_da": None, "image_approvata_at": None, "image_nota_revisione": None,
    })
    await db.flyer_projects.insert_one(rec)
    await log_audit(org_id=org_id, user=user, action="CREATE_FLYER_PROJECT",
                    entity_type="flyer_project", entity_id=rec["id"], details={"brief": body.brief.strip()})
    return _public(rec)


async def _readiness(org_id: str) -> dict:
    settings = await db.settings.find_one({"id": org_id}) or {}
    ai_real = bool(settings.get("ai_real_mode"))
    conn = await db.ai_connections.find_one({
        "organization_id": org_id, "provider_type": "requesty", "verified": True, "active": True,
    }, {"_id": 0})
    budget = await db.budgets.find_one({"id": org_id}) or {}
    spent_rows = await db.executions.find({"organization_id": org_id}, {"_id": 0, "real_cost": 1}).to_list(1000)
    spent = sum(r.get("real_cost", 0.0) for r in spent_rows)
    residuo = round(budget.get("general_limit", 0.0) - spent, 6)
    motivi = []
    if not ai_real:
        motivi.append("Modalita' AI REALE non attiva (Impostazioni).")
    if not conn:
        motivi.append("Nessuna connessione Requesty verificata e attiva (Connessioni).")
    elif not (conn.get("effective_model") or "").strip():
        motivi.append("La connessione Requesty non ha un 'modello effettivo' configurato.")
    if not budget.get("general_limit", 0.0) > 0:
        motivi.append("Nessun budget generale configurato (Budget).")
    return {"pronto": not motivi, "motivi": motivi, "connessione": conn, "budget_residuo": residuo}


@router.post("/projects/{project_id}/generate/preview")
async def generate_preview(project_id: str, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.flyer_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto flyer non trovato")
    r = await _readiness(org_id)
    conn = r.pop("connessione", None)
    return {**r, "provider": "requesty", "modello_effettivo": (conn or {}).get("effective_model"),
            "message": "Verra' effettuata UNA chiamata reale a Requesty (testo). Nessuna chiamata parte senza conferma esplicita."}


class ConfirmBody(BaseModel):
    confirm: bool = False


@router.post("/projects/{project_id}/generate")
async def generate(project_id: str, body: ConfirmBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rate_limit(f"flyer_generate:{project_id}", max_calls=5, window_seconds=60)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta prima di una chiamata reale a Requesty.")
    p = await db.flyer_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto flyer non trovato")
    if p["status"] == "PROGETTO_PRONTO":
        raise HTTPException(status_code=409, detail="Progetto gia' pronto: crea un nuovo progetto per rigenerare.")
    if p["status"] == "ESITO_INCERTO":
        raise HTTPException(status_code=409, detail="Esito incerto: risolvilo prima di riprovare.")

    r = await _readiness(org_id)
    if not r["pronto"]:
        raise HTTPException(status_code=409, detail="; ".join(r["motivi"]))
    conn = r["connessione"]

    contesto, mancanti = await _company_context(org_id)
    if mancanti:
        raise HTTPException(status_code=400, detail=f"Informazioni aziendali mancanti: {', '.join(mancanti)}.")

    def _campo(chiave):
        return contesto.get(chiave, "") or "informazione non disponibile"

    memoria_ctx = await social_memory.get_memory_context(db, org_id)
    memoria_blocco = social_memory.render_memory_block(memoria_ctx)

    system = (
        "Sei un Creative/Graphic Designer di ACTELYA specializzato in flyer promozionali. "
        "REGOLA ASSOLUTA: usa ESCLUSIVAMENTE le informazioni aziendali fornite. Non inventare MAI "
        "prodotto, caratteristiche, benefici, prezzi, pubblico, territorio o promesse non forniti. "
        "Se un'informazione e' 'informazione non disponibile', non inventarla e non menzionarla in modo "
        "specifico. Rispondi SOLO con un oggetto JSON conforme allo schema, in italiano, tranne "
        "prompt_immagine che va scritto in inglese per un generatore di immagini."
    )
    messaggio = (
        f"Azienda: {_brand(contesto)}\nRagione sociale: {_campo('ragione_sociale')}\nSettore: {_campo('settore')}\n"
        f"Sito web: {_campo('sito_web')}\nObiettivi commerciali: {_campo('obiettivi_commerciali')}\n"
        f"Prodotto: {_campo('prodotto')}\nPubblico target: {_campo('pubblico_target')}\n"
        f"Tono di voce: {_campo('tono_di_voce')}\n"
        f"Brief creativo aggiuntivo: {p.get('brief') or 'nessuno: crea un flyer generico e coerente col settore, senza inventare dettagli specifici sul prodotto'}\n"
        + (f"Richiesta di modifica rispetto a un tentativo precedente: {p.get('nota_revisione')}\n" if p.get("nota_revisione") else "")
        + (f"\n{memoria_blocco}\n" if memoria_blocco else "")
        + "\nGenera: formato (es. verticale A4 o 'story' 9:16), CTA, headline, prompt_immagine (inglese, dettagliato, "
          "adatto a un flyer promozionale), sottotitolo, testo del corpo, da 2 a 6 hashtag pertinenti "
          "(senza spazi, es. '#panetteria', mai un hashtag generico senza relazione con settore/prodotto/localita' dichiarati)."
    )

    await db.flyer_projects.update_one({"id": project_id}, {"$set": {"status": "GENERAZIONE_IN_CORSO", "updated_at": now_iso()}})
    try:
        risultato = requesty_gateway.genera_json(
            model_id_requesty=conn["effective_model"], system=system, messaggio_utente=messaggio,
            schema_json=FLYER_SCHEMA, schema_nome="actelya_flyer_project",
            max_tokens=conn.get("max_tokens") or MAX_TOKENS_DEFAULT, timeout=conn.get("timeout") or 60,
        )
    except RequestyNonConfigurato as exc:
        await db.flyer_projects.update_one({"id": project_id}, {"$set": {
            "status": "BLOCCATO", "generazione": {"ultimo_errore_codice": "credenziale_assente", "ultimo_errore_messaggio": str(exc)},
            "updated_at": now_iso()}})
        raise HTTPException(status_code=409, detail=str(exc))
    except RequestyErroreSanificato as exc:
        nuovo = "ESITO_INCERTO" if exc.codice == "esito_incerto" else "BLOCCATO"
        await db.flyer_projects.update_one({"id": project_id}, {"$set": {
            "status": nuovo, "generazione": {"ultimo_errore_codice": exc.codice, "ultimo_errore_messaggio": exc.messaggio},
            "updated_at": now_iso()}})
        await log_audit(org_id=org_id, user=user, action="FLYER_GENERATE_ERROR", entity_type="flyer_project",
                        entity_id=project_id, status="ERROR", reason=exc.codice)
        raise HTTPException(status_code=502, detail=exc.messaggio)

    stima_costo = await _registra_spesa_reale(org_id, project_id, risultato.input_tokens, risultato.output_tokens)
    try:
        contenuto = json.loads(risultato.testo)
    except (json.JSONDecodeError, TypeError):
        await db.flyer_projects.update_one({"id": project_id}, {"$set": {
            "status": "BLOCCATO", "generazione": {"ultimo_errore_codice": "risposta_non_valida",
                                                  "errori_validazione": ["Risposta non e' un JSON valido."],
                                                  "stima_costo_usd": stima_costo}, "updated_at": now_iso()}})
        raise HTTPException(status_code=502, detail="La risposta di Requesty non e' un JSON valido (chiamata comunque addebitata).")

    validazione = ({"status": "BLOCCATO", "warnings": [], "errors": ["Risposta troncata"]}
                   if risultato.troncata else validate_flyer_content(contenuto))
    semantic = semantic_validate_generic_content(_campi_testuali_flyer(contenuto), contesto, p.get("brief", "")) \
        if validazione["status"] in ("COMPLETATO", "COMPLETATO_CON_AVVISI") else {"status": "NON_VERIFICATO", "affermazioni_contestate": []}
    nuovo_status = "PROGETTO_PRONTO" if validazione["status"] in ("COMPLETATO", "COMPLETATO_CON_AVVISI") else "BLOCCATO"
    generazione = {
        "modello_effettivo": risultato.modello_effettivo, "input_tokens": risultato.input_tokens,
        "output_tokens": risultato.output_tokens, "latenza_ms": risultato.latenza_ms,
        "troncata": risultato.troncata, "stima_costo_usd": stima_costo,
        "errori_validazione": validazione["errors"], "avvisi_validazione": validazione["warnings"],
    }
    if p.get("content"):
        await _snapshot_content_version(org_id, project_id, p, user.get("id", "system"))
    await db.flyer_projects.update_one({"id": project_id}, {"$set": {
        "status": nuovo_status, "progetto_pronto": nuovo_status == "PROGETTO_PRONTO",
        "content": contenuto, "generazione": generazione, "semantic_check": semantic, "updated_at": now_iso(),
        "image_status": "NON_RICHIESTO", "image_url": None, "image_approvata": False,
        "image_approvata_da": None, "image_approvata_at": None,
    }})
    await log_audit(org_id=org_id, user=user, action="FLYER_GENERATED", entity_type="flyer_project",
                    entity_id=project_id, details={"status": nuovo_status, "stima_costo_usd": stima_costo})
    p2 = await db.flyer_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


class ResolveUncertainBody(BaseModel):
    nota: str


@router.post("/projects/{project_id}/risolvi-esito-incerto")
async def risolvi_esito_incerto(project_id: str, body: ResolveUncertainBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.flyer_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto flyer non trovato")
    if p["status"] != "ESITO_INCERTO":
        raise HTTPException(status_code=409, detail="Il progetto non ha un esito incerto da risolvere.")
    if not body.nota.strip():
        raise HTTPException(status_code=422, detail="Nota di risoluzione obbligatoria")
    await db.flyer_projects.update_one({"id": project_id}, {"$set": {"status": "BLOCCATO", "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="FLYER_RESOLVE_UNCERTAIN", entity_type="flyer_project",
                    entity_id=project_id, details={"nota": body.nota.strip()})
    p2 = await db.flyer_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


@router.post("/projects/{project_id}/approve")
async def approve_project(project_id: str, user: dict = Depends(require_roles("ADMIN", "APPROVATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.flyer_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto flyer non trovato")
    if p["status"] != "PROGETTO_PRONTO":
        raise HTTPException(status_code=409, detail="Solo un progetto flyer PRONTO puo' essere approvato.")
    await db.flyer_projects.update_one({"id": project_id}, {"$set": {
        "progetto_approvato": True, "progetto_approvato_da": user.get("email") or user.get("id"),
        "progetto_approvato_at": now_iso(), "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="FLYER_PROJECT_APPROVED", entity_type="flyer_project", entity_id=project_id)
    p2 = await db.flyer_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


@router.get("/projects/{project_id}/content/versions")
async def list_content_versions(project_id: str, user: dict = Depends(get_current_user)):
    p = await db.flyer_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto flyer non trovato")
    rows = await db.flyer_content_versions.find(
        {"flyer_project_id": project_id}, {"_id": 0}).sort("version", -1).to_list(200)
    return [_public_content_version(v) for v in rows]


@router.post("/projects/{project_id}/verifica-semantica")
async def verifica_semantica(project_id: str, user: dict = Depends(require_roles("OPERATORE", "ADMIN", "APPROVATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.flyer_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto flyer non trovato")
    if not p.get("content"):
        raise HTTPException(status_code=409, detail="Nessun contenuto da verificare: genera prima il progetto.")
    semantic = semantic_validate_generic_content(_campi_testuali_flyer(p["content"]), p.get("fact_snapshot", {}), p.get("brief", ""))
    await db.flyer_projects.update_one({"id": project_id}, {"$set": {"semantic_check": semantic, "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="FLYER_SEMANTIC_CHECK", entity_type="flyer_project", entity_id=project_id,
                    details={"status": semantic["status"]})
    p2 = await db.flyer_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


class RichiediModificaBody(BaseModel):
    nota: str


@router.post("/projects/{project_id}/richiedi-modifica")
async def richiedi_modifica(project_id: str, body: RichiediModificaBody,
                            user: dict = Depends(require_roles("ADMIN", "APPROVATORE", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.flyer_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto flyer non trovato")
    if p["status"] not in ("PROGETTO_PRONTO", "BLOCCATO"):
        raise HTTPException(status_code=409, detail="Richiesta di modifica non applicabile allo stato corrente.")
    if not body.nota.strip():
        raise HTTPException(status_code=422, detail="Nota di modifica obbligatoria")
    await db.flyer_projects.update_one({"id": project_id}, {"$set": {
        "status": "BOZZA", "progetto_pronto": False, "progetto_approvato": False,
        "progetto_approvato_da": None, "progetto_approvato_at": None,
        "nota_revisione": body.nota.strip(), "semantic_check": {"status": "NON_VERIFICATO", "affermazioni_contestate": []},
        "image_status": "NON_RICHIESTO", "image_url": None, "image_approvata": False,
        "image_approvata_da": None, "image_approvata_at": None, "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="FLYER_REVISION_REQUESTED", entity_type="flyer_project",
                    entity_id=project_id, details={"nota": body.nota.strip()})
    await social_memory.record_entry(
        db, org_id, "revision_pattern", summary=body.nota.strip(),
        source_project_id=project_id, actor=user.get("email") or user.get("id"),
    )
    p2 = await db.flyer_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


# ===================== IMMAGINE (Requesty reale, sincrona) =====================

async def _image_readiness(org_id: str, project: dict) -> dict:
    motivi = []
    if project["status"] != "PROGETTO_PRONTO":
        motivi.append("Il progetto flyer (testo) non e' PRONTO.")
    semantic = project.get("semantic_check") or {"status": "NON_VERIFICATO"}
    if semantic.get("status") != "OK":
        motivi.append(f"Validazione semantica non superata ({semantic.get('status', 'NON_VERIFICATO')}).")
    if project.get("image_status") == "IN_GENERAZIONE":
        motivi.append("Una generazione immagine e' gia' in corso per questo progetto.")
    r = await _readiness(org_id)
    motivi.extend(r["motivi"])
    return {"pronto": not motivi, "motivi": motivi, "connessione": r["connessione"], "budget_residuo": r["budget_residuo"]}


@router.post("/projects/{project_id}/image/preview")
async def image_preview(project_id: str, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.flyer_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto flyer non trovato")
    r = await _image_readiness(org_id, p)
    conn = r.pop("connessione", None)
    return {**r, "provider": "requesty", "modello_effettivo": (conn or {}).get("effective_model"),
            "message": "Verra' generata UNA immagine reale via Requesty (POST /v1/images/generations). "
                       "Nessuna chiamata parte senza conferma esplicita."}


@router.post("/projects/{project_id}/image/generate")
async def image_generate(project_id: str, body: ConfirmBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rate_limit(f"flyer_image_generate:{project_id}", max_calls=5, window_seconds=60)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta prima di una generazione immagine reale.")
    p = await db.flyer_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto flyer non trovato")
    r = await _image_readiness(org_id, p)
    if not r["pronto"]:
        raise HTTPException(status_code=409, detail="; ".join(r["motivi"]))
    conn = r["connessione"]

    await db.flyer_projects.update_one({"id": project_id}, {"$set": {"image_status": "IN_GENERAZIONE", "updated_at": now_iso()}})
    try:
        risultato = requesty_gateway.genera_immagine(
            # Nessun campo 'image_model' dedicato sulla connessione Requesty in
            # questa fase (stessa connessione usata per il testo): modello
            # immagine confermato su docs.requesty.ai, non configurabile da UI oggi.
            model_id_requesty="azure/openai/gpt-image-1",
            prompt=p["content"]["prompt_immagine"],
            size="1024x1536" if "9:16" in (p["content"].get("formato") or "").lower() or "story" in (p["content"].get("formato") or "").lower() else "1024x1024",
            timeout=conn.get("timeout") or 60,
        )
    except RequestyNonConfigurato as exc:
        await db.flyer_projects.update_one({"id": project_id}, {"$set": {"image_status": "BLOCCATO", "updated_at": now_iso()}})
        raise HTTPException(status_code=409, detail=str(exc))
    except RequestyErroreSanificato as exc:
        # Nessun token noto in questo ramo (l'errore e' avvenuto prima di una
        # risposta completa): nessun costo registrato -- mai una cifra
        # inventata quando il consumo reale non e' misurabile. 'esito_incerto'
        # e' l'UNICO caso in cui una spesa potrebbe comunque essere avvenuta
        # lato Requesty senza che questa chiamata lo sappia: lo stato riflette
        # l'incertezza (mai dichiarato ne' riuscito ne' gratuito).
        nuovo = "ESITO_INCERTO" if exc.codice == "esito_incerto" else "FALLITO"
        await db.flyer_projects.update_one({"id": project_id}, {"$set": {
            "image_status": nuovo, "image_errore_codice": exc.codice, "image_errore_messaggio": exc.messaggio,
            "updated_at": now_iso()}})
        await log_audit(org_id=org_id, user=user, action="FLYER_IMAGE_GENERATE_ERROR", entity_type="flyer_project",
                        entity_id=project_id, status="ERROR", reason=exc.codice)
        raise HTTPException(status_code=502, detail=exc.messaggio)

    # La chiamata e' andata a buon fine ed ha consumato risorse: il costo va
    # SEMPRE registrato da qui in poi, anche se la verifica dell'asset (sotto)
    # dovesse poi fallire -- una generazione fallita dopo che il provider ha
    # gia' elaborato la richiesta resta comunque una spesa reale.
    stima_costo = await _registra_spesa_reale(org_id, project_id, risultato.input_tokens, risultato.output_tokens, source="flyer_image")

    # Verifica lato BACKEND (mai solo lato frontend): un'immagine e' 'pronta'
    # SOLO se esiste davvero un asset utilizzabile. url esterno (quando
    # fornito) usato direttamente; b64_json (default per gpt-image-1) va
    # decodificato, verificato e persistito PRIMA di dichiarare IMMAGINE_PRONTA.
    try:
        if risultato.url and risultato.url.strip():
            image_url = risultato.url.strip()
        elif risultato.b64_json and risultato.b64_json.strip():
            image_url = await _persist_image_asset(org_id, project_id, risultato.b64_json, risultato.mime_type)
        else:
            raise RequestyErroreSanificato("risposta_non_valida", "Nessun asset immagine utilizzabile nella risposta.")
    except RequestyErroreSanificato as exc:
        await db.flyer_projects.update_one({"id": project_id}, {"$set": {
            "image_status": "FALLITO", "image_errore_codice": exc.codice, "image_errore_messaggio": exc.messaggio,
            "generazione_immagine": {"stima_costo_usd": stima_costo, "input_tokens": risultato.input_tokens,
                                     "output_tokens": risultato.output_tokens},
            "updated_at": now_iso()}})
        await log_audit(org_id=org_id, user=user, action="FLYER_IMAGE_ASSET_INVALID", entity_type="flyer_project",
                        entity_id=project_id, status="ERROR", reason=exc.codice, details={"stima_costo_usd": stima_costo})
        raise HTTPException(status_code=502, detail=f"{exc.messaggio} (chiamata comunque addebitata: vedi budget).")

    await db.flyer_projects.update_one({"id": project_id}, {"$set": {
        "image_status": "IMMAGINE_PRONTA", "image_url": image_url, "image_mime_type": risultato.mime_type,
        "image_errore_codice": None, "image_errore_messaggio": None,
        "generazione_immagine": {"modello_effettivo": risultato.modello_effettivo, "latenza_ms": risultato.latenza_ms,
                                 "stima_costo_usd": stima_costo, "input_tokens": risultato.input_tokens,
                                 "output_tokens": risultato.output_tokens},
        "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="FLYER_IMAGE_GENERATED", entity_type="flyer_project",
                    entity_id=project_id, details={"modello_effettivo": risultato.modello_effettivo,
                                                   "latenza_ms": risultato.latenza_ms, "stima_costo_usd": stima_costo})
    p2 = await db.flyer_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


@router.get("/assets/{asset_id}")
async def get_image_asset(asset_id: str, user: dict = Depends(get_current_user)):
    """Serve l'asset persistito (mai un base64 enorme nel documento
    principale, mai una stringa che il frontend deve decodificare a mano):
    URL interno stabile, isolamento tenant verificato come ovunque."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    asset = await db.flyer_media_assets.find_one({"id": asset_id})
    if not asset or asset.get("organization_id") != org_id:
        raise HTTPException(status_code=404, detail="Asset non trovato")
    raw = base64.b64decode(asset["data_b64"])
    return Response(content=raw, media_type=asset.get("mime_type", "image/png"))


@router.post("/projects/{project_id}/image/approve")
async def image_approve(project_id: str, user: dict = Depends(require_roles("ADMIN", "APPROVATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.flyer_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto flyer non trovato")
    if p.get("image_status") != "IMMAGINE_PRONTA" or not p.get("image_url"):
        raise HTTPException(status_code=409, detail="Nessuna immagine realmente pronta da approvare.")
    await db.flyer_projects.update_one({"id": project_id}, {"$set": {
        "image_approvata": True, "image_approvata_da": user.get("email") or user.get("id"),
        "image_approvata_at": now_iso(), "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="FLYER_IMAGE_APPROVED", entity_type="flyer_project", entity_id=project_id)
    content = p.get("content") or {}
    await social_memory.record_entry(
        db, org_id, "format_preference", summary=f"flyer {content.get('formato', '')} approvato".strip(),
        data={"formato": content.get("formato")}, source_project_id=project_id,
        actor=user.get("email") or user.get("id"),
    )
    await social_memory.record_entry(
        db, org_id, "content_summary", summary=f"Flyer approvato — headline: {content.get('headline', '')}",
        source_project_id=project_id, actor=user.get("email") or user.get("id"),
    )
    p2 = await db.flyer_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


@router.post("/projects/{project_id}/image/richiedi-modifica")
async def image_richiedi_modifica(project_id: str, body: RichiediModificaBody,
                                  user: dict = Depends(require_roles("ADMIN", "APPROVATORE", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.flyer_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto flyer non trovato")
    if p.get("image_status") not in ("IMMAGINE_PRONTA", "BLOCCATO", "FALLITO"):
        raise HTTPException(status_code=409, detail="Richiesta di modifica immagine non applicabile allo stato corrente.")
    if not body.nota.strip():
        raise HTTPException(status_code=422, detail="Nota di modifica obbligatoria")
    await db.flyer_projects.update_one({"id": project_id}, {"$set": {
        "image_status": "NON_RICHIESTO", "image_url": None, "image_approvata": False,
        "image_approvata_da": None, "image_approvata_at": None,
        "image_nota_revisione": body.nota.strip(), "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="FLYER_IMAGE_REVISION_REQUESTED", entity_type="flyer_project",
                    entity_id=project_id, details={"nota": body.nota.strip()})
    p2 = await db.flyer_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)
