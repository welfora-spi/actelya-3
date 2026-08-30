"""Brain — integrazione verticale minima: collega context + classifier +
capability_selector + gateway + producers + guard al planner/motore M2 SENZA
sostituire DAG, persistenza, lease, idempotenza, budget, recovery, audit o
approvazioni (tutti in m2/engine.py, qui MAI modificati, solo richiamati).

Flusso:
1. Estrae contesto + triage dal testo dell'obiettivo (context.py, classifier.py).
   Se mancano informazioni indispensabili -> ritorna SOLO domande di
   chiarimento: nessun goal/piano viene creato, nessuno stato sporco.
2. Delega la creazione del piano (DAG, task, stima, indici, audit) a
   m2.engine.create_plan, INVARIATO.
3. Per ogni task del piano gia' creato, prova a produrre un contenuto
   contestuale (producers.py) tramite il gateway MOCK; lo accetta come
   deliverable_override SOLO se supera sia il validatore strutturale M2
   (m2.deliverables.validate_deliverable, invariato) sia il controllo di
   coerenza del brain (guard.py). In caso contrario NON scarta il task ne'
   blocca il piano: lascia che m2/engine.py::_execute produca il contenuto
   generico di default (fallback sempre sicuro, mai un piano bloccato per un
   errore del brain).
4. Salva il GoalContext e la traccia delle decisioni del brain sul piano
   (campi additivi 'goal_context'/'brain', mai un campo gia' usato da M2)."""
from __future__ import annotations

from ..m2 import engine as m2_engine
from ..m2.deliverables import validate_deliverable
from ..models import base_record, new_id
from .capability_selector import select_capabilities
from .classifier import triage_goal
from .context import extract_goal_context
from .gateway import get_default_gateway
from .guard import guard_content
from .producers import produce_brain_deliverable


async def create_plan_with_brain(db, org_id: str, user_id: str, goal_text: str) -> dict:
    triage = triage_goal(goal_text)
    if triage.requires_clarification:
        return {
            "plan": None,
            "requires_clarification": True,
            "objective_type": triage.objective_type,
            "questions": triage.questions,
            "goal_context": triage.context,
        }

    goal_id = new_id("goal")
    await db.goals.insert_one({
        **base_record(org_id, user_id), "id": goal_id, "text": goal_text,
        "status": "IN_APPROVAZIONE", "mode": "SIMULAZIONE",
    })

    res = await m2_engine.create_plan(db, org_id, user_id, goal_id, goal_text)  # invariato
    if res.get("requires_clarification") or not res.get("plan"):
        return {
            "plan": None, "requires_clarification": True,
            "objective_type": res.get("objective_type"),
            "questions": triage.questions, "goal_context": triage.context,
        }

    plan = res["plan"]
    ctx = extract_goal_context(goal_text)
    cap = select_capabilities(goal_text, ctx)
    gateway = get_default_gateway()

    tasks = await db.tasks.find({"plan_id": plan["id"]}, {"_id": 0}).sort("seq", 1).to_list(200)
    overrides: dict[str, str] = {}
    scarti: list[dict] = []
    for task in tasks:
        dtype = task["deliverable_type"]
        contenuto = produce_brain_deliverable(dtype, ctx, cap, gateway)
        if contenuto is None:
            continue  # nessun produttore brain per questo tipo: fallback M2 di default
        ok, motivi = guard_content(dtype, contenuto, ctx, validate_deliverable=validate_deliverable)
        if not ok:
            scarti.append({"task_id": task["id"], "deliverable_type": dtype, "motivi": motivi})
            continue
        await db.tasks.update_one({"id": task["id"]}, {"$set": {"inputs.deliverable_override": contenuto}})
        overrides[task["id"]] = dtype

    brain_trace = {
        "objective_type": triage.objective_type,
        "intent_type": triage.intent_type,
        "risk_flags": triage.risk_flags,
        "capability": cap,
        "content_overrides": overrides,
        "content_fallback": scarti,
    }
    await db.plans.update_one(
        {"id": plan["id"]},
        {"$set": {"goal_context": ctx.come_dict(), "brain": brain_trace}},
    )

    plan["goal_context"] = ctx.come_dict()
    plan["brain"] = brain_trace
    tasks = await db.tasks.find({"plan_id": plan["id"]}, {"_id": 0}).sort("seq", 1).to_list(200)
    return {"plan": plan, "tasks": tasks, "requires_clarification": False, "brain_trace": brain_trace}
