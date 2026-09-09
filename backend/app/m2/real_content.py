"""Milestone 2 — generazione REALE (gateway LLM esistente) per i due task M2
generici e testuali: editorial_plan e social_content.

Attivo SOLO quando (tutte le condizioni, verificate dal chiamante in
engine.py::_execute):
- l'organizzazione ha ai_real_mode=True in QUESTO momento;
- il task e' stato approvato mentre l'organizzazione era GIA' in quella
  modalita' (campo 'approved_mode' impostato da engine.py::approve_plan/
  approve_task): un'approvazione data in SIMULAZIONE non autorizza mai una
  spesa reale, nemmeno se l'org passa REALE in seguito — e un piano creato/
  approvato PRIMA di questa funzionalita' non ha affatto questo campo, quindi
  ricade sempre sul percorso simulato esistente, mai eseguito o convertito
  automaticamente in REALE;
- una connessione AI verificata e attiva e' configurata (stesso gateway
  multi-provider di brain/llm_gateway.py, stessa risoluzione di
  brain/llm_understanding.py::resolve_org_llm_config).

In ogni altro caso il chiamante resta sul percorso simulato deterministico
invariato di deliverables.py — questo modulo non decide MAI da solo se e'
lecito chiamare il provider, si limita a farlo quando richiesto e a
restituire un esito tipizzato (successo con contenuto + provenienza reale,
oppure un errore con codice stabile): mai un'eccezione grezza, mai un
fallback silenzioso a contenuto simulato dichiarato completato."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from ..brain import llm_gateway
from ..brain.llm_understanding import ProviderModelRef, resolve_org_llm_config
from ..domains.estimator import PRICE_PER_TOKEN

REAL_ELIGIBLE_TYPES = {"editorial_plan", "social_content"}


async def _resolve_api_key(db, org_id: str, ref: ProviderModelRef) -> Optional[str]:
    """Duplicato deliberato (5 righe) di brain/llm_understanding.py::_resolve_api_key
    — stesso motivo per cui domains/flyer.py duplica _company_context di
    domains/reel.py: evita un accoppiamento incrociato M2 -> funzione privata
    di un altro pacchetto, senza introdurre una seconda logica."""
    if ref.provider_type == "requesty":
        from ..integrations import requesty_secrets
        return "keyring" if requesty_secrets.requesty_configurata() else None
    conn = await db.ai_connections.find_one({"id": ref.connection_id, "organization_id": org_id})
    if not conn or not conn.get("api_key_encrypted"):
        return None
    from ..security import SecretVaultError, decrypt_secret
    try:
        return decrypt_secret(conn["api_key_encrypted"])
    except SecretVaultError:
        return None


@dataclass
class RealReadiness:
    pronto: bool
    motivi: list
    ref: Optional[ProviderModelRef] = None


async def check_readiness(db, org_id: str) -> RealReadiness:
    """Stesso pattern di domains/flyer.py::_readiness: ai_real_mode + connessione
    verificata/attiva + budget generale configurato, TUTTI verificati PRIMA di
    qualunque chiamata reale."""
    cfg = await resolve_org_llm_config(db, org_id)
    motivi = []
    if not cfg.ai_real_mode:
        motivi.append("Modalita' AI REALE non attiva per l'organizzazione (Impostazioni).")
    if cfg.primary is None:
        motivi.append("Nessuna connessione AI verificata e attiva configurata (Connessioni).")
    budget = await db.budgets.find_one({"id": org_id}) or {}
    if not budget.get("general_limit", 0.0) > 0:
        motivi.append("Nessun budget generale configurato (Budget).")
    return RealReadiness(pronto=not motivi, motivi=motivi, ref=cfg.primary)


@dataclass
class RealGenerationResult:
    esito: str                      # "OK" | "ERRORE"
    content: Optional[dict] = None
    codice_errore: Optional[str] = None
    messaggio: Optional[str] = None
    provider: Optional[str] = None
    modello_effettivo: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latenza_ms: Optional[int] = None
    stima_costo_usd: Optional[float] = None
    truncated: bool = False


def _stima_costo(input_tokens, output_tokens) -> Optional[float]:
    """Mai una cifra inventata quando i token reali non sono noti (None, mai 0)."""
    if input_tokens is None or output_tokens is None:
        return None
    return round((input_tokens + output_tokens) * PRICE_PER_TOKEN, 6)


_EDITORIAL_SYSTEM = (
    "Sei uno Strategist di contenuti editoriali di ACTELYA. REGOLA ASSOLUTA: usa "
    "ESCLUSIVAMENTE il soggetto, il brand, il prodotto e i dettagli forniti nella richiesta "
    "dell'utente qui sotto. Se la richiesta descrive un'azienda o un'attivita' immaginaria o di "
    "esempio, usa ESATTAMENTE quella — non sostituirla MAI con altre informazioni aziendali "
    "eventualmente presenti nel contesto o nel tuo addestramento. Non inventare fatti non "
    "forniti nella richiesta. Se la richiesta specifica un calendario (giorni, canali, formati), "
    "rispettalo esattamente, senza aggiungere o togliere voci. Il campo 'calendar' deve avere "
    "almeno 3 voci, ciascuna con topic (almeno 6 caratteri), format e channel (almeno 3 "
    "caratteri). Rispondi SOLO con l'oggetto JSON richiesto, in italiano."
)

EDITORIAL_PLAN_SCHEMA = {
    "type": "object",
    "required": ["title", "cadence", "tone_of_voice", "pillars", "calendar"],
    "properties": {
        "title": {"type": "string"},
        "cadence": {"type": "string"},
        "tone_of_voice": {"type": "string"},
        "pillars": {"type": "array", "items": {"type": "string"}},
        "calendar": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["slot", "topic", "format", "channel"],
                "properties": {
                    "slot": {"type": "string"}, "topic": {"type": "string"},
                    "format": {"type": "string"}, "channel": {"type": "string"},
                },
            },
        },
    },
}

_SOCIAL_SYSTEM = (
    "Sei un Social Media Manager di ACTELYA. REGOLA ASSOLUTA: usa ESCLUSIVAMENTE il soggetto, "
    "il brand, il prodotto e i dettagli forniti nella richiesta dell'utente e nel piano "
    "editoriale collegato qui sotto. Se la richiesta descrive un'azienda o un'attivita' "
    "immaginaria o di esempio, usa ESATTAMENTE quella — non sostituirla MAI con altre "
    "informazioni aziendali eventualmente presenti nel contesto o nel tuo addestramento. Ogni "
    "post deve avere: hook, body (testo breve ma sostanziale, almeno 20 caratteri), cta, almeno "
    "2 hashtag pertinenti, channel (canale esatto), objective (obiettivo del post) e "
    "success_metric (criterio di successo misurabile, dichiarato ESPLICITAMENTE come obiettivo "
    "dimostrativo/simulato, mai come un risultato reale gia' ottenuto). Non inventare fatti non "
    "forniti. Rispondi SOLO con l'oggetto JSON richiesto, in italiano."
)

SOCIAL_CONTENT_SCHEMA = {
    "type": "object",
    "required": ["platform", "posts"],
    "properties": {
        "platform": {"type": "string"},
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["hook", "body", "cta", "hashtags", "channel", "objective", "success_metric"],
                "properties": {
                    "hook": {"type": "string"}, "body": {"type": "string"}, "cta": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "channel": {"type": "string"}, "day": {"type": "string"},
                    "objective": {"type": "string"}, "success_metric": {"type": "string"},
                },
            },
        },
    },
}


async def _call(db, org_id: str, ref: ProviderModelRef, *, system: str, user_message: str,
                 schema: dict, schema_name: str) -> RealGenerationResult:
    adapter = llm_gateway.get_adapter(ref.provider_type)
    if adapter is None:
        return RealGenerationResult(esito="ERRORE", codice_errore="provider_sconosciuto",
                                     messaggio="Nessun adapter registrato per il provider configurato.")
    api_key = await _resolve_api_key(db, org_id, ref)
    try:
        r = adapter.genera_json(
            api_key=api_key, model=ref.model, system=system, messaggio_utente=user_message,
            schema_json=schema, schema_nome=schema_name, max_tokens=ref.max_tokens,
            timeout=ref.timeout, base_url=ref.base_url,
        )
    except llm_gateway.LLMGatewayError as exc:
        return RealGenerationResult(esito="ERRORE", codice_errore=exc.codice, messaggio=exc.messaggio,
                                     provider=exc.provider)

    stima = _stima_costo(r.input_tokens, r.output_tokens)
    if r.troncata:
        return RealGenerationResult(
            esito="ERRORE", codice_errore="risposta_troncata",
            messaggio="La risposta del provider e' stata troncata (max_tokens insufficiente): "
                      "contenuto incompleto, mai salvato come completato.",
            provider=r.provider, modello_effettivo=r.modello_effettivo,
            input_tokens=r.input_tokens, output_tokens=r.output_tokens,
            latenza_ms=r.latenza_ms, stima_costo_usd=stima, truncated=True,
        )
    try:
        content = json.loads(r.testo)
    except (json.JSONDecodeError, TypeError):
        return RealGenerationResult(
            esito="ERRORE", codice_errore="risposta_non_valida",
            messaggio="La risposta del provider non e' un JSON valido.",
            provider=r.provider, modello_effettivo=r.modello_effettivo,
            input_tokens=r.input_tokens, output_tokens=r.output_tokens,
            latenza_ms=r.latenza_ms, stima_costo_usd=stima,
        )
    if not isinstance(content, dict):
        return RealGenerationResult(
            esito="ERRORE", codice_errore="risposta_non_valida",
            messaggio="La risposta del provider non e' un oggetto JSON.",
            provider=r.provider, modello_effettivo=r.modello_effettivo,
            input_tokens=r.input_tokens, output_tokens=r.output_tokens,
            latenza_ms=r.latenza_ms, stima_costo_usd=stima,
        )
    return RealGenerationResult(
        esito="OK", content=content, provider=r.provider, modello_effettivo=r.modello_effettivo,
        input_tokens=r.input_tokens, output_tokens=r.output_tokens, latenza_ms=r.latenza_ms,
        stima_costo_usd=stima,
    )


_SOCIAL_REVISION_SYSTEM = (
    "Sei un Social Media Manager di ACTELYA che sta REVISIONANDO un singolo post gia' esistente, non "
    "creandone uno nuovo da zero. REGOLA ASSOLUTA: modifica SOLO ciò che la richiesta di modifica indica, "
    "mantenendo tutto il resto coerente con il post originale fornito qui sotto. Usa ESCLUSIVAMENTE il "
    "soggetto, il brand e i dettagli gia' presenti nel post originale — non sostituirli MAI con altre "
    "informazioni aziendali eventualmente presenti nel contesto o nel tuo addestramento, e non inventare "
    "fatti non forniti. Il risultato deve avere: hook, body (testo breve ma sostanziale, almeno 20 "
    "caratteri), cta, almeno 2 hashtag pertinenti, channel, objective e success_metric (dichiarato "
    "ESPLICITAMENTE come obiettivo dimostrativo/simulato, mai come un risultato reale gia' ottenuto). "
    "Rispondi SOLO con l'oggetto JSON del post revisionato, in italiano."
)

_SOCIAL_POST_SCHEMA = SOCIAL_CONTENT_SCHEMA["properties"]["posts"]["items"]


async def generate_social_content_item_revision(db, org_id: str, ref: ProviderModelRef, post_originale: dict,
                                                 nota_modifica: str) -> RealGenerationResult:
    """Rigenera UN solo post esistente secondo una richiesta di modifica
    editoriale — mai l'intero deliverable, mai le altre bozze. Stesso
    principio anti-allucinazione e stesso schema di generate_social_content,
    ristretto a un singolo oggetto invece dell'array completo."""
    user_message = (
        f"Post originale (JSON):\n{json.dumps(post_originale, ensure_ascii=False)}\n\n"
        f"Richiesta di modifica editoriale da applicare:\n{nota_modifica}\n\n"
        "Restituisci il post revisionato, con lo stesso schema del post originale."
    )
    return await _call(db, org_id, ref, system=_SOCIAL_REVISION_SYSTEM, user_message=user_message,
                       schema=_SOCIAL_POST_SCHEMA, schema_name="actelya_social_content_item_revision")


async def generate_editorial_plan(db, org_id: str, ref: ProviderModelRef, goal_text: str) -> RealGenerationResult:
    user_message = (
        f"Richiesta originale dell'utente:\n{goal_text}\n\n"
        "Genera il piano editoriale richiesto, rispettando esattamente soggetto e calendario "
        "indicati nella richiesta."
    )
    return await _call(db, org_id, ref, system=_EDITORIAL_SYSTEM, user_message=user_message,
                        schema=EDITORIAL_PLAN_SCHEMA, schema_name="actelya_editorial_plan")


async def generate_social_content(db, org_id: str, ref: ProviderModelRef, goal_text: str,
                                   editorial_plan_content: Optional[dict]) -> RealGenerationResult:
    blocco_piano = (
        "\n\nPiano editoriale gia' prodotto per questo stesso obiettivo (i post devono essere "
        f"coerenti con temi/canali/calendario di questo piano):\n"
        f"{json.dumps(editorial_plan_content, ensure_ascii=False)}"
        if editorial_plan_content else ""
    )
    user_message = (
        f"Richiesta originale dell'utente:\n{goal_text}{blocco_piano}\n\n"
        "Genera i post social richiesti, rispettando esattamente soggetto e calendario/canali "
        "indicati nella richiesta."
    )
    return await _call(db, org_id, ref, system=_SOCIAL_SYSTEM, user_message=user_message,
                        schema=SOCIAL_CONTENT_SCHEMA, schema_name="actelya_social_content")
