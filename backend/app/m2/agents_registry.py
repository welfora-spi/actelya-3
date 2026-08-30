"""Blocco 3 — Registro e contratti degli agenti (SIMULAZIONE).
Contratti versionati, validati allo startup. Mapping capability->agente senza duplicazioni
né fallback silenziosi. Selezione dinamica deterministica ed esplicabile.
Nessun agente può pubblicare/inviare/contattare persone reali in M2."""
from .planner import DELIVERABLE_AGENT

REGISTRY_VERSION = "m2-1.0.0"

# Azioni vietate a TUTTI gli agenti in M2 (nessuna azione esterna reale).
GLOBAL_FORBIDDEN = ["invio_reale", "pubblicazione_reale", "contatto_persone_reali", "spesa_reale"]


def _c(agent_id, mission, capabilities, allowed_deliverables, *, operative,
       input_schema, output_schema, allowed_actions, forbidden_actions,
       success, block, handoff, missing_data, token_limit, budget, timeout, role="producer"):
    return {
        "id": agent_id,
        "contract_version": REGISTRY_VERSION,
        "mission": mission,
        "role": role,                          # producer | reviewer
        "operative": operative,                # False => PREDISPOSTO (mai selezionato)
        "capabilities": capabilities,
        "allowed_deliverables": allowed_deliverables,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "allowed_actions": allowed_actions,
        "forbidden_actions": sorted(set(GLOBAL_FORBIDDEN + forbidden_actions)),
        "success_criteria": success,
        "block_criteria": block,
        "handoff_criteria": handoff,
        "missing_data_criteria": missing_data,
        "token_limit": token_limit,
        "budget": budget,
        "timeout": timeout,
    }


AGENT_CONTRACTS = {
    "marketing_strategist": _c(
        "marketing_strategist", "Definire strategia e posizionamento.",
        ["strategy"], ["marketing_strategy"], operative=True,
        input_schema={"goal": "str", "org_profile": "dict"},
        output_schema={"deliverable_type": "marketing_strategy"},
        allowed_actions=["produzione_bozza"], forbidden_actions=[],
        success=["Strategia con segmenti, value prop e messaggi chiave"],
        block=["Obiettivo vuoto o profilo assente"],
        handoff=["Passa a Content & Social"], missing_data=["org_profile mancante"],
        token_limit=1500, budget=0.03, timeout=60),
    "content_social": _c(
        "content_social", "Produrre piano editoriale, contenuti social ed email (bozza).",
        ["editorial", "social", "email"], ["editorial_plan", "social_content", "email"], operative=True,
        input_schema={"strategy": "dict", "org_profile": "dict"},
        output_schema={"deliverable_type": "editorial_plan|social_content|email"},
        allowed_actions=["produzione_bozza"], forbidden_actions=["invio_reale"],
        success=["Campi obbligatori non vuoti"], block=["Campi vuoti o soli placeholder"],
        handoff=["Passa a Compliance Reviewer"], missing_data=["strategy mancante"],
        token_limit=1600, budget=0.03, timeout=60),
    "advertising": _c(
        "advertising", "Preparare campagne pubblicitarie in BOZZA (mai pubblicate).",
        ["ads"], ["ad_campaign_draft"], operative=True,
        input_schema={"strategy": "dict"},
        output_schema={"deliverable_type": "ad_campaign_draft", "status": "DRAFT"},
        allowed_actions=["produzione_bozza"], forbidden_actions=["pubblicazione_reale"],
        success=["Bozza campagna con audience e varianti, status=DRAFT"],
        block=["status != DRAFT", "nessuna variante"],
        handoff=["Passa ad Analytics"], missing_data=["strategy mancante"],
        token_limit=1400, budget=0.03, timeout=60),
    "lead_gen_sdr": _c(
        "lead_gen_sdr", "Produrre strategia, criteri e piano di lead generation (nessun contatto).",
        ["leadgen"], ["lead_gen_plan"], operative=True,
        input_schema={"strategy": "dict"},
        output_schema={"deliverable_type": "lead_gen_plan"},
        allowed_actions=["produzione_bozza"], forbidden_actions=["contatto_persone_reali", "invio_reale"],
        success=["ICP, criteri e sequenze con placeholder, nessuna PII"],
        block=["Presenza di PII/persone reali", "criteri insufficienti"],
        handoff=["Passa ad Analytics"], missing_data=["strategy mancante"],
        token_limit=1500, budget=0.03, timeout=60),
    "analytics_performance": _c(
        "analytics_performance", "Produrre report KPI (dati simulati o non disponibili, mai inventati).",
        ["analytics"], ["kpi_report"], operative=True,
        input_schema={"context": "dict"},
        output_schema={"deliverable_type": "kpi_report"},
        allowed_actions=["produzione_bozza"], forbidden_actions=[],
        success=["Metriche con target e stato dato (SIMULATO/NON_DISPONIBILE)"],
        block=["current inventato come reale"],
        handoff=["Ritorna all'orchestratore"], missing_data=["metriche non definite"],
        token_limit=1200, budget=0.02, timeout=60),
    # ---- Revisori NON distruttivi ----
    "compliance_reviewer": _c(
        "compliance_reviewer", "Revisione compliance non distruttiva: produce record di revisione.",
        ["review_compliance"], [], operative=True, role="reviewer",
        input_schema={"deliverable": "dict"}, output_schema={"review": "dict"},
        allowed_actions=["revisione"], forbidden_actions=["modifica_deliverable", "cancellazione_deliverable"],
        success=["Record di revisione persistito"], block=[],
        handoff=["Ritorna all'orchestratore"], missing_data=["deliverable assente"],
        token_limit=800, budget=0.01, timeout=60),
    "auditor": _c(
        "auditor", "Audit indipendente non distruttivo: produce record di revisione.",
        ["review_audit"], [], operative=True, role="reviewer",
        input_schema={"deliverable": "dict", "audit": "dict"}, output_schema={"review": "dict"},
        allowed_actions=["revisione"], forbidden_actions=["modifica_deliverable", "cancellazione_deliverable"],
        success=["Record di audit persistito"], block=[],
        handoff=["Ritorna all'orchestratore"], missing_data=[],
        token_limit=800, budget=0.01, timeout=60),
    "tech_lead": _c(
        "tech_lead", "Supervisione tecnica e handoff, non distruttivo.",
        ["review_tech"], [], operative=True, role="reviewer",
        input_schema={"plan": "dict"}, output_schema={"review": "dict"},
        allowed_actions=["revisione"], forbidden_actions=["modifica_deliverable"],
        success=["Handoff coerente"], block=[], handoff=["Coordina agenti"], missing_data=[],
        token_limit=800, budget=0.01, timeout=60),
    # ---- PREDISPOSTI (mai selezionati come operativi in M2) ----
    "appointment_setter": _c(
        "appointment_setter", "PREDISPOSTO: fissare appuntamenti (non operativo in M2).",
        ["appointments"], [], operative=False,
        input_schema={}, output_schema={}, allowed_actions=[], forbidden_actions=["invio_reale", "contatto_persone_reali"],
        success=[], block=["Non operativo in M2"], handoff=[], missing_data=[],
        token_limit=1000, budget=0.02, timeout=60),
    "nurturing": _c(
        "nurturing", "PREDISPOSTO: sequenze di nurturing (non operativo in M2).",
        ["nurturing"], [], operative=False,
        input_schema={}, output_schema={}, allowed_actions=[], forbidden_actions=["invio_reale"],
        success=[], block=["Non operativo in M2"], handoff=[], missing_data=[],
        token_limit=1000, budget=0.02, timeout=60),
}


class ContractError(Exception):
    """Errore esplicito: contratto invalido, capability assente, duplicazione, azione vietata."""


def validate_registry(registry: dict = None) -> dict:
    """Valida i contratti allo startup. Solleva ContractError su problemi bloccanti.
    Ritorna il mapping capability->agente (solo agenti operativi, senza duplicazioni)."""
    reg = registry if registry is not None else AGENT_CONTRACTS
    required = ["id", "contract_version", "mission", "capabilities", "allowed_deliverables",
                "input_schema", "output_schema", "allowed_actions", "forbidden_actions",
                "success_criteria", "block_criteria", "handoff_criteria", "missing_data_criteria",
                "token_limit", "budget", "timeout", "operative", "role"]
    seen_ids = set()
    cap_map = {}
    for key, c in reg.items():
        # id univoco e stabile
        if c.get("id") != key:
            raise ContractError(f"Chiave registro '{key}' diversa da id '{c.get('id')}'")
        if c["id"] in seen_ids:
            raise ContractError(f"Identificativo agente duplicato: {c['id']}")
        seen_ids.add(c["id"])
        # campi obbligatori
        for f in required:
            if f not in c:
                raise ContractError(f"Contratto '{key}' privo del campo obbligatorio '{f}'")
        # limiti validi
        if c["token_limit"] <= 0 or c["budget"] < 0 or c["timeout"] <= 0:
            raise ContractError(f"Contratto '{key}': limiti token/budget/timeout non validi")
        # producer deve avere deliverable autorizzati; reviewer no
        if c["role"] == "producer" and c["operative"] and not c["allowed_deliverables"]:
            raise ContractError(f"Agente producer operativo '{key}' senza deliverable autorizzati")
        # capability->agente senza duplicazioni (solo operativi entrano nel mapping)
        if c["operative"]:
            for cap in c["capabilities"]:
                if cap in cap_map:
                    raise ContractError(f"Capability duplicata '{cap}' tra '{cap_map[cap]}' e '{c['id']}'")
                cap_map[cap] = c["id"]
    return cap_map


# Mapping deliverable_type -> capability necessaria (deterministico, esplicito).
DELIVERABLE_CAPABILITY = {
    "marketing_strategy": "strategy",
    "editorial_plan": "editorial",
    "social_content": "social",
    "ad_campaign_draft": "ads",
    "lead_gen_plan": "leadgen",
    "kpi_report": "analytics",
    "email": "email",
}


def select_agent(deliverable_type: str, registry: dict = None) -> dict:
    """Selezione dinamica DETERMINISTICA ed esplicabile.
    Errore esplicito se manca un agente compatibile (nessun fallback silenzioso)."""
    reg = registry if registry is not None else AGENT_CONTRACTS
    cap = DELIVERABLE_CAPABILITY.get(deliverable_type)
    if cap is None:
        raise ContractError(f"Nessuna capability mappata per deliverable '{deliverable_type}'")
    cap_map = validate_registry(reg)  # garantisce assenza di duplicazioni
    agent_id = cap_map.get(cap)
    if not agent_id:
        raise ContractError(f"Nessun agente OPERATIVO compatibile per capability '{cap}' (deliverable '{deliverable_type}')")
    agent = reg[agent_id]
    # difesa: l'agente deve dichiarare il deliverable e non essere un revisore
    if deliverable_type not in agent["allowed_deliverables"]:
        raise ContractError(f"Agente '{agent_id}' non autorizzato al deliverable '{deliverable_type}'")
    return {
        "agent_id": agent_id,
        "capability": cap,
        "reason": f"deliverable '{deliverable_type}' -> capability '{cap}' -> agente operativo '{agent_id}'",
        "contract_version": agent["contract_version"],
    }


def assert_action_allowed(agent_id: str, action: str, registry: dict = None):
    """Blocco sicuro: solleva ContractError se l'azione è vietata o non consentita."""
    reg = registry if registry is not None else AGENT_CONTRACTS
    c = reg.get(agent_id)
    if not c:
        raise ContractError(f"Agente inesistente: {agent_id}")
    if action in c["forbidden_actions"]:
        raise ContractError(f"Azione VIETATA '{action}' per agente '{agent_id}' — blocco sicuro")
    if action not in c["allowed_actions"]:
        raise ContractError(f"Azione '{action}' non consentita per agente '{agent_id}' — blocco sicuro")
    return True
