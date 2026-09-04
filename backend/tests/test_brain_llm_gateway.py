"""Brain — test del gateway LLM multi-provider (CEO Agent 100% reale, blocco 2):
i quattro adapter reali (OpenAI, Anthropic, Gemini via HTTP diretto con
`requests`; Requesty tramite il gateway gia' esistente), copertura di
successo/autenticazione/permesso negato/limite di frequenza/timeout di
connessione (mai inviata, 'rete')/timeout di lettura (inviata, esito
incerto, MAI ritentato)/JSON non valido/contenuto mancante, per ciascun
provider. Trasporto SEMPRE mockato: nessuna chiamata di rete reale."""
import json
import types

import pytest
import requests

from app.brain.llm_gateway import (
    AnthropicAdapter,
    GeminiAdapter,
    LLMGatewayError,
    OpenAIAdapter,
    RequestyAdapter,
    _to_gemini_schema,
    get_adapter,
)

SCHEMA = {"type": "object", "properties": {"intent": {"type": ["string", "null"]}}, "required": ["intent"]}


def _resp(status_code, json_body=None, raise_json_error=False):
    r = types.SimpleNamespace()
    r.status_code = status_code
    if raise_json_error:
        def _raise():
            raise ValueError("not json")
        r.json = _raise
    else:
        r.json = lambda: json_body
    return r


# ==================== registry ====================
def test_get_adapter_provider_noto_e_sconosciuto():
    assert isinstance(get_adapter("openai"), OpenAIAdapter)
    assert isinstance(get_adapter("anthropic"), AnthropicAdapter)
    assert isinstance(get_adapter("gemini"), GeminiAdapter)
    assert isinstance(get_adapter("requesty"), RequestyAdapter)
    assert get_adapter("provider-inesistente") is None
    assert get_adapter("") is None


def test_credenziale_assente_mai_una_chiamata_di_rete(monkeypatch):
    def _mai_chiamato(*a, **kw):
        raise AssertionError("nessuna richiesta deve partire senza credenziale")
    monkeypatch.setattr(requests, "post", _mai_chiamato)
    for adapter in (OpenAIAdapter(), AnthropicAdapter(), GeminiAdapter()):
        with pytest.raises(LLMGatewayError) as exc:
            adapter.genera_json(api_key=None, model="m", system="s", messaggio_utente="u",
                                schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
        assert exc.value.codice == "non_configurato"


# ==================== OpenAI ====================
def test_openai_successo(monkeypatch):
    body = {
        "model": "gpt-4o", "choices": [{"message": {"content": '{"intent": "x"}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _resp(200, body))
    r = OpenAIAdapter().genera_json(api_key="k", model="gpt-4o", system="s", messaggio_utente="u",
                                    schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert r.testo == '{"intent": "x"}'
    assert r.provider == "openai"
    assert r.modello_effettivo == "gpt-4o"
    assert r.input_tokens == 10 and r.output_tokens == 5
    assert r.troncata is False


def test_openai_troncata(monkeypatch):
    body = {"model": "gpt-4o", "choices": [{"message": {"content": "{}"}, "finish_reason": "length"}], "usage": {}}
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _resp(200, body))
    r = OpenAIAdapter().genera_json(api_key="k", model="gpt-4o", system="s", messaggio_utente="u",
                                    schema_json=SCHEMA, schema_nome="n", max_tokens=10, timeout=5)
    assert r.troncata is True


@pytest.mark.parametrize("status,codice_atteso", [
    (401, "autenticazione"), (403, "permesso_negato"), (404, "modello_non_disponibile"),
    (429, "limite_frequenza"), (500, "errore_api"), (503, "errore_api"),
])
def test_openai_errori_http(monkeypatch, status, codice_atteso):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _resp(status, {}))
    with pytest.raises(LLMGatewayError) as exc:
        OpenAIAdapter().genera_json(api_key="k", model="m", system="s", messaggio_utente="u",
                                    schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == codice_atteso


def test_openai_timeout_connessione_mai_inviata(monkeypatch):
    def _raise(*a, **kw):
        raise requests.exceptions.ConnectTimeout("mai connesso")
    monkeypatch.setattr(requests, "post", _raise)
    with pytest.raises(LLMGatewayError) as exc:
        OpenAIAdapter().genera_json(api_key="k", model="m", system="s", messaggio_utente="u",
                                    schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == "rete"


def test_openai_timeout_lettura_esito_incerto(monkeypatch):
    def _raise(*a, **kw):
        raise requests.exceptions.ReadTimeout("inviata, nessuna risposta")
    monkeypatch.setattr(requests, "post", _raise)
    with pytest.raises(LLMGatewayError) as exc:
        OpenAIAdapter().genera_json(api_key="k", model="m", system="s", messaggio_utente="u",
                                    schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == "esito_incerto"


def test_openai_json_non_valido(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _resp(200, raise_json_error=True))
    with pytest.raises(LLMGatewayError) as exc:
        OpenAIAdapter().genera_json(api_key="k", model="m", system="s", messaggio_utente="u",
                                    schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == "risposta_non_valida"


def test_openai_contenuto_mancante(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _resp(200, {"choices": []}))
    with pytest.raises(LLMGatewayError) as exc:
        OpenAIAdapter().genera_json(api_key="k", model="m", system="s", messaggio_utente="u",
                                    schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == "risposta_non_valida"


# ==================== Anthropic ====================
def test_anthropic_successo_tool_use(monkeypatch):
    body = {
        "model": "claude-x", "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "name": "n", "input": {"intent": "x"}}],
        "usage": {"input_tokens": 8, "output_tokens": 3},
    }
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _resp(200, body))
    r = AnthropicAdapter().genera_json(api_key="k", model="claude-x", system="s", messaggio_utente="u",
                                       schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert json.loads(r.testo) == {"intent": "x"}
    assert r.provider == "anthropic"
    assert r.input_tokens == 8 and r.output_tokens == 3


def test_anthropic_senza_tool_use_risposta_non_valida(monkeypatch):
    body = {"model": "claude-x", "content": [{"type": "text", "text": "non strutturato"}], "usage": {}}
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _resp(200, body))
    with pytest.raises(LLMGatewayError) as exc:
        AnthropicAdapter().genera_json(api_key="k", model="claude-x", system="s", messaggio_utente="u",
                                       schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == "risposta_non_valida"


@pytest.mark.parametrize("status,codice_atteso", [
    (401, "autenticazione"), (403, "permesso_negato"), (429, "limite_frequenza"), (500, "errore_api"),
])
def test_anthropic_errori_http(monkeypatch, status, codice_atteso):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _resp(status, {}))
    with pytest.raises(LLMGatewayError) as exc:
        AnthropicAdapter().genera_json(api_key="k", model="m", system="s", messaggio_utente="u",
                                       schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == codice_atteso


def test_anthropic_timeout_lettura_esito_incerto(monkeypatch):
    def _raise(*a, **kw):
        raise requests.exceptions.ReadTimeout("inviata")
    monkeypatch.setattr(requests, "post", _raise)
    with pytest.raises(LLMGatewayError) as exc:
        AnthropicAdapter().genera_json(api_key="k", model="m", system="s", messaggio_utente="u",
                                       schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == "esito_incerto"


# ==================== Gemini ====================
def test_gemini_successo(monkeypatch):
    body = {
        "candidates": [{"content": {"parts": [{"text": '{"intent": "x"}'}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2},
    }
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _resp(200, body))
    r = GeminiAdapter().genera_json(api_key="k", model="gemini-x", system="s", messaggio_utente="u",
                                    schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert r.testo == '{"intent": "x"}'
    assert r.provider == "gemini"
    assert r.input_tokens == 4 and r.output_tokens == 2


def test_gemini_nessun_candidato(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _resp(200, {"candidates": []}))
    with pytest.raises(LLMGatewayError) as exc:
        GeminiAdapter().genera_json(api_key="k", model="m", system="s", messaggio_utente="u",
                                    schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == "risposta_non_valida"


@pytest.mark.parametrize("status,codice_atteso", [
    (401, "autenticazione"), (403, "permesso_negato"), (429, "limite_frequenza"), (500, "errore_api"),
])
def test_gemini_errori_http(monkeypatch, status, codice_atteso):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _resp(status, {}))
    with pytest.raises(LLMGatewayError) as exc:
        GeminiAdapter().genera_json(api_key="k", model="m", system="s", messaggio_utente="u",
                                    schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == codice_atteso


def test_gemini_schema_converter_maiuscolo_e_nullable():
    convertito = _to_gemini_schema({
        "type": "object",
        "properties": {
            "intent": {"type": ["string", "null"]},
            "rischi": {"type": "array", "items": {"type": "object", "properties": {"categoria": {"type": "string"}}}},
        },
        "required": ["intent"],
    })
    assert convertito["type"] == "OBJECT"
    assert convertito["properties"]["intent"]["type"] == "STRING"
    assert convertito["properties"]["intent"]["nullable"] is True
    assert convertito["properties"]["rischi"]["type"] == "ARRAY"
    assert convertito["properties"]["rischi"]["items"]["type"] == "OBJECT"
    assert convertito["required"] == ["intent"]


# ==================== Requesty (wrapping del gateway esistente) ====================
def test_requesty_adapter_avvolge_il_gateway_esistente(monkeypatch):
    from app.integrations import requesty_gateway as rg

    chiamato = {}

    def _fake_genera_json(**kwargs):
        chiamato.update(kwargs)
        return rg.RisultatoGenerazioneRequesty(
            testo='{"intent": "x"}', modello_effettivo="anthropic/claude-sonnet-4-5",
            latenza_ms=42, input_tokens=7, output_tokens=3, troncata=False,
        )

    monkeypatch.setattr(rg, "genera_json", _fake_genera_json)
    r = RequestyAdapter().genera_json(api_key="ignorato-di-proposito", model="anthropic/claude-sonnet-4-5",
                                      system="s", messaggio_utente="u", schema_json=SCHEMA,
                                      schema_nome="n", max_tokens=100, timeout=5)
    assert r.provider == "requesty"
    assert r.testo == '{"intent": "x"}'
    assert chiamato["model_id_requesty"] == "anthropic/claude-sonnet-4-5"


def test_requesty_adapter_credenziale_assente(monkeypatch):
    from app.integrations import requesty_gateway as rg

    def _raise(**kwargs):
        raise rg.RequestyNonConfigurato("nessuna credenziale")

    monkeypatch.setattr(rg, "genera_json", _raise)
    with pytest.raises(LLMGatewayError) as exc:
        RequestyAdapter().genera_json(api_key=None, model="m", system="s", messaggio_utente="u",
                                      schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == "non_configurato"


def test_requesty_adapter_errore_sanificato_propagato(monkeypatch):
    from app.integrations import requesty_gateway as rg

    def _raise(**kwargs):
        raise rg.RequestyErroreSanificato("limite_frequenza", "troppo veloce")

    monkeypatch.setattr(rg, "genera_json", _raise)
    with pytest.raises(LLMGatewayError) as exc:
        RequestyAdapter().genera_json(api_key="k", model="m", system="s", messaggio_utente="u",
                                      schema_json=SCHEMA, schema_nome="n", max_tokens=100, timeout=5)
    assert exc.value.codice == "limite_frequenza"
