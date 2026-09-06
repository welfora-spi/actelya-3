"""Appointment Setter — test di integrazione della pipeline reale (MongoDB
locale): idempotenza, prevenzione doppie prenotazioni, cancellazione,
riprogrammazione, recovery. Un fake adapter deterministico sostituisce
qualunque chiamata di rete (mai un provider reale invocato)."""
import asyncio
import uuid
from dataclasses import dataclass, field

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.domains.appointments import calendar_adapters as CA
from app.domains.appointments.pipeline import (
    cancel_booking,
    create_booking,
    reconcile_cancellation,
    recover_on_startup,
    reschedule_booking,
    resolve_cancellation_manually,
    run_booking_job,
)
from app.models import new_id, now_iso


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, org):
    for c in ("appointment_connections", "appointment_proposals", "appointment_bookings",
              "appointment_reschedule_sagas"):
        await db[c].delete_many({"organization_id": org})


@dataclass
class FakeAdapter(CA.CalendarAdapter):
    """Fake adapter deterministico: mai una chiamata di rete. `risposta`
    controlla l'esito di create_event ("OK"|"ERRORE"|"ESITO_INCERTO")."""
    provider_type: str = "fake"
    risposta: str = "OK"
    # Controlla l'esito di cancel_event(): un elenco consumato in ordine (un
    # valore per chiamata) cosi' un test puo' simulare "primo tentativo
    # fallito, secondo riuscito" per la riconciliazione. Se vuoto, usa
    # sempre `cancel_risposta_default`.
    cancel_risposte: list = field(default_factory=list)
    cancel_risposta_default: bool = True
    eventi_creati: list = field(default_factory=list)
    eventi_cancellati: list = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return True

    def verify(self):
        return True, None

    def list_busy(self, start_iso, end_iso):
        return []

    def create_event(self, *, start_iso, end_iso, title, description):
        if self.risposta == "OK":
            event_id = f"fake-event-{uuid.uuid4().hex[:8]}"
            self.eventi_creati.append(event_id)
            return CA.CalendarEvent(event_id, CA.STATO_OK)
        if self.risposta == "ESITO_INCERTO":
            return CA.CalendarEvent(None, "ESITO_INCERTO", "timeout simulato")
        return CA.CalendarEvent(None, CA.STATO_ERRORE, "errore simulato")

    def cancel_event(self, provider_event_id):
        self.eventi_cancellati.append(provider_event_id)
        if self.cancel_risposte:
            return self.cancel_risposte.pop(0)
        return self.cancel_risposta_default


def _proposal(org, *, connection_id="conn-1", slots=None):
    slots = slots if slots is not None else [
        {"start": "2026-09-07T09:00:00+00:00", "end": "2026-09-07T09:30:00+00:00"},
        {"start": "2026-09-07T10:00:00+00:00", "end": "2026-09-07T10:30:00+00:00"},
    ]
    return {
        "id": new_id("apptprop"), "organization_id": org, "connection_id": connection_id,
        "lead_id": "lead-1", "lead_type": "aziende", "campaign_id": None, "duration_minutes": 30,
        "proposed_slots": slots, "status": "APPROVATA", "created_at": now_iso(),
    }


def test_create_booking_e_idempotente_stessa_proposta_stesso_slot(monkeypatch):
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b1 = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            b2 = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            assert b1["id"] == b2["id"]
            totale = await db.appointment_bookings.count_documents({"organization_id": org})
            assert totale == 1
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_create_booking_previene_doppia_prenotazione_stesso_slot(monkeypatch):
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p1 = _proposal(org)
            p2 = _proposal(org)  # proposta DIVERSA, ma stesso connection_id e stesso slot
            await db.appointment_proposals.insert_many([p1, p2])
            await create_booking(db, org_id=org, proposal=p1, slot_index=0, actor="user-test")
            with pytest.raises(ValueError, match="sovrapposizione"):
                await create_booking(db, org_id=org, proposal=p2, slot_index=0, actor="user-test")
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_run_booking_job_conferma_con_adapter_ok(monkeypatch):
    fake = FakeAdapter(risposta="OK")
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            aggiornata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})
            assert aggiornata["status"] == "CONFERMATA"
            assert aggiornata["provider_event_id"] in fake.eventi_creati
            proposta_agg = await db.appointment_proposals.find_one({"id": p["id"]}, {"_id": 0})
            assert proposta_agg["status"] == "INVIATA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_run_booking_job_esito_incerto_mai_dichiarato_confermato(monkeypatch):
    fake = FakeAdapter(risposta="ESITO_INCERTO")
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            aggiornata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})
            assert aggiornata["status"] == "ESITO_INCERTO"
            assert aggiornata["provider_event_id"] is None
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_run_booking_job_idempotente_non_rielabora_se_gia_avviato(monkeypatch):
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            await run_booking_job(db, b)  # richiamato con lo stesso job, ormai non piu' IN_CODA
            assert len(fake.eventi_creati) == 1  # un solo evento realmente creato
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_cancel_booking_confermata_chiama_cancel_event_e_marca_cancellata(monkeypatch):
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})
            cancellata = await cancel_booking(db, confermata, actor="user-test", reason="Cliente non disponibile")
            assert cancellata["status"] == "CANCELLATA"
            assert cancellata["cancel_provider_confirmed"] is True
            assert confermata["provider_event_id"] in fake.eventi_cancellati
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ==================== Correzioni: cancellazione non confermata, riconciliazione, riprogrammazione sicura/idempotente ====================
def test_cancel_booking_non_confermata_dal_provider_resta_incerta_non_cancellata(monkeypatch):
    """Correzione 3: se il provider NON conferma la cancellazione di una
    prenotazione CONFERMATA, lo stato deve restare CANCELLAZIONE_INCERTA —
    mai CANCELLATA, mai una cancellazione dichiarata senza conferma reale."""
    fake = FakeAdapter(cancel_risposta_default=False)
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})
            esito = await cancel_booking(db, confermata, actor="user-test", reason="Cliente non disponibile")
            assert esito["status"] == "CANCELLAZIONE_INCERTA"
            assert esito["cancel_provider_confirmed"] is False
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_cancel_booking_senza_provider_event_id_e_sempre_certa():
    # Una prenotazione mai confermata sul provider (nessun provider_event_id)
    # non ha nulla da confermare: la cancellazione locale resta sempre certa.
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            booking = {
                "id": new_id("appt"), "organization_id": org, "connection_id": "conn-1",
                "status": "PIANIFICATA", "provider_event_id": None, "idempotency_key": new_id("idem"),
                "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.appointment_bookings.insert_one(booking)
            esito = await cancel_booking(db, booking, actor="user-test", reason="Mai inviata")
            assert esito["status"] == "CANCELLATA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_reconcile_cancellation_ritenta_e_puo_confermare(monkeypatch):
    """Correzione 3: reconcile_cancellation() ritenta cancel_event() — se il
    provider conferma ora, passa a CANCELLATA."""
    fake = FakeAdapter(cancel_risposte=[False, True])  # primo tentativo fallito, secondo riuscito
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})
            incerta = await cancel_booking(db, confermata, actor="user-test", reason="Test")
            assert incerta["status"] == "CANCELLAZIONE_INCERTA"

            riconciliata = await reconcile_cancellation(db, incerta, actor="user-test")
            assert riconciliata["status"] == "CANCELLATA"
            assert riconciliata["cancel_provider_confirmed"] is True
            assert len(fake.eventi_cancellati) == 2  # due tentativi realmente effettuati
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_reconcile_cancellation_su_stato_diverso_e_no_op():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            booking = {"id": new_id("appt"), "organization_id": org, "status": "CANCELLATA"}
            risultato = await reconcile_cancellation(db, booking, actor="user-test")
            assert risultato is booking  # nessuna modifica, nessuna chiamata
            return True
        finally:
            client.close()

    assert run(scenario())


def test_resolve_cancellation_manually_richiede_stato_incerto_e_nota(monkeypatch):
    """Correzione 3: la risoluzione manuale è applicabile SOLO a una
    prenotazione in CANCELLAZIONE_INCERTA e richiede sempre una nota."""
    fake = FakeAdapter(cancel_risposta_default=False)
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})
            incerta = await cancel_booking(db, confermata, actor="user-test", reason="Test")
            assert incerta["status"] == "CANCELLAZIONE_INCERTA"

            with pytest.raises(ValueError, match="Nota"):
                await resolve_cancellation_manually(db, incerta, actor="admin-test", note="   ")

            risolta = await resolve_cancellation_manually(
                db, incerta, actor="admin-test", note="Verificato manualmente su Google Calendar: evento assente.")
            assert risolta["status"] == "CANCELLATA"
            assert any("Risolto manualmente" in (h.get("motivo") or "") for h in risolta["history"])

            # Non riapplicabile a una prenotazione già risolta.
            with pytest.raises(ValueError, match="CANCELLAZIONE_INCERTA"):
                await resolve_cancellation_manually(db, risolta, actor="admin-test", note="di nuovo")
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_reschedule_booking_slot_non_disponibile_non_tocca_originale(monkeypatch):
    """Correzione 2: se il nuovo slot non è disponibile, l'appuntamento
    originale NON deve essere cancellato (resta CONFERMATA)."""
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})

            # Un'altra prenotazione attiva occupa esattamente il nuovo slot richiesto.
            occupante = {
                "id": new_id("appt"), "organization_id": org, "connection_id": confermata["connection_id"],
                "status": "CONFERMATA", "start": "2026-09-08T09:00:00+00:00", "end": "2026-09-08T09:30:00+00:00",
                "idempotency_key": new_id("idem"), "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.appointment_bookings.insert_one(occupante)

            with pytest.raises(ValueError, match="Nuovo slot non disponibile"):
                await reschedule_booking(db, confermata, new_start_iso="2026-09-08T09:00:00+00:00",
                                         actor="user-test", reason="Richiesta cliente")

            # L'originale non è stato toccato: nessuna cancellazione tentata sul provider.
            invariata = await db.appointment_bookings.find_one({"id": confermata["id"]}, {"_id": 0})
            assert invariata["status"] == "CONFERMATA"
            assert fake.eventi_cancellati == []
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_reschedule_booking_cancellazione_incerta_non_crea_nuova_prenotazione(monkeypatch):
    """Correzione 2+3 insieme: se la cancellazione dell'originale non è
    confermata dal provider, la riprogrammazione deve fermarsi (mai una
    nuova prenotazione mentre l'originale potrebbe essere ancora attivo sul
    calendario del provider — eviterebbe un doppio impegno)."""
    fake = FakeAdapter(cancel_risposta_default=False)
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})

            with pytest.raises(ValueError, match="CANCELLAZIONE_INCERTA"):
                await reschedule_booking(db, confermata, new_start_iso="2026-09-09T09:00:00+00:00",
                                         actor="user-test", reason="Richiesta cliente")

            aggiornata = await db.appointment_bookings.find_one({"id": confermata["id"]}, {"_id": 0})
            assert aggiornata["status"] == "CANCELLAZIONE_INCERTA"  # mai SOSTITUITA
            nuove = await db.appointment_bookings.count_documents({
                "organization_id": org, "rescheduled_from": confermata["id"],
            })
            assert nuove == 0  # nessuna nuova prenotazione creata
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_reschedule_booking_idempotente_stessa_richiesta_stesso_slot(monkeypatch):
    """Correzione 4: chiave di idempotenza deterministica (prenotazione
    originale + nuovo slot), mai un identificativo casuale — una ripetizione
    della stessa richiesta di riprogrammazione ritorna la STESSA nuova
    prenotazione, senza ricancellare l'originale una seconda volta."""
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})

            nuova1 = await reschedule_booking(db, confermata, new_start_iso="2026-09-10T09:00:00+00:00",
                                              actor="user-test", reason="Richiesta cliente")
            nuova2 = await reschedule_booking(db, confermata, new_start_iso="2026-09-10T09:00:00+00:00",
                                              actor="user-test", reason="Richiesta cliente (ripetuta)")
            assert nuova1["id"] == nuova2["id"]
            assert nuova1["idempotency_key"] == nuova2["idempotency_key"]
            # La chiave non contiene alcun identificativo casuale: e' riproducibile a mano.
            assert nuova1["idempotency_key"] == f"resched:{confermata['id']}:2026-09-10T09:00:00+00:00:2026-09-10T09:30:00+00:00"
            totale_nuove = await db.appointment_bookings.count_documents({
                "organization_id": org, "rescheduled_from": confermata["id"],
            })
            assert totale_nuove == 1  # non duplicata dalla seconda chiamata
            assert len(fake.eventi_cancellati) == 1  # l'originale e' stato cancellato una volta sola
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_reschedule_booking_crea_nuova_prenotazione_e_marca_sostituita(monkeypatch):
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})

            nuova = await reschedule_booking(db, confermata, new_start_iso="2026-09-08T09:00:00+00:00",
                                             actor="user-test", reason="Richiesta cliente")
            assert nuova["status"] == "IN_CODA"
            assert nuova["rescheduled_from"] == confermata["id"]

            vecchia = await db.appointment_bookings.find_one({"id": confermata["id"]}, {"_id": 0})
            assert vecchia["status"] == "SOSTITUITA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_recover_on_startup_riporta_in_coda_prenotazioni_interrotte():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            booking = {
                "id": new_id("appt"), "organization_id": org, "status": "IN_ESECUZIONE",
                "idempotency_key": new_id("idem"), "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.appointment_bookings.insert_one(booking)
            await recover_on_startup(db)
            aggiornata = await db.appointment_bookings.find_one({"id": booking["id"]}, {"_id": 0})
            assert aggiornata["status"] == "IN_CODA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ==================== Fase 0: saga persistente e recuperabile di riprogrammazione ====================
def test_reschedule_saga_registra_tutte_le_fasi_fino_a_completata(monkeypatch):
    """La saga deve persistere ogni fase (richiesta creata, nuovo slot
    verificato, cancellazione originale richiesta, cancellazione confermata,
    sostituto creato, completata) — mai un salto diretto a 'completata'."""
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})

            nuova = await reschedule_booking(db, confermata, new_start_iso="2026-09-11T09:00:00+00:00",
                                             actor="user-test", reason="Richiesta cliente")

            saga = await db.appointment_reschedule_sagas.find_one({"booking_id": confermata["id"]}, {"_id": 0})
            assert saga is not None
            assert saga["status"] == "COMPLETATA"
            assert saga["new_booking_id"] == nuova["id"]
            fasi = [h["status"] for h in saga["history"]]
            for attesa in ("RICHIESTA_CREATA", "NUOVO_SLOT_VERIFICATO", "CANCELLAZIONE_ORIGINALE_RICHIESTA",
                          "CANCELLAZIONE_CONFERMATA", "SOSTITUTO_CREATO", "COMPLETATA"):
                assert attesa in fasi, f"fase mancante nella cronologia della saga: {attesa}"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_reschedule_saga_recovery_completa_dopo_riavvio_prima_del_sostituto(monkeypatch):
    """Simula un riavvio del processo esattamente dopo la conferma della
    cancellazione dell'originale ma PRIMA che il sostituto fosse creato: il
    recovery deve riprendere la saga da dove si era interrotta, senza
    perdere l'operazione (Fase 0, punto 4)."""
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            originale = {
                "id": new_id("appt"), "organization_id": org, "connection_id": "conn-1",
                "lead_id": "lead-1", "lead_type": "aziende", "campaign_id": None, "duration_minutes": 30,
                "status": "SOSTITUITA",  # come se cancel_booking() l'avesse gia' marcata cosi'
                "idempotency_key": new_id("idem"), "provider_event_id": "fake-event-x",
                "start": "2026-09-12T09:00:00+00:00", "end": "2026-09-12T09:30:00+00:00",
                "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.appointment_bookings.insert_one(originale)
            saga_id = f"resched:{originale['id']}:2026-09-13T09:00:00+00:00:2026-09-13T09:30:00+00:00"
            saga = {
                "id": saga_id, "organization_id": org, "booking_id": originale["id"],
                "connection_id": "conn-1", "new_start": "2026-09-13T09:00:00+00:00",
                "new_end": "2026-09-13T09:30:00+00:00", "reason": "Riprogrammazione", "actor": "user-test",
                "status": "CANCELLAZIONE_CONFERMATA", "new_booking_id": None, "last_error": None,
                "history": [{"at": now_iso(), "status": "CANCELLAZIONE_CONFERMATA", "motivo": ""}],
                "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.appointment_reschedule_sagas.insert_one(saga)

            await recover_on_startup(db)

            saga_dopo = await db.appointment_reschedule_sagas.find_one({"id": saga_id}, {"_id": 0})
            assert saga_dopo["status"] == "COMPLETATA"
            sostituto = await db.appointment_bookings.find_one({"id": saga_dopo["new_booking_id"]}, {"_id": 0})
            assert sostituto is not None
            assert sostituto["rescheduled_from"] == originale["id"]
            assert sostituto["idempotency_key"] == saga_id
            assert sostituto["status"] == "IN_CODA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


async def _assicura_indici_idempotenza(db):
    """Gli indici unici (stessi creati da server.py all'avvio contro
    actelya3_dev) NON esistono di default nel database di test
    actelya3_test, dato che questi test si connettono direttamente a Mongo
    bypassando il lifespan della app. Un test che verifica la protezione
    dalla duplicazione sotto concorrenza reale deve prima garantirli
    esplicitamente, altrimenti verificherebbe una garanzia che a runtime
    esiste ma che nel test non sarebbe davvero applicata."""
    await db.appointment_reschedule_sagas.create_index("id", unique=True)
    await db.appointment_bookings.create_index("idempotency_key", unique=True)


def test_reschedule_saga_recovery_non_duplica_se_il_sostituto_era_gia_stato_creato(monkeypatch):
    """Simula un riavvio ANCORA piu' tardivo: il sostituto era gia' stato
    inserito su Mongo ma il processo si e' interrotto prima di scrivere lo
    stato SOSTITUTO_CREATO sulla saga — il recovery non deve creare un
    secondo appuntamento, deve solo riconoscere quello gia' esistente."""
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _assicura_indici_idempotenza(db)
            originale_id = new_id("appt")
            saga_id = f"resched:{originale_id}:2026-09-14T09:00:00+00:00:2026-09-14T09:30:00+00:00"
            originale = {
                "id": originale_id, "organization_id": org, "connection_id": "conn-1",
                "lead_id": "lead-1", "lead_type": "aziende", "duration_minutes": 30,
                "status": "SOSTITUITA", "idempotency_key": new_id("idem"),
                "start": "2026-09-14T08:00:00+00:00", "end": "2026-09-14T08:30:00+00:00",
                "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.appointment_bookings.insert_one(originale)
            sostituto_preesistente = {
                "id": new_id("appt"), "organization_id": org, "connection_id": "conn-1",
                "rescheduled_from": originale_id, "idempotency_key": saga_id,
                "status": "IN_CODA", "start": "2026-09-14T09:00:00+00:00", "end": "2026-09-14T09:30:00+00:00",
                "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.appointment_bookings.insert_one(sostituto_preesistente)
            saga = {
                "id": saga_id, "organization_id": org, "booking_id": originale_id,
                "connection_id": "conn-1", "new_start": "2026-09-14T09:00:00+00:00",
                "new_end": "2026-09-14T09:30:00+00:00", "reason": "Riprogrammazione", "actor": "user-test",
                "status": "CANCELLAZIONE_CONFERMATA", "new_booking_id": None, "last_error": None,
                "history": [], "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.appointment_reschedule_sagas.insert_one(saga)

            await recover_on_startup(db)

            saga_dopo = await db.appointment_reschedule_sagas.find_one({"id": saga_id}, {"_id": 0})
            assert saga_dopo["status"] == "COMPLETATA"
            assert saga_dopo["new_booking_id"] == sostituto_preesistente["id"]
            totale = await db.appointment_bookings.count_documents({"idempotency_key": saga_id})
            assert totale == 1  # nessun secondo appuntamento creato dal recovery
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_reschedule_saga_compensazione_richiesta_poi_risolta_manualmente_completa_la_saga(monkeypatch):
    """Correzione 3+Fase 0: se la cancellazione dell'originale resta incerta,
    la saga si ferma in COMPENSAZIONE_RICHIESTA (intervento manuale
    richiesto). Una volta che un operatore risolve manualmente la
    cancellazione, la saga deve riprendere da sola e completarsi, creando
    finalmente il sostituto — senza che l'utente debba ripetere la
    richiesta di riprogrammazione."""
    fake = FakeAdapter(cancel_risposta_default=False)
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})

            with pytest.raises(ValueError, match="CANCELLAZIONE_INCERTA"):
                await reschedule_booking(db, confermata, new_start_iso="2026-09-15T09:00:00+00:00",
                                         actor="user-test", reason="Richiesta cliente")

            saga = await db.appointment_reschedule_sagas.find_one({"booking_id": confermata["id"]}, {"_id": 0})
            assert saga["status"] == "COMPENSAZIONE_RICHIESTA"

            incerta = await db.appointment_bookings.find_one({"id": confermata["id"]}, {"_id": 0})
            assert incerta["status"] == "CANCELLAZIONE_INCERTA"
            risolta = await resolve_cancellation_manually(
                db, incerta, actor="admin-test", note="Verificato manualmente sul calendario del provider.")
            # La risoluzione manuale riprende subito la saga in sospeso: se la
            # saga arriva a completarsi nello stesso momento, l'originale
            # risulta gia' SOSTITUITA (mai piu' CANCELLAZIONE_INCERTA/CONFERMATA).
            assert risolta["status"] in ("CANCELLATA", "SOSTITUITA")

            saga_dopo = await db.appointment_reschedule_sagas.find_one({"id": saga["id"]}, {"_id": 0})
            assert saga_dopo["status"] == "COMPLETATA"
            sostituto = await db.appointment_bookings.find_one({"id": saga_dopo["new_booking_id"]}, {"_id": 0})
            assert sostituto is not None
            assert sostituto["status"] == "IN_CODA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_cancel_booking_filtra_la_connessione_anche_per_organization_id(monkeypatch):
    """Fase 0, punto 6: una prenotazione di un'organizzazione non deve mai
    poter risolvere la connessione calendario di un'ALTRA organizzazione. Se
    (per un bug altrove) capitasse, l'accesso filtrato per organization_id
    deve degradare a NON_CONFIGURATO — mai una cancellazione confermata
    usando le credenziali di un'altra organizzazione."""
    fake = FakeAdapter()  # se venisse usato, confermerebbe sempre: il test verifica che NON venga usato
    build_adapter_originale = CA.build_adapter
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter",
                       lambda c: fake if c is not None else build_adapter_originale(None))

    async def scenario():
        client, db = _db()
        org_a = f"org-test-{uuid.uuid4().hex[:8]}"
        org_b = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            connessione_org_a = {
                "id": new_id("apptconn"), "organization_id": org_a, "provider_type": "fake",
                "status": "VERIFICATO", "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.appointment_connections.insert_one(connessione_org_a)
            prenotazione_org_b = {
                "id": new_id("appt"), "organization_id": org_b, "connection_id": connessione_org_a["id"],
                "status": "CONFERMATA", "provider_event_id": "fake-event-cross-org",
                "idempotency_key": new_id("idem"), "start": "2026-09-16T09:00:00+00:00",
                "end": "2026-09-16T09:30:00+00:00", "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.appointment_bookings.insert_one(prenotazione_org_b)

            esito = await cancel_booking(db, prenotazione_org_b, actor="user-test", reason="test")
            # La connessione di org_a non e' visibile a org_b: l'adapter degrada a
            # NON_CONFIGURATO, che NON conferma mai la cancellazione.
            assert esito["status"] == "CANCELLAZIONE_INCERTA"
            assert fake.eventi_cancellati == []  # il fake NON e' mai stato invocato
            return True
        finally:
            await db.appointment_connections.delete_many({"organization_id": org_a})
            await _cleanup(db, org_b)
            client.close()

    assert run(scenario())


def test_reschedule_booking_isolamento_tenant_ignora_prenotazioni_di_unaltra_org(monkeypatch):
    """Fase 0: la verifica di disponibilita' del nuovo slot deve restare
    isolata per organizzazione — una prenotazione identica su un'ALTRA
    organizzazione, sulla stessa connessione, non deve mai bloccare la
    riprogrammazione."""
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        altra_org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})

            occupante_altra_org = {
                "id": new_id("appt"), "organization_id": altra_org, "connection_id": confermata["connection_id"],
                "status": "CONFERMATA", "start": "2026-09-17T09:00:00+00:00", "end": "2026-09-17T09:30:00+00:00",
                "idempotency_key": new_id("idem"), "created_at": now_iso(), "updated_at": now_iso(),
            }
            await db.appointment_bookings.insert_one(occupante_altra_org)

            nuova = await reschedule_booking(db, confermata, new_start_iso="2026-09-17T09:00:00+00:00",
                                             actor="user-test", reason="Richiesta cliente")
            assert nuova["status"] == "IN_CODA"
            return True
        finally:
            await _cleanup(db, org)
            await db.appointment_bookings.delete_many({"organization_id": altra_org})
            client.close()

    assert run(scenario())


def test_reschedule_booking_concorrente_stessa_richiesta_crea_una_sola_prenotazione(monkeypatch):
    """Fase 0, punto 5/8: due esecuzioni concorrenti della STESSA richiesta di
    riprogrammazione (stessa prenotazione originale, stesso nuovo slot) non
    devono mai produrre due prenotazioni ne' richiedere due volte la
    cancellazione dell'originale al provider."""
    fake = FakeAdapter()
    monkeypatch.setattr("app.domains.appointments.calendar_adapters.build_adapter", lambda c: fake)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _assicura_indici_idempotenza(db)
            p = _proposal(org)
            await db.appointment_proposals.insert_one(p)
            b = await create_booking(db, org_id=org, proposal=p, slot_index=0, actor="user-test")
            await run_booking_job(db, b)
            confermata = await db.appointment_bookings.find_one({"id": b["id"]}, {"_id": 0})

            risultati = await asyncio.gather(
                reschedule_booking(db, confermata, new_start_iso="2026-09-18T09:00:00+00:00",
                                   actor="user-test", reason="Richiesta concorrente 1"),
                reschedule_booking(db, confermata, new_start_iso="2026-09-18T09:00:00+00:00",
                                   actor="user-test", reason="Richiesta concorrente 2"),
            )
            assert risultati[0]["id"] == risultati[1]["id"]
            totale = await db.appointment_bookings.count_documents({
                "organization_id": org, "rescheduled_from": confermata["id"],
            })
            assert totale == 1
            assert len(fake.eventi_cancellati) == 1
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())
