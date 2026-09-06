"""Analyst/KPI — test E2E HTTP (server live, MongoDB reale)."""
import pytest
import requests

from conftest import API_URL as API, register_tenant

TEST_PASSWORD = "AnalystTest!2026x"


def _register(company_name="Analyst Test Co"):
    return register_tenant(company_name, password=TEST_PASSWORD)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def shared_tenant():
    return _register()


def test_generate_report_senza_dati_dichiara_tutto_non_disponibile(shared_tenant):
    _, token = shared_tenant
    r = requests.post(f"{API}/analyst/reports", headers=_auth(token), timeout=15, json={"time_range_days": 30})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kpis"]["conversion_rate"]["reliability"] == "NON_DISPONIBILE"
    assert body["kpis"]["roas"]["missing_data"] is True
    assert len(body["insights"]) >= 1


def test_list_reports(shared_tenant):
    _, token = shared_tenant
    requests.post(f"{API}/analyst/reports", headers=_auth(token), timeout=15, json={"time_range_days": 7})
    r = requests.get(f"{API}/analyst/reports", headers=_auth(token), timeout=15)
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_get_report_by_id(shared_tenant):
    _, token = shared_tenant
    report = requests.post(f"{API}/analyst/reports", headers=_auth(token), timeout=15, json={"time_range_days": 30}).json()
    r = requests.get(f"{API}/analyst/reports/{report['id']}", headers=_auth(token), timeout=15)
    assert r.status_code == 200
    assert r.json()["id"] == report["id"]


def test_report_inesistente_404(shared_tenant):
    _, token = shared_tenant
    r = requests.get(f"{API}/analyst/reports/non-esiste", headers=_auth(token), timeout=15)
    assert r.status_code == 404


def test_isolamento_multi_tenant():
    _, token_a = _register("Analyst Tenant A")
    _, token_b = _register("Analyst Tenant B")
    report = requests.post(f"{API}/analyst/reports", headers=_auth(token_a), timeout=15, json={"time_range_days": 30}).json()
    r = requests.get(f"{API}/analyst/reports/{report['id']}", headers=_auth(token_b), timeout=15)
    assert r.status_code == 404


def test_insights_for_agent_endpoint(shared_tenant):
    _, token = shared_tenant
    requests.post(f"{API}/analyst/reports", headers=_auth(token), timeout=15, json={"time_range_days": 30})
    r = requests.get(f"{API}/analyst/insights/coordinatore-actelya", headers=_auth(token), timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_generate_report_richiede_ruolo_operatore_o_admin():
    r = requests.post(f"{API}/analyst/reports", timeout=15, json={"time_range_days": 30})
    assert r.status_code in (401, 403)
