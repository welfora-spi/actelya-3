"""Blocco 4 — Test end-to-end HTTP (RBAC, idempotenza, esecuzione, reject, stop, isolamento).
Usa il server live tramite REACT_APP_BACKEND_URL. NON modifica l'admin owner:
crea utenti TEST_ dedicati per OPERATORE/APPROVATORE/SOLA_LETTURA."""
import os
import uuid
import time
import pytest
import requests

def _load_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if not url:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    assert url, "REACT_APP_BACKEND_URL non definito"
    return url.rstrip("/")

BASE_URL = _load_base_url()
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "raffaelepatarino77@gmail.com"
ADMIN_PASSWORD = "Actelya2!Milestone"

INITIAL_PWD = "TempPass!12345"
FINAL_PWD = "Actelya!Test2025"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    return r


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_token():
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200, f"login admin: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _ensure_user(admin_token, role, tag):
    """Crea o riusa (via login) un utente TEST_ con ruolo dato e password FINAL_PWD."""
    email = f"test_{tag}_{role.lower()}@example.com"
    # Prova login diretto con FINAL_PWD (utente esistente)
    r = _login(email, FINAL_PWD)
    if r.status_code == 200:
        return email, r.json()["access_token"]
    # Crea nuovo
    payload = {"first_name": "Test", "last_name": role, "email": email,
               "role": role, "password": INITIAL_PWD, "active": True}
    cr = requests.post(f"{API}/users", json=payload, headers=_auth_headers(admin_token), timeout=15)
    assert cr.status_code in (200, 201, 400), f"create user: {cr.status_code} {cr.text}"
    # Login iniziale con INITIAL_PWD
    r = _login(email, INITIAL_PWD)
    assert r.status_code == 200, f"login iniziale: {r.status_code} {r.text}"
    tok = r.json()["access_token"]
    # Cambia password (must_change_password=True al primo login)
    cp = requests.post(f"{API}/auth/change-password",
                       json={"current_password": INITIAL_PWD, "new_password": FINAL_PWD},
                       headers=_auth_headers(tok), timeout=15)
    assert cp.status_code == 200, f"change-password: {cp.status_code} {cp.text}"
    # Re-login con nuova password
    r2 = _login(email, FINAL_PWD)
    assert r2.status_code == 200, f"re-login: {r2.status_code} {r2.text}"
    return email, r2.json()["access_token"]


@pytest.fixture(scope="module")
def op_token(admin_token):
    _, tok = _ensure_user(admin_token, "OPERATORE", "b4")
    return tok


@pytest.fixture(scope="module")
def appr_token(admin_token):
    _, tok = _ensure_user(admin_token, "APPROVATORE", "b4")
    return tok


@pytest.fixture(scope="module")
def ro_token(admin_token):
    _, tok = _ensure_user(admin_token, "SOLA_LETTURA", "b4")
    return tok


def _create_plan(token, text):
    return requests.post(f"{API}/m2/plans", json={"text": text},
                         headers=_auth_headers(token), timeout=20)


# ---------------- 0. Auth base ----------------
def test_no_token_returns_401():
    r = requests.post(f"{API}/m2/plans", json={"text": "x"}, timeout=10)
    assert r.status_code in (401, 403)


# ---------------- 1. RBAC creazione ----------------
def test_ro_cannot_create_plan(ro_token):
    r = _create_plan(ro_token, "Prepara una campagna social e adv per il lancio")
    assert r.status_code == 403, r.text


def test_operatore_can_create_plan(op_token):
    r = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("requires_clarification") is not True
    plan = body["plan"]
    assert plan["plan_status"] == "IN_ATTESA_APPROVAZIONE"
    assert plan.get("organization_id")


def test_ambiguous_text_requires_clarification(op_token):
    r = _create_plan(op_token, "Fai qualcosa di utile")
    assert r.status_code == 200, r.text
    assert r.json().get("requires_clarification") is True


# ---------------- 2. RBAC approvazione ----------------
def test_operatore_cannot_approve_plan(op_token):
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    plan_id = cr.json()["plan"]["id"]
    r = requests.post(f"{API}/m2/plans/{plan_id}/approve",
                      headers=_auth_headers(op_token), timeout=15)
    assert r.status_code == 403, r.text


def test_ro_cannot_approve_plan(op_token, ro_token):
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    plan_id = cr.json()["plan"]["id"]
    r = requests.post(f"{API}/m2/plans/{plan_id}/approve",
                      headers=_auth_headers(ro_token), timeout=15)
    assert r.status_code == 403, r.text


# ---------------- 3. Approvazione parziale ----------------
def test_partial_approval(op_token, appr_token):
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    plan = cr.json()["plan"]
    plan_id = plan["id"]
    # get tasks
    g = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth_headers(op_token), timeout=15)
    assert g.status_code == 200
    tasks = sorted(g.json()["tasks"], key=lambda t: t["seq"])
    assert len(tasks) == 5
    t1_id = tasks[0]["id"]
    r = requests.post(f"{API}/m2/plans/{plan_id}/tasks/{t1_id}/approve",
                      headers=_auth_headers(appr_token), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["plan_status"] == "APPROVATO_PARZIALE"
    g2 = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth_headers(op_token), timeout=15).json()
    tasks2 = {t["seq"]: t for t in g2["tasks"]}
    assert tasks2[1]["task_status"] == "IN_CODA"
    assert tasks2[2]["task_status"] == "IN_ATTESA_APPROVAZIONE"


# ---------------- 4. Approvazione completa + idempotenza execution ----------------
def test_full_approval_idempotent_execution(op_token, appr_token):
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    plan_id = cr.json()["plan"]["id"]
    r1 = requests.post(f"{API}/m2/plans/{plan_id}/approve",
                       headers=_auth_headers(appr_token), timeout=15)
    assert r1.status_code == 200, r1.text
    ex1 = r1.json()["execution_id"]
    # secondo approve -> stessa execution
    r2 = requests.post(f"{API}/m2/plans/{plan_id}/approve",
                       headers=_auth_headers(appr_token), timeout=15)
    assert r2.status_code == 200, r2.text
    ex2 = r2.json()["execution_id"]
    assert ex1 == ex2
    g = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth_headers(op_token), timeout=15).json()
    assert g["execution"]["id"] == ex1
    assert g["plan"]["plan_status"] == "APPROVATO"


# ---------------- 5. Esecuzione tick fino a COMPLETATO ----------------
def test_tick_runs_to_completion(op_token, appr_token):
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    plan_id = cr.json()["plan"]["id"]
    ar = requests.post(f"{API}/m2/plans/{plan_id}/approve",
                       headers=_auth_headers(appr_token), timeout=15)
    assert ar.status_code == 200
    # eseguo tick piu' volte per far avanzare la DAG
    for _ in range(10):
        tr = requests.post(f"{API}/m2/plans/{plan_id}/tick",
                           headers=_auth_headers(op_token), timeout=20)
        assert tr.status_code == 200, tr.text
        g = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth_headers(op_token), timeout=15).json()
        if g["plan"]["plan_status"] in ("COMPLETATO", "BLOCCATO"):
            break
    assert g["plan"]["plan_status"] == "COMPLETATO", g["plan"]["plan_status"]
    assert all(t["task_status"] == "COMPLETATA" for t in g["tasks"])
    assert g["execution"]["execution_status"] == "COMPLETATA"
    assert g["execution"]["mode"] == "SIMULAZIONE"


# ---------------- 6. Reject task ----------------
def test_reject_without_reason_returns_422(op_token, appr_token):
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    plan_id = cr.json()["plan"]["id"]
    g = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth_headers(op_token), timeout=15).json()
    t2 = [t for t in g["tasks"] if t["seq"] == 2][0]
    # senza body
    r = requests.post(f"{API}/m2/plans/{plan_id}/tasks/{t2['id']}/reject",
                      headers=_auth_headers(appr_token), timeout=15)
    assert r.status_code == 422, r.text
    # reason vuoto
    r2 = requests.post(f"{API}/m2/plans/{plan_id}/tasks/{t2['id']}/reject",
                      json={"reason": "   "}, headers=_auth_headers(appr_token), timeout=15)
    assert r2.status_code == 422, r2.text


def test_operatore_cannot_reject(op_token):
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    plan_id = cr.json()["plan"]["id"]
    g = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth_headers(op_token), timeout=15).json()
    t1 = [t for t in g["tasks"] if t["seq"] == 1][0]
    r = requests.post(f"{API}/m2/plans/{plan_id}/tasks/{t1['id']}/reject",
                      json={"reason": "nope"}, headers=_auth_headers(op_token), timeout=15)
    assert r.status_code == 403, r.text


def test_reject_blocks_dependents_and_preserves_deliverables(op_token, appr_token):
    """Approvazione parziale del solo t1 -> lo eseguiamo (tick) -> reject t2 (ancora
    IN_ATTESA_APPROVAZIONE). Il deliverable di t1 NON deve essere cancellato."""
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    plan_id = cr.json()["plan"]["id"]
    g0 = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth_headers(op_token), timeout=15).json()
    tasks0 = {t["seq"]: t for t in g0["tasks"]}
    # Approva SOLO t1 (parziale) e tick -> t1 completa con deliverable
    ar = requests.post(f"{API}/m2/plans/{plan_id}/tasks/{tasks0[1]['id']}/approve",
                      headers=_auth_headers(appr_token), timeout=15)
    assert ar.status_code == 200
    tr = requests.post(f"{API}/m2/plans/{plan_id}/tick",
                      headers=_auth_headers(op_token), timeout=20)
    assert tr.status_code == 200
    g = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth_headers(op_token), timeout=15).json()
    tasks = {t["seq"]: t for t in g["tasks"]}
    assert tasks[1]["task_status"] == "COMPLETATA"
    assert tasks[1].get("deliverable_id"), "deliverable prodotto per t1"
    deliv_id_t1 = tasks[1]["deliverable_id"]
    # Rifiuta t2 (ancora IN_ATTESA_APPROVAZIONE)
    assert tasks[2]["task_status"] == "IN_ATTESA_APPROVAZIONE"
    r = requests.post(f"{API}/m2/plans/{plan_id}/tasks/{tasks[2]['id']}/reject",
                     json={"reason": "Contenuto non conforme"},
                     headers=_auth_headers(appr_token), timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["reason"] == "Contenuto non conforme"
    g2 = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth_headers(op_token), timeout=15).json()
    tasks2 = {t["seq"]: t for t in g2["tasks"]}
    assert tasks2[1]["task_status"] == "COMPLETATA"          # preservato
    assert tasks2[1]["deliverable_id"] == deliv_id_t1        # deliverable non cancellato
    assert tasks2[2]["task_status"] == "BLOCCATA"
    # t3 e t4 (dipendono da t2) -> SALTATA (propagazione)
    assert tasks2[3]["task_status"] == "SALTATA"


# ---------------- 7. Stop manuale (solo ADMIN) ----------------
def test_stop_requires_admin_and_blocks_execution(op_token, appr_token, admin_token):
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    plan_id = cr.json()["plan"]["id"]
    requests.post(f"{API}/m2/plans/{plan_id}/approve",
                  headers=_auth_headers(appr_token), timeout=15)
    # operatore/approvatore NON possono fare stop
    r_op = requests.post(f"{API}/m2/plans/{plan_id}/stop",
                         headers=_auth_headers(op_token), timeout=15)
    assert r_op.status_code == 403
    r_ap = requests.post(f"{API}/m2/plans/{plan_id}/stop",
                         headers=_auth_headers(appr_token), timeout=15)
    assert r_ap.status_code == 403
    # admin -> ok
    r_ad = requests.post(f"{API}/m2/plans/{plan_id}/stop",
                         headers=_auth_headers(admin_token), timeout=15)
    assert r_ad.status_code == 200, r_ad.text
    # tick dopo stop -> nessun task completato
    tr = requests.post(f"{API}/m2/plans/{plan_id}/tick",
                       headers=_auth_headers(op_token), timeout=15)
    assert tr.status_code == 200
    body = tr.json()
    assert body.get("stopped") is True or body.get("processed") == 0
    g = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth_headers(op_token), timeout=15).json()
    completed = [t for t in g["tasks"] if t["task_status"] == "COMPLETATA"]
    assert len(completed) == 0


# ---------------- 8. Nessun segreto in response ----------------
def test_no_secrets_in_responses(op_token, appr_token):
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    body = cr.json()
    text = str(body).lower()
    for forbidden in ("password", "api_key", "access_token", "secret"):
        assert forbidden not in text, f"segreto potenzialmente presente: {forbidden}"
    plan_id = body["plan"]["id"]
    g = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth_headers(op_token), timeout=15).json()
    gtext = str(g).lower()
    for forbidden in ("password", "api_key", "access_token", "secret"):
        assert forbidden not in gtext, f"segreto potenzialmente presente in GET plan: {forbidden}"
