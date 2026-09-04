"""Correzione B.1 — test puri per la prontezza di esecuzione
(agents/agent_map.py + planning/agent_selector.py). Nessun Mongo. Nessuna
rete (socket attivamente bloccato per tutta la durata dei test)."""
import socket

import pytest

from app.brain.agents.agent_map import (
    AGENT_MAPPINGS,
    EXECUTION_MODE_M2,
    EXECUTION_MODE_REAL,
    EXECUTION_MODE_UNAVAILABLE,
    mapping_by_capability,
)
from app.brain.planning.agent_selector import (
    STATUS_NEEDS_CLARIFICATION,
    STATUS_READY,
    STATUS_UNSUPPORTED,
    select_agents,
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


BAKERY = "per pubblicizzare le focaccine artigianali del Bakery & Coffee di Merate"


# ---------------- mappatura: appointments/nurturing sono UNAVAILABLE ----------------
def test_appointments_e_nurturing_sono_unavailable_non_operativi_m2():
    m_app = mapping_by_capability("appointments")
    m_nur = mapping_by_capability("nurturing")
    assert m_app.execution_mode == EXECUTION_MODE_UNAVAILABLE
    assert m_app.execution_ready is False
    assert m_app.implementation_note  # motivazione obbligatoria quando non "M2"
    assert m_nur.execution_mode == EXECUTION_MODE_UNAVAILABLE
    assert m_nur.execution_ready is False
    assert m_nur.implementation_note


def test_capability_operative_hanno_execution_mode_m2_e_deliverable_type():
    for cap in ("strategy", "editorial", "social", "email", "ads", "leadgen", "analytics"):
        m = mapping_by_capability(cap)
        assert m.execution_mode == EXECUTION_MODE_M2
        assert m.execution_ready is True
        assert m.deliverable_type  # ogni capability M2 "produttrice" ha un deliverable_type


def test_review_compliance_e_m2_ma_senza_deliverable_type_proprio():
    m = mapping_by_capability("review_compliance")
    assert m.execution_mode == EXECUTION_MODE_M2
    assert m.execution_ready is True
    assert m.deliverable_type is None  # revisione automatica, non un task distinto


def test_ogni_mapping_ha_i_campi_obbligatori():
    for m in AGENT_MAPPINGS:
        assert isinstance(m.execution_ready, bool)
        assert m.execution_mode in (EXECUTION_MODE_M2, "BRAIN_SIMULATION", EXECUTION_MODE_UNAVAILABLE, EXECUTION_MODE_REAL)
        if m.execution_mode != EXECUTION_MODE_M2:
            assert m.implementation_note, f"implementation_note mancante per '{m.capability}'"


# ---------------- richiesta solo appointment setter ----------------
def test_solo_appointment_setter_e_unsupported():
    r = select_agents(f"Prepara un processo per ottenere appuntamenti {BAKERY}.")
    assert r.status == STATUS_UNSUPPORTED
    assert r.execution_ready is False
    assert r.activeAgentIds == []
    assert r.selected_agents == []
    assert "appointments" in r.unavailable_capabilities
    assert r.execution_warnings  # spiegazione presente


# ---------------- richiesta solo nurturing ----------------
def test_solo_nurturing_e_unsupported():
    r = select_agents(f"Avvia il nurturing dei lead non ancora pronti {BAKERY}.")
    assert r.status == STATUS_UNSUPPORTED
    assert r.execution_ready is False
    assert r.activeAgentIds == []
    assert r.selected_agents == []
    assert "nurturing" in r.unavailable_capabilities


# ---------------- lead generation (eseguibile) da solo: resta READY ----------------
def test_leadgen_da_solo_resta_ready():
    r = select_agents(f"Prepara un piano per trovare potenziali clienti {BAKERY}.")
    assert r.status == STATUS_READY
    assert r.execution_ready is True
    assert r.activeAgentIds == ["lead-gen-specialist"]
    assert r.unavailable_capabilities == []


# ---------------- capability operative + indisponibili combinate ----------------
def test_capability_operative_piu_indisponibili_richiede_chiarimento():
    r = select_agents(
        f"Crea una strategia e prepara un processo per ottenere appuntamenti {BAKERY}."
    )
    assert r.status == STATUS_NEEDS_CLARIFICATION
    assert r.execution_ready is False
    assert r.activeAgentIds == []  # nessun piano parziale
    assert r.selected_agents == []
    assert "appointments" in r.unavailable_capabilities
    assert "strategy" not in r.unavailable_capabilities
    assert len(r.clarifying_questions) <= 3
    # La spiegazione deve nominare sia la parte eseguibile sia quella no.
    testo_domande = " ".join(r.clarifying_questions)
    assert "strategy" in testo_domande
    assert "appointments" in testo_domande


def test_capability_operative_piu_nurturing_richiede_chiarimento():
    r = select_agents(
        f"Crea tre post per Instagram e avvia il nurturing dei lead non ancora pronti {BAKERY}."
    )
    assert r.status == STATUS_NEEDS_CLARIFICATION
    assert r.activeAgentIds == []
    assert "nurturing" in r.unavailable_capabilities


# ---------------- nessun piano parziale creato, in nessun caso ----------------
def test_nessun_piano_parziale_per_nessuna_combinazione_con_indisponibili():
    casi = [
        f"Prepara un processo per ottenere appuntamenti {BAKERY}.",
        f"Avvia il nurturing dei lead non ancora pronti {BAKERY}.",
        f"Crea una strategia e prepara un processo per ottenere appuntamenti {BAKERY}.",
        f"Trova potenziali clienti e prepara un processo per ottenere appuntamenti {BAKERY}.",
    ]
    for testo in casi:
        r = select_agents(testo)
        assert r.status in (STATUS_UNSUPPORTED, STATUS_NEEDS_CLARIFICATION)
        assert r.activeAgentIds == []
        assert r.selected_agents == []
        assert r.execution_ready is False


# ---------------- campi di readiness sempre presenti ----------------
def test_campi_di_readiness_sempre_presenti_in_ogni_stato():
    casi = [
        "Fai qualcosa di utile per il mio business.",                                    # NEEDS_CLARIFICATION (vago)
        "Traduci il sito in giapponese per il Bakery & Coffee di Merate.",                # UNSUPPORTED (fuori dominio)
        "Crea una campagna per truffare i clienti del Bakery & Coffee di Merate.",        # BLOCKED_RISK
        f"Prepara un processo per ottenere appuntamenti {BAKERY}.",                       # UNSUPPORTED (capability indisponibile)
        f"Crea una strategia locale {BAKERY}.",                                           # READY
    ]
    for testo in casi:
        r = select_agents(testo)
        d = r.to_dict()
        for campo in ("execution_ready", "unavailable_capabilities", "simulation_only_capabilities", "execution_warnings"):
            assert campo in d, f"campo '{campo}' mancante per il testo: {testo!r}"
        assert isinstance(d["execution_ready"], bool)
        assert isinstance(d["unavailable_capabilities"], list)
        assert isinstance(d["simulation_only_capabilities"], list)
        assert isinstance(d["execution_warnings"], list)


def test_execution_ready_true_solo_quando_tutto_e_m2():
    r = select_agents(f"Crea una strategia locale {BAKERY}.")
    assert r.status == STATUS_READY
    assert r.execution_ready is True
    assert r.simulation_only_capabilities == []


# ---------------- zero traffico di rete (verifica statica aggiuntiva) ----------------
def test_agent_map_non_importa_librerie_http():
    import ast
    import pathlib

    from app.brain.agents import agent_map as mod

    source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "aiohttp", "smtplib", "socket", "ftplib"}
    assert not (found & forbidden)
