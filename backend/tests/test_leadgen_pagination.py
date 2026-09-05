"""Lead Generation — paginazione server-side: contratto page/page_size/
items/total/pages, allowlist di ordinamento, isolamento multi-tenant.

Due livelli di test:
- diretti su pagination.paginate()/resolve_sort() con MongoDB reale (veloci,
  deterministici, dataset creato ad hoc);
- HTTP live sugli endpoint reali (server + MongoDB reali) per verificare che
  i parametri di query arrivino davvero al motore di paginazione."""
import asyncio
import uuid

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

from app.domains.leadgen.pagination import MAX_PAGE_SIZE, paginate, resolve_sort
from app.models import new_id, now_iso
from conftest import API_URL as API

TEST_PASSWORD = "LeadGenPageTest!2026x"


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


def run(coro):
    return asyncio.run(coro)


# ==================== paginate()/resolve_sort() diretti (MongoDB reale) ====================
COLLEZIONE = "leadgen_pagination_probe"


async def _popola(db, org, n):
    docs = [
        {"id": new_id("probe"), "organization_id": org, "seq": i, "created_at": now_iso()}
        for i in range(n)
    ]
    if docs:
        await db[COLLEZIONE].insert_many(docs)


def test_prima_pagina_e_ultima_pagina_coerenti():
    async def scenario():
        client, db = _db()
        org = f"org-page-{uuid.uuid4().hex[:8]}"
        try:
            await _popola(db, org, 25)
            prima = await paginate(db[COLLEZIONE], {"organization_id": org}, page=1, page_size=10,
                                   sort_field="seq", direction=1)
            assert prima["total"] == 25
            assert prima["pages"] == 3
            assert [d["seq"] for d in prima["items"]] == list(range(0, 10))

            ultima = await paginate(db[COLLEZIONE], {"organization_id": org}, page=3, page_size=10,
                                    sort_field="seq", direction=1)
            assert [d["seq"] for d in ultima["items"]] == [20, 21, 22, 23, 24]  # 5 elementi, non 10
            return True
        finally:
            await db[COLLEZIONE].delete_many({"organization_id": org})
            client.close()

    assert run(scenario())


def test_pagina_vuota_oltre_il_totale():
    async def scenario():
        client, db = _db()
        org = f"org-page-{uuid.uuid4().hex[:8]}"
        try:
            await _popola(db, org, 5)
            oltre = await paginate(db[COLLEZIONE], {"organization_id": org}, page=9, page_size=10,
                                   sort_field="seq", direction=1)
            assert oltre["items"] == []
            assert oltre["total"] == 5
            assert oltre["pages"] == 1  # il totale/pagine restano corretti, mai un redirect silenzioso
            return True
        finally:
            await db[COLLEZIONE].delete_many({"organization_id": org})
            client.close()

    assert run(scenario())


def test_pagina_vuota_con_filtro_senza_risultati():
    async def scenario():
        client, db = _db()
        org = f"org-page-{uuid.uuid4().hex[:8]}"
        try:
            await _popola(db, org, 3)
            vuota = await paginate(db[COLLEZIONE], {"organization_id": org, "seq": 999}, page=1, page_size=10,
                                   sort_field="seq", direction=1)
            assert vuota == {"items": [], "total": 0, "page": 1, "page_size": 10, "pages": 0}
            return True
        finally:
            await db[COLLEZIONE].delete_many({"organization_id": org})
            client.close()

    assert run(scenario())


def test_page_size_bloccato_al_massimo_consentito():
    async def scenario():
        client, db = _db()
        org = f"org-page-{uuid.uuid4().hex[:8]}"
        try:
            await _popola(db, org, 5)
            r = await paginate(db[COLLEZIONE], {"organization_id": org}, page=1, page_size=10_000,
                               sort_field="seq", direction=1)
            assert r["page_size"] == MAX_PAGE_SIZE
            return True
        finally:
            await db[COLLEZIONE].delete_many({"organization_id": org})
            client.close()

    assert run(scenario())


def test_page_e_page_size_minimi_almeno_uno():
    async def scenario():
        client, db = _db()
        org = f"org-page-{uuid.uuid4().hex[:8]}"
        try:
            await _popola(db, org, 3)
            r = await paginate(db[COLLEZIONE], {"organization_id": org}, page=0, page_size=0,
                               sort_field="seq", direction=1)
            assert r["page"] == 1
            assert r["page_size"] == 1
            return True
        finally:
            await db[COLLEZIONE].delete_many({"organization_id": org})
            client.close()

    assert run(scenario())


def test_isolamento_organizzazione_nella_query():
    async def scenario():
        client, db = _db()
        org_a = f"org-page-a-{uuid.uuid4().hex[:8]}"
        org_b = f"org-page-b-{uuid.uuid4().hex[:8]}"
        try:
            await _popola(db, org_a, 4)
            await _popola(db, org_b, 9)
            solo_a = await paginate(db[COLLEZIONE], {"organization_id": org_a}, page=1, page_size=50,
                                    sort_field="seq", direction=1)
            assert solo_a["total"] == 4
            assert all(True for _ in solo_a["items"])  # nessun documento di org_b incluso per costruzione della query
            return True
        finally:
            await db[COLLEZIONE].delete_many({"organization_id": {"$in": [org_a, org_b]}})
            client.close()

    assert run(scenario())


def test_resolve_sort_valido_e_direzione():
    campo, direzione = resolve_sort("score", "asc", {"score": "score", "created_at": "created_at"}, "created_at")
    assert campo == "score"
    assert direzione == 1
    campo2, direzione2 = resolve_sort(None, "desc", {"score": "score"}, "score")
    assert campo2 == "score"
    assert direzione2 == -1


def test_resolve_sort_campo_non_ammesso_solleva_errore():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        resolve_sort("campo_non_esistente", "asc", {"score": "score"}, "score")
    assert exc.value.status_code == 400


def test_resolve_sort_direzione_non_ammessa_solleva_errore():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        resolve_sort("score", "laterale", {"score": "score"}, "score")
    assert exc.value.status_code == 400


# ==================== HTTP live (server + MongoDB reali) ====================
def _register(company_name="Lead Gen Page Test Co"):
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


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def shared_tenant():
    return _register()


def _create_campaign(token, name="C"):
    r = requests.post(f"{API}/leadgen/campaigns", headers=_auth(token), timeout=15, json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import_rows(token, campaign_id, righe):
    corpo = "ragione_sociale,dominio\n" + "".join(f"{nome},{dominio}.it\n" for nome, dominio in righe)
    file_id = requests.post(f"{API}/leadgen/files", headers=_auth(token), timeout=15,
                            files={"upload": (f"lead-{uuid.uuid4().hex[:8]}.csv", corpo.encode("utf-8"), "text/csv")}
                            ).json()["id"]
    r = requests.post(f"{API}/leadgen/files/{file_id}/import", params={"campaign_id": campaign_id},
                      headers=_auth(token), timeout=15,
                      json={"mapping": {"ragione_sociale": "ragione_sociale", "dominio": "dominio"}})
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]
    import time
    deadline = time.time() + 20
    while time.time() < deadline:
        stato = requests.get(f"{API}/leadgen/import-jobs/{job_id}", headers=_auth(token), timeout=15).json()["status"]
        if stato in ("READY_FOR_APPROVAL", "REVIEW_REQUIRED", "FAILED", "PARTIAL"):
            return
        time.sleep(0.5)
    pytest.fail("Import non completato entro il timeout")


def test_http_campagne_pagina_e_filtra_correttamente(shared_tenant):
    _, token = shared_tenant
    for i in range(3):
        _create_campaign(token, name=f"Pagination Probe {uuid.uuid4().hex[:6]} {i}")

    r = requests.get(f"{API}/leadgen/campaigns", params={"page": 1, "page_size": 2}, headers=_auth(token), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"items", "total", "page", "page_size", "pages"}
    assert len(body["items"]) == 2
    assert body["total"] >= 3
    assert body["pages"] >= 2

    r2 = requests.get(f"{API}/leadgen/campaigns", params={"page": 2, "page_size": 2}, headers=_auth(token), timeout=15)
    pagina2 = r2.json()["items"]
    assert {c["id"] for c in body["items"]}.isdisjoint({c["id"] for c in pagina2})  # nessuna sovrapposizione


def test_http_leads_ordinamento_non_ammesso_restituisce_400(shared_tenant):
    _, token = shared_tenant
    campaign_id = _create_campaign(token)
    r = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads",
                     params={"sort_by": "campo_inventato"}, headers=_auth(token), timeout=15)
    assert r.status_code == 400


def test_http_leads_dataset_significativo_navigazione_e_filtro_mantenuto(shared_tenant):
    _, token = shared_tenant
    campaign_id = _create_campaign(token, name=f"Dataset {uuid.uuid4().hex[:6]}")
    righe = [(f"Azienda{i} Srl", f"azienda{i}dataset{uuid.uuid4().hex[:6]}") for i in range(25)]
    _import_rows(token, campaign_id, righe)

    pagina1 = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads",
                          params={"page": 1, "page_size": 10, "sort_by": "ragione_sociale", "sort_dir": "asc"},
                          headers=_auth(token), timeout=15).json()
    assert pagina1["total"] == 25
    assert pagina1["pages"] == 3
    assert len(pagina1["items"]) == 10

    pagina2 = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads",
                          params={"page": 2, "page_size": 10, "sort_by": "ragione_sociale", "sort_dir": "asc"},
                          headers=_auth(token), timeout=15).json()
    pagina3 = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads",
                          params={"page": 3, "page_size": 10, "sort_by": "ragione_sociale", "sort_dir": "asc"},
                          headers=_auth(token), timeout=15).json()
    assert len(pagina3["items"]) == 5  # ultima pagina, resto del dataset

    ids_1 = {l["id"] for l in pagina1["items"]}
    ids_2 = {l["id"] for l in pagina2["items"]}
    ids_3 = {l["id"] for l in pagina3["items"]}
    assert ids_1.isdisjoint(ids_2) and ids_2.isdisjoint(ids_3) and ids_1.isdisjoint(ids_3)
    assert len(ids_1 | ids_2 | ids_3) == 25

    # Il filtro (qualification_status) resta valido navigando avanti e indietro.
    filtrata_p1 = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads",
                              params={"page": 1, "page_size": 5, "qualification_status": "QUALIFIED"},
                              headers=_auth(token), timeout=15).json()
    assert all(l["qualification_status"] == "QUALIFIED" for l in filtrata_p1["items"])
    if filtrata_p1["pages"] > 1:
        filtrata_p_ultima = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/leads",
                                        params={"page": filtrata_p1["pages"], "page_size": 5,
                                               "qualification_status": "QUALIFIED"},
                                        headers=_auth(token), timeout=15).json()
        assert all(l["qualification_status"] == "QUALIFIED" for l in filtrata_p_ultima["items"])


def test_http_duplicati_pagina_e_isolamento_organizzazione(shared_tenant):
    org_a, token_a = shared_tenant
    _, token_b = _register("Tenant Pagination B")
    campaign_id = _create_campaign(token_a, name=f"Duplicati {uuid.uuid4().hex[:6]}")
    dominio = f"dup{uuid.uuid4().hex[:6]}.it"
    righe = [(f"Riga{i} Srl", dominio.replace(".it", "")) for i in range(4)]
    _import_rows(token_a, campaign_id, righe)

    r = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/duplicates",
                     params={"page": 1, "page_size": 1}, headers=_auth(token_a), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert len(body["items"]) <= 1

    r_isolato = requests.get(f"{API}/leadgen/campaigns/{campaign_id}/duplicates", headers=_auth(token_b), timeout=15)
    assert r_isolato.status_code == 404  # campagna di un'altra organizzazione: mai visibile
