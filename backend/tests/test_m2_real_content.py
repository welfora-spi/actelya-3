"""Test mirati — generazione REALE (gateway LLM esistente) per i task M2
editorial_plan/social_content (m2/real_content.py + dispatch in m2/engine.py).

Nessuna chiamata reale o a pagamento: il trasporto verso il provider e' un
doppio di test (llm_gateway.get_adapter monkeypatchato), stesso stile di
test_brain_llm_understanding.py. Database dedicato di test (mai il DB di
sviluppo/produzione ne' 'actelya_paperclip_comparison')."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.m2 import models as M
from app.m2 import engine as E
from app.brain import llm_gateway
from app.brain.llm_gateway import LLMGatewayError, LLMResult


def _db():
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27020")
    return client, client["actelya3_test_m2real"]


async def _cleanup(db, *orgs):
    for org in orgs:
        for c in ("plans", "tasks", "executions", "deliverables", "audit_logs",
                  "worker_leases", "goals", "reviews", "ai_connections", "budgets"):
            await db[c].delete_many({"organization_id": org})
        await db.settings.delete_many({"id": org})


def _new_org():
    return f"org-test-real-{uuid.uuid4().hex[:8]}"


def run(coro):
    return asyncio.run(coro)


class _AdapterFittizio:
    """Doppio di test per LLMProviderAdapter: comportamento controllato dal
    test (successo/errore/conteggio chiamate), nessuna rete."""

    def __init__(self, comportamento):
        self.provider_id = "requesty"
        self._comportamento = comportamento
        self.chiamate = []

    def genera_json(self, **kwargs):
        self.chiamate.append(kwargs)
        return self._comportamento(len(self.chiamate), **kwargs)


async def _setup_org(db, org, *, ai_real_mode=True, verified=True, active=True,
                      general_limit=10.0, approved_cap=1.0):
    await M.create_m2_indexes(db)
    await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": ai_real_mode}}, upsert=True)
    if verified is not None:
        await db.ai_connections.insert_one({
            "id": f"aiconn-{uuid.uuid4().hex[:8]}", "organization_id": org,
            "provider_type": "requesty", "effective_model": "anthropic/claude-sonnet-4-5",
            "priority": 1, "verified": verified, "active": active,
            "timeout": 20, "max_tokens": 1200, "api_key_encrypted": None,
            "created_at": "2026-01-01T00:00:00Z",
        })
    if general_limit is not None:
        await db.budgets.update_one({"id": org}, {"$set": {"id": org, "general_limit": general_limit}}, upsert=True)
    return approved_cap


async def _make_plan(db, org, text):
    goal_id = M.new_id("goal")
    await db.goals.insert_one({"id": goal_id, "organization_id": org, "text": text})
    return await E.create_plan(db, org, "user-test", goal_id, text)


async def _approve_and_cap(db, plan, cap):
    r = await E.approve_plan(db, plan["id"], "appr@test")
    ex = await E._get_execution(db, plan)
    await db.executions.update_one({"id": ex["id"]}, {"$set": {"approved_cap": cap}})
    await db.tasks.update_many({"plan_id": plan["id"]}, {"$set": {"inputs.cost": 0.001}})
    return r


CONTENUTO_TEXT = "Piano editoriale con post per Instagram e Facebook della Caffetteria Due Sorsi"


def _risposta_ok(payload):
    def comportamento(n, **kwargs):
        return LLMResult(testo=payload, provider="requesty", modello_effettivo="anthropic/claude-sonnet-4-5",
                          latenza_ms=42, input_tokens=100, output_tokens=50, troncata=False)
    return comportamento


EDITORIAL_JSON = (
    '{"title": "Piano editoriale — Caffetteria Due Sorsi", "cadence": "3 post a settimana", '
    '"tone_of_voice": "Caldo, informale, di quartiere", "pillars": ["Espresso e cappuccino", "Cornetti freschi"], '
    '"calendar": [{"slot": "Lun", "topic": "Espresso della casa", "format": "post", "channel": "Instagram feed"}, '
    '{"slot": "Mer", "topic": "Cappuccino del mattino", "format": "storia", "channel": "Instagram Stories"}, '
    '{"slot": "Ven", "topic": "Cornetti freschi", "format": "post", "channel": "Facebook"}]}'
)
SOCIAL_JSON = (
    '{"platform": "Instagram e Facebook", "posts": ['
    '{"hook": "Espresso come una volta", "body": "Vieni a provare il nostro espresso, preparato ogni giorno con cura.", '
    '"cta": "Passa a trovarci", "hashtags": ["#espresso", "#caffetteria"], "channel": "Instagram feed", '
    '"objective": "Aumentare la notorieta\'", "success_metric": "200 interazioni (obiettivo dimostrativo, simulato)"}, '
    '{"hook": "Cornetti caldi ogni mattina", "body": "I nostri cornetti freschi ti aspettano ogni mattina al banco.", '
    '"cta": "Scoprili in negozio", "hashtags": ["#cornetti", "#colazione"], "channel": "Facebook", '
    '"objective": "Aumentare le visite", "success_metric": "50 visite (obiettivo dimostrativo, simulato)"}]}'
)


# ==================== 1. Percorso reale riuscito (adapter mockato) ====================
def test_percorso_reale_riuscito_editorial_plan(monkeypatch):
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)

            adapter = _AdapterFittizio(_risposta_ok(EDITORIAL_JSON))
            monkeypatch.setattr(llm_gateway, "get_adapter", lambda pt: adapter if pt == "requesty" else None)

            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            r = await E.process_task(db, t1["id"])
            t1_after = await db.tasks.find_one({"id": t1["id"]})
            deliv = await db.deliverables.find_one({"id": t1_after["deliverable_id"]})
            return r, t1_after, deliv, len(adapter.chiamate)
        finally:
            await _cleanup(db, org)
            client.close()

    r, task, deliv, n_chiamate = run(scenario())
    assert r["result"] == "completed"
    assert task["task_status"] == "COMPLETATA"
    assert n_chiamate == 1
    assert deliv["mode"] == "REALE"
    assert deliv["content"]["title"].startswith("Piano editoriale")
    assert deliv["generation"]["provider"] == "requesty"
    assert deliv["generation"]["modello_effettivo"] == "anthropic/claude-sonnet-4-5"
    assert deliv["generation"]["input_tokens"] == 100 and deliv["generation"]["output_tokens"] == 50
    assert deliv["generation"]["stima_costo_usd"] is not None
    assert deliv["status"] in ("COMPLETATO", "COMPLETATO_CON_AVVISI")


# ==================== soggetto immaginario non sostituito dal profilo org ====================
def test_prompt_usa_testo_obiettivo_non_profilo_organizzazione(monkeypatch):
    """Il system/prompt deve portare il testo ESATTO dell'obiettivo (che
    descrive un soggetto immaginario) al provider, mai dati del profilo reale
    dell'organizzazione: qui l'organizzazione non ha ALCUN profilo aziendale
    salvato, eppure la generazione deve comunque riflettere il soggetto
    dichiarato nella richiesta (verificato leggendo cosa viene passato
    all'adapter fittizio)."""
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org)
            testo = "Piano editoriale con post per Instagram e Facebook della Caffetteria Due Sorsi"
            res = await _make_plan(db, org, testo)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)

            adapter = _AdapterFittizio(_risposta_ok(EDITORIAL_JSON))
            monkeypatch.setattr(llm_gateway, "get_adapter", lambda pt: adapter if pt == "requesty" else None)

            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            await E.process_task(db, t1["id"])
            return adapter.chiamate[0]["messaggio_utente"]
        finally:
            await _cleanup(db, org)
            client.close()

    messaggio = run(scenario())
    assert "Caffetteria Due Sorsi" in messaggio


# ==================== 2. Percorso simulato invariato ====================
def test_percorso_simulato_invariato_quando_ai_real_mode_spento(monkeypatch):
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org, ai_real_mode=False)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)

            called = {"n": 0}
            def boom(pt):
                called["n"] += 1
                raise AssertionError("non deve mai essere chiamato in modalita' simulata")
            monkeypatch.setattr(llm_gateway, "get_adapter", boom)

            r = await E.run_ready_tasks(db, plan["id"])
            tasks = await db.tasks.find({"plan_id": plan["id"]}).to_list(50)
            delivs = await db.deliverables.find({"plan_id": plan["id"], "is_current": True}).to_list(50)
            return r, tasks, delivs, called["n"]
        finally:
            await _cleanup(db, org)
            client.close()

    r, tasks, delivs, n_called = run(scenario())
    assert n_called == 0
    assert all(t["task_status"] == "COMPLETATA" for t in tasks)
    assert all(d["mode"] == "SIMULAZIONE" for d in delivs)
    assert any(d["deliverable_type"] == "editorial_plan" and d["content"]["mode"] == "SIMULAZIONE" for d in delivs)


# ==================== 3/4. Connessione/credenziale assente o non verificata ====================
def test_nessuna_connessione_verificata_blocca_senza_chiamare(monkeypatch):
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org, verified=False)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)

            adapter = _AdapterFittizio(_risposta_ok(EDITORIAL_JSON))
            monkeypatch.setattr(llm_gateway, "get_adapter", lambda pt: adapter if pt == "requesty" else None)

            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            r = await E.process_task(db, t1["id"])
            t1_after = await db.tasks.find_one({"id": t1["id"]})
            return r, t1_after, len(adapter.chiamate)
        finally:
            await _cleanup(db, org)
            client.close()

    r, task, n_chiamate = run(scenario())
    assert r["result"] == "real_unavailable"
    assert task["task_status"] == "BLOCCATA"
    assert n_chiamate == 0   # nessuna chiamata al provider: bloccato PRIMA della chiamata
    assert any("connessione" in w.lower() for w in task["warnings"])


# ==================== 5. Budget insufficiente (nessun budget generale) ====================
def test_nessun_budget_generale_blocca_senza_chiamare(monkeypatch):
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org, general_limit=0.0)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)

            adapter = _AdapterFittizio(_risposta_ok(EDITORIAL_JSON))
            monkeypatch.setattr(llm_gateway, "get_adapter", lambda pt: adapter if pt == "requesty" else None)

            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            r = await E.process_task(db, t1["id"])
            t1_after = await db.tasks.find_one({"id": t1["id"]})
            return r, t1_after, len(adapter.chiamate)
        finally:
            await _cleanup(db, org)
            client.close()

    r, task, n_chiamate = run(scenario())
    assert r["result"] == "real_unavailable"
    assert task["task_status"] == "BLOCCATA"
    assert n_chiamate == 0   # nessuna chiamata al provider: bloccato PRIMA della chiamata
    assert any("budget" in w.lower() for w in task["warnings"])


# ==================== 6. Approvazione non valida per la modalita' (piano "vecchio") ====================
def test_approvazione_data_in_simulazione_non_autorizza_spesa_reale(monkeypatch):
    """Simula un piano approvato PRIMA che l'org passasse a REALE (o un piano
    creato prima di questa funzionalita', senza il campo approved_mode): non
    deve mai usare il percorso reale, anche se l'org e' REALE al momento del
    tick."""
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org, ai_real_mode=False)  # org ancora in SIMULAZIONE
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)  # approvato in SIMULAZIONE -> approved_mode="SIMULAZIONE"

            # L'org passa REALE DOPO l'approvazione (stessa condizione di un piano pre-esistente).
            await db.settings.update_one({"id": org}, {"$set": {"ai_real_mode": True}})

            called = {"n": 0}
            monkeypatch.setattr(llm_gateway, "get_adapter", lambda pt: called.__setitem__("n", called["n"] + 1))

            r = await E.run_ready_tasks(db, plan["id"])
            tasks = await db.tasks.find({"plan_id": plan["id"]}).to_list(50)
            delivs = await db.deliverables.find({"plan_id": plan["id"], "is_current": True}).to_list(50)
            t1 = next(t for t in tasks if t["seq"] == 1)
            return t1, delivs, called["n"]
        finally:
            await _cleanup(db, org)
            client.close()

    t1, delivs, n_called = run(scenario())
    assert t1["approved_mode"] == "SIMULAZIONE"
    assert n_called == 0
    assert all(d["mode"] == "SIMULAZIONE" for d in delivs)


def test_task_senza_approved_mode_pre_esistente_resta_simulato(monkeypatch):
    """Un task come quelli gia' persistiti prima di questa funzionalita' (nessun
    campo 'approved_mode' nel documento) non deve mai essere convertito o
    eseguito in automatico in modalita' reale."""
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org, ai_real_mode=True)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)
            # Rimuove il campo approved_mode per simulare un task "vecchio".
            await db.tasks.update_many({"plan_id": plan["id"]}, {"$unset": {"approved_mode": ""}})

            called = {"n": 0}
            monkeypatch.setattr(llm_gateway, "get_adapter", lambda pt: called.__setitem__("n", called["n"] + 1))

            await E.run_ready_tasks(db, plan["id"])
            delivs = await db.deliverables.find({"plan_id": plan["id"], "is_current": True}).to_list(50)
            return delivs, called["n"]
        finally:
            await _cleanup(db, org)
            client.close()

    delivs, n_called = run(scenario())
    assert n_called == 0
    assert all(d["mode"] == "SIMULAZIONE" for d in delivs)


# ==================== 7. Risposta malformata/incompleta ====================
def test_risposta_json_non_valida_blocca_e_registra_costo_reale(monkeypatch):
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)

            adapter = _AdapterFittizio(_risposta_ok("questo non e' JSON valido"))
            monkeypatch.setattr(llm_gateway, "get_adapter", lambda pt: adapter if pt == "requesty" else None)

            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            r = await E.process_task(db, t1["id"])
            t1_after = await db.tasks.find_one({"id": t1["id"]})
            ex = await E._get_execution(db, plan)
            return r, t1_after, ex
        finally:
            await _cleanup(db, org)
            client.close()

    r, task, ex = run(scenario())
    assert r["result"] == "real_failed"
    assert task["task_status"] == "BLOCCATA"
    # Chiamata avvenuta ed elaborata (token noti): costo reale registrato, mai perso.
    assert ex["real_cost"] > 0
    assert any("generazione reale fallita" in w.lower() for w in task["warnings"])


def test_risposta_troncata_non_salvata_come_completata(monkeypatch):
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)

            def comportamento(n, **kwargs):
                return LLMResult(testo=EDITORIAL_JSON, provider="requesty", modello_effettivo="m",
                                  latenza_ms=10, input_tokens=10, output_tokens=5, troncata=True)
            adapter = _AdapterFittizio(comportamento)
            monkeypatch.setattr(llm_gateway, "get_adapter", lambda pt: adapter if pt == "requesty" else None)

            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            r = await E.process_task(db, t1["id"])
            t1_after = await db.tasks.find_one({"id": t1["id"]})
            return r, t1_after
        finally:
            await _cleanup(db, org)
            client.close()

    r, task = run(scenario())
    assert r["result"] == "real_failed"
    assert task["task_status"] == "BLOCCATA"
    assert task["deliverable_id"] is None


# ==================== 8/9. Timeout/esito incerto: nessuna chiamata duplicata ====================
def test_esito_incerto_blocca_senza_retry_automatico(monkeypatch):
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)

            def comportamento(n, **kwargs):
                raise LLMGatewayError("esito_incerto", "Nessuna risposta entro il timeout.", "requesty")
            adapter = _AdapterFittizio(comportamento)
            monkeypatch.setattr(llm_gateway, "get_adapter", lambda pt: adapter if pt == "requesty" else None)

            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            r1 = await E.process_task(db, t1["id"])
            # Un secondo giro di tick non deve ritentare (task terminale BLOCCATA).
            r2 = await E.run_ready_tasks(db, plan["id"])
            t1_after = await db.tasks.find_one({"id": t1["id"]})
            return r1, r2, t1_after, len(adapter.chiamate)
        finally:
            await _cleanup(db, org)
            client.close()

    r1, r2, task, n_chiamate = run(scenario())
    assert r1["result"] == "real_uncertain"
    assert task["task_status"] == "BLOCCATA"
    assert r2["processed"] == 0   # nessun altro task IN_CODA: nessun secondo tentativo
    assert n_chiamate == 1
    assert any("incerto" in w.lower() for w in task["warnings"])


def test_errore_rete_ritenta_fino_a_max_tentativi_poi_fallita(monkeypatch):
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)

            def comportamento(n, **kwargs):
                raise LLMGatewayError("rete", "Impossibile connettersi.", "requesty")
            adapter = _AdapterFittizio(comportamento)
            monkeypatch.setattr(llm_gateway, "get_adapter", lambda pt: adapter if pt == "requesty" else None)

            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            for _ in range(E.MAX_ATTEMPTS + 1):
                await E.run_ready_tasks(db, plan["id"])
            t1_after = await db.tasks.find_one({"id": t1["id"]})
            return t1_after, len(adapter.chiamate)
        finally:
            await _cleanup(db, org)
            client.close()

    task, n_chiamate = run(scenario())
    assert task["task_status"] == "FALLITA"
    assert n_chiamate == E.MAX_ATTEMPTS


# ==================== 10. Isolamento tra organizzazioni ====================
def test_isolamento_tra_organizzazioni(monkeypatch):
    async def scenario():
        client, db = _db()
        org_a = _new_org()
        org_b = _new_org()
        try:
            await _setup_org(db, org_a)                                   # org A: pronta per il reale
            await _setup_org(db, org_b, verified=None, general_limit=None)  # org B: nessuna connessione/budget

            readiness_a = await E.check_readiness(db, org_a)
            readiness_b = await E.check_readiness(db, org_b)
            return readiness_a, readiness_b
        finally:
            await _cleanup(db, org_a, org_b)
            client.close()

    ra, rb = run(scenario())
    assert ra.pronto is True
    assert rb.pronto is False
    assert rb.ref is None


# ==================== 11. Il piano editoriale alimenta i contenuti social ====================
def test_social_content_riceve_il_piano_editoriale_prodotto(monkeypatch):
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            cap = await _setup_org(db, org)
            res = await _make_plan(db, org, CONTENUTO_TEXT)
            plan = res["plan"]
            await _approve_and_cap(db, plan, cap)

            sequenza = [EDITORIAL_JSON, SOCIAL_JSON]
            def comportamento(n, **kwargs):
                return LLMResult(testo=sequenza[n - 1], provider="requesty", modello_effettivo="m",
                                  latenza_ms=10, input_tokens=20, output_tokens=10, troncata=False)
            adapter = _AdapterFittizio(comportamento)
            monkeypatch.setattr(llm_gateway, "get_adapter", lambda pt: adapter if pt == "requesty" else None)

            r = await E.run_ready_tasks(db, plan["id"])
            delivs = {d["deliverable_type"]: d for d in
                      await db.deliverables.find({"plan_id": plan["id"], "is_current": True}).to_list(50)}
            return r, delivs, adapter.chiamate
        finally:
            await _cleanup(db, org)
            client.close()

    r, delivs, chiamate = run(scenario())
    assert set(delivs.keys()) == {"editorial_plan", "social_content"}
    assert delivs["editorial_plan"]["mode"] == "REALE"
    assert delivs["social_content"]["mode"] == "REALE"
    assert len(chiamate) == 2
    # La seconda chiamata (social_content) deve portare il contenuto del piano editoriale.
    assert "Caffetteria Due Sorsi" in chiamate[1]["messaggio_utente"] or "Piano editoriale" in chiamate[1]["messaggio_utente"]
    assert delivs["editorial_plan"]["content"]["title"] in chiamate[1]["messaggio_utente"]
