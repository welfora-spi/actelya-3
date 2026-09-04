"""Blocco A — test puri per backend/app/brain/config.py.
Nessuna rete, nessun Mongo: solo funzioni pure su dizionari sintetici."""
import importlib

from app.brain import config


def test_real_external_actions_assente_e_sicuro():
    assert config.resolve_real_external_actions({}) is False


def test_ai_provider_mode_assente_e_sicuro():
    assert config.resolve_ai_provider_mode({}) == "mock"


def test_connector_mode_assente_e_sicuro():
    assert config.resolve_connector_mode({}) == "dry_run"


def test_valori_validi_espliciti():
    assert config.resolve_ai_provider_mode({"AI_PROVIDER_MODE": "mock"}) == "mock"
    assert config.resolve_connector_mode({"CONNECTOR_MODE": "dry_run"}) == "dry_run"
    assert config.resolve_ai_provider_mode({"AI_PROVIDER_MODE": "MOCK"}) == "mock"  # case-insensitive
    assert config.resolve_connector_mode({"CONNECTOR_MODE": " dry_run "}) == "dry_run"  # spazi tollerati


def test_valori_sconosciuti_ricadono_sul_default_sicuro():
    assert config.resolve_ai_provider_mode({"AI_PROVIDER_MODE": "banana"}) == "mock"
    assert config.resolve_connector_mode({"CONNECTOR_MODE": "produzione"}) == "dry_run"
    assert config.resolve_real_external_actions({"REAL_EXTERNAL_ACTIONS": "boh"}) is False


def test_real_external_actions_stringa_vuota_e_sicuro():
    assert config.resolve_real_external_actions({"REAL_EXTERNAL_ACTIONS": ""}) is False


def test_valori_non_riconosciuti_per_connector_mode_restano_dry_run():
    # AGGIORNATO (DECISIONE UFFICIALE "100% REALE"): CONNECTOR_MODE puo' ora
    # risolvere a 'real' (vedi test_connector_mode_real_richiede_valore_esatto
    # sotto), ma SOLO per la stringa esatta 'real' (case-insensitive) — ogni
    # altro tentativo/refuso resta bloccato su dry_run. AI_PROVIDER_MODE non
    # ha invece alcun valore reale in questa fase (i provider AI reali non
    # passano da questo flag, vedi domains/connections.py): resta sempre 'mock'.
    for tentativo in ("live", "production", "true", "1", "enabled", "reale", " real ish"):
        assert config.resolve_ai_provider_mode({"AI_PROVIDER_MODE": tentativo}) == "mock"
        assert config.resolve_connector_mode({"CONNECTOR_MODE": tentativo}) == "dry_run"


def test_connector_mode_real_richiede_valore_esatto():
    # 'real' (case-insensitive, spazi tollerati) e' l'UNICO valore che
    # sblocca la modalita' reale del connector — da solo NON e' comunque
    # sufficiente per un'azione reale: gateways/connector_gateway.py
    # verifica anche REAL_EXTERNAL_ACTIONS, un adapter reale registrato e la
    # configurazione/verifica del connector per l'organizzazione.
    assert config.resolve_connector_mode({"CONNECTOR_MODE": "real"}) == "real"
    assert config.resolve_connector_mode({"CONNECTOR_MODE": "REAL"}) == "real"
    assert config.resolve_connector_mode({"CONNECTOR_MODE": " real "}) == "real"


def test_real_external_actions_puo_essere_impostato_esplicitamente_a_vero():
    # Il flag stesso può essere letto come True se qualcuno lo imposta
    # esplicitamente (per un'eventuale fase futura) — ma questo NON
    # implica alcuna azione reale: il connector gateway lo verifica
    # comunque come seconda barriera indipendente (vedi
    # test_brain_connector_gateway.py::test_tentativo_bloccato_anche_se_config_manomessa).
    assert config.resolve_real_external_actions({"REAL_EXTERNAL_ACTIONS": "true"}) is True
    assert config.resolve_real_external_actions({"REAL_EXTERNAL_ACTIONS": "1"}) is True


def test_costanti_modulo_sono_i_default_sicuri_se_ambiente_pulito(monkeypatch):
    for var in ("REAL_EXTERNAL_ACTIONS", "AI_PROVIDER_MODE", "CONNECTOR_MODE"):
        monkeypatch.delenv(var, raising=False)
    importlib.reload(config)
    try:
        assert config.REAL_EXTERNAL_ACTIONS is False
        assert config.AI_PROVIDER_MODE == "mock"
        assert config.CONNECTOR_MODE == "dry_run"
    finally:
        importlib.reload(config)  # ripristina lo stato per gli altri test del processo
