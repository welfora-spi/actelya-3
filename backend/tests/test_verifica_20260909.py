"""Test mirati per la prova ACTELYA 3 del 2026-09-09 (piano
plan-7340ce4c511a406db485): tre difetti dimostrati e corretti in questa
sessione — nessuna scrittura sul database applicativo reale (database di
test dedicato, mai actelya3_dev), nessuna chiamata di rete reale (adapter
LLM sempre mockato, stesso stile di test_brain_ceo_agent_llm_pipeline.py).

1) knowledge.write_fact: la stessa fonte che rilegge lo stesso valore non
   deve piu' alzare l'affidabilita' (era il bug dietro "55% -> 70% senza
   nuove evidenze": Discovery e' deterministica per dominio, quindi una
   ri-esecuzione confermava sempre se stessa).
2) brain/llm_understanding.py: una chiamata REALE di comprensione (mode
   REALE) deve ora registrare il proprio costo in tool_cost_events, come
   gia' avviene per content-creator via il Tool Execution Gateway.
3) brain/service.py: il tetto (plan.approved_cap) aggiunto quando un task
   'content_item' reale viene collegato al piano deve restare sincronizzato
   con la stima annidata (plan.estimate.*) che la UI legge — mai un tetto
   che esiste solo in approved_cap mentre la stima mostrata resta $0.
"""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app import audit as audit_module
from app.brain import llm_gateway
from app.brain import service as SVC
from app.brain.audit.memory_audit import get_audit_log
from app.brain.llm_gateway import LLMResult
from app.brain.llm_understanding import _prova_provider, ProviderModelRef
from app.brain.llm_context_builder import BrainLLMContext
from app.brain.memory.session import get_session_store
from app.domains.knowledge import write_fact
from app.m2 import models as M

# Stessa istanza gia' verificata raggiungibile in questa sessione (vedi
# scripts/README-DB.md) — database dedicato di test, mai actelya3_dev.
_MONGO_URL = "mongodb://127.0.0.1:27020"
_TEST_DB = "actelya3_test_verifica20260909"

CONTENT_GOAL = (
    "Crea tre post testuali distinti in bozza. "
    "Usa la conoscenza aziendale gia' disponibile e soltanto informazioni documentate. "
    "Ogni post deve avere titolo, corpo e invito a visitare il sito, con tono coerente. "
    "Non pubblicare, non inviare email e non generare immagini o video. "
    "Voglio tre bozze leggibili e salvate in ACTELYA. "
    # Formato etichettato esplicito richiesto da brain/context.py::_PATTERN_
    # AZIENDA_LABEL/_PATTERN_PRODOTTO_LABEL per evitare la richiesta di
    # chiarimento (senza questo, il triage chiede "nome dell'azienda"/
    # "prodotto" anche con un profilo aziendale gia' scritto nel Fact
    # Ledger, perche' l'arricchimento automatico salta l'etichetta quando
    # il nome compare gia' altrove nel testo in forma libera — stesso
    # comportamento osservato nel piano reale, dove serviva un ciclo di
    # chiarimento esplicito).
    "Azienda: Test Azienda. Prodotto: servizi di consulenza informatica."
)


def _db(monkeypatch=None):
    client = AsyncIOMotorClient(_MONGO_URL)
    db = client[_TEST_DB]
    if monkeypatch is not None:
        # tool_gateway.authorize()/record_execution() -> log_audit scrivono
        # sul db GLOBALE (app/audit.py: 'from .db import db', legato a
        # MONGO_URL/.env — oggi il database reale actelya3_dev): mai
        # lasciare che questi test lo raggiungano (stesso principio della
        # guardia autouse di conftest.py, qui soddisfatto esplicitamente
        # col db di test di QUESTA esecuzione, creato nello stesso event
        # loop — mai un client Motor riusato tra loop diversi).
        monkeypatch.setattr(audit_module, "db", db)
    return client, db


async def _cleanup(db, org):
    for c in ("plans", "tasks", "executions", "deliverables", "audit_logs", "goals",
              "brain_audit_events", "brain_sessions", "settings", "ai_connections", "facts",
              "content_items", "tool_cost_events", "organizations", "budgets"):
        await db[c].delete_many({"organization_id": org})
    await db.settings.delete_many({"id": org})


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_singletons():
    get_session_store().reset()
    get_audit_log().reset()
    yield
    get_session_store().reset()
    get_audit_log().reset()


# ==================== 1) Fact Ledger: nessun bump senza nuova evidenza ====================
def test_write_fact_stessa_fonte_stesso_valore_non_alza_affidabilita():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            f1 = await write_fact(db, org_id=org, user_id="u", field="tono_di_voce",
                                  value="Professionale e diretto", source="discovery_sito",
                                  method="ESTRATTO", confidence=0.55)
            assert f1["confidence"] == 0.55

            # Rilettura IDENTICA dalla STESSA fonte (es. Discovery rieseguita
            # sullo stesso dominio, deterministica): nessuna nuova evidenza,
            # l'affidabilita' NON deve salire.
            f2 = await write_fact(db, org_id=org, user_id="u", field="tono_di_voce",
                                  value="Professionale e diretto", source="discovery_sito",
                                  method="ESTRATTO", confidence=0.55)
            assert f2["confidence"] == 0.55, "la stessa fonte non deve mai alzare l'affidabilita' da sola"
            assert f2["id"] == f1["id"]

            righe = await db.facts.find({"organization_id": org, "field": "tono_di_voce"}).to_list(10)
            assert len(righe) == 1, "nessun duplicato scritto per una rilettura senza nuova evidenza"
            assert righe[0]["confidence"] == 0.55

            # Una fonte DIVERSA che confermi lo stesso valore resta invece
            # una reale conferma indipendente: l'affidabilita' sale.
            f3 = await write_fact(db, org_id=org, user_id="u", field="tono_di_voce",
                                  value="Professionale e diretto", source="https://esempio.it/pagina-reale",
                                  method="ESTRATTO", confidence=0.55)
            assert f3["confidence"] == pytest.approx(0.70), "una fonte diversa deve continuare a rinforzare"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ==================== 2) Brain: la comprensione REALE registra il costo ====================
def test_comprensione_brain_reale_registra_costo_in_tool_cost_events(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            prima = await db.tool_cost_events.count_documents({"organization_id": org})
            assert prima == 0

            import json
            proposta = json.dumps({
                "intent": "test", "strategia_proposta": "test",
                "priorita": "ALTA", "urgenza": "MEDIA",
                "agenti_suggeriti": [{"capability": "content", "motivazione": "test"}],
                "task_proposti": [{"nome": "post", "capability": "content", "ordine": 1,
                                   "priorita": "ALTA", "scadenza": None}],
            })
            adapter = llm_gateway.RequestyAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=proposta, provider="requesty", modello_effettivo="claude-test",
                latenza_ms=42, input_tokens=1000, output_tokens=500, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "requesty": adapter})

            ref = ProviderModelRef(provider_type="requesty", connection_id="conn-test", model="claude-test",
                                   timeout=20.0, max_tokens=1000)
            contesto = BrainLLMContext(richiesta_originale=CONTENT_GOAL)

            proposta_obj, tentativo = await _prova_provider(db, org, ref, contesto)
            assert tentativo.esito == "OK"
            assert tentativo.input_tokens == 1000 and tentativo.output_tokens == 500
            assert tentativo.stima_costo_usd == pytest.approx(round(1500 * 0.000002, 6))

            eventi = await db.tool_cost_events.find({"organization_id": org}, {"_id": 0}).to_list(10)
            assert len(eventi) == 1, "esattamente un evento di costo per una chiamata reale, mai duplicato"
            assert eventi[0]["tool_id"] == "requesty_llm"
            assert eventi[0]["agent_id"] == "coordinatore-actelya"
            assert eventi[0]["amount"] == pytest.approx(round(1500 * 0.000002, 6))
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ==================== 3) Preventivo: tetto e stima restano sincronizzati ====================
def test_task_content_item_allinea_stima_e_tetto_del_piano(monkeypatch):
    """La capability 'content' non ha alcun rilevamento a parola chiave
    (backend/app/brain/planning/agent_selector.py::detect_capabilities): entra
    nel piano SOLO tramite una proposta LLM che la suggerisce esplicitamente
    (stesso principio di test_capability_reale_ma_non_rilevata_da_keyword_
    entra_nel_piano in test_brain_ceo_agent_llm_pipeline.py) — coerente con
    come e' nato davvero il piano reale plan-7340ce4c511a406db485 (llm_
    understanding.mode='REALE')."""
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            for campo, valore in (("ragione_sociale", "Test Azienda"), ("prodotto", "servizi informatici"),
                                  ("settore", "servizi informatici"), ("sito_web", "https://esempio.it/")):
                await write_fact(db, org_id=org, user_id="user-test", field=campo, value=valore,
                                 source="onboarding", method="DICHIARATO", confidence=1.0)

            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one({
                "organization_id": org, "provider_type": "requesty", "effective_model": "claude-test",
                "priority": 1, "verified": True, "active": True, "timeout": 20, "max_tokens": 1000,
                "id": f"aiconn-{uuid.uuid4().hex[:8]}", "api_key_encrypted": None,
            })
            import json
            proposta = json.dumps({
                "intent": "creare tre post", "strategia_proposta": "content-creator produce i post",
                "priorita": "ALTA", "urgenza": "MEDIA",
                "agenti_suggeriti": [{"capability": "content", "motivazione": "richiesta esplicita di post"}],
                "task_proposti": [{"nome": "post", "capability": "content", "ordine": 1,
                                   "priorita": "ALTA", "scadenza": None}],
            })
            adapter = llm_gateway.RequestyAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=proposta, provider="requesty", modello_effettivo="claude-test",
                latenza_ms=12, input_tokens=10, output_tokens=10, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "requesty": adapter})

            res = await SVC.create_plan_with_brain(db, org, "user-test", CONTENT_GOAL)
            assert res["plan"] is not None
            plan = await db.plans.find_one({"id": res["plan"]["id"]}, {"_id": 0})

            content_task = next((t for t in res["tasks"] if t["deliverable_type"] == "content_item"), None)
            assert content_task is not None, "il goal deve generare un task content_item reale"

            # Il bug osservato: approved_cap (0.03) esisteva gia', ma
            # plan.estimate.* (letto dalla UI, Sala Riunioni/dettaglio
            # piano) restava a 0 — un tetto invisibile. Ora devono coincidere.
            assert plan["approved_cap"] > 0
            assert plan["estimate"]["approvable_cap"] == pytest.approx(plan["approved_cap"])
            assert plan["estimate"]["cost_probable"] == pytest.approx(plan["approved_cap"])
            assert plan["estimate"]["cost_max"] == pytest.approx(plan["approved_cap"])
            assert plan["estimate"]["calls_estimated"] >= 1
            assert plan["estimate"]["external_tools_cost"] == pytest.approx(plan["approved_cap"])
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ==================== 4) Azienda gia' nota in forma libera (mai chiarimento ridondante) ====================
def test_azienda_nel_testo_libero_non_richiede_chiarimento_se_dichiarata(monkeypatch):
    """Bug reale riprodotto durante la prova E2E del 2026-09-09: un obiettivo
    che nomina l'azienda in forma libera ("... dedicate a X di Acme.") non
    corrisponde a nessun pattern regex di context.py (serve un'etichetta
    esplicita "Azienda:"/"Brand:" o un pattern rigido tipo "del/della X"):
    anche con ragione_sociale gia' DICHIARATA nel Fact Ledger e un LLM che
    la riconosce perfettamente, la 'doppia rete di sicurezza' (triage_goal,
    indipendente dall'LLM) chiedeva comunque il nome dell'azienda — un fatto
    gia' disponibile trattato come mancante."""
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            for campo, valore in (("ragione_sociale", "Acme"), ("prodotto", "servizi di consulenza"),
                                  ("settore", "servizi"), ("sito_web", "https://esempio-acme.it/")):
                await write_fact(db, org_id=org, user_id="user-test", field=campo, value=valore,
                                 source="onboarding", method="DICHIARATO", confidence=1.0)

            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one({
                "organization_id": org, "provider_type": "requesty", "effective_model": "claude-test",
                "priority": 1, "verified": True, "active": True, "timeout": 20, "max_tokens": 1000,
                "id": f"aiconn-{uuid.uuid4().hex[:8]}", "api_key_encrypted": None,
            })
            import json
            proposta = json.dumps({
                "intent": "creare tre post", "strategia_proposta": "x", "priorita": "ALTA", "urgenza": "MEDIA",
                "agenti_suggeriti": [{"capability": "content", "motivazione": "x"}],
                "task_proposti": [{"nome": "post", "capability": "content", "ordine": 1,
                                   "priorita": "ALTA", "scadenza": None}],
            })
            adapter = llm_gateway.RequestyAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=proposta, provider="requesty", modello_effettivo="claude-test",
                latenza_ms=12, input_tokens=10, output_tokens=10, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "requesty": adapter})

            # NESSUNA etichetta "Azienda:"/"Brand:", solo linguaggio naturale
            # — stessa formulazione (adattata) del piano di prova reale.
            goal = ("Prepara tre bozze testuali distinte dedicate ai servizi di consulenza di Acme. "
                    "Non pubblicare, non generare immagini o video.")
            res = await SVC.create_plan_with_brain(db, org, "user-test", goal)
            assert res["plan"] is not None, (
                f"non deve chiedere l'azienda quando gia' dichiarata nel Fact Ledger, anche se il testo la "
                f"nomina in forma libera: missing_information={res.get('missing_information')}, "
                f"clarifying_questions={res.get('clarifying_questions')}")
            assert "azienda" not in (res.get("missing_information") or [])
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ==================== 5) Chiarimenti proposti dall'LLM persistiti in sessione ====================
def test_domande_llm_persistite_in_session_clarifications(monkeypatch):
    """Bug reale riprodotto durante la prova E2E del 2026-09-09 (dopo il fix
    del test precedente): il ramo 'domande_extra' di service.py (righe
    ~696-712, alimentato da normalized.domande_aggiuntive/budget/rischio)
    restituiva le domande nel payload HTTP ma non le scriveva MAI in
    session.clarifications (a differenza del ramo di
    prepare_brain_session/selection.clarifying_questions, che lo fa da
    sempre). Un refresh a meta' di QUESTO tipo di chiarimento perdeva le
    domande (NewGoal.jsx si affida a sess.clarifications per la ripresa), e
    il riesame successivo non poteva riconoscerle come 'gia' poste'."""
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            for campo, valore in (("ragione_sociale", "Acme"), ("prodotto", "servizi di consulenza"),
                                  ("settore", "servizi"), ("sito_web", "https://esempio-acme.it/")):
                await write_fact(db, org_id=org, user_id="user-test", field=campo, value=valore,
                                 source="onboarding", method="DICHIARATO", confidence=1.0)

            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one({
                "organization_id": org, "provider_type": "requesty", "effective_model": "claude-test",
                "priority": 1, "verified": True, "active": True, "timeout": 20, "max_tokens": 1000,
                "id": f"aiconn-{uuid.uuid4().hex[:8]}", "api_key_encrypted": None,
            })
            import json
            # "dati_mancanti" con voci che NON matchano _DATI_NON_INDISPENSABILI_KW
            # (niente prezzo/target/competitor/...): classify_missing_data le
            # deve marcare REQUIRED_TO_START -> domande_aggiuntive non vuoto.
            proposta = json.dumps({
                "intent": "creare tre post", "strategia_proposta": "x", "priorita": "ALTA", "urgenza": "MEDIA",
                "agenti_suggeriti": [{"capability": "content", "motivazione": "x"}],
                "task_proposti": [{"nome": "post", "capability": "content", "ordine": 1,
                                   "priorita": "ALTA", "scadenza": None}],
                "dati_mancanti": ["obiettivi KPI specifici della campagna"],
            })
            adapter = llm_gateway.RequestyAdapter()
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=proposta, provider="requesty", modello_effettivo="claude-test",
                latenza_ms=12, input_tokens=10, output_tokens=10, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "requesty": adapter})

            goal = ("Prepara tre bozze testuali distinte dedicate ai servizi di consulenza di Acme. "
                    "Non pubblicare, non generare immagini o video.")
            res = await SVC.create_plan_with_brain(db, org, "user-test", goal)
            assert res["status"] == "NEEDS_CLARIFICATION", (
                f"precondizione del test non soddisfatta: atteso un ciclo di chiarimento LLM, "
                f"ottenuto status={res.get('status')}, plan={res.get('plan')}")
            assert res["questions"], "il payload deve comunque esporre le domande all'utente"

            sid = res["session_id"]
            snap = await db.brain_sessions.find_one({"session_id": sid, "organization_id": org}, {"_id": 0})
            assert snap is not None, "la sessione deve essere persistita"
            domande_salvate = {c["question"] for c in (snap.get("clarifications") or [])}
            for q in res["questions"]:
                assert q in domande_salvate, (
                    f"domanda LLM '{q}' mostrata all'utente ma NON persistita in "
                    f"session.clarifications (perduta a un refresh, non riconoscibile al riesame)")
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())
