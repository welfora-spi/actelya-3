"""Brain — mappatura ufficiale degli agenti (Blocco B, corretta in B.1).

Unica fonte di verità che collega:
- capability M2 (m2/agents_registry.py::DELIVERABLE_CAPABILITY);
- agent_id M2 (m2/agents_registry.py::AGENT_CONTRACTS) — NON duplicato,
  solo referenziato per nome/stringa;
- agent_id frontend (frontend/src/components/meeting-room/agentRegistry.js)
  — letto e verificato manualmente (il backend non importa codice
  frontend): gli agent_id qui sotto DEVONO coincidere esattamente con
  quelli in AGENT_REGISTRY lato frontend;
- prontezza di esecuzione reale (execution_ready/execution_mode): una
  capability può essere selezionabile concettualmente ma NON ancora
  eseguibile da M2 — il brain non deve mai dichiarare eseguibile un piano
  che M2 non può davvero trasformare in task/deliverable.

execution_mode:
- "M2": la capability ha un agente M2 operativo (agents_registry.py,
  operative=True) E un producer deterministico che genera quel
  deliverable_type (m2/deliverables.py + brain/producers.py) — eseguibile
  oggi, per davvero.
- "BRAIN_SIMULATION": nessun agente M2 operativo, ma esiste un producer
  deterministico nel brain in grado di simulare un risultato coerente
  senza toccare M2 — NESSUNA capability è oggi in questo stato (verificato
  sul codice reale: né m2/deliverables.py né brain/producers.py hanno un
  producer per 'appointments'/'nurturing') — il valore resta previsto per
  quando un producer del genere esisterà.
- "UNAVAILABLE": nessun agente M2 operativo E nessun producer di
  simulazione: la capability non può produrre alcun risultato oggi.

Il Coordinatore ACTELYA ("coordinatore-actelya" lato frontend) NON è un
agente selezionabile: non compare in questa mappatura, non è mai incluso
in activeAgentIds — è gestito separatamente dal frontend tramite
agentRegistry.js::COORDINATOR_AGENT, sempre visibile di suo.

Due capability M2 esistono ma non hanno alcun ruolo frontend dedicato
(auditor, tech_lead): sono processi di revisione automatici, sempre
eseguiti da m2/reviews.py su ogni deliverable indipendentemente dalla
selezione dinamica — mai esposti come agente "convocabile" in questa fase
(vedi UNMAPPED_M2_ONLY_CAPABILITIES)."""
from __future__ import annotations

from dataclasses import dataclass, field

EXECUTION_MODE_M2 = "M2"
EXECUTION_MODE_SIMULATION = "BRAIN_SIMULATION"
EXECUTION_MODE_UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class AgentMapping:
    capability: str          # capability M2 (m2/agents_registry.py::DELIVERABLE_CAPABILITY)
    m2_agent_id: str         # m2/agents_registry.py::AGENT_CONTRACTS
    frontend_agent_id: str   # frontend/src/components/meeting-room/agentRegistry.js
    role_name: str           # deve combaciare con agentRegistry.js::role_name
    typical_use_cases: str
    m2_operative: bool             # AGENT_CONTRACTS[...]["operative"] in M2 oggi
    execution_ready: bool          # True SOLO se execution_mode == "M2"
    execution_mode: str            # "M2" | "BRAIN_SIMULATION" | "UNAVAILABLE"
    deliverable_type: str | None = None   # tipo di deliverable M2 prodotto, se esiste
    implementation_note: str = ""         # spiegazione, obbligatoria se non "M2"
    notes: str = ""


# Ordine deterministico: definisce anche l'ordine stabile con cui
# selected_agents/activeAgentIds vengono restituiti (mai un ordine
# dipendente da un set/dict Python).
AGENT_MAPPINGS: tuple[AgentMapping, ...] = (
    AgentMapping(
        "strategy", "marketing_strategist", "resp-marketing", "Responsabile marketing",
        "Strategia, posizionamento, priorità tra canali di attrazione.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="marketing_strategy",
    ),
    AgentMapping(
        "editorial", "content_social", "social-media-manager", "Social media manager",
        "Piano editoriale, calendario contenuti organici.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="editorial_plan",
    ),
    AgentMapping(
        "social", "content_social", "copywriter", "Copywriter",
        "Scrittura dei singoli post/contenuti social.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="social_content",
        notes="Stesso agente M2 di 'editorial' (content_social): capability diversa, ruolo frontend diverso.",
    ),
    AgentMapping(
        "email", "content_social", "copywriter", "Copywriter",
        "Scrittura email.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="email",
        notes="Capability 'email' assegnata a content_social in M2; lato frontend mappata su Copywriter "
              "(stesso ruolo di 'social').",
    ),
    AgentMapping(
        "ads", "advertising", "resp-advertising", "Specialista advertising",
        "Bozza di campagna pubblicitaria (mai pubblicata).", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="ad_campaign_draft",
    ),
    AgentMapping(
        "leadgen", "lead_gen_sdr", "lead-gen-specialist", "Lead generation specialist",
        "Criteri e piano di lead generation (nessun contatto reale).", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="lead_gen_plan",
    ),
    AgentMapping(
        "analytics", "analytics_performance", "analista-performance", "Analista performance",
        "Report KPI, lettura/valutazione di risultati e performance esistenti.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="kpi_report",
    ),
    AgentMapping(
        "review_compliance", "compliance_reviewer", "resp-compliance", "Responsabile compliance",
        "Verifica di conformità sui contenuti prodotti.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type=None,
        implementation_note="Non produce un deliverable proprio: è una revisione automatica eseguita "
                             "da m2/reviews.py su ogni deliverable, non un task distinto del DAG.",
        notes="In M2 la revisione compliance è già eseguita automaticamente su ogni deliverable "
              "(m2/reviews.py, invariato). Qui selezionabile esplicitamente quando si produce "
              "contenuto rivolto al pubblico, per mostrarlo come collaboratore attivo in sala riunioni.",
    ),
    AgentMapping(
        "appointments", "appointment_setter", "appointment-setter", "Appointment setter",
        "Predisporre un processo per ottenere appuntamenti.", False,
        execution_ready=False, execution_mode=EXECUTION_MODE_UNAVAILABLE, deliverable_type=None,
        implementation_note="Nessun deliverable_type esiste in M2 per questa capability e nessun "
                             "producer di simulazione esiste nel brain (verificato su "
                             "m2/deliverables.py::PRODUCERS e brain/producers.py::BRAIN_PRODUCERS, "
                             "entrambi privi di una voce 'appointments'). PREDISPOSTO in M2 "
                             "(agents_registry.py, operative=False): non eseguibile, né realmente né "
                             "in simulazione, in questa fase.",
    ),
    AgentMapping(
        "nurturing", "nurturing", "specialista-nurturing", "Specialista nurturing",
        "Mantenimento nel tempo dei lead non ancora pronti.", False,
        execution_ready=False, execution_mode=EXECUTION_MODE_UNAVAILABLE, deliverable_type=None,
        implementation_note="Stesso limite di 'appointments': nessun deliverable_type M2 e nessun "
                             "producer di simulazione nel brain per questa capability oggi.",
    ),
)

# Capability M2 che esistono ma NON sono esposte come agenti selezionabili
# dal brain in questa fase: processi automatici interni a M2, mai in
# activeAgentIds, mai in selected_agents/excluded_agents.
UNMAPPED_M2_ONLY_CAPABILITIES: dict[str, str] = {
    "review_audit": "auditor",   # eseguito automaticamente da m2/reviews.py su ogni deliverable
    "review_tech": "tech_lead",  # nessun ruolo frontend dedicato; fuori scope in questa fase
}

COORDINATOR_FRONTEND_ID = "coordinatore-actelya"


@dataclass(frozen=True)
class AgentGroup:
    """Un agente frontend può coprire più capability M2 (es. copywriter
    copre sia 'social' sia 'email', stesso agente M2 content_social)."""
    frontend_agent_id: str
    role_name: str
    mappings: tuple[AgentMapping, ...] = field(default_factory=tuple)

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(m.capability for m in self.mappings)

    @property
    def m2_agent_id(self) -> str:
        return self.mappings[0].m2_agent_id

    @property
    def m2_operative(self) -> bool:
        return self.mappings[0].m2_operative


def agent_groups() -> tuple[AgentGroup, ...]:
    """Raggruppa AGENT_MAPPINGS per agent_id frontend, preservando
    l'ordine di prima apparizione: un solo AgentGroup per ciascuno dei 9
    ruoli frontend, anche quando più capability M2 vi convergono."""
    order: list[str] = []
    grouped: dict[str, list[AgentMapping]] = {}
    for m in AGENT_MAPPINGS:
        if m.frontend_agent_id not in grouped:
            grouped[m.frontend_agent_id] = []
            order.append(m.frontend_agent_id)
        grouped[m.frontend_agent_id].append(m)
    return tuple(
        AgentGroup(frontend_agent_id=fid, role_name=grouped[fid][0].role_name, mappings=tuple(grouped[fid]))
        for fid in order
    )


ALL_FRONTEND_AGENT_IDS: frozenset = frozenset(m.frontend_agent_id for m in AGENT_MAPPINGS)


def mapping_by_capability(capability: str) -> AgentMapping | None:
    for m in AGENT_MAPPINGS:
        if m.capability == capability:
            return m
    return None


def group_by_frontend_id(agent_id: str) -> AgentGroup | None:
    for g in agent_groups():
        if g.frontend_agent_id == agent_id:
            return g
    return None
