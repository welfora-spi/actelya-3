"""Brain — integrazione verticale minima: collega selezione agenti + context +
classifier + capability_selector + gateway + producers + guard al
planner/motore M2 SENZA sostituire DAG, persistenza, lease, idempotenza,
budget, recovery, audit o approvazioni (tutti in m2/engine.py, qui MAI
modificati, solo richiamati).

Flusso (Blocco B, esteso dal Blocco C con memoria di sessione + audit):
0. prepare_brain_session() [Blocco C, PURA: nessun db]: crea/riusa una
   sessione in memory/session.py, registra REQUEST_RECEIVED, esegue
   planning.agent_selector.select_agents() (rileva le capability richieste
   e seleziona SOLO gli agenti necessari, mai "marketing = tutti gli
   agenti"), registra TRIAGE_COMPLETED + AGENT_SELECTED/AGENT_EXCLUDED per
   ciascun agente, aggiorna la sessione con richiesta normalizzata/agenti/
   activeAgentIds/stato. Se lo stato non è READY (NEEDS_CLARIFICATION /
   UNSUPPORTED / BLOCKED_RISK) registra CLARIFICATION_REQUIRED o
   PLAN_BLOCKED (+ EXTERNAL_ACTION_BLOCKED per BLOCKED_RISK) e
   create_plan_with_brain ritorna SUBITO: nessun goal, nessun piano,
   nessuna azione M2 — solo l'esito di triage/selezione + stato sessione/
   audit.
1. Se READY, registra PLAN_ALLOWED, poi estrae contesto + triage dal testo
   dell'obiettivo (context.py, classifier.py) come ulteriore rete di
   sicurezza. Se mancano informazioni indispensabili -> ritorna SOLO domande
   di chiarimento (+ CLARIFICATION_REQUIRED registrato): nessun goal/piano
   viene creato, nessuno stato sporco.
2. Delega la creazione del piano (DAG, task, stima, indici, audit M2) a
   m2.engine.create_plan, INVARIATO.
3. Per ogni task del piano gia' creato, prova a produrre un contenuto
   contestuale (producers.py) tramite il gateway MOCK; lo accetta come
   deliverable_override SOLO se supera sia il validatore strutturale M2
   (m2.deliverables.validate_deliverable, invariato) sia il controllo di
   coerenza del brain (guard.py). In caso contrario NON scarta il task ne'
   blocca il piano: registra ERROR_FALLBACK e lascia che
   m2/engine.py::_execute produca il contenuto generico di default
   (fallback sempre sicuro, mai un piano bloccato per un errore del brain).
4. Salva il GoalContext, activeAgentIds e la traccia delle decisioni del
   brain sul piano (campi additivi 'goal_context'/'brain'/'active_agent_ids',
   mai un campo gia' usato da M2), aggiorna la sessione con plan_id/handoff
   iniziali (WAITING_DEPENDENCY: nessun task e' ancora stato eseguito) e
   porta lo stato della sessione a PLAN_CREATED.

   Correzione C.0 — la creazione del piano NON e' un risultato pronto per
   l'approvazione: RESULT_READY_FOR_APPROVAL NON viene mai registrato qui.
   E' registrabile SOLO tramite mark_result_ready_for_approval(), che
   verifica esplicitamente task completati/approvati, handoff READY e
   deliverable validi prima di registrare l'evento — mai in automatico,
   mai se una condizione manca."""
from __future__ import annotations

from typing import Optional

from ..m2 import engine as m2_engine
from ..m2.deliverables import validate_deliverable
from ..m2.models import new_task
from ..m2.planner import DELIVERABLE_AGENT as M2_DELIVERABLE_AGENT
from ..models import base_record, new_id
from .agents.agent_map import COORDINATOR_FRONTEND_ID, mapping_by_capability
from .audit.memory_audit import (
    EVENT_AGENT_EXCLUDED,
    EVENT_AGENT_SELECTED,
    EVENT_CLARIFICATION_REQUIRED,
    EVENT_ERROR_FALLBACK,
    EVENT_EXTERNAL_ACTION_BLOCKED,
    EVENT_HANDOFF_READY,
    EVENT_HANDOFF_REJECTED,
    EVENT_HANDOFF_WAITING,
    EVENT_PLAN_ALLOWED,
    EVENT_PLAN_BLOCKED,
    EVENT_REQUEST_RECEIVED,
    EVENT_RESULT_READY_FOR_APPROVAL,
    EVENT_TRIAGE_COMPLETED,
    get_audit_log,
)
from .capability_selector import select_capabilities
from .classifier import triage_goal
from .context import augment_goal_text, extract_goal_context
from .gateway import get_default_gateway
from .guard import guard_content
from .memory.session import get_session_store
from .planning.agent_selector import (
    STATUS_BLOCKED_RISK,
    STATUS_NEEDS_CLARIFICATION,
    STATUS_READY,
    SelectionResult,
    select_agents,
)
from .planning.handoff import HANDOFF_READY, collect_task_handoffs
from .producers import produce_brain_deliverable
from ..domains.knowledge import current_facts_map
from ..domains import reel as reel_domain
from ..domains import flyer as flyer_domain
from fastapi import HTTPException

_ACTOR_SELECTOR = "brain.planning.agent_selector"
_ACTOR_SERVICE = "brain.service"

# Item #10 (DECISIONE UFFICIALE) — marcatore additivo, MAI retroattivo: un
# piano creato PRIMA della correzione item #6 (M2 costruiva i task dalla
# propria classify_objective/decompose indipendente, non dalla selezione del
# brain) non ha questo campo. Nessuna migrazione/cancellazione di dati
# esistenti: l'assenza del campo e' sufficiente per riconoscere un piano
# storico e non confonderlo con un risultato prodotto dal flusso corrente
# (vedi Plans.jsx, che mostra un'etichetta "storico" quando manca).
PLAN_GENERATION_TAG = "brain_single_team_v2"

# Capability rilevate dal brain (agent_selector.detect_capabilities) -> deliverable_type
# nativo di M2 (planner.DELIVERABLE_AGENT ne conosce l'agente). SOLO le capability qui
# elencate producono un task M2 "classico" (prodotto simulato deterministico via
# m2/deliverables.py). Le altre capability riconosciute NON compaiono qui perche' non
# hanno un task M2 proprio:
# - "video_reel"/"flyer_image": task REALE aggiunto piu' sotto, collegato a un progetto
#   vero (domains/reel.py / domains/flyer.py), mai tramite questa mappa.
# - "review_compliance"/"audio_voiceover": nessun deliverable_type esiste per loro
#   (agent_map.py: deliverable_type=None) — restano visibili SOLO come agente convocato
#   (activeAgentIds), mai come task del DAG.
_M2_NATIVE_DELIVERABLE = {
    "strategy": "marketing_strategy",
    "editorial": "editorial_plan",
    "social": "social_content",
    "ads": "ad_campaign_draft",
    "leadgen": "lead_gen_plan",
    "analytics": "kpi_report",
    "email": "email",
}


def _brain_task_specs(detected_intents: list) -> list:
    """Costruisce gli SpecTask M2 (stessa forma di planner.decompose():
    {key, name, deliverable_type, depends_on}) ESCLUSIVAMENTE dalle capability che
    il brain ha realmente selezionato per questo obiettivo — mai dalla
    classificazione testuale indipendente di M2 (planner.classify_objective +
    decompose), che ignorerebbe la squadra convocata e potrebbe aggiungere task
    estranei (es. l'intera campagna quando e' stato chiesto solo un flyer).
    Nessuna dipendenza forzata tra i task: l'ordine 'campagna completa'
    (strategia -> editoriale -> social -> ads -> kpi) era un'inferenza di M2
    sul solo testo, non una decisione del brain — qui ogni capability
    selezionata resta un task indipendente, approvabile ed eseguibile da solo."""
    seen: dict = {}
    for cap in detected_intents:
        dtype = _M2_NATIVE_DELIVERABLE.get(cap)
        if dtype and dtype not in seen:
            seen[dtype] = M2_DELIVERABLE_AGENT[dtype]  # verifica esistenza agente M2 (KeyError se mappa disallineata)
    return [
        {"key": f"t{i}", "name": dtype, "deliverable_type": dtype, "depends_on": []}
        for i, dtype in enumerate(seen.keys(), start=1)
    ]


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


def prepare_brain_session(goal_text: str, *, session_id: Optional[str] = None,
                           is_reexamination: bool = False) -> dict:
    """Blocco C — funzione PURA (nessun db, nessuna rete): crea/riusa la
    sessione in memoria, esegue triage/selezione agenti e registra nel
    registro audit in-memory tutte le decisioni prese fino al gate
    READY/non-READY. create_plan_with_brain() la richiama SEMPRE per prima;
    se lo stato non è READY, la creazione del piano non avviene affatto e
    questa funzione da sola descrive già l'intero esito osservabile —
    per questo è testabile senza MongoDB e senza avviare alcun server.

    is_reexamination: True quando goal_text è già stato arricchito con le
    risposte a un chiarimento precedente (vedi create_plan_with_brain,
    parametro clarification) — usato solo per l'audit, non cambia la
    logica di selezione/triage, che resta la stessa per qualunque testo."""
    store = get_session_store()
    audit_log = get_audit_log()
    audit_event_ids: list[str] = []

    sess = store.create_session(session_id=session_id, original_request=goal_text)
    sid = sess["session_id"]

    def _log(event_type: str, *, actor: str, decision: str, reason: str, metadata: Optional[dict] = None,
              goal_id: Optional[str] = None, plan_id: Optional[str] = None) -> None:
        ev = audit_log.record(
            event_type=event_type, session_id=sid, goal_id=goal_id, plan_id=plan_id,
            actor=actor, decision=decision, reason=reason, metadata=metadata or {},
        )
        audit_event_ids.append(ev["event_id"])

    _log(EVENT_REQUEST_RECEIVED, actor=_ACTOR_SERVICE, decision="RECEIVED",
         reason="Richiesta ricevuta dal brain." if not is_reexamination
                else "Richiesta ri-esaminata dopo risposte di chiarimento dell'utente.",
         metadata={"goal_text_length": len(goal_text or ""), "reexamination": is_reexamination})

    selection = select_agents(goal_text)

    _log(EVENT_TRIAGE_COMPLETED, actor=_ACTOR_SELECTOR, decision=selection.status,
         reason=f"Capability rilevate: {selection.detected_intents}.",
         metadata={"detected_intents": selection.detected_intents, "risk_flags": selection.risk_flags,
                   "missing_information": selection.missing_information})

    for a in selection.selected_agents:
        _log(EVENT_AGENT_SELECTED, actor=_ACTOR_SELECTOR, decision="SELECTED", reason=a.reason,
             metadata={"agent_id": a.agent_id, "capability": a.capability, "capabilities": a.capabilities})
    for a in selection.excluded_agents:
        _log(EVENT_AGENT_EXCLUDED, actor=_ACTOR_SELECTOR, decision="EXCLUDED", reason=a.reason,
             metadata={"agent_id": a.agent_id, "capability": a.capability, "capabilities": a.capabilities})

    store.update_session(
        sid, normalized_request=selection.normalized_goal,
        selected_agents=[a.__dict__ for a in selection.selected_agents],
        activeAgentIds=selection.activeAgentIds, status=selection.status,
    )
    for q in selection.clarifying_questions:
        store.append_to_session(sid, "clarifications", {"question": q, "answer": None})

    if selection.status == STATUS_NEEDS_CLARIFICATION:
        _log(EVENT_CLARIFICATION_REQUIRED, actor=_ACTOR_SELECTOR, decision="NEEDS_CLARIFICATION",
             reason="Informazioni indispensabili mancanti o capability non tutte disponibili.",
             metadata={"missing_information": selection.missing_information,
                       "unavailable_capabilities": selection.unavailable_capabilities})
    elif selection.status != STATUS_READY:
        _log(EVENT_PLAN_BLOCKED, actor=_ACTOR_SELECTOR, decision=selection.status,
             reason="Nessun piano creato: richiesta fuori dominio o capability non disponibili.",
             metadata={"unavailable_capabilities": selection.unavailable_capabilities,
                       "risk_flags": selection.risk_flags})
        if selection.status == STATUS_BLOCKED_RISK:
            _log(EVENT_EXTERNAL_ACTION_BLOCKED, actor=_ACTOR_SERVICE, decision="BLOCKED",
                 reason="Richiesta implica un'azione esterna reale o un intento vietato: mai eseguita.",
                 metadata={"risk_flags": selection.risk_flags})
    else:
        _log(EVENT_PLAN_ALLOWED, actor=_ACTOR_SELECTOR, decision="ALLOWED",
             reason="Agenti selezionati, nessun rischio rilevato: si procede col triage M2.",
             metadata={"activeAgentIds": selection.activeAgentIds})

    return {
        "session_id": sid,
        "selection": selection,
        "audit_event_ids": audit_event_ids,
        "session_state": store.get_session(sid),
    }


async def create_plan_with_brain(db, org_id: str, user_id: str, goal_text: str, *,
                                  session_id: Optional[str] = None,
                                  clarification: Optional[dict] = None) -> dict:
    """clarification (opzionale): risposte dell'utente a un precedente esito
    NEEDS_CLARIFICATION, forma {"missing_information": [...], "answers": [...]}
    (stesso ordine/lunghezza delle domande a cui rispondono — vedi
    router.py::ClarificationAnswers). Se presente, il testo dell'obiettivo
    viene arricchito con le risposte (context.py::augment_goal_text, stessa
    sintassi a campo etichettato usata in estrazione — nessun valore fisso,
    funziona per qualunque nome/campo) PRIMA di ripetere l'intero triage:
    non è un ramo speciale, è la stessa funzione richiamata su un testo più
    completo, con lo stesso session_id per continuare la stessa sessione."""
    store = get_session_store()
    audit_log = get_audit_log()

    # Il Fact Ledger e' la memoria aziendale autorevole: arricchisce il testo
    # prima di qualunque triage, evitando di chiedere nuovamente dati gia'
    # dichiarati durante registrazione/onboarding. Il testo originale resta
    # intatto e i fatti vengono aggiunti con etichette comprese da context.py.
    if db is not None:
        try:
            facts = await current_facts_map(db, org_id)
        except (AttributeError, TypeError):
            facts = {}  # fake DB minimali dei test legacy
        labels = {
            "ragione_sociale": "Azienda/brand",
            "nome_commerciale": "Azienda/brand",
            "prodotto": "Prodotto/servizio",
            "servizio": "Prodotto/servizio",
            "settore": "Settore",
            "sito_web": "Sito web",
            "obiettivi_commerciali": "Obiettivo aziendale",
        }
        additions = []
        already = goal_text.lower()
        for field, label in labels.items():
            fact = facts.get(field)
            value = str((fact or {}).get("value") or "").strip()
            if value and value.lower() not in already:
                additions.append(f"{label}: {value}.")
        if additions:
            goal_text = f"{goal_text.strip()} {' '.join(additions)}".strip()

    is_reexamination = bool(clarification and clarification.get("answers"))
    if is_reexamination:
        goal_text = augment_goal_text(
            goal_text,
            clarification.get("missing_information") or [],
            clarification.get("answers") or [],
        )

    prep = prepare_brain_session(goal_text, session_id=session_id, is_reexamination=is_reexamination)
    sid = prep["session_id"]
    selection: SelectionResult = prep["selection"]
    audit_event_ids: list[str] = list(prep["audit_event_ids"])

    if selection.status != STATUS_READY:
        # Nessun goal, nessun piano, nessuna azione M2: solo l'esito di
        # triage/selezione (NEEDS_CLARIFICATION / UNSUPPORTED / BLOCKED_RISK),
        # già interamente descritto (e già tracciato in memoria/audit) da
        # prepare_brain_session().
        payload = _esito_non_pronto(selection)
        payload.update({
            "session_id": sid, "audit_event_ids": audit_event_ids,
            "session_state": prep["session_state"],
        })
        return payload

    def _log(event_type: str, *, actor: str, decision: str, reason: str, metadata: Optional[dict] = None,
              goal_id: Optional[str] = None, plan_id: Optional[str] = None) -> None:
        ev = audit_log.record(
            event_type=event_type, session_id=sid, goal_id=goal_id, plan_id=plan_id,
            actor=actor, decision=decision, reason=reason, metadata=metadata or {},
        )
        audit_event_ids.append(ev["event_id"])

    triage = triage_goal(goal_text)
    if triage.requires_clarification:
        # Doppia rete di sicurezza: select_agents() ha dato READY, ma il
        # triage esistente (M2 planner + contesto) rileva comunque
        # un'ambiguità non intercettata dal selettore -> si resta prudenti,
        # nessun goal/piano creato.
        _log(EVENT_CLARIFICATION_REQUIRED, actor=_ACTOR_SERVICE, decision="NEEDS_CLARIFICATION",
             reason="Ambiguità rilevata dal triage M2 dopo una selezione agenti READY.",
             metadata={"objective_type": triage.objective_type})
        store.update_session(sid, status="NEEDS_CLARIFICATION")
        payload = _selection_payload(selection)
        payload.update({
            "plan": None, "tasks": [], "requires_clarification": True,
            "status": "NEEDS_CLARIFICATION", "objective_type": triage.objective_type,
            "questions": triage.questions, "clarifying_questions": triage.questions,
            "goal_context": triage.context,
            "session_id": sid, "audit_event_ids": audit_event_ids,
            "session_state": store.get_session(sid),
        })
        return payload

    goal_id = new_id("goal")
    await db.goals.insert_one({
        **base_record(org_id, user_id), "id": goal_id, "text": goal_text,
        "status": "IN_APPROVAZIONE", "mode": "SIMULAZIONE",
    })
    store.update_session(sid, goal_id=goal_id)

    task_specs = _brain_task_specs(selection.detected_intents)
    res = await m2_engine.create_plan(db, org_id, user_id, goal_id, goal_text, task_specs=task_specs)
    if res.get("requires_clarification") or not res.get("plan"):
        _log(EVENT_CLARIFICATION_REQUIRED, actor=_ACTOR_SERVICE, decision="NEEDS_CLARIFICATION",
             reason="Il planner M2 non ha potuto costruire un piano dal testo dell'obiettivo.",
             goal_id=goal_id, metadata={"objective_type": res.get("objective_type")})
        store.update_session(sid, status="NEEDS_CLARIFICATION")
        payload = _selection_payload(selection)
        payload.update({
            "plan": None, "tasks": [], "requires_clarification": True,
            "status": "NEEDS_CLARIFICATION", "objective_type": res.get("objective_type"),
            "questions": triage.questions, "clarifying_questions": triage.questions,
            "goal_context": triage.context,
            "session_id": sid, "audit_event_ids": audit_event_ids,
            "session_state": store.get_session(sid),
        })
        return payload

    plan = res["plan"]
    store.update_session(sid, plan_id=plan["id"])
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
            _log(EVENT_ERROR_FALLBACK, actor=_ACTOR_SERVICE, decision="FALLBACK_M2_DEFAULT",
                 reason="Override brain scartato da guard/validatore: M2 userà il produttore generico.",
                 goal_id=goal_id, plan_id=plan["id"],
                 metadata={"task_id": task["id"], "deliverable_type": dtype, "motivi": motivi})
            continue
        await db.tasks.update_one({"id": task["id"]}, {"$set": {"inputs.deliverable_override": contenuto}})
        overrides[task["id"]] = dtype

    # Handoff (Blocco C): a questo punto nessun task e' ancora stato eseguito
    # (tutti "IN_ATTESA_APPROVAZIONE"), quindi nessun deliverable esiste
    # ancora in db.deliverables -> gli handoff tra task dipendenti risultano
    # sempre WAITING_DEPENDENCY. Calcolati comunque (SOLO se esistono
    # dipendenze dichiarate nel DAG) cosi' la sessione riflette da subito la
    # topologia delle dipendenze, pronta per essere ricalcolata quando i
    # task verranno eseguiti (Blocco C.1).
    tasks_by_id = {t["id"]: t for t in tasks}
    handoff_dicts: list[dict] = []
    for task in tasks:
        if not task.get("depends_on"):
            continue
        for h in collect_task_handoffs(
            plan=plan, target_task=task, tasks_by_id=tasks_by_id, deliverables_by_task_id={},
        ):
            handoff_dicts.append(h.to_dict())
    for h in handoff_dicts:
        store.append_to_session(sid, "handoffs", h)
        h_event = (
            EVENT_HANDOFF_READY if h["status"] == HANDOFF_READY
            else EVENT_HANDOFF_REJECTED if h["status"] in ("REJECTED_INVALID", "BLOCKED_INTEGRITY")
            else EVENT_HANDOFF_WAITING
        )
        _log(h_event, actor=_ACTOR_SERVICE, decision=h["status"],
             reason=f"Handoff {h['source_task_id']} -> {h['target_task_id']}: {h['status']}.",
             goal_id=goal_id, plan_id=plan["id"],
             metadata={"handoff_id": h["handoff_id"], "source_task_id": h["source_task_id"],
                       "target_task_id": h["target_task_id"]})
    handoff_status = None
    if handoff_dicts:
        handoff_status = "READY" if all(h["status"] == HANDOFF_READY for h in handoff_dicts) else "WAITING_DEPENDENCY"

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
            "plan_generation": PLAN_GENERATION_TAG,
        }},
    )

    plan["goal_context"] = ctx.come_dict()
    plan["brain"] = brain_trace
    plan["active_agent_ids"] = selection.activeAgentIds
    plan["plan_generation"] = PLAN_GENERATION_TAG

    # Capability REALE 'video_reel' (agents/agent_map.py): UN SOLO piano, mai
    # un secondo percorso. M2 resta dichiaratamente solo-simulazione (mai
    # generatore di contenuto reale), quindi questo task NON passa da
    # m2.planner.decompose(): e' aggiunto qui come task aggiuntivo dello
    # STESSO piano, con un deliverable_override che punta a un progetto reale
    # gia' creato/grounded sul Fact Ledger da domains/reel.py (nessun secondo
    # motore di generazione, nessuna euristica di contesto duplicata). Il
    # contenuto vero (sceneggiatura, storyboard, video) si genera e si
    # approva nel laboratorio Reel (vedi skills.py: reel_text_requesty /
    # reel_video_runway); qui il task M2 e' solo un riferimento tracciabile,
    # approvabile e visibile come qualunque altro task del piano.
    reel_project = None
    if "video_reel" in selection.detected_intents:
        pseudo_user = {"id": user_id, "email": None, "organization_id": org_id}
        try:
            reel_project = await reel_domain.create_project(reel_domain.NewReelBody(brief=goal_text), pseudo_user)
        except HTTPException as exc:
            _log(EVENT_ERROR_FALLBACK, actor=_ACTOR_SERVICE, decision="FALLBACK_M2_DEFAULT",
                 reason=f"Task 'video_reel' non aggiunto al piano: {exc.detail}",
                 goal_id=goal_id, plan_id=plan["id"], metadata={"detail": exc.detail})
        else:
            reel_mapping = mapping_by_capability("video_reel")
            ultimo = await db.tasks.find({"plan_id": plan["id"]}).sort("seq", -1).to_list(1)
            seq = (ultimo[0]["seq"] + 1) if ultimo else 1
            reel_task = new_task(
                org_id, user_id, plan["id"], goal_id, plan["version"], seq,
                name="Reel — testo e video", agent_id=reel_mapping.frontend_agent_id if reel_mapping else "video-creator",
                deliverable_type="video_reel_project",
                inputs={"cost": 0.0, "deliverable_override": {
                    "reel_project_id": reel_project["id"], "mode": "REALE",
                    "note": "Genera e approva il contenuto in Reel — laboratorio.",
                }},
                depends_on=[],
            )
            await db.tasks.insert_one(reel_task)
            await db.plans.update_one({"id": plan["id"]}, {"$push": {
                "dag.nodes": reel_task["id"], "topo_order": reel_task["id"],
            }})
            _log(EVENT_PLAN_ALLOWED, actor=_ACTOR_SERVICE, decision="VIDEO_REEL_TASK_LINKED",
                 reason="Task 'video_reel_project' aggiunto al piano M2, collegato al progetto reale in domains/reel.py.",
                 goal_id=goal_id, plan_id=plan["id"],
                 metadata={"task_id": reel_task["id"], "reel_project_id": reel_project["id"]})

    # Stesso pattern, capability REALE 'flyer_image' (Creative/Graphic
    # Designer): seconda prova della stessa architettura multimodale, mai un
    # secondo motore. Vedi domains/flyer.py.
    flyer_project = None
    if "flyer_image" in selection.detected_intents:
        pseudo_user = {"id": user_id, "email": None, "organization_id": org_id}
        try:
            flyer_project = await flyer_domain.create_project(flyer_domain.NewFlyerBody(brief=goal_text), pseudo_user)
        except HTTPException as exc:
            _log(EVENT_ERROR_FALLBACK, actor=_ACTOR_SERVICE, decision="FALLBACK_M2_DEFAULT",
                 reason=f"Task 'flyer_image' non aggiunto al piano: {exc.detail}",
                 goal_id=goal_id, plan_id=plan["id"], metadata={"detail": exc.detail})
        else:
            flyer_mapping = mapping_by_capability("flyer_image")
            ultimo = await db.tasks.find({"plan_id": plan["id"]}).sort("seq", -1).to_list(1)
            seq = (ultimo[0]["seq"] + 1) if ultimo else 1
            flyer_task = new_task(
                org_id, user_id, plan["id"], goal_id, plan["version"], seq,
                name="Flyer — copy e immagine", agent_id=flyer_mapping.frontend_agent_id if flyer_mapping else "creative-designer",
                deliverable_type="flyer_project",
                inputs={"cost": 0.0, "deliverable_override": {
                    "flyer_project_id": flyer_project["id"], "mode": "REALE",
                    "note": "Genera e approva il contenuto in Flyer — laboratorio.",
                }},
                depends_on=[],
            )
            await db.tasks.insert_one(flyer_task)
            await db.plans.update_one({"id": plan["id"]}, {"$push": {
                "dag.nodes": flyer_task["id"], "topo_order": flyer_task["id"],
            }})
            _log(EVENT_PLAN_ALLOWED, actor=_ACTOR_SERVICE, decision="FLYER_TASK_LINKED",
                 reason="Task 'flyer_project' aggiunto al piano M2, collegato al progetto reale in domains/flyer.py.",
                 goal_id=goal_id, plan_id=plan["id"],
                 metadata={"task_id": flyer_task["id"], "flyer_project_id": flyer_project["id"]})

    tasks = await db.tasks.find({"plan_id": plan["id"]}, {"_id": 0}).sort("seq", 1).to_list(200)

    for task_id, dtype in overrides.items():
        store.append_to_session(sid, "deliverable_refs", {
            "task_id": task_id, "deliverable_type": dtype, "source": "brain_override",
        })

    # Correzione C.0: la creazione del piano NON è un risultato pronto per
    # l'approvazione — nessun task è ancora stato eseguito, nessun
    # deliverable è completo, gli handoff restano WAITING_DEPENDENCY.
    # PLAN_ALLOWED è già stato registrato da prepare_brain_session() al gate
    # READY; qui si registra solo il passaggio di stato della sessione.
    # RESULT_READY_FOR_APPROVAL può essere registrato SOLO in seguito, da
    # mark_result_ready_for_approval(), e solo se tutte le condizioni sono
    # verificate (Blocco C.1 fornirà lo stato reale post-esecuzione).
    store.update_session(sid, status="PLAN_CREATED")

    payload = _selection_payload(selection)
    payload.update({
        "plan": plan, "tasks": tasks, "requires_clarification": False,
        "brain_trace": brain_trace, "reel_project": reel_project, "flyer_project": flyer_project,
        "session_id": sid, "audit_event_ids": audit_event_ids,
        "session_state": store.get_session(sid),
    })
    if handoff_status is not None:
        payload["handoff_status"] = handoff_status
    return payload


def mark_result_ready_for_approval(
    *,
    session_id: str,
    plan_id: str,
    tasks: list,
    handoffs: list,
    deliverables_by_task_id: Optional[dict] = None,
    blocking_errors: Optional[list] = None,
    requires_approval: bool = True,
) -> dict:
    """Correzione C.0 — funzione PURA (nessun db, nessuna esecuzione di
    task): l'UNICO punto autorizzato a registrare RESULT_READY_FOR_APPROVAL.
    Riceve lo stato già calcolato altrove (tasks/handoff/deliverable —
    prodotto dall'esecuzione reale nel futuro Blocco C.1, o da un chiamante
    di test in questo blocco) e verifica ESPLICITAMENTE che il risultato
    sia realmente pronto:
    - tutti i task passati sono COMPLETATA (nessuno FALLITA/BLOCCATA/SALTATA);
    - se richiesta, ogni task è approvato;
    - tutti gli handoff passati sono READY;
    - ogni task ha un deliverable presente, valido e non BLOCCATO;
    - nessun errore bloccante esterno segnalato dal chiamante.

    Se manca anche una sola condizione: NON registra alcun evento, NON
    tocca lo stato della sessione, e ritorna 'ready': False con l'elenco
    esplicito delle condizioni mancanti. Idempotente: una chiamata
    ripetuta con lo stesso (session_id, plan_id) già marcato pronto non
    genera un secondo evento — ritorna l'event_id già registrato."""
    store = get_session_store()
    audit_log = get_audit_log()
    deliverables_by_task_id = deliverables_by_task_id or {}
    blocking_errors = list(blocking_errors or [])

    missing: list[str] = []

    if not tasks:
        missing.append("nessun task fornito: non esiste un risultato da marcare pronto")

    incompleti = [t["id"] for t in tasks if t.get("task_status") != "COMPLETATA"]
    if incompleti:
        missing.append(f"task non completati: {incompleti}")

    in_errore = [t["id"] for t in tasks if t.get("task_status") in ("FALLITA", "BLOCCATA", "SALTATA")]
    if in_errore:
        missing.append(f"task in stato di errore/blocco: {in_errore}")

    if requires_approval:
        non_approvati = [t["id"] for t in tasks if not t.get("approved")]
        if non_approvati:
            missing.append(f"task senza approvazione richiesta: {non_approvati}")

    handoff_non_pronti = [h.get("handoff_id", "?") for h in handoffs if h.get("status") != HANDOFF_READY]
    if handoff_non_pronti:
        missing.append(f"handoff non pronti (non READY): {handoff_non_pronti}")

    for t in tasks:
        d = deliverables_by_task_id.get(t["id"])
        if d is None or not d.get("valid") or d.get("status") not in ("COMPLETATO", "COMPLETATO_CON_AVVISI"):
            missing.append(f"deliverable mancante o non valido per il task '{t['id']}'")

    if blocking_errors:
        missing.append(f"errori bloccanti presenti: {blocking_errors}")

    esistenti = audit_log.filter(session_id=session_id, plan_id=plan_id,
                                  event_type=EVENT_RESULT_READY_FOR_APPROVAL)

    if missing:
        return {
            "ready": False, "session_id": session_id, "plan_id": plan_id,
            "missing_conditions": missing, "event_id": None, "already_marked": bool(esistenti),
        }

    if esistenti:
        # Idempotente: già marcato pronto in precedenza, nessun nuovo evento.
        return {
            "ready": True, "session_id": session_id, "plan_id": plan_id,
            "missing_conditions": [], "event_id": esistenti[0]["event_id"], "already_marked": True,
        }

    ev = audit_log.record(
        event_type=EVENT_RESULT_READY_FOR_APPROVAL, session_id=session_id, plan_id=plan_id,
        actor=_ACTOR_SERVICE, decision="READY_FOR_APPROVAL",
        reason="Tutti i task completati e approvati, handoff pronti, deliverable validi: "
               "risultato realmente pronto per l'approvazione.",
        metadata={"tasks": len(tasks), "handoffs": len(handoffs)},
    )
    if store.get_session(session_id) is not None:
        store.update_session(session_id, status="RESULT_READY_FOR_APPROVAL")
    return {
        "ready": True, "session_id": session_id, "plan_id": plan_id,
        "missing_conditions": [], "event_id": ev["event_id"], "already_marked": False,
    }


def inspect_session(session_id: str) -> dict:
    """Blocco C — funzione PURA di sola lettura, pensata per la prova
    integrata del Blocco C.1: nessun accesso a MongoDB, nessuna chiamata
    esterna, nessun avvio di server. Legge esclusivamente lo stato già
    presente nella memoria di sessione e nel registro audit in-process."""
    store = get_session_store()
    audit_log = get_audit_log()

    sess = store.get_session(session_id)
    if sess is None:
        return {
            "session_id": session_id, "found": False, "session": None,
            "activeAgentIds": [], "plan_id": None, "handoffs": [],
            "audit_events": [], "pending_approval": False,
        }

    events = audit_log.filter(session_id=session_id)
    pending_approval = any(e["event_type"] == EVENT_RESULT_READY_FOR_APPROVAL for e in events)
    return {
        "session_id": session_id,
        "found": True,
        "session": sess,
        "activeAgentIds": sess.get("activeAgentIds", []),
        "plan_id": sess.get("plan_id"),
        "handoffs": sess.get("handoffs", []),
        "audit_events": events,
        "pending_approval": pending_approval,
    }
