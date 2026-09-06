"""Test end-to-end di un utente reale (server live, MongoDB reale): l'intero
flusso Nuovo Obiettivo → Brain → CEO → Plan → Task → Agent → Handoff →
Approval → Deliverable, attraversando insieme TUTTI i sei agenti REALI oggi
operativi (Lead Generation, Content Creator, Sales, Appointment Setter,
Analyst/KPI, Compliance) a partire da un solo obiettivo in linguaggio
naturale — senza alcuna modalità AI REALE attiva (percorso DETERMINISTICO
del CEO, quello che funziona per qualunque organizzazione anche a costo
zero, senza credenziali LLM): nessuna chiamata reale a un provider esterno."""
import uuid

import pytest
import requests

from conftest import API_URL as API, register_tenant

TEST_PASSWORD = "E2ERealFlow!2026x"

GOAL_TEXT = (
    "Voglio fare lead generation per trovare nuovi clienti, scrivere un articolo per il blog "
    "aziendale, vedere un report sulle performance attuali, gestire la pipeline commerciale e "
    "fissare appuntamenti con i clienti interessati."
)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def real_user():
    """Un utente reale: registra il tenant, dichiara il 'prodotto' mancante
    (unico campo del Fact Ledger non già coperto dalla registrazione stessa)
    — stesso percorso che un vero cliente seguirebbe dal proprio onboarding."""
    org_id, token = register_tenant("E2E Real Flow Co", password=TEST_PASSWORD)
    r = requests.post(f"{API}/knowledge/facts", headers=_auth(token), timeout=15,
                      json={"field": "prodotto", "value": "Software gestionale per PMI", "source": "manuale"})
    assert r.status_code == 200, r.text
    return org_id, token


def test_nuovo_obiettivo_rileva_tutti_gli_agenti_reali_e_produce_un_piano_pronto(real_user):
    """Brain → CEO (percorso deterministico, nessun provider LLM configurato)
    → Plan: un solo obiettivo in linguaggio naturale deve convocare TUTTI e
    sei gli agenti reali insieme, senza che nessuno scarti gli altri."""
    _, token = real_user
    r = requests.post(f"{API}/brain/plans", headers=_auth(token), timeout=30, json={"text": GOAL_TEXT})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["status"] == "READY", body
    assert body["llm_understanding"]["mode"] == "DETERMINISTICO"  # nessuna chiamata LLM reale
    assert set(body["detected_intents"]) == {"analytics", "leadgen", "appointments", "sales", "content", "review_compliance"}
    assert set(body["activeAgentIds"]) == {
        "content-creator", "lead-gen-specialist", "analista-performance",
        "resp-compliance", "appointment-setter", "sales-agent",
    }
    assert body["plan"] is not None and body["plan"]["id"]

    tasks_per_tipo = {t["deliverable_type"]: t for t in body["tasks"]}
    assert tasks_per_tipo["lead_gen_campaign"]["agent_id"] == "lead-gen-specialist"
    assert tasks_per_tipo["content_item"]["agent_id"] == "content-creator"
    assert tasks_per_tipo["analyst_report"]["agent_id"] == "analista-performance"
    assert tasks_per_tipo["appointment_setter_task"]["agent_id"] == "appointment-setter"
    assert tasks_per_tipo["sales_opportunity"]["agent_id"] == "sales-agent"

    # Handoff reale e verificabile: la campagna lead generation esiste già,
    # collegata al piano/obiettivo appena creato (mai un id inventato).
    assert body["lead_campaign"]["plan_id"] == body["plan"]["id"]
    lc = requests.get(f"{API}/leadgen/campaigns/{body['lead_campaign']['id']}", headers=_auth(token), timeout=15)
    assert lc.status_code == 200
    assert lc.json()["status"] == "BOZZA"

    content_item_ids = tasks_per_tipo["content_item"]["inputs"]["deliverable_override"]["content_item_ids"]
    ci = requests.get(f"{API}/content-creator/items/{content_item_ids[0]}", headers=_auth(token), timeout=15)
    assert ci.status_code == 200
    assert ci.json()["status"] == "BOZZA"

    analyst_report_id = tasks_per_tipo["analyst_report"]["inputs"]["deliverable_override"]["analyst_report_id"]
    ar = requests.get(f"{API}/analyst/reports/{analyst_report_id}", headers=_auth(token), timeout=15)
    assert ar.status_code == 200
    assert "insights" in ar.json()


def test_approval_e_tick_completano_i_task_reali_con_deliverable_onesto(real_user):
    """Approval → Tool Gateway/Task claim → Deliverable: dopo l'approvazione
    del piano, il tick M2 deve far progredire OGNI task reale (leadgen/
    content/analytics/appointments/sales) fino a un deliverable che dichiara
    onestamente dove si trova il lavoro vero (nessun 'tipo sconosciuto',
    nessun contenuto simulato spacciato per reale)."""
    _, token = real_user
    r = requests.post(f"{API}/brain/plans", headers=_auth(token), timeout=30, json={"text": GOAL_TEXT})
    plan_id = r.json()["plan"]["id"]

    r_appr = requests.post(f"{API}/m2/plans/{plan_id}/approve", headers=_auth(token), timeout=15)
    assert r_appr.status_code == 200, r_appr.text
    assert r_appr.json()["plan_status"] == "APPROVATO"

    r_tick = requests.post(f"{API}/m2/plans/{plan_id}/tick", headers=_auth(token), timeout=30)
    assert r_tick.status_code == 200, r_tick.text
    tick_body = r_tick.json()
    assert tick_body["processed"] >= 5  # almeno i 5 task REALI (+ eventuale compliance)
    for risultato in tick_body["results"]:
        assert risultato["result"] == "completed"
        assert risultato["deliverable_status"] != "BLOCCATO"

    r_del = requests.get(f"{API}/m2/plans/{plan_id}/deliverables", headers=_auth(token), timeout=15)
    assert r_del.status_code == 200, r_del.text
    deliverables = r_del.json()["deliverables"]
    per_tipo = {d["deliverable_type"]: d for d in deliverables}

    for tipo, laboratorio in (
        ("lead_gen_campaign", "Lead Generation"), ("content_item", "Content Creator"),
        ("analyst_report", "Analyst"), ("appointment_setter_task", "Appointment Setter"),
        ("sales_opportunity", "Sales"),
    ):
        assert tipo in per_tipo, f"deliverable mancante per {tipo}"
        d = per_tipo[tipo]
        assert d["status"] == "COMPLETATO_CON_AVVISI"
        assert d["content"].get("mode") == "REALE"
        assert any(laboratorio in w for w in d["warnings"]), (
            f"il deliverable {tipo} deve dichiarare esplicitamente dove si trova il lavoro vero ({laboratorio})")


def test_isolamento_multi_tenant_sul_flusso_completo():
    """Due utenti reali indipendenti: il piano/i task/le entità reali di uno
    non devono mai essere visibili all'altro, lungo l'intero flusso."""
    org_a, token_a = register_tenant("E2E Isolamento Tenant A", password=TEST_PASSWORD)
    org_b, token_b = register_tenant("E2E Isolamento Tenant B", password=TEST_PASSWORD)
    requests.post(f"{API}/knowledge/facts", headers=_auth(token_a), timeout=15,
                 json={"field": "prodotto", "value": "Software gestionale per PMI", "source": "manuale"})

    r = requests.post(f"{API}/brain/plans", headers=_auth(token_a), timeout=30, json={"text": GOAL_TEXT})
    body = r.json()
    plan_id = body["plan"]["id"]
    lead_campaign_id = body["lead_campaign"]["id"]

    r_plan_b = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth(token_b), timeout=15)
    assert r_plan_b.status_code in (403, 404)

    r_lead_b = requests.get(f"{API}/leadgen/campaigns/{lead_campaign_id}", headers=_auth(token_b), timeout=15)
    assert r_lead_b.status_code in (403, 404)
