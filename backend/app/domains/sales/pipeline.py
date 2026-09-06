"""Sales Agent — orchestrazione completa: riceve un lead pronto per l'handoff
da Lead Generation (next_action == PRONTO_PER_SALES), analizza il lead,
decide canale/timing/next-best-action, delega la SCRITTURA del messaggio a
Content Creator (mai duplicata qui), gestisce le risposte del prospect
attraverso l'intera pipeline commerciale, e si collega — in lettura, mai
creando nulla al posto suo — al laboratorio Appointment Setter per riflettere
l'esito reale di una prenotazione."""
from __future__ import annotations

import logging
from typing import Optional

from ...models import new_id, now_iso
from ..content_creator import pipeline as content_creator_pipeline
from .models import PIPELINE_STAGES, STAGE_TERMINALI
from .strategy import analyze_lead, decide_next_action

logger = logging.getLogger("actelya.sales")


class SalesError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _lead_collection(db, lead_type: str):
    if lead_type not in ("aziende", "persone"):
        raise SalesError("TIPO_LEAD_SCONOSCIUTO", f"Tipo di lead sconosciuto: '{lead_type}'.")
    return db.lead_persons if lead_type == "persone" else db.lead_companies


async def create_opportunity(db, *, org_id: str, lead_id: str, lead_type: str, actor: str) -> dict:
    """Crea l'opportunità commerciale a partire da un lead qualificato da
    Lead Generation. Idempotente: un lead ha al più UNA opportunità (una
    richiesta ripetuta ritorna la stessa, mai una seconda)."""
    esistente = await db.sales_opportunities.find_one(
        {"organization_id": org_id, "lead_id": lead_id, "lead_type": lead_type}, {"_id": 0})
    if esistente:
        return esistente

    collezione = _lead_collection(db, lead_type)
    lead = await collezione.find_one({"id": lead_id, "organization_id": org_id}, {"_id": 0})
    if not lead:
        raise SalesError("LEAD_NON_TROVATO", "Lead non trovato per questa organizzazione.")

    azione_leadgen = lead.get("next_action") or {}
    if azione_leadgen.get("azione") != "PRONTO_PER_SALES":
        raise SalesError(
            "LEAD_NON_PRONTO",
            f"Il lead non è pronto per l'handoff a Sales (next_action attuale: "
            f"'{azione_leadgen.get('azione', 'sconosciuta')}' — {azione_leadgen.get('motivazione', '')}).",
        )

    analisi = analyze_lead(lead)
    next_best_action = "CONTATTA_ORA" if analisi["canale"] else "ESCALATION_UMANA"
    opportunita = {
        "id": new_id("opp"), "organization_id": org_id, "lead_id": lead_id, "lead_type": lead_type,
        "stage": "QUALIFICATO", "analysis": analisi, "next_best_action": next_best_action,
        "message_content_item_id": None, "appointment_proposal_id": None,
        "escalation_richiesta": next_best_action == "ESCALATION_UMANA",
        "escalation_nota": None,
        "history": [
            {"at": now_iso(), "stage": "NUOVO", "actor": actor, "motivo": "Handoff ricevuto da Lead Generation"},
            {"at": now_iso(), "stage": "QUALIFICATO", "actor": actor, "motivo": analisi["motivazione"]},
        ],
        "created_by": actor, "created_at": now_iso(), "updated_at": now_iso(),
    }
    try:
        await db.sales_opportunities.insert_one(opportunita)
    except Exception:
        esistente = await db.sales_opportunities.find_one(
            {"organization_id": org_id, "lead_id": lead_id, "lead_type": lead_type}, {"_id": 0})
        if esistente:
            return esistente
        raise
    return opportunita


async def request_message(db, opportunity: dict, *, actor: str) -> dict:
    """Delega a Content Creator la scrittura del messaggio commerciale (mai
    una seconda chiamata Requesty qui): crea un content_item BOZZA, pronto
    per essere generato/approvato nel laboratorio Content Creator."""
    if opportunity["stage"] not in ("QUALIFICATO", "FOLLOW_UP"):
        raise SalesError(
            "STATO_NON_VALIDO",
            f"Richiesta di messaggio non applicabile allo stage attuale: {opportunity['stage']}.",
        )
    analisi = opportunity["analysis"]
    risultato = await content_creator_pipeline.create_content_item(
        db, org_id=opportunity["organization_id"], actor=actor,
        objective=f"Messaggio commerciale per il lead {opportunity['lead_id']} ({analisi['stima_interesse']} interesse)",
        channel="sales", funnel_stage="BOFU", content_type="comunicazione_commerciale",
        campaign_id=None, tone_override=None, constraints="",
        brief=analisi["value_proposition"] + " " + analisi["pain_point"],
    )
    content_item_id = risultato["items"][0]["id"]
    await db.sales_opportunities.update_one(
        {"id": opportunity["id"]},
        {"$set": {"message_content_item_id": content_item_id, "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "stage": opportunity["stage"], "actor": actor,
                               "motivo": f"Messaggio richiesto a Content Creator (content_item {content_item_id})"}}},
    )
    return await db.sales_opportunities.find_one({"id": opportunity["id"]}, {"_id": 0})


async def sync_message_status(db, opportunity_id: str) -> dict:
    """Legge (sola lettura) lo stato del content_item collegato — mai una
    duplicazione della logica di Content Creator."""
    opportunity = await db.sales_opportunities.find_one({"id": opportunity_id}, {"_id": 0})
    if not opportunity or not opportunity.get("message_content_item_id"):
        return opportunity
    content_item = await db.content_items.find_one({"id": opportunity["message_content_item_id"]}, {"_id": 0})
    if not content_item:
        return opportunity
    return {**opportunity, "message_status": content_item.get("status")}


async def mark_contacted(db, opportunity: dict, *, actor: str) -> dict:
    """Conferma umana esplicita che il messaggio è stato davvero inviato
    (nessun invio automatico esiste in questa fase — vedi Tool Registry,
    canali di comunicazione individuali non configurati): richiede un
    content_item collegato e APPROVATO o COMPLETATO."""
    if opportunity["stage"] != "QUALIFICATO":
        raise SalesError("STATO_NON_VALIDO", f"Conferma di contatto non applicabile allo stage: {opportunity['stage']}.")
    if not opportunity.get("message_content_item_id"):
        raise SalesError("MESSAGGIO_MANCANTE", "Nessun messaggio richiesto a Content Creator per questa opportunità.")
    content_item = await db.content_items.find_one({"id": opportunity["message_content_item_id"]}, {"_id": 0})
    if not content_item or content_item.get("status") not in ("APPROVATO", "COMPLETATO"):
        raise SalesError(
            "MESSAGGIO_NON_PRONTO",
            f"Il messaggio non è ancora approvato in Content Creator (stato attuale: "
            f"{content_item.get('status') if content_item else 'sconosciuto'}).",
        )
    await db.sales_opportunities.update_one(
        {"id": opportunity["id"]},
        {"$set": {"stage": "CONTATTATO", "next_best_action": "NESSUNA_AZIONE", "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "stage": "CONTATTATO", "actor": actor,
                               "motivo": "Messaggio inviato (confermato manualmente)"}}},
    )
    return await db.sales_opportunities.find_one({"id": opportunity["id"]}, {"_id": 0})


async def record_response(db, opportunity: dict, *, response_type: str, note: str, actor: str) -> dict:
    """Applica la decisione deterministica (strategy.py) alla risposta del
    prospect e persiste la nuova fase/azione — mai una transizione
    silenziosa senza una regola esplicita."""
    esito = decide_next_action(stage=opportunity["stage"], response_type=response_type)
    aggiornamento = {
        "stage": esito["nuovo_stage"], "next_best_action": esito["next_best_action"], "updated_at": now_iso(),
    }
    if esito["richiede_escalation"]:
        aggiornamento["escalation_richiesta"] = True
    await db.sales_opportunities.update_one(
        {"id": opportunity["id"]},
        {"$set": aggiornamento,
         "$push": {"history": {"at": now_iso(), "stage": esito["nuovo_stage"], "actor": actor,
                               "motivo": f"Risposta '{response_type}': {esito['motivazione']}" + (f" — nota: {note}" if note else "")}}},
    )
    return await db.sales_opportunities.find_one({"id": opportunity["id"]}, {"_id": 0})


async def resolve_escalation(db, opportunity: dict, *, note: str, actor: str) -> dict:
    if not opportunity.get("escalation_richiesta"):
        raise SalesError("NESSUNA_ESCALATION", "Nessuna escalation da risolvere per questa opportunità.")
    if not note or not note.strip():
        raise SalesError("NOTA_OBBLIGATORIA", "Nota di risoluzione obbligatoria.")
    await db.sales_opportunities.update_one(
        {"id": opportunity["id"]},
        {"$set": {"escalation_richiesta": False, "escalation_nota": note.strip(), "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "stage": opportunity["stage"], "actor": actor,
                               "motivo": f"Escalation risolta manualmente: {note.strip()}"}}},
    )
    return await db.sales_opportunities.find_one({"id": opportunity["id"]}, {"_id": 0})


async def link_appointment(db, opportunity: dict, *, proposal_id: str, actor: str) -> dict:
    """Collega l'opportunità a una proposta già creata nel laboratorio
    Appointment Setter (mai creata qui: la disponibilità/proposta/booking
    restano responsabilità esclusiva di quel dominio, per confine di
    responsabilità esplicito)."""
    if opportunity["stage"] != "RICHIESTA_APPUNTAMENTO":
        raise SalesError(
            "STATO_NON_VALIDO", f"Collegamento appuntamento possibile solo da RICHIESTA_APPUNTAMENTO "
                                f"(stato attuale: {opportunity['stage']}).")
    proposta = await db.appointment_proposals.find_one(
        {"id": proposal_id, "organization_id": opportunity["organization_id"]}, {"_id": 0})
    if not proposta:
        raise SalesError("PROPOSTA_NON_TROVATA", "Proposta di appuntamento non trovata per questa organizzazione.")
    await db.sales_opportunities.update_one(
        {"id": opportunity["id"]},
        {"$set": {"appointment_proposal_id": proposal_id, "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "stage": opportunity["stage"], "actor": actor,
                               "motivo": f"Collegata proposta di appuntamento {proposal_id}"}}},
    )
    return await sync_appointment_status(db, opportunity["id"])


async def sync_appointment_status(db, opportunity_id: str) -> dict:
    """Legge (sola lettura) l'esito reale della prenotazione collegata e
    fa avanzare/retrocedere la pipeline di conseguenza — mai una conferma
    dichiarata senza una risposta reale del provider calendario (quella
    garanzia resta interamente di domains/appointments)."""
    opportunity = await db.sales_opportunities.find_one({"id": opportunity_id}, {"_id": 0})
    if not opportunity or not opportunity.get("appointment_proposal_id"):
        return opportunity
    prenotazioni = await db.appointment_bookings.find(
        {"proposal_id": opportunity["appointment_proposal_id"]}, {"_id": 0},
    ).sort("created_at", -1).to_list(1)
    if not prenotazioni:
        return opportunity
    prenotazione = prenotazioni[0]
    stato_booking = prenotazione.get("status")

    if stato_booking == "CONFERMATA" and opportunity["stage"] == "RICHIESTA_APPUNTAMENTO":
        await db.sales_opportunities.update_one(
            {"id": opportunity_id},
            {"$set": {"stage": "APPUNTAMENTO_FISSATO", "next_best_action": "NESSUNA_AZIONE", "updated_at": now_iso()},
             "$push": {"history": {"at": now_iso(), "stage": "APPUNTAMENTO_FISSATO", "actor": "sistema",
                                   "motivo": "Prenotazione confermata dal provider calendario"}}},
        )
    elif stato_booking in ("CANCELLATA", "CANCELLAZIONE_INCERTA", "FALLITA") and opportunity["stage"] in (
            "RICHIESTA_APPUNTAMENTO", "APPUNTAMENTO_FISSATO"):
        await db.sales_opportunities.update_one(
            {"id": opportunity_id},
            {"$set": {"stage": "FOLLOW_UP", "next_best_action": "INVIA_FOLLOW_UP", "updated_at": now_iso()},
             "$push": {"history": {"at": now_iso(), "stage": "FOLLOW_UP", "actor": "sistema",
                                   "motivo": f"Prenotazione non confermata (stato provider: {stato_booking}): "
                                            f"ripristinato il follow-up."}}},
        )
    return await db.sales_opportunities.find_one({"id": opportunity_id}, {"_id": 0})


# Ordine di avanzamento manuale per gli stage tardivi (giudizio commerciale
# umano, non automatizzabile da un segnale di sistema): mai un salto
# all'indietro, mai un salto di più di uno stage alla volta.
_ORDINE_STAGE_TARDIVI = ("APPUNTAMENTO_FISSATO", "OPPORTUNITA", "PROPOSTA", "NEGOZIAZIONE", "VINTO")


async def advance_stage(db, opportunity: dict, *, new_stage: str, actor: str, note: str = "") -> dict:
    """Avanzamento manuale esplicito (OPPORTUNITA -> PROPOSTA -> NEGOZIAZIONE
    -> VINTO), o chiusura a PERSO da qualunque stage non terminale — mai un
    salto multiplo negli stage tardivi, mai una riapertura di uno stage
    terminale."""
    if opportunity["stage"] in STAGE_TERMINALI:
        raise SalesError("STATO_TERMINALE", f"L'opportunità è già in stato terminale '{opportunity['stage']}'.")
    if new_stage not in PIPELINE_STAGES:
        raise SalesError("STAGE_SCONOSCIUTO", f"Stage sconosciuto: '{new_stage}'.")
    if new_stage == "PERSO":
        pass  # chiusura a perso sempre ammessa da qualunque stage non terminale
    elif opportunity["stage"] in _ORDINE_STAGE_TARDIVI and new_stage in _ORDINE_STAGE_TARDIVI:
        indice_attuale = _ORDINE_STAGE_TARDIVI.index(opportunity["stage"])
        indice_nuovo = _ORDINE_STAGE_TARDIVI.index(new_stage)
        if indice_nuovo != indice_attuale + 1:
            raise SalesError(
                "TRANSIZIONE_NON_VALIDA",
                f"Da '{opportunity['stage']}' si può avanzare solo a "
                f"'{_ORDINE_STAGE_TARDIVI[indice_attuale + 1] if indice_attuale + 1 < len(_ORDINE_STAGE_TARDIVI) else 'nessuno stage successivo'}'.",
            )
    else:
        raise SalesError(
            "TRANSIZIONE_NON_VALIDA",
            f"Avanzamento manuale non applicabile da '{opportunity['stage']}' a '{new_stage}'.",
        )
    await db.sales_opportunities.update_one(
        {"id": opportunity["id"]},
        {"$set": {"stage": new_stage, "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "stage": new_stage, "actor": actor, "motivo": note or "Avanzamento manuale"}}},
    )
    return await db.sales_opportunities.find_one({"id": opportunity["id"]}, {"_id": 0})
