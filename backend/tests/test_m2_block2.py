"""Blocco 2 — test planner/DAG/classificazione + fix fallback swap_current_version.
Tutto in SIMULAZIONE, nessuna chiamata reale."""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from app.m2 import planner as P
from app.m2 import models as M


# ---------------- Classificazione deterministica ----------------
def test_objective_mapping_deterministic():
    cases = {
        "Prepara una strategia di marketing per un'azienda fittizia": "STRATEGIA",
        "Prepara una campagna social e adv per il lancio": "CAMPAGNA",
        "Scrivi un post social per Instagram": "CONTENUTO",
        "Costruisci un piano di lead generation per prospect B2B": "LEAD_GEN",
        "Genera un report KPI del trimestre": "REPORT",
        "Scrivi una breve email commerciale": "EMAIL",
        "Fai qualcosa di utile": "AMBIGUO",
    }
    for text, expected in cases.items():
        r1 = P.classify_objective(text)
        r2 = P.classify_objective(text)
        assert r1 == r2, "classificazione non deterministica"
        assert r1["objective_type"] == expected, f"{text} -> {r1['objective_type']} (atteso {expected})"


def test_intent_types_and_safety_precedence():
    assert P.classify_objective("Scrivi una breve email")["intent"]["intent_type"] == "PRODUZIONE"
    assert P.classify_objective("Invia una mail ai clienti")["intent"]["intent_type"] == "AZIONE_ESTERNA"
    assert P.classify_objective("Scrivi e invia una mail")["intent"]["intent_type"] == "MISTO"
    # Ambiguo sensibile (consenso/prospect) senza verbo di produzione/invio -> AMBIGUO
    amb = P.classify_objective("Gestisci il consenso dei prospect")
    assert amb["intent"]["intent_type"] == "AMBIGUO"
    # Precedenza sicurezza: presenza di flag di rischio quando c'è invio/dati
    ext = P.classify_objective("Invia una mail ai clienti")
    assert "invio" in ext["intent"]["risk_flags"]


def test_ambiguo_requires_clarification_no_external():
    r = P.classify_objective("Aiutami con il marketing, non so bene cosa")
    assert r["objective_type"] == "AMBIGUO"
    assert r["requires_clarification"] is True
    assert r["external_action_auto"] is False
    assert P.decompose("AMBIGUO") == []  # nessuna attività auto-creata


def test_no_external_action_task_created():
    # Anche per CAMPAGNA (che poi produrrà una bozza ad) nessun task è un'azione esterna.
    external_like = {"send", "publish", "invio", "pubblica"}
    for otype in ["STRATEGIA", "CONTENUTO", "CAMPAGNA", "LEAD_GEN", "REPORT", "EMAIL"]:
        for spec in P.decompose(otype):
            assert spec["deliverable_type"] in M.DELIVERABLE_TYPES
            assert spec["deliverable_type"] not in external_like


# ---------------- DAG / topologico ----------------
def test_dag_acyclic_and_topo_order():
    specs = P.decompose("CAMPAGNA")
    v = P.validate_dag(specs)
    assert v["ok"], v["errors"]
    order = P.topological_order(specs)
    pos = {k: i for i, k in enumerate(order)}
    # ogni dipendenza precede il dipendente
    for s in specs:
        for d in s["depends_on"]:
            assert pos[d] < pos[s["key"]]


def test_dag_cycle_detected():
    specs = [
        {"key": "a", "deliverable_type": "marketing_strategy", "agent_id": "x", "depends_on": ["b"]},
        {"key": "b", "deliverable_type": "editorial_plan", "agent_id": "y", "depends_on": ["a"]},
    ]
    v = P.validate_dag(specs)
    assert v["ok"] is False
    assert any("Ciclo" in e for e in v["errors"])


def test_dag_orphan_dependency():
    specs = [
        {"key": "a", "deliverable_type": "marketing_strategy", "agent_id": "x", "depends_on": ["zzz"]},
    ]
    v = P.validate_dag(specs)
    assert v["ok"] is False
    assert any("orfana" in e for e in v["errors"])


def test_email_single_task_plan():
    sk = P.plan_skeleton("Scrivi una breve email commerciale")
    assert sk["objective_type"] == "EMAIL"
    assert len(sk["tasks"]) == 1
    assert sk["tasks"][0]["deliverable_type"] == "email"
    assert sk["valid"] is True and sk["topo_order"] == ["t1"]


# ---------------- Fix fallback swap_current_version ----------------
async def _swap_fallback_scenario():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["actelya2_db"]
    await db.plans.delete_many({"goal_id": "G_SWAP_TEST"})
    await db.plans.insert_one({"id": "pv1", "goal_id": "G_SWAP_TEST", "version": 1, "is_current": True})
    await db.plans.insert_one({"id": "pv2", "goal_id": "G_SWAP_TEST", "version": 2, "is_current": False})

    audits = []
    async def audit_stub(**kw):
        audits.append(kw)

    raised = False
    try:
        # new_plan_id inesistente: set-new fallisce -> deve ripristinare pv1
        await M.swap_current_version(db, "G_SWAP_TEST", "NON_ESISTE", audit=audit_stub)
    except Exception:
        raised = True

    current = [p["id"] async for p in db.plans.find({"goal_id": "G_SWAP_TEST", "is_current": True})]
    await db.plans.delete_many({"goal_id": "G_SWAP_TEST"})
    client.close()
    return raised, current, audits


def test_swap_fallback_restores_previous_current():
    raised, current, audits = asyncio.run(_swap_fallback_scenario())
    assert raised is True, "lo swap avrebbe dovuto sollevare un errore"
    assert current == ["pv1"], f"la versione corrente precedente non e' stata ripristinata: {current}"
    assert any(a.get("action") == "SWAP_CURRENT_VERSION_FAILED" for a in audits), "errore non registrato in audit"


def test_swap_success_moves_current():
    async def scenario():
        client = AsyncIOMotorClient("mongodb://localhost:27017")
        db = client["actelya2_db"]
        await db.plans.delete_many({"goal_id": "G_SWAP_OK"})
        await db.plans.insert_one({"id": "pa", "goal_id": "G_SWAP_OK", "version": 1, "is_current": True})
        await db.plans.insert_one({"id": "pb", "goal_id": "G_SWAP_OK", "version": 2, "is_current": False})
        await M.swap_current_version(db, "G_SWAP_OK", "pb", audit=lambda **k: _noop())
        cur = [p["id"] async for p in db.plans.find({"goal_id": "G_SWAP_OK", "is_current": True})]
        await db.plans.delete_many({"goal_id": "G_SWAP_OK"})
        client.close()
        return cur

    async def _noop():
        return None

    cur = asyncio.run(scenario())
    assert cur == ["pb"], f"la corrente non e' passata a pb: {cur}"
