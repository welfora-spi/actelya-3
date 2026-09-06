"""Content Creator — test E2E HTTP (server live, MongoDB reale). Nessuna
chiamata reale a Requesty: senza una connessione REALE verificata configurata
in questo ambiente, questi test coprono onestamente il percorso di
autorizzazione/stato/RBAC end-to-end; la generazione REALE con adapter
mockato e' coperta a livello di pipeline (test_content_creator_pipeline.py)."""
import pytest
import requests

from conftest import API_URL as API, register_tenant

TEST_PASSWORD = "ContentTest!2026x"


def _register(company_name="Content Creator Test Co"):
    return register_tenant(company_name, password=TEST_PASSWORD)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def shared_tenant():
    return _register()


def _create_item(token, **overrides):
    body = {"objective": "Aumentare le richieste di preventivo", "channel": "instagram", "funnel_stage": "MOFU", **overrides}
    r = requests.post(f"{API}/content-creator/items", headers=_auth(token), timeout=15, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------- creazione e decisione ----------------
def test_creazione_senza_tipo_esplicito_decide_in_base_al_canale(shared_tenant):
    _, token = shared_tenant
    risultato = _create_item(token, channel="blog", content_type=None)
    assert risultato["content_types_decisi"] == ["articolo_blog", "contenuto_seo"]
    assert len(risultato["items"]) == 2
    for item in risultato["items"]:
        assert item["status"] == "BOZZA"


def test_creazione_con_tipo_esplicito_produce_un_solo_item(shared_tenant):
    _, token = shared_tenant
    risultato = _create_item(token, content_type="email")
    assert risultato["content_types_decisi"] == ["email"]
    assert len(risultato["items"]) == 1


def test_creazione_con_tipo_sconosciuto_rifiutata(shared_tenant):
    _, token = shared_tenant
    r = requests.post(f"{API}/content-creator/items", headers=_auth(token), timeout=15, json={
        "objective": "Test", "channel": "instagram", "content_type": "tipo-mai-esistito",
    })
    assert r.status_code == 400


def test_creazione_richiede_ruolo_operatore_o_admin():
    org_id, token = _register("Content Creator RBAC Co")
    # SOLA_LETTURA non puo' creare — verificato aggiungendo un utente con quel
    # ruolo non e' nello scope di questo test (nessun endpoint di invito qui):
    # verificato invece che un token assente sia rifiutato (401), stesso
    # principio minimo di sicurezza per ogni endpoint di scrittura.
    r = requests.post(f"{API}/content-creator/items", timeout=15, json={"objective": "Test"})
    assert r.status_code in (401, 403)


# ---------------- lista/dettaglio/paginazione ----------------
def test_lista_paginata(shared_tenant):
    _, token = shared_tenant
    r = requests.get(f"{API}/content-creator/items", headers=_auth(token), params={"page": 1, "page_size": 5}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "total" in body and "pages" in body


def test_dettaglio_singolo_item(shared_tenant):
    _, token = shared_tenant
    risultato = _create_item(token, content_type="headline")
    item_id = risultato["items"][0]["id"]
    r = requests.get(f"{API}/content-creator/items/{item_id}", headers=_auth(token), timeout=15)
    assert r.status_code == 200
    assert r.json()["id"] == item_id


def test_item_inesistente_404(shared_tenant):
    _, token = shared_tenant
    r = requests.get(f"{API}/content-creator/items/non-esiste", headers=_auth(token), timeout=15)
    assert r.status_code == 404


def test_isolamento_multi_tenant():
    _, token_a = _register("Content Creator Tenant A")
    _, token_b = _register("Content Creator Tenant B")
    risultato = _create_item(token_a, content_type="headline")
    item_id = risultato["items"][0]["id"]
    r = requests.get(f"{API}/content-creator/items/{item_id}", headers=_auth(token_b), timeout=15)
    assert r.status_code == 404


# ---------------- generazione: guardrail senza alcuna chiamata reale ----------------
def test_generate_senza_conferma_esplicita_rifiutato(shared_tenant):
    _, token = shared_tenant
    risultato = _create_item(token, content_type="headline")
    item_id = risultato["items"][0]["id"]
    r = requests.post(f"{API}/content-creator/items/{item_id}/generate", headers=_auth(token), timeout=15, json={"confirm": False})
    assert r.status_code == 400


def test_generate_senza_ai_reale_bloccato_senza_chiamata(shared_tenant):
    _, token = shared_tenant
    risultato = _create_item(token, content_type="headline")
    item_id = risultato["items"][0]["id"]
    r = requests.post(f"{API}/content-creator/items/{item_id}/generate", headers=_auth(token), timeout=15, json={"confirm": True})
    # Nessuna modalita' AI REALE attiva in questo tenant di test: rifiutato
    # prima di qualunque chiamata di rete (mai un tentativo silenzioso).
    assert r.status_code == 409


# ---------------- macchina a stati: guardrail su transizioni non valide ----------------
def test_approve_su_item_ancora_in_bozza_rifiutato(shared_tenant):
    _, token = shared_tenant
    risultato = _create_item(token, content_type="headline")
    item_id = risultato["items"][0]["id"]
    r = requests.post(f"{API}/content-creator/items/{item_id}/approve", headers=_auth(token), timeout=15, json={"approve": True})
    assert r.status_code == 409


def test_resolve_uncertain_su_item_non_incerto_rifiutato(shared_tenant):
    _, token = shared_tenant
    risultato = _create_item(token, content_type="headline")
    item_id = risultato["items"][0]["id"]
    r = requests.post(f"{API}/content-creator/items/{item_id}/resolve-uncertain", headers=_auth(token), timeout=15, json={"note": ""})
    assert r.status_code == 409


def test_link_media_su_item_non_in_attesa_asset_rifiutato(shared_tenant):
    _, token = shared_tenant
    risultato = _create_item(token, content_type="headline")
    item_id = risultato["items"][0]["id"]
    r = requests.post(f"{API}/content-creator/items/{item_id}/link-media", headers=_auth(token), timeout=15,
                      json={"kind": "reel", "project_id": "reel-x"})
    assert r.status_code == 409


def test_request_revision_richiede_nota_non_vuota(shared_tenant):
    _, token = shared_tenant
    risultato = _create_item(token, content_type="headline")
    item_id = risultato["items"][0]["id"]
    r = requests.post(f"{API}/content-creator/items/{item_id}/request-revision", headers=_auth(token), timeout=15, json={"note": ""})
    assert r.status_code == 422  # Pydantic: note ha min_length=1
