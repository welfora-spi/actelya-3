"""Brain — test puri per l'audit append-only in-memory (Blocco C,
audit/memory_audit.py). Nessun Mongo, nessuna rete (socket bloccato per
tutta la durata dei test): ogni test crea una propria AuditLog isolata,
mai il singleton di processo."""
import socket

import pytest

from app.brain.audit.memory_audit import (
    ALLOWED_EVENT_TYPES,
    EVENT_AGENT_SELECTED,
    EVENT_PLAN_ALLOWED,
    EVENT_PLAN_BLOCKED,
    EVENT_REQUEST_RECEIVED,
    AuditLog,
    AuditSink,
    LimiteAuditSuperato,
    TipoEventoNonValido,
)


class _NetworkCallAttempted(Exception):
    pass


@pytest.fixture(autouse=True)
def block_all_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise _NetworkCallAttempted("Tentativo di apertura socket bloccato nei test brain.")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


def _clock_sequenziale():
    contatore = {"n": 0}

    def _clock():
        contatore["n"] += 1
        return f"2026-01-01T00:00:{contatore['n']:02d}Z"

    return _clock


# ---------------- tipo evento sconosciuto ----------------
def test_tipo_evento_sconosciuto_solleva():
    log = AuditLog(clock=_clock_sequenziale())
    with pytest.raises(TipoEventoNonValido):
        log.record(event_type="EVENTO_INVENTATO", session_id="s1", actor="test", decision="X", reason="r")


def test_tutti_i_tredici_tipi_evento_sono_registrabili():
    log = AuditLog(clock=_clock_sequenziale())
    assert len(ALLOWED_EVENT_TYPES) == 13
    for et in ALLOWED_EVENT_TYPES:
        ev = log.record(event_type=et, session_id="s1", actor="test", decision="X", reason="r")
        assert ev["event_type"] == et


# ---------------- 19. audit append-only ----------------
def test_audit_e_append_only_nessun_metodo_di_modifica_o_cancellazione():
    log = AuditLog(clock=_clock_sequenziale())
    log.record(event_type=EVENT_REQUEST_RECEIVED, session_id="s1", actor="test", decision="X", reason="r")
    assert not hasattr(log, "update")
    assert not hasattr(log, "delete")
    assert not hasattr(log, "remove")


def test_reset_e_solo_per_i_test_azzera_tutto():
    log = AuditLog(clock=_clock_sequenziale())
    log.record(event_type=EVENT_REQUEST_RECEIVED, session_id="s1", actor="test", decision="X", reason="r")
    log.reset()
    assert log.events() == []
    ev = log.record(event_type=EVENT_REQUEST_RECEIVED, session_id="s1", actor="test", decision="X", reason="r")
    assert ev["sequence_number"] == 1  # la numerazione riparte dopo reset (solo nei test)


# ---------------- 20. sequence number e ordine deterministici ----------------
def test_sequence_number_progressivo_e_ordine_stabile():
    log = AuditLog(clock=_clock_sequenziale())
    e1 = log.record(event_type=EVENT_REQUEST_RECEIVED, session_id="s1", actor="a", decision="X", reason="r")
    e2 = log.record(event_type=EVENT_PLAN_ALLOWED, session_id="s1", actor="a", decision="X", reason="r")
    e3 = log.record(event_type=EVENT_AGENT_SELECTED, session_id="s1", actor="a", decision="X", reason="r")
    assert [e1["sequence_number"], e2["sequence_number"], e3["sequence_number"]] == [1, 2, 3]
    assert [e["timestamp"] for e in log.events()] == sorted(e["timestamp"] for e in log.events())
    assert [e["event_id"] for e in log.events()] == [e1["event_id"], e2["event_id"], e3["event_id"]]


def test_clock_iniettabile_rende_i_timestamp_deterministici():
    letture = iter(["t0", "t1"])
    log = AuditLog(clock=lambda: next(letture))
    e1 = log.record(event_type=EVENT_REQUEST_RECEIVED, session_id="s1", actor="a", decision="X", reason="r")
    e2 = log.record(event_type=EVENT_PLAN_ALLOWED, session_id="s1", actor="a", decision="X", reason="r")
    assert e1["timestamp"] == "t0" and e2["timestamp"] == "t1"


# ---------------- 21. filtri audit ----------------
def test_filtri_per_sessione_piano_obiettivo_tipo_evento():
    log = AuditLog(clock=_clock_sequenziale())
    log.record(event_type=EVENT_REQUEST_RECEIVED, session_id="s1", goal_id="g1", actor="a", decision="X", reason="r")
    log.record(event_type=EVENT_PLAN_ALLOWED, session_id="s1", goal_id="g1", plan_id="p1", actor="a",
               decision="X", reason="r")
    log.record(event_type=EVENT_REQUEST_RECEIVED, session_id="s2", goal_id="g2", actor="a", decision="X", reason="r")

    assert len(log.filter(session_id="s1")) == 2
    assert len(log.filter(plan_id="p1")) == 1
    assert len(log.filter(goal_id="g2")) == 1
    assert len(log.filter(event_type=EVENT_REQUEST_RECEIVED)) == 2
    assert len(log.filter(session_id="s1", event_type=EVENT_PLAN_ALLOWED)) == 1
    assert log.filter(session_id="inesistente") == []


# ---------------- 22. impossibilità di modificare eventi restituiti ----------------
def test_evento_restituito_e_una_copia_difensiva():
    log = AuditLog(clock=_clock_sequenziale())
    log.record(event_type=EVENT_REQUEST_RECEIVED, session_id="s1", actor="a", decision="X", reason="r",
               metadata={"chiave": "valore"})
    letto = log.events()[0]
    letto["metadata"]["chiave"] = "MANOMESSO"
    letto["decision"] = "MANOMESSO"
    ancora = log.events()[0]
    assert ancora["metadata"]["chiave"] == "valore"
    assert ancora["decision"] == "X"


def test_filter_restituisce_copie_indipendenti():
    log = AuditLog(clock=_clock_sequenziale())
    log.record(event_type=EVENT_REQUEST_RECEIVED, session_id="s1", actor="a", decision="X", reason="r")
    a = log.filter(session_id="s1")
    b = log.filter(session_id="s1")
    a[0]["decision"] = "ALTRO"
    assert b[0]["decision"] == "X"


# ---------------- limite eventi (senza eliminazioni silenziose) ----------------
def test_limite_eventi_rifiuta_senza_eliminare_i_precedenti():
    log = AuditLog(clock=_clock_sequenziale(), max_events=2)
    log.record(event_type=EVENT_REQUEST_RECEIVED, session_id="s1", actor="a", decision="X", reason="r")
    log.record(event_type=EVENT_PLAN_ALLOWED, session_id="s1", actor="a", decision="X", reason="r")
    with pytest.raises(LimiteAuditSuperato):
        log.record(event_type=EVENT_PLAN_BLOCKED, session_id="s1", actor="a", decision="X", reason="r")
    assert len(log.events()) == 2  # nessun evento precedente eliminato per fare spazio


# ---------------- redazione ricorsiva ----------------
def test_redazione_credenziali_nei_metadata():
    log = AuditLog(clock=_clock_sequenziale())
    ev = log.record(event_type=EVENT_REQUEST_RECEIVED, session_id="s1", actor="a", decision="X", reason="r",
                     metadata={"api_key": "sk-123", "annidato": {"password": "abc"}, "ok": "visibile"})
    assert ev["metadata"]["api_key"] == "[REDACTED]"
    assert ev["metadata"]["annidato"]["password"] == "[REDACTED]"
    assert ev["metadata"]["ok"] == "visibile"


# ---------------- interfaccia AuditSink (predisposizione futura) ----------------
def test_auditlog_implementa_auditsink():
    log = AuditLog(clock=_clock_sequenziale())
    assert isinstance(log, AuditSink)


# ---------------- zero traffico di rete (verifica statica aggiuntiva) ----------------
def test_audit_module_non_importa_librerie_di_rete_o_db():
    import ast
    import pathlib

    from app.brain.audit import memory_audit as mod

    source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "aiohttp", "smtplib", "socket", "ftplib", "pymongo", "motor"}
    assert not (found & forbidden)
