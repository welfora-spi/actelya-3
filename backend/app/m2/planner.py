"""Milestone 2 — Planner: classificazione deterministica dell'obiettivo,
scomposizione in attività, costruzione DAG e ordinamento topologico.
Funzioni PURE (nessuna scrittura DB, nessuna chiamata reale): risultato deterministico
a parità di input. La persistenza avviene nel Blocco 4."""
from ..domains.intent import classify_intent

# Mappatura deterministica keyword -> objective_type (ordine di priorità FISSO).
# La prima regola che matcha vince. Nessuna casualità, nessun timestamp.
_OBJECTIVE_RULES = [
    ("REPORT", ["report", "kpi", "analisi delle performance", "analisi performance", "risultati"]),
    ("LEAD_GEN", ["lead generation", "lead gen", "lead", "prospect", "sdr", "outreach", "acquisizione clienti"]),
    ("CAMPAGNA", ["campagna", "lancio", "advertising", " adv", "ads", "sponsorizza", "inserzion"]),
    ("CONTENUTO", ["piano editoriale", "calendario editoriale", "editoriale", "post", "social", "contenut"]),
    ("STRATEGIA", ["strategia", "posizionamento", "go-to-market", "gtm", "piano marketing"]),
    ("EMAIL", ["email", "e-mail", "mail"]),
]

# Agente responsabile per ciascun tipo di deliverable.
DELIVERABLE_AGENT = {
    "marketing_strategy": "marketing_strategist",
    "editorial_plan": "content_social",
    "social_content": "content_social",
    "ad_campaign_draft": "advertising",
    "lead_gen_plan": "lead_gen_sdr",
    "kpi_report": "analytics_performance",
    "email": "content_social",
}


def classify_objective(goal_text: str) -> dict:
    """Classificazione IBRIDA e DETERMINISTICA.
    - intent (PRODUZIONE/AZIONE_ESTERNA/MISTO/AMBIGUO) dalle regole M1 (precedenza assoluta
      alle regole di sicurezza: invio/pubblicazione/contatto/spesa/dati/consenso).
    - objective_type dalle regole keyword deterministiche.
    - Nessuna azione esterna viene creata automaticamente: external_action_auto = False.
    - Obiettivo ambiguo => AMBIGUO con requires_clarification=True."""
    text = (goal_text or "").lower().strip()
    intent = classify_intent(goal_text)  # regole deterministiche M1 + sicurezza prioritaria

    objective_type = None
    for otype, kws in _OBJECTIVE_RULES:
        if any(kw in text for kw in kws):
            objective_type = otype
            break

    requires_clarification = False
    if objective_type is None or intent["intent_type"] == "AMBIGUO":
        # Ambiguità: non dedurre azioni esterne, chiedere chiarimento.
        if objective_type is None:
            objective_type = "AMBIGUO"
        requires_clarification = True

    return {
        "objective_type": objective_type,
        "intent": intent,                       # include intent_type, risk_flags, applied_rules
        "requires_clarification": requires_clarification,
        "external_action_auto": False,          # il planner NON crea mai azioni esterne
        "deterministic": True,
        "mode": "SIMULAZIONE",
    }


def decompose(objective_type: str) -> list[dict]:
    """Scompone l'obiettivo in attività (TaskSpec) con dipendenze per chiave locale.
    TaskSpec: {key, name, agent_id, deliverable_type, depends_on:[key...]}"""
    def t(key, dtype, deps=None, name=None):
        return {
            "key": key, "name": name or dtype, "deliverable_type": dtype,
            "agent_id": DELIVERABLE_AGENT[dtype], "depends_on": deps or [],
        }

    if objective_type == "STRATEGIA":
        return [t("t1", "marketing_strategy")]
    if objective_type == "CONTENUTO":
        return [t("t1", "editorial_plan"), t("t2", "social_content", ["t1"])]
    if objective_type == "CAMPAGNA":
        return [
            t("t1", "marketing_strategy"),
            t("t2", "editorial_plan", ["t1"]),
            t("t3", "social_content", ["t2"]),
            t("t4", "ad_campaign_draft", ["t1"]),
            t("t5", "kpi_report", ["t3", "t4"]),
        ]
    if objective_type == "LEAD_GEN":
        return [t("t1", "marketing_strategy"), t("t2", "lead_gen_plan", ["t1"])]
    if objective_type == "REPORT":
        return [t("t1", "kpi_report")]
    if objective_type == "EMAIL":
        # Compatibilità M1: piano a UNA sola attività.
        return [t("t1", "email")]
    # AMBIGUO: nessuna attività, richiede chiarimento.
    return []


def build_dag(specs: list[dict]) -> dict:
    keys = [s["key"] for s in specs]
    edges = []
    for s in specs:
        for d in s["depends_on"]:
            edges.append([d, s["key"]])  # dipendenza -> attività
    return {"nodes": keys, "edges": edges}


def validate_dag(specs: list[dict]) -> dict:
    """Verifica: nessun task orfano (dipendenza inesistente) e assenza di cicli."""
    errors = []
    keys = {s["key"] for s in specs}
    for s in specs:
        for d in s["depends_on"]:
            if d not in keys:
                errors.append(f"Dipendenza orfana: {s['key']} -> {d} (inesistente)")
    try:
        topological_order(specs)
    except ValueError as e:
        errors.append(str(e))
    return {"ok": len(errors) == 0, "errors": errors}


def topological_order(specs: list[dict]) -> list[str]:
    """Ordinamento topologico (Kahn) DETERMINISTICO. Solleva ValueError se ciclico."""
    keys = [s["key"] for s in specs]
    deps = {s["key"]: set(s["depends_on"]) for s in specs}
    indeg = {k: len(deps[k]) for k in keys}
    # Coda stabile nell'ordine di dichiarazione (determinismo).
    ready = [k for k in keys if indeg[k] == 0]
    order = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for k in keys:  # ordine stabile
            if n in deps[k]:
                deps[k].discard(n)
                indeg[k] -= 1
                if indeg[k] == 0:
                    ready.append(k)
    if len(order) != len(keys):
        raise ValueError("Ciclo rilevato nel DAG del piano (aciclicità violata)")
    return order


def plan_skeleton(goal_text: str) -> dict:
    """Scheletro del piano (senza persistenza) usato dal Blocco 4 per creare plan/tasks."""
    cls = classify_objective(goal_text)
    specs = decompose(cls["objective_type"])
    dag = build_dag(specs)
    validation = validate_dag(specs)
    topo = topological_order(specs) if validation["ok"] else []
    return {
        "objective_type": cls["objective_type"],
        "intent": cls["intent"],
        "requires_clarification": cls["requires_clarification"],
        "external_action_auto": cls["external_action_auto"],
        "tasks": specs,
        "dag": dag,
        "topo_order": topo,
        "valid": validation["ok"],
        "validation_errors": validation["errors"],
        "mode": "SIMULAZIONE",
    }
