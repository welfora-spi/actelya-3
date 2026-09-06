"""Sales Agent — endpoint HTTP. Autenticazione, ruoli sulle scritture,
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
    CreateOpportunityBody,
    EscalationResolveBody,
    LinkAppointmentBody,
    RecordResponseBody,
    RequestMessageBody,
)
from .pipeline import SalesError

router = APIRouter(prefix="/sales", tags=["sales"])


def _public(opp: dict) -> dict:
    return {k: v for k, v in opp.items() if k != "_id"}


@router.post("/opportunities")
async def create_opportunity_endpoint(body: CreateOpportunityBody,
                                      user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    try:
        opportunita = await pipeline.create_opportunity(
            db, org_id=org_id, lead_id=body.lead_id, lead_type=body.lead_type, actor=user["id"])
    except SalesError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=org_id, user=user, action="SALES_OPPORTUNITY_CREATED",
                    entity_type="sales_opportunity", entity_id=opportunita["id"],
                    details={"lead_id": body.lead_id, "stage": opportunita["stage"]})
    return _public(opportunita)


_OPPORTUNITIES_SORT = {"created_at": "created_at", "stage": "stage", "updated_at": "updated_at"}


@router.get("/opportunities")
async def list_opportunities(stage: Optional[str] = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
                             sort_by: str = "created_at", sort_dir: str = "desc",
                             user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    query: dict = {"organization_id": org_id}
    if stage:
        query["stage"] = stage
    campo, direzione = resolve_sort(sort_by, sort_dir, _OPPORTUNITIES_SORT, "created_at")
    return await paginate(db.sales_opportunities, query, page=page, page_size=page_size,
                          sort_field=campo, direction=direzione)


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity(opportunity_id: str, user: dict = Depends(get_current_user)):
    opp = await db.sales_opportunities.find_one({"id": opportunity_id})
    assert_same_org(opp, user, "Opportunità non trovata")
    return _public(opp)


@router.post("/opportunities/{opportunity_id}/request-message")
async def request_message_endpoint(opportunity_id: str, body: RequestMessageBody,
                                   user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    opp = await db.sales_opportunities.find_one({"id": opportunity_id})
    assert_same_org(opp, user, "Opportunità non trovata")
    try:
        aggiornata = await pipeline.request_message(db, opp, actor=user["id"])
    except SalesError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=opp["organization_id"], user=user, action="SALES_MESSAGE_REQUESTED",
                    entity_type="sales_opportunity", entity_id=opportunity_id,
                    details={"content_item_id": aggiornata["message_content_item_id"]})
    return _public(aggiornata)


@router.get("/opportunities/{opportunity_id}/message-status")
async def message_status_endpoint(opportunity_id: str, user: dict = Depends(get_current_user)):
    opp = await db.sales_opportunities.find_one({"id": opportunity_id})
    assert_same_org(opp, user, "Opportunità non trovata")
    return _public(await pipeline.sync_message_status(db, opportunity_id))


@router.post("/opportunities/{opportunity_id}/mark-contacted")
async def mark_contacted_endpoint(opportunity_id: str, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    opp = await db.sales_opportunities.find_one({"id": opportunity_id})
    assert_same_org(opp, user, "Opportunità non trovata")
    try:
        aggiornata = await pipeline.mark_contacted(db, opp, actor=user["id"])
    except SalesError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=opp["organization_id"], user=user, action="SALES_MARKED_CONTACTED",
                    entity_type="sales_opportunity", entity_id=opportunity_id, details={})
    return _public(aggiornata)


@router.post("/opportunities/{opportunity_id}/record-response")
async def record_response_endpoint(opportunity_id: str, body: RecordResponseBody,
                                   user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    opp = await db.sales_opportunities.find_one({"id": opportunity_id})
    assert_same_org(opp, user, "Opportunità non trovata")
    try:
        aggiornata = await pipeline.record_response(
            db, opp, response_type=body.response_type, note=body.note, actor=user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await log_audit(org_id=opp["organization_id"], user=user, action="SALES_RESPONSE_RECORDED",
                    entity_type="sales_opportunity", entity_id=opportunity_id,
                    details={"response_type": body.response_type, "stage": aggiornata["stage"]})
    return _public(aggiornata)


@router.post("/opportunities/{opportunity_id}/resolve-escalation")
async def resolve_escalation_endpoint(opportunity_id: str, body: EscalationResolveBody,
                                      user: dict = Depends(require_roles("ADMIN"))):
    opp = await db.sales_opportunities.find_one({"id": opportunity_id})
    assert_same_org(opp, user, "Opportunità non trovata")
    try:
        aggiornata = await pipeline.resolve_escalation(db, opp, note=body.note, actor=user["id"])
    except SalesError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=opp["organization_id"], user=user, action="SALES_ESCALATION_RESOLVED",
                    entity_type="sales_opportunity", entity_id=opportunity_id, details={"note": body.note})
    return _public(aggiornata)


@router.post("/opportunities/{opportunity_id}/link-appointment")
async def link_appointment_endpoint(opportunity_id: str, body: LinkAppointmentBody,
                                    user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    opp = await db.sales_opportunities.find_one({"id": opportunity_id})
    assert_same_org(opp, user, "Opportunità non trovata")
    try:
        aggiornata = await pipeline.link_appointment(db, opp, proposal_id=body.proposal_id, actor=user["id"])
    except SalesError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=opp["organization_id"], user=user, action="SALES_APPOINTMENT_LINKED",
                    entity_type="sales_opportunity", entity_id=opportunity_id,
                    details={"proposal_id": body.proposal_id, "stage": aggiornata["stage"]})
    return _public(aggiornata)


@router.post("/opportunities/{opportunity_id}/sync-appointment")
async def sync_appointment_endpoint(opportunity_id: str, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    opp = await db.sales_opportunities.find_one({"id": opportunity_id})
    assert_same_org(opp, user, "Opportunità non trovata")
    return _public(await pipeline.sync_appointment_status(db, opportunity_id))


@router.post("/opportunities/{opportunity_id}/advance-stage")
async def advance_stage_endpoint(opportunity_id: str, new_stage: str, note: str = "",
                                 user: dict = Depends(require_roles("ADMIN", "APPROVATORE"))):
    opp = await db.sales_opportunities.find_one({"id": opportunity_id})
    assert_same_org(opp, user, "Opportunità non trovata")
    try:
        aggiornata = await pipeline.advance_stage(db, opp, new_stage=new_stage, actor=user["id"], note=note)
    except SalesError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=opp["organization_id"], user=user, action="SALES_STAGE_ADVANCED",
                    entity_type="sales_opportunity", entity_id=opportunity_id,
                    details={"new_stage": new_stage, "note": note})
    return _public(aggiornata)
