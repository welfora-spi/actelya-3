"""Brain — orchestratore LLM del CEO Agent (CEO Agent 100% reale, blocchi 2/3/6/12).

Punto UNICO da cui il resto del brain ottiene una proposta LLM: risolve la
configurazione per organizzazione (provider primario + catena di fallback
ordinata, da `ai_connections`/`settings`, mai duplicata altrove), costruisce
il contesto minimizzato (llm_context_builder.py), prova i provider in
ordine tramite il gateway astratto (llm_gateway.py — nessun SDK/dettaglio di
provider importato qui), valida ogni risposta contro lo schema
(llm_schema.py), e si ferma al primo successo. Degrada SEMPRE, in modo
esplicito e mai silenzioso, al planner deterministico quando: nessun
provider e' configurato/verificato, `ai_real_mode` e' spento, tutti i
tentativi falliscono, il timeout scade, o l'output non supera la
validazione — mai un falso successo, mai un'eccezione propagata al
chiamante."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from . import llm_gateway
from .llm_context_builder import BrainLLMContext, build_context
from .llm_schema import CeoLLMProposal, PropostaNonValida, SCHEMA_NOME, json_schema_per_provider

logger = logging.getLogger("actelya.brain.llm_understanding")

MODE_REALE = "REALE"
MODE_DETERMINISTICO = "DETERMINISTICO"

MAX_TOKENS_DEFAULT = 1400
TIMEOUT_DEFAULT_SECONDI = 20.0
MAX_FALLBACK_ATTEMPTS_DEFAULT = 2

_SYSTEM = (
    "Sei il modulo di comprensione e pianificazione del CEO Agent di ACTELYA. Ricevi la richiesta di "
    "un imprenditore e il contesto reale dell'azienda, e proponi un'analisi strutturata: intent, "
    "priorita', urgenza, budget, scadenza, vincoli, pubblico, canali, dati mancanti, rischi, strategia, "
    "agenti/capability suggeriti (SOLO tra quelli elencati nel contesto, mai inventati), task proposti "
    "con dipendenze, deliverable, KPI, approvazioni necessarie. Non decidi mai se la richiesta e' "
    "consentita: quella decisione resta di un livello deterministico che non puoi vedere ne' aggirare. "
    "Se un dato non e' nel contesto fornito, non inventarlo: elencalo in 'dati_mancanti'. Rispondi SOLO "
    "con l'oggetto JSON richiesto, in italiano."
)


@dataclass
class ProviderModelRef:
    provider_type: str
    connection_id: str
    model: str
    timeout: float
    max_tokens: int
    base_url: Optional[str] = None


@dataclass
class OrgLLMConfig:
    ai_real_mode: bool
    primary: Optional[ProviderModelRef]
    fallbacks: list = field(default_factory=list)   # list[ProviderModelRef]
    max_fallback_attempts: int = MAX_FALLBACK_ATTEMPTS_DEFAULT


@dataclass
class TentativoProvider:
    provider: str
    model: str
    esito: str            # "OK" | "ERRORE"
    codice_errore: Optional[str] = None
    messaggio: Optional[str] = None
    latenza_ms: Optional[int] = None

    def come_dict(self) -> dict:
        return {"provider": self.provider, "model": self.model, "esito": self.esito,
                "codice_errore": self.codice_errore, "messaggio": self.messaggio, "latenza_ms": self.latenza_ms}


@dataclass
class LLMOrchestrationOutcome:
    mode: str
    motivo: str
    provider_effettivo: Optional[str] = None
    modello_effettivo: Optional[str] = None
    proposta: Optional[CeoLLMProposal] = None
    providers_tried: list = field(default_factory=list)   # list[TentativoProvider]
    contesto: Optional[BrainLLMContext] = None

    def come_dict(self) -> dict:
        return {
            "mode": self.mode, "motivo": self.motivo,
            "provider_effettivo": self.provider_effettivo, "modello_effettivo": self.modello_effettivo,
            "proposta": self.proposta.model_dump() if self.proposta is not None else None,
            "providers_tried": [t.come_dict() for t in self.providers_tried],
        }


async def resolve_org_llm_config(db, org_id: str) -> OrgLLMConfig:
    """Nessuna API key ne' credenziale in chiaro in questo oggetto: solo
    riferimenti (provider_type, connection_id, modello) — la credenziale
    viene risolta al momento della chiamata da _resolve_api_key(), mai
    prima, mai loggata."""
    if db is None:
        return OrgLLMConfig(ai_real_mode=False, primary=None, fallbacks=[])
    try:
        settings = await db.settings.find_one({"id": org_id}) or {}
        righe = await db.ai_connections.find({
            "organization_id": org_id, "active": True, "verified": True,
        }, {"_id": 0}).sort([("priority", 1), ("created_at", 1)]).to_list(20)
    except (AttributeError, TypeError):
        return OrgLLMConfig(ai_real_mode=False, primary=None, fallbacks=[])

    ai_real_mode = bool(settings.get("ai_real_mode"))
    max_fallback = int(settings.get("llm_max_fallback_attempts") or MAX_FALLBACK_ATTEMPTS_DEFAULT)

    riferimenti: list[ProviderModelRef] = []
    for c in righe:
        modello = (c.get("effective_model") or c.get("logical_model") or "").strip()
        if not modello:
            continue
        if llm_gateway.get_adapter(c.get("provider_type", "")) is None:
            continue
        riferimenti.append(ProviderModelRef(
            provider_type=c["provider_type"], connection_id=c["id"], model=modello,
            timeout=float(c.get("timeout") or TIMEOUT_DEFAULT_SECONDI),
            max_tokens=int(c.get("max_tokens") or MAX_TOKENS_DEFAULT),
            base_url=(c.get("base_url") or "").strip() or None,
        ))

    if not riferimenti:
        return OrgLLMConfig(ai_real_mode=ai_real_mode, primary=None, fallbacks=[], max_fallback_attempts=max_fallback)
    return OrgLLMConfig(
        ai_real_mode=ai_real_mode, primary=riferimenti[0], fallbacks=riferimenti[1:1 + max_fallback],
        max_fallback_attempts=max_fallback,
    )


async def _resolve_api_key(db, org_id: str, ref: ProviderModelRef) -> Optional[str]:
    if ref.provider_type == "requesty":
        from ..integrations import requesty_secrets
        return "keyring" if requesty_secrets.requesty_configurata() else None
    try:
        conn = await db.ai_connections.find_one({"id": ref.connection_id, "organization_id": org_id})
    except (AttributeError, TypeError):
        return None
    if not conn or not conn.get("api_key_encrypted"):
        return None
    from ..security import decrypt_secret, SecretVaultError
    try:
        return decrypt_secret(conn["api_key_encrypted"])
    except SecretVaultError:
        return None


async def _prova_provider(db, org_id: str, ref: ProviderModelRef, contesto: BrainLLMContext) -> tuple[Optional[CeoLLMProposal], TentativoProvider]:
    adapter = llm_gateway.get_adapter(ref.provider_type)
    if adapter is None:
        return None, TentativoProvider(provider=ref.provider_type, model=ref.model, esito="ERRORE",
                                        codice_errore="provider_sconosciuto", messaggio="Nessun adapter per questo provider_type.")
    api_key = await _resolve_api_key(db, org_id, ref)
    try:
        r = adapter.genera_json(
            api_key=api_key, model=ref.model, system=_SYSTEM,
            messaggio_utente=contesto.come_prompt_utente(),
            schema_json=json_schema_per_provider(), schema_nome=SCHEMA_NOME,
            max_tokens=ref.max_tokens, timeout=ref.timeout, base_url=ref.base_url,
        )
    except llm_gateway.LLMGatewayError as exc:
        logger.info("Provider %s non disponibile (%s): %s", ref.provider_type, exc.codice, exc.messaggio)
        return None, TentativoProvider(provider=ref.provider_type, model=ref.model, esito="ERRORE",
                                        codice_errore=exc.codice, messaggio=exc.messaggio)

    try:
        from .llm_schema import parse_llm_proposal
        proposta = parse_llm_proposal(r.testo)
    except PropostaNonValida as exc:
        return None, TentativoProvider(provider=ref.provider_type, model=ref.model, esito="ERRORE",
                                        codice_errore="risposta_non_valida", messaggio=exc.motivo, latenza_ms=r.latenza_ms)

    return proposta, TentativoProvider(provider=ref.provider_type, model=r.modello_effettivo or ref.model,
                                        esito="OK", latenza_ms=r.latenza_ms)


async def propose_plan(db, org_id: str, goal_text: str, *, chiarimenti_precedenti: Optional[list] = None) -> LLMOrchestrationOutcome:
    """Ritorna sempre un esito, mai solleva. mode=REALE solo se un provider
    ha davvero risposto con una proposta valida; mode=DETERMINISTICO con un
    motivo esplicito in ogni altro caso — nessuna differenza di
    comportamento per il chiamante fra 'nessun provider configurato' e
    'tutti i provider hanno fallito': in entrambi i casi il planner
    deterministico prosegue esattamente come se questa funzione non
    esistesse."""
    cfg = await resolve_org_llm_config(db, org_id)
    if not cfg.ai_real_mode:
        return LLMOrchestrationOutcome(mode=MODE_DETERMINISTICO, motivo="Modalita' AI REALE non attiva per l'organizzazione.")
    if cfg.primary is None:
        return LLMOrchestrationOutcome(mode=MODE_DETERMINISTICO, motivo="Nessuna connessione AI verificata e attiva configurata per l'organizzazione.")

    contesto = await build_context(db, org_id, goal_text, chiarimenti_precedenti=chiarimenti_precedenti)
    tentativi: list[TentativoProvider] = []

    catena = [cfg.primary] + list(cfg.fallbacks)
    for ref in catena:
        proposta, tentativo = await _prova_provider(db, org_id, ref, contesto)
        tentativi.append(tentativo)
        if proposta is not None:
            return LLMOrchestrationOutcome(
                mode=MODE_REALE, motivo="Proposta ricevuta e validata.",
                provider_effettivo=tentativo.provider, modello_effettivo=tentativo.model,
                proposta=proposta, providers_tried=tentativi, contesto=contesto,
            )
        # Esito incerto: MAI ritentato con lo stesso provider (nessun ciclo
        # secondario qui sotto lo richiama di nuovo) — si passa al successivo
        # provider DIVERSO della catena, se presente, esattamente come per
        # qualunque altro errore.

    motivo = (
        f"Tutti i provider configurati ({len(tentativi)}) hanno fallito o non sono disponibili: "
        "si procede con il planner deterministico."
    )
    return LLMOrchestrationOutcome(mode=MODE_DETERMINISTICO, motivo=motivo, providers_tried=tentativi, contesto=contesto)
