"""Blocco 6 — revisori NON distruttivi Compliance/Auditor (SIMULAZIONE).
Verifica: revisioni persistite e collegate, non distruttività (deliverable invariato),
rilievi (PII, campagna non-DRAFT, incoerenza valid), idempotenza, blocco azioni vietate,
integrazione col motore. Nessuna chiamata reale."""
import asyncio
import uuid

from motor.motor_asyncio import AsyncIOMotorClient

from app.m2 import models as M
from app.m2 import engine as E
from app.m2 import deliverables as D
from app.m2 import reviews as R
from app.m2.agents_registry import assert_action_allowed, ContractError


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, org):
    for c in ("plans", "tasks", "executions", "deliverables", "audit_logs",
              "worker_leases", "goals", "reviews"):
        await db[c].delete_many({"organization_id": org})


def _deliverable(org, status="COMPLETATO", dtype="marketing_strategy", content=None):
    return {"id": f"deliv-{uuid.uuid4().hex[:8]}", "organization_id": org,
            "plan_id": "plan-x", "task_id": "task-x", "agent_id": "marketing_strategist",
            "deliverable_type": dtype, "version": 1, "is_current": True,
            "status": status, "valid": status in ("COMPLETATO", "COMPLETATO_CON_AVVISI"),
            "content": content or {"title": "ok"}, "mode": "SIMULAZIONE"}


# ---------------- Reviewer non modifica/cancella (blocco sicuro) ----------------
def test_reviewer_non_puo_modificare_deliverable():
    for aid in ("compliance_reviewer", "auditor"):
        assert assert_action_allowed(aid, "revisione") is True
        for forbidden in ("modifica_deliverable", "cancellazione_deliverable"):
            try:
                assert_action_allowed(aid, forbidden)
                assert False, f"{aid} non doveva permettere {forbidden}"
            except ContractError:
                pass


# ---------------- Non distruttività + collegamenti ----------------
def test_review_non_distruttiva_e_collegata():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d = _deliverable(org)
            await db.deliverables.insert_one(dict(d))
            before = await db.deliverables.find_one({"id": d["id"]}, {"_id": 0})
            res = await R.review_deliverable(db, d, {"cost": 0.001, "attempt": 1})
            after = await db.deliverables.find_one({"id": d["id"]}, {"_id": 0})
            types = sorted(r["review_type"] for r in res)
            linked = all(r["deliverable_id"] == d["id"] and r["plan_id"] == d["plan_id"]
                         and r["organization_id"] == org and r["reviewer_agent"] in
                         ("compliance_reviewer", "auditor") and r["non_destructive"] for r in res)
            return before == after, types, linked, len(res)
        finally:
            await _cleanup(db, org); client.close()
    unchanged, types, linked, n = run(scenario())
    assert unchanged is True                 # deliverable NON modificato
    assert types == ["audit", "compliance"]  # due revisioni
    assert linked is True and n == 2


# ---------------- Rilievi Compliance ----------------
def test_compliance_rileva_pii():
    d = _deliverable("o", dtype="lead_gen_plan",
                     content={"outreach_sequence": [{"message_template": "scrivimi a mario@example.com"}]})
    findings, sev = R.run_compliance(d, {})
    assert sev == "high"
    assert any(f["code"] == "PII" for f in findings)


def test_compliance_rileva_campagna_non_draft():
    d = _deliverable("o", dtype="ad_campaign_draft", content={"status": "PUBLISHED"})
    findings, sev = R.run_compliance(d, {})
    assert sev == "high" and any(f["code"] == "CAMPAIGN_STATUS" for f in findings)


def test_compliance_gdpr_reminder_email():
    d = _deliverable("o", dtype="email", content={"contenuto_completo": "Ciao [Nome]"})
    findings, _ = R.run_compliance(d, {})
    assert any(f["code"] == "GDPR" for f in findings)


# ---------------- Rilievi Audit ----------------
def test_audit_rileva_incoerenza_valid():
    d = _deliverable("o", status="COMPLETATO")
    d["valid"] = False  # incoerente con lo stato
    findings, sev = R.run_audit(d, {})
    assert sev == "high" and any(f["code"] == "VALID_MISMATCH" for f in findings)


def test_audit_rileva_link_mancante():
    d = _deliverable("o")
    d["agent_id"] = None
    findings, _ = R.run_audit(d, {})
    assert any(f["code"] == "MISSING_LINK" for f in findings)


# ---------------- Idempotenza ----------------
def test_review_idempotente():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d = _deliverable(org)
            await R.review_deliverable(db, d, {"cost": 0, "attempt": 1})
            await R.review_deliverable(db, d, {"cost": 0, "attempt": 1})  # seconda volta
            total = await db.reviews.count_documents({"deliverable_id": d["id"]})
            return total
        finally:
            await _cleanup(db, org); client.close()
    assert run(scenario()) == 2  # una compliance + una audit, nessun duplicato


def test_review_idempotente_concorrente():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d = _deliverable(org)
            await asyncio.gather(
                R.review_deliverable(db, d, {"cost": 0, "attempt": 1}),
                R.review_deliverable(db, d, {"cost": 0, "attempt": 1}),
            )
            total = await db.reviews.count_documents({"deliverable_id": d["id"]})
            return total
        finally:
            await _cleanup(db, org); client.close()
    assert run(scenario()) == 2  # unique (deliverable_id, review_type) previene duplicati


# ---------------- Integrazione col motore ----------------
def test_engine_genera_revisioni_per_ogni_deliverable():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            goal_id = M.new_id("goal")
            res = await E.create_plan(db, org, "user-test", goal_id, "Prepara una campagna social e adv per il lancio")
            plan = res["plan"]
            await E.approve_plan(db, plan["id"], "appr@test")
            # snapshot deliverable prima e dopo (le revisioni non devono cambiarli)
            await E.run_ready_tasks(db, plan["id"])
            delivs = await db.deliverables.find({"plan_id": plan["id"], "is_current": True}, {"_id": 0}).to_list(50)
            reviews = await db.reviews.find({"plan_id": plan["id"]}, {"_id": 0}).to_list(200)
            # ogni deliverable ha esattamente 2 revisioni (compliance + audit)
            per_deliv = {}
            for r in reviews:
                per_deliv.setdefault(r["deliverable_id"], set()).add(r["review_type"])
            all_two = all(per_deliv.get(d["id"]) == {"compliance", "audit"} for d in delivs)
            return len(delivs), len(reviews), all_two
        finally:
            await _cleanup(db, org); client.close()
    n_deliv, n_reviews, all_two = run(scenario())
    assert n_deliv == 5
    assert n_reviews == 10 and all_two  # 5 deliverable x 2 revisori
