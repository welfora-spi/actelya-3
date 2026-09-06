"""Sales Agent — costanti, stati e corpi Pydantic. Nessuna logica qui (vedi
strategy.py per le decisioni, pipeline.py per l'orchestrazione)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Pipeline commerciale completa (equivalenti diretti di new/researching/
# qualified/contacted/engaged/follow-up/meeting requested/meeting booked/
# opportunity/proposal/negotiation/won/lost).
PIPELINE_STAGES = (
    "NUOVO", "IN_ANALISI", "QUALIFICATO", "CONTATTATO", "IN_RELAZIONE",
    "FOLLOW_UP", "RICHIESTA_APPUNTAMENTO", "APPUNTAMENTO_FISSATO",
    "OPPORTUNITA", "PROPOSTA", "NEGOZIAZIONE", "VINTO", "PERSO",
)

# Stati terminali: nessuna ulteriore transizione automatica.
STAGE_TERMINALI = ("VINTO", "PERSO")

# Tipi di risposta del prospect che l'agente sa interpretare.
RESPONSE_TYPES = (
    "POSITIVA", "NEGATIVA", "RICHIESTA_INFORMAZIONI", "OBIEZIONE_PREZZO",
    "NON_INTERESSATO", "RICONTATTO_FUTURO", "NESSUNA_RISPOSTA", "ESCALATION",
    "RICHIESTA_APPUNTAMENTO",
)

# next_best_action: cosa l'agente propone di fare adesso (mai un'azione
# eseguita automaticamente — sempre una raccomandazione tracciata).
NEXT_BEST_ACTIONS = (
    "CONTATTA_ORA", "INVIA_FOLLOW_UP", "PIANIFICA_RICONTATTO", "GESTISCI_OBIEZIONE_PREZZO",
    "INVIA_INFORMAZIONI", "PROPONI_APPUNTAMENTO", "ESCALATION_UMANA", "NESSUNA_AZIONE",
)


class CreateOpportunityBody(BaseModel):
    lead_id: str = Field(min_length=1)
    lead_type: str = "aziende"  # "aziende" | "persone", stesso vocabolario di leadgen/appointments


class RecordResponseBody(BaseModel):
    response_type: str
    note: str = ""


class RequestMessageBody(BaseModel):
    channel_override: Optional[str] = None


class LinkAppointmentBody(BaseModel):
    proposal_id: str = Field(min_length=1)


class EscalationResolveBody(BaseModel):
    note: str = Field(min_length=1)
