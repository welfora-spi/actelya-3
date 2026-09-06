"""Appointment Setter — interfaccia astratta per i provider calendario, mai
legata a un singolo servizio (stesso principio di domains/leadgen/research.py
per i provider di ricerca prospect). Ogni adapter dichiara se e' CONFIGURATO;
un adapter non configurato ritorna sempre esplicitamente NON_DISPONIBILE,
mai un finto slot libero o una finta conferma.

Le chiamate reali usano `requests` in funzioni SINCRONE (stesso pattern di
integrations/runway_gateway.py/requesty_gateway.py: nessun await, il
chiamante — un handler async — le invoca direttamente). Mai invocate nei
test: i test sostituiscono `build_adapter` con un fake adapter deterministico
tramite monkeypatch, esattamente come gia' avviene per llm_gateway.ADAPTERS."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import requests

from ...security import decrypt_secret

STATO_OK = "OK"
STATO_NON_DISPONIBILE = "NON_DISPONIBILE"
STATO_ERRORE = "ERRORE"

TIMEOUT_SECONDI = 10.0

# Credenziali dell'app OAuth (registrata UNA VOLTA dall'operatore ACTELYA
# presso il provider, mai per organizzazione): lette da env, mai da Mongo,
# mai restituite al frontend. Un client_id/secret assente rende NON
# disponibile il flusso OAuth per QUALUNQUE organizzazione finche' non
# configurato: nessuna eccezione, nessun crash, un motivo esplicito.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CALENDAR_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_CALENDAR_REDIRECT_URI", "")
MS_CLIENT_ID = os.environ.get("MS_GRAPH_CLIENT_ID", "")
MS_CLIENT_SECRET = os.environ.get("MS_GRAPH_CLIENT_SECRET", "")
MS_REDIRECT_URI = os.environ.get("MS_GRAPH_REDIRECT_URI", "")

GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_API_BASE = "https://www.googleapis.com/calendar/v3"
GOOGLE_SCOPES = "https://www.googleapis.com/auth/calendar.events"

MS_AUTH_BASE = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_API_BASE = "https://graph.microsoft.com/v1.0"
MS_SCOPES = "offline_access Calendars.ReadWrite"

CALENDLY_API_BASE = "https://api.calendly.com"


@dataclass
class CalendarEvent:
    provider_event_id: Optional[str]
    status: str  # OK | NON_DISPONIBILE | ERRORE | ESITO_INCERTO
    motivo: Optional[str] = None
    raw: dict = field(default_factory=dict)

    def come_dict(self) -> dict:
        return {"provider_event_id": self.provider_event_id, "status": self.status,
                "motivo": self.motivo}


@dataclass
class BusySlot:
    start: str
    end: str


class CalendarAdapter(ABC):
    provider_type: str = "sconosciuto"

    @property
    @abstractmethod
    def configured(self) -> bool:
        ...

    @abstractmethod
    def verify(self) -> tuple[bool, Optional[str]]:
        """Verifica reale, sola lettura (es. leggere il calendario), nessun costo. Ritorna (ok, motivo_errore)."""

    @abstractmethod
    def list_busy(self, start_iso: str, end_iso: str) -> list[BusySlot]:
        ...

    @abstractmethod
    def create_event(self, *, start_iso: str, end_iso: str, title: str, description: str) -> CalendarEvent:
        ...

    @abstractmethod
    def cancel_event(self, provider_event_id: str) -> bool:
        ...


def _authz_header(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


class GoogleCalendarAdapter(CalendarAdapter):
    provider_type = "google_calendar"

    def __init__(self, connection: dict):
        self._conn = connection
        self._calendar_id = connection.get("calendar_id") or "primary"
        self._access_token = None
        enc = connection.get("access_token_encrypted")
        if enc:
            self._access_token = decrypt_secret(enc)

    @property
    def configured(self) -> bool:
        return bool(self._access_token)

    def verify(self) -> tuple[bool, Optional[str]]:
        if not self.configured:
            return False, "Nessun token di accesso configurato."
        try:
            r = requests.get(f"{GOOGLE_API_BASE}/calendars/{self._calendar_id}",
                             headers=_authz_header(self._access_token), timeout=TIMEOUT_SECONDI)
        except requests.RequestException as exc:
            return False, str(exc)
        if r.status_code == 200:
            return True, None
        return False, f"Google Calendar ha risposto {r.status_code}"

    def list_busy(self, start_iso: str, end_iso: str) -> list[BusySlot]:
        if not self.configured:
            return []
        try:
            r = requests.post(f"{GOOGLE_API_BASE}/freeBusy",
                              headers={**_authz_header(self._access_token), "Content-Type": "application/json"},
                              json={"timeMin": start_iso, "timeMax": end_iso,
                                    "items": [{"id": self._calendar_id}]},
                              timeout=TIMEOUT_SECONDI)
            r.raise_for_status()
            busy = r.json().get("calendars", {}).get(self._calendar_id, {}).get("busy", [])
            return [BusySlot(b["start"], b["end"]) for b in busy]
        except (requests.RequestException, KeyError, ValueError):
            return []

    def create_event(self, *, start_iso: str, end_iso: str, title: str, description: str) -> CalendarEvent:
        if not self.configured:
            return CalendarEvent(None, STATO_NON_DISPONIBILE, "Connessione Google Calendar non configurata.")
        try:
            r = requests.post(
                f"{GOOGLE_API_BASE}/calendars/{self._calendar_id}/events",
                headers={**_authz_header(self._access_token), "Content-Type": "application/json"},
                json={"summary": title, "description": description,
                     "start": {"dateTime": start_iso}, "end": {"dateTime": end_iso}},
                timeout=TIMEOUT_SECONDI,
            )
        except requests.RequestException as exc:
            return CalendarEvent(None, "ESITO_INCERTO", str(exc))
        if r.status_code in (200, 201):
            data = r.json()
            return CalendarEvent(data.get("id"), STATO_OK, raw={"htmlLink": data.get("htmlLink")})
        if r.status_code >= 500:
            return CalendarEvent(None, "ESITO_INCERTO", f"Google Calendar {r.status_code}")
        return CalendarEvent(None, STATO_ERRORE, f"Google Calendar ha rifiutato la richiesta: {r.status_code}")

    def cancel_event(self, provider_event_id: str) -> bool:
        if not self.configured or not provider_event_id:
            return False
        try:
            r = requests.delete(f"{GOOGLE_API_BASE}/calendars/{self._calendar_id}/events/{provider_event_id}",
                                headers=_authz_header(self._access_token), timeout=TIMEOUT_SECONDI)
            return r.status_code in (200, 204, 410)
        except requests.RequestException:
            return False


class MicrosoftGraphAdapter(CalendarAdapter):
    provider_type = "microsoft_graph"

    def __init__(self, connection: dict):
        self._conn = connection
        self._access_token = None
        enc = connection.get("access_token_encrypted")
        if enc:
            self._access_token = decrypt_secret(enc)

    @property
    def configured(self) -> bool:
        return bool(self._access_token)

    def verify(self) -> tuple[bool, Optional[str]]:
        if not self.configured:
            return False, "Nessun token di accesso configurato."
        try:
            r = requests.get(f"{MS_API_BASE}/me/calendar", headers=_authz_header(self._access_token),
                             timeout=TIMEOUT_SECONDI)
        except requests.RequestException as exc:
            return False, str(exc)
        if r.status_code == 200:
            return True, None
        return False, f"Microsoft Graph ha risposto {r.status_code}"

    def list_busy(self, start_iso: str, end_iso: str) -> list[BusySlot]:
        if not self.configured:
            return []
        try:
            r = requests.post(
                f"{MS_API_BASE}/me/calendar/getSchedule",
                headers={**_authz_header(self._access_token), "Content-Type": "application/json"},
                json={"schedules": ["me"], "startTime": {"dateTime": start_iso, "timeZone": "UTC"},
                     "endTime": {"dateTime": end_iso, "timeZone": "UTC"}},
                timeout=TIMEOUT_SECONDI,
            )
            r.raise_for_status()
            items = (r.json().get("value") or [{}])[0].get("scheduleItems", [])
            return [BusySlot(i["start"]["dateTime"], i["end"]["dateTime"]) for i in items]
        except (requests.RequestException, KeyError, IndexError, ValueError):
            return []

    def create_event(self, *, start_iso: str, end_iso: str, title: str, description: str) -> CalendarEvent:
        if not self.configured:
            return CalendarEvent(None, STATO_NON_DISPONIBILE, "Connessione Microsoft Graph non configurata.")
        try:
            r = requests.post(
                f"{MS_API_BASE}/me/events",
                headers={**_authz_header(self._access_token), "Content-Type": "application/json"},
                json={"subject": title, "body": {"contentType": "Text", "content": description},
                     "start": {"dateTime": start_iso, "timeZone": "UTC"},
                     "end": {"dateTime": end_iso, "timeZone": "UTC"}},
                timeout=TIMEOUT_SECONDI,
            )
        except requests.RequestException as exc:
            return CalendarEvent(None, "ESITO_INCERTO", str(exc))
        if r.status_code in (200, 201):
            data = r.json()
            return CalendarEvent(data.get("id"), STATO_OK, raw={"webLink": data.get("webLink")})
        if r.status_code >= 500:
            return CalendarEvent(None, "ESITO_INCERTO", f"Microsoft Graph {r.status_code}")
        return CalendarEvent(None, STATO_ERRORE, f"Microsoft Graph ha rifiutato la richiesta: {r.status_code}")

    def cancel_event(self, provider_event_id: str) -> bool:
        if not self.configured or not provider_event_id:
            return False
        try:
            r = requests.delete(f"{MS_API_BASE}/me/events/{provider_event_id}",
                                headers=_authz_header(self._access_token), timeout=TIMEOUT_SECONDI)
            return r.status_code in (200, 204, 404)
        except requests.RequestException:
            return False


class CalendlyAdapter(CalendarAdapter):
    """Calendly usa un Personal Access Token (mai OAuth in questa fase) e un
    modello 'scheduling page' — non un create_event libero: qui esponiamo
    solo la sola-lettura reale (utente/disponibilita'); create/cancel restano
    NON_DISPONIBILE finche' non si integra l'endpoint di scheduling reale
    (richiede una Scheduling Link gia' pubblicata dal cliente, fuori scope
    codice)."""
    provider_type = "calendly"

    def __init__(self, connection: dict):
        self._conn = connection
        self._api_key = None
        enc = connection.get("api_key_encrypted")
        if enc:
            self._api_key = decrypt_secret(enc)

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def verify(self) -> tuple[bool, Optional[str]]:
        if not self.configured:
            return False, "Nessun Personal Access Token Calendly configurato."
        try:
            r = requests.get(f"{CALENDLY_API_BASE}/users/me", headers=_authz_header(self._api_key),
                             timeout=TIMEOUT_SECONDI)
        except requests.RequestException as exc:
            return False, str(exc)
        if r.status_code == 200:
            return True, None
        return False, f"Calendly ha risposto {r.status_code}"

    def list_busy(self, start_iso: str, end_iso: str) -> list[BusySlot]:
        return []  # predisposto: Calendly non espone freebusy classico via API pubblica

    def create_event(self, *, start_iso: str, end_iso: str, title: str, description: str) -> CalendarEvent:
        return CalendarEvent(None, STATO_NON_DISPONIBILE,
                             "Prenotazione diretta Calendly non predisposta in questa fase: richiede una "
                             "Scheduling Link pubblicata dal cliente.")

    def cancel_event(self, provider_event_id: str) -> bool:
        return False


class _NonConfiguratoAdapter(CalendarAdapter):
    def __init__(self, provider_type: str):
        self.provider_type = provider_type

    @property
    def configured(self) -> bool:
        return False

    def verify(self) -> tuple[bool, Optional[str]]:
        return False, f"Connessione {self.provider_type} non configurata."

    def list_busy(self, start_iso: str, end_iso: str) -> list[BusySlot]:
        return []

    def create_event(self, *, start_iso: str, end_iso: str, title: str, description: str) -> CalendarEvent:
        return CalendarEvent(None, STATO_NON_DISPONIBILE, f"Connessione {self.provider_type} non configurata.")

    def cancel_event(self, provider_event_id: str) -> bool:
        return False


_ADAPTER_CLASSES = {
    "google_calendar": GoogleCalendarAdapter,
    "microsoft_graph": MicrosoftGraphAdapter,
    "calendly": CalendlyAdapter,
}


def build_adapter(connection: Optional[dict]) -> CalendarAdapter:
    """Factory unica usata da router.py/pipeline.py: mai istanziare un
    adapter concreto altrove. Nei test si sostituisce QUESTA funzione con un
    fake adapter tramite monkeypatch (stesso pattern di llm_gateway.ADAPTERS)."""
    if not connection:
        return _NonConfiguratoAdapter("sconosciuto")
    cls = _ADAPTER_CLASSES.get(connection.get("provider_type"))
    if not cls:
        return _NonConfiguratoAdapter(connection.get("provider_type", "sconosciuto"))
    return cls(connection)


def oauth_authorize_url(provider_type: str, state: str) -> Optional[str]:
    """Costruisce l'URL di autorizzazione OAuth (solo costruzione stringa,
    NESSUNA chiamata di rete): None se l'app OAuth non e' configurata
    (client_id/redirect_uri assenti da env) — mai un URL con un client_id
    vuoto passato al provider."""
    from urllib.parse import urlencode

    if provider_type == "google_calendar":
        if not (GOOGLE_CLIENT_ID and GOOGLE_REDIRECT_URI):
            return None
        params = {"client_id": GOOGLE_CLIENT_ID, "redirect_uri": GOOGLE_REDIRECT_URI,
                  "response_type": "code", "scope": GOOGLE_SCOPES, "access_type": "offline",
                  "prompt": "consent", "state": state}
        return f"{GOOGLE_AUTH_BASE}?{urlencode(params)}"
    if provider_type == "microsoft_graph":
        if not (MS_CLIENT_ID and MS_REDIRECT_URI):
            return None
        params = {"client_id": MS_CLIENT_ID, "redirect_uri": MS_REDIRECT_URI,
                  "response_type": "code", "scope": MS_SCOPES, "state": state}
        return f"{MS_AUTH_BASE}?{urlencode(params)}"
    return None  # calendly: nessun OAuth in questa fase, solo Personal Access Token


def oauth_exchange_code(provider_type: str, code: str) -> Optional[dict]:
    """Scambia un codice di autorizzazione con access/refresh token (chiamata
    REALE, mai invocata nei test: i test iniettano i token direttamente).
    Ritorna None se l'app OAuth non e' configurata o lo scambio fallisce."""
    if provider_type == "google_calendar":
        if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI):
            return None
        try:
            r = requests.post(GOOGLE_TOKEN_URL, data={
                "code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI, "grant_type": "authorization_code",
            }, timeout=TIMEOUT_SECONDI)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        data = r.json()
        return {"access_token": data.get("access_token"), "refresh_token": data.get("refresh_token")}
    if provider_type == "microsoft_graph":
        if not (MS_CLIENT_ID and MS_CLIENT_SECRET and MS_REDIRECT_URI):
            return None
        try:
            r = requests.post(MS_TOKEN_URL, data={
                "code": code, "client_id": MS_CLIENT_ID, "client_secret": MS_CLIENT_SECRET,
                "redirect_uri": MS_REDIRECT_URI, "grant_type": "authorization_code", "scope": MS_SCOPES,
            }, timeout=TIMEOUT_SECONDI)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        data = r.json()
        return {"access_token": data.get("access_token"), "refresh_token": data.get("refresh_token")}
    return None
