"""Professional Tool Registry — stato REALE per organizzazione. Nessun
calcolo statico spacciato per stato vero: un tool con codice completo
verifica la STESSA fonte di verità già usata dal proprio dominio (nessuna
seconda logica di readiness duplicata); un tool senza codice resta sempre
NON_CONFIGURATO, qualunque cosa contenga Mongo.

Il campo `status` restituito qui è SEMPRE nel vocabolario italiano a 4 stati
già usato da domains/appointments e domains/leadgen (NON_CONFIGURATO/
CONFIGURATO/VERIFICATO/ERRORE) — coerente con l'intero dominio applicativo,
anche quando la fonte di verità sottostante (brain/skills.py, per i
provider LLM/media/social più vecchi) usa le proprie costanti inglesi
REAL/NOT_CONFIGURED: qui vengono tradotte, mai esposte miste nella stessa
risposta API."""
from __future__ import annotations

from .registry import STATUS_NOT_CONFIGURED, STATUS_REAL, ToolSpec

_EN_TO_IT_STATUS = {STATUS_REAL: "VERIFICATO", STATUS_NOT_CONFIGURED: "NON_CONFIGURATO"}

# tool_id -> (collection, provider_type) per i provider con verifica
# verified+active già esistente (stesso schema di brain/skills.py::skill_status).
_VERIFIED_ACTIVE_COLLECTION = {
    "requesty_llm": ("ai_connections", "requesty"),
    "openai_llm": ("ai_connections", "openai"),
    "anthropic_llm": ("ai_connections", "anthropic"),
    "gemini_llm": ("ai_connections", "gemini"),
    "runway_video": ("video_connections", "runway"),
    "meta_graph_social": ("meta_connections", None),
    "meta_insights": ("meta_connections", None),
}

# tool_id -> nome del provider_type nella collezione appointment_connections
# (che già persiste uno stato CONFIGURATO/VERIFICATO/ERRORE proprio: qui si
# legge quello, mai una seconda verifica). 'calendly_booking' non compare
# qui di proposito: code_complete=False (solo la verifica del token è
# reale, non la disponibilità/prenotazione — vedi registry.py), quindi il
# ramo `if not tool.code_complete` sopra intercetta sempre prima di
# arrivare qui.
_APPOINTMENT_PROVIDER = {
    "google_calendar": "google_calendar",
    "microsoft_calendar": "microsoft_graph",
}

# Tool sempre REAL perché puramente interni (nessuna connessione esterna da verificare).
_ALWAYS_REAL = {"actelya_audit_log", "local_document_parsers"}


async def computed_status_for(tool: ToolSpec, org_id: str, db) -> str:
    if not tool.code_complete:
        return "NON_CONFIGURATO"
    if tool.tool_id in _ALWAYS_REAL:
        return "VERIFICATO"

    if tool.tool_id in _APPOINTMENT_PROVIDER:
        provider_type = _APPOINTMENT_PROVIDER[tool.tool_id]
        conn = await db.appointment_connections.find_one(
            {"organization_id": org_id, "provider_type": provider_type}, {"_id": 0, "status": 1},
        )
        return conn["status"] if conn else "NON_CONFIGURATO"

    ref = _VERIFIED_ACTIVE_COLLECTION.get(tool.tool_id)
    if ref:
        collection, provider_type = ref
        query = {"organization_id": org_id, "verified": True, "active": True}
        if provider_type:
            query["provider_type"] = provider_type
        conn = await db[collection].find_one(query, {"_id": 0, "id": 1})
        return _EN_TO_IT_STATUS[STATUS_REAL] if conn else _EN_TO_IT_STATUS[STATUS_NOT_CONFIGURED]

    return "NON_CONFIGURATO"
