"""Social Media Manager — pubblicazione (item 14/15/16 della sessione
precedente; adapter reale Meta nella DECISIONE UFFICIALE "100% REALE").

Schema OBBLIGATORIO, mai aggirato:
    Social Media Manager -> approvazione -> PublishingService (qui) ->
    ConnectorGateway (brain/gateways/connector_gateway.py, invariato nella
    sua logica di sicurezza) -> adapter reale Meta (integrations/meta/,
    registrato qui sotto, mai importato da connector_gateway.py stesso).

Il percorso REALE e' raggiungibile SOLO quando TUTTE le condizioni
dell'item 7 sono vere (vedi _meta_readiness()): REAL_EXTERNAL_ACTIONS,
CONNECTOR_MODE='real', un adapter registrato (register_meta_adapters(),
richiamata da server.py allo startup), una connessione Meta configurata E
verificata per QUESTA organizzazione, l'asset da pubblicare pubblicamente
raggiungibile. Se anche una sola manca, la pubblicazione resta dry-run
(mai bloccata del tutto: il percorso dry-run e' sempre disponibile e
sicuro) — MAI un'azione reale con una condizione mancante.

Approvazione (item 4) e compliance (item 5) restano SEMPRE gate bloccanti
(409) indipendenti dalla modalita' reale/dry-run: senza di essi nessuna
pubblicazione, nemmeno in dry-run, puo' avvenire."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..brain import config as brain_config
from ..brain.gateways.connector_gateway import ConnectorRequest, get_connector_gateway
from ..brain.safety.errors import AzioneEsternaBloccata, RichiestaConnettoreNonValida
from ..db import db
from ..deps import get_current_user, require_roles, rate_limit, assert_same_org
from ..audit import log_audit
from ..models import now_iso, base_record, new_id
from ..config import DEFAULT_ORG_ID
from ..security import decrypt_secret
from ..integrations.meta import facebook as meta_facebook, instagram as meta_instagram
from ..integrations.meta.errors import MetaConnectorError, MetaMediaProcessingError, MetaTimeout
from . import meta_connections, social_memory

logger = logging.getLogger("actelya.social_publishing")
router = APIRouter(prefix="/social/publishing", tags=["social-publishing"])

CHANNELS = frozenset({"instagram", "facebook"})
SOURCE_KINDS = frozenset({"reel", "flyer"})

# Macchina a stati — stesso stile esplicito di m2/engine.py::ALLOWED_TASK_TRANSITIONS.
# PUBLISH_UNCERTAIN (item 15): la richiesta e' partita ma nessuna risposta
# e' arrivata entro il timeout — l'esito reale (pubblicato o no) NON e' noto,
# mai trattato come fallito ne' come riuscito: richiede risoluzione manuale
# esplicita (vedi POST .../resolve-uncertain), mai un secondo publish alla
# cieca automatico.
ALLOWED_TRANSITIONS = {
    "DRAFT": {"AWAITING_APPROVAL", "CANCELLED"},
    "AWAITING_APPROVAL": {"APPROVED", "CANCELLED"},
    "APPROVED": {"SCHEDULED", "PUBLISHING", "CANCELLED"},
    "SCHEDULED": {"PUBLISHING", "CANCELLED"},
    "PUBLISHING": {"PUBLISHED", "FAILED", "PUBLISH_UNCERTAIN"},
    "PUBLISHED": set(),
    "FAILED": {"PUBLISHING", "CANCELLED"},  # un fallimento resta ritentabile, mai bloccato per sempre
    "PUBLISH_UNCERTAIN": {"APPROVED", "PUBLISHED", "CANCELLED"},  # solo via resolve-uncertain, mai un retry implicito
    "CANCELLED": set(),
}


class InvalidTransition(Exception):
    pass


async def _set_status(package_id: str, new_status: str, *, extra: Optional[dict] = None) -> dict:
    pkg = await db.social_publishing_packages.find_one({"id": package_id})
    cur = pkg["status"]
    if new_status != cur and new_status not in ALLOWED_TRANSITIONS.get(cur, set()):
        raise InvalidTransition(f"Transizione non consentita {cur} -> {new_status}")
    upd = {"status": new_status, "updated_at": now_iso()}
    if extra:
        upd.update(extra)
    await db.social_publishing_packages.update_one({"id": package_id}, {"$set": upd})
    pkg.update(upd)
    pkg.pop("_id", None)
    return pkg


def _public(p: dict) -> dict:
    return {
        "id": p["id"], "source_kind": p["source_kind"], "source_project_id": p["source_project_id"],
        "channel": p["channel"], "format": p.get("format"), "asset_url": p.get("asset_url"),
        "caption": p.get("caption"), "cta": p.get("cta"), "hashtags": p.get("hashtags", []),
        "status": p["status"], "scheduled_at": p.get("scheduled_at"),
        "dry_run": p.get("dry_run"), "connector_attempt_id": p.get("connector_attempt_id"),
        "idempotency_key": p.get("idempotency_key"),
        "approved_by": p.get("approved_by"), "approved_at": p.get("approved_at"),
        "compliance_status": p.get("compliance_status"),
        "published_at": p.get("published_at"), "external_post_id": p.get("external_post_id"),
        "permalink": p.get("permalink"),
        "error_code": p.get("error_code"), "error_message": p.get("error_message"),
        "created_by": p.get("created_by"), "created_at": p.get("created_at"), "updated_at": p.get("updated_at"),
    }


def _public_snapshot(s: dict) -> dict:
    return {
        "id": s["id"], "publishing_package_id": s["publishing_package_id"], "channel": s.get("channel"),
        "source_kind": s.get("source_kind"), "data_available": s.get("data_available", False),
        "impressions": s.get("impressions"), "reach": s.get("reach"), "views": s.get("views"),
        "likes": s.get("likes"), "comments": s.get("comments"), "shares": s.get("shares"),
        "saves": s.get("saves"), "clicks": s.get("clicks"), "engagement_score": s.get("engagement_score"),
        "note": s.get("note"), "created_at": s.get("created_at"),
    }


async def _fetch_source(source_kind: str, source_project_id: str, org_id: str) -> dict:
    coll = db.reel_projects if source_kind == "reel" else db.flyer_projects
    proj = await coll.find_one({"id": source_project_id})
    if not proj or proj.get("organization_id") != org_id:
        raise HTTPException(status_code=404, detail=f"Progetto {source_kind} di origine non trovato")
    return proj


def _extract_publishable_fields(source_kind: str, project: dict) -> dict:
    """Estrae SOLO i campi gia' generati/approvati dal progetto sorgente:
    mai un nuovo contenuto inventato qui, questo modulo non chiama alcun
    provider AI, solo il progetto reel/flyer gia' pronto."""
    content = project.get("content") or {}
    if source_kind == "reel":
        return {
            "format": content.get("formato"), "asset_url": project.get("video_url"),
            "caption": content.get("caption"), "cta": content.get("cta"),
            "hashtags": content.get("hashtags", []),
        }
    # flyer: nessun campo 'caption' nativo (e' un layout statico, non un post) —
    # composta qui da headline/subheadline/body_text, MAI testo inventato:
    # concatenazione letterale dei campi gia' generati e approvati.
    parts = [content.get("headline", ""), content.get("subheadline", ""), content.get("body_text", "")]
    caption = " — ".join(p.strip() for p in parts if p and p.strip())
    return {
        "format": content.get("formato"), "asset_url": project.get("image_url"),
        "caption": caption, "cta": content.get("cta"), "hashtags": content.get("hashtags", []),
    }


def _is_source_approved(source_kind: str, project: dict) -> tuple[bool, str]:
    if not project.get("progetto_approvato"):
        return False, "Il testo del progetto di origine non è ancora approvato."
    media_field = "video_approvato" if source_kind == "reel" else "image_approvata"
    if not project.get(media_field):
        return False, f"Il media del progetto di origine non è ancora approvato ({media_field})."
    return True, ""


def _resolve_public_asset_url(asset_url: Optional[str]) -> Optional[str]:
    """Un URL gia' assoluto (es. CDN Runway/Requesty per un reel) resta
    invariato. Un percorso relativo servito da QUESTO backend (es.
    /api/flyer/assets/{id}) va reso assoluto con PUBLIC_BACKEND_URL (item
    10): senza questa variabile d'ambiente configurata, un asset relativo
    NON e' pubblicamente raggiungibile da Meta — None qui diventa un motivo
    esplicito in _meta_readiness(), mai un localhost passato in silenzio a
    facebook.py/instagram.py (che comunque lo rifiuterebbero di nuovo, vedi
    integrations/meta/client.py::assert_public_media_url — doppia barriera)."""
    if not asset_url:
        return None
    if asset_url.startswith(("http://", "https://")):
        return asset_url
    base = os.environ.get("PUBLIC_BACKEND_URL", "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}{asset_url}"


async def _meta_readiness(org_id: str, channel: str, asset_url: Optional[str]) -> dict:
    """item 7: calcola quali delle condizioni per un'azione REALE sono
    soddisfatte. NON decide da sola se bloccare la pubblicazione (i gate
    bloccanti — approvazione, compliance — restano verificati a monte in
    _execute_publish): decide SOLO se tentare 'real' invece di 'dry_run'.
    'pronto=False' non è mai un errore, è il percorso sicuro di default."""
    motivi: list[str] = []
    if not brain_config.REAL_EXTERNAL_ACTIONS:
        motivi.append("REAL_EXTERNAL_ACTIONS non abilitato.")
    if brain_config.CONNECTOR_MODE != "real":
        motivi.append("CONNECTOR_MODE non impostato su 'real'.")

    conn = await meta_connections._active_connection(org_id)
    if not conn:
        motivi.append("Nessuna connessione Meta configurata per questa organizzazione.")
        return {"pronto": False, "motivi": motivi, "connessione": None, "public_asset_url": None}

    if conn.get("mode") != "real":
        motivi.append("La connessione Meta per questa organizzazione è impostata su 'dry_run'.")
    if not conn.get("access_token_encrypted"):
        motivi.append("Nessun access token Meta configurato.")

    if channel == "facebook":
        if not conn.get("page_id"):
            motivi.append("Nessun Facebook Page ID configurato.")
        if conn.get("facebook_status") != meta_connections.STATUS_CONNECTED:
            motivi.append(f"Connessione Facebook non verificata (stato attuale: {conn.get('facebook_status')}).")
    else:
        if not conn.get("instagram_business_account_id"):
            motivi.append("Nessun Instagram Business Account ID configurato.")
        if conn.get("instagram_status") != meta_connections.STATUS_CONNECTED:
            motivi.append(f"Connessione Instagram non verificata (stato attuale: {conn.get('instagram_status')}).")

    public_url = _resolve_public_asset_url(asset_url)
    if not public_url:
        motivi.append("L'asset da pubblicare non ha un URL pubblicamente raggiungibile (configurare PUBLIC_BACKEND_URL).")

    return {"pronto": not motivi, "motivi": motivi, "connessione": conn, "public_asset_url": public_url}


def _compute_engagement_score(d: dict) -> Optional[float]:
    """Punteggio di engagement SOLO da metriche realmente misurate (mai
    inventato: se non c'e' una base di impression/reach su cui calcolarlo,
    None). Formula esplicita e dichiarata (non un 'algoritmo segreto'):
    interazioni pesate / copertura, in percentuale — usata da
    social_memory.py::derive_learning_suggestions() per confrontare
    formati diversi, sempre etichettata come dato derivato, mai un fatto."""
    base = d.get("impressions") or d.get("reach")
    if not base:
        return None
    interazioni = ((d.get("likes") or 0) + (d.get("comments") or 0) * 2
                  + (d.get("shares") or 0) * 3 + (d.get("saves") or 0) * 2)
    return round((interazioni / base) * 100, 4)


def _meta_compose_caption(caption: Optional[str], hashtags: Optional[list]) -> str:
    parti = [(caption or "").strip()]
    if hashtags:
        parti.append(" ".join(h if str(h).startswith("#") else f"#{h}" for h in hashtags))
    return "\n\n".join(p for p in parti if p)


def _meta_attendi_container_pronto(token: str, container_id: str, api_version: str, *,
                                   max_attempts: int = 15, wait_seconds: float = 3.0):
    """Poll BLOCCANTE limitato (item 9): la maggior parte delle immagini
    finisce in pochi secondi, molti Reel entro questa finestra — oltre, si
    smette di attendere e si segnala esito incerto (MAI un blocco a tempo
    indeterminato della richiesta HTTP che ha avviato la pubblicazione, MAI
    un 'pronto' dichiarato quando non lo e' davvero)."""
    import time
    for _ in range(max_attempts):
        stato = meta_instagram.get_container_status(token, container_id, api_version=api_version)
        if stato.status_code in meta_instagram.CONTAINER_STATI_TERMINALI:
            return stato
        time.sleep(wait_seconds)
    return meta_instagram.ContainerStato(container_id=container_id, status_code="IN_PROGRESS", status=None)


def _meta_publish_real_adapter(req: ConnectorRequest) -> dict:
    """Adapter reale registrato per action_type='publish_social' (vedi
    register_meta_adapters). Sincrono per costruzione (ConnectorGateway.
    request() e' sync): il chiamante async lo invoca SEMPRE via
    asyncio.to_thread (vedi _execute_publish), mai direttamente sul loop
    dell'evento. Riceve credenziali GIA' risolte/decifrate nel payload
    (nessun accesso a Mongo da qui: quello resta nella parte async del
    chiamante, che conosce l'organizzazione)."""
    p = req.payload
    channel = p["channel"]
    token = p["access_token"]
    api_version = p.get("graph_api_version") or "v21.0"
    caption = _meta_compose_caption(p.get("caption"), p.get("hashtags"))
    asset_url = p["public_asset_url"]
    is_video = p.get("source_kind") == "reel"

    if channel == "facebook":
        page_id = p["page_id"]
        if is_video:
            ris = meta_facebook.publish_page_video(token, page_id, video_url=asset_url, description=caption, api_version=api_version)
        else:
            ris = meta_facebook.publish_page_photo(token, page_id, image_url=asset_url, caption=caption, api_version=api_version)
        permalink = None
        try:
            info = meta_facebook.get_post_status(token, ris.external_post_id, api_version=api_version)
            permalink = info.get("permalink_url")
        except Exception:
            pass  # permalink e' un arricchimento, mai un motivo di fallimento della pubblicazione gia' avvenuta
        return {"external_post_id": ris.external_post_id, "permalink": permalink}

    if channel == "instagram":
        ig_id = p["instagram_business_account_id"]
        container_id = meta_instagram.create_media_container(
            token, ig_id, caption=caption,
            image_url=None if is_video else asset_url, video_url=asset_url if is_video else None,
            is_reel=is_video, api_version=api_version,
        )
        stato = _meta_attendi_container_pronto(token, container_id, api_version)
        if stato.status_code == "ERROR":
            raise MetaMediaProcessingError(f"Elaborazione media Instagram fallita (container {container_id}).")
        if stato.status_code != "FINISHED":
            raise MetaTimeout(
                f"Container Instagram {container_id} non pronto entro l'attesa massima: esito non "
                "verificabile ora, il container potrebbe completarsi in seguito (mai ripubblicato alla cieca)."
            )
        ris = meta_instagram.publish_container(token, ig_id, container_id, api_version=api_version)
        permalink = None
        try:
            permalink = meta_instagram.get_media_permalink(token, ris.external_post_id, api_version=api_version)
        except Exception:
            pass
        return {"external_post_id": ris.external_post_id, "permalink": permalink}

    raise MetaConnectorError("canale_non_supportato", f"Canale '{channel}' non supportato dal connector Meta.")


def _meta_metrics_real_adapter(req: ConnectorRequest) -> dict:
    p = req.payload
    channel = p["channel"]
    token = p["access_token"]
    api_version = p.get("graph_api_version") or "v21.0"
    external_id = p.get("external_post_id")
    if not external_id:
        return {"data_available": False, "note": "Nessun external_post_id disponibile per questo pacchetto."}
    m = (meta_facebook.get_post_insights(token, external_id, api_version=api_version) if channel == "facebook"
         else meta_instagram.get_media_insights(token, external_id, api_version=api_version))
    return {
        "data_available": m.data_available, "impressions": m.impressions, "reach": m.reach, "views": m.views,
        "likes": m.likes, "comments": m.comments, "shares": m.shares, "saves": m.saves, "clicks": m.clicks,
        "note": m.note,
    }


def register_meta_adapters(gateway=None) -> None:
    """Registra gli adapter reali Meta sul ConnectorGateway condiviso (o su
    uno passato esplicitamente, utile nei test per isolamento). Richiamata
    da server.py allo startup — la SOLA registrazione non abilita nulla da
    sola (serve ANCHE REAL_EXTERNAL_ACTIONS + CONNECTOR_MODE='real', vedi
    ConnectorGateway.request()), ma senza di essa il percorso reale
    resterebbe irraggiungibile anche a configurazione altrimenti corretta."""
    gw = gateway or get_connector_gateway()
    gw.register_real_adapter("publish_social", _meta_publish_real_adapter)
    gw.register_real_adapter("retrieve_metrics", _meta_metrics_real_adapter)


class NewPublishingPackageBody(BaseModel):
    source_kind: str
    source_project_id: str
    channel: str


@router.post("/packages")
async def create_package(body: NewPublishingPackageBody, user: dict = Depends(require_roles("OPERATORE", "ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    if body.source_kind not in SOURCE_KINDS:
        raise HTTPException(status_code=422, detail=f"source_kind deve essere uno tra {sorted(SOURCE_KINDS)}")
    if body.channel not in CHANNELS:
        raise HTTPException(status_code=422, detail=f"channel deve essere uno tra {sorted(CHANNELS)}")

    project = await _fetch_source(body.source_kind, body.source_project_id, org_id)
    ok, motivo = _is_source_approved(body.source_kind, project)
    if not ok:
        raise HTTPException(status_code=409, detail=motivo)
    semantic = project.get("semantic_check") or {}
    if semantic.get("status") != "OK":
        raise HTTPException(status_code=409, detail="Il contenuto di origine non ha superato la validazione di conformità.")

    fields = _extract_publishable_fields(body.source_kind, project)
    if not fields["asset_url"]:
        raise HTTPException(status_code=409, detail="Nessun asset (video/immagine) realmente disponibile da pubblicare.")

    rec = base_record(org_id, user["id"])
    rec.update({
        "id": new_id("pub"), "source_kind": body.source_kind, "source_project_id": body.source_project_id,
        "channel": body.channel, "status": "DRAFT", "scheduled_at": None,
        "dry_run": None, "connector_attempt_id": None, "idempotency_key": new_id("idem"),
        "approved_by": None, "approved_at": None, "compliance_status": semantic.get("status"),
        "published_at": None, "external_post_id": None, "error_code": None, "error_message": None,
        **fields,
    })
    await db.social_publishing_packages.insert_one(rec)
    # DRAFT -> AWAITING_APPROVAL immediato e tracciato: non c'e' altro da
    # completare prima della revisione (il contenuto e' gia' stato approvato
    # a monte), ma l'autorizzazione alla PUBBLICAZIONE resta un passo
    # esplicito e distinto (item 8/9), mai implicita nella creazione.
    pkg = await _set_status(rec["id"], "AWAITING_APPROVAL")
    await log_audit(org_id=org_id, user=user, action="PUBLISHING_PACKAGE_CREATED",
                    entity_type="publishing_package", entity_id=rec["id"],
                    details={"source_kind": body.source_kind, "channel": body.channel})
    return _public(pkg)


@router.get("/packages")
async def list_packages(source_project_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    query: dict = {"organization_id": org_id}
    if source_project_id:
        query["source_project_id"] = source_project_id
    rows = await db.social_publishing_packages.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [_public(p) for p in rows]


@router.get("/packages/{package_id}")
async def get_package(package_id: str, user: dict = Depends(get_current_user)):
    p = await db.social_publishing_packages.find_one({"id": package_id}, {"_id": 0})
    assert_same_org(p, user, "Pacchetto di pubblicazione non trovato")
    return _public(p)


@router.post("/packages/{package_id}/approve")
async def approve_package(package_id: str, user: dict = Depends(require_roles("APPROVATORE", "ADMIN"))):
    """Autorizzazione alla PUBBLICAZIONE: DISTINTA e successiva
    all'approvazione del contenuto/media (già avvenuta perché altrimenti il
    pacchetto non sarebbe potuto esistere — vedi create_package)."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.social_publishing_packages.find_one({"id": package_id})
    assert_same_org(p, user, "Pacchetto di pubblicazione non trovato")
    if p["status"] != "AWAITING_APPROVAL":
        raise HTTPException(status_code=409, detail="Il pacchetto non è in attesa di approvazione.")
    pkg = await _set_status(package_id, "APPROVED", extra={
        "approved_by": user.get("email") or user.get("id"), "approved_at": now_iso(),
    })
    await log_audit(org_id=org_id, user=user, action="PUBLISHING_PACKAGE_APPROVED",
                    entity_type="publishing_package", entity_id=package_id)
    return _public(pkg)


class ScheduleBody(BaseModel):
    scheduled_at: str  # ISO 8601, sempre nel futuro


@router.post("/packages/{package_id}/schedule")
async def schedule_package(package_id: str, body: ScheduleBody,
                           user: dict = Depends(require_roles("OPERATORE", "APPROVATORE", "ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.social_publishing_packages.find_one({"id": package_id})
    assert_same_org(p, user, "Pacchetto di pubblicazione non trovato")
    if p["status"] != "APPROVED":
        raise HTTPException(status_code=409, detail="Solo un pacchetto APPROVATO può essere programmato.")
    try:
        raw = body.scheduled_at.replace("Z", "+00:00")
        quando = datetime.fromisoformat(raw)
        if quando.tzinfo is None:
            quando = quando.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=422, detail="Data/ora di programmazione non valida (usa formato ISO 8601).")
    if quando <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="La data di programmazione deve essere nel futuro.")
    pkg = await _set_status(package_id, "SCHEDULED", extra={"scheduled_at": body.scheduled_at})
    await log_audit(org_id=org_id, user=user, action="PUBLISHING_PACKAGE_SCHEDULED",
                    entity_type="publishing_package", entity_id=package_id, details={"scheduled_at": body.scheduled_at})
    return _public(pkg)


@router.post("/packages/{package_id}/cancel")
async def cancel_package(package_id: str, user: dict = Depends(require_roles("OPERATORE", "APPROVATORE", "ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.social_publishing_packages.find_one({"id": package_id})
    assert_same_org(p, user, "Pacchetto di pubblicazione non trovato")
    if p["status"] not in ("DRAFT", "AWAITING_APPROVAL", "APPROVED", "SCHEDULED", "FAILED"):
        raise HTTPException(status_code=409, detail="Il pacchetto non può più essere annullato dal suo stato corrente.")
    pkg = await _set_status(package_id, "CANCELLED")
    await log_audit(org_id=org_id, user=user, action="PUBLISHING_PACKAGE_CANCELLED",
                    entity_type="publishing_package", entity_id=package_id)
    return _public(pkg)


class ConfirmBody(BaseModel):
    confirm: bool = False


async def _execute_publish(package_id: str, org_id: str, actor: str, *, actor_label: str = "system") -> dict:
    """Nucleo condiviso tra l'endpoint HTTP e il worker di scheduling (mai
    duplicata la logica). IDEMPOTENTE per costruzione: se il pacchetto è
    già PUBLISHED, ritorna subito lo stato esistente SENZA una seconda
    chiamata al connector — un retry (umano o del worker) non pubblica mai
    due volte (item 15)."""
    pkg = await db.social_publishing_packages.find_one({"id": package_id})
    if pkg["status"] == "PUBLISHED":
        pkg.pop("_id", None)
        return pkg
    if pkg["status"] not in ("APPROVED", "SCHEDULED", "FAILED"):
        raise HTTPException(status_code=409, detail="Stato non valido per la pubblicazione: serve un pacchetto APPROVATO, SCHEDULED, FAILED o PUBLISH_UNCERTAIN già risolto.")

    project = await _fetch_source(pkg["source_kind"], pkg["source_project_id"], org_id)
    semantic = project.get("semantic_check") or {}
    if semantic.get("status") != "OK":
        raise HTTPException(status_code=409, detail="Il contenuto di origine non ha (più) superato la validazione di conformità: pubblicazione bloccata.")

    readiness = await _meta_readiness(org_id, pkg["channel"], pkg.get("asset_url"))
    payload: dict = {
        "organization_id": org_id, "channel": pkg["channel"], "caption": pkg.get("caption"),
        "cta": pkg.get("cta"), "hashtags": pkg.get("hashtags"), "format": pkg.get("format"),
        "source_kind": pkg["source_kind"], "scheduled_at": pkg.get("scheduled_at"),
        "idempotency_key": pkg.get("idempotency_key"),
    }
    requested_mode = "dry_run"
    if readiness["pronto"]:
        conn = readiness["connessione"]
        payload.update({
            "access_token": decrypt_secret(conn["access_token_encrypted"]),
            "graph_api_version": conn.get("graph_api_version") or "v21.0",
            "page_id": conn.get("page_id"),
            "instagram_business_account_id": conn.get("instagram_business_account_id"),
            "public_asset_url": readiness["public_asset_url"],
        })
        requested_mode = "real"

    await _set_status(package_id, "PUBLISHING")
    gateway = get_connector_gateway()
    req = ConnectorRequest(
        action_type="publish_social", payload=payload,
        reason=f"Pubblicazione {pkg['source_kind']} '{pkg['source_project_id']}' su {pkg['channel']}",
        requested_mode=requested_mode,
    )
    try:
        # request() e' sincrona (puo' eseguire una chiamata HTTP bloccante
        # sul percorso reale): mai bloccare il loop asyncio, sempre in thread.
        result = await asyncio.to_thread(gateway.request, req)
    except (AzioneEsternaBloccata, RichiestaConnettoreNonValida) as exc:
        pkg2 = await _set_status(package_id, "FAILED", extra={
            "error_code": "connector_bloccato", "error_message": str(exc),
        })
        await log_audit(org_id=org_id, user={"email": actor_label}, action="PUBLISHING_FAILED",
                        entity_type="publishing_package", entity_id=package_id, status="ERROR", reason=str(exc))
        return pkg2
    except MetaTimeout as exc:
        # Esito incerto (item 15): la richiesta e' partita, l'esito reale
        # non e' noto. MAI un fallimento, MAI un successo, MAI un secondo
        # tentativo automatico: richiede risoluzione umana esplicita.
        pkg2 = await _set_status(package_id, "PUBLISH_UNCERTAIN", extra={
            "error_code": exc.codice, "error_message": exc.messaggio,
        })
        await log_audit(org_id=org_id, user={"email": actor_label}, action="PUBLISHING_UNCERTAIN",
                        entity_type="publishing_package", entity_id=package_id, status="ERROR", reason=exc.messaggio)
        return pkg2
    except MetaConnectorError as exc:
        pkg2 = await _set_status(package_id, "FAILED", extra={"error_code": exc.codice, "error_message": exc.messaggio})
        await log_audit(org_id=org_id, user={"email": actor_label}, action="PUBLISHING_FAILED",
                        entity_type="publishing_package", entity_id=package_id, status="ERROR", reason=exc.messaggio)
        return pkg2

    is_real = result.status == "ESEGUITO_REALE"
    external_id = result.data.get("external_post_id") if is_real else None
    permalink = result.data.get("permalink") if is_real else None
    pkg2 = await _set_status(package_id, "PUBLISHED", extra={
        "dry_run": not is_real, "connector_attempt_id": result.attempt_id,
        "published_at": now_iso(), "external_post_id": external_id, "permalink": permalink,
        "error_code": None, "error_message": None,
    })
    # Motivo esplicito e verificabile del dry-run (mai solo dichiarato): le
    # condizioni mancanti calcolate da _meta_readiness(), non una frase fissa.
    motivo_dry_run = "; ".join(readiness["motivi"]) if not is_real else None
    await log_audit(org_id=org_id, user={"email": actor_label}, action="PUBLISHING_SUCCEEDED",
                    entity_type="publishing_package", entity_id=package_id,
                    details={"dry_run": pkg2["dry_run"], "motivo_dry_run": motivo_dry_run,
                             "connector_attempt_id": result.attempt_id, "external_post_id": external_id})
    await social_memory.record_entry(
        db, org_id, "publish_outcome",
        summary=f"{pkg['channel']}/{pkg['source_kind']} pubblicato (dry_run={pkg2['dry_run']}).",
        data={"channel": pkg["channel"], "source_kind": pkg["source_kind"], "dry_run": pkg2["dry_run"]},
        source_project_id=pkg["source_project_id"], actor=actor_label,
    )
    return pkg2


@router.post("/packages/{package_id}/publish")
async def publish_package(package_id: str, body: ConfirmBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.social_publishing_packages.find_one({"id": package_id})
    assert_same_org(p, user, "Pacchetto di pubblicazione non trovato")
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta prima di avviare la pubblicazione.")
    rate_limit(f"social_publish:{package_id}", max_calls=5, window_seconds=60)
    pkg2 = await _execute_publish(package_id, org_id, user["id"], actor_label=user.get("email") or user.get("id"))
    return _public(pkg2)


class ResolveUncertainBody(BaseModel):
    nota: str
    found_external_post_id: Optional[str] = None  # valorizzato SOLO se un admin ha verificato manualmente su Meta che il post esiste davvero


@router.post("/packages/{package_id}/resolve-uncertain")
async def resolve_uncertain(package_id: str, body: ResolveUncertainBody, user: dict = Depends(require_roles("ADMIN"))):
    """Risolve manualmente un esito incerto (item 15): NON ripubblica mai
    automaticamente. Se l'admin ha verificato su Meta che il post esiste
    (found_external_post_id), il pacchetto passa a PUBLISHED con quell'id;
    altrimenti torna APPROVED, pronto per un nuovo tentativo esplicito."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.social_publishing_packages.find_one({"id": package_id})
    assert_same_org(p, user, "Pacchetto di pubblicazione non trovato")
    if p["status"] != "PUBLISH_UNCERTAIN":
        raise HTTPException(status_code=409, detail="Il pacchetto non ha un esito incerto da risolvere.")
    if not body.nota.strip():
        raise HTTPException(status_code=422, detail="Nota di risoluzione obbligatoria.")
    if body.found_external_post_id:
        pkg2 = await _set_status(package_id, "PUBLISHED", extra={
            "external_post_id": body.found_external_post_id, "dry_run": False,
            "published_at": now_iso(), "error_code": None, "error_message": None,
        })
    else:
        pkg2 = await _set_status(package_id, "APPROVED", extra={"error_code": None, "error_message": None})
    await log_audit(org_id=org_id, user=user, action="PUBLISHING_UNCERTAIN_RESOLVED",
                    entity_type="publishing_package", entity_id=package_id,
                    details={"nota": body.nota.strip(), "found_external_post_id": body.found_external_post_id})
    return _public(pkg2)


@router.post("/packages/{package_id}/metrics/refresh")
async def refresh_metrics(package_id: str, user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    pkg = await db.social_publishing_packages.find_one({"id": package_id})
    assert_same_org(pkg, user, "Pacchetto di pubblicazione non trovato")
    if pkg["status"] != "PUBLISHED":
        raise HTTPException(status_code=409, detail="Le metriche sono disponibili solo dopo la pubblicazione.")

    readiness = await _meta_readiness(org_id, pkg["channel"], pkg.get("asset_url"))
    payload: dict = {"channel": pkg["channel"], "external_post_id": pkg.get("external_post_id")}
    requested_mode = "dry_run"
    if readiness["pronto"] and pkg.get("external_post_id"):
        conn = readiness["connessione"]
        payload.update({
            "access_token": decrypt_secret(conn["access_token_encrypted"]),
            "graph_api_version": conn.get("graph_api_version") or "v21.0",
        })
        requested_mode = "real"

    gateway = get_connector_gateway()
    try:
        result = await asyncio.to_thread(gateway.request, ConnectorRequest(
            action_type="retrieve_metrics", payload=payload,
            reason=f"Recupero metriche pacchetto {package_id}", requested_mode=requested_mode,
        ))
    except (AzioneEsternaBloccata, RichiestaConnettoreNonValida) as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except MetaConnectorError as exc:
        raise HTTPException(status_code=502, detail=exc.messaggio)

    if result.status == "ESEGUITO_REALE":
        d = result.data
        snapshot = {
            "id": new_id("anlt"), "organization_id": org_id, "publishing_package_id": package_id,
            "channel": pkg["channel"], "source_kind": pkg["source_kind"],
            "data_available": bool(d.get("data_available")),
            "impressions": d.get("impressions"), "reach": d.get("reach"), "views": d.get("views"),
            "likes": d.get("likes"), "comments": d.get("comments"), "shares": d.get("shares"),
            "saves": d.get("saves"), "clicks": d.get("clicks"),
            "engagement_score": _compute_engagement_score(d) if d.get("data_available") else None,
            "connector_attempt_id": result.attempt_id,
            "note": d.get("note") or "", "created_at": now_iso(),
        }
    else:
        # dry-run: nessun provider reale ha risposto, quindi NESSUNA metrica
        # e' realmente disponibile — mai un valore inventato (item 16: 'null/
        # not_available e non zero inventato').
        snapshot = {
            "id": new_id("anlt"), "organization_id": org_id, "publishing_package_id": package_id,
            "channel": pkg["channel"], "source_kind": pkg["source_kind"], "data_available": False,
            "impressions": None, "reach": None, "views": None, "likes": None, "comments": None,
            "shares": None, "saves": None, "clicks": None, "engagement_score": None,
            "connector_attempt_id": result.attempt_id,
            "note": "; ".join(readiness["motivi"]) or "Metriche non disponibili (dry-run).",
            "created_at": now_iso(),
        }
    await db.social_analytics_snapshots.insert_one(snapshot)
    if snapshot["data_available"]:
        await social_memory.record_entry(
            db, org_id, "performance_note",
            summary=f"Metriche reali raccolte per {pkg['channel']}/{pkg['source_kind']}.",
            data=snapshot, source_project_id=pkg["source_project_id"],
        )
    return _public_snapshot(snapshot)


@router.get("/packages/{package_id}/metrics")
async def latest_metrics(package_id: str, user: dict = Depends(get_current_user)):
    p = await db.social_publishing_packages.find_one({"id": package_id}, {"_id": 0})
    assert_same_org(p, user, "Pacchetto di pubblicazione non trovato")
    snap = await db.social_analytics_snapshots.find_one(
        {"publishing_package_id": package_id}, {"_id": 0}, sort=[("created_at", -1)])
    if not snap:
        return {"data_available": False, "note": "Nessuna rilevazione ancora richiesta (POST .../metrics/refresh)."}
    return _public_snapshot(snap)


@router.get("/packages/{package_id}/metrics/history")
async def metrics_history(package_id: str, user: dict = Depends(get_current_user)):
    p = await db.social_publishing_packages.find_one({"id": package_id}, {"_id": 0})
    assert_same_org(p, user, "Pacchetto di pubblicazione non trovato")
    rows = await db.social_analytics_snapshots.find(
        {"publishing_package_id": package_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [_public_snapshot(s) for s in rows]


async def recover_on_startup() -> None:
    """Un riavvio del processo durante _execute_publish (fra PUBLISHING e il
    suo esito) lascerebbe altrimenti un pacchetto bloccato per sempre in
    PUBLISHING (nessun worker lo riprenderebbe mai: PUBLISHING non e' uno
    stato che lo scheduler interroga). Stesso principio di
    domains/engine.py::recover_on_startup: riportato in APPROVED, cosi'
    resta ritentabile con un normale POST .../publish (idempotente per
    costruzione, vedi _execute_publish)."""
    res = await db.social_publishing_packages.update_many(
        {"status": "PUBLISHING"}, {"$set": {"status": "APPROVED", "updated_at": now_iso()}})
    if res.modified_count:
        logger.info("Recovery: %s pacchetti di pubblicazione riportati in APPROVED", res.modified_count)


# --------- Worker di scheduling (stesso pattern di domains/engine.py) ---------
_worker_task = None


async def _tick_scheduler() -> int:
    """Pubblica (sempre in dry-run, mai una seconda volta per lo stesso
    pacchetto: vedi idempotenza in _execute_publish) i pacchetti SCHEDULED
    la cui scheduled_at e' gia' passata. Ritorna il numero elaborato (usato
    dai test, mai dal chiamante di produzione)."""
    now = datetime.now(timezone.utc).isoformat()
    dovuti = await db.social_publishing_packages.find(
        {"status": "SCHEDULED", "scheduled_at": {"$lte": now}}, {"_id": 0}).to_list(50)
    for pkg in dovuti:
        try:
            await _execute_publish(pkg["id"], pkg["organization_id"], "scheduler", actor_label="scheduler")
        except Exception:
            logger.exception("Errore nel worker di scheduling pubblicazioni per il pacchetto %s", pkg["id"])
    return len(dovuti)


async def scheduler_worker_loop():
    logger.info("Worker di scheduling pubblicazioni social avviato")
    while True:
        try:
            await _tick_scheduler()
        except Exception:
            logger.exception("Errore nel worker di scheduling pubblicazioni")
        await asyncio.sleep(5)


def start_scheduler_worker():
    global _worker_task
    if _worker_task is None:
        _worker_task = asyncio.create_task(scheduler_worker_loop())
