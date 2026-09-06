"""Content Creator — endpoint HTTP. Autenticazione, ruoli sulle scritture,
isolamento per organizzazione, paginazione uniforme (riusa
domains/leadgen/pagination.py: stesso contratto in tutto il backend)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ...audit import log_audit
from ...config import DEFAULT_ORG_ID
from ...db import db
from ...deps import assert_same_org, get_current_user, require_roles
from ..leadgen.pagination import DEFAULT_PAGE_SIZE, paginate, resolve_sort
from . import pipeline
from .models import (
    ApprovalBody,
    ConfirmBody,
    ContentRequestBody,
    LinkMediaBody,
    ResolveUncertainBody,
    RevisionRequestBody,
)
from .pipeline import ContentCreatorError

router = APIRouter(prefix="/content-creator", tags=["content-creator"])


def _public(item: dict) -> dict:
    return {k: v for k, v in item.items() if k != "_id"}


@router.post("/items")
async def create_items(body: ContentRequestBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    try:
        risultato = await pipeline.create_content_item(
            db, org_id=org_id, actor=user["id"], objective=body.objective, channel=body.channel,
            funnel_stage=body.funnel_stage, content_type=body.content_type, campaign_id=body.campaign_id,
            tone_override=body.tone_override, constraints=body.constraints, brief=body.brief,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(org_id=org_id, user=user, action="CONTENT_CREATOR_ITEMS_CREATED",
                    entity_type="content_item", entity_id=",".join(i["id"] for i in risultato["items"]),
                    details={"content_types": risultato["content_types_decisi"], "motivazione": risultato["motivazione"]})
    return {
        "content_types_decisi": risultato["content_types_decisi"], "motivazione": risultato["motivazione"],
        "items": [_public(i) for i in risultato["items"]],
    }


_ITEMS_SORT = {"created_at": "created_at", "status": "status", "content_type": "content_type"}


@router.get("/items")
async def list_items(status: Optional[str] = None, content_type: Optional[str] = None,
                     campaign_id: Optional[str] = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
                     sort_by: str = "created_at", sort_dir: str = "desc",
                     user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    query: dict = {"organization_id": org_id}
    if status:
        query["status"] = status
    if content_type:
        query["content_type"] = content_type
    if campaign_id:
        query["campaign_id"] = campaign_id
    campo, direzione = resolve_sort(sort_by, sort_dir, _ITEMS_SORT, "created_at")
    return await paginate(db.content_items, query, page=page, page_size=page_size,
                          sort_field=campo, direction=direzione)


@router.get("/items/{item_id}")
async def get_item(item_id: str, user: dict = Depends(get_current_user)):
    item = await db.content_items.find_one({"id": item_id})
    assert_same_org(item, user, "Contenuto non trovato")
    return _public(item)


@router.get("/items/{item_id}/versions")
async def list_versions(item_id: str, user: dict = Depends(get_current_user)):
    item = await db.content_items.find_one({"id": item_id})
    assert_same_org(item, user, "Contenuto non trovato")
    rows = await db.content_item_versions.find(
        {"content_item_id": item_id}, {"_id": 0}).sort("version", -1).to_list(100)
    return rows


@router.post("/items/{item_id}/generate")
async def generate_item(item_id: str, body: ConfirmBody, user: dict = Depends(require_roles("ADMIN"))):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta prima di una chiamata reale a Requesty.")
    item = await db.content_items.find_one({"id": item_id})
    assert_same_org(item, user, "Contenuto non trovato")
    try:
        aggiornato = await pipeline.generate_content_item(db, item, actor=user["id"], user=user)
    except ContentCreatorError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=item["organization_id"], user=user, action="CONTENT_CREATOR_GENERATED",
                    entity_type="content_item", entity_id=item_id, details={"status": aggiornato["status"]})
    return _public(aggiornato)


@router.post("/items/{item_id}/approve")
async def approve_item(item_id: str, body: ApprovalBody, user: dict = Depends(require_roles("ADMIN", "APPROVATORE"))):
    item = await db.content_items.find_one({"id": item_id})
    assert_same_org(item, user, "Contenuto non trovato")
    try:
        aggiornato = await pipeline.approve_content_item(db, item, actor=user["id"], approve=body.approve, note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=item["organization_id"], user=user, action="CONTENT_CREATOR_APPROVAL",
                    entity_type="content_item", entity_id=item_id,
                    details={"approve": body.approve, "status": aggiornato["status"]})
    return _public(aggiornato)


@router.post("/items/{item_id}/request-revision")
async def request_revision_endpoint(item_id: str, body: RevisionRequestBody,
                                    user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    item = await db.content_items.find_one({"id": item_id})
    assert_same_org(item, user, "Contenuto non trovato")
    try:
        aggiornato = await pipeline.request_revision(db, item, actor=user["id"], note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=item["organization_id"], user=user, action="CONTENT_CREATOR_REVISION_REQUESTED",
                    entity_type="content_item", entity_id=item_id, details={"note": body.note})
    return _public(aggiornato)


@router.post("/items/{item_id}/resolve-uncertain")
async def resolve_uncertain_endpoint(item_id: str, body: ResolveUncertainBody,
                                     user: dict = Depends(require_roles("ADMIN"))):
    item = await db.content_items.find_one({"id": item_id})
    assert_same_org(item, user, "Contenuto non trovato")
    try:
        aggiornato = await pipeline.resolve_uncertain(db, item, actor=user["id"], note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=item["organization_id"], user=user, action="CONTENT_CREATOR_UNCERTAIN_RESOLVED",
                    entity_type="content_item", entity_id=item_id, details={"note": body.note})
    return _public(aggiornato)


@router.post("/items/{item_id}/link-media")
async def link_media_endpoint(item_id: str, body: LinkMediaBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    item = await db.content_items.find_one({"id": item_id})
    assert_same_org(item, user, "Contenuto non trovato")
    try:
        aggiornato = await pipeline.link_media_project(db, item, kind=body.kind, project_id=body.project_id, actor=user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=item["organization_id"], user=user, action="CONTENT_CREATOR_MEDIA_LINKED",
                    entity_type="content_item", entity_id=item_id,
                    details={"kind": body.kind, "project_id": body.project_id, "status": aggiornato["status"]})
    return _public(aggiornato)


@router.post("/items/{item_id}/sync-media")
async def sync_media_endpoint(item_id: str, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    item = await db.content_items.find_one({"id": item_id})
    assert_same_org(item, user, "Contenuto non trovato")
    aggiornato = await pipeline.sync_media_status(db, item_id)
    return _public(aggiornato)
