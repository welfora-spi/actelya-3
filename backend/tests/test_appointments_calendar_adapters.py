"""Appointment Setter — adapter calendario: nessuna chiamata di rete reale
(bloccata attivamente per tutta la durata dei test, stesso schema di
test_brain_agent_selector_b1.py)."""
import socket

import pytest

from app.domains.appointments import calendar_adapters as CA
from app.security import encrypt_secret


class _NetworkCallAttempted(Exception):
    pass


@pytest.fixture(autouse=True)
def block_all_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise _NetworkCallAttempted("Tentativo di apertura socket bloccato nei test appointments.")
    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


def test_build_adapter_senza_connessione_e_non_configurato():
    a = CA.build_adapter(None)
    assert a.configured is False
    ok, motivo = a.verify()
    assert ok is False
    esito = a.create_event(start_iso="x", end_iso="y", title="t", description="d")
    assert esito.status == CA.STATO_NON_DISPONIBILE


def test_build_adapter_provider_sconosciuto_e_non_configurato():
    a = CA.build_adapter({"provider_type": "provider-mai-esistito"})
    assert a.configured is False


def test_build_adapter_google_senza_token_non_configurato():
    a = CA.build_adapter({"provider_type": "google_calendar", "calendar_id": "primary"})
    assert a.provider_type == "google_calendar"
    assert a.configured is False
    esito = a.create_event(start_iso="2026-01-01T09:00:00Z", end_iso="2026-01-01T09:30:00Z",
                           title="t", description="d")
    assert esito.status == CA.STATO_NON_DISPONIBILE


def test_build_adapter_google_con_token_e_configurato_ma_non_chiama_la_rete():
    conn = {"provider_type": "google_calendar", "calendar_id": "primary",
           "access_token_encrypted": encrypt_secret("token-di-test")}
    a = CA.build_adapter(conn)
    assert a.configured is True  # nessuna chiamata di rete avvenuta per arrivare qui (socket bloccato)


def test_build_adapter_microsoft_graph_con_token_e_configurato():
    conn = {"provider_type": "microsoft_graph", "access_token_encrypted": encrypt_secret("token-di-test")}
    a = CA.build_adapter(conn)
    assert a.provider_type == "microsoft_graph"
    assert a.configured is True


def test_build_adapter_calendly_con_api_key_e_configurato_ma_create_event_non_disponibile():
    conn = {"provider_type": "calendly", "api_key_encrypted": encrypt_secret("pat-di-test")}
    a = CA.build_adapter(conn)
    assert a.configured is True
    esito = a.create_event(start_iso="2026-01-01T09:00:00Z", end_iso="2026-01-01T09:30:00Z",
                           title="t", description="d")
    assert esito.status == CA.STATO_NON_DISPONIBILE  # predisposto, mai una prenotazione diretta oggi


def test_oauth_authorize_url_google_senza_app_configurata_ritorna_none(monkeypatch):
    monkeypatch.setattr(CA, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(CA, "GOOGLE_REDIRECT_URI", "")
    assert CA.oauth_authorize_url("google_calendar", "stato") is None


def test_oauth_authorize_url_google_con_app_configurata_costruisce_url_senza_rete(monkeypatch):
    monkeypatch.setattr(CA, "GOOGLE_CLIENT_ID", "client-di-test")
    monkeypatch.setattr(CA, "GOOGLE_REDIRECT_URI", "https://esempio.it/callback")
    url = CA.oauth_authorize_url("google_calendar", "stato-xyz")
    assert url is not None
    assert "client-di-test" in url
    assert "stato-xyz" in url
    assert url.startswith(CA.GOOGLE_AUTH_BASE)


def test_oauth_authorize_url_calendly_non_previsto():
    assert CA.oauth_authorize_url("calendly", "stato") is None


def test_oauth_exchange_code_senza_app_configurata_ritorna_none(monkeypatch):
    monkeypatch.setattr(CA, "GOOGLE_CLIENT_ID", "")
    assert CA.oauth_exchange_code("google_calendar", "un-codice") is None
