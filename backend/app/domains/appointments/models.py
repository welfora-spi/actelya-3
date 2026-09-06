"""Appointment Setter — costanti, stati e corpi Pydantic. Nessuna logica qui."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

PROVIDER_TYPES = ("google_calendar", "microsoft_graph", "calendly")

# Stato della connessione calendario, identico nello spirito a quello già
# usato per Meta/Runway/Requesty (mai un nome diverso per lo stesso concetto).
CONNECTION_STATUS = ("NON_CONFIGURATO", "CONFIGURATO", "VERIFICATO", "ERRORE")

PROPOSAL_STATUS = ("BOZZA", "IN_ATTESA_APPROVAZIONE", "APPROVATA", "RIFIUTATA", "INVIATA", "SCADUTA")

BOOKING_STATUS = ("PIANIFICATA", "IN_CODA", "IN_ESECUZIONE", "CONFERMATA", "FALLITA",
                 "ESITO_INCERTO", "CANCELLATA", "CANCELLAZIONE_INCERTA", "RIPROGRAMMATA", "SOSTITUITA")

# Stati della saga persistente di riprogrammazione (collection
# appointment_reschedule_sagas). Ogni fase e' scritta su MongoDB PRIMA di
# procedere alla successiva, cosi' un riavvio del processo puo' riprendere
# esattamente da dove si era interrotto (vedi pipeline.py::recover_on_startup
# e ::_advance_reschedule_saga). COMPENSAZIONE_RICHIESTA e' l'unico stato non
# ripreso automaticamente al riavvio: richiede un intervento esplicito
# (riconciliazione o risoluzione manuale della cancellazione dell'originale).
RESCHEDULE_SAGA_STATUS = (
    "RICHIESTA_CREATA",
    "NUOVO_SLOT_VERIFICATO",
    "CANCELLAZIONE_ORIGINALE_RICHIESTA",
    "CANCELLAZIONE_CONFERMATA",
    "SOSTITUTO_CREATO",
    "COMPLETATA",
    "FALLITA",
    "COMPENSAZIONE_RICHIESTA",
)

DEFAULT_SLOT_DURATION_MINUTES = 30
MAX_PROPOSED_SLOTS = 5


class CalendarConnectionBody(BaseModel):
    name: str
    provider_type: str = "google_calendar"
    calendar_id: str = "primary"
    timezone: str = "Europe/Rome"
    # Token ottenuti tramite il flusso OAuth (redirect+callback, vedi router.py)
    # oppure incollati manualmente per un uso avanzato/di test — mai richiesti
    # entrambi: qualunque campo assente resta NON_CONFIGURATO finché non
    # arriva tramite OAuth o inserimento manuale.
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    # Calendly usa un Personal Access Token al posto di OAuth.
    api_key: Optional[str] = None
    active: bool = True


class AvailabilityWindowBody(BaseModel):
    weekday: int = Field(ge=0, le=6)  # 0=lunedì ... 6=domenica
    start_time: str  # "HH:MM", ora locale nel timezone della connessione
    end_time: str


class ProposalBody(BaseModel):
    connection_id: str
    lead_id: str
    lead_type: str = "aziende"  # "aziende" | "persone" (stesso vocabolario di leadgen)
    campaign_id: Optional[str] = None
    duration_minutes: int = Field(default=DEFAULT_SLOT_DURATION_MINUTES, ge=5, le=240)
    search_from: Optional[str] = None  # ISO date; default: ora
    search_days: int = Field(default=7, ge=1, le=30)
    message_template: str = ""


class ApprovalBody(BaseModel):
    approve: bool
    note: str = ""


class BookingConfirmBody(BaseModel):
    slot_index: int = 0  # quale tra gli slot proposti viene prenotato
    confirm: bool = False


class RescheduleBody(BaseModel):
    new_start: str  # ISO datetime
    reason: str = ""


class ResolveCancellationBody(BaseModel):
    note: str


class CancelBody(BaseModel):
    reason: str = ""
