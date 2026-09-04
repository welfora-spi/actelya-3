"""Brain — test per llm_schema.py (CEO Agent 100% reale, blocco 4): rifiuta
sempre un output sintatticamente non valido, non conforme allo schema, o
conforme ma semanticamente vuoto (nessun intent/strategia/agente/task)."""
import json

import pytest

from app.brain.llm_schema import CeoLLMProposal, PropostaNonValida, json_schema_per_provider, parse_llm_proposal

JSON_MINIMO_VALIDO = json.dumps({"intent": "aumentare i clienti", "strategia_proposta": "campagna locale"})

JSON_COMPLETO = json.dumps({
    "intent": "aumentare i clienti", "obiettivo_normalizzato": "campagna social locale",
    "priorita": "ALTA", "urgenza": "MEDIA", "budget_totale": 2000.0, "budget_valuta": "EUR",
    "allocazioni_budget": [{"etichetta": "social", "importo": 1000.0}],
    "scadenza": "2026-12-01", "vincoli": ["nessun dato reale"], "pubblico": "famiglie locali",
    "canali": ["Instagram", "Facebook"], "dati_mancanti": ["logo aziendale"],
    "rischi": [{"categoria": "spesa", "severita": "MEDIA", "descrizione": "campagna a pagamento"}],
    "strategia_proposta": "campagna locale mirata a famiglie", "agenti_suggeriti": [
        {"capability": "social", "motivazione": "richiesta esplicita di post"},
    ], "capability_richieste": ["social"], "task_proposti": [
        {"nome": "post settimanali", "capability": "social", "ordine": 1, "dipende_da": [],
         "deliverable_type": "social_content", "priorita": "ALTA", "scadenza": None},
    ], "deliverable": ["post"], "kpi": ["engagement"], "approvazioni_necessarie": ["pubblicazione"],
    "confidence": 0.8, "assunzioni": ["pubblico gia' noto"],
})


def test_parse_json_completo():
    p = parse_llm_proposal(JSON_COMPLETO)
    assert isinstance(p, CeoLLMProposal)
    assert p.intent == "aumentare i clienti"
    assert p.priorita == "ALTA"
    assert p.budget_totale == 2000.0
    assert p.agenti_suggeriti[0].capability == "social"
    assert p.task_proposti[0].nome == "post settimanali"
    assert p.e_significativa() is True


def test_parse_json_minimo_valido():
    p = parse_llm_proposal(JSON_MINIMO_VALIDO)
    assert p.e_significativa() is True
    assert p.rischi == []
    assert p.task_proposti == []


def test_json_sintatticamente_non_valido():
    with pytest.raises(PropostaNonValida):
        parse_llm_proposal("questo non e' un JSON {{{")


def test_json_valido_ma_non_e_un_oggetto():
    with pytest.raises(PropostaNonValida):
        parse_llm_proposal("[1, 2, 3]")


def test_json_none_o_vuoto():
    with pytest.raises(PropostaNonValida):
        parse_llm_proposal("")
    with pytest.raises(PropostaNonValida):
        parse_llm_proposal(None)


def test_schema_non_conforme_tipo_errato():
    grezzo = json.dumps({"intent": "x", "strategia_proposta": "y", "priorita": 12345})
    with pytest.raises(PropostaNonValida):
        parse_llm_proposal(grezzo)


def test_output_semanticamente_vuoto_rifiutato():
    grezzo = json.dumps({"intent": "", "strategia_proposta": "", "agenti_suggeriti": [], "task_proposti": []})
    with pytest.raises(PropostaNonValida):
        parse_llm_proposal(grezzo)


def test_output_vuoto_ma_con_task_proposti_e_accettato():
    grezzo = json.dumps({
        "intent": "", "strategia_proposta": "",
        "task_proposti": [{"nome": "t", "capability": "social", "ordine": 1}],
    })
    p = parse_llm_proposal(grezzo)
    assert p.e_significativa() is True


def test_json_schema_per_provider_ha_i_campi_principali():
    schema = json_schema_per_provider()
    assert schema["type"] == "object"
    for campo in ("intent", "priorita", "urgenza", "budget_totale", "rischi", "agenti_suggeriti",
                  "task_proposti", "confidence", "assunzioni"):
        assert campo in schema["properties"]
    assert schema["required"] == ["intent", "strategia_proposta"]
