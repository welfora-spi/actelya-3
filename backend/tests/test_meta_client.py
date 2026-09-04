"""Meta Graph API — client HTTP di basso livello e validazione token
(item 20/21, DECISIONE UFFICIALE "100% REALE"). Trasporto HTTP SEMPRE
mockato: nessuna chiamata di rete reale in questi test (verificato anche
attivamente bloccando socket.socket, come test_brain_connector_gateway.py)."""
import socket

import pytest

from app.integrations.meta import client as C
from app.integrations.meta import auth as A
from app.integrations.meta.errors import (
    MetaAuthError, MetaConnectorError, MetaPermissionError, MetaRateLimitError, MetaTimeout,
)


class _NetworkCallAttempted(Exception):
    pass


@pytest.fixture(autouse=True)
def block_all_real_sockets(monkeypatch):
    def _blocked(*a, **kw):
        raise _NetworkCallAttempted("Tentativo di apertura socket reale bloccato nei test Meta.")
    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


class _FakeResponse:
    def __init__(self, status_code, json_body, headers=None):
        self.status_code = status_code
        self._json = json_body
        self.headers = headers or {}

    def json(self):
        return self._json


def _patch_requests(monkeypatch, fn):
    """Sostituisce requests.request con fn(method, url, **kw) -> _FakeResponse.
    graph_request() importa `requests` lazy al momento della chiamata: dato
    che e' lo STESSO modulo condiviso in sys.modules, patchare l'attributo
    globale `requests.request` intercetta anche quella import locale."""
    import requests
    monkeypatch.setattr(requests, "request", fn)


def test_richiesta_ok_ritorna_json(monkeypatch):
    def fake(method, url, **kw):
        assert kw["params"]["access_token"] == "tok-123"
        return _FakeResponse(200, {"id": "42", "name": "Bakery"})
    _patch_requests(monkeypatch, fake)
    corpo = C.graph_request("GET", "me", access_token="tok-123", params={"fields": "id,name"})
    assert corpo == {"id": "42", "name": "Bakery"}


def test_token_mai_esposto_nell_url_redatto():
    url = f"{C.GRAPH_API_BASE}/v21.0/me?fields=id&access_token=SEGRETO123&extra=1"
    redatto = C._redigi(url)
    assert "SEGRETO123" not in redatto
    assert "[REDACTED]" in redatto
    assert "extra=1" in redatto  # il resto della query string resta leggibile


def test_errore_autenticazione_non_ritentato(monkeypatch):
    chiamate = {"n": 0}
    def fake(method, url, **kw):
        chiamate["n"] += 1
        return _FakeResponse(400, {"error": {"code": 190, "message": "Token scaduto"}})
    _patch_requests(monkeypatch, fake)
    with pytest.raises(MetaAuthError):
        C.graph_request("GET", "me", access_token="tok", max_retries=2)
    assert chiamate["n"] == 1  # nessun retry per un errore di autenticazione


def test_errore_permesso_non_ritentato(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(403, {"error": {"code": 200, "message": "Permesso mancante"}})
    _patch_requests(monkeypatch, fake)
    with pytest.raises(MetaPermissionError):
        C.graph_request("POST", "123/feed", access_token="tok", max_retries=2)


def test_rate_limit_ritentato_poi_riuscito(monkeypatch):
    chiamate = {"n": 0}
    def fake(method, url, **kw):
        chiamate["n"] += 1
        if chiamate["n"] < 3:
            return _FakeResponse(429, {"error": {"code": 4, "message": "Rate limit"}})
        return _FakeResponse(200, {"id": "999"})
    _patch_requests(monkeypatch, fake)
    monkeypatch.setattr(C.time, "sleep", lambda s: None)  # niente attese reali nei test
    corpo = C.graph_request("POST", "123/feed", access_token="tok", max_retries=3)
    assert corpo == {"id": "999"}
    assert chiamate["n"] == 3


def test_rate_limit_esaurisce_i_retry(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(429, {"error": {"code": 4, "message": "Rate limit"}})
    _patch_requests(monkeypatch, fake)
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    with pytest.raises(MetaRateLimitError):
        C.graph_request("POST", "123/feed", access_token="tok", max_retries=1)


def test_5xx_ritentato(monkeypatch):
    chiamate = {"n": 0}
    def fake(method, url, **kw):
        chiamate["n"] += 1
        if chiamate["n"] == 1:
            return _FakeResponse(503, {"error": {"message": "Service unavailable"}})
        return _FakeResponse(200, {"id": "1"})
    _patch_requests(monkeypatch, fake)
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    corpo = C.graph_request("GET", "me", access_token="tok", max_retries=1)
    assert corpo == {"id": "1"}
    assert chiamate["n"] == 2


def test_timeout_solleva_meta_timeout_senza_retry_automatico(monkeypatch):
    import requests
    chiamate = {"n": 0}
    def fake(method, url, **kw):
        chiamate["n"] += 1
        raise requests.exceptions.Timeout("simulated timeout")
    _patch_requests(monkeypatch, fake)
    with pytest.raises(MetaTimeout):
        C.graph_request("POST", "123/feed", access_token="tok", max_retries=2)
    assert chiamate["n"] == 1  # esito incerto: MAI ritentato alla cieca dal client stesso


def test_errore_rete_ritentato_poi_fallisce(monkeypatch):
    import requests
    def fake(method, url, **kw):
        raise requests.exceptions.ConnectionError("simulated network error")
    _patch_requests(monkeypatch, fake)
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    with pytest.raises(MetaConnectorError):
        C.graph_request("GET", "me", access_token="tok", max_retries=1)


def test_nessun_token_fornito_bloccato_prima_della_chiamata(monkeypatch):
    chiamato = {"v": False}
    def fake(method, url, **kw):
        chiamato["v"] = True
        return _FakeResponse(200, {})
    _patch_requests(monkeypatch, fake)
    with pytest.raises(MetaAuthError):
        C.graph_request("GET", "me", access_token="")
    assert chiamato["v"] is False


# ---------------- auth.py ----------------
def test_validate_token_ok(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(200, {"id": "10", "name": "Bakery & Coffee Page"})
    _patch_requests(monkeypatch, fake)
    r = A.validate_token("tok")
    assert r.valido is True
    assert r.app_id == "10"


def test_validate_token_non_valido(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(400, {"error": {"code": 190, "message": "Token scaduto"}})
    _patch_requests(monkeypatch, fake)
    r = A.validate_token("tok-scaduto")
    assert r.valido is False


def test_verify_page_restituisce_instagram_collegato(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(200, {"id": "page1", "name": "Bakery & Coffee",
                                   "instagram_business_account": {"id": "ig1"}})
    _patch_requests(monkeypatch, fake)
    info = A.verify_page("tok", "page1")
    assert info.page_name == "Bakery & Coffee"
    assert info.instagram_business_account_id == "ig1"


def test_verify_page_senza_page_id_solleva_invalid_account():
    from app.integrations.meta.errors import MetaInvalidAccount
    with pytest.raises(MetaInvalidAccount):
        A.verify_page("tok", "")


def test_verify_instagram_account_ok(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(200, {"id": "ig1", "username": "bakerycoffee"})
    _patch_requests(monkeypatch, fake)
    info = A.verify_instagram_account("tok", "ig1")
    assert info.username == "bakerycoffee"
