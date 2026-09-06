"""Appointment Setter — orchestrazione prenotazioni: creazione idempotente,
coda persistente con worker recuperabile (stesso pattern di
domains/leadgen/pipeline.py e domains/discovery.py), prevenzione doppie
prenotazioni, cancellazione/riprogrammazione, esito incerto.

Nessun appuntamento e' MAI dichiarato CONFERMATA senza una risposta OK
dell'adapter (reale o fake nei test) — un errore di rete o un timeout
producono ESITO_INCERTO, mai una conferma inventata."""
from __future__ import annotations

import asyncio
import logging

from ...models import new_id, now_iso
from . import calendar_adapters as calendar_adapters_module

logger = logging.getLogger("actelya.appointments")

_worker_task = None
RUN_DELAY_SECONDS = 1


async def _get_connection_and_adapter(db, connection_id: str, org_id: str):
    """Ogni accesso a una connessione calendario filtra ANCHE per
    organization_id: una prenotazione di un'altra organizzazione non deve mai
    poter risolvere una connessione altrui. Se il filtro non trova nulla (id
    inesistente o appartenente a un'altra org), build_adapter(None) degrada in
    modo sicuro a _NonConfiguratoAdapter — mai un crash, mai una conferma."""
    conn = await db.appointment_connections.find_one({"id": connection_id, "organization_id": org_id})
    return conn, calendar_adapters_module.build_adapter(conn)


async def create_booking(db, *, org_id: str, proposal: dict, slot_index: int, actor: str) -> dict:
    """Crea (o ritorna, se già esistente per idempotenza) una prenotazione
    PIANIFICATA per lo slot scelto di una proposta APPROVATA. Idempotenza:
    stessa proposta+slot -> stessa prenotazione, mai una seconda."""
    if proposal["status"] != "APPROVATA":
        raise ValueError("La proposta deve essere approvata prima di prenotare.")
    slots = proposal.get("proposed_slots") or []
    if slot_index < 0 or slot_index >= len(slots):
        raise ValueError("Slot proposto inesistente.")
    slot = slots[slot_index]
    idempotency_key = f"{proposal['id']}:{slot_index}"

    esistente = await db.appointment_bookings.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
    if esistente:
        return esistente

    # Prevenzione doppie prenotazioni: nessun'altra prenotazione ATTIVA sulla
    # stessa connessione con un intervallo sovrapposto.
    attive = await db.appointment_bookings.find({
        "organization_id": org_id, "connection_id": proposal["connection_id"],
        "status": {"$in": ["PIANIFICATA", "IN_CODA", "IN_ESECUZIONE", "CONFERMATA"]},
    }, {"_id": 0, "start": 1, "end": 1}).to_list(500)
    for a in attive:
        if slot["start"] < a["end"] and slot["end"] > a["start"]:
            raise ValueError("Slot non più disponibile: sovrapposizione con un'altra prenotazione attiva.")

    booking = {
        "id": new_id("appt"), "organization_id": org_id, "proposal_id": proposal["id"],
        "lead_id": proposal["lead_id"], "lead_type": proposal["lead_type"],
        "connection_id": proposal["connection_id"], "campaign_id": proposal.get("campaign_id"),
        "start": slot["start"], "end": slot["end"], "duration_minutes": proposal["duration_minutes"],
        "status": "IN_CODA", "idempotency_key": idempotency_key,
        "provider_event_id": None, "attempt": 0, "last_error": None,
        "rescheduled_from": None, "history": [{"at": now_iso(), "status": "IN_CODA", "actor": actor}],
        "created_by": actor, "created_at": now_iso(), "updated_at": now_iso(),
    }
    try:
        await db.appointment_bookings.insert_one(booking)
    except Exception:
        esistente = await db.appointment_bookings.find_one({"idempotency_key": idempotency_key}, {"_id": 0})
        if esistente:
            return esistente
        raise
    return booking


async def run_booking_job(db, booking: dict) -> None:
    """Elabora UNA prenotazione in coda: claim atomico, chiama l'adapter,
    aggiorna lo stato. Idempotente: una prenotazione non più IN_CODA non
    viene rielaborata da qui."""
    claimed = await db.appointment_bookings.find_one_and_update(
        {"id": booking["id"], "status": "IN_CODA"},
        {"$set": {"status": "IN_ESECUZIONE", "updated_at": now_iso()},
         "$inc": {"attempt": 1}},
    )
    if not claimed:
        return
    await asyncio.sleep(RUN_DELAY_SECONDS)

    conn, adapter = await _get_connection_and_adapter(db, booking["connection_id"], booking["organization_id"])
    proposal = await db.appointment_proposals.find_one({"id": booking["proposal_id"]})

    esito = adapter.create_event(
        start_iso=booking["start"], end_iso=booking["end"],
        title=f"Appuntamento — {proposal.get('lead_id', '') if proposal else ''}",
        description="Prenotato da ACTELYA — Appointment Setter (approvato prima dell'invio).",
    )
    nuovo_stato = {"OK": "CONFERMATA", "ESITO_INCERTO": "ESITO_INCERTO",
                  "NON_DISPONIBILE": "FALLITA", "ERRORE": "FALLITA"}.get(esito.status, "FALLITA")

    await db.appointment_bookings.update_one(
        {"id": booking["id"]},
        {"$set": {"status": nuovo_stato, "provider_event_id": esito.provider_event_id,
                  "last_error": esito.motivo, "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "status": nuovo_stato, "motivo": esito.motivo}}},
    )
    if nuovo_stato == "CONFERMATA" and proposal:
        await db.appointment_proposals.update_one({"id": proposal["id"]}, {"$set": {"status": "INVIATA", "updated_at": now_iso()}})


async def cancel_booking(db, booking: dict, *, actor: str, reason: str) -> dict:
    """Cancella una prenotazione. Se non e' mai stata confermata sul
    provider (nessun provider_event_id), non c'e' nulla da confermare: la
    cancellazione locale e' sempre certa. Se ERA confermata, la
    cancellazione presso il provider deve essere DAVVERO confermata perche'
    lo stato diventi CANCELLATA — altrimenti resta CANCELLAZIONE_INCERTA
    (mai una cancellazione dichiarata quando il provider non l'ha
    confermata), da risolvere con reconcile_cancellation() o
    resolve_cancellation_manually()."""
    aveva_evento_confermato = booking["status"] == "CONFERMATA" and bool(booking.get("provider_event_id"))
    if aveva_evento_confermato:
        conn, adapter = await _get_connection_and_adapter(db, booking["connection_id"], booking["organization_id"])
        provider_confermato = adapter.cancel_event(booking["provider_event_id"])
    else:
        provider_confermato = True
    nuovo_stato = "CANCELLATA" if provider_confermato else "CANCELLAZIONE_INCERTA"
    await db.appointment_bookings.update_one(
        {"id": booking["id"]},
        {"$set": {"status": nuovo_stato, "cancel_reason": reason, "cancel_provider_confirmed": provider_confermato,
                  "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "status": nuovo_stato, "actor": actor, "motivo": reason}}},
    )
    return await db.appointment_bookings.find_one({"id": booking["id"]}, {"_id": 0})


async def reconcile_cancellation(db, booking: dict, *, actor: str) -> dict:
    """Ritenta la cancellazione presso il provider per una prenotazione in
    CANCELLAZIONE_INCERTA. Nessun limite di tentativi imposto qui: se il
    provider continua a non confermare, la prenotazione resta
    CANCELLAZIONE_INCERTA finche' un umano non la risolve esplicitamente
    (resolve_cancellation_manually) o il provider non conferma davvero."""
    if booking["status"] != "CANCELLAZIONE_INCERTA":
        return booking
    provider_confermato = True
    if booking.get("provider_event_id"):
        conn, adapter = await _get_connection_and_adapter(db, booking["connection_id"], booking["organization_id"])
        provider_confermato = adapter.cancel_event(booking["provider_event_id"])
    nuovo_stato = "CANCELLATA" if provider_confermato else "CANCELLAZIONE_INCERTA"
    await db.appointment_bookings.update_one(
        {"id": booking["id"]},
        {"$set": {"status": nuovo_stato, "cancel_provider_confirmed": provider_confermato, "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "status": nuovo_stato, "actor": actor,
                               "motivo": "Riconciliazione cancellazione"}}},
    )
    return await db.appointment_bookings.find_one({"id": booking["id"]}, {"_id": 0})


async def resolve_cancellation_manually(db, booking: dict, *, actor: str, note: str) -> dict:
    """Un umano dichiara risolta una cancellazione incerta dopo verifica
    esterna (es. controllato manualmente il calendario del provider) — mai
    automatico, sempre con una nota esplicita registrata nella cronologia."""
    if booking["status"] != "CANCELLAZIONE_INCERTA":
        raise ValueError("Risoluzione manuale applicabile solo a una prenotazione in CANCELLAZIONE_INCERTA.")
    if not note or not note.strip():
        raise ValueError("Nota di risoluzione obbligatoria.")
    await db.appointment_bookings.update_one(
        {"id": booking["id"]},
        {"$set": {"status": "CANCELLATA", "cancel_provider_confirmed": True, "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "status": "CANCELLATA", "actor": actor,
                               "motivo": f"Risolto manualmente: {note.strip()}"}}},
    )
    # La risoluzione manuale e' sempre un'azione umana attivata dal router
    # (mai dalla saga stessa): sicuro riprendere qui una eventuale saga di
    # riprogrammazione lasciata in COMPENSAZIONE_RICHIESTA in attesa di questo esito.
    await continua_saga_in_sospeso_per_booking(db, booking["id"])
    return await db.appointment_bookings.find_one({"id": booking["id"]}, {"_id": 0})


async def _slot_in_conflitto(db, *, org_id: str, connection_id: str, exclude_booking_id: str,
                             start_iso: str, end_iso: str) -> bool:
    attive = await db.appointment_bookings.find({
        "organization_id": org_id, "connection_id": connection_id,
        "id": {"$ne": exclude_booking_id},
        "status": {"$in": ["PIANIFICATA", "IN_CODA", "IN_ESECUZIONE", "CONFERMATA"]},
    }, {"_id": 0, "start": 1, "end": 1}).to_list(500)
    return any(start_iso < a["end"] and end_iso > a["start"] for a in attive)


async def _saga_avanza(db, saga_id: str, nuovo_stato: str, *, motivo: str = "", **campi_extra) -> dict:
    campi = {"status": nuovo_stato, "updated_at": now_iso(), **campi_extra}
    if nuovo_stato == "FALLITA":
        campi["last_error"] = motivo
    await db.appointment_reschedule_sagas.update_one(
        {"id": saga_id},
        {"$set": campi, "$push": {"history": {"at": now_iso(), "status": nuovo_stato, "motivo": motivo}}},
    )
    return await db.appointment_reschedule_sagas.find_one({"id": saga_id}, {"_id": 0})


async def _esegui_cancellazione_originale(db, saga: dict) -> dict:
    """Esegue davvero la richiesta di cancellazione dell'originale (o la
    ritenta se gia' incerta) e fa avanzare la saga di conseguenza. Va
    invocata SOLO da chi ha vinto l'accesso esclusivo al passo (vedi
    _richiedi_cancellazione_originale) oppure da un ritentativo esplicito
    (riconciliazione manuale, recovery di una saga orfana): mai da due
    esecuzioni concorrenti sulla stessa saga, per non richiedere la
    cancellazione due volte allo stesso provider."""
    originale = await db.appointment_bookings.find_one({"id": saga["booking_id"]}, {"_id": 0})
    if originale["status"] not in ("CANCELLATA", "SOSTITUITA"):
        if originale["status"] == "CANCELLAZIONE_INCERTA":
            originale = await reconcile_cancellation(db, originale, actor=saga["actor"])
        else:
            originale = await cancel_booking(db, originale, actor=saga["actor"], reason=saga["reason"])
    if originale["status"] in ("CANCELLATA", "SOSTITUITA"):
        return await _saga_avanza(db, saga["id"], "CANCELLAZIONE_CONFERMATA")
    return await _saga_avanza(
        db, saga["id"], "COMPENSAZIONE_RICHIESTA",
        motivo="Cancellazione dell'originale non confermata dal provider (stato CANCELLAZIONE_INCERTA).",
    )


async def _richiedi_cancellazione_originale(db, saga: dict) -> dict:
    """Reclama atomicamente (find_one_and_update) il passo NUOVO_SLOT_VERIFICATO
    -> CANCELLAZIONE_ORIGINALE_RICHIESTA: tra esecuzioni concorrenti sulla
    STESSA saga (stesso booking_id + stesso nuovo slot), solo chi vince il
    claim invoca davvero l'adapter — stesso pattern di claim atomico gia'
    usato da run_booking_job() per IN_CODA -> IN_ESECUZIONE."""
    vinta = await db.appointment_reschedule_sagas.find_one_and_update(
        {"id": saga["id"], "status": "NUOVO_SLOT_VERIFICATO"},
        {"$set": {"status": "CANCELLAZIONE_ORIGINALE_RICHIESTA", "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "status": "CANCELLAZIONE_ORIGINALE_RICHIESTA", "motivo": ""}}},
    )
    if vinta is None:
        return await db.appointment_reschedule_sagas.find_one({"id": saga["id"]}, {"_id": 0})
    aggiornata = await db.appointment_reschedule_sagas.find_one({"id": saga["id"]}, {"_id": 0})
    return await _esegui_cancellazione_originale(db, aggiornata)


async def _advance_reschedule_saga(db, saga: dict) -> dict:
    """Fa avanzare la saga di riprogrammazione di un passo alla volta, ognuno
    persistito su MongoDB prima di procedere al successivo — puo' essere
    richiamata piu' volte sulla stessa saga (idempotente) sia per riprendere
    dopo un riavvio (recover_on_startup) sia per una richiesta ripetuta
    dall'utente (reschedule_booking)."""
    for _ in range(200):  # limite difensivo: mai un ciclo infinito
        stato = saga["status"]
        if stato in ("COMPLETATA", "FALLITA"):
            return saga

        if stato == "RICHIESTA_CREATA":
            occupato = await _slot_in_conflitto(
                db, org_id=saga["organization_id"], connection_id=saga["connection_id"],
                exclude_booking_id=saga["booking_id"], start_iso=saga["new_start"], end_iso=saga["new_end"],
            )
            if occupato:
                saga = await _saga_avanza(
                    db, saga["id"], "FALLITA",
                    motivo="Nuovo slot non disponibile: sovrapposizione con un'altra prenotazione attiva.",
                )
                continue
            saga = await _saga_avanza(db, saga["id"], "NUOVO_SLOT_VERIFICATO")
            continue

        if stato == "NUOVO_SLOT_VERIFICATO":
            saga = await _richiedi_cancellazione_originale(db, saga)
            continue

        if stato == "CANCELLAZIONE_ORIGINALE_RICHIESTA":
            # Un'altra esecuzione concorrente ha gia' vinto il claim su questo
            # passo: attende brevemente il suo esito invece di ritentare la
            # cancellazione una seconda volta. Se dopo l'attesa lo stato non
            # e' progredito, si presume una saga orfana dopo un riavvio (mai
            # chi la stava eseguendo l'ha davvero completata) e la ritenta.
            progredita = False
            for _ in range(3):
                await asyncio.sleep(0.05)
                saga = await db.appointment_reschedule_sagas.find_one({"id": saga["id"]}, {"_id": 0})
                if saga["status"] != "CANCELLAZIONE_ORIGINALE_RICHIESTA":
                    progredita = True
                    break
            if not progredita:
                saga = await _esegui_cancellazione_originale(db, saga)
            continue

        if stato == "COMPENSAZIONE_RICHIESTA":
            saga = await _esegui_cancellazione_originale(db, saga)
            if saga["status"] == "COMPENSAZIONE_RICHIESTA":
                return saga
            continue

        if stato == "CANCELLAZIONE_CONFERMATA":
            await db.appointment_bookings.update_one(
                {"id": saga["booking_id"]}, {"$set": {"status": "SOSTITUITA", "updated_at": now_iso()}})
            originale = await db.appointment_bookings.find_one({"id": saga["booking_id"]}, {"_id": 0})
            nuova = {
                **{k: v for k, v in originale.items() if k not in (
                    "_id", "id", "status", "provider_event_id", "attempt", "last_error", "history",
                    "idempotency_key", "cancel_reason", "cancel_provider_confirmed")},
                "id": new_id("appt"), "start": saga["new_start"], "end": saga["new_end"],
                "status": "IN_CODA", "provider_event_id": None, "attempt": 0, "last_error": None,
                "idempotency_key": saga["id"], "rescheduled_from": saga["booking_id"],
                "history": [{"at": now_iso(), "status": "IN_CODA", "actor": saga["actor"], "motivo": "Riprogrammata"}],
                "created_at": now_iso(), "updated_at": now_iso(),
            }
            try:
                await db.appointment_bookings.insert_one(nuova)
            except Exception:
                # Idempotenza: se una precedente esecuzione (poi interrotta
                # prima di scrivere SOSTITUTO_CREATO) l'aveva gia' creata, la
                # si riusa — mai un secondo appuntamento per la stessa saga.
                esistente = await db.appointment_bookings.find_one({"idempotency_key": saga["id"]}, {"_id": 0})
                if not esistente:
                    raise
                nuova = esistente
            saga = await _saga_avanza(db, saga["id"], "SOSTITUTO_CREATO", new_booking_id=nuova["id"])
            continue

        if stato == "SOSTITUTO_CREATO":
            saga = await _saga_avanza(db, saga["id"], "COMPLETATA")
            return saga

        return saga  # stato sconosciuto: non avanzare, evita comportamenti non previsti

    logger.error("Saga di riprogrammazione %s bloccata dopo troppi passi: %s", saga.get("id"), saga.get("status"))
    return saga


async def continua_saga_in_sospeso_per_booking(db, booking_id: str) -> None:
    """Riprende una saga di riprogrammazione lasciata in COMPENSAZIONE_RICHIESTA
    quando la sua prenotazione originale e' stata appena confermata CANCELLATA
    da un'azione umana esplicita (riconciliazione o risoluzione manuale) —
    mai chiamata dall'interno della saga stessa (rischio di rientranza)."""
    saga = await db.appointment_reschedule_sagas.find_one(
        {"booking_id": booking_id, "status": "COMPENSAZIONE_RICHIESTA"}, {"_id": 0})
    if saga:
        await _advance_reschedule_saga(db, saga)


async def reschedule_booking(db, booking: dict, *, new_start_iso: str, actor: str, reason: str) -> dict:
    """Riprogramma una prenotazione tramite una saga persistente e
    recuperabile (collection appointment_reschedule_sagas — vedi
    RESCHEDULE_SAGA_STATUS in models.py per le fasi): verifica PRIMA che il
    nuovo slot sia davvero libero (mai toccare l'originale se non lo e');
    cancella l'originale SOLO dopo; se quella cancellazione non e' confermata
    dal provider (CANCELLAZIONE_INCERTA) la saga si ferma in
    COMPENSAZIONE_RICHIESTA — NON crea la nuova prenotazione (eviterebbe un
    doppio impegno se l'originale risultasse ancora attivo sul calendario del
    provider) finche' una riconciliazione o risoluzione manuale non la
    sblocca. Idempotente con una chiave DETERMINISTICA (prenotazione
    originale + nuovo slot, mai un identificativo casuale) che e' anche l'id
    della saga: una ripetizione della stessa richiesta — o una ripresa dopo
    un riavvio del processo — ritorna sempre la stessa nuova prenotazione,
    mai una seconda, e non richiede la cancellazione dell'originale due
    volte."""
    from datetime import datetime, timedelta

    durata = timedelta(minutes=booking["duration_minutes"])
    nuovo_inizio = datetime.fromisoformat(new_start_iso.replace("Z", "+00:00"))
    nuova_fine = nuovo_inizio + durata
    nuovo_inizio_iso, nuova_fine_iso = nuovo_inizio.isoformat(), nuova_fine.isoformat()
    saga_id = f"resched:{booking['id']}:{nuovo_inizio_iso}:{nuova_fine_iso}"

    saga = await db.appointment_reschedule_sagas.find_one({"id": saga_id}, {"_id": 0})
    if saga is None:
        nuova_saga = {
            "id": saga_id, "organization_id": booking["organization_id"], "booking_id": booking["id"],
            "connection_id": booking["connection_id"], "new_start": nuovo_inizio_iso, "new_end": nuova_fine_iso,
            "reason": reason or "Riprogrammazione", "actor": actor, "status": "RICHIESTA_CREATA",
            "new_booking_id": None, "last_error": None,
            "history": [{"at": now_iso(), "status": "RICHIESTA_CREATA", "actor": actor, "motivo": ""}],
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        try:
            await db.appointment_reschedule_sagas.insert_one(nuova_saga)
            saga = nuova_saga
        except Exception:
            saga = await db.appointment_reschedule_sagas.find_one({"id": saga_id}, {"_id": 0})

    saga = await _advance_reschedule_saga(db, saga)

    if saga["status"] == "FALLITA":
        raise ValueError(saga.get("last_error") or "Nuovo slot non disponibile.")
    if saga["status"] == "COMPENSAZIONE_RICHIESTA":
        raise ValueError(
            "Impossibile riprogrammare: la cancellazione dell'appuntamento originale non è stata confermata "
            "dal provider (stato CANCELLAZIONE_INCERTA). E' stata aperta una procedura di riconciliazione: "
            "usa /bookings/{id}/reconcile-cancellation o /resolve-cancellation, poi ripeti la riprogrammazione "
            "(stessa chiave, nessuna duplicazione)."
        )
    return await db.appointment_bookings.find_one({"id": saga["new_booking_id"]}, {"_id": 0})


async def worker_loop(db) -> None:
    logger.info("Appointment Setter worker avviato")
    while True:
        try:
            pending = await db.appointment_bookings.find({"status": "IN_CODA"}, {"_id": 0}).sort("created_at", 1).to_list(20)
            for booking in pending:
                await run_booking_job(db, booking)
        except Exception:
            logger.exception("Errore nel worker Appointment Setter")
        await asyncio.sleep(1)


async def recover_on_startup(db) -> None:
    res = await db.appointment_bookings.update_many(
        {"status": "IN_ESECUZIONE"}, {"$set": {"status": "IN_CODA", "updated_at": now_iso()}},
    )
    if res.modified_count:
        logger.info("Appointment Setter recovery: %s prenotazioni riportate in coda", res.modified_count)

    # Riprende ogni saga di riprogrammazione non terminale lasciata a meta' da
    # un riavvio. COMPENSAZIONE_RICHIESTA e' volutamente ESCLUSA: richiede un
    # intervento esplicito (riconciliazione o risoluzione manuale), mai un
    # ritentativo automatico e silenzioso ad ogni avvio del processo.
    sospese = await db.appointment_reschedule_sagas.find(
        {"status": {"$nin": ["COMPLETATA", "FALLITA", "COMPENSAZIONE_RICHIESTA"]}}, {"_id": 0},
    ).to_list(200)
    for saga in sospese:
        try:
            await _advance_reschedule_saga(db, saga)
        except Exception:
            logger.exception("Errore riprendendo la saga di riprogrammazione %s", saga.get("id"))
    if sospese:
        logger.info("Appointment Setter recovery: %s saghe di riprogrammazione riprese", len(sospese))


def start_worker(db) -> None:
    global _worker_task
    if _worker_task is None:
        _worker_task = asyncio.create_task(worker_loop(db))
