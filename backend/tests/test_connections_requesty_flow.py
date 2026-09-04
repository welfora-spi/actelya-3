"""Flusso reale (Mongo locale, MAI rete reale) per la connessione Requesty:
chiave in Credential Manager, test reale gated da conferma esplicita, nessun
segreto mai nell'audit log. Il confine esterno (chiamata HTTP a Requesty) e'
l'UNICO punto mockato: e' vietato spendere denaro reale in una suite di test
automatica (vedi tests/test_requesty_gateway.py per la copertura del gateway
in isolamento). Un client Mongo fresco per scenario (chiuso a fine test),
stesso pattern di tests/test_m2_block4.py: evita il crash 'Event loop is
closed' di Motor quando asyncio.run() viene chiamato piu' volte nella sessione."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME
from app.domains import connections
from app.integrations import requesty_gateway as rg
from app.integrations import requesty_secrets
from app.integrations.requesty_gateway import RequestyErroreSanificato, RisultatoGenerazioneRequesty


def run(coro):
    return asyncio.run(coro)


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client[DB_NAME]


@pytest.fixture(autouse=True)
def isolate_requesty_credential(monkeypatch):
    """Mai il Credential Manager reale in questa suite: store in memoria dedicato."""
    store: dict = {}

    def fake_save(v):
        if not v.strip():
            raise ValueError("vuoto")
        store["k"] = v

    monkeypatch.setattr(requesty_secrets, "salva_api_key_requesty", fake_save)
    monkeypatch.setattr(requesty_secrets, "leggi_api_key_requesty", lambda: store.get("k"))
    monkeypatch.setattr(requesty_secrets, "requesty_configurata", lambda: "k" in store)
    monkeypatch.setattr(requesty_secrets, "requesty_api_key_mascherata",
                        lambda: ("****" + store["k"][-4:]) if "k" in store else None)
    yield


class Body:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _new_conn_body(**overrides):
    base = dict(name="Requesty prod", provider_type="requesty", base_url="", api_key="sk-req-realtest-1234",
               logical_model="claude-sonnet-5", effective_model="anthropic/claude-sonnet-4-5",
               timeout=60, max_tokens=2000, max_budget_per_task=1.0, daily_budget=10.0, active=True, priority=1)
    base.update(overrides)
    return connections.AIConnectionBody(**base)


def _admin(org_id):
    return {"id": "user-test-admin-reqflow", "email": "admin-reqflow@test.local", "role": "ADMIN", "organization_id": org_id}


async def _scenario(fn):
    client, fresh_db = _db()
    org_id = f"org-test-req-{uuid.uuid4().hex[:8]}"
    import app.domains.connections as connections_mod
    import app.audit as audit_mod
    old_db, old_audit_db = connections_mod.db, audit_mod.db
    connections_mod.db = fresh_db
    audit_mod.db = fresh_db
    try:
        return await fn(fresh_db, org_id)
    finally:
        connections_mod.db = old_db
        audit_mod.db = old_audit_db
        await fresh_db.ai_connections.delete_many({"organization_id": org_id})
        await fresh_db.audit_logs.delete_many({"organization_id": org_id})
        client.close()


def test_create_stores_key_in_keyring_not_mongo():
    async def scenario(fresh_db, org_id):
        conn = await connections.create_ai(_new_conn_body(), _admin(org_id))
        assert conn["has_key"] is True
        assert conn["provider_type"] == "requesty"
        raw = await fresh_db.ai_connections.find_one({"id": conn["id"]})
        assert raw.get("api_key_encrypted") is None  # mai in Mongo per Requesty

    run(_scenario(scenario))


def test_test_real_richiede_conferma_esplicita():
    async def scenario(fresh_db, org_id):
        conn = await connections.create_ai(_new_conn_body(), _admin(org_id))
        with pytest.raises(Exception) as ei:
            await connections.test_real(conn["id"], connections.TestConfirmBody(confirm=False), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 400

    run(_scenario(scenario))


def test_test_real_provider_diverso_da_requesty_ora_supportato_ma_senza_credenziale_da_errore_sanificato():
    """CEO Agent 100% reale (blocco 2): test-real non e' piu' limitato a
    Requesty (llm_gateway.py registra anche openai/anthropic/gemini). Una
    connessione openai SENZA credenziale non produce piu' un HTTP 400: la
    chiamata parte, l'adapter la rifiuta con un errore sanificato
    ('non_configurato'), restituito come esito normale (mai un'eccezione),
    esattamente come per Requesty."""
    async def scenario(fresh_db, org_id):
        conn = await connections.create_ai(_new_conn_body(provider_type="openai", api_key=None), _admin(org_id))
        result = await connections.test_real(conn["id"], connections.TestConfirmBody(confirm=True), _admin(org_id))
        assert result["esito"] == "ERRORE"
        assert result["codice_errore"] == "non_configurato"
        updated = await fresh_db.ai_connections.find_one({"id": conn["id"]})
        assert updated["verified"] is False

    run(_scenario(scenario))


def test_test_real_rifiuta_provider_senza_adapter_registrato():
    async def scenario(fresh_db, org_id):
        conn = await connections.create_ai(_new_conn_body(provider_type="openai_compatible", api_key=None), _admin(org_id))
        # 'openai_compatible' HA un adapter (stesso protocollo di OpenAI):
        # per testare davvero il rifiuto serve un provider_type valido ma
        # senza adapter registrato -- forziamo il campo direttamente su Mongo,
        # una situazione che l'endpoint deve gestire senza sollevare un'
        # eccezione non gestita.
        await fresh_db.ai_connections.update_one({"id": conn["id"]}, {"$set": {"provider_type": "provider-mai-registrato"}})
        with pytest.raises(Exception) as ei:
            await connections.test_real(conn["id"], connections.TestConfirmBody(confirm=True), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 400

    run(_scenario(scenario))


def test_test_real_richiede_modello_effettivo():
    async def scenario(fresh_db, org_id):
        conn = await connections.create_ai(_new_conn_body(effective_model=""), _admin(org_id))
        with pytest.raises(Exception) as ei:
            await connections.test_real(conn["id"], connections.TestConfirmBody(confirm=True), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 400

    run(_scenario(scenario))


def test_test_real_ok_aggiorna_verified_e_audit_senza_segreti(monkeypatch):
    """CEO Agent 100% reale (blocco 2): test_real() ora passa da
    llm_gateway.diagnostic_test() -> RequestyAdapter -> requesty_gateway.
    genera_json() (mai piu' da requesty_gateway.test_diagnostico(), che
    questo endpoint non chiama piu'): il doppio di test va sul NUOVO punto
    di ingresso reale, altrimenti il mock non ha alcun effetto e la
    chiamata vera parte per davvero verso Requesty (bug osservato e
    corretto qui: mai piu' un test che invoca silenziosamente un provider
    reale)."""
    esito_ok = RisultatoGenerazioneRequesty(testo='{"ok": true}', modello_effettivo="anthropic/claude-sonnet-4-5",
                                            latenza_ms=120, input_tokens=5, output_tokens=2, troncata=False)
    monkeypatch.setattr(rg, "genera_json", lambda **kwargs: esito_ok)

    async def scenario(fresh_db, org_id):
        conn = await connections.create_ai(_new_conn_body(), _admin(org_id))
        result = await connections.test_real(conn["id"], connections.TestConfirmBody(confirm=True), _admin(org_id))
        assert result["esito"] == "OK"
        updated = await fresh_db.ai_connections.find_one({"id": conn["id"]})
        assert updated["verified"] is True
        assert updated["last_test_result"] == "OK_REALE"

        log = await fresh_db.audit_logs.find_one({"organization_id": org_id, "action": "TEST_AI_CONNECTION_REAL"})
        assert log is not None
        assert "sk-req-realtest-1234" not in str(log)

    run(_scenario(scenario))


def test_test_real_errore_non_marca_verified(monkeypatch):
    def _raise(**kwargs):
        raise RequestyErroreSanificato("autenticazione", "Credenziale Requesty non valida o rifiutata.")
    monkeypatch.setattr(rg, "genera_json", _raise)

    async def scenario(fresh_db, org_id):
        # Come in ACTELYA v1: un test diagnostico fallito NON e' un errore del
        # server (nessuna HTTPException) -- e' un esito normale del test, con
        # l'errore sanificato incapsulato nella risposta (mai un traceback grezzo).
        conn = await connections.create_ai(_new_conn_body(), _admin(org_id))
        result = await connections.test_real(conn["id"], connections.TestConfirmBody(confirm=True), _admin(org_id))
        assert result["esito"] == "ERRORE"
        assert result["codice_errore"] == "autenticazione"
        updated = await fresh_db.ai_connections.find_one({"id": conn["id"]})
        assert updated["verified"] is False
        assert updated["last_test_result"] == "ERRORE_autenticazione"

    run(_scenario(scenario))
