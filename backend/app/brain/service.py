"""Brain — integrazione verticale minima: collega selezione agenti + context +
classifier + capability_selector + gateway + producers + guard al
planner/motore M2 SENZA sostituire DAG, persistenza, lease, idempotenza,
budget, recovery, audit o approvazioni (tutti in m2/engine.py, qui MAI
modificati, solo richiamati).

Flusso (Blocco B):
0. planning.agent_selector.select_agents(): rileva le capability richieste
   e seleziona SOLO gli agenti necessari (mai "marketing = tutti gli
   agenti"). Se lo stato non è READY (NEEDS_CLARIFICATION / UNSUPPORTED /
   BLOCKED_RISK) si ritorna SUBITO: nessun goal, nessun piano, nessuna
   azione M2 — solo l'esito di triage/selezione.
1. Se READY, estrae contesto + triage dal testo dell'obiettivo (context.py,
   classifier.py) come ulteriore rete di sicurezza. Se mancano informazioni
   indispensabili -> ritorna SOLO domande di chiarimento: nessun goal/piano
   viene creato, nessuno stato sporco.
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
4. Salva il GoalContext, activeAgentIds e la traccia delle decisioni del
   brain sul piano (campi additivi 'goal_context'/'brain'/'active_agent_ids',
   mai un campo gia' usato da M2)."""
from __future__ import annotations

from ..m2 import engine as m2_engine
from ..m2.deliverables import validate_deliverable
from ..models import base_record, new_id
from .agents.agent_map import COORDINATOR_FRONTEND_ID
from .capability_selector import select_capabilities
from .classifier import triage_goal
from .context import extract_goal_context
from .gateway import get_default_gateway
from .guard import guard_content
from .planning.agent_selector import STATUS_READY, SelectionResult, select_agents
from .producers import produce_brain_deliverable


def _selection_payload(selection: SelectionResult) -> dict:
    return {
        "status": selection.status,
        "normalized_goal": selection.normalized_goal,
        "detected_intents": selection.detected_intents,
        "selected_agents": [a.__dict__ for a in selection.selected_agents],
        "activeAgentIds": selection.activeAgentIds,
        "coordinator_agent_id": COORDINATOR_FRONTEND_ID,  # sempre presente, mai in activeAgentIds
        "missing_information": selection.missing_information,
        "clarifying_questions": selection.clarifying_questions,
        "selection_reasons": selection.selection_reasons,
        "excluded_agents": [a.__dict__ for a in selection.excluded_agents],
        "risk_flags": selection.risk_flags,
        "execution_ready": selection.execution_ready,
        "unavailable_capabilities": selection.unavailable_capabilities,
        "simulation_only_capabilities": selection.simulation_only_capabilities,
        "execution_warnings": selection.execution_warnings,
    }


def _esito_non_pronto(selection: SelectionResult) -> dict:
    payload = _selection_payload(selection)
    payload.update({
        "plan": None,
        "tasks": [],
        "requires_clarification": True,
        "objective_type": None,
        "questions": selection.clarifying_questions,
        "goal_context": None,
    })
    return payload


async def create_plan_with_brain(db, org_id: str, user_id: str, goal_text: str) -> dict:
    selection = select_agents(goal_text)
    if selection.status != STATUS_READY:
        # Nessun goal, nessun piano, nessuna azione M2: solo l'esito di
        # triage/selezione (NEEDS_CLARIFICATION / UNSUPPORTED / BLOCKED_RISK).
        return _esito_non_pronto(selection)

    triage = triage_goal(goal_text)
    if triage.requires_clarification:
        # Doppia rete di sicurezza: select_agents() ha dato READY, ma il
        # triage esistente (M2 planner + contesto) rileva comunque
        # un'ambiguità non intercettata dal selettore -> si resta prudenti,
        # nessun goal/piano creato.
        payload = _selection_payload(selection)
        payload.update({
            "plan": None, "tasks": [], "requires_clarification": True,
            "status": "NEEDS_CLARIFICATION", "objective_type": triage.objective_type,
            "questions": triage.questions, "clarifying_questions": triage.questions,
            "goal_context": triage.context,
        })
        return payload

    goal_id = new_id("goal")
    await db.goals.insert_one({
        **base_record(org_id, user_id), "id": goal_id, "text": goal_text,
        "status": "IN_APPROVAZIONE", "mode": "SIMULAZIONE",
    })

    res = await m2_engine.create_plan(db, org_id, user_id, goal_id, goal_text)  # invariato
    if res.get("requires_clarification") or not res.get("plan"):
        payload = _selection_payload(selection)
        payload.update({
            "plan": None, "tasks": [], "requires_clarification": True,
            "status": "NEEDS_CLARIFICATION", "objective_type": res.get("objective_type"),
            "questions": triage.questions, "clarifying_questions": triage.questions,
            "goal_context": triage.context,
        })
        return payload

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
        "agent_selection": _selection_payload(selection),
    }
    await db.plans.update_one(
        {"id": plan["id"]},
        {"$set": {
            "goal_context": ctx.come_dict(),
            "brain": brain_trace,
            "active_agent_ids": selection.activeAgentIds,
        }},
    )

    plan["goal_context"] = ctx.come_dict()
    plan["brain"] = brain_trace
    plan["active_agent_ids"] = selection.activeAgentIds
    tasks = await db.tasks.find({"plan_id": plan["id"]}, {"_id": 0}).sort("seq", 1).to_list(200)

    payload = _selection_payload(selection)
    payload.update({
        "plan": plan, "tasks": tasks, "requires_clarification": False,
        "brain_trace": brain_trace,
    })
    return payload
