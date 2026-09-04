"""Brain — test di integrazione della pipeline completa richiesta dal
blocco "CEO Agent 100% reale": contesto -> LLM propose -> validazione
deterministica -> normalizzazione -> piano -> agenti -> M2 -> deliverable
-> approval (service.py::create_plan_with_brain). Verifica che l'output LLM
validato influenzi REALMENTE priorita'/scadenza dei task e budget del piano,
che l'escalation di rischio/budget avvenga SOLO verso maggiore cautela (mai
verso una decisione piu' permissiva rispetto a quella deterministica), e che
il percorso deterministico puro (nessun provider configurato) resti
identico a prima di questo blocco."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.brain import llm_gateway
from app.brain import service as SVC
from app.brain.audit.memory_audit import get_audit_log
from app.brain.llm_gateway import LLMResult
from app.brain.memory.session import get_session_store
from app.domains.knowledge import write_fact
from app.m2 import models as M

FOCACCINE_GOAL = (
    "Prepara una campagna social per pubblicizzare le focaccine artigianali del "
    "Bakery & Coffee di Merate. Crea una strategia locale, un piano editoriale e "
    "tre post per Instagram e Facebook rivolti alle famiglie e ai lavoratori della "
    "zona. Usa dati simulati, non contattare clienti e non pubblicare nulla."
)


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


async def _cleanup(db, org):
    for c in ("plans", "tasks", "executions", "deliverables", "audit_logs", "goals",
              "brain_audit_events", "brain_sessions", "settings", "ai_connections", "facts"):
        await db[c].delete_many({"organization_id": org})
    await db.settings.delete_many({"id": org})


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def reset_singleton_stores():
    get_session_store().reset()
    get_audit_log().reset()
    yield
    get_session_store().reset()
    get_audit_log().reset()


def _connessione(org, provider_type="openai", model="gpt-4o", priority=1):
    return {
        "organization_id": org, "provider_type": provider_type, "effective_model": model,
        "priority": priority, "verified": True, "active": True, "timeout": 20, "max_tokens": 1000,
        "id": f"aiconn-{uuid.uuid4().hex[:8]}", "api_key_encrypted": None,
    }


def _proposta_json(**overrides):
    import json
    base = {
        "intent": "aumentare la visibilita' locale", "strategia_proposta": "campagna social mirata",
        "priorita": "ALTA", "urgenza": "MEDIA", "agenti_suggeriti": [
            {"capability": "social", "motivazione": "richiesta esplicita di post"},
            {"capability": "strategy", "motivazione": "serve una strategia"},
        ],
        "task_proposti": [
            {"nome": "strategia", "capability": "strategy", "ordine": 1, "priorita": "ALTA", "scadenza": "2026-12-01"},
            {"nome": "post social", "capability": "social", "ordine": 2, "priorita": "MEDIA", "scadenza": None},
        ],
    }
    base.update(overrides)
    return json.dumps(base)


# ---------------- percorso deterministico puro: nessuna regressione ----------------
def test_percorso_deterministico_puro_senza_llm_configurato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["plan"] is not None
            assert res["llm_understanding"]["mode"] == "DETERMINISTICO"
            assert res["normalized_plan"]["origine"] == "DETERMINISTICO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- proposta LLM reale (mockata) influenza il piano ----------------
def test_proposta_llm_valida_influenza_priorita_e_scadenza_dei_task(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org))

            adapter = llm_gateway.OpenAIAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=_proposta_json(), provider="openai", modello_effettivo="gpt-4o",
                latenza_ms=12, input_tokens=10, output_tokens=10, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "openai": adapter})

            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["plan"] is not None
            assert res["llm_understanding"]["mode"] == "REALE"
            assert res["llm_understanding"]["provider_effettivo"] == "openai"
            assert res["normalized_plan"]["origine"] == "LLM"
            assert res["normalized_plan"]["priorita"] == "ALTA"

            strategy_task = next((t for t in res["tasks"] if t["deliverable_type"] == "marketing_strategy"), None)
            assert strategy_task is not None
            assert strategy_task.get("llm_priority") == "ALTA"
            assert strategy_task.get("llm_deadline") == "2026-12-01"

            persisted = await db.tasks.find_one({"id": strategy_task["id"]}, {"_id": 0})
            assert persisted["llm_priority"] == "ALTA"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_capability_reale_ma_non_rilevata_da_keyword_entra_nel_piano(monkeypatch):
    """Correzione architetturale: 'leadgen' e' una capability reale e
    operativa (agent_map.py) che il testo FOCACCINE_GOAL non rilevava a
    parola chiave. La proposta LLM la introduce comunque: deve entrare
    davvero nel piano (nuovo task M2 con l'agente lead-gen-specialist), non
    essere scartata solo perche' assente dal rilevamento a keyword."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org))

            adapter = llm_gateway.OpenAIAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=_proposta_json(agenti_suggeriti=[
                    {"capability": "social", "motivazione": "m"}, {"capability": "leadgen", "motivazione": "m2"},
                ], task_proposti=[
                    {"nome": "social", "capability": "social", "ordine": 1},
                    {"nome": "lead gen", "capability": "leadgen", "ordine": 2},
                ]), provider="openai", modello_effettivo="gpt-4o",
                latenza_ms=12, input_tokens=10, output_tokens=10, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "openai": adapter})

            assert "leadgen" not in discovery_leadgen_free_text_check()

            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["status"] == "READY"
            assert "leadgen" in res["normalized_plan"]["capability_validate"]
            assert res["normalized_plan"]["capability_extra_scartate"] == []
            assert "lead-gen-specialist" in res["activeAgentIds"]
            deliverable_types = {t["deliverable_type"] for t in res["tasks"]}
            assert "lead_gen_plan" in deliverable_types
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def discovery_leadgen_free_text_check() -> list:
    """Verifica di garanzia del test sopra: conferma che il testo
    FOCACCINE_GOAL non contiene alcuna parola chiave che farebbe rilevare
    'leadgen' deterministicamente (altrimenti il test non proverebbe nulla
    sulla comprensione LLM)."""
    from app.brain.planning.agent_selector import detect_capabilities
    return detect_capabilities(FOCACCINE_GOAL)


def test_capability_inesistente_scartata_e_mai_nel_piano(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org))

            adapter = llm_gateway.OpenAIAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=_proposta_json(agenti_suggeriti=[
                    {"capability": "social", "motivazione": "m"}, {"capability": "capability-mai-esistita", "motivazione": "m2"},
                ]), provider="openai", modello_effettivo="gpt-4o",
                latenza_ms=12, input_tokens=10, output_tokens=10, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "openai": adapter})

            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert "capability-mai-esistita" in res["normalized_plan"]["capability_extra_scartate"]
            assert "capability-mai-esistita" not in res["activeAgentIds"]
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- escalation budget: SOLO verso maggiore cautela ----------------
def test_budget_assente_su_richiesta_ads_escalation_a_needs_clarification(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org))

            adapter = llm_gateway.OpenAIAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=_proposta_json(
                    agenti_suggeriti=[{"capability": "ads", "motivazione": "campagna a pagamento richiesta"}],
                    task_proposti=[{"nome": "ads", "capability": "ads", "ordine": 1}],
                ), provider="openai", modello_effettivo="gpt-4o",
                latenza_ms=12, input_tokens=10, output_tokens=10, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "openai": adapter})

            goal = "Prepara una campagna pubblicitaria a pagamento per promuovere le focaccine del Bakery & Coffee di Merate."
            res = await SVC.create_plan_with_brain(db, org, "user-test", goal)
            assert res["status"] == "NEEDS_CLARIFICATION"
            assert res["plan"] is None
            assert any("budget" in q.lower() for q in res["questions"])
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_rischio_bloccante_dal_llm_produce_blocked_risk(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org))

            adapter = llm_gateway.OpenAIAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=_proposta_json(rischi=[{"categoria": "irreversibile", "severita": "ALTA", "descrizione": "azione non reversibile rilevata"}]),
                provider="openai", modello_effettivo="gpt-4o",
                latenza_ms=12, input_tokens=10, output_tokens=10, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "openai": adapter})

            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["status"] == "BLOCKED_RISK"
            assert res["plan"] is None
            assert "irreversibile" in res["risk_flags"]

            piani = await db.plans.count_documents({"organization_id": org})
            assert piani == 0  # nessun piano creato: l'escalation ha bloccato PRIMA della creazione
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ==================== Correzione architetturale: LLM PRIMA delle keyword ====================
# Item 1/2/3/4 della verifica: la comprensione libera deve poter precedere
# (mai seguire) la selezione deterministica a parola chiave, restando
# comunque validata contro i registry reali e i guardrail deterministici.

GOAL_SENZA_KEYWORD = "Voglio aumentare i clienti."


def test_richiesta_priva_di_keyword_tecniche_compresa_dallLLM(monkeypatch):
    """GOAL_SENZA_KEYWORD non contiene ALCUNA parola chiave di capability
    (verificato: detect_capabilities() ritorna []) ne' azienda/prodotto nel
    testo — solo il Fact Ledger (facts dichiarati) fornisce il contesto
    aziendale, esattamente come per un'organizzazione reale gia' onboardata.
    Con il rilevamento a sola keyword la richiesta finirebbe SEMPRE in
    NEEDS_CLARIFICATION generico. Con una proposta LLM validata deve invece
    produrre un piano reale."""
    from app.brain.planning.agent_selector import detect_capabilities
    assert detect_capabilities(GOAL_SENZA_KEYWORD) == []

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await write_fact(db, org_id=org, user_id="user-test", field="ragione_sociale",
                             value="Bakery & Coffee", source="test", method="DICHIARATO", confidence=1.0)
            await write_fact(db, org_id=org, user_id="user-test", field="prodotto",
                             value="focaccine artigianali", source="test", method="DICHIARATO", confidence=1.0)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org))

            adapter = llm_gateway.OpenAIAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=_proposta_json(agenti_suggeriti=[{"capability": "strategy", "motivazione": "serve una strategia per acquisire clienti"}],
                                     task_proposti=[{"nome": "strategia", "capability": "strategy", "ordine": 1}]),
                provider="openai", modello_effettivo="gpt-4o",
                latenza_ms=12, input_tokens=10, output_tokens=10, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "openai": adapter})

            res = await SVC.create_plan_with_brain(db, org, "user-test", GOAL_SENZA_KEYWORD)
            assert res["status"] == "READY", res.get("questions")
            assert res["plan"] is not None
            assert "strategy" in res["normalized_plan"]["capability_validate"]
            deliverable_types = {t["deliverable_type"] for t in res["tasks"]}
            assert "marketing_strategy" in deliverable_types
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_dipendenze_llm_reali_nel_dag_m2(monkeypatch):
    """task_proposti[].dipende_da deve tradursi in depends_on REALI sui
    documenti db.tasks (id risolti da m2/engine.py::create_plan, invariato),
    non solo in metadati — il DAG viene davvero costruito dalla proposta
    validata, non solo esposto in lettura."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org))

            adapter = llm_gateway.OpenAIAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=_proposta_json(
                    agenti_suggeriti=[{"capability": "strategy", "motivazione": "m"}, {"capability": "social", "motivazione": "m2"}],
                    task_proposti=[
                        {"nome": "strategia", "capability": "strategy", "ordine": 1, "dipende_da": []},
                        {"nome": "post social", "capability": "social", "ordine": 2, "dipende_da": ["strategia"]},
                    ],
                ), provider="openai", modello_effettivo="gpt-4o",
                latenza_ms=12, input_tokens=10, output_tokens=10, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "openai": adapter})

            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["status"] == "READY"
            tasks = await db.tasks.find({"plan_id": res["plan"]["id"]}, {"_id": 0}).to_list(50)
            strategia_task = next(t for t in tasks if t["deliverable_type"] == "marketing_strategy")
            social_task = next(t for t in tasks if t["deliverable_type"] == "social_content")
            assert social_task["depends_on"] == [strategia_task["id"]]
            assert strategia_task["depends_on"] == []
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_compliance_non_bypassabile_llm_mai_interpellato(monkeypatch):
    """Una richiesta che implica un'azione esterna reale deve restare
    BLOCKED_RISK SEMPRE, e l'LLM non deve nemmeno essere interpellato (mai
    spendere su una richiesta gia' esclusa, mai una possibilita' per la
    proposta di aggirare il blocco): il doppio di test dell'adapter solleva
    un errore se richiamato."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org))

            def _mai_chiamato(**kw):
                raise AssertionError("l'LLM non deve mai essere interpellato per una richiesta gia' bloccata deterministicamente")
            adapter = llm_gateway.OpenAIAdapter()
            monkeypatch.setattr(adapter, "genera_json", _mai_chiamato)
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "openai": adapter})

            goal = "Scrivi e invia una mail ai prospect pensionistici senza il loro consenso."
            res = await SVC.create_plan_with_brain(db, org, "user-test", goal)
            assert res["status"] == "BLOCKED_RISK"
            assert res["plan"] is None
            assert "llm_understanding" not in res  # mai calcolato: l'LLM non e' mai stato interpellato
            piani = await db.plans.count_documents({"organization_id": org})
            assert piani == 0
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ==================== Ogni provider primary nel flusso COMPLETO di service.py ====================
def _mock_result(provider, testo=None):
    return LLMResult(
        testo=testo or _proposta_json(), provider=provider, modello_effettivo=f"modello-{provider}",
        latenza_ms=15, input_tokens=8, output_tokens=8, troncata=False,
    )


def test_primary_openai_flusso_completo(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org, provider_type="openai", model="gpt-4o"))
            adapter = llm_gateway.OpenAIAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: _mock_result("openai"))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "openai": adapter})

            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["status"] == "READY"
            assert res["llm_understanding"]["mode"] == "REALE"
            assert res["llm_understanding"]["provider_effettivo"] == "openai"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_primary_anthropic_flusso_completo(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org, provider_type="anthropic", model="claude-x"))
            adapter = llm_gateway.AnthropicAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: _mock_result("anthropic"))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "anthropic": adapter})

            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["status"] == "READY"
            assert res["llm_understanding"]["mode"] == "REALE"
            assert res["llm_understanding"]["provider_effettivo"] == "anthropic"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_primary_gemini_flusso_completo(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org, provider_type="gemini", model="gemini-x"))
            adapter = llm_gateway.GeminiAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: _mock_result("gemini"))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "gemini": adapter})

            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["status"] == "READY"
            assert res["llm_understanding"]["mode"] == "REALE"
            assert res["llm_understanding"]["provider_effettivo"] == "gemini"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_primary_requesty_flusso_completo(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org, provider_type="requesty", model="anthropic/claude-sonnet-4-5"))

            from app.integrations import requesty_gateway as rg
            from app.integrations.requesty_gateway import RisultatoGenerazioneRequesty
            monkeypatch.setattr(rg, "genera_json", lambda **kw: RisultatoGenerazioneRequesty(
                testo=_proposta_json(), modello_effettivo="anthropic/claude-sonnet-4-5",
                latenza_ms=20, input_tokens=9, output_tokens=9, troncata=False,
            ))

            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["status"] == "READY"
            assert res["llm_understanding"]["mode"] == "REALE"
            assert res["llm_understanding"]["provider_effettivo"] == "requesty"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_fallback_provider_flusso_completo(monkeypatch):
    """Primary (openai) fallisce, fallback (anthropic) riesce: il piano
    finale deve riflettere la proposta del FALLBACK, non un finto successo
    del primary."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org, provider_type="openai", model="gpt-4o", priority=1))
            await db.ai_connections.insert_one(_connessione(org, provider_type="anthropic", model="claude-x", priority=2))

            openai_adapter = llm_gateway.OpenAIAdapter()
            def _fallisce(**kw):
                raise llm_gateway.LLMGatewayError("rete", "irraggiungibile", "openai")
            monkeypatch.setattr(openai_adapter, "genera_json", _fallisce)

            anthropic_adapter = llm_gateway.AnthropicAdapter()
            monkeypatch.setattr(anthropic_adapter, "genera_json", lambda **kw: _mock_result("anthropic"))

            monkeypatch.setattr(llm_gateway, "ADAPTERS", {
                **llm_gateway.ADAPTERS, "openai": openai_adapter, "anthropic": anthropic_adapter,
            })

            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["status"] == "READY"
            assert res["llm_understanding"]["mode"] == "REALE"
            assert res["llm_understanding"]["provider_effettivo"] == "anthropic"
            assert len(res["llm_understanding"]["providers_tried"]) == 2
            assert res["llm_understanding"]["providers_tried"][0]["esito"] == "ERRORE"
            assert res["llm_understanding"]["providers_tried"][1]["esito"] == "OK"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_fallimento_provider_degrada_a_deterministico_piano_creato_comunque(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one(_connessione(org))

            adapter = llm_gateway.OpenAIAdapter()

            def _raise(**kw):
                raise llm_gateway.LLMGatewayError("rete", "irraggiungibile", "openai")
            monkeypatch.setattr(adapter, "genera_json", _raise)
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "openai": adapter})

            res = await SVC.create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["plan"] is not None  # il core CEO funziona comunque
            assert res["llm_understanding"]["mode"] == "DETERMINISTICO"
            assert res["llm_understanding"]["providers_tried"][0]["codice_errore"] == "rete"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())
