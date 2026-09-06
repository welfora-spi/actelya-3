"""Analyst/KPI — costanti e corpi Pydantic. Nessuna logica qui."""
from __future__ import annotations

from pydantic import BaseModel, Field

# Affidabilità del valore calcolato: mai un dato reale spacciato per certo
# quando il volume è troppo basso per essere significativo, e mai un dato
# mancante sostituito da un'invenzione (NON_DISPONIBILE è sempre esplicito).
RELIABILITY = ("ALTA", "MEDIA", "BASSA", "NON_DISPONIBILE")

# Agenti a cui un insight strutturato può essere indirizzato.
INSIGHT_TARGETS = (
    "coordinatore-actelya", "resp-marketing", "content-creator", "lead-gen-specialist", "sales-agent",
)


class GenerateReportBody(BaseModel):
    time_range_days: int = Field(default=30, ge=1, le=365)
