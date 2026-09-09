"""Test mirati — completamento Discovery reale, controllo costi preventivo/
consuntivo del brain, uso della conoscenza acquisita (prova del 2026-09-09,
seconda parte). Database di test dedicato (mai actelya3_dev), nessuna
chiamata di rete reale eccetto l'unica prova autorizzata eseguita a parte
tramite il percorso applicativo vero (non in questo file)."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app import audit as audit_module
from app.brain import llm_gateway
from app.brain import service as SVC
from app.brain.audit.memory_audit import get_audit_log
from app.brain.llm_gateway import LLMResult, LLMGatewayError
from app.brain.llm_understanding import _prova_provider, ProviderModelRef
from app.brain.llm_context_builder import BrainLLMContext
from app.brain.memory.session import get_session_store
from app.domains import discovery as D
from app.domains import budget as BUDGET
from app.domains.knowledge import write_fact
from app.domains.budget import get_budget
from app.tools import cost_ledger
from app.m2 import models as M

_MONGO_URL = "mongodb://127.0.0.1:27020"
_TEST_DB = "actelya3_test_verifica20260909p2"


def _db(monkeypatch=None):
    client = AsyncIOMotorClient(_MONGO_URL)
    db = client[_TEST_DB]
    if monkeypatch is not None:
        monkeypatch.setattr(audit_module, "db", db)
    return client, db


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, org):
    for c in ("plans", "tasks", "goals", "facts", "discovery_runs", "tool_cost_events",
              "organization_budgets", "settings", "ai_connections", "budgets", "executions"):
        await db[c].delete_many({"organization_id": org})
    await db.settings.delete_many({"id": org})
    await db.organization_budgets.delete_many({"organization_id": org})


@pytest.fixture(autouse=True)
def _reset_singletons():
    get_session_store().reset()
    get_audit_log().reset()
    yield
    get_session_store().reset()
    get_audit_log().reset()


HTML_JS_ONLY = "<html><head><title>Acme</title></head><body>Per usare questa app abilitare JavaScript.</body></html>"
HTML_REALE = (
    "<html><head><title>Acme Software House</title>"
    "<meta name='description' content='Acme sviluppa piattaforme SaaS per la logistica.'></head>"
    "<body><h1>Soluzioni logistiche intelligenti</h1>"
    "<p>Acme e' una software house specializzata in gestione magazzino, tracciamento spedizioni e "
    "ottimizzazione delle rotte per aziende di trasporto merci in tutta Italia.</p>"
    "<h2>Chi siamo</h2><h2>Prodotti</h2>"
    "<a href='https://www.instagram.com/acmesoftware'>Instagram</a>"
    "<a href='https://www.linkedin.com/company/acme'>LinkedIn</a>"
    "</body></html>"
)


def _mock_fetch_sincrono(monkeypatch, html: str, status_code: int = 200):
    monkeypatch.setattr(D, "_fetch_sincrono", lambda url: {
        "ok": True, "url_finale": url, "status_code": status_code, "testo": html,
    })


def _mock_fetch_sincrono_fallito(monkeypatch, motivo: str):
    monkeypatch.setattr(D, "_fetch_sincrono", lambda url: {
        "ok": False, "motivo": motivo, "url_tentato": url,
    })


# ==================== 1) Discovery reale: permesso, esiti, fallback JS ====================
def test_discovery_real_fetch_disattivato_senza_permesso_specifico(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            _mock_fetch_sincrono(monkeypatch, HTML_REALE)
            risultato = await D.fetch_sito_reale(db, org, "https://esempio-acme.it/")
            assert risultato is None, "senza settings.discovery_real_fetch=True, nessun tentativo reale"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_discovery_contenuto_letto_e_persistito_con_evidenza(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "discovery_real_fetch": True}}, upsert=True)
            _mock_fetch_sincrono(monkeypatch, HTML_REALE)
            risultato = await D.fetch_sito_reale(db, org, "https://esempio-acme.it/")
            assert risultato["esito"] == D.ESITO_LETTO
            assert risultato["titolo"] == "Acme Software House"
            assert any("instagram.com/acmesoftware" in s for s in risultato["social_links"])

            f = await write_fact(db, org_id=org, user_id="u", field="titolo_sito_estratto",
                                 value=risultato["titolo"], source="esempio-acme.it", method="ESTRATTO",
                                 confidence=0.75, evidence={"url": risultato["url"], "acquisito_il": risultato["acquisito_il"],
                                                            "estratto": risultato["titolo"]})
            assert f["evidence"][0]["url"] == "https://esempio-acme.it/"
            assert f["evidence"][0]["acquisito_il"]
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_discovery_fallback_js_quando_statico_insufficiente(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "discovery_real_fetch": True}}, upsert=True)
            _mock_fetch_sincrono(monkeypatch, HTML_JS_ONLY)

            async def _fake_js(url):
                return {"ok": True, "url_finale": url, "status_code": 200, "testo": HTML_REALE}
            monkeypatch.setattr(D, "_fetch_con_rendering_js", _fake_js)

            risultato = await D.fetch_sito_reale(db, org, "https://esempio-acme.it/")
            assert risultato["esito"] == D.ESITO_LETTO
            assert risultato["via_rendering_js"] is True
            assert risultato["titolo"] == "Acme Software House"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_discovery_js_fallback_non_disponibile_esito_esplicito(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "discovery_real_fetch": True}}, upsert=True)
            _mock_fetch_sincrono(monkeypatch, HTML_JS_ONLY)
            monkeypatch.setattr(D, "_fetch_con_rendering_js", lambda url: asyncio.sleep(0, result=None))

            risultato = await D.fetch_sito_reale(db, org, "https://esempio-acme.it/")
            assert risultato["esito"] == D.ESITO_INSUFFICIENTE_JS, "mai spacciato per CONTENUTO_LETTO se il fallback non produce nulla"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_discovery_accesso_impedito_nessun_dato_simulato_al_suo_posto(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "discovery_real_fetch": True}}, upsert=True)
            _mock_fetch_sincrono_fallito(monkeypatch, "status_non_ok")
            risultato = await D.fetch_sito_reale(db, org, "https://esempio-acme.it/")
            assert risultato["esito"] == D.ESITO_ACCESSO_IMPEDITO
            assert risultato["titolo"] is None
            assert risultato["social_links"] == []
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_discovery_rerun_stesso_dominio_non_duplica_ne_alza_affidabilita(monkeypatch):
    """Percorso applicativo completo (process_run), non solo fetch_sito_reale
    diretto: due esecuzioni di Discovery sullo stesso sito non devono ne'
    duplicare i fatti reali ne' alzarne l'affidabilita' da sole."""
    async def scenario():
        client, db = _db()
        # process_run() usa il 'db' GLOBALE del modulo (from ..db import db,
        # legato a MONGO_URL/.env — oggi actelya3_dev), non un parametro
        # esplicito: va sostituito qui — e chiama log_audit(), che a sua
        # volta attraversa il 'db' GLOBALE di app.audit (guardia autouse in
        # conftest.py): entrambi vanno sostituiti con lo stesso db isolato.
        monkeypatch.setattr(D, "db", db)
        monkeypatch.setattr(audit_module, "db", db)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "discovery_real_fetch": True}}, upsert=True)
            _mock_fetch_sincrono(monkeypatch, HTML_REALE)

            for _ in range(2):
                run_doc = {
                    "id": f"disco-{uuid.uuid4().hex[:8]}", "organization_id": org, "created_by": "u",
                    "status": "IN_CODA", "mode": "SIMULATO", "target_website": "https://esempio-acme.it/",
                    "target_social": [], "started_at": None, "finished_at": None, "facts_written": [],
                    "warnings": [], "real_fetch": None,
                }
                await db.discovery_runs.insert_one(dict(run_doc))
                await D.process_run(run_doc)

            righe = await db.facts.find({"organization_id": org, "field": "titolo_sito_estratto"}).to_list(10)
            assert len(righe) == 1, "nessun fatto duplicato dopo due esecuzioni identiche"
            assert righe[0]["confidence"] == 0.75, "nessun rinforzo di affidabilita' senza nuova evidenza indipendente"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_discovery_social_non_trovati_nessun_profilo_inventato(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "discovery_real_fetch": True}}, upsert=True)
            html_senza_social = "<html><head><title>Acme</title></head><body>" + ("contenuto reale " * 30) + "</body></html>"
            _mock_fetch_sincrono(monkeypatch, html_senza_social)
            risultato = await D.fetch_sito_reale(db, org, "https://esempio-acme.it/")
            assert risultato["esito"] == D.ESITO_LETTO
            assert risultato["social_links"] == [], "nessun social inventato quando non ce ne sono sulla pagina"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


# ==================== 2) Budget preventivo/consuntivo del brain ====================
def test_budget_insufficiente_blocca_zero_chiamate_al_provider(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await cost_ledger.set_daily_cap(db, org, 0.0000001, "test")
            chiamate = {"n": 0}
            adapter = llm_gateway.RequestyAdapter()

            def _spia(**kw):
                chiamate["n"] += 1
                return LLMResult(testo="{}", provider="requesty", modello_effettivo="claude-test",
                                 latenza_ms=1, input_tokens=10, output_tokens=10, troncata=False)
            monkeypatch.setattr(adapter, "genera_json", _spia)
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "requesty": adapter})

            ref = ProviderModelRef(provider_type="requesty", connection_id="c", model="claude-test",
                                   timeout=20.0, max_tokens=1000)
            _, tentativo = await _prova_provider(db, org, ref, BrainLLMContext(richiesta_originale="test"))
            assert tentativo.esito == "ERRORE"
            assert tentativo.codice_errore == "budget_insufficiente"
            assert chiamate["n"] == 0, "zero chiamate al provider quando il budget preventivo non basta"
            eventi = await db.tool_cost_events.count_documents({"organization_id": org})
            assert eventi == 0
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_contabilizzazione_risposta_valida_non_valida_e_timeout(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            ref = ProviderModelRef(provider_type="requesty", connection_id="c", model="claude-test",
                                   timeout=20.0, max_tokens=1000)
            adapter = llm_gateway.RequestyAdapter()

            # Risposta VALIDA
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo='{"intent":"x","strategia_proposta":"x","priorita":"ALTA","urgenza":"MEDIA","agenti_suggeriti":[],"task_proposti":[]}',
                provider="requesty", modello_effettivo="claude-test", latenza_ms=1,
                input_tokens=100, output_tokens=50, troncata=False))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "requesty": adapter})
            _, t1 = await _prova_provider(db, org, ref, BrainLLMContext(richiesta_originale="test"))
            assert t1.esito == "OK"
            assert t1.stima_costo_usd is not None and t1.stima_costo_usd > 0

            # Risposta NON valida (schema): costo comunque registrato (chiamata reale avvenuta)
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo="non e' json valido", provider="requesty", modello_effettivo="claude-test",
                latenza_ms=1, input_tokens=80, output_tokens=20, troncata=False))
            _, t2 = await _prova_provider(db, org, ref, BrainLLMContext(richiesta_originale="test"))
            assert t2.esito == "ERRORE" and t2.codice_errore == "risposta_non_valida"
            assert t2.stima_costo_usd is not None and t2.stima_costo_usd > 0, "una risposta non valida e' comunque una chiamata reale gia' pagata"

            # Timeout/errore di rete: NESSUN token noto, nessun costo "gratis"
            def _timeout(**kw):
                raise LLMGatewayError(codice="rete", messaggio="Timeout", provider="requesty")
            monkeypatch.setattr(adapter, "genera_json", _timeout)
            _, t3 = await _prova_provider(db, org, ref, BrainLLMContext(richiesta_originale="test"))
            assert t3.esito == "ERRORE" and t3.codice_errore == "rete"
            assert t3.stima_costo_usd is None, "nessuna chiamata reale avvenuta: mai un costo (nemmeno 0.0)"

            eventi = await db.tool_cost_events.find({"organization_id": org}, {"_id": 0}).to_list(10)
            assert len(eventi) == 2, "un evento per la risposta valida, uno per quella non valida — nessuno per il timeout"

            # La riserva preventiva non deve restare 'bloccata' dopo i tre tentativi
            org_budget = await db.organization_budgets.find_one({"organization_id": org}, {"_id": 0})
            assert org_budget is None or abs(org_budget.get("reserved_usd", 0.0)) < 1e-9
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_riserva_budget_concorrente_non_permette_doppia_spesa():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await cost_ledger.set_daily_cap(db, org, 0.01, "test")
            # Due riserve concorrenti da 0.006 ciascuna: insieme (0.012) superano
            # il tetto (0.01), quindi al massimo UNA puo' riuscire.
            r1, r2 = await asyncio.gather(
                cost_ledger.reserve_budget(db, org_id=org, tool_id="requesty_llm", estimated_cost=0.006),
                cost_ledger.reserve_budget(db, org_id=org, tool_id="requesty_llm", estimated_cost=0.006),
            )
            successi = sum(1 for ok, _ in (r1, r2) if ok)
            assert successi == 1, "mai entrambe le riserve concorrenti quando insieme supererebbero il tetto"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_budget_pagina_include_costi_brain_senza_alcun_piano(monkeypatch):
    async def scenario():
        client, db = _db()
        monkeypatch.setattr(BUDGET, "db", db)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.budgets.update_one({"id": org}, {"$set": {"id": org, "general_limit": 1.0, "daily_limit": 0.25}}, upsert=True)
            await cost_ledger.record_cost(db, org_id=org, tool_id="requesty_llm", agent_id="coordinatore-actelya", amount=0.004)
            # Nessuna execution/piano per questa org: solo un costo di comprensione del brain.
            assert await db.executions.count_documents({"organization_id": org}) == 0

            class _U(dict):
                def get(self, k, d=None):
                    return super().get(k, d)
            user = {"organization_id": org, "id": "u"}
            b = await get_budget(user=user)
            assert b["spent_brain"] == pytest.approx(0.004)
            assert b["spent_simulated"] == pytest.approx(0.004), "il costo del brain deve comparire anche senza alcun piano/esecuzione"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


# ==================== 3) Uso della conoscenza acquisita dal brain ====================
def test_brain_non_richiede_chiarimento_se_prodotto_gia_da_discovery(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await write_fact(db, org_id=org, user_id="u", field="ragione_sociale", value="Acme",
                             source="onboarding", method="DICHIARATO", confidence=1.0)
            await write_fact(db, org_id=org, user_id="u", field="settore", value="logistica",
                             source="onboarding", method="DICHIARATO", confidence=1.0)
            await write_fact(db, org_id=org, user_id="u", field="sito_web", value="https://esempio-acme.it/",
                             source="onboarding", method="DICHIARATO", confidence=1.0)
            # Prodotto/servizio SOLO da Discovery reale (mai dichiarato dall'utente).
            await write_fact(db, org_id=org, user_id="u", field="prodotti_servizi_candidati",
                             value="gestione magazzino, tracciamento spedizioni", source="esempio-acme.it",
                             method="ESTRATTO", confidence=0.35,
                             evidence={"url": "https://esempio-acme.it/", "acquisito_il": "2026-09-09T00:00:00Z"})

            goal = "Crea tre post testuali distinti in bozza. Non pubblicare, non generare immagini o video."
            res = await SVC.create_plan_with_brain(db, org, "user-test", goal)
            assert res["plan"] is not None, (
                f"non deve chiedere chiarimenti su un prodotto gia' raccolto da Discovery: "
                f"missing_information={res.get('missing_information')}")
            assert "prodotto" not in (res.get("missing_information") or [])
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())
