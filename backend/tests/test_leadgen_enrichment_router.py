"""Lead Generation — test E2E HTTP del ciclo di arricchimento per-lead
(server live, MongoDB reale). Nessun provider reale: il risultato applicato
qui simula quello che in futuro arriverà da un adapter reale del Tool
Registry (Apollo/Hunter/...) — la logica applicativa (validazione,
normalizzazione, conflitti, ricalcolo) è la stessa."""
import time

import pytest
import requests

from conftest import API_URL as API, register_tenant

TEST_PASSWORD = "LeadGenEnrichTest!2026x"


def _register(company_name="Lead Gen Enrichment Test Co"):
    return register_tenant(company_name, password=TEST_PASSWORD)


@pytest.fixture(scope="module")
def shared_tenant():
    return _register()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _wait_job(token, job_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{API}/leadgen/import-jobs/{job_id}", headers=_auth(token), timeout=15)
        assert r.status_code == 200, r.text
        stato = r.json()["status"]
        if stato in ("READY_FOR_APPROVAL", "REVIEW_REQUIRED", "FAILED", "PARTIAL"):
            return stato
        time.sleep(0.5)
    pytest.fail("Import job non completato entro il timeout")


def _importa_lead_senza_contatto(token):
    """Azienda senza email/telefono: next_action deve richiedere una
    capability di arricchimento prima di poter passare a Sales."""
    contenuto = "ragione_sociale,settore,citta,dipendenti\nAcme Srl,software,Milano,50\n".encode("utf-8")
    file_id = requests.post(f"{API}/leadgen/files", headers=_auth(token), timeout=15,
                            files={"upload": ("lead.csv", contenuto, "text/csv")}).json()["id"]
    campaign_id = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token), timeout=15, json={
        "name": "Campagna arricchimento", "channels": ["email"],
    }).json()["id"]
    job_id = requests.post(f"{API}/leadgen/files/{file_id}/import", params={"campaign_id": campaign_id},
                           headers=_auth(token), timeout=15, json={
                               "mapping": {"ragione_sociale": "ragione_sociale", "settore": "settore",
                                          "citta": "citta", "dipendenti": "dipendenti"},
                           }).json()
    _wait_job(token, job_id["id"])
    leads = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads", headers=_auth(token), timeout=15).json()
    return leads["items"][0]


def test_request_enrichment_e_applicazione_risultato_end_to_end(shared_tenant):
    _, token = shared_tenant
    lead = _importa_lead_senza_contatto(token)
    assert lead["next_action"]["azione"] == "CONTINUA_ENRICHMENT"
    assert "EMAIL_DISCOVERY" in lead["next_action"]["capability_richieste"]

    r = requests.post(f"{API}/leadgen/leads/aziende/{lead['id']}/request-enrichment",
                      headers=_auth(token), timeout=15)
    assert r.status_code == 200, r.text
    richiesta = r.json()
    assert richiesta["status"] == "IN_ATTESA"
    assert "EMAIL_DISCOVERY" in richiesta["capability_richieste"]

    r2 = requests.post(f"{API}/leadgen/enrichment-requests/{richiesta['id']}/apply-result",
                       headers=_auth(token), timeout=15,
                       json={"result_fields": {"email": "info@acme.it", "telefono": "0212345678"}, "source": "adapter-di-test"})
    assert r2.status_code == 200, r2.text
    esito = r2.json()
    assert esito["lead"]["email"]["value"] == "info@acme.it"
    assert esito["request"]["status"] == "COMPLETATA"


def test_request_enrichment_lead_inesistente_409(shared_tenant):
    _, token = shared_tenant
    r = requests.post(f"{API}/leadgen/leads/aziende/non-esiste/request-enrichment", headers=_auth(token), timeout=15)
    assert r.status_code == 409


def test_apply_result_richiesta_inesistente_404(shared_tenant):
    _, token = shared_tenant
    r = requests.post(f"{API}/leadgen/enrichment-requests/non-esiste/apply-result",
                      headers=_auth(token), timeout=15, json={"result_fields": {"email": "a@b.it"}})
    assert r.status_code == 404


def test_isolamento_multi_tenant_richiesta_arricchimento():
    _, token_a = _register("Lead Gen Enrichment Tenant A")
    _, token_b = _register("Lead Gen Enrichment Tenant B")
    lead = _importa_lead_senza_contatto(token_a)
    r = requests.post(f"{API}/leadgen/leads/aziende/{lead['id']}/request-enrichment",
                      headers=_auth(token_b), timeout=15)
    assert r.status_code == 409  # lead non trovato per il tenant B
