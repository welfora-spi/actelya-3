"""Blocco 3 — test registro e contratti agenti (SIMULAZIONE)."""
import copy
import pytest

from app.m2 import agents_registry as R
from app.m2.agents_registry import ContractError, AGENT_CONTRACTS, GLOBAL_FORBIDDEN


def test_registry_valid_and_unique_ids():
    cap_map = R.validate_registry()
    # id univoci e stabili (chiave == id)
    for key, c in AGENT_CONTRACTS.items():
        assert c["id"] == key
    # capability mappate senza duplicazioni
    assert len(set(cap_map.values())) >= 1
    assert cap_map == R.validate_registry()  # deterministico


def test_contracts_have_all_fields():
    for key, c in AGENT_CONTRACTS.items():
        for f in ["mission", "capabilities", "allowed_deliverables", "input_schema", "output_schema",
                  "allowed_actions", "forbidden_actions", "success_criteria", "block_criteria",
                  "handoff_criteria", "missing_data_criteria", "token_limit", "budget", "timeout"]:
            assert f in c, f"{key} manca {f}"
        assert c["token_limit"] > 0 and c["timeout"] > 0 and c["budget"] >= 0


def test_global_forbidden_on_every_agent():
    # Nessun agente può pubblicare/inviare/contattare persone reali in M2.
    for key, c in AGENT_CONTRACTS.items():
        for gf in GLOBAL_FORBIDDEN:
            assert gf in c["forbidden_actions"], f"{key} non vieta {gf}"


def test_deterministic_and_explainable_selection():
    r1 = R.select_agent("marketing_strategy")
    r2 = R.select_agent("marketing_strategy")
    assert r1 == r2  # deterministico
    assert r1["agent_id"] == "marketing_strategist"
    assert "->" in r1["reason"]  # esplicabile
    # copertura di tutti i deliverable operativi M2
    expected = {
        "marketing_strategy": "marketing_strategist",
        "editorial_plan": "content_social",
        "social_content": "content_social",
        "ad_campaign_draft": "advertising",
        "lead_gen_plan": "lead_gen_sdr",
        "kpi_report": "analytics_performance",
        "email": "content_social",
    }
    for dtype, agent in expected.items():
        assert R.select_agent(dtype)["agent_id"] == agent


def test_reviewers_non_destructive():
    for rid in ["compliance_reviewer", "auditor"]:
        c = AGENT_CONTRACTS[rid]
        assert c["role"] == "reviewer"
        assert c["allowed_deliverables"] == []  # non producono/sostituiscono deliverable
        assert "modifica_deliverable" in c["forbidden_actions"]
        assert "cancellazione_deliverable" in c["forbidden_actions"]


def test_predisposti_never_selected_as_operative():
    for pid in ["appointment_setter", "nurturing"]:
        assert AGENT_CONTRACTS[pid]["operative"] is False
    # non compaiono nel mapping capability->agente (solo operativi)
    cap_map = R.validate_registry()
    assert "appointment_setter" not in cap_map.values()
    assert "nurturing" not in cap_map.values()


def test_duplicate_id_raises():
    reg = copy.deepcopy(AGENT_CONTRACTS)
    reg["dup"] = copy.deepcopy(reg["marketing_strategist"])  # id resta 'marketing_strategist'
    with pytest.raises(ContractError):
        R.validate_registry(reg)


def test_duplicate_capability_raises():
    reg = copy.deepcopy(AGENT_CONTRACTS)
    # aggiunge un secondo agente operativo con la stessa capability 'strategy'
    clone = copy.deepcopy(reg["marketing_strategist"])
    clone["id"] = "strategist_2"
    reg["strategist_2"] = clone
    with pytest.raises(ContractError):
        R.validate_registry(reg)


def test_invalid_contract_missing_field_raises():
    reg = copy.deepcopy(AGENT_CONTRACTS)
    del reg["advertising"]["output_schema"]
    with pytest.raises(ContractError):
        R.validate_registry(reg)


def test_missing_compatible_agent_raises():
    # deliverable senza mapping capability -> errore esplicito, nessun fallback
    with pytest.raises(ContractError):
        R.select_agent("deliverable_inesistente")
    # capability presente ma nessun agente operativo che la offre
    reg = copy.deepcopy(AGENT_CONTRACTS)
    reg["analytics_performance"]["operative"] = False
    with pytest.raises(ContractError):
        R.select_agent("kpi_report", registry=reg)


def test_forbidden_action_blocks_safely():
    # tentativo di assegnare un'azione vietata -> blocco sicuro (ContractError), non esecuzione
    with pytest.raises(ContractError):
        R.assert_action_allowed("content_social", "invio_reale")
    with pytest.raises(ContractError):
        R.assert_action_allowed("advertising", "pubblicazione_reale")
    with pytest.raises(ContractError):
        R.assert_action_allowed("lead_gen_sdr", "contatto_persone_reali")
    # azione consentita passa
    assert R.assert_action_allowed("marketing_strategist", "produzione_bozza") is True


def test_email_m1_compat_selects_content_social():
    sel = R.select_agent("email")
    assert sel["agent_id"] == "content_social"
    assert AGENT_CONTRACTS["content_social"]["operative"] is True
