"""Blocco 5 — sei deliverable versionati e validati (SIMULAZIONE).
Test positivi/negativi per ogni validatore, concorrenza sul versionamento,
integrazione col motore e compatibilità email M1. Nessuna chiamata reale."""
import asyncio
import uuid

from motor.motor_asyncio import AsyncIOMotorClient

from app.m2 import models as M
from app.m2 import engine as E
from app.m2 import deliverables as D
from app.models import new_id


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, org):
    for c in ("plans", "tasks", "executions", "deliverables", "audit_logs", "worker_leases", "goals"):
        await db[c].delete_many({"organization_id": org})


# ==================== PRODUTTORI -> validi ====================
def test_produttori_generano_deliverable_validi():
    org = {"nome_commerciale": "ACME"}
    expected_ok = {"COMPLETATO", "COMPLETATO_CON_AVVISI"}
    for dtype in ("marketing_strategy", "editorial_plan", "social_content",
                  "ad_campaign_draft", "lead_gen_plan", "kpi_report", "email"):
        content = D.produce_deliverable(dtype, {"deliverable_type": dtype}, {}, org)
        v = D.validate_deliverable(dtype, content)
        assert v["status"] in expected_ok, f"{dtype} -> {v}"
        assert v["errors"] == [], f"{dtype} errori inattesi: {v['errors']}"


def test_ad_campaign_sempre_draft_e_non_pubblicata():
    c = D.produce_ad_campaign_draft({}, {}, {})
    assert c["status"] == "DRAFT" and c["published"] is False


def test_lead_gen_senza_pii():
    c = D.produce_lead_gen_plan({}, {}, {})
    blob = str(c)
    assert not D.PII_EMAIL_RE.search(blob) and not D.PII_PHONE_RE.search(blob)
    assert D.validate_lead_gen_plan(c)["status"] in {"COMPLETATO", "COMPLETATO_CON_AVVISI"}


def test_kpi_dichiara_simulato_o_non_disponibile():
    c = D.produce_kpi_report({}, {}, {})
    for k in c["kpis"]:
        assert k["source"] in ("SIMULATO", "NON_DISPONIBILE")


# ==================== VALIDATORI negativi ====================
def test_reject_vuoti_e_token_vietati():
    bad = {"title": "", "executive_summary": "TODO", "value_proposition": "N/A",
           "positioning": "UNKNOWN", "target_segments": [], "channels": [], "objectives": []}
    assert D.validate_marketing_strategy(bad)["status"] == "BLOCCATO"


def test_reject_rifiuto_modello():
    bad = D.produce_marketing_strategy({}, {}, {})
    bad["executive_summary"] = "Mi dispiace, non posso generare questo contenuto."
    assert D.validate_marketing_strategy(bad)["status"] == "BLOCCATO"


def test_placeholder_in_campo_non_variabile_bloccato():
    bad = D.produce_marketing_strategy({}, {}, {})
    bad["title"] = "Strategia [DA_DEFINIRE]"  # titolo non è campo variabile
    r = D.validate_marketing_strategy(bad)
    assert r["status"] == "BLOCCATO"
    assert any("placeholder" in e.lower() for e in r["errors"])


def test_placeholder_in_campo_variabile_avviso():
    c = D.produce_social_content({}, {}, {})  # body/cta contengono [Nome]/[Azienda]
    r = D.validate_social_content(c)
    assert r["status"] == "COMPLETATO_CON_AVVISI" and r["errors"] == []


def test_campagna_pubblicata_bloccata():
    bad = D.produce_ad_campaign_draft({}, {}, {})
    bad["status"] = "PUBLISHED"
    bad["published"] = True
    r = D.validate_ad_campaign_draft(bad)
    assert r["status"] == "BLOCCATO"


def test_lead_gen_con_pii_bloccato():
    bad = D.produce_lead_gen_plan({}, {}, {})
    bad["outreach_sequence"][0]["message_template"] = "Scrivimi a mario.rossi@example.com per parlarne"
    assert D.validate_lead_gen_plan(bad)["status"] == "BLOCCATO"


def test_kpi_dato_inventato_come_reale_bloccato():
    bad = D.produce_kpi_report({}, {}, {})
    bad["kpis"][0]["source"] = "REALE"  # non consentito
    assert D.validate_kpi_report(bad)["status"] == "BLOCCATO"


def test_kpi_simulato_senza_current_bloccato():
    bad = D.produce_kpi_report({}, {}, {})
    bad["kpis"][0]["source"] = "SIMULATO"
    bad["kpis"][0]["current"] = None
    assert D.validate_kpi_report(bad)["status"] == "BLOCCATO"


# ==================== VERSIONAMENTO ====================
def _fake_task(org, plan_id, dtype="social_content"):
    return {"id": f"task-{uuid.uuid4().hex[:8]}", "plan_id": plan_id, "organization_id": org,
            "version": 1, "goal_id": "g1", "deliverable_type": dtype,
            "artifact_slot": f"{dtype}-1", "agent_id": "content_social"}


def test_versionamento_non_sovrascrive():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            plan_id = f"plan-{uuid.uuid4().hex[:8]}"
            task = _fake_task(org, plan_id)
            content = D.produce_social_content(task, {}, {})
            val = D.validate_social_content(content)
            d1 = await D.create_deliverable_version(db, org_id=org, plan={"id": plan_id}, task=task,
                                                    content=content, validation=val, agent_id="content_social")
            d2 = await D.create_deliverable_version(db, org_id=org, plan={"id": plan_id}, task=task,
                                                    content=content, validation=val, agent_id="content_social")
            total = await db.deliverables.count_documents({"plan_id": plan_id, "task_id": task["id"]})
            current = await db.deliverables.count_documents({"plan_id": plan_id, "task_id": task["id"], "is_current": True})
            return d1["version"], d2["version"], total, current, d2["is_current"]
        finally:
            await _cleanup(db, org); client.close()
    v1, v2, total, current, d2_current = run(scenario())
    assert v1 == 1 and v2 == 2 and total == 2   # nessuna sovrascrittura
    assert current == 1 and d2_current is True  # solo l'ultima è corrente


def test_versionamento_concorrente():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            plan_id = f"plan-{uuid.uuid4().hex[:8]}"
            task = _fake_task(org, plan_id)
            content = D.produce_social_content(task, {}, {})
            val = D.validate_social_content(content)
            a, b = await asyncio.gather(
                D.create_deliverable_version(db, org_id=org, plan={"id": plan_id}, task=task, content=content, validation=val, agent_id="content_social"),
                D.create_deliverable_version(db, org_id=org, plan={"id": plan_id}, task=task, content=content, validation=val, agent_id="content_social"),
            )
            total = await db.deliverables.count_documents({"plan_id": plan_id, "task_id": task["id"]})
            current = await db.deliverables.count_documents({"plan_id": plan_id, "task_id": task["id"], "is_current": True})
            return {a["version"], b["version"]}, total, current
        finally:
            await _cleanup(db, org); client.close()
    versions, total, current = run(scenario())
    assert versions == {1, 2}   # due versioni distinte, nessuna persa/sovrascritta
    assert total == 2 and current == 1  # esattamente una corrente


def test_piu_deliverable_stesso_tipo_task_diversi():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            plan_id = f"plan-{uuid.uuid4().hex[:8]}"
            t1 = _fake_task(org, plan_id, "social_content"); t1["artifact_slot"] = "social_content-1"
            t2 = _fake_task(org, plan_id, "social_content"); t2["artifact_slot"] = "social_content-2"
            content = D.produce_social_content(t1, {}, {})
            val = D.validate_social_content(content)
            await D.create_deliverable_version(db, org_id=org, plan={"id": plan_id}, task=t1, content=content, validation=val, agent_id="content_social")
            await D.create_deliverable_version(db, org_id=org, plan={"id": plan_id}, task=t2, content=content, validation=val, agent_id="content_social")
            total = await db.deliverables.count_documents({"plan_id": plan_id, "deliverable_type": "social_content"})
            return total
        finally:
            await _cleanup(db, org); client.close()
    assert run(scenario()) == 2  # stesso tipo, task/slot diversi -> consentito


# ==================== INTEGRAZIONE COL MOTORE ====================
def test_engine_campagna_produce_deliverable_validi():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            goal_id = M.new_id("goal")
            res = await E.create_plan(db, org, "user-test", goal_id, "Prepara una campagna social e adv per il lancio")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            await E.run_ready_tasks(db, plan["id"])
            tasks = await db.tasks.find({"plan_id": plan["id"]}).to_list(50)
            delivs = await db.deliverables.find({"plan_id": plan["id"], "is_current": True}).to_list(50)
            p = await db.plans.find_one({"id": plan["id"]})
            types = {d["deliverable_type"] for d in delivs}
            return ([t["task_status"] for t in tasks], len(delivs), types, p["plan_status"],
                    all(d["valid"] for d in delivs))
        finally:
            await _cleanup(db, org); client.close()
    statuses, n_deliv, types, plan_status, all_valid = run(scenario())
    assert all(s == "COMPLETATA" for s in statuses)
    assert n_deliv == 5 and all_valid
    assert types == {"marketing_strategy", "editorial_plan", "social_content", "ad_campaign_draft", "kpi_report"}
    assert plan_status == "COMPLETATO"


def test_engine_deliverable_invalido_non_conta_ma_costo_registrato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            goal_id = M.new_id("goal")
            res = await E.create_plan(db, org, "user-test", goal_id, "Genera un report KPI del trimestre")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            t1 = await db.tasks.find_one({"plan_id": plan["id"], "seq": 1})
            # inietta contenuto invalido (rifiuto): il validatore deve marcare BLOCCATO
            bad = {"title": "TODO", "period": "N/A", "kpis": []}
            await db.tasks.update_one({"id": t1["id"]}, {"$set": {"inputs.deliverable_override": bad}})
            await E.run_ready_tasks(db, plan["id"])
            d = await db.deliverables.find_one({"plan_id": plan["id"], "task_id": t1["id"]}, {"_id": 0})
            t = await db.tasks.find_one({"id": t1["id"]})
            p = await db.plans.find_one({"id": plan["id"]})
            return d["status"], d["valid"], t.get("cost", 0), t["attempt"], p["plan_status"]
        finally:
            await _cleanup(db, org); client.close()
    dstatus, valid, cost, attempt, plan_status = run(scenario())
    assert dstatus == "BLOCCATO" and valid is False   # non conta come valido
    assert cost > 0 and attempt == 1                   # costo e tentativo registrati
    assert plan_status == "BLOCCATO"                   # piano non completato con successo


def test_engine_email_m1_compat():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            goal_id = M.new_id("goal")
            res = await E.create_plan(db, org, "user-test", goal_id, "Scrivi una breve email commerciale")
            plan = res["plan"]
            assert len(res["plan"]["topo_order"]) == 1  # piano a una attività (compat M1)
            await E.approve_plan(db, plan["id"], "appr@test")
            await E.run_ready_tasks(db, plan["id"])
            d = await db.deliverables.find_one({"plan_id": plan["id"], "is_current": True}, {"_id": 0})
            return d["deliverable_type"], d["status"], d["valid"]
        finally:
            await _cleanup(db, org); client.close()
    dtype, status, valid = run(scenario())
    assert dtype == "email"
    assert status in {"COMPLETATO", "COMPLETATO_CON_AVVISI"} and valid is True


# ==================== GUARD MODALITA' SIMULAZIONE (ramo 409) ====================
def test_guard_tick_bloccato_in_modalita_reale():
    """_assert_simulation deve sollevare 409 se ai_real_mode=True, consentire se SIMULAZIONE."""
    from fastapi import HTTPException

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            # Modalità REALE -> blocco sicuro 409
            await E._global_db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            raised = None
            try:
                await E._assert_simulation(org)
            except HTTPException as e:
                raised = e.status_code
            # Modalità SIMULAZIONE -> nessun blocco
            await E._global_db.settings.update_one({"id": org}, {"$set": {"ai_real_mode": False}})
            ok = True
            try:
                await E._assert_simulation(org)
            except HTTPException:
                ok = False
            return raised, ok
        finally:
            await E._global_db.settings.delete_one({"id": org})
            client.close()
    raised, ok = run(scenario())
    assert raised == 409   # bloccato in modalità reale (invocato solo da POST /plans, vedi sotto)
    assert ok is True      # consentito in SIMULAZIONE


def test_http_create_plan_bloccato_reale_ma_http_tick_piano_esistente_no():
    """Correzione (allineamento implementazione/test): _assert_simulation()
    e' invocato SOLO da http_create_plan() — l'accesso HTTP DIRETTO al
    percorso M2 grezzo (bypassa triage/selezione agenti/compliance del
    Brain: nessun percorso prodotto lo chiama, Plans.jsx crea sempre da
    "Nuovo Obiettivo" -> POST /brain/plans). http_tick() su un piano GIA'
    creato deve restare disponibile anche a modalità reale attiva: fa
    progredire un piano di qualunque origine (Brain incluso), mai bloccato
    dalla modalità reale attivata per ALTRE capability dello stesso piano
    (es. domains/reel.py/flyer.py/leadgen)."""
    from fastapi import HTTPException

    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        user = {"id": "u1", "email": "u1@test.it", "organization_id": org, "role": "OPERATORE"}
        try:
            # Piano creato e approvato in SIMULAZIONE, PRIMA di attivare il reale.
            res = await E.create_plan(E._global_db, org, user["id"], new_id("goal"),
                                      "Prepara una campagna social e adv per il lancio")
            plan_id = res["plan"]["id"]
            await E.approve_plan(E._global_db, plan_id, user["email"])

            await E._global_db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)

            # POST /m2/plans grezzo: bloccato.
            creato_bloccato = None
            try:
                await E.http_create_plan(E.PlanBody(text="Scrivi una breve email commerciale"), user=user)
            except HTTPException as e:
                creato_bloccato = e.status_code

            # POST /m2/plans/{id}/tick su un piano GIA' esistente: NON bloccato.
            tick_status = None
            try:
                tick_res = await E.http_tick(plan_id, user=user)
                tick_status = "ok"
            except HTTPException as e:
                tick_status = e.status_code

            return creato_bloccato, tick_status, tick_res if tick_status == "ok" else None
        finally:
            await E._global_db.settings.delete_one({"id": org})
            await _cleanup(E._global_db, org)
            client.close()

    creato_bloccato, tick_status, tick_res = run(scenario())
    assert creato_bloccato == 409
    assert tick_status == "ok"
    assert tick_res.get("mode") == "SIMULAZIONE"
