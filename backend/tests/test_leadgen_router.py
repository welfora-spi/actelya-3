"""Lead Generation Specialist — test E2E HTTP (server live, MongoDB reale).

Un solo tenant condiviso (fixture 'shared_tenant', scope=module) per la
maggior parte dei test: ogni test lavora comunque su una PROPRIA campagna/
file, quindi l'isolamento del singolo test non dipende dall'isolamento
dell'organizzazione. Registrare un tenant per test esaurirebbe rapidamente
il rate limit reale su POST /tenant/register (max 10/60s per IP, deps.py --
un controllo di sicurezza legittimo, mai indebolito per comodita' dei test).
Un secondo tenant viene registrato SOLO dal test che verifica davvero
l'isolamento multi-organizzazione."""
import time
import uuid

import pytest
import requests

from conftest import API_URL as API

TEST_PASSWORD = "LeadGenTest!2026x"


def _register(company_name="Lead Gen Test Co"):
    email = f"test_{uuid.uuid4().hex[:12]}@example.com"
    body = {
        "company_name": company_name, "sector": "Servizi", "website": "https://example.com",
        "social_links": [], "primary_goal": "Crescere",
        "first_name": "Test", "last_name": "User", "email": email, "password": TEST_PASSWORD,
    }
    r = requests.post(f"{API}/tenant/register", json=body, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    return data["organization_id"], data["access_token"]


@pytest.fixture(scope="module")
def shared_tenant():
    return _register()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _csv_bytes(righe=1):
    corpo = "ragione_sociale,email,settore,citta,dipendenti\n"
    for i in range(righe):
        corpo += f"Acme{i} Srl,info{i}@acme.it,software,Milano,50\n"
    return corpo.encode("utf-8")


def _upload(token, filename="lead.csv", content=None, content_type="text/csv"):
    content = content if content is not None else _csv_bytes()
    return requests.post(f"{API}/leadgen/files", headers=_auth(token), timeout=15,
                         files={"upload": (filename, content, content_type)})


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


# ---------------- upload ----------------
def test_upload_csv_valido(shared_tenant):
    _, token = shared_tenant
    r = _upload(token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "VALIDATO"
    assert "ragione_sociale" in body["columns"]
    assert body["suggested_mapping"]["ragione_sociale"] == "ragione_sociale"
    assert "storage_path" not in body  # mai il percorso filesystem esposto


def test_upload_idempotente_stesso_hash(shared_tenant):
    _, token = shared_tenant
    contenuto = _csv_bytes()
    r1 = _upload(token, content=contenuto)
    r2 = _upload(token, content=contenuto)
    assert r1.json()["id"] == r2.json()["id"]


def test_upload_estensione_non_supportata_rifiutato(shared_tenant):
    _, token = shared_tenant
    r = requests.post(f"{API}/leadgen/files", headers=_auth(token), timeout=15,
                      files={"upload": ("malware.exe", b"contenuto binario", "application/octet-stream")})
    assert r.status_code == 400


def test_upload_file_vuoto_rifiutato(shared_tenant):
    _, token = shared_tenant
    r = requests.post(f"{API}/leadgen/files", headers=_auth(token), timeout=15,
                      files={"upload": ("vuoto.csv", b"", "text/csv")})
    assert r.status_code == 400


def test_upload_xlsx_corrotto_produce_422_e_record_rifiutato(shared_tenant):
    _, token = shared_tenant
    r = requests.post(f"{API}/leadgen/files", headers=_auth(token), timeout=15,
                      files={"upload": ("corrotto.xlsx", b"non un vero xlsx", "application/octet-stream")})
    assert r.status_code == 422
    body = requests.get(f"{API}/leadgen/files", params={"status": "RIFIUTATO"}, headers=_auth(token), timeout=15).json()
    assert any(f["status"] == "RIFIUTATO" for f in body["items"])


def test_preview_file(shared_tenant):
    _, token = shared_tenant
    file_id = _upload(token).json()["id"]
    r = requests.get(f"{API}/leadgen/files/{file_id}/preview", headers=_auth(token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"][0] == "ragione_sociale"
    assert len(body["rows"]) >= 1


# ---------------- campagne + import ----------------
def test_flusso_completo_import_dedup_approve_export(shared_tenant):
    org_id, token = shared_tenant
    # Due aziende volutamente distinte (nomi/domini non simili): questo test
    # copre il percorso senza duplicati; il percorso con duplicati e' coperto
    # da test_duplicati_esatti_bloccano_approvazione_fino_a_decisione.
    contenuto = (
        "ragione_sociale,email,settore,citta,dipendenti\n"
        "Bright Software Srl,info@brightsoftware.it,software,Milano,50\n"
        "Coastal Hotels Group,info@coastalhotels.it,turismo,Napoli,120\n"
    ).encode("utf-8")
    file_id = _upload(token, content=contenuto).json()["id"]

    r = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token), timeout=15, json={
        "name": "Campagna Test", "channels": ["email"], "target_quantity": 10,
    })
    assert r.status_code == 200, r.text
    campaign_id = r.json()["id"]
    assert r.json()["status"] == "BOZZA"

    r = requests.post(f"{API}/leadgen/files/{file_id}/import",
                      params={"campaign_id": campaign_id}, headers=_auth(token), timeout=15,
                      json={"mapping": {"ragione_sociale": "ragione_sociale", "email": "email",
                                       "settore": "settore", "citta": "citta", "dipendenti": "dipendenti"}})
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]

    stato = _wait_job(token, job_id)
    assert stato in ("READY_FOR_APPROVAL", "REVIEW_REQUIRED")

    r = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads", headers=_auth(token), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert all("id" in item for item in body["items"])

    # Nessun duplicato in questo CSV (righe distinte): approvazione diretta.
    r = requests.post(f"{API}/leadgen/campaigns/{campaign_id}/approve", headers=_auth(token), timeout=15,
                      json={"approve": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVATA"

    r = requests.post(f"{API}/leadgen/campaigns/{campaign_id}/export", headers=_auth(token), timeout=15,
                      json={"campaign_id": campaign_id, "format": "csv"})
    assert r.status_code == 200, r.text
    assert b"ragione_sociale" in r.content

    r = requests.post(f"{API}/leadgen/campaigns/{campaign_id}/handoff", headers=_auth(token), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "lead_handoff_package"


def test_export_bloccato_prima_dellapprovazione(shared_tenant):
    _, token = shared_tenant
    file_id = _upload(token).json()["id"]
    campaign_id = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token), timeout=15,
                                json={"name": "C"}).json()["id"]
    requests.post(f"{API}/leadgen/files/{file_id}/import", params={"campaign_id": campaign_id},
                  headers=_auth(token), timeout=15, json={"mapping": {"ragione_sociale": "ragione_sociale"}})
    r = requests.post(f"{API}/leadgen/campaigns/{campaign_id}/export", headers=_auth(token), timeout=15,
                      json={"campaign_id": campaign_id, "format": "csv"})
    assert r.status_code == 409


def test_import_idempotente_stesso_file_stessa_campagna_stesso_mapping(shared_tenant):
    _, token = shared_tenant
    file_id = _upload(token).json()["id"]
    campaign_id = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token), timeout=15,
                                json={"name": "C"}).json()["id"]
    mapping = {"mapping": {"ragione_sociale": "ragione_sociale"}}
    r1 = requests.post(f"{API}/leadgen/files/{file_id}/import", params={"campaign_id": campaign_id},
                       headers=_auth(token), timeout=15, json=mapping)
    r2 = requests.post(f"{API}/leadgen/files/{file_id}/import", params={"campaign_id": campaign_id},
                       headers=_auth(token), timeout=15, json=mapping)
    assert r1.json()["id"] == r2.json()["id"]


# ---------------- duplicati ----------------
def test_duplicati_esatti_bloccano_approvazione_fino_a_decisione(shared_tenant):
    _, token = shared_tenant
    contenuto = ("ragione_sociale,dominio\nAcme Srl,acme.it\nAcme Bis,acme.it\n").encode("utf-8")
    file_id = _upload(token, content=contenuto).json()["id"]
    campaign_id = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token), timeout=15,
                                json={"name": "C"}).json()["id"]
    r = requests.post(f"{API}/leadgen/files/{file_id}/import", params={"campaign_id": campaign_id},
                      headers=_auth(token), timeout=15,
                      json={"mapping": {"ragione_sociale": "ragione_sociale", "dominio": "dominio"}})
    job_id = r.json()["id"]
    stato = _wait_job(token, job_id)
    assert stato == "REVIEW_REQUIRED"

    r = requests.post(f"{API}/leadgen/campaigns/{campaign_id}/approve", headers=_auth(token), timeout=15,
                      json={"approve": True})
    assert r.status_code == 409

    dup = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/duplicates", headers=_auth(token), timeout=15).json()
    assert dup["total"] == 1
    assert len(dup["items"]) == 1
    r = requests.post(f"{API}/leadgen/duplicates/{dup['items'][0]['id']}/decision", headers=_auth(token), timeout=15,
                      json={"action": "KEEP_SEPARATE"})
    assert r.status_code == 200

    r = requests.post(f"{API}/leadgen/campaigns/{campaign_id}/approve", headers=_auth(token), timeout=15,
                      json={"approve": True})
    assert r.status_code == 200


# ---------------- ricerca prospect ----------------
def test_search_senza_url_esplicite_non_disponibile_ma_dati_interni_ok(shared_tenant):
    _, token = shared_tenant
    campaign_id = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token), timeout=15,
                                json={"name": "C"}).json()["id"]
    r = requests.post(f"{API}/leadgen/search", headers=_auth(token), timeout=15,
                      json={"campaign_id": campaign_id, "query": "hotel Nord Italia"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sources"]["web_pubblico"]["status"] == "NON_DISPONIBILE"
    assert body["sources"]["dati_interni"]["status"] == "OK"
    assert body["sources"]["provider_commerciale"]["status"] == "NON_DISPONIBILE"


# ---------------- isolamento multi-tenant ----------------
def test_isolamento_multi_tenant_file_e_campagne():
    _, token_a = _register("Tenant A")
    _, token_b = _register("Tenant B")
    file_id = _upload(token_a).json()["id"]
    campaign_id = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token_a), timeout=15,
                                json={"name": "C"}).json()["id"]

    r = requests.get(f"{API}/leadgen/files/{file_id}", headers=_auth(token_b), timeout=15)
    assert r.status_code == 404
    r = requests.get(f"{API}/leadgen/campaigns/{campaign_id}", headers=_auth(token_b), timeout=15)
    assert r.status_code == 404
    r = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads", headers=_auth(token_b), timeout=15)
    assert r.status_code == 404


# ---------------- delete ----------------
def test_delete_file(shared_tenant):
    _, token = shared_tenant
    file_id = _upload(token).json()["id"]
    r = requests.delete(f"{API}/leadgen/files/{file_id}", headers=_auth(token), timeout=15)
    assert r.status_code == 200
    r = requests.get(f"{API}/leadgen/files/{file_id}", headers=_auth(token), timeout=15)
    assert r.status_code == 404
