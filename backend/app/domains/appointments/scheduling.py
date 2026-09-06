"""Appointment Setter — calcolo deterministico degli slot liberi (nessuna
chiamata esterna qui: le finestre di occupazione vengono passate già lette
dall'adapter calendario). Timezone-aware tramite zoneinfo (libreria
standard, nessuna nuova dipendenza)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import MAX_PROPOSED_SLOTS


def _parse_busy(busy_slots) -> list[tuple[datetime, datetime]]:
    intervalli = []
    for b in busy_slots:
        try:
            inizio = datetime.fromisoformat(b.start.replace("Z", "+00:00"))
            fine = datetime.fromisoformat(b.end.replace("Z", "+00:00"))
            intervalli.append((inizio, fine))
        except (ValueError, AttributeError):
            continue
    return intervalli


def _si_sovrappone(inizio, fine, intervalli_occupati) -> bool:
    for occ_inizio, occ_fine in intervalli_occupati:
        if inizio < occ_fine and fine > occ_inizio:
            return True
    return False


def compute_free_slots(*, availability_windows: list[dict], busy_slots: list, start: datetime,
                       days: int, duration_minutes: int, timezone_name: str,
                       max_slots: int = MAX_PROPOSED_SLOTS) -> list[dict]:
    """availability_windows: [{"weekday": 0-6, "start_time": "HH:MM", "end_time": "HH:MM"}].
    Ritorna al massimo max_slots slot liberi, in ordine cronologico, come
    [{"start": iso, "end": iso}] in UTC. Nessuna finestra disponibile ->
    lista vuota (mai uno slot inventato)."""
    if not availability_windows:
        return []
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("UTC")

    intervalli_occupati = _parse_busy(busy_slots)
    durata = timedelta(minutes=duration_minutes)
    per_weekday: dict[int, list[dict]] = {}
    for w in availability_windows:
        per_weekday.setdefault(w["weekday"], []).append(w)

    risultati: list[dict] = []
    cursore = start.astimezone(tz)
    for offset in range(days):
        giorno = cursore + timedelta(days=offset)
        finestre = per_weekday.get(giorno.weekday(), [])
        for finestra in finestre:
            h1, m1 = map(int, finestra["start_time"].split(":"))
            h2, m2 = map(int, finestra["end_time"].split(":"))
            inizio_finestra = giorno.replace(hour=h1, minute=m1, second=0, microsecond=0)
            fine_finestra = giorno.replace(hour=h2, minute=m2, second=0, microsecond=0)
            slot_inizio = inizio_finestra
            while slot_inizio + durata <= fine_finestra:
                slot_fine = slot_inizio + durata
                if slot_inizio > start.astimezone(tz) and not _si_sovrappone(slot_inizio, slot_fine, intervalli_occupati):
                    risultati.append({
                        "start": slot_inizio.astimezone(ZoneInfo("UTC")).isoformat(),
                        "end": slot_fine.astimezone(ZoneInfo("UTC")).isoformat(),
                    })
                    if len(risultati) >= max_slots:
                        return risultati
                slot_inizio = slot_fine
    return risultati
