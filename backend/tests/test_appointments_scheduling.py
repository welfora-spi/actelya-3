"""Appointment Setter — calcolo deterministico degli slot liberi. Nessuna
rete, nessun Mongo."""
from datetime import datetime, timezone

from app.domains.appointments.calendar_adapters import BusySlot
from app.domains.appointments.scheduling import compute_free_slots

LUN_MAR_9_17 = [
    {"weekday": 0, "start_time": "09:00", "end_time": "17:00"},
    {"weekday": 1, "start_time": "09:00", "end_time": "17:00"},
]


def _lunedi_9(ora=9):
    # 2026-09-07 e' un lunedi'.
    return datetime(2026, 9, 7, ora, 0, tzinfo=timezone.utc)


def test_nessuna_disponibilita_produce_lista_vuota():
    slots = compute_free_slots(availability_windows=[], busy_slots=[], start=_lunedi_9(),
                               days=7, duration_minutes=30, timezone_name="UTC")
    assert slots == []


def test_slot_liberi_rispettano_la_finestra_di_disponibilita():
    slots = compute_free_slots(availability_windows=LUN_MAR_9_17, busy_slots=[], start=_lunedi_9(8),
                               days=1, duration_minutes=60, timezone_name="UTC", max_slots=20)
    assert len(slots) == 8  # 09-17 con slot da 60' = 8 slot
    assert slots[0]["start"].startswith("2026-09-07T09:00")
    assert slots[-1]["end"].startswith("2026-09-07T17:00")


def test_slot_occupati_vengono_esclusi():
    occupato = [BusySlot(start="2026-09-07T10:00:00+00:00", end="2026-09-07T11:00:00+00:00")]
    slots = compute_free_slots(availability_windows=LUN_MAR_9_17, busy_slots=occupato, start=_lunedi_9(8),
                               days=1, duration_minutes=60, timezone_name="UTC", max_slots=20)
    orari = [s["start"] for s in slots]
    assert not any("T10:00" in o for o in orari)
    assert len(slots) == 7  # 8 slot totali meno quello occupato


def test_rispetta_max_slots():
    slots = compute_free_slots(availability_windows=LUN_MAR_9_17, busy_slots=[], start=_lunedi_9(8),
                               days=7, duration_minutes=30, timezone_name="UTC", max_slots=3)
    assert len(slots) == 3


def test_nessuno_slot_nel_passato():
    # Richiesta a meta' mattina: gli slot prima dell'ora corrente non devono comparire.
    slots = compute_free_slots(availability_windows=LUN_MAR_9_17, busy_slots=[], start=_lunedi_9(12),
                               days=1, duration_minutes=60, timezone_name="UTC", max_slots=20)
    assert not any("T09:00" in s["start"] or "T10:00" in s["start"] or "T11:00" in s["start"] for s in slots)
    assert all(s["start"] >= "2026-09-07T12:00" for s in slots)


def test_weekday_senza_finestra_non_produce_slot():
    # Solo lun/mar hanno disponibilita': partendo da mercoledi' (2026-09-09) per 1 giorno -> nessuno slot.
    mercoledi = datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc)
    slots = compute_free_slots(availability_windows=LUN_MAR_9_17, busy_slots=[], start=mercoledi,
                               days=1, duration_minutes=30, timezone_name="UTC")
    assert slots == []


def test_timezone_non_valido_ripiega_su_utc_senza_eccezione():
    slots = compute_free_slots(availability_windows=LUN_MAR_9_17, busy_slots=[], start=_lunedi_9(8),
                               days=1, duration_minutes=60, timezone_name="Fuso/Inesistente", max_slots=20)
    assert len(slots) == 8
