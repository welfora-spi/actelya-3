"""Sales Agent — test E2E HTTP (server live, MongoDB reale): handoff da un
lead reale PRONTO_PER_SALES, delega del messaggio a Content Creator, guardrail
di stato/RBAC/isolamento tenant. Nessuna chiamata reale a Requesty (la
generazione del messaggio resta responsabilità di Content Creator, testata
altrove)."""
import time

import pytest
import requests

from conftest import API_URL as API, register_tenant

TEST_PASSWORD = "SalesTest!2026x"


def _register(company_name="Sales Test Co"):
    return register_tenant(company_name, password=TEST_PASSWORD)


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


def _lead_pronto_per_sales(token):
    """Azienda con email e ICP coerente: deve risultare PRONTO_PER_SALES."""
    contenuto = (
        "ragione_sociale,email,settore,citta,dipendenti,sito\n"
        "Acme Srl,info@acme.it,software,Milano,50,https://acme.it\n"
    ).encode("utf-8")
    file_id = requests.post(f"{API}/leadgen/files", headers=_auth(token), timeout=15,
                            files={"upload": ("lead.csv", contenuto, "text/csv")}).json()["id"]
    campaign_id = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token), timeout=15, json={
        "name": "Campagna sales", "channels": ["email"],
        "icp": {"settori_inclusi": ["software"], "localita": ["Milano"]},
    }).json()["id"]
    job = requests.post(f"{API}/leadgen/files/{file_id}/import", params={"campaign_id": campaign_id},
                        headers=_auth(token), timeout=15, json={
                            "mapping": {"ragione_sociale": "ragione_sociale", "email": "email", "settore": "settore",
                                       "citta": "citta", "dipendenti": "dipendenti", "sito": "sito"},
                        }).json()
    _wait_job(token, job["id"])
    leads = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads", headers=_auth(token), timeout=15).json()
    return leads["items"][0]


def test_create_opportunity_end_to_end_e_richiesta_messaggio():
    _, token = _register()
    lead = _lead_pronto_per_sales(token)
    assert lead["next_action"]["azione"] == "PRONTO_PER_SALES"

    r = requests.post(f"{API}/sales/opportunities", headers=_auth(token), timeout=15,
                      json={"lead_id": lead["id"], "lead_type": "aziende"})
    assert r.status_code == 200, r.text
    opp = r.json()
    assert opp["stage"] == "QUALIFICATO"

    r2 = requests.post(f"{API}/sales/opportunities/{opp['id']}/request-message", headers=_auth(token), timeout=15, json={})
    assert r2.status_code == 200, r2.text
    assert r2.json()["message_content_item_id"]

    r3 = requests.get(f"{API}/sales/opportunities/{opp['id']}/message-status", headers=_auth(token), timeout=15)
    assert r3.status_code == 200
    assert r3.json()["message_status"] == "BOZZA"


def test_create_opportunity_lead_non_pronto_409():
    _, token = _register()
    contenuto = "ragione_sociale\nAcme Incompleta Srl\n".encode("utf-8")
    file_id = requests.post(f"{API}/leadgen/files", headers=_auth(token), timeout=15,
                            files={"upload": ("lead.csv", contenuto, "text/csv")}).json()["id"]
    campaign_id = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token), timeout=15, json={
        "name": "Campagna incompleta", "channels": ["email"],
    }).json()["id"]
    job = requests.post(f"{API}/leadgen/files/{file_id}/import", params={"campaign_id": campaign_id},
                        headers=_auth(token), timeout=15,
                        json={"mapping": {"ragione_sociale": "ragione_sociale"}}).json()
    _wait_job(token, job["id"])
    leads = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads", headers=_auth(token), timeout=15).json()
    lead = leads["items"][0]
    assert lead["next_action"]["azione"] != "PRONTO_PER_SALES"

    r = requests.post(f"{API}/sales/opportunities", headers=_auth(token), timeout=15,
                      json={"lead_id": lead["id"], "lead_type": "aziende"})
    assert r.status_code == 409


def test_mark_contacted_senza_messaggio_approvato_409():
    _, token = _register()
    lead = _lead_pronto_per_sales(token)
    opp = requests.post(f"{API}/sales/opportunities", headers=_auth(token), timeout=15,
                        json={"lead_id": lead["id"], "lead_type": "aziende"}).json()
    requests.post(f"{API}/sales/opportunities/{opp['id']}/request-message", headers=_auth(token), timeout=15, json={})
    r = requests.post(f"{API}/sales/opportunities/{opp['id']}/mark-contacted", headers=_auth(token), timeout=15)
    assert r.status_code == 409


def test_record_response_tipo_sconosciuto_400():
    _, token = _register()
    lead = _lead_pronto_per_sales(token)
    opp = requests.post(f"{API}/sales/opportunities", headers=_auth(token), timeout=15,
                        json={"lead_id": lead["id"], "lead_type": "aziende"}).json()
    r = requests.post(f"{API}/sales/opportunities/{opp['id']}/record-response", headers=_auth(token), timeout=15,
                      json={"response_type": "TIPO-INESISTENTE", "note": ""})
    assert r.status_code == 400


def test_opportunita_inesistente_404():
    _, token = _register()
    r = requests.get(f"{API}/sales/opportunities/non-esiste", headers=_auth(token), timeout=15)
    assert r.status_code == 404


def test_isolamento_multi_tenant():
    _, token_a = _register("Sales Tenant A")
    _, token_b = _register("Sales Tenant B")
    lead = _lead_pronto_per_sales(token_a)
    opp = requests.post(f"{API}/sales/opportunities", headers=_auth(token_a), timeout=15,
                        json={"lead_id": lead["id"], "lead_type": "aziende"}).json()
    r = requests.get(f"{API}/sales/opportunities/{opp['id']}", headers=_auth(token_b), timeout=15)
    assert r.status_code == 404


def test_lista_paginata():
    _, token = _register()
    r = requests.get(f"{API}/sales/opportunities", headers=_auth(token), params={"page": 1, "page_size": 5}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "total" in body
