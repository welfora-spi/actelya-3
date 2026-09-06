"""Appointment Setter — endpoint HTTP. Autenticazione, ruoli sulle scritture,
isolamento per organizzazione, paginazione uniforme (riusa
domains/leadgen/pagination.py: stesso contratto page/page_size/items/total/
pages in tutto il backend, mai duplicato)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ...audit import log_audit
from ...config import DEFAULT_ORG_ID
from ...db import db
from ...deps import assert_same_org, get_current_user, rate_limit, require_roles
from ...models import base_record, new_id, now_iso, touch
from ...security import encrypt_secret, mask_secret, vault_available
from ..leadgen.pagination import DEFAULT_PAGE_SIZE, paginate, resolve_sort
from . import calendar_adapters, pipeline, scheduling
from .models import (
    PROVIDER_TYPES,
    ApprovalBody,
    AvailabilityWindowBody,
    BookingConfirmBody,
    CalendarConnectionBody,
    CancelBody,
    ProposalBody,
    RescheduleBody,
    ResolveCancellationBody,
)

router = APIRouter(prefix="/appointments", tags=["appointments"])

_BLOCKED_QUALIFICATION = {"EXCLUDED", "DO_NOT_CONTACT"}
_BLOCKED_COMPLIANCE = {"BLOCKED", "DO_NOT_CONTACT"}


def _public_connection(c: dict) -> dict:
    return {k: v for k, v in c.items() if k not in (
        "_id", "access_token_encrypted", "refresh_token_encrypted", "api_key_encrypted")}


def _public_proposal(p: dict) -> dict:
    return {k: v for k, v in p.items() if k != "_id"}


def _public_booking(b: dict) -> dict:
    return {k: v for k, v in b.items() if k != "_id"}


async def _status_for(connection: dict) -> str:
    if connection.get("status") == "ERRORE":
        return "ERRORE"
    adapter = calendar_adapters.build_adapter(connection)
    return "VERIFICATO" if connection.get("verified") and adapter.configured else (
        "CONFIGURATO" if adapter.configured else "NON_CONFIGURATO")


# ==================== Connessioni calendario ====================
@router.get("/connections")
async def list_connections(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.appointment_connections.find({"organization_id": org_id}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return [_public_connection(c) for c in rows]


@router.post("/connections")
async def create_connection(body: CalendarConnectionBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    if body.provider_type not in PROVIDER_TYPES:
        raise HTTPException(status_code=400, detail=f"Provider non supportato: '{body.provider_type}'.")
    if (body.access_token or body.refresh_token or body.api_key) and not vault_available():
        raise HTTPException(status_code=503, detail="MASTER_KEY non configurata: impossibile salvare segreti in modo sicuro.")

    rec = base_record(org_id, user["id"])
    rec.update({
        "id": new_id("apptconn"), "name": body.name, "provider_type": body.provider_type,
        "calendar_id": body.calendar_id, "timezone": body.timezone, "active": body.active,
        "status": "NON_CONFIGURATO", "verified": False, "last_test_at": None, "last_test_result": None,
        "access_token_encrypted": encrypt_secret(body.access_token) if body.access_token else None,
        "refresh_token_encrypted": encrypt_secret(body.refresh_token) if body.refresh_token else None,
        "api_key_encrypted": encrypt_secret(body.api_key) if body.api_key else None,
        "api_key_masked": mask_secret(body.api_key) if body.api_key else "",
    })
    if body.access_token or body.api_key:
        rec["status"] = "CONFIGURATO"
    await db.appointment_connections.insert_one(rec)
    await log_audit(org_id=org_id, user=user, action="APPT_CONNECTION_CREATED",
                    entity_type="appointment_connection", entity_id=rec["id"],
                    details={"provider_type": body.provider_type})
    return _public_connection(rec)


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str, user: dict = Depends(require_roles("ADMIN"))):
    c = await db.appointment_connections.find_one({"id": connection_id})
    assert_same_org(c, user, "Connessione non trovata")
    await db.appointment_connections.delete_one({"id": connection_id})
    await log_audit(org_id=c["organization_id"], user=user, action="APPT_CONNECTION_DELETED",
                    entity_type="appointment_connection", entity_id=connection_id)
    return {"ok": True}


@router.get("/connections/oauth/authorize-url")
async def oauth_authorize_url(provider_type: str, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    state = f"{org_id}:{uuid.uuid4().hex}"
    url = calendar_adapters.oauth_authorize_url(provider_type, state)
    if not url:
        return {"status": "NON_CONFIGURATO",
               "motivo": f"App OAuth per '{provider_type}' non configurata (variabili d'ambiente assenti)."}
    return {"status": "OK", "authorize_url": url, "state": state}


@router.post("/connections/{connection_id}/oauth/callback")
async def oauth_callback(connection_id: str, code: str, user: dict = Depends(require_roles("ADMIN"))):
    c = await db.appointment_connections.find_one({"id": connection_id})
    assert_same_org(c, user, "Connessione non trovata")
    tokens = calendar_adapters.oauth_exchange_code(c["provider_type"], code)
    if not tokens or not tokens.get("access_token"):
        raise HTTPException(status_code=502, detail="Scambio del codice OAuth non riuscito.")
    aggiornamento = {"status": "CONFIGURATO", "verified": False, "updated_at": now_iso(),
                     "access_token_encrypted": encrypt_secret(tokens["access_token"])}
    if tokens.get("refresh_token"):
        aggiornamento["refresh_token_encrypted"] = encrypt_secret(tokens["refresh_token"])
    await db.appointment_connections.update_one({"id": connection_id}, {"$set": aggiornamento})
    await log_audit(org_id=c["organization_id"], user=user, action="APPT_CONNECTION_OAUTH_COMPLETED",
                    entity_type="appointment_connection", entity_id=connection_id)
    return _public_connection(await db.appointment_connections.find_one({"id": connection_id}, {"_id": 0}))


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str, user: dict = Depends(require_roles("ADMIN"))):
    rate_limit(f"testapptconn:{connection_id}", max_calls=5, window_seconds=60)
    c = await db.appointment_connections.find_one({"id": connection_id})
    assert_same_org(c, user, "Connessione non trovata")
    adapter = calendar_adapters.build_adapter(c)
    if not adapter.configured:
        await db.appointment_connections.update_one({"id": connection_id}, {"$set": {
            "status": "NON_CONFIGURATO", "verified": False, "last_test_at": now_iso(),
            "last_test_result": "NON_CONFIGURATO",
        }})
        return {"status": "NON_CONFIGURATO", "verified": False}
    ok, motivo = adapter.verify()
    await db.appointment_connections.update_one({"id": connection_id}, {"$set": {
        "status": "VERIFICATO" if ok else "ERRORE", "verified": ok, "last_test_at": now_iso(),
        "last_test_result": "OK" if ok else (motivo or "ERRORE"),
    }})
    await log_audit(org_id=c["organization_id"], user=user, action="APPT_CONNECTION_TESTED",
                    entity_type="appointment_connection", entity_id=connection_id, details={"ok": ok, "motivo": motivo})
    return {"status": "VERIFICATO" if ok else "ERRORE", "verified": ok, "motivo": motivo}


@router.put("/connections/{connection_id}/availability")
async def set_availability(connection_id: str, windows: list[AvailabilityWindowBody],
                           user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    c = await db.appointment_connections.find_one({"id": connection_id})
    assert_same_org(c, user, "Connessione non trovata")
    valori = [w.model_dump() for w in windows]
    await db.appointment_connections.update_one({"id": connection_id}, {"$set": {"availability": valori, "updated_at": now_iso()}})
    return {"availability": valori}


# ==================== Proposte ====================
async def _fetch_lead(org_id: str, lead_id: str, lead_type: str) -> dict:
    collezione = db.lead_persons if lead_type == "persone" else db.lead_companies
    lead = await collezione.find_one({"id": lead_id, "organization_id": org_id}, {"_id": 0})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead non trovato.")
    if lead.get("compliance_status") in _BLOCKED_COMPLIANCE or lead.get("qualification_status") in _BLOCKED_QUALIFICATION:
        raise HTTPException(status_code=409, detail="Lead non contattabile (opt-out, opposizione o DO_NOT_CONTACT).")
    return lead


@router.post("/proposals")
async def create_proposal(body: ProposalBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    conn = await db.appointment_connections.find_one({"id": body.connection_id})
    assert_same_org(conn, user, "Connessione non trovata")
    await _fetch_lead(org_id, body.lead_id, body.lead_type)

    inizio = datetime.now(timezone.utc)
    if body.search_from:
        try:
            inizio = datetime.fromisoformat(body.search_from.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="search_from non è una data ISO valida.")

    adapter = calendar_adapters.build_adapter(conn)
    slots = []
    if adapter.configured:
        fine_ricerca = inizio.replace(hour=23, minute=59)
        busy = adapter.list_busy(inizio.isoformat(), fine_ricerca.isoformat())
        slots = scheduling.compute_free_slots(
            availability_windows=conn.get("availability") or [], busy_slots=busy, start=inizio,
            days=body.search_days, duration_minutes=body.duration_minutes, timezone_name=conn.get("timezone", "UTC"),
        )

    rec = base_record(org_id, user["id"])
    rec.update({
        "id": new_id("apptprop"), "connection_id": body.connection_id, "lead_id": body.lead_id,
        "lead_type": body.lead_type, "campaign_id": body.campaign_id, "duration_minutes": body.duration_minutes,
        "message_template": body.message_template, "proposed_slots": slots,
        "status": "IN_ATTESA_APPROVAZIONE" if slots else "BOZZA",
        "connection_configured": adapter.configured,
    })
    await db.appointment_proposals.insert_one(rec)
    await log_audit(org_id=org_id, user=user, action="APPT_PROPOSAL_CREATED",
                    entity_type="appointment_proposal", entity_id=rec["id"],
                    details={"lead_id": body.lead_id, "slot_count": len(slots)})
    return _public_proposal(rec)


_PROPOSALS_SORT = {"created_at": "created_at", "status": "status"}


@router.get("/proposals")
async def list_proposals(status: Optional[str] = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
                         sort_by: str = "created_at", sort_dir: str = "desc",
                         user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    query: dict = {"organization_id": org_id}
    if status:
        query["status"] = status
    campo, direzione = resolve_sort(sort_by, sort_dir, _PROPOSALS_SORT, "created_at")
    return await paginate(db.appointment_proposals, query, page=page, page_size=page_size,
                          sort_field=campo, direction=direzione)


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, user: dict = Depends(get_current_user)):
    p = await db.appointment_proposals.find_one({"id": proposal_id})
    assert_same_org(p, user, "Proposta non trovata")
    return _public_proposal(p)


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, body: ApprovalBody, user: dict = Depends(require_roles("ADMIN", "APPROVATORE"))):
    p = await db.appointment_proposals.find_one({"id": proposal_id})
    assert_same_org(p, user, "Proposta non trovata")
    if not p.get("proposed_slots"):
        raise HTTPException(status_code=409, detail="Nessuno slot proposto: impossibile approvare.")
    nuovo_stato = "APPROVATA" if body.approve else "RIFIUTATA"
    touch(p, user["id"], f"Proposta appuntamento: {'approvata' if body.approve else 'rifiutata'} — {body.note}".strip())
    await db.appointment_proposals.update_one({"id": proposal_id}, {"$set": {
        "status": nuovo_stato, "updated_at": now_iso(), "change_history": p["change_history"],
    }})
    await log_audit(org_id=p["organization_id"], user=user, action="APPT_PROPOSAL_APPROVAL",
                    entity_type="appointment_proposal", entity_id=proposal_id, details={"approve": body.approve})
    return {"id": proposal_id, "status": nuovo_stato}


# ==================== Prenotazioni ====================
@router.post("/proposals/{proposal_id}/book")
async def book_proposal(proposal_id: str, body: BookingConfirmBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta per la prenotazione.")
    p = await db.appointment_proposals.find_one({"id": proposal_id})
    assert_same_org(p, user, "Proposta non trovata")
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    try:
        booking = await pipeline.create_booking(db, org_id=org_id, proposal=p, slot_index=body.slot_index, actor=user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=org_id, user=user, action="APPT_BOOKING_REQUESTED",
                    entity_type="appointment_booking", entity_id=booking["id"], details={"proposal_id": proposal_id})
    return _public_booking(booking)


_BOOKINGS_SORT = {"created_at": "created_at", "start": "start", "status": "status"}


@router.get("/bookings")
async def list_bookings(status: Optional[str] = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
                        sort_by: str = "start", sort_dir: str = "asc",
                        user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    query: dict = {"organization_id": org_id}
    if status:
        query["status"] = status
    campo, direzione = resolve_sort(sort_by, sort_dir, _BOOKINGS_SORT, "start")
    return await paginate(db.appointment_bookings, query, page=page, page_size=page_size,
                          sort_field=campo, direction=direzione)


@router.get("/bookings/{booking_id}")
async def get_booking(booking_id: str, user: dict = Depends(get_current_user)):
    b = await db.appointment_bookings.find_one({"id": booking_id})
    assert_same_org(b, user, "Prenotazione non trovata")
    return _public_booking(b)


@router.post("/bookings/{booking_id}/cancel")
async def cancel_booking_endpoint(booking_id: str, body: CancelBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    b = await db.appointment_bookings.find_one({"id": booking_id})
    assert_same_org(b, user, "Prenotazione non trovata")
    if b["status"] in ("CANCELLATA", "SOSTITUITA", "FALLITA", "CANCELLAZIONE_INCERTA"):
        raise HTTPException(status_code=409,
                            detail=f"Prenotazione già in stato terminale o da riconciliare: {b['status']}.")
    aggiornata = await pipeline.cancel_booking(db, b, actor=user["id"], reason=body.reason)
    await log_audit(org_id=b["organization_id"], user=user, action="APPT_BOOKING_CANCELLED",
                    entity_type="appointment_booking", entity_id=booking_id,
                    details={"reason": body.reason, "status": aggiornata["status"]})
    return _public_booking(aggiornata)


@router.post("/bookings/{booking_id}/reconcile-cancellation")
async def reconcile_cancellation_endpoint(booking_id: str, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    b = await db.appointment_bookings.find_one({"id": booking_id})
    assert_same_org(b, user, "Prenotazione non trovata")
    if b["status"] != "CANCELLAZIONE_INCERTA":
        raise HTTPException(status_code=409, detail=f"Nessuna riconciliazione necessaria: stato {b['status']}.")
    aggiornata = await pipeline.reconcile_cancellation(db, b, actor=user["id"])
    if aggiornata["status"] == "CANCELLATA":
        # Un'eventuale saga di riprogrammazione lasciata in attesa di questa
        # conferma puo' ora proseguire (mai automaticamente dall'interno
        # della riconciliazione stessa: solo qui, dopo l'esito).
        await pipeline.continua_saga_in_sospeso_per_booking(db, booking_id)
    await log_audit(org_id=b["organization_id"], user=user, action="APPT_BOOKING_CANCELLATION_RECONCILED",
                    entity_type="appointment_booking", entity_id=booking_id, details={"status": aggiornata["status"]})
    return _public_booking(aggiornata)


@router.post("/bookings/{booking_id}/resolve-cancellation")
async def resolve_cancellation_endpoint(booking_id: str, body: ResolveCancellationBody,
                                        user: dict = Depends(require_roles("ADMIN"))):
    b = await db.appointment_bookings.find_one({"id": booking_id})
    assert_same_org(b, user, "Prenotazione non trovata")
    try:
        aggiornata = await pipeline.resolve_cancellation_manually(db, b, actor=user["id"], note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=b["organization_id"], user=user, action="APPT_BOOKING_CANCELLATION_RESOLVED_MANUALLY",
                    entity_type="appointment_booking", entity_id=booking_id, details={"note": body.note})
    return _public_booking(aggiornata)


@router.post("/bookings/{booking_id}/reschedule")
async def reschedule_booking_endpoint(booking_id: str, body: RescheduleBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    b = await db.appointment_bookings.find_one({"id": booking_id})
    assert_same_org(b, user, "Prenotazione non trovata")
    if b["status"] not in ("CONFERMATA", "PIANIFICATA", "IN_CODA"):
        raise HTTPException(status_code=409, detail=f"Prenotazione non riprogrammabile dallo stato: {b['status']}.")
    try:
        nuova = await pipeline.reschedule_booking(db, b, new_start_iso=body.new_start, actor=user["id"], reason=body.reason)
    except ValueError as exc:
        await log_audit(org_id=b["organization_id"], user=user, action="APPT_BOOKING_RESCHEDULE_FALLITA",
                        entity_type="appointment_booking", entity_id=booking_id,
                        details={"new_start": body.new_start, "motivo": str(exc)})
        raise HTTPException(status_code=409, detail=str(exc))
    await log_audit(org_id=b["organization_id"], user=user, action="APPT_BOOKING_RESCHEDULE_COMPLETATA",
                    entity_type="appointment_booking", entity_id=booking_id, details={"new_booking_id": nuova["id"]})
    return _public_booking(nuova)
