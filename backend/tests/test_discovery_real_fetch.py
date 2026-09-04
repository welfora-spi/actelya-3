"""Discovery / Research Service — test per l'estrazione reale OPZIONALE
del sito dichiarato (item 3/9/13, CEO Agent 100% reale): domains/discovery.py.
Protezione SSRF rafforzata (schema, TLD interni, risoluzione DNS reale con
verifica IPv4/IPv6 pubblico, redirect seguiti manualmente con la STESSA
verifica ripetuta a ogni hop, content-type HTML, dimensione limitata in
streaming), estrazione di titolo/meta description/H1/testo essenziale/
prodotti-servizi candidati/link social, provenienza puntuale sul Fact
Ledger. La stima simulata di tono/pubblico resta INVARIATA (vedi
test_tenant_knowledge_discovery.py, non toccato): questo blocco e'
puramente additivo, gated dall'interruttore globale REAL_EXTERNAL_ACTIONS
(brain/config.py), e degrada sempre a None (mai un'eccezione) per
qualunque condizione mancante o errore di rete/DNS/redirect/content-type."""
import asyncio
import socket
import uuid

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

from app import audit as audit_mod
from app.domains import discovery


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


def run(coro):
    return asyncio.run(coro)


def _get_mai_chiamato(*args, **kwargs):
    raise AssertionError("requests.get non deve mai essere chiamato quando il gate e' chiuso o l'host non e' pubblico/risolvibile.")


# socket.getaddrinfo va sostituito con cura: e' usato ANCHE da Motor per
# risolvere 'localhost' verso MongoDB in questi stessi test (su un thread
# executor). Ogni doppio di test qui sotto e' quindi SELETTIVO sull'host
# richiesto: intercetta solo i domini di test, delega 'localhost'/tutto il
# resto alla risoluzione reale — altrimenti un patch globale indiscriminato
# romperebbe la connessione Mongo del test stesso (osservato: ServerSelectionTimeoutError).
_getaddrinfo_reale = socket.getaddrinfo


def _dns_pubblico(host, *a, **kw):
    if host == "localhost":
        return _getaddrinfo_reale(host, *a, **kw)
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def _dns_privato(host, *a, **kw):
    if host == "localhost":
        return _getaddrinfo_reale(host, *a, **kw)
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]


def _dns_fallisce(host, *a, **kw):
    if host == "localhost":
        return _getaddrinfo_reale(host, *a, **kw)
    raise socket.gaierror("nome non risolvibile")


class _FakeResponse:
    def __init__(self, status_code=200, headers=None, body=b"", location=None):
        self.status_code = status_code
        self.headers = headers or {}
        if location:
            self.headers["Location"] = location
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        self.closed = True


# ---------------- _ip_pubblico ----------------
@pytest.mark.parametrize("ip,atteso", [
    ("93.184.216.34", True), ("8.8.8.8", True),
    ("127.0.0.1", False), ("10.0.0.5", False), ("192.168.1.10", False),
    ("172.16.0.1", False), ("172.31.255.255", False), ("172.32.0.1", True),
    ("169.254.1.1", False), ("0.0.0.0", False), ("224.0.0.1", False),
    ("::1", False), ("fe80::1", False), ("fc00::1", False), ("2001:4860:4860::8888", True),
])
def test_ip_pubblico(ip, atteso):
    assert discovery._ip_pubblico(ip) is atteso


def test_ip_non_valido_non_pubblico():
    assert discovery._ip_pubblico("non-un-ip") is False


# ---------------- _schema_e_host_validi ----------------
@pytest.mark.parametrize("url,atteso", [
    ("https://esempio-pubblico.it", True), ("http://esempio-pubblico.it/pagina", True),
    ("ftp://esempio.it", False), ("http://localhost", False), ("http://localhost:8000", False),
    ("http://mio-servizio.local", False), ("http://mio-servizio.internal", False),
    ("http://mio-servizio.test", False), ("http://mio-servizio.invalid", False),
])
def test_schema_e_host_validi(url, atteso):
    ok, _, _ = discovery._schema_e_host_validi(url)
    assert ok is atteso


# ---------------- _dns_pubblico / _url_pubblico_e_risolvibile ----------------
def test_dns_pubblico_true_quando_tutti_gli_indirizzi_sono_pubblici(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns_pubblico)
    assert discovery._dns_pubblico("esempio-pubblico.it", 443) is True


def test_dns_privato_false_anche_con_hostname_pubblico(monkeypatch):
    """DNS rebinding: un hostname dall'aspetto pubblico che risolve a un IP
    privato deve essere rifiutato, non solo il nome dell'host."""
    monkeypatch.setattr(socket, "getaddrinfo", _dns_privato)
    assert discovery._dns_pubblico("hostname-innocuo.it", 443) is False


def test_dns_irrisolvibile_false(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns_fallisce)
    assert discovery._dns_pubblico("dominio-inesistente.invalido", 443) is False


def test_url_pubblico_e_risolvibile_combina_schema_e_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns_pubblico)
    assert discovery._url_pubblico_e_risolvibile("https://esempio-pubblico.it") is True
    assert discovery._url_pubblico_e_risolvibile("http://localhost") is False


# ---------------- fetch_sito_reale: gate globale ----------------
def test_gate_chiuso_di_default_nessuna_chiamata(monkeypatch):
    monkeypatch.setattr(requests, "get", _get_mai_chiamato)
    assert discovery.brain_config.REAL_EXTERNAL_ACTIONS is False
    res = run(discovery.fetch_sito_reale("https://esempio-pubblico.it"))
    assert res is None


def test_gate_aperto_ma_dns_privato_nessuna_chiamata_http(monkeypatch):
    monkeypatch.setattr(discovery.brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(socket, "getaddrinfo", _dns_privato)
    monkeypatch.setattr(requests, "get", _get_mai_chiamato)
    res = run(discovery.fetch_sito_reale("http://hostname-innocuo.it"))
    assert res is None


# ---------------- successo: estrazione completa ----------------
def test_successo_estrae_titolo_meta_h1_testo_prodotti_social(monkeypatch):
    monkeypatch.setattr(discovery.brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(socket, "getaddrinfo", _dns_pubblico)

    html = """
    <html><head><title>  Bakery & Coffee - Merate  </title>
    <meta name="description" content="Panetteria artigianale a Merate">
    </head><body>
    <h1>Bakery &amp; Coffee</h1>
    <h2>Focacce artigianali</h2>
    <h2>Caffetteria</h2>
    <p>Testo introduttivo della pagina con qualche dettaglio in piu'.</p>
    <a href="https://www.instagram.com/bakerycoffee">Instagram</a>
    <a href="https://facebook.com/bakerycoffee">Facebook</a>
    </body></html>
    """.encode("utf-8")

    def _fake_get(url, timeout=None, headers=None, allow_redirects=None, stream=None):
        return _FakeResponse(200, {"Content-Type": "text/html; charset=utf-8"}, html)

    monkeypatch.setattr(requests, "get", _fake_get)
    res = run(discovery.fetch_sito_reale("bakerycoffee.it"))
    assert res is not None
    assert res["titolo"] == "Bakery & Coffee - Merate"
    assert res["meta_description"] == "Panetteria artigianale a Merate"
    assert "Bakery" in res["h1"]
    assert "Focacce artigianali" in res["prodotti_servizi_candidati"]
    assert "Caffetteria" in res["prodotti_servizi_candidati"]
    assert any("instagram.com" in s for s in res["social_links"])
    assert any("facebook.com" in s for s in res["social_links"])
    assert res["testo_essenziale"]
    assert res["url"] == "https://bakerycoffee.it"


# ---------------- redirect: seguiti manualmente, verificati a ogni hop ----------------
def test_redirect_verso_host_pubblico_seguito(monkeypatch):
    monkeypatch.setattr(discovery.brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(socket, "getaddrinfo", _dns_pubblico)

    html = b"<html><head><title>Pagina finale</title></head></html>"
    chiamate = []

    def _fake_get(url, timeout=None, headers=None, allow_redirects=None, stream=None):
        chiamate.append(url)
        if url == "https://esempio-pubblico.it":
            return _FakeResponse(302, location="https://esempio-pubblico.it/it")
        return _FakeResponse(200, {"Content-Type": "text/html"}, html)

    monkeypatch.setattr(requests, "get", _fake_get)
    res = run(discovery.fetch_sito_reale("esempio-pubblico.it"))
    assert res is not None
    assert res["titolo"] == "Pagina finale"
    assert len(chiamate) == 2


def test_redirect_verso_rete_privata_bloccato(monkeypatch):
    """Un redirect verso un IP/host privato deve essere rifiutato ANCHE se
    l'URL iniziale era pubblico e risolvibile: la verifica si ripete a
    ogni hop, mai solo sul primo."""
    monkeypatch.setattr(discovery.brain_config, "REAL_EXTERNAL_ACTIONS", True)

    def _dns_dinamico(host, porta, **kw):
        if host == "esempio-pubblico.it":
            return _dns_pubblico(host, porta, **kw)
        return _dns_privato(host, porta, **kw)  # il dominio di destinazione del redirect risolve a IP privato

    monkeypatch.setattr(socket, "getaddrinfo", _dns_dinamico)

    def _fake_get(url, timeout=None, headers=None, allow_redirects=None, stream=None):
        assert url == "https://esempio-pubblico.it"
        return _FakeResponse(302, location="http://servizio-interno.it/segreto")

    monkeypatch.setattr(requests, "get", _fake_get)
    res = run(discovery.fetch_sito_reale("esempio-pubblico.it"))
    assert res is None


def test_troppi_redirect_annullato(monkeypatch):
    monkeypatch.setattr(discovery.brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(socket, "getaddrinfo", _dns_pubblico)

    contatore = {"n": 0}

    def _fake_get(url, timeout=None, headers=None, allow_redirects=None, stream=None):
        contatore["n"] += 1
        return _FakeResponse(302, location=f"https://esempio-pubblico.it/hop{contatore['n']}")

    monkeypatch.setattr(requests, "get", _fake_get)
    res = run(discovery.fetch_sito_reale("esempio-pubblico.it"))
    assert res is None
    assert contatore["n"] == discovery.MAX_REDIRECT + 1


# ---------------- content-type non ammesso ----------------
def test_content_type_non_html_scartato(monkeypatch):
    monkeypatch.setattr(discovery.brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(socket, "getaddrinfo", _dns_pubblico)

    def _fake_get(url, timeout=None, headers=None, allow_redirects=None, stream=None):
        return _FakeResponse(200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 ...")

    monkeypatch.setattr(requests, "get", _fake_get)
    res = run(discovery.fetch_sito_reale("esempio-pubblico.it"))
    assert res is None


# ---------------- dimensione limitata in streaming ----------------
def test_dimensione_troncata_al_limite(monkeypatch):
    monkeypatch.setattr(discovery.brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(socket, "getaddrinfo", _dns_pubblico)
    monkeypatch.setattr(discovery, "REAL_FETCH_MAX_BYTES", 100)

    corpo_grande = b"<html><head><title>Titolo</title></head><body>" + (b"x" * 5000) + b"</body></html>"

    def _fake_get(url, timeout=None, headers=None, allow_redirects=None, stream=None):
        return _FakeResponse(200, {"Content-Type": "text/html"}, corpo_grande)

    monkeypatch.setattr(requests, "get", _fake_get)
    res = run(discovery.fetch_sito_reale("esempio-pubblico.it"))
    # Il titolo e' entro i primi 100 byte -> ancora estraibile; il corpo
    # scaricato resta comunque troncato al limite configurato.
    assert res is not None
    assert res["titolo"] == "Titolo"


# ---------------- errori di rete: sempre degradati a None ----------------
def test_errore_di_rete_degrada_a_none(monkeypatch):
    monkeypatch.setattr(discovery.brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(socket, "getaddrinfo", _dns_pubblico)

    def _raise(*a, **kw):
        raise requests.exceptions.ConnectTimeout("timeout simulato")

    monkeypatch.setattr(requests, "get", _raise)
    res = run(discovery.fetch_sito_reale("esempio-pubblico.it"))
    assert res is None


def test_pagina_senza_contenuto_utile_ritorna_none(monkeypatch):
    monkeypatch.setattr(discovery.brain_config, "REAL_EXTERNAL_ACTIONS", True)
    monkeypatch.setattr(socket, "getaddrinfo", _dns_pubblico)

    def _fake_get(url, timeout=None, headers=None, allow_redirects=None, stream=None):
        return _FakeResponse(200, {"Content-Type": "text/html"}, b"<html></html>")

    monkeypatch.setattr(requests, "get", _fake_get)
    res = run(discovery.fetch_sito_reale("esempio-pubblico.it"))
    assert res is None


# ---------------- integrazione in process_run: provenienza sul Fact Ledger ----------------
def test_process_run_con_gate_chiuso_non_scrive_real_fetch(monkeypatch):
    async def scenario():
        client, fresh_db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        monkeypatch.setattr(discovery, "db", fresh_db)
        monkeypatch.setattr(audit_mod, "db", fresh_db)
        monkeypatch.setattr(requests, "get", _get_mai_chiamato)
        try:
            run_rec = discovery.base_record(org, "user-test")
            run_rec.update({
                "id": discovery.new_id("disco"), "status": "IN_CODA", "mode": "SIMULATO",
                "target_website": "https://esempio-pubblico.it", "target_social": [],
                "started_at": None, "finished_at": None, "facts_written": [], "warnings": [],
                "real_fetch": None,
            })
            await fresh_db.discovery_runs.insert_one(run_rec)
            await discovery.process_run(run_rec)
            persisted = await fresh_db.discovery_runs.find_one({"id": run_rec["id"]}, {"_id": 0})
            assert persisted["status"] == "COMPLETATO"
            assert persisted["real_fetch"] is None
            assert persisted["mode"] == "SIMULATO"
            return True
        finally:
            await fresh_db.discovery_runs.delete_many({"organization_id": org})
            await fresh_db.facts.delete_many({"organization_id": org})
            client.close()

    assert run(scenario())


def test_process_run_con_gate_aperto_scrive_fatti_con_provenienza_puntuale(monkeypatch):
    async def scenario():
        client, fresh_db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        monkeypatch.setattr(discovery, "db", fresh_db)
        monkeypatch.setattr(audit_mod, "db", fresh_db)
        monkeypatch.setattr(discovery.brain_config, "REAL_EXTERNAL_ACTIONS", True)
        monkeypatch.setattr(socket, "getaddrinfo", _dns_pubblico)

        html = (
            "<html><head><title>Esempio Pubblico</title>"
            '<meta name="description" content="Descrizione reale di test">'
            "</head><body><h1>Titolo H1</h1><h2>Servizio A</h2>"
            '<a href="https://instagram.com/esempio">ig</a></body></html>'
        ).encode("utf-8")

        def _fake_get(url, timeout=None, headers=None, allow_redirects=None, stream=None):
            return _FakeResponse(200, {"Content-Type": "text/html"}, html)

        monkeypatch.setattr(requests, "get", _fake_get)
        try:
            run_rec = discovery.base_record(org, "user-test")
            run_rec.update({
                "id": discovery.new_id("disco"), "status": "IN_CODA", "mode": "SIMULATO",
                "target_website": "https://esempio-pubblico.it", "target_social": [],
                "started_at": None, "finished_at": None, "facts_written": [], "warnings": [],
                "real_fetch": None,
            })
            await fresh_db.discovery_runs.insert_one(run_rec)
            await discovery.process_run(run_rec)
            persisted = await fresh_db.discovery_runs.find_one({"id": run_rec["id"]}, {"_id": 0})
            assert persisted["status"] == "COMPLETATO"
            assert persisted["real_fetch"]["titolo"] == "Esempio Pubblico"
            assert persisted["real_fetch"]["h1"] == "Titolo H1"

            facts = await fresh_db.facts.find({"organization_id": org}, {"_id": 0}).to_list(50)
            titolo_fact = next((f for f in facts if f["field"] == "titolo_sito_estratto"), None)
            assert titolo_fact is not None
            assert titolo_fact["source"] == "https://esempio-pubblico.it"  # provenienza puntuale: l'URL reale
            assert titolo_fact["method"] == "ESTRATTO"

            prodotti_fact = next((f for f in facts if f["field"] == "prodotti_servizi_candidati"), None)
            assert prodotti_fact is not None
            assert prodotti_fact["confidence"] < 0.5  # inferenza euristica, mai presentata come certa
            assert "Servizio A" in prodotti_fact["value"]

            social_fact = next((f for f in facts if f["field"] == "social_links_estratti"), None)
            assert social_fact is not None
            assert "instagram.com" in social_fact["value"]
            return True
        finally:
            await fresh_db.discovery_runs.delete_many({"organization_id": org})
            await fresh_db.facts.delete_many({"organization_id": org})
            client.close()

    assert run(scenario())
