"""Professional Tool Registry — test HTTP live (server + MongoDB reali)."""
import pytest
import requests

from conftest import API_URL as API, register_tenant

TEST_PASSWORD = "ToolRegistryTest!2026x"


def _register(company_name="Tool Registry Test Co"):
    return register_tenant(company_name, password=TEST_PASSWORD)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def shared_tenant():
    return _register()


def test_lista_completa_registro(shared_tenant):
    _, token = shared_tenant
    r = requests.get(f"{API}/tool-registry", headers=_auth(token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["tools"]) == 63
    assert len(body["categories"]) == 22


def test_filtro_per_agente(shared_tenant):
    _, token = shared_tenant
    r = requests.get(f"{API}/tool-registry", params={"agent_id": "appointment-setter"}, headers=_auth(token), timeout=15)
    assert r.status_code == 200
    ids = {t["tool_id"] for t in r.json()["tools"]}
    assert "google_calendar" in ids
    assert "requesty_llm" not in ids


def test_filtro_per_categoria(shared_tenant):
    _, token = shared_tenant
    r = requests.get(f"{API}/tool-registry", params={"category": "crm"}, headers=_auth(token), timeout=15)
    assert r.status_code == 200
    tools = r.json()["tools"]
    assert len(tools) == 3
    assert all(t["category"] == "crm" for t in tools)


def test_dettaglio_singolo_strumento(shared_tenant):
    _, token = shared_tenant
    r = requests.get(f"{API}/tool-registry/google_calendar", headers=_auth(token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "Google Calendar API"
    assert body["code_complete"] is True
    assert "access_token" not in body and "client_secret" not in body  # nessun segreto, mai


def test_strumento_inesistente_404(shared_tenant):
    _, token = shared_tenant
    r = requests.get(f"{API}/tool-registry/provider-mai-esistito", headers=_auth(token), timeout=15)
    assert r.status_code == 404


def test_stato_riflette_connessione_reale_per_organizzazione(shared_tenant):
    _, token = shared_tenant
    requests.post(f"{API}/appointments/connections", headers=_auth(token), timeout=15, json={
        "name": "Test", "provider_type": "google_calendar", "access_token": "token-di-test",
    })
    r = requests.get(f"{API}/tool-registry/google_calendar", headers=_auth(token), timeout=15)
    assert r.json()["status"] == "CONFIGURATO"  # creato ma non ancora verificato con /test


def test_isolamento_multi_tenant_stato():
    # Tenant indipendenti (non lo shared_tenant, per non dipendere dall'ordine
    # di esecuzione degli altri test su questo file): A configura una
    # connessione calendario, B no.
    _, token_a = _register("Tool Registry Tenant A")
    _, token_b = _register("Tool Registry Tenant B")
    requests.post(f"{API}/appointments/connections", headers=_auth(token_a), timeout=15, json={
        "name": "Test", "provider_type": "microsoft_graph", "access_token": "token-di-test",
    })
    r_a = requests.get(f"{API}/tool-registry/microsoft_calendar", headers=_auth(token_a), timeout=15)
    r_b = requests.get(f"{API}/tool-registry/microsoft_calendar", headers=_auth(token_b), timeout=15)
    assert r_b.json()["status"] == "NON_CONFIGURATO"
    assert r_a.json()["status"] in ("CONFIGURATO", "VERIFICATO")


# ==================== Tool Execution Gateway: budget (Fase 1) ====================
def test_budget_default_nessun_tetto_configurato():
    _, token = _register("Tool Registry Budget Default Co")
    r = requests.get(f"{API}/tool-registry/budget", headers=_auth(token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["daily_cap_usd"] is None
    assert body["spent_today_usd"] == 0


def test_budget_impostazione_e_lettura():
    _, token = _register("Tool Registry Budget Set Co")
    r = requests.put(f"{API}/tool-registry/budget", headers=_auth(token), json={"daily_cap_usd": 25.0}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["daily_cap_usd"] == 25.0
    r2 = requests.get(f"{API}/tool-registry/budget", headers=_auth(token), timeout=15)
    assert r2.json()["daily_cap_usd"] == 25.0


def test_budget_negativo_rifiutato():
    _, token = _register("Tool Registry Budget Negative Co")
    r = requests.put(f"{API}/tool-registry/budget", headers=_auth(token), json={"daily_cap_usd": -1.0}, timeout=15)
    assert r.status_code == 400
