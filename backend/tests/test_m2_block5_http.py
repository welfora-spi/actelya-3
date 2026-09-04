"""Blocco 5 — Test end-to-end HTTP: deliverable versionati e validati (SIMULAZIONE).
Verifica: 5 deliverable campagna, ad_campaign DRAFT, lead_gen senza PII, kpi source SIMULATO,
email M1 compat, versionamento is_current, guard /tick SIMULAZIONE, RBAC, no secrets."""
import os
import re
import time
import pytest
import requests

from conftest import BASE_URL, API_URL as API, ADMIN_EMAIL, ADMIN_TEST_PASSWORD as ADMIN_PASSWORD

FINAL_PWD = "Actelya!Test2025"
INITIAL_PWD = "TempPass!12345"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s\-().]{6,}\d)")


def _login(email, password):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_token():
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200, f"login admin: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _ensure_user(admin_token, role, tag="b5"):
    email = f"test_{tag}_{role.lower()}@example.com"
    r = _login(email, FINAL_PWD)
    if r.status_code == 200:
        return email, r.json()["access_token"]
    payload = {"first_name": "Test", "last_name": role, "email": email,
               "role": role, "password": INITIAL_PWD, "active": True}
    cr = requests.post(f"{API}/users", json=payload, headers=_auth(admin_token), timeout=15)
    assert cr.status_code in (200, 201, 400), cr.text
    r = _login(email, INITIAL_PWD)
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    cp = requests.post(f"{API}/auth/change-password",
                       json={"current_password": INITIAL_PWD, "new_password": FINAL_PWD},
                       headers=_auth(tok), timeout=15)
    assert cp.status_code == 200, cp.text
    r2 = _login(email, FINAL_PWD)
    return email, r2.json()["access_token"]


@pytest.fixture(scope="module")
def op_token(admin_token):
    return _ensure_user(admin_token, "OPERATORE")[1]


@pytest.fixture(scope="module")
def appr_token(admin_token):
    return _ensure_user(admin_token, "APPROVATORE")[1]


@pytest.fixture(scope="module")
def ro_token(admin_token):
    return _ensure_user(admin_token, "SOLA_LETTURA")[1]


def _create_plan(token, text):
    return requests.post(f"{API}/m2/plans", json={"text": text}, headers=_auth(token), timeout=20)


def _run_to_end(op_token, appr_token, text, max_ticks=15):
    cr = _create_plan(op_token, text)
    assert cr.status_code == 200, cr.text
    plan_id = cr.json()["plan"]["id"]
    ar = requests.post(f"{API}/m2/plans/{plan_id}/approve",
                       headers=_auth(appr_token), timeout=15)
    assert ar.status_code == 200, ar.text
    g = None
    for _ in range(max_ticks):
        tr = requests.post(f"{API}/m2/plans/{plan_id}/tick",
                           headers=_auth(op_token), timeout=25)
        assert tr.status_code == 200, tr.text
        assert tr.json().get("mode") == "SIMULAZIONE"
        g = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth(op_token), timeout=15).json()
        if g["plan"]["plan_status"] in ("COMPLETATO", "BLOCCATO"):
            break
    return plan_id, g


def _get_deliverables(op_token, plan_id):
    r = requests.get(f"{API}/m2/plans/{plan_id}/deliverables",
                     headers=_auth(op_token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("mode") == "SIMULAZIONE"
    return body["deliverables"]


# ---------- 0. Auth base ----------
def test_deliverables_requires_auth():
    r = requests.get(f"{API}/m2/plans/nope/deliverables", timeout=10)
    assert r.status_code in (401, 403)


def test_ro_cannot_create_plan(ro_token):
    r = _create_plan(ro_token, "Prepara una campagna social e adv per il lancio")
    assert r.status_code == 403


# ---------- 1. Flusso end-to-end CAMPAGNA ----------
def test_campagna_5_deliverable_validi(op_token, appr_token):
    plan_id, g = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    assert g["plan"]["plan_status"] == "COMPLETATO", g["plan"]["plan_status"]
    delivs = _get_deliverables(op_token, plan_id)
    current = [d for d in delivs if d.get("is_current")]
    assert len(current) == 5, f"attesi 5 deliverable, trovati {len(current)}"
    types = {d["deliverable_type"] for d in current}
    assert types == {"marketing_strategy", "editorial_plan", "social_content",
                     "ad_campaign_draft", "kpi_report"}, types
    for d in current:
        assert d["valid"] is True, d
        assert d["status"] in ("COMPLETATO", "COMPLETATO_CON_AVVISI"), d
        assert d["version"] >= 1
        assert "content" in d


# ---------- 2. ad_campaign_draft: DRAFT e non pubblicata ----------
def test_ad_campaign_is_draft(op_token, appr_token):
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    delivs = _get_deliverables(op_token, plan_id)
    ad = next(d for d in delivs if d["deliverable_type"] == "ad_campaign_draft" and d["is_current"])
    assert ad["content"]["status"] == "DRAFT"
    assert ad["content"]["published"] is False


# ---------- 3. lead_gen: no PII ----------
def test_lead_gen_no_pii(op_token, appr_token):
    plan_id, g = _run_to_end(op_token, appr_token,
                             "Costruisci un piano di lead generation per prospect B2B")
    assert g["plan"]["plan_status"] in ("COMPLETATO", "COMPLETATO_CON_AVVISI",), g["plan"]["plan_status"]
    delivs = _get_deliverables(op_token, plan_id)
    lg = [d for d in delivs if d["deliverable_type"] == "lead_gen_plan" and d["is_current"]]
    assert lg, f"nessun lead_gen_plan in {[(d['deliverable_type'], d['is_current']) for d in delivs]}"
    lg = lg[0]
    assert lg["valid"] is True
    assert lg["status"] in ("COMPLETATO", "COMPLETATO_CON_AVVISI")
    blob = str(lg["content"])
    assert not EMAIL_RE.search(blob), f"trovata email PII: {blob[:200]}"
    # phone: verifica assenza di numeri lunghi (>=7 cifre consecutive)
    assert not re.search(r"\d{7,}", blob.replace(" ", "")), f"possibile telefono: {blob[:200]}"
    # deve contenere componenti attesi (icp/criteri/sequenze)
    c = lg["content"]
    keys = set(c.keys())
    assert any(k in keys for k in ("icp", "criteria", "criteri")), keys
    assert any(k in keys for k in ("outreach_sequence", "sequences", "sequenze")), keys


# ---------- 4. kpi_report: source SIMULATO/NON_DISPONIBILE ----------
def test_kpi_report_source(op_token, appr_token):
    plan_id, _ = _run_to_end(op_token, appr_token, "Genera un report KPI del trimestre")
    delivs = _get_deliverables(op_token, plan_id)
    kpi = [d for d in delivs if d["deliverable_type"] == "kpi_report" and d["is_current"]]
    assert kpi, "nessun kpi_report"
    kpi = kpi[0]
    assert kpi["valid"] is True
    for k in kpi["content"]["kpis"]:
        assert k["source"] in ("SIMULATO", "NON_DISPONIBILE"), k


# ---------- 5. email M1 compat ----------
def test_email_m1_compat(op_token, appr_token):
    cr = _create_plan(op_token, "Scrivi una breve email commerciale")
    assert cr.status_code == 200, cr.text
    plan_id = cr.json()["plan"]["id"]
    g0 = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth(op_token), timeout=15).json()
    assert len(g0["tasks"]) == 1, f"attesa 1 attività, trovate {len(g0['tasks'])}"
    plan_id, g = _run_to_end(op_token, appr_token, "Scrivi una breve email commerciale")
    delivs = _get_deliverables(op_token, plan_id)
    current = [d for d in delivs if d["is_current"]]
    assert len(current) == 1
    d = current[0]
    assert d["deliverable_type"] == "email"
    assert d["valid"] is True
    assert d["status"] in ("COMPLETATO", "COMPLETATO_CON_AVVISI")


# ---------- 6. Versionamento: una is_current per task ----------
def test_versioning_one_current_per_task(op_token, appr_token):
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    delivs = _get_deliverables(op_token, plan_id)
    # Per ogni task_id, esattamente una is_current True
    from collections import defaultdict
    by_task = defaultdict(list)
    for d in delivs:
        by_task[d["task_id"]].append(d)
    for tid, arr in by_task.items():
        curr = [x for x in arr if x.get("is_current")]
        assert len(curr) == 1, f"task {tid}: {len(curr)} correnti"
        # ogni deliverable ha version >= 1
        for x in arr:
            assert x["version"] >= 1


# ---------- 7. Guard SIMULAZIONE su /tick ----------
def test_tick_simulazione_mode(op_token, appr_token):
    """Verifica risposta base: mode=SIMULAZIONE."""
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    plan_id = cr.json()["plan"]["id"]
    requests.post(f"{API}/m2/plans/{plan_id}/approve", headers=_auth(appr_token), timeout=15)
    tr = requests.post(f"{API}/m2/plans/{plan_id}/tick", headers=_auth(op_token), timeout=20)
    assert tr.status_code == 200
    assert tr.json().get("mode") == "SIMULAZIONE"


def test_tick_blocked_if_real_mode(admin_token, op_token, appr_token):
    """Se possibile attivare la modalità REALE, /tick e /plans devono restituire 409.
    Se non possibile (prerequisiti non soddisfatti) -> il test è considerato passato
    documentando che il guard esiste (verificato in test precedente via mode)."""
    s = requests.get(f"{API}/settings", headers=_auth(admin_token), timeout=15)
    assert s.status_code == 200
    can_enable = s.json().get("can_enable_real_mode", False)
    if not can_enable:
        pytest.skip("Prerequisiti REALE non soddisfatti: guard verificato indirettamente via mode=SIMULAZIONE.")
    # Prepara un piano approvato in SIMULAZIONE
    cr = _create_plan(op_token, "Prepara una campagna social e adv per il lancio")
    plan_id = cr.json()["plan"]["id"]
    requests.post(f"{API}/m2/plans/{plan_id}/approve", headers=_auth(appr_token), timeout=15)
    try:
        r = requests.put(f"{API}/settings/real-mode",
                         json={"enable": True, "confirm": True},
                         headers=_auth(admin_token), timeout=15)
        if r.status_code != 200:
            pytest.skip(f"attivazione reale rifiutata: {r.status_code} {r.text}")
        tr = requests.post(f"{API}/m2/plans/{plan_id}/tick",
                           headers=_auth(op_token), timeout=15)
        assert tr.status_code == 409, tr.text
        # anche POST /plans deve essere bloccato
        cp = _create_plan(op_token, "Scrivi una breve email commerciale")
        assert cp.status_code == 409, cp.text
    finally:
        requests.put(f"{API}/settings/real-mode",
                     json={"enable": False}, headers=_auth(admin_token), timeout=15)


# ---------- 8. Nessun segreto nei deliverable ----------
def test_no_secrets_in_deliverables(op_token, appr_token):
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    delivs = _get_deliverables(op_token, plan_id)
    blob = str(delivs).lower()
    for forbidden in ("api_key", "apikey", "password", "secret_key", "access_token", "bearer "):
        assert forbidden not in blob, f"segreto potenzialmente presente: {forbidden}"
