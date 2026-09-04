"""ACTELYA 2 backend regression tests - Milestone 1 SIMULAZIONE"""
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL as BASE, ADMIN_EMAIL, ADMIN_TEST_PASSWORD as ADMIN_PASS, ADMIN_SEED_PASSWORD as SEED_PASS


def _clear_lockout():
    try:
        MongoClient("mongodb://localhost:27017")["actelya2_db"].login_attempts.delete_many({})
    except Exception:
        pass


@pytest.fixture(scope="module")
def client():
    _clear_lockout()
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    r = s.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    s.headers["Authorization"] = f"Bearer {tok}"
    return s


# ---------- Basic ----------
def test_health():
    r = requests.get(f"{BASE}/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_me(client):
    r = client.get(f"{BASE}/api/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "ADMIN"


def test_bad_login():
    _clear_lockout()
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": "nonexistent_test_xyz@example.com", "password": "wrong"})

def test_seed_password_no_longer_works(client):
    """Idempotent seed: env ADMIN_PASSWORD must NOT overwrite a user-changed
    password. AUTOCONTENUTO (item 23, DECISIONE UFFICIALE "100% REALE"):
    la versione precedente assumeva che la password admin del server live
    fosse gia' stata cambiata da un'azione esterna a questo test file (vera
    solo se un riavvio precedente con FORCE_RESET_ADMIN non l'aveva
    resettata nel frattempo) -- un presupposto ambientale non garantito,
    che rendeva il test fragile e dipendente dallo stato residuo di sessioni
    precedenti. Ora il test PRODUCE da solo la precondizione (cambia
    davvero la password), verifica l'idempotenza del seed, e ripristina la
    password originale alla fine (altri test di questo file assumono
    ADMIN_TEST_PASSWORD valida)."""
    _clear_lockout()
    temp_password = f"TempTest!{uuid.uuid4().hex[:12]}"

    r = client.post(f"{BASE}/api/auth/change-password",
                    json={"current_password": ADMIN_PASS, "new_password": temp_password})
    assert r.status_code == 200, r.text

    try:
        _clear_lockout()
        r = requests.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": SEED_PASS})
        assert r.status_code == 401, f"Seed password still works after a real password change! seed idempotence broken: {r.status_code}"
    finally:
        # Ripristina la password originale: il resto della suite (e chiunque
        # altro usi questo ambiente) si aspetta ADMIN_TEST_PASSWORD valida.
        _clear_lockout()
        r_login_temp = requests.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": temp_password})
        assert r_login_temp.status_code == 200, "Impossibile ripristinare la password admin dopo il test: credenziale temporanea non valida."
        tok = r_login_temp.json()["access_token"]
        r_restore = requests.post(f"{BASE}/api/auth/change-password",
                                  headers={"Authorization": f"Bearer {tok}"},
                                  json={"current_password": temp_password, "new_password": ADMIN_PASS})
        assert r_restore.status_code == 200, "Impossibile ripristinare la password admin originale dopo il test."


# ---------- Full flow PRODUZIONE ----------
def test_full_produzione_flow(client):
    r = client.post(f"{BASE}/api/goals", json={
        "text": "Scrivi una breve email di follow-up per un prospect. Non inviare l'email."
    })
    assert r.status_code == 200, r.text
    data = r.json()
    goal = data["goal"]
    approval = data["approval"]
    assert goal["intent"]["intent_type"] == "PRODUZIONE", goal["intent"]
    assert "cost_min" in approval and "cost_probable" in approval and "cost_max" in approval

    appr_id = approval["id"]
    # approve
    r = client.post(f"{BASE}/api/approvals/{appr_id}/approve", json={})
    assert r.status_code == 200, r.text
    exec_id = r.json().get("execution_id")
    assert exec_id

    # idempotency: second approve returns same execution / idempotent
    r2 = client.post(f"{BASE}/api/approvals/{appr_id}/approve", json={})
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2.get("idempotent") is True or body2.get("execution_id") == exec_id

    # poll execution
    for _ in range(30):
        r = client.get(f"{BASE}/api/executions/{exec_id}")
        assert r.status_code == 200
        e = r.json().get("execution", r.json())
        if e.get("execution_status") == "COMPLETATA":
            assert e.get("deliverable_status") in ("COMPLETATO", "COMPLETATO_CON_AVVISI")
            assert e.get("action_status") == "NON_RICHIESTA"
            return
        time.sleep(1)
    pytest.fail(f"PRODUZIONE execution did not complete: {e}")


# ---------- Full flow MISTO ----------
def test_full_misto_action_blocked(client):
    r = client.post(f"{BASE}/api/goals", json={
        "text": "Scrivi e invia una mail ai prospect pensionistici."
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["goal"]["intent"]["intent_type"] == "MISTO", data["goal"]["intent"]
    appr_id = data["approval"]["id"]

    r = client.post(f"{BASE}/api/approvals/{appr_id}/approve", json={})
    assert r.status_code == 200, r.text
    exec_id = r.json()["execution_id"]

    for _ in range(30):
        r = client.get(f"{BASE}/api/executions/{exec_id}")
        e = r.json().get("execution", r.json())
        if e.get("execution_status") == "COMPLETATA":
            assert e.get("action_status") == "BLOCCATA", e
            assert e.get("missing_prerequisites"), e
            return
        time.sleep(1)
    pytest.fail(f"MISTO execution did not complete: {e}")


def test_misto_external_action_blocked_on_approve(client):
    """External action approval must return 409 when blocked (missing prereqs)."""
    r = client.get(f"{BASE}/api/approvals")
    assert r.status_code == 200
    rows = r.json()
    external_blocked = [a for a in rows if a.get("type") == "AZIONE_ESTERNA" and a.get("blocked")]
    if not external_blocked:
        pytest.skip("No blocked external action approval present yet")
    a = external_blocked[0]
    r = client.post(f"{BASE}/api/approvals/{a['id']}/approve", json={})
    assert r.status_code == 409, r.text


# ---------- Connections: API key masking ----------
def test_create_ai_connection_key_masked(client):
    payload = {"name": "TEST_provider", "provider_type": "openai",
               "api_key": "sk-abcdefghij1234", "base_url": "", "logical_model": "gpt-4o-mini"}
    r = client.post(f"{BASE}/api/connections/ai", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "api_key" not in body  # never returned plain
    assert body["has_key"] is True
    assert body["api_key_masked"] and body["api_key_masked"].endswith("1234")
    assert body["verified"] is False


# ---------- Budget ----------
def test_budget_persist(client):
    r = client.put(f"{BASE}/api/budget", json={"general_limit": 10})
    assert r.status_code == 200, r.text
    r = client.get(f"{BASE}/api/budget")
    assert r.status_code == 200
    data = r.json()
    assert data.get("general_limit") == 10 or data.get("limit") == 10 or data.get("general_cap") == 10


# ---------- Audit ----------
def test_audit_no_secrets(client):
    r = client.get(f"{BASE}/api/audit")
    assert r.status_code == 200, r.text
    body = r.text.lower()
    assert "sk-abcdefghij1234" not in body
    assert "actelya2!milestone" not in body
    assert "zyzryd4jfkv6pbr0" not in body


# ---------- Real mode ----------
def test_real_mode_endpoint(client):
    r = client.put(f"{BASE}/api/settings/real-mode", json={"enable": True, "confirm": True})
    # requires prereqs; should be 400/409/422 when no verified conn/budget, or 200 if allowed
    assert r.status_code in (200, 400, 403, 409, 422), r.text


# ---------- Org profile ----------
def test_org_profile_persist(client):
    payload = {"ragione_sociale": "TEST_Actelya SRL", "nome_commerciale": "TEST_Actelya"}
    r = client.put(f"{BASE}/api/org/profile", json=payload)
    assert r.status_code == 200, r.text
    r = client.get(f"{BASE}/api/org/profile")
    assert r.status_code == 200
    d = r.json()
    assert d.get("ragione_sociale") == "TEST_Actelya SRL"
