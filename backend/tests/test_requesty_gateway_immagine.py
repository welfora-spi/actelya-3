"""Gateway Requesty — generazione immagine (POST /v1/images/generations,
confermato reale su docs.requesty.ai). Nessuna chiamata di rete: _client()
sempre sostituito da un doppio di test, stesso pattern di
test_requesty_gateway.py."""
import types

import openai
import pytest

from app.integrations import requesty_gateway as gw


class FakeImages:
    def __init__(self, behavior):
        self._behavior = behavior

    def generate(self, **kwargs):
        return self._behavior(**kwargs)


class FakeClient:
    def __init__(self, behavior):
        self.images = FakeImages(behavior)


def _patch_client(monkeypatch, behavior):
    monkeypatch.setattr(gw, "_client", lambda timeout: (FakeClient(behavior), openai))


def _fake_image_response(url="https://cdn.requesty.example/img123.png"):
    return types.SimpleNamespace(data=[types.SimpleNamespace(url=url, b64_json=None)])


def test_genera_immagine_ok(monkeypatch):
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: "fake-key")
    _patch_client(monkeypatch, lambda **kw: _fake_image_response())
    r = gw.genera_immagine("azure/openai/gpt-image-1", "a vertical flyer, clean modern style")
    assert r.url == "https://cdn.requesty.example/img123.png"
    assert r.modello_effettivo == "azure/openai/gpt-image-1"


def test_genera_immagine_risposta_vuota(monkeypatch):
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: "fake-key")
    _patch_client(monkeypatch, lambda **kw: types.SimpleNamespace(data=[]))
    with pytest.raises(gw.RequestyErroreSanificato) as ei:
        gw.genera_immagine("azure/openai/gpt-image-1", "prompt")
    assert ei.value.codice == "risposta_non_valida"


def test_genera_immagine_credenziale_assente(monkeypatch):
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: None)
    with pytest.raises(gw.RequestyNonConfigurato):
        gw.genera_immagine("azure/openai/gpt-image-1", "prompt")


@pytest.mark.parametrize("exc_factory,codice_atteso", [
    (lambda: openai.PermissionDeniedError("no credit", response=__import__("httpx").Response(403, request=__import__("httpx").Request("POST", "https://router.requesty.ai/v1/images/generations")), body=None), "permesso_negato"),
    (lambda: openai.RateLimitError("slow down", response=__import__("httpx").Response(429, request=__import__("httpx").Request("POST", "https://router.requesty.ai/v1/images/generations")), body=None), "limite_frequenza"),
])
def test_genera_immagine_errori_sanificati(monkeypatch, exc_factory, codice_atteso):
    monkeypatch.setattr(gw, "leggi_api_key_requesty", lambda: "fake-key")

    def boom(**kw):
        raise exc_factory()

    _patch_client(monkeypatch, boom)
    with pytest.raises(gw.RequestyErroreSanificato) as ei:
        gw.genera_immagine("azure/openai/gpt-image-1", "prompt")
    assert ei.value.codice == codice_atteso
