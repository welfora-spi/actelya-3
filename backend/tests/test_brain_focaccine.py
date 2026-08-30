"""Brain — test di regressione end-to-end sul caso di accettazione ("focaccine").
Richiede MongoDB locale + motor/pymongo (stesso requisito di test_m2_block4.py):
NON eseguito in questa fase per assenza di tali dipendenze nell'ambiente corrente
(vedi report di integrazione). Verifica che il piano creato tramite il brain:
- mantenga azienda/localita/prodotto/pubblico/canali nel goal_context persistito;
- produca deliverable concreti (non generici) gia' persistiti come override,
  visibili PRIMA di qualunque approvazione;
- non contenga mai testo pensionistico;
- non esegua alcuna azione esterna (resta in SIMULAZIONE)."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.brain.service import create_plan_with_brain
from app.m2 import models as M

FOCACCINE_GOAL = (
    "Prepara una campagna social per pubblicizzare le focaccine artigianali del "
    "Bakery & Coffee di Merate. Crea una strategia locale, un piano editoriale e "
    "tre post per Instagram e Facebook rivolti alle famiglie e ai lavoratori della "
    "zona. Usa dati simulati, non contattare clienti e non pubblicare nulla."
)

_DOMINI_VIETATI = ["pensione", "inps", "tfr", "previdenz", "rpo", "welfora"]


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya2_db"]


async def _cleanup(db, org):
    for c in ("plans", "tasks", "executions", "deliverables", "audit_logs", "goals"):
        await db[c].delete_many({"organization_id": org})


def run(coro):
    return asyncio.run(coro)


def test_focaccine_piano_coerente_e_deliverable_concreti():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            res = await create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            assert res["requires_clarification"] is False, res.get("questions")
            plan = res["plan"]
            assert plan is not None

            ctx = res.get("brain_trace") and plan["goal_context"]
            assert ctx["azienda"] == "Bakery & Coffee"
            assert ctx["localita"] == "Merate"
            assert "focaccine" in (ctx["prodotto"] or "").lower()
            assert set(["Instagram", "Facebook"]).issubset(set(ctx["canali"]))

            tasks = res["tasks"]
            assert len(tasks) >= 3  # marketing_strategy, editorial_plan, social_content (+ altri per CAMPAGNA)

            overrides = res["brain_trace"]["content_overrides"]
            assert overrides, "il brain deve aver prodotto almeno un override contestuale"

            social_tasks = [t for t in tasks if t["deliverable_type"] == "social_content"]
            assert social_tasks
            social_content = social_tasks[0]["inputs"]["deliverable_override"]
            assert len(social_content["posts"]) == 3  # "tre post" dal testo dell'obiettivo
            blob_social = str(social_content).lower()
            assert "bakery" in blob_social and "merate" in blob_social
            assert "instagram" in blob_social.lower() or "Instagram" in social_content["platform"]

            testo_completo = str(res).lower()
            for termine in _DOMINI_VIETATI:
                assert termine not in testo_completo, f"testo pensionistico/estraneo rilevato: {termine}"

            for t in tasks:
                assert t["task_status"] == "IN_ATTESA_APPROVAZIONE"  # nessuna azione eseguita/pubblicata

            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_focaccine_deliverable_gia_persistito_prima_di_approvare():
    """I contenuti del brain sono scritti su task.inputs.deliverable_override SUBITO
    alla creazione del piano (visibili in lettura), non solo dopo l'approvazione:
    verifica leggendo direttamente dal DB, senza chiamare alcun endpoint di approvazione."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            res = await create_plan_with_brain(db, org, "user-test", FOCACCINE_GOAL)
            plan = res["plan"]
            persisted = await db.tasks.find({"plan_id": plan["id"]}, {"_id": 0}).to_list(50)
            con_override = [t for t in persisted if "deliverable_override" in t.get("inputs", {})]
            assert con_override, "almeno un task deve avere il contenuto brain gia' persistito"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_goal_ambiguo_non_crea_piano_ne_azioni():
    """Un obiettivo senza azienda/prodotto non deve creare alcun goal/piano:
    solo domande di chiarimento, nessuno stato sporco in DB."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            res = await create_plan_with_brain(db, org, "user-test", "Fai qualcosa di utile per me")
            assert res["requires_clarification"] is True
            assert res["plan"] is None
            assert res["questions"]
            goals = await db.goals.count_documents({"organization_id": org})
            plans = await db.plans.count_documents({"organization_id": org})
            assert goals == 0 and plans == 0
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())
