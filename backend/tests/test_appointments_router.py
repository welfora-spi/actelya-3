"""Appointment Setter — test E2E HTTP (server live, MongoDB reale).

Un solo tenant condiviso (fixture 'shared_tenant', scope=module) per la
maggior parte dei test — stesso motivo di test_leadgen_router.py: evitare
di esaurire il rate limit reale su POST /tenant/register (deps.py, mai
indebolito per comodità dei test). Nessun provider calendario reale viene
mai contattato: senza credenziali reali configurate in questo ambiente, i
test qui coprono onestamente il percorso NON_CONFIGURATO end-to-end; il
percorso di prenotazione CONFERMATA con un fake adapter deterministico è
coperto a livello di pipeline (test_appointments_pipeline.py)."""
import pytest
import requests

from conftest import API_URL as API, register_tenant

TEST_PASSWORD = "ApptTest!2026x"


def _register(company_name="Appointments Test Co"):
    return register_tenant(company_name, password=TEST_PASSWORD)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def shared_tenant():
    return _register()


def _create_connection(token, provider_type="google_calendar", **extra):
    body = {"name": f"Connessione {provider_type}", "provider_type": provider_type, **extra}
    r = requests.post(f"{API}/appointments/connections", headers=_auth(token), timeout=15, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------- connessioni ----------------
def test_crea_connessione_senza_token_resta_non_configurato(shared_tenant):
    _, token = shared_tenant
    conn = _create_connection(token)
    assert conn["status"] == "NON_CONFIGURATO"
    assert "access_token_encrypted" not in conn  # segreto mai esposto


def test_crea_connessione_con_token_diventa_configurato(shared_tenant):
    _, token = shared_tenant
    conn = _create_connection(token, access_token="token-di-test-mai-reale")
    assert conn["status"] == "CONFIGURATO"


def test_crea_connessione_provider_non_supportato_rifiutata(shared_tenant):
    _, token = shared_tenant
    r = requests.post(f"{API}/appointments/connections", headers=_auth(token), timeout=15,
                      json={"name": "X", "provider_type": "provider-inventato"})
    assert r.status_code == 400


def test_lista_connessioni(shared_tenant):
    _, token = shared_tenant
    _create_connection(token, provider_type="microsoft_graph")
    r = requests.get(f"{API}/appointments/connections", headers=_auth(token), timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert any(c["provider_type"] == "microsoft_graph" for c in r.json())


def test_elimina_connessione(shared_tenant):
    _, token = shared_tenant
    conn = _create_connection(token)
    r = requests.delete(f"{API}/appointments/connections/{conn['id']}", headers=_auth(token), timeout=15)
    assert r.status_code == 200
    r2 = requests.get(f"{API}/appointments/connections", headers=_auth(token), timeout=15)
    assert not any(c["id"] == conn["id"] for c in r2.json())


# ---------------- OAuth (nessuna chiamata reale: app OAuth non configurata in questo ambiente) ----------------
def test_oauth_authorize_url_senza_app_configurata_e_non_configurato(shared_tenant):
    _, token = shared_tenant
    r = requests.get(f"{API}/appointments/connections/oauth/authorize-url",
                     params={"provider_type": "google_calendar"}, headers=_auth(token), timeout=15)
    assert r.status_code == 200
    assert r.json()["status"] == "NON_CONFIGURATO"


def test_oauth_callback_senza_app_configurata_risponde_502(shared_tenant):
    _, token = shared_tenant
    conn = _create_connection(token)
    r = requests.post(f"{API}/appointments/connections/{conn['id']}/oauth/callback",
                      params={"code": "un-codice-qualsiasi"}, headers=_auth(token), timeout=15)
    assert r.status_code == 502


# ---------------- test connessione ----------------
def test_test_connessione_non_configurata(shared_tenant):
    _, token = shared_tenant
    conn = _create_connection(token)
    r = requests.post(f"{API}/appointments/connections/{conn['id']}/test", headers=_auth(token), timeout=15)
    assert r.status_code == 200
    assert r.json()["status"] == "NON_CONFIGURATO"


# ---------------- disponibilità ----------------
def test_imposta_disponibilita(shared_tenant):
    _, token = shared_tenant
    conn = _create_connection(token)
    finestre = [{"weekday": 0, "start_time": "09:00", "end_time": "17:00"}]
    r = requests.put(f"{API}/appointments/connections/{conn['id']}/availability",
                     headers=_auth(token), timeout=15, json=finestre)
    assert r.status_code == 200, r.text
    assert r.json()["availability"] == finestre


# ---------------- proposte (senza connessione configurata: slot sempre vuoti, mai inventati) ----------------
def test_crea_proposta_lead_inesistente_rifiutata(shared_tenant):
    _, token = shared_tenant
    conn = _create_connection(token)
    r = requests.post(f"{API}/appointments/proposals", headers=_auth(token), timeout=15, json={
        "connection_id": conn["id"], "lead_id": "lead-mai-esistito", "lead_type": "aziende",
    })
    assert r.status_code == 404


def test_crea_proposta_connessione_non_configurata_produce_slot_vuoti(shared_tenant):
    _, token = shared_tenant
    conn = _create_connection(token)
    file_id = requests.post(f"{API}/leadgen/files", headers=_auth(token), timeout=15,
                            files={"upload": ("lead.csv", b"ragione_sociale\nAcme Srl\n", "text/csv")}).json()["id"]
    campaign_id = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token), timeout=15,
                                json={"name": "C"}).json()["id"]
    r = requests.post(f"{API}/leadgen/files/{file_id}/import", params={"campaign_id": campaign_id},
                      headers=_auth(token), timeout=15, json={"mapping": {"ragione_sociale": "ragione_sociale"}})
    job_id = r.json()["id"]
    import time
    deadline = time.time() + 20
    stato = None
    while time.time() < deadline:
        stato = requests.get(f"{API}/leadgen/import-jobs/{job_id}", headers=_auth(token), timeout=15).json()["status"]
        if stato in ("READY_FOR_APPROVAL", "REVIEW_REQUIRED", "FAILED", "PARTIAL"):
            break
        time.sleep(0.5)
    leads = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads", headers=_auth(token), timeout=15).json()
    lead_id = leads["items"][0]["id"]

    r = requests.post(f"{API}/appointments/proposals", headers=_auth(token), timeout=15, json={
        "connection_id": conn["id"], "lead_id": lead_id, "lead_type": "aziende", "campaign_id": campaign_id,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["proposed_slots"] == []
    assert body["status"] == "BOZZA"
    assert body["connection_configured"] is False


def test_approva_proposta_senza_slot_bloccata(shared_tenant):
    _, token = shared_tenant
    conn = _create_connection(token)
    file_id = requests.post(f"{API}/leadgen/files", headers=_auth(token), timeout=15,
                            files={"upload": ("lead2.csv", b"ragione_sociale\nBeta Srl\n", "text/csv")}).json()["id"]
    campaign_id = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token), timeout=15,
                                json={"name": "C2"}).json()["id"]
    job_id = requests.post(f"{API}/leadgen/files/{file_id}/import", params={"campaign_id": campaign_id},
                           headers=_auth(token), timeout=15,
                           json={"mapping": {"ragione_sociale": "ragione_sociale"}}).json()["id"]
    import time
    deadline = time.time() + 20
    while time.time() < deadline:
        stato = requests.get(f"{API}/leadgen/import-jobs/{job_id}", headers=_auth(token), timeout=15).json()["status"]
        if stato in ("READY_FOR_APPROVAL", "REVIEW_REQUIRED", "FAILED", "PARTIAL"):
            break
        time.sleep(0.5)
    leads = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads", headers=_auth(token), timeout=15).json()
    lead_id = leads["items"][0]["id"]

    proposta = requests.post(f"{API}/appointments/proposals", headers=_auth(token), timeout=15, json={
        "connection_id": conn["id"], "lead_id": lead_id, "lead_type": "aziende",
    }).json()
    r = requests.post(f"{API}/appointments/proposals/{proposta['id']}/approve", headers=_auth(token), timeout=15,
                      json={"approve": True})
    assert r.status_code == 409


def test_lista_proposte_paginata(shared_tenant):
    _, token = shared_tenant
    r = requests.get(f"{API}/appointments/proposals", params={"page": 1, "page_size": 5},
                     headers=_auth(token), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items", "total", "page", "page_size", "pages"}


def test_lista_prenotazioni_paginata(shared_tenant):
    _, token = shared_tenant
    r = requests.get(f"{API}/appointments/bookings", params={"page": 1, "page_size": 5},
                     headers=_auth(token), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items", "total", "page", "page_size", "pages"}


# ---------------- isolamento multi-tenant ----------------
def test_isolamento_multi_tenant(shared_tenant):
    _, token_a = shared_tenant
    _, token_b = _register("Appointments Tenant B")
    conn = _create_connection(token_a)
    r2 = requests.delete(f"{API}/appointments/connections/{conn['id']}", headers=_auth(token_b), timeout=15)
    assert r2.status_code == 404
    r3 = requests.post(f"{API}/appointments/connections/{conn['id']}/test", headers=_auth(token_b), timeout=15)
    assert r3.status_code == 404
