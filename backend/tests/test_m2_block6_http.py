"""Blocco 6 — Test end-to-end HTTP: revisori NON distruttivi Compliance/Auditor (SIMULAZIONE)."""
import os
import copy
import pytest
import requests


def _load_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if not url:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    return url.rstrip("/")


BASE_URL = _load_base_url()
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "raffaelepatarino77@gmail.com"
ADMIN_PASSWORD = "Actelya2!Milestone"
FINAL_PWD = "Actelya!Test2025"
INITIAL_PWD = "TempPass!12345"


def _login(email, password):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_token():
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200, f"login admin: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _ensure_user(admin_token, role, tag="b4"):
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


def _run_to_end(op_tok, appr_tok, text, max_ticks=15):
    cr = _create_plan(op_tok, text)
    assert cr.status_code == 200, cr.text
    plan_id = cr.json()["plan"]["id"]
    ar = requests.post(f"{API}/m2/plans/{plan_id}/approve",
                       headers=_auth(appr_tok), timeout=15)
    assert ar.status_code == 200, ar.text
    g = None
    for _ in range(max_ticks):
        tr = requests.post(f"{API}/m2/plans/{plan_id}/tick",
                           headers=_auth(op_tok), timeout=30)
        assert tr.status_code == 200, tr.text
        assert tr.json().get("mode") == "SIMULAZIONE"
        g = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth(op_tok), timeout=15).json()
        if g["plan"]["plan_status"] in ("COMPLETATO", "BLOCCATO"):
            break
    return plan_id, g


def _get_delivs(tok, plan_id):
    r = requests.get(f"{API}/m2/plans/{plan_id}/deliverables",
                     headers=_auth(tok), timeout=15)
    assert r.status_code == 200
    return r.json()["deliverables"]


def _get_reviews(tok, plan_id):
    r = requests.get(f"{API}/m2/plans/{plan_id}/reviews",
                     headers=_auth(tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("mode") == "SIMULAZIONE"
    return body["reviews"]


# ---------- Auth base ----------
def test_reviews_requires_auth():
    r = requests.get(f"{API}/m2/plans/anyid/reviews", timeout=10)
    assert r.status_code in (401, 403)


# ---------- 10 revisioni (5 deliv x 2 revisori) ----------
def test_campagna_genera_10_revisioni(op_token, appr_token):
    plan_id, g = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    assert g["plan"]["plan_status"] == "COMPLETATO", g["plan"]["plan_status"]
    delivs = _get_delivs(op_token, plan_id)
    current = [d for d in delivs if d.get("is_current")]
    assert len(current) == 5
    reviews = _get_reviews(op_token, plan_id)
    # 5 deliverable * 2 revisioni
    assert len(reviews) == 10, f"attese 10 revisioni, trovate {len(reviews)}"
    # Verifica campi obbligatori
    for r in reviews:
        assert r["review_type"] in ("compliance", "audit")
        assert r["reviewer_agent"] in ("compliance_reviewer", "auditor")
        # coerenza type<->agent
        if r["review_type"] == "compliance":
            assert r["reviewer_agent"] == "compliance_reviewer"
        else:
            assert r["reviewer_agent"] == "auditor"
        assert r["non_destructive"] is True
        assert r["severity"] in ("info", "warning", "high")
        assert isinstance(r.get("findings"), list) and len(r["findings"]) > 0
        assert r["plan_id"] == plan_id
        assert r.get("task_id")
        assert r.get("deliverable_id")
        assert r.get("organization_id")
    # 2 revisioni per deliverable
    from collections import defaultdict
    per_deliv = defaultdict(set)
    for r in reviews:
        per_deliv[r["deliverable_id"]].add(r["review_type"])
    for d in current:
        assert per_deliv.get(d["id"]) == {"compliance", "audit"}, d["id"]


# ---------- Non distruttività ----------
def test_reviews_non_distruttive(op_token, appr_token):
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    delivs_before = _get_delivs(op_token, plan_id)
    # snapshot content + status
    snap_before = {d["id"]: (copy.deepcopy(d["content"]), d["status"], d["valid"])
                   for d in delivs_before if d.get("is_current")}
    # Chiamiamo la re-review manuale su ogni task per forzare esecuzione revisori
    plan = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth(op_token), timeout=15).json()
    admin_r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    admin_tok = admin_r.json()["access_token"]
    for t in plan["tasks"]:
        rr = requests.post(f"{API}/m2/plans/{plan_id}/tasks/{t['id']}/review",
                           headers=_auth(admin_tok), timeout=20)
        assert rr.status_code == 200, rr.text
        assert rr.json().get("mode") == "SIMULAZIONE"
    delivs_after = _get_delivs(op_token, plan_id)
    snap_after = {d["id"]: (d["content"], d["status"], d["valid"])
                  for d in delivs_after if d.get("is_current")}
    assert snap_before == snap_after, "deliverable modificati dalle revisioni!"


# ---------- Idempotenza re-review manuale ----------
def test_manual_review_idempotent(op_token, appr_token, admin_token):
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    plan = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth(op_token), timeout=15).json()
    tid = plan["tasks"][0]["id"]
    # count reviews per task target deliverable
    delivs = _get_delivs(op_token, plan_id)
    task_deliv = next(d for d in delivs if d["task_id"] == tid and d.get("is_current"))
    # chiama /review 2 volte
    for _ in range(2):
        rr = requests.post(f"{API}/m2/plans/{plan_id}/tasks/{tid}/review",
                           headers=_auth(admin_token), timeout=20)
        assert rr.status_code == 200, rr.text
    reviews = _get_reviews(op_token, plan_id)
    per_deliv = [r for r in reviews if r["deliverable_id"] == task_deliv["id"]]
    assert len(per_deliv) == 2, f"attese 2 revisioni per deliverable, trovate {len(per_deliv)}"
    types = sorted(r["review_type"] for r in per_deliv)
    assert types == ["audit", "compliance"]


def test_operatore_cannot_manual_review(op_token, appr_token):
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    plan = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth(op_token), timeout=15).json()
    tid = plan["tasks"][0]["id"]
    rr = requests.post(f"{API}/m2/plans/{plan_id}/tasks/{tid}/review",
                       headers=_auth(op_token), timeout=15)
    assert rr.status_code == 403, rr.text


def test_ro_cannot_read_review_endpoint(op_token, appr_token, ro_token):
    """SOLA_LETTURA non può eseguire /review."""
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    plan = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth(op_token), timeout=15).json()
    tid = plan["tasks"][0]["id"]
    rr = requests.post(f"{API}/m2/plans/{plan_id}/tasks/{tid}/review",
                       headers=_auth(ro_token), timeout=15)
    assert rr.status_code == 403, rr.text


# ---------- Compliance su lead_gen: GDPR ma NO PII ----------
def test_leadgen_compliance_gdpr_no_pii(op_token, appr_token):
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Costruisci un piano di lead generation per prospect B2B")
    delivs = _get_delivs(op_token, plan_id)
    lg = next(d for d in delivs if d["deliverable_type"] == "lead_gen_plan" and d.get("is_current"))
    reviews = _get_reviews(op_token, plan_id)
    compl = [r for r in reviews if r["deliverable_id"] == lg["id"] and r["review_type"] == "compliance"]
    assert len(compl) == 1
    codes = [f["code"] for f in compl[0]["findings"]]
    assert "PII" not in codes, f"PII segnalato erroneamente: {codes}"
    assert "GDPR" in codes, f"GDPR mancante: {codes}"
    # severity GDPR = warning
    gdpr_finding = next(f for f in compl[0]["findings"] if f["code"] == "GDPR")
    assert gdpr_finding.get("severity") == "warning"


def test_ad_campaign_compliance_no_high(op_token, appr_token):
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    delivs = _get_delivs(op_token, plan_id)
    ad = next(d for d in delivs if d["deliverable_type"] == "ad_campaign_draft" and d.get("is_current"))
    assert ad["content"]["status"] == "DRAFT"
    reviews = _get_reviews(op_token, plan_id)
    compl = [r for r in reviews if r["deliverable_id"] == ad["id"] and r["review_type"] == "compliance"]
    assert len(compl) == 1
    codes = [f["code"] for f in compl[0]["findings"]]
    assert "CAMPAIGN_STATUS" not in codes, f"CAMPAIGN_STATUS erroneamente sollevato: {codes}"


# ---------- Audit: TRACE cost/attempt + link ----------
def test_audit_trace_and_links(op_token, appr_token):
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    reviews = _get_reviews(op_token, plan_id)
    audits = [r for r in reviews if r["review_type"] == "audit"]
    assert len(audits) == 5
    for a in audits:
        codes = [f["code"] for f in a["findings"]]
        assert "TRACE" in codes, f"TRACE mancante in audit: {codes}"
        trace = next(f for f in a["findings"] if f["code"] == "TRACE")
        # cost e attempt presenti nella meta del finding
        meta = trace.get("meta") or trace.get("details") or trace
        assert "cost" in str(meta).lower() or "cost" in trace, f"costo mancante in TRACE: {trace}"
        # link presenti
        assert a.get("plan_id") == plan_id
        assert a.get("task_id")
        assert a.get("reviewer_agent") == "auditor"
        assert a.get("organization_id")
    # mode SIMULAZIONE è garantito dal wrapper dell'endpoint /reviews
    r_full = requests.get(f"{API}/m2/plans/{plan_id}/reviews",
                          headers=_auth(op_token), timeout=15).json()
    assert r_full.get("mode") == "SIMULAZIONE"


# ---------- Guard SIMULAZIONE su /review ----------
def test_manual_review_simulazione_mode(op_token, appr_token, admin_token):
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    plan = requests.get(f"{API}/m2/plans/{plan_id}", headers=_auth(op_token), timeout=15).json()
    tid = plan["tasks"][0]["id"]
    rr = requests.post(f"{API}/m2/plans/{plan_id}/tasks/{tid}/review",
                       headers=_auth(admin_token), timeout=15)
    assert rr.status_code == 200
    assert rr.json().get("mode") == "SIMULAZIONE"


# ---------- Nessun segreto nelle reviews ----------
def test_no_secrets_in_reviews(op_token, appr_token):
    plan_id, _ = _run_to_end(op_token, appr_token,
                             "Prepara una campagna social e adv per il lancio")
    reviews = _get_reviews(op_token, plan_id)
    blob = str(reviews).lower()
    for forbidden in ("api_key", "apikey", "password", "secret_key", "access_token", "bearer "):
        assert forbidden not in blob, f"segreto trovato nelle reviews: {forbidden}"
