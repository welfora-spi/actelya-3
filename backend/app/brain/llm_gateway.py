"""Brain — gateway LLM astratto multi-provider (CEO Agent 100% reale, blocco 2).

Contratto comune (`LLMProviderAdapter.genera_json`) dietro cui il resto del
brain non vede MAI un dettaglio specifico di provider: nessun modulo del
brain importa `openai`/`anthropic`/SDK di terzi o httpx direttamente — passa
sempre da qui. Quattro adapter reali, tutti su trasporto HTTP gia'
disponibile nel progetto (`requests`, usato anche da `integrations/meta/`):

- OpenAIAdapter    -> https://api.openai.com/v1/chat/completions (response_format json_schema)
- AnthropicAdapter -> https://api.anthropic.com/v1/messages (tool-use forzato per JSON garantito)
- GeminiAdapter    -> generativelanguage.googleapis.com generateContent (responseSchema nativo)
- RequestyAdapter  -> avvolge integrations/requesty_gateway.py (gia' reale, invariato)

Stesso stile sanificato di integrations/meta/ e integrations/requesty_gateway.py:
- ogni eccezione di trasporto/HTTP viene rimappata in LLMGatewayError (codice
  stabile + messaggio senza mai un traceback grezzo, una URL con query string
  o un frammento di credenziale);
- timeout di CONNESSIONE (richiesta mai inviata) -> codice 'rete', sicuro
  riprovare (con un provider diverso, mai lo stesso identico tentativo);
- timeout di LETTURA (richiesta inviata, risposta mai arrivata) -> codice
  'esito_incerto', MAI ritentato automaticamente sullo stesso provider (il
  chiamante puo' comunque provare un provider diverso: e' un servizio/account
  diverso, non un secondo tentativo della stessa chiamata incerta);
- nessun retry interno a un adapter, in nessun caso: il retry/fallback fra
  provider e' deciso solo dall'orchestratore (llm_understanding.py)."""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class LLMGatewayError(Exception):
    """Codice stabile ('non_configurato', 'autenticazione', 'modello_non_disponibile',
    'rete', 'limite_frequenza', 'permesso_negato', 'esito_incerto', 'errore_api',
    'risposta_non_valida', 'errore_sconosciuto') + messaggio sanificato + provider."""

    def __init__(self, codice: str, messaggio: str, provider: str):
        self.codice = codice
        self.messaggio = messaggio
        self.provider = provider
        super().__init__(messaggio)


@dataclass
class LLMResult:
    testo: str                       # JSON grezzo restituito dal provider (non ancora validato)
    provider: str
    modello_effettivo: Optional[str]
    latenza_ms: int
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    troncata: bool


class LLMProviderAdapter(ABC):
    provider_id: str = "sconosciuto"

    @abstractmethod
    def genera_json(
        self, *, api_key: Optional[str], model: str, system: str, messaggio_utente: str,
        schema_json: dict, schema_nome: str, max_tokens: int, timeout: float,
        base_url: Optional[str] = None,
    ) -> LLMResult:
        ...


def _richiede_credenziale(api_key: Optional[str], provider: str) -> None:
    if not api_key or not api_key.strip():
        raise LLMGatewayError("non_configurato", f"Nessuna credenziale {provider} configurata.", provider)


# ==================== OpenAI (e 'openai_compatible': stesso protocollo, base_url configurabile) ====================
class OpenAIAdapter(LLMProviderAdapter):
    provider_id = "openai"
    BASE_URL = "https://api.openai.com/v1/chat/completions"

    def genera_json(self, *, api_key, model, system, messaggio_utente, schema_json, schema_nome,
                     max_tokens, timeout, base_url: Optional[str] = None) -> LLMResult:
        _richiede_credenziale(api_key, self.provider_id)
        import requests

        url = (base_url or "").strip() or self.BASE_URL
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": messaggio_utente}],
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_nome, "schema": schema_json, "strict": False},
            },
        }
        inizio = time.monotonic()
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        except requests.exceptions.ConnectTimeout as exc:
            raise LLMGatewayError("rete", "Impossibile connettersi a OpenAI entro il timeout previsto (richiesta mai inviata).", self.provider_id) from exc
        except requests.exceptions.ReadTimeout as exc:
            raise LLMGatewayError("esito_incerto", "Richiesta inviata a OpenAI ma nessuna risposta entro il timeout: esito non noto, non ritentare automaticamente.", self.provider_id) from exc
        except requests.exceptions.ConnectionError as exc:
            raise LLMGatewayError("rete", "Impossibile raggiungere OpenAI (errore di rete, richiesta mai inviata).", self.provider_id) from exc
        except Exception as exc:
            raise LLMGatewayError("errore_sconosciuto", "Errore imprevisto durante la chiamata a OpenAI.", self.provider_id) from exc
        latenza_ms = int((time.monotonic() - inizio) * 1000)
        _solleva_su_status_http(resp.status_code, self.provider_id, model)

        try:
            dati = resp.json()
        except ValueError as exc:
            raise LLMGatewayError("risposta_non_valida", "Risposta OpenAI non e' un JSON valido.", self.provider_id) from exc
        scelte = dati.get("choices") or []
        messaggio = (scelte[0].get("message") or {}) if scelte else {}
        testo = messaggio.get("content")
        if not testo:
            raise LLMGatewayError("risposta_non_valida", "Risposta OpenAI priva di contenuto testuale.", self.provider_id)
        troncata = (scelte[0].get("finish_reason") == "length") if scelte else False
        uso = dati.get("usage") or {}
        return LLMResult(
            testo=testo, provider=self.provider_id, modello_effettivo=dati.get("model"),
            latenza_ms=latenza_ms, input_tokens=uso.get("prompt_tokens"),
            output_tokens=uso.get("completion_tokens"), troncata=troncata,
        )


# ==================== Anthropic ====================
class AnthropicAdapter(LLMProviderAdapter):
    provider_id = "anthropic"
    BASE_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def genera_json(self, *, api_key, model, system, messaggio_utente, schema_json, schema_nome,
                     max_tokens, timeout, base_url: Optional[str] = None) -> LLMResult:
        _richiede_credenziale(api_key, self.provider_id)
        import requests

        headers = {
            "x-api-key": api_key, "anthropic-version": self.API_VERSION, "Content-Type": "application/json",
        }
        # Tool-use forzato: il MECCANISMO reale e documentato di Anthropic per
        # ottenere JSON strutturato garantito (mai un parsing euristico del
        # testo libero della risposta).
        tool = {"name": schema_nome, "description": f"Restituisce {schema_nome} in formato strutturato.", "input_schema": schema_json}
        body = {
            "model": model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": messaggio_utente}],
            "tools": [tool], "tool_choice": {"type": "tool", "name": schema_nome},
        }
        inizio = time.monotonic()
        try:
            resp = requests.post(self.BASE_URL, headers=headers, json=body, timeout=timeout)
        except requests.exceptions.ConnectTimeout as exc:
            raise LLMGatewayError("rete", "Impossibile connettersi ad Anthropic entro il timeout previsto (richiesta mai inviata).", self.provider_id) from exc
        except requests.exceptions.ReadTimeout as exc:
            raise LLMGatewayError("esito_incerto", "Richiesta inviata ad Anthropic ma nessuna risposta entro il timeout: esito non noto, non ritentare automaticamente.", self.provider_id) from exc
        except requests.exceptions.ConnectionError as exc:
            raise LLMGatewayError("rete", "Impossibile raggiungere Anthropic (errore di rete, richiesta mai inviata).", self.provider_id) from exc
        except Exception as exc:
            raise LLMGatewayError("errore_sconosciuto", "Errore imprevisto durante la chiamata ad Anthropic.", self.provider_id) from exc
        latenza_ms = int((time.monotonic() - inizio) * 1000)
        _solleva_su_status_http(resp.status_code, self.provider_id, model)

        try:
            dati = resp.json()
        except ValueError as exc:
            raise LLMGatewayError("risposta_non_valida", "Risposta Anthropic non e' un JSON valido.", self.provider_id) from exc
        contenuto = dati.get("content") or []
        blocco_tool = next((b for b in contenuto if b.get("type") == "tool_use"), None)
        if not blocco_tool:
            raise LLMGatewayError("risposta_non_valida", "Risposta Anthropic priva del blocco tool_use atteso.", self.provider_id)
        testo = json.dumps(blocco_tool.get("input") or {}, ensure_ascii=False)
        troncata = dati.get("stop_reason") == "max_tokens"
        uso = dati.get("usage") or {}
        return LLMResult(
            testo=testo, provider=self.provider_id, modello_effettivo=dati.get("model") or model,
            latenza_ms=latenza_ms, input_tokens=uso.get("input_tokens"),
            output_tokens=uso.get("output_tokens"), troncata=troncata,
        )


# ==================== Gemini ====================
def _to_gemini_schema(schema: dict) -> dict:
    """Converte un JSON Schema standard nel dialetto atteso da Gemini
    (chiavi 'type' in maiuscolo, nessun 'additionalProperties'). Ricorsivo,
    conservativo: campi non riconosciuti vengono scartati piuttosto che
    inviati (Gemini rifiuta uno schema con chiavi sconosciute)."""
    if not isinstance(schema, dict):
        return schema
    tipo = schema.get("type")
    out: dict = {}
    if isinstance(tipo, list):
        non_null = [t for t in tipo if t != "null"]
        tipo = non_null[0] if non_null else "string"
        if "null" in schema.get("type", []):
            out["nullable"] = True
    if tipo:
        out["type"] = str(tipo).upper()
    if "description" in schema:
        out["description"] = schema["description"]
    if "enum" in schema:
        out["enum"] = schema["enum"]
    if "properties" in schema:
        out["properties"] = {k: _to_gemini_schema(v) for k, v in schema["properties"].items()}
    if "items" in schema:
        out["items"] = _to_gemini_schema(schema["items"])
    if "required" in schema:
        out["required"] = schema["required"]
    return out


class GeminiAdapter(LLMProviderAdapter):
    provider_id = "gemini"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def genera_json(self, *, api_key, model, system, messaggio_utente, schema_json, schema_nome,
                     max_tokens, timeout, base_url: Optional[str] = None) -> LLMResult:
        _richiede_credenziale(api_key, self.provider_id)
        import requests

        url = self.BASE_URL.format(model=model)
        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": messaggio_utente}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens, "temperature": 0.7,
                "responseMimeType": "application/json", "responseSchema": _to_gemini_schema(schema_json),
            },
        }
        inizio = time.monotonic()
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        except requests.exceptions.ConnectTimeout as exc:
            raise LLMGatewayError("rete", "Impossibile connettersi a Gemini entro il timeout previsto (richiesta mai inviata).", self.provider_id) from exc
        except requests.exceptions.ReadTimeout as exc:
            raise LLMGatewayError("esito_incerto", "Richiesta inviata a Gemini ma nessuna risposta entro il timeout: esito non noto, non ritentare automaticamente.", self.provider_id) from exc
        except requests.exceptions.ConnectionError as exc:
            raise LLMGatewayError("rete", "Impossibile raggiungere Gemini (errore di rete, richiesta mai inviata).", self.provider_id) from exc
        except Exception as exc:
            raise LLMGatewayError("errore_sconosciuto", "Errore imprevisto durante la chiamata a Gemini.", self.provider_id) from exc
        latenza_ms = int((time.monotonic() - inizio) * 1000)
        _solleva_su_status_http(resp.status_code, self.provider_id, model)

        try:
            dati = resp.json()
        except ValueError as exc:
            raise LLMGatewayError("risposta_non_valida", "Risposta Gemini non e' un JSON valido.", self.provider_id) from exc
        candidati = dati.get("candidates") or []
        if not candidati:
            raise LLMGatewayError("risposta_non_valida", "Risposta Gemini priva di candidati.", self.provider_id)
        parts = (candidati[0].get("content") or {}).get("parts") or []
        testo = "".join(p.get("text", "") for p in parts)
        if not testo:
            raise LLMGatewayError("risposta_non_valida", "Risposta Gemini priva di contenuto testuale.", self.provider_id)
        troncata = candidati[0].get("finishReason") == "MAX_TOKENS"
        uso = dati.get("usageMetadata") or {}
        return LLMResult(
            testo=testo, provider=self.provider_id, modello_effettivo=model,
            latenza_ms=latenza_ms, input_tokens=uso.get("promptTokenCount"),
            output_tokens=uso.get("candidatesTokenCount"), troncata=troncata,
        )


# ==================== Requesty (gia' reale, solo adattato al contratto comune) ====================
class RequestyAdapter(LLMProviderAdapter):
    provider_id = "requesty"

    def genera_json(self, *, api_key, model, system, messaggio_utente, schema_json, schema_nome,
                     max_tokens, timeout, base_url: Optional[str] = None) -> LLMResult:
        # Requesty non prende la credenziale come parametro: legge dal
        # Credential Manager di Windows tramite requesty_gateway._client()
        # (invariato, vedi integrations/requesty_secrets.py). api_key qui e'
        # ignorato di proposito, mai duplicato in un secondo posto.
        from ..integrations import requesty_gateway
        from ..integrations.requesty_gateway import RequestyErroreSanificato, RequestyNonConfigurato

        try:
            r = requesty_gateway.genera_json(
                model_id_requesty=model, system=system, messaggio_utente=messaggio_utente,
                schema_json=schema_json, schema_nome=schema_nome, max_tokens=max_tokens, timeout=timeout,
            )
        except RequestyNonConfigurato as exc:
            raise LLMGatewayError("non_configurato", str(exc), self.provider_id) from exc
        except RequestyErroreSanificato as exc:
            raise LLMGatewayError(exc.codice, exc.messaggio, self.provider_id) from exc
        return LLMResult(
            testo=r.testo, provider=self.provider_id, modello_effettivo=r.modello_effettivo,
            latenza_ms=r.latenza_ms, input_tokens=r.input_tokens, output_tokens=r.output_tokens,
            troncata=r.troncata,
        )


def _solleva_su_status_http(status_code: int, provider: str, model: str) -> None:
    if status_code == 200:
        return
    if status_code == 401:
        raise LLMGatewayError("autenticazione", f"Credenziale {provider} non valida o rifiutata.", provider)
    if status_code == 403:
        raise LLMGatewayError("permesso_negato", f"Permesso negato da {provider} (credito esaurito o accesso non consentito).", provider)
    if status_code == 404:
        raise LLMGatewayError("modello_non_disponibile", f"Modello '{model}' non risulta disponibile su {provider}.", provider)
    if status_code == 429:
        raise LLMGatewayError("limite_frequenza", f"Limite di frequenza {provider} raggiunto.", provider)
    if status_code >= 500:
        raise LLMGatewayError("errore_api", f"Errore {provider} (status {status_code}).", provider)
    raise LLMGatewayError("errore_api", f"Errore {provider} (status {status_code}).", provider)


_OPENAI_ADAPTER = OpenAIAdapter()

ADAPTERS: dict[str, LLMProviderAdapter] = {
    "openai": _OPENAI_ADAPTER,
    # Stesso protocollo di OpenAI (chat/completions), solo un base_url diverso
    # (endpoint self-hosted/compatibile): nessun secondo adapter duplicato.
    "openai_compatible": _OPENAI_ADAPTER,
    "anthropic": AnthropicAdapter(),
    "gemini": GeminiAdapter(),
    "requesty": RequestyAdapter(),
}


def get_adapter(provider_type: str) -> Optional[LLMProviderAdapter]:
    return ADAPTERS.get((provider_type or "").strip().lower())


_SCHEMA_TEST_DIAGNOSTICO = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
_PROMPT_TEST_DIAGNOSTICO = "Rispondi esclusivamente con il JSON richiesto: {\"ok\": true}."
MAX_TOKENS_TEST_DIAGNOSTICO = 20
TIMEOUT_TEST_DIAGNOSTICO_SECONDI = 20.0


def diagnostic_test(provider_type: str, api_key: Optional[str], model: str,
                     base_url: Optional[str] = None, timeout: float = TIMEOUT_TEST_DIAGNOSTICO_SECONDI) -> dict:
    """Smoke test manuale generico per QUALUNQUE provider registrato: UNA
    sola chiamata reale a costo minimo, mai automatica (va invocata solo da
    un endpoint che ha gia' richiesto conferma esplicita — vedi
    domains/connections.py::test_real). Stessa forma di ritorno di
    integrations/requesty_gateway.py::RisultatoTestRequesty.come_dict(), cosi'
    il chiamante non deve distinguere il provider nella risposta HTTP."""
    inizio = time.monotonic()
    adapter = get_adapter(provider_type)
    if adapter is None:
        return {"esito": "ERRORE", "codice_errore": "provider_sconosciuto",
                "messaggio": f"Nessun adapter registrato per '{provider_type}'.",
                "modello_effettivo": None, "latenza_ms": None, "input_tokens": None, "output_tokens": None}
    try:
        r = adapter.genera_json(
            api_key=api_key, model=model, system="Rispondi solo con JSON valido.",
            messaggio_utente=_PROMPT_TEST_DIAGNOSTICO, schema_json=_SCHEMA_TEST_DIAGNOSTICO,
            schema_nome="diagnostic_test", max_tokens=MAX_TOKENS_TEST_DIAGNOSTICO, timeout=timeout,
            base_url=base_url,
        )
    except LLMGatewayError as exc:
        return {"esito": "ERRORE", "codice_errore": exc.codice, "messaggio": exc.messaggio,
                "modello_effettivo": None, "latenza_ms": int((time.monotonic() - inizio) * 1000),
                "input_tokens": None, "output_tokens": None}
    return {
        "esito": "OK", "codice_errore": None, "messaggio": "Connessione riuscita.",
        "modello_effettivo": r.modello_effettivo, "latenza_ms": r.latenza_ms,
        "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
    }
