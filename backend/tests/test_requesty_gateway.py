"""Gateway Requesty: mappatura errori sanificata e generazione JSON. Nessuna
chiamata di rete reale: _client() e' sempre sostituito da un doppio di test."""
import json
import types

import httpx
import openai
import pytest

from app.integrations import requesty_gateway as gw


def _req():
    return httpx.Request("POST", "https://router.requesty.ai/v1/chat/completions")


def _resp(status=400):
    return httpx.Response(status, request=_req())


class FakeCompletions:
    def __init__(self, behavior):
        self._behavior = behavior

    def create(self, **kwargs):
        return self._behavior(**kwargs)


class FakeChat:
    def __init__(self, behavior):
        self.completions = FakeCompletions(behavior)


class FakeClient:
    def __init__(self, behavior):
        self.chat = FakeChat(behavior)


def _patch_client(monkeypatch, behavior):
    monkeypatch.setattr(gw, "_client", lambda timeout: (FakeClient(behavior), openai))


def _fake_choice(content, finish_reason="stop"):
    return types.SimpleNamespace(
        message=types.SimpleNamespace(content=content),
        finish_reason=finish_reason,
    )


def _fake_response(content, model="anthropic/claude-sonnet-4-5", prompt_tokens=12, completion_tokens=4, finish_reason="stop"):
    return types.SimpleNamespace(
        choices=[_fake_choice(content, finish_reason)],
        model=model,
        usage=types.SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


# ---------------- test_diagnostico ----------------
def test_credenziale_assente(monkeypatch):
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: None)
    r = gw.test_diagnostico("anthropic/claude-sonnet-4-5")
    assert r.esito == "ERRORE"
    assert r.codice_errore == "credenziale_assente"


def test_diagnostico_ok(monkeypatch):
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: "fake-key")
    _patch_client(monkeypatch, lambda **kw: _fake_response("OK"))
    r = gw.test_diagnostico("anthropic/claude-sonnet-4-5")
    assert r.esito == "OK"
    assert r.codice_errore is None
    assert r.modello_effettivo == "anthropic/claude-sonnet-4-5"
    assert r.input_tokens == 12 and r.output_tokens == 4


def test_diagnostico_risposta_vuota(monkeypatch):
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: "fake-key")
    _patch_client(monkeypatch, lambda **kw: _fake_response(None))
    r = gw.test_diagnostico("m")
    assert r.esito == "ERRORE"
    assert r.codice_errore == "risposta_non_valida"


@pytest.mark.parametrize("exc_factory,codice_atteso", [
    (lambda: openai.AuthenticationError("bad key", response=_resp(401), body=None), "autenticazione"),
    (lambda: openai.NotFoundError("no model", response=_resp(404), body=None), "modello_non_disponibile"),
    (lambda: openai.RateLimitError("slow down", response=_resp(429), body=None), "limite_frequenza"),
    (lambda: openai.PermissionDeniedError("no credit", response=_resp(403), body=None), "permesso_negato"),
    (lambda: openai.APIStatusError("server error", response=_resp(500), body=None), "errore_api"),
    (lambda: openai.APIConnectionError(request=_req()), "rete"),
    (lambda: RuntimeError("boom"), "errore_sconosciuto"),
])
def test_errori_sanificati(monkeypatch, exc_factory, codice_atteso):
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: "fake-key")

    def boom(**kw):
        raise exc_factory()

    _patch_client(monkeypatch, boom)
    r = gw.test_diagnostico("m")
    assert r.esito == "ERRORE"
    assert r.codice_errore == codice_atteso


def test_timeout_connessione_e_rete(monkeypatch):
    """httpx.ConnectTimeout come causa -> richiesta MAI inviata -> 'rete'."""
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: "fake-key")

    def boom(**kw):
        try:
            raise httpx.ConnectTimeout("connect timeout")
        except httpx.ConnectTimeout as cause:
            raise openai.APITimeoutError(request=_req()) from cause

    _patch_client(monkeypatch, boom)
    r = gw.test_diagnostico("m")
    assert r.codice_errore == "rete"


def test_timeout_risposta_esito_incerto(monkeypatch):
    """Timeout NON di connessione -> richiesta gia' inviata -> 'esito_incerto', mai
    trattato come un banale errore di rete riprovabile."""
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: "fake-key")

    def boom(**kw):
        try:
            raise httpx.ReadTimeout("read timeout")
        except httpx.ReadTimeout as cause:
            raise openai.APITimeoutError(request=_req()) from cause

    _patch_client(monkeypatch, boom)
    r = gw.test_diagnostico("m")
    assert r.codice_errore == "esito_incerto"


# ---------------- genera_json ----------------
def test_genera_json_ok(monkeypatch):
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: "fake-key")
    payload = json.dumps({"concept": "x"})
    _patch_client(monkeypatch, lambda **kw: _fake_response(payload))
    r = gw.genera_json(
        model_id_requesty="m", system="sys", messaggio_utente="user",
        schema_json={"type": "object"}, schema_nome="s", max_tokens=100,
    )
    assert r.testo == payload
    assert r.troncata is False
    assert r.input_tokens == 12 and r.output_tokens == 4


def test_genera_json_troncata(monkeypatch):
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: "fake-key")
    _patch_client(monkeypatch, lambda **kw: _fake_response("{incomplet", finish_reason="length"))
    r = gw.genera_json(
        model_id_requesty="m", system="sys", messaggio_utente="user",
        schema_json={"type": "object"}, schema_nome="s", max_tokens=100,
    )
    assert r.troncata is True


def test_genera_json_esito_incerto_si_propaga(monkeypatch):
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: "fake-key")

    def boom(**kw):
        try:
            raise httpx.ReadTimeout("read timeout")
        except httpx.ReadTimeout as cause:
            raise openai.APITimeoutError(request=_req()) from cause

    _patch_client(monkeypatch, boom)
    with pytest.raises(gw.RequestyErroreSanificato) as ei:
        gw.genera_json(
            model_id_requesty="m", system="sys", messaggio_utente="user",
            schema_json={"type": "object"}, schema_nome="s", max_tokens=100,
        )
    assert ei.value.codice == "esito_incerto"
