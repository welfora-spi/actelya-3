"""Lead Generation — test degli adapter di ricerca prospect. Un adapter non
configurato deve SEMPRE dichiarare NON_DISPONIBILE, mai un risultato vuoto
spacciato per 'nessun prospect trovato'. Protezione SSRF verificata con DNS
mockato (mai una vera rete)."""
import asyncio
import socket
import types

import pytest
import requests

from app.domains.leadgen.research import (
    InternalDataAdapter,
    PublicUrlAdapter,
    build_adapters,
    fetch_pagina_pubblica,
)


def run(coro):
    return asyncio.run(coro)


_getaddrinfo_reale = socket.getaddrinfo


def _dns_pubblico(host, *a, **kw):
    if host == "localhost":
        return _getaddrinfo_reale(host, *a, **kw)
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def _dns_privato(host, *a, **kw):
    if host == "localhost":
        return _getaddrinfo_reale(host, *a, **kw)
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]


class _FakeResponse:
    def __init__(self, status_code=200, headers=None, body=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        pass


# ---------------- PublicUrlAdapter ----------------
def test_public_url_adapter_sempre_configurato():
    assert PublicUrlAdapter().configured is True


def test_public_url_adapter_senza_url_esplicite_non_disponibile():
    r = run(PublicUrlAdapter().search(query="hotel Nord Italia"))
    assert r.status == "NON_DISPONIBILE"
    assert "URL pubblici espliciti" in r.motivo


def test_public_url_adapter_con_url_pubblica_estrae_dati(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns_pubblico)
    html = b"<html><head><title>Hotel Alpi</title><meta name=\"description\" content=\"Hotel a Milano\"></head></html>"
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _FakeResponse(200, {"Content-Type": "text/html"}, html))
    r = run(PublicUrlAdapter().search(urls=["https://esempio-pubblico.it"]))
    assert r.status == "OK"
    assert len(r.records) == 1
    assert r.records[0]["ragione_sociale"] == "Hotel Alpi"
    assert r.records[0]["fonte"] == "https://esempio-pubblico.it"


def test_public_url_adapter_host_privato_scartato_senza_chiamata(monkeypatch):
    def _mai(*a, **kw):
        raise AssertionError("non deve mai chiamare requests.get su un host privato")
    monkeypatch.setattr(requests, "get", _mai)
    r = run(PublicUrlAdapter().search(urls=["http://localhost:9000"]))
    assert r.status == "OK"
    assert r.records == []  # nessun risultato, ma nessuna eccezione


def test_fetch_pagina_pubblica_dns_privato_ritorna_none(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns_privato)
    assert fetch_pagina_pubblica("http://esempio.it") is None


# ---------------- InternalDataAdapter ----------------
def test_internal_data_adapter_configurato_e_gestisce_db_assente():
    adapter = InternalDataAdapter(db=None, org_id="org-1")
    assert adapter.configured is True
    r = run(adapter.search())
    assert r.status == "NON_DISPONIBILE"


# ---------------- Adapter non configurati ----------------
def test_adapter_predisposti_sempre_non_disponibili():
    registro = build_adapters(db=None, org_id="org-1")
    for chiave in ("directory_pubbliche", "provider_commerciale", "crm"):
        adapter = registro[chiave]
        assert adapter.configured is False
        r = run(adapter.search(query="qualunque"))
        assert r.status == "NON_DISPONIBILE"
        assert r.records == []
        assert r.motivo


def test_build_adapters_include_tutte_le_fonti_previste():
    registro = build_adapters(db=None, org_id="org-1")
    assert set(registro.keys()) == {"web_pubblico", "dati_interni", "directory_pubbliche", "provider_commerciale", "crm"}
