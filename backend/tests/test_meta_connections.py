"""Connessioni Meta (domains/meta_connections.py) — CRUD multi-tenant, test
diagnostico reale (mockato) e stato aggregato /social/connectors/meta/status
(item 11/12/14). Mongo locale reale, trasporto HTTP Meta sempre mockato."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME
from app.domains import meta_connections as MC


def run(coro):
    return asyncio.run(coro)


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client[DB_NAME]


def _user(org_id, role, tag="a"):
    return {"id": f"user-metaconn-{tag}", "email": f"{tag}@test.local", "role": role, "organization_id": org_id}


class _FakeResponse:
    def __init__(self, status_code, json_body):
        self.status_code = status_code
        self._json = json_body
        self.headers = {}

    def json(self):
        return self._json


def _patch_requests(monkeypatch, fn):
    import requests
    monkeypatch.setattr(requests, "request", fn)


async def _scenario(fn):
    client, fresh_db = _db()
    org_id = f"org-test-metaconn-{uuid.uuid4().hex[:8]}"
    import app.audit as audit_mod
    old_db, old_audit_db = MC.db, audit_mod.db
    MC.db = fresh_db
    audit_mod.db = fresh_db
    try:
        return await fn(fresh_db, org_id)
    finally:
        MC.db = old_db
        audit_mod.db = old_audit_db
        for coll in ("organizations", "meta_connections", "audit_logs"):
            await fresh_db[coll].delete_many({"organization_id": org_id})
        client.close()


def test_create_e_list():
    async def scenario(fresh_db, org_id):
        c = await MC.create_meta_connection(
            MC.MetaConnectionBody(name="Bakery Meta", access_token="segretoreale", page_id="page1"),
            _user(org_id, "ADMIN"))
        assert c["name"] == "Bakery Meta"
        assert c["has_access_token"] is True
        assert "segretoreale" not in str(c)  # mai il token in chiaro nella risposta pubblica

        righe = await MC.list_meta_connections(_user(org_id, "OPERATORE"))
        assert len(righe) == 1

    run(_scenario(scenario))


def test_update_invalida_verifica_precedente():
    async def scenario(fresh_db, org_id):
        c = await MC.create_meta_connection(MC.MetaConnectionBody(name="X", access_token="tok"), _user(org_id, "ADMIN"))
        await fresh_db.meta_connections.update_one({"id": c["id"]}, {"$set": {"facebook_status": MC.STATUS_CONNECTED}})
        c2 = await MC.update_meta_connection(c["id"], MC.MetaConnectionBody(name="X rinominata", access_token=None), _user(org_id, "ADMIN"))
        assert c2["name"] == "X rinominata"
        assert c2["facebook_status"] == MC.STATUS_NOT_CONFIGURED  # config cambiata -> va riverificata

    run(_scenario(scenario))


def test_delete():
    async def scenario(fresh_db, org_id):
        c = await MC.create_meta_connection(MC.MetaConnectionBody(name="X", access_token="tok"), _user(org_id, "ADMIN"))
        await MC.delete_meta_connection(c["id"], _user(org_id, "ADMIN"))
        righe = await MC.list_meta_connections(_user(org_id, "OPERATORE"))
        assert righe == []

    run(_scenario(scenario))


def test_isolamento_tenant():
    async def scenario(fresh_db, org_a):
        org_b = f"org-test-metaconn-{uuid.uuid4().hex[:8]}"
        c = await MC.create_meta_connection(MC.MetaConnectionBody(name="X", access_token="tok"), _user(org_a, "ADMIN"))
        with pytest.raises(Exception) as ei:
            await MC.update_meta_connection(c["id"], MC.MetaConnectionBody(name="Y"), _user(org_b, "ADMIN", "cross"))
        assert getattr(ei.value, "status_code", None) == 404

    run(_scenario(scenario))


def test_test_connection_richiede_conferma():
    async def scenario(fresh_db, org_id):
        c = await MC.create_meta_connection(MC.MetaConnectionBody(name="X", access_token="tok"), _user(org_id, "ADMIN"))
        with pytest.raises(Exception) as ei:
            await MC.test_meta_connection(c["id"], MC.TestConfirmBody(confirm=False), _user(org_id, "ADMIN"))
        assert getattr(ei.value, "status_code", None) == 400

    run(_scenario(scenario))


def test_test_connection_ok_facebook_e_instagram(monkeypatch):
    def fake(method, url, **kw):
        if url.endswith("/me"):
            return _FakeResponse(200, {"id": "user1", "name": "Admin"})
        if url.endswith("/page1"):
            return _FakeResponse(200, {"id": "page1", "name": "Bakery & Coffee", "instagram_business_account": {"id": "ig1"}})
        if url.endswith("/ig1"):
            return _FakeResponse(200, {"id": "ig1", "username": "bakerycoffee"})
        raise AssertionError(f"URL inatteso: {url}")
    _patch_requests(monkeypatch, fake)

    async def scenario(fresh_db, org_id):
        c = await MC.create_meta_connection(
            MC.MetaConnectionBody(name="X", access_token="tok", page_id="page1"), _user(org_id, "ADMIN"))
        risultato = await MC.test_meta_connection(c["id"], MC.TestConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        assert risultato["facebook_status"] == MC.STATUS_CONNECTED
        assert risultato["instagram_status"] == MC.STATUS_CONNECTED
        assert risultato["page_name"] == "Bakery & Coffee"
        assert risultato["instagram_username"] == "bakerycoffee"

    run(_scenario(scenario))


def test_test_connection_token_non_valido(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(400, {"error": {"code": 190, "message": "Token scaduto"}})
    _patch_requests(monkeypatch, fake)

    async def scenario(fresh_db, org_id):
        c = await MC.create_meta_connection(MC.MetaConnectionBody(name="X", access_token="tok-scaduto"), _user(org_id, "ADMIN"))
        risultato = await MC.test_meta_connection(c["id"], MC.TestConfirmBody(confirm=True), _user(org_id, "ADMIN"))
        assert risultato["facebook_status"] == MC.STATUS_INVALID
        assert "dettagli_errore" in risultato

    run(_scenario(scenario))


# ---------------- stato aggregato ----------------
def test_status_non_configurato():
    async def scenario(fresh_db, org_id):
        stato = await MC.meta_connector_status(_user(org_id, "OPERATORE"))
        assert stato["configured"] is False
        assert stato["facebook_page"]["connected"] is False
        assert stato["instagram"]["connected"] is False

    run(_scenario(scenario))


def test_status_configurato_e_connesso():
    async def scenario(fresh_db, org_id):
        c = await MC.create_meta_connection(MC.MetaConnectionBody(name="X", mode="real", access_token="tok", page_id="page1"), _user(org_id, "ADMIN"))
        await fresh_db.meta_connections.update_one({"id": c["id"]}, {"$set": {
            "facebook_status": MC.STATUS_CONNECTED, "page_name": "Bakery & Coffee",
            "instagram_status": MC.STATUS_CONNECTED, "instagram_username": "bakerycoffee",
        }})
        stato = await MC.meta_connector_status(_user(org_id, "OPERATORE"))
        assert stato["configured"] is True
        assert stato["mode"] == "real"
        assert stato["facebook_page"]["connected"] is True
        assert stato["facebook_page"]["page_name"] == "Bakery & Coffee"
        assert stato["instagram"]["connected"] is True
        assert "tok" not in str(stato)  # mai un token nella risposta

    run(_scenario(scenario))
