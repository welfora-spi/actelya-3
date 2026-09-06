"""Tool Execution Gateway (Fase 1) — test diretti (MongoDB locale, nessuna
rete): autorizzazione (agente/connessione/approvazione/budget) e cost
ledger. Nessuna chiamata reale a un provider: qui si verifica SOLO il
controllo che deve precedere l'adapter."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.models import now_iso
from app.tools import cost_ledger as CL
from app.tools import gateway as GW


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


class _AuditSpia:
    """log_audit() scrive SEMPRE nel db condiviso importato da app.db (lo
    stesso usato dall'app in esecuzione — mai quello passato esplicitamente
    dal chiamante, ne' il client Mongo isolato 'actelya3_test' usato da
    questi test): verificare una voce di audit tramite una seconda lettura
    Mongo reale mescolerebbe due database diversi E riaprirebbe un secondo
    event loop asyncio.run() nello stesso processo (fonte nota di 'Event
    loop is closed' su Windows/pytest-xdist — vedi altri file di test).
    Si intercetta quindi la CHIAMATA stessa a log_audit, senza toccare Mongo."""

    def __init__(self):
        self.chiamate: list = []

    async def __call__(self, **kwargs):
        self.chiamate.append(kwargs)
        return {"id": "audit-spia", **kwargs}


@pytest.fixture(autouse=True)
def _no_real_audit(monkeypatch):
    """log_audit() scrive SEMPRE nel db condiviso app.db (mai quello isolato
    'actelya3_test' di questi test): intercettato per OGNI test di questo
    file, anche quando il test non sta verificando l'audit in sé — basta che
    authorize() raggiunga il percorso di successo (anche solo come effetto
    collaterale di un secondo controllo nello stesso test) per scrivere
    davvero nel db condiviso. Evita sia la contaminazione fra database
    diversi sia il flake noto 'Event loop is closed' (Motor + più
    asyncio.run() nello stesso worker pytest-xdist). Un test che vuole
    ispezionare le chiamate installa comunque la propria _AuditSpia() in
    monkeypatch, che sostituisce semplicemente questa di default."""
    monkeypatch.setattr("app.tools.gateway.log_audit", _AuditSpia())


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, org):
    for c in ("ai_connections", "appointment_connections", "organization_budgets", "tool_cost_events", "audit_logs"):
        await db[c].delete_many({"organization_id": org})


def test_authorize_rifiuta_strumento_sconosciuto():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            with pytest.raises(GW.ToolGatewayError) as exc:
                await GW.authorize(db, org_id=org, agent_id="lead-gen-specialist", tool_id="strumento-inesistente")
            assert exc.value.code == "STRUMENTO_SCONOSCIUTO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_authorize_rifiuta_agente_non_autorizzato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            with pytest.raises(GW.ToolGatewayError) as exc:
                await GW.authorize(db, org_id=org, agent_id="appointment-setter", tool_id="requesty_llm")
            assert exc.value.code == "AGENTE_NON_AUTORIZZATO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_authorize_rifiuta_connessione_non_verificata():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            # Nessuna connessione ai_connections per 'requesty' in questa org: NON_CONFIGURATO.
            with pytest.raises(GW.ToolGatewayError) as exc:
                await GW.authorize(db, org_id=org, agent_id="resp-marketing", tool_id="requesty_llm")
            assert exc.value.code == "CONNESSIONE_NON_VERIFICATA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_authorize_rifiuta_senza_approvazione_esplicita():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.appointment_connections.insert_one({
                "id": "conn-gw-1", "organization_id": org, "provider_type": "google_calendar",
                "status": "VERIFICATO", "created_at": now_iso(), "updated_at": now_iso(),
            })
            with pytest.raises(GW.ToolGatewayError) as exc:
                await GW.authorize(db, org_id=org, agent_id="appointment-setter", tool_id="google_calendar",
                                   approved=False)
            assert exc.value.code == "APPROVAZIONE_RICHIESTA"
            # Con approved=True (l'appuntamento e' gia' stato approvato nel dominio) l'autorizzazione passa.
            tool = await GW.authorize(db, org_id=org, agent_id="appointment-setter", tool_id="google_calendar",
                                      approved=True)
            assert tool.tool_id == "google_calendar"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_authorize_registra_audit_in_caso_di_successo(monkeypatch):
    spia = _AuditSpia()
    monkeypatch.setattr("app.tools.gateway.log_audit", spia)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.appointment_connections.insert_one({
                "id": "conn-gw-2", "organization_id": org, "provider_type": "google_calendar",
                "status": "VERIFICATO", "created_at": now_iso(), "updated_at": now_iso(),
            })
            await GW.authorize(db, org_id=org, agent_id="appointment-setter", tool_id="google_calendar",
                               approved=True, actor="user-test")
            assert len(spia.chiamate) == 1
            assert spia.chiamate[0]["action"] == "TOOL_GATEWAY_AUTHORIZED"
            assert spia.chiamate[0]["details"]["agent_id"] == "appointment-setter"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_budget_nessun_tetto_configurato_non_blocca_mai():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await CL.check_budget(db, org_id=org, tool_id="requesty_llm", estimated_cost=999999.0)
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_budget_tetto_configurato_blocca_quando_superato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await CL.set_daily_cap(db, org, 1.0, actor="admin-test")
            await CL.record_cost(db, org_id=org, tool_id="requesty_llm", agent_id="resp-marketing", amount=0.9)
            with pytest.raises(CL.BudgetExceededError):
                await CL.check_budget(db, org_id=org, tool_id="requesty_llm", estimated_cost=0.5)
            # Una stima che rientra ancora nel tetto non deve essere bloccata.
            await CL.check_budget(db, org_id=org, tool_id="requesty_llm", estimated_cost=0.05)
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_authorize_rifiuta_per_budget_superato_su_tool_con_costo():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.ai_connections.insert_one({
                "id": "aiconn-gw-1", "organization_id": org, "provider_type": "requesty",
                "verified": True, "active": True, "created_at": now_iso(), "updated_at": now_iso(),
            })
            await CL.set_daily_cap(db, org, 1.0, actor="admin-test")
            await CL.record_cost(db, org_id=org, tool_id="requesty_llm", agent_id="resp-marketing", amount=0.95)
            with pytest.raises(GW.ToolGatewayError) as exc:
                await GW.authorize(db, org_id=org, agent_id="resp-marketing", tool_id="requesty_llm",
                                   estimated_cost=0.5)
            assert exc.value.code == "BUDGET_SUPERATO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_record_execution_registra_costo_effettivo_e_audit(monkeypatch):
    spia = _AuditSpia()
    monkeypatch.setattr("app.tools.gateway.log_audit", spia)

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await GW.record_execution(db, org_id=org, tool_id="requesty_llm", agent_id="resp-marketing",
                                      actual_cost=0.12, outcome="OK", actor="user-test")
            speso = await CL.spent_today(db, org)
            assert speso == 0.12
            assert len(spia.chiamate) == 1
            assert spia.chiamate[0]["action"] == "TOOL_GATEWAY_EXECUTED"
            assert spia.chiamate[0]["details"]["outcome"] == "OK"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())
