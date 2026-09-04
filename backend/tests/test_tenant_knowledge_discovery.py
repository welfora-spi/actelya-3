"""Registrazione/tenant, onboarding CEO, Fact Ledger e Discovery (SIMULATO) — HTTP e2e.
Ogni test crea il proprio tenant via registrazione pubblica: nessuna dipendenza
dall'admin seed, cosi' i test restano isolati fra loro e riusano lo stesso schema
di isolamento che verificano."""
import time
import uuid
import requests
import pytest

from conftest import API_URL as API

TEST_PASSWORD = "TenantTest!2026x"


def _register(company_name, sector="Test", website="https://example.com", social=None, goal="Crescere"):
    email = f"test_{uuid.uuid4().hex[:12]}@example.com"
    body = {
        "company_name": company_name, "sector": sector, "website": website,
        "social_links": social or [], "primary_goal": goal,
        "first_name": "Test", "last_name": "User", "email": email, "password": TEST_PASSWORD,
    }
    r = requests.post(f"{API}/tenant/register", json=body, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    return data["organization_id"], data["access_token"], email


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- Registration / tenant creation ----------
def test_register_creates_isolated_admin_tenant():
    org_id, token, email = _register("Panetteria Test")
    assert org_id.startswith("org-")
    r = requests.get(f"{API}/auth/me", headers=_auth(token), timeout=15)
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["role"] == "ADMIN"
    assert user["organization_id"] == org_id
    assert user["must_change_password"] is False


def test_register_duplicate_email_rejected():
    email = f"test_{uuid.uuid4().hex[:12]}@example.com"
    body = {"company_name": "A", "sector": "", "website": "", "social_links": [], "primary_goal": "",
           "first_name": "A", "last_name": "B", "email": email, "password": TEST_PASSWORD}
    r1 = requests.post(f"{API}/tenant/register", json=body, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/tenant/register", json=body, timeout=15)
    assert r2.status_code == 400


# ---------- Onboarding status ----------
def test_onboarding_status_ready_when_all_declared():
    org_id, token, _ = _register("Azienda Completa", sector="Retail", website="https://x.it",
                                 social=["https://instagram.com/x"], goal="Vendere di piu'")
    r = requests.get(f"{API}/onboarding/status", headers=_auth(token), timeout=15)
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["onboarding_status"] == "IN_CORSO"
    assert st["missing_core_fields"] == []
    assert st["open_conflicts"] == 0
    assert st["ready_to_complete"] is True


def test_onboarding_status_missing_fields_when_incomplete():
    email = f"test_{uuid.uuid4().hex[:12]}@example.com"
    body = {"company_name": "Solo Nome", "sector": "", "website": "", "social_links": [], "primary_goal": "",
           "first_name": "A", "last_name": "B", "email": email, "password": TEST_PASSWORD}
    r = requests.post(f"{API}/tenant/register", json=body, timeout=15)
    token = r.json()["access_token"]
    st = requests.get(f"{API}/onboarding/status", headers=_auth(token), timeout=15).json()
    assert "settore" in st["missing_core_fields"]
    assert "sito_web" in st["missing_core_fields"]
    assert st["ready_to_complete"] is False


# ---------- Fact Ledger: declared facts, conflicts, resolution ----------
def test_declared_facts_have_method_dichiarato():
    org_id, token, _ = _register("Fact Co", sector="Servizi", website="https://factco.it")
    facts = requests.get(f"{API}/knowledge/facts/current", headers=_auth(token), timeout=15).json()
    assert facts["ragione_sociale"]["method"] == "DICHIARATO"
    assert facts["ragione_sociale"]["value"] == "Fact Co"
    assert facts["settore"]["state"] == "ATTIVO"


def test_conflicting_declared_facts_flagged_and_resolved():
    org_id, token, _ = _register("Conflitto Co", sector="Settore A")
    # Same field, same method (DICHIARATO), disagreeing value -> real contradiction.
    r = requests.post(f"{API}/knowledge/facts", headers=_auth(token), timeout=15,
                      json={"field": "settore", "value": "Settore B", "source": "manuale"})
    assert r.status_code == 200, r.text
    new_fact = r.json()
    assert new_fact["state"] == "CONTRADDITTORIO"

    conflicts = requests.get(f"{API}/knowledge/conflicts", headers=_auth(token), timeout=15).json()
    assert "settore" in conflicts
    assert len(conflicts["settore"]) == 2

    onboarding_blocked = requests.post(f"{API}/onboarding/complete", headers=_auth(token), timeout=15)
    assert onboarding_blocked.status_code == 400

    # Resolve: confirm the new fact wins.
    resolved = requests.post(f"{API}/knowledge/facts/{new_fact['id']}/confirm",
                             headers=_auth(token), timeout=15)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["method"] == "VERIFICATO"
    assert resolved.json()["state"] == "ATTIVO"

    current = requests.get(f"{API}/knowledge/facts/current", headers=_auth(token), timeout=15).json()
    assert current["settore"]["value"] == "Settore B"

    onboarding_ok = requests.post(f"{API}/onboarding/complete", headers=_auth(token), timeout=15)
    assert onboarding_ok.status_code == 200, onboarding_ok.text


def test_higher_priority_fact_supersedes_without_conflict():
    """A DICHIARATO fact silently supersedes a lower-priority ESTRATTO one (no question asked)."""
    org_id, token, _ = _register("Priorita Co", sector="Iniziale", website="https://prio.it",
                                 social=["https://instagram.com/prio"])
    run = requests.post(f"{API}/discovery/run", headers=_auth(token), timeout=15)
    assert run.status_code == 200, run.text
    run_id = run.json()["id"]
    _wait_discovery(token, run_id)

    # Declaring a value for a field discovery extracted (tono_di_voce) should supersede it, not conflict.
    before = requests.get(f"{API}/knowledge/facts/current", headers=_auth(token), timeout=15).json()
    assert before["tono_di_voce"]["method"] == "ESTRATTO"
    r = requests.post(f"{API}/knowledge/facts", headers=_auth(token), timeout=15,
                      json={"field": "tono_di_voce", "value": "Ironico e scanzonato", "source": "manuale"})
    assert r.status_code == 200
    assert r.json()["state"] == "ATTIVO"
    conflicts = requests.get(f"{API}/knowledge/conflicts", headers=_auth(token), timeout=15).json()
    assert "tono_di_voce" not in conflicts


# ---------- Discovery ----------
def _wait_discovery(token, run_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{API}/discovery/runs/{run_id}", headers=_auth(token), timeout=15)
        st = r.json()["status"]
        if st in ("COMPLETATO", "FALLITO"):
            return st
        time.sleep(0.5)
    pytest.fail("Discovery run non completata entro il timeout")


def test_discovery_run_completes_and_writes_estratto_facts():
    org_id, token, _ = _register("Discovery Co", sector="Retail", website="https://discoveryco.it",
                                 social=["https://instagram.com/discoveryco"])
    run = requests.post(f"{API}/discovery/run", headers=_auth(token), timeout=15)
    assert run.status_code == 200, run.text
    data = run.json()
    assert data["status"] == "IN_CODA"
    assert data["mode"] == "SIMULATO"

    final_status = _wait_discovery(token, data["id"])
    assert final_status == "COMPLETATO"

    detail = requests.get(f"{API}/discovery/runs/{data['id']}", headers=_auth(token), timeout=15).json()
    assert len(detail["facts_written"]) >= 2

    current = requests.get(f"{API}/knowledge/facts/current", headers=_auth(token), timeout=15).json()
    assert current["tono_di_voce"]["method"] == "ESTRATTO"
    assert current["tono_di_voce"]["source"] == "discovery_sito"
    assert current["presenza_social"]["method"] == "ESTRATTO"


def test_discovery_without_website_or_social_rejected():
    org_id, token, _ = _register("Senza Presenza", sector="Test", website="", social=[])
    r = requests.post(f"{API}/discovery/run", headers=_auth(token), timeout=15)
    assert r.status_code == 400


def test_goal_creation_not_blocked_while_discovery_running():
    """New goal creation must succeed even while a Discovery run for the same
    tenant is still queued/in progress — the two subsystems must not serialize."""
    org_id, token, _ = _register("Concorrenza Co", sector="Retail", website="https://concorrenza.it",
                                 social=["https://instagram.com/concorrenza"])
    run = requests.post(f"{API}/discovery/run", headers=_auth(token), timeout=15)
    run_id = run.json()["id"]

    goal_resp = requests.post(f"{API}/goals", headers=_auth(token), timeout=15,
                              json={"text": "Prepara una strategia di marketing per il rilancio"})
    assert goal_resp.status_code == 200, goal_resp.text
    assert goal_resp.json()["goal"]["organization_id"] == org_id

    _wait_discovery(token, run_id)


# ---------- Tenant isolation ----------
def test_tenant_isolation_goals_facts_audit():
    org_a, token_a, _ = _register("Tenant A", sector="Settore A")
    org_b, token_b, _ = _register("Tenant B", sector="Settore B")
    assert org_a != org_b

    goal_a = requests.post(f"{API}/goals", headers=_auth(token_a), timeout=15,
                           json={"text": "Genera un report KPI del trimestre"})
    assert goal_a.status_code == 200
    goal_a_id = goal_a.json()["goal"]["id"]

    # B cannot list A's goal.
    goals_b = requests.get(f"{API}/goals", headers=_auth(token_b), timeout=15).json()
    assert all(g["id"] != goal_a_id for g in goals_b)

    # B cannot fetch A's goal by id directly (404, not 403 — no existence leak).
    direct = requests.get(f"{API}/goals/{goal_a_id}", headers=_auth(token_b), timeout=15)
    assert direct.status_code == 404

    # B's Fact Ledger has no trace of A's declared company name.
    facts_b = requests.get(f"{API}/knowledge/facts/current", headers=_auth(token_b), timeout=15).json()
    assert facts_b["ragione_sociale"]["value"] == "Tenant B"

    # B's audit log contains no entries from A's organization.
    audit_b = requests.get(f"{API}/audit?limit=100", headers=_auth(token_b), timeout=15).json()
    assert all(a["organization_id"] == org_b for a in audit_b)


def test_tenant_isolation_users_management():
    org_a, token_a, _ = _register("User Iso A")
    org_b, token_b, _ = _register("User Iso B")
    users_b = requests.get(f"{API}/users", headers=_auth(token_b), timeout=15).json()
    users_a_emails = {u["email"] for u in requests.get(f"{API}/users", headers=_auth(token_a), timeout=15).json()}
    users_b_emails = {u["email"] for u in users_b}
    assert users_a_emails.isdisjoint(users_b_emails)
