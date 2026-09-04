"""Brain — schema strutturato della proposta CEO (CEO Agent 100% reale, blocco 4).

`CeoLLMProposal` e' l'UNICA forma in cui l'output di un provider LLM entra nel
resto del sistema: il JSON grezzo del provider viene sempre fatto passare da
`parse_llm_proposal()` prima di essere usato altrove. Un output sintatticamente
valido ma non conforme allo schema, o conforme ma semanticamente vuoto/inutile
(nessun intent, nessuna strategia, nessun agente/task proposto), viene sempre
rifiutato qui — mai propagato come se fosse una proposta utilizzabile."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, ValidationError

SCHEMA_NOME = "ceo_agent_proposal"

LIVELLI = ("BASSA", "MEDIA", "ALTA")


class RischioProposto(BaseModel):
    categoria: str = Field(..., min_length=1)
    severita: str = "MEDIA"
    descrizione: str = ""


class AllocazioneBudget(BaseModel):
    etichetta: str = Field(..., min_length=1)   # nome task o canale
    importo: float = 0.0


class AgenteSuggerito(BaseModel):
    capability: str = Field(..., min_length=1)
    motivazione: str = ""


class TaskProposto(BaseModel):
    nome: str = Field(..., min_length=1)
    capability: str = Field(..., min_length=1)
    ordine: int = 0
    dipende_da: list[str] = Field(default_factory=list)
    deliverable_type: Optional[str] = None
    priorita: str = "MEDIA"
    scadenza: Optional[str] = None


class CeoLLMProposal(BaseModel):
    intent: str = ""
    obiettivo_normalizzato: str = ""
    priorita: str = "MEDIA"
    urgenza: str = "MEDIA"
    budget_totale: Optional[float] = None
    budget_valuta: str = "EUR"
    allocazioni_budget: list[AllocazioneBudget] = Field(default_factory=list)
    scadenza: Optional[str] = None
    vincoli: list[str] = Field(default_factory=list)
    pubblico: Optional[str] = None
    canali: list[str] = Field(default_factory=list)
    dati_mancanti: list[str] = Field(default_factory=list)
    rischi: list[RischioProposto] = Field(default_factory=list)
    strategia_proposta: str = ""
    agenti_suggeriti: list[AgenteSuggerito] = Field(default_factory=list)
    capability_richieste: list[str] = Field(default_factory=list)
    task_proposti: list[TaskProposto] = Field(default_factory=list)
    deliverable: list[str] = Field(default_factory=list)
    kpi: list[str] = Field(default_factory=list)
    approvazioni_necessarie: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    assunzioni: list[str] = Field(default_factory=list)

    def e_significativa(self) -> bool:
        """False per un output tecnicamente valido ma inutile (nessun
        intent/strategia/agente/task proposto): equivalente a una risposta
        vuota, va rifiutato esattamente come un JSON malformato."""
        return bool(
            (self.intent or "").strip()
            or (self.strategia_proposta or "").strip()
            or self.agenti_suggeriti
            or self.task_proposti
        )


class PropostaNonValida(Exception):
    def __init__(self, motivo: str):
        self.motivo = motivo
        super().__init__(motivo)


def parse_llm_proposal(testo_json: str) -> CeoLLMProposal:
    """Valida il testo JSON grezzo di un provider contro CeoLLMProposal.
    Solleva PropostaNonValida (mai un'eccezione Pydantic grezza) per JSON
    sintatticamente non valido, schema non conforme, o risposta
    semanticamente vuota/inutilizzabile."""
    import json

    try:
        grezzo = json.loads(testo_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise PropostaNonValida("La risposta del provider non e' un JSON valido.") from exc
    if not isinstance(grezzo, dict):
        raise PropostaNonValida("La risposta del provider non e' un oggetto JSON.")

    try:
        proposta = CeoLLMProposal.model_validate(grezzo)
    except ValidationError as exc:
        raise PropostaNonValida(f"La risposta non rispetta lo schema atteso: {exc.error_count()} errore/i di validazione.") from exc

    if not proposta.e_significativa():
        raise PropostaNonValida("La risposta e' conforme allo schema ma semanticamente vuota (nessun intent/strategia/agente/task).")

    return proposta


def json_schema_per_provider() -> dict:
    """JSON Schema scritto a mano (non generato da Pydantic): i provider
    (OpenAI response_format, Anthropic tool input_schema, Gemini
    responseSchema) richiedono un dialetto semplice e prevedibile — niente
    $defs/anyOf che Pydantic.model_json_schema() introdurrebbe per i campi
    Optional. La validazione semantica resta comunque sempre Pydantic
    (parse_llm_proposal sopra), questo schema serve solo a guidare il
    provider verso una forma piu' vicina a quella attesa."""
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string"},
            "obiettivo_normalizzato": {"type": "string"},
            "priorita": {"type": "string", "enum": list(LIVELLI)},
            "urgenza": {"type": "string", "enum": list(LIVELLI)},
            "budget_totale": {"type": ["number", "null"]},
            "budget_valuta": {"type": "string"},
            "allocazioni_budget": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"etichetta": {"type": "string"}, "importo": {"type": "number"}},
                    "required": ["etichetta", "importo"],
                },
            },
            "scadenza": {"type": ["string", "null"]},
            "vincoli": {"type": "array", "items": {"type": "string"}},
            "pubblico": {"type": ["string", "null"]},
            "canali": {"type": "array", "items": {"type": "string"}},
            "dati_mancanti": {"type": "array", "items": {"type": "string"}},
            "rischi": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "categoria": {"type": "string"},
                        "severita": {"type": "string", "enum": list(LIVELLI)},
                        "descrizione": {"type": "string"},
                    },
                    "required": ["categoria"],
                },
            },
            "strategia_proposta": {"type": "string"},
            "agenti_suggeriti": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"capability": {"type": "string"}, "motivazione": {"type": "string"}},
                    "required": ["capability"],
                },
            },
            "capability_richieste": {"type": "array", "items": {"type": "string"}},
            "task_proposti": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nome": {"type": "string"}, "capability": {"type": "string"},
                        "ordine": {"type": "integer"}, "dipende_da": {"type": "array", "items": {"type": "string"}},
                        "deliverable_type": {"type": ["string", "null"]}, "priorita": {"type": "string", "enum": list(LIVELLI)},
                        "scadenza": {"type": ["string", "null"]},
                    },
                    "required": ["nome", "capability"],
                },
            },
            "deliverable": {"type": "array", "items": {"type": "string"}},
            "kpi": {"type": "array", "items": {"type": "string"}},
            "approvazioni_necessarie": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
            "assunzioni": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["intent", "strategia_proposta"],
    }
