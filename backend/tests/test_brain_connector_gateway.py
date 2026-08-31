"""Blocco A — test puri per backend/app/brain/gateways/connector_gateway.py.
Nessun Mongo. Nessuna rete: il socket è attivamente bloccato per tutta la
durata di questi test (fixture autouse), non solo verificato "a posteriori"."""
import ast
import importlib
import pathlib
import socket

import pytest

from app.brain import config as brain_config
from app.brain.gateways import connector_gateway as cg
from app.brain.safety.errors import AzioneEsternaBloccata, RichiestaConnettoreNonValida


class _NetworkCallAttempted(Exception):
    pass


@pytest.fixture(autouse=True)
def block_all_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise _NetworkCallAttempted("Tentativo di apertura socket bloccato nei test brain.")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


@pytest.fixture
def gateway():
    return cg.ConnectorGateway()


# ---------------- comportamento dry-run ----------------
def test_azione_dry_run_valida(gateway):
    result = gateway.request(
        cg.ConnectorRequest(action_type="send_email", payload={"to": "demo@example.com"}, reason="test")
    )
    assert result.status == "DRY_RUN"
    assert result.executed is False
    assert result.action_type == "send_email"


def test_payload_non_valido_rifiutato(gateway):
    with pytest.raises(RichiestaConnettoreNonValida):
        gateway.request(cg.ConnectorRequest(action_type="send_email", payload="non-un-dict"))


def test_tipo_azione_sconosciuto_rifiutato(gateway):
    with pytest.raises(RichiestaConnettoreNonValida):
        gateway.request(cg.ConnectorRequest(action_type="elimina_database", payload={}))


def test_tentativo_modalita_reale_bloccato(gateway):
    with pytest.raises(AzioneEsternaBloccata):
        gateway.request(cg.ConnectorRequest(action_type="send_email", payload={}, requested_mode="real"))


def test_tentativo_bloccato_anche_se_config_manomessa(gateway, monkeypatch):
    # Seconda barriera indipendente: anche se REAL_EXTERNAL_ACTIONS fosse
    # vero, il gateway blocca comunque (nessuna implementazione reale
    # esiste in questo file, per costruzione).
    monkeypatch.setattr(brain_config, "REAL_EXTERNAL_ACTIONS", True)
    with pytest.raises(AzioneEsternaBloccata):
        gateway.request(cg.ConnectorRequest(action_type="send_email", payload={}))


def test_tentativo_bloccato_anche_se_connector_mode_manomesso(gateway, monkeypatch):
    monkeypatch.setattr(brain_config, "CONNECTOR_MODE", "live")
    with pytest.raises(AzioneEsternaBloccata):
        gateway.request(cg.ConnectorRequest(action_type="send_email", payload={}))


# ---------------- registrazione tentativi ----------------
def test_registrazione_tentativo(gateway):
    gateway.request(cg.ConnectorRequest(action_type="publish_social", payload={"text": "ciao"}, reason="demo"))
    tentativi = gateway.attempts()
    assert len(tentativi) == 1
    assert tentativi[0].action_type == "publish_social"
    assert tentativi[0].result_status == "DRY_RUN"
    assert tentativi[0].created_at
    assert tentativi[0].attempt_id


def test_tentativo_bloccato_viene_comunque_registrato(gateway):
    with pytest.raises(AzioneEsternaBloccata):
        gateway.request(cg.ConnectorRequest(action_type="send_email", payload={}, requested_mode="real"))
    tentativi = gateway.attempts()
    assert len(tentativi) == 1
    assert tentativi[0].result_status == "BLOCCATO"


def test_attempts_ritorna_una_copia(gateway):
    gateway.request(cg.ConnectorRequest(action_type="send_email", payload={}))
    tentativi = gateway.attempts()
    tentativi.append("intruso")
    assert len(gateway.attempts()) == 1  # il registro interno non è stato alterato


# ---------------- payload ----------------
def test_payload_originale_non_modificato(gateway):
    payload = {"to": "demo@example.com", "api_key": "supersegreto"}
    originale = dict(payload)
    gateway.request(cg.ConnectorRequest(action_type="send_email", payload=payload))
    assert payload == originale


def test_payload_minimizzato_redige_segreti(gateway):
    gateway.request(cg.ConnectorRequest(action_type="send_email", payload={"to": "x@x.com", "api_key": "segreto123"}))
    registrato = gateway.attempts()[0].payload_minimized
    assert registrato["api_key"] == "[REDACTED]"
    assert registrato["to"] == "x@x.com"


def test_payload_minimizzato_redige_segreti_annidati(gateway):
    gateway.request(cg.ConnectorRequest(
        action_type="crm_write",
        payload={"lead": {"nome": "Mario", "credential": {"token": "xyz"}}},
    ))
    registrato = gateway.attempts()[0].payload_minimized
    assert registrato["lead"]["nome"] == "Mario"
    assert registrato["lead"]["credential"] == "[REDACTED]"


# ---------------- determinismo ----------------
def test_risposta_deterministica(gateway):
    r1 = gateway.request(cg.ConnectorRequest(action_type="send_email", payload={"to": "a@a.com"}))
    r2 = gateway.request(cg.ConnectorRequest(action_type="send_email", payload={"to": "a@a.com"}))
    assert r1.status == r2.status == "DRY_RUN"
    assert r1.executed == r2.executed is False
    assert r1.action_type == r2.action_type == "send_email"


def test_gateway_condiviso_default():
    g1 = cg.get_connector_gateway()
    g2 = cg.get_connector_gateway()
    assert g1 is g2


# ---------------- isolamento reale (non solo dichiarato) ----------------
def test_connector_gateway_non_importa_librerie_http():
    source = pathlib.Path(cg.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "aiohttp", "smtplib", "socket", "ftplib", "urllib3", "urllib"}
    intersezione = found & forbidden
    assert not intersezione, f"Import vietati trovati in connector_gateway.py: {intersezione}"


def test_config_import_non_produce_traffico_di_rete():
    importlib.reload(brain_config)  # eseguito con il socket bloccato dalla fixture autouse


def test_connector_gateway_import_non_produce_traffico_di_rete():
    importlib.reload(cg)
