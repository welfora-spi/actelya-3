"""Brain — selezione dinamica degli agenti (Blocco B).

Dato il testo di un obiettivo, decide QUALI collaboratori convocare (mai
"marketing = tutti gli agenti"): rileva le capability richieste con
euristiche testuali deterministiche (nessun LLM, nessuna chiamata di rete),
le unisce alla mappatura ufficiale (agents/agent_map.py) e restituisce un
esito con uno tra quattro stati — READY, NEEDS_CLARIFICATION, UNSUPPORTED,
BLOCKED_RISK — mai un piano creato quando lo stato non è READY.

Riusa (senza duplicarla) la classificazione di sicurezza già presente in
domains/intent.py::classify_intent (rischio/azione esterna) e l'estrazione
di contesto già presente in brain/context.py::extract_goal_context
(azienda/prodotto mancanti -> mai inventati)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...domains.intent import classify_intent
from ..agents.agent_map import (
    EXECUTION_MODE_M2,
    EXECUTION_MODE_SIMULATION,
    EXECUTION_MODE_UNAVAILABLE,
    agent_groups,
    mapping_by_capability,
)
from ..context import extract_goal_context

# ---------------- Pattern di rilevamento capability (deterministici) ----------------
_STRATEGY_KW = [r"strategia", r"posizionamento", r"piano marketing", r"go-to-market", r"go to market"]
_EDITORIAL_KW = [r"piano editoriale", r"calendario editoriale", r"calendario dei contenuti"]
_SOCIAL_KW = [r"\bpost\b", r"contenuti social", r"contenuto social", r"\binstagram\b", r"\bfacebook\b", r"social media"]
_EMAIL_KW = [r"\bemail\b", r"\be-mail\b", r"\bnewsletter\b"]
_ADS_KW = [r"campagna pubblicitaria", r"campagna ads", r"\badvertising\b", r"sponsorizzat", r"annunci a pagamento", r"campagna a pagamento", r"\bads\b"]
_LEADGEN_KW = [r"lead generation", r"lead gen\b", r"trova client", r"potenziali client", r"acquisizione client", r"nuovi client", r"genera lead", r"generazione di lead"]
_APPOINTMENT_KW = [r"appuntament", r"prenotazion", r"fissare una call", r"ottenere appuntamenti"]
_NURTURING_KW = [r"\bnurturing\b", r"follow-up dei lead", r"coltivare i lead", r"mantenere il contatto con i lead"]
_ANALYTICS_KW = [r"\bkpi\b", r"\bperformance\b", r"risultati della campagna", r"analizza", r"analisi dei risultati", r"\breport\b"]

_ANALYSIS_ONLY_VERBS = [r"\banalizza\b", r"\bvaluta\b", r"\bmisura\b", r"controlla i risultati", r"leggi i risultati", r"leggi le performance"]
_CREATION_VERBS = [r"\bcrea\b", r"\bprepara\b", r"\bscrivi\b", r"\bgenera\b", r"\blancia\b", r"\bavvia\b", r"\bsviluppa\b", r"\bcostruisci\b", r"\bprogetta\b", r"\bredigi\b"]

_OUT_OF_DOMAIN_KW = [
    r"traduci il sito", r"prenota un volo", r"fai la contabilit", r"sviluppa un.?app",
    r"scrivi del codice", r"crea un sito web da zero", r"prenota un hotel", r"ordina la spesa",
    r"assumi un dipendente", r"ripara la stampante",
]

_RISK_DENYLIST_KW = [
    r"truffa", r"raggirare", r"ingannare i client", r"dati rubati", r"senza consenso",
    r"aggirare il consenso", r"falsificare", r"contenuti falsi per ingannare", r"fake news",
]

# Capability il cui contenuto è rivolto al pubblico: quando almeno una è
# selezionata, la revisione compliance viene convocata di conseguenza
# (in M2 è comunque sempre eseguita su ogni deliverable — qui la rendiamo
# visibile come collaboratore attivo solo quando pertinente).
_CONTENT_FACING_CAPABILITIES = {"editorial", "social", "ads", "email"}

STATUS_READY = "READY"
STATUS_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
STATUS_UNSUPPORTED = "UNSUPPORTED"
STATUS_BLOCKED_RISK = "BLOCKED_RISK"


def _normalizza(testo: str) -> str:
    return re.sub(r"\s+", " ", (testo or "").strip())


def _match_any(testo: str, patterns: list[str]) -> bool:
    return any(re.search(p, testo, re.IGNORECASE) for p in patterns)


def detect_capabilities(goal_text: str) -> list[str]:
    """Rileva TUTTE le capability con un segnale nel testo (una richiesta
    può convocare più agenti) — mai un solo intento vincente. Le richieste
    di sola analisi hanno la precedenza: "analizza i risultati della
    campagna" non attiva 'ads' solo perché nomina "campagna", a meno che il
    testo contenga anche un verbo di creazione esplicito."""
    testo = (goal_text or "").lower()

    trovate: list[str] = []
    if _match_any(testo, _ANALYTICS_KW):
        trovate.append("analytics")

    solo_analisi = _match_any(testo, _ANALYSIS_ONLY_VERBS) and not _match_any(testo, _CREATION_VERBS)
    if solo_analisi:
        return trovate

    if _match_any(testo, _STRATEGY_KW):
        trovate.append("strategy")
    if _match_any(testo, _EDITORIAL_KW):
        trovate.append("editorial")
    if _match_any(testo, _SOCIAL_KW):
        trovate.append("social")
    if _match_any(testo, _EMAIL_KW):
        trovate.append("email")
    if _match_any(testo, _ADS_KW):
        trovate.append("ads")
    if _match_any(testo, _LEADGEN_KW):
        trovate.append("leadgen")
    if _match_any(testo, _APPOINTMENT_KW):
        trovate.append("appointments")
    if _match_any(testo, _NURTURING_KW):
        trovate.append("nurturing")

    visti = set()
    ordinate = []
    for c in trovate:
        if c not in visti:
            visti.add(c)
            ordinate.append(c)
    return ordinate


# ---------------- Forma della risposta ----------------
@dataclass
class SelectedAgent:
    agent_id: str
    m2_agent_id: str
    capability: str
    capabilities: list[str]
    reason: str


@dataclass
class ExcludedAgent:
    agent_id: str
    m2_agent_id: str
    capability: str
    capabilities: list[str]
    reason: str


@dataclass
class SelectionResult:
    status: str
    normalized_goal: str
    detected_intents: list[str] = field(default_factory=list)
    selected_agents: list[SelectedAgent] = field(default_factory=list)
    activeAgentIds: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    clarifying_questions: list[str] = field(default_factory=list)
    selection_reasons: dict[str, str] = field(default_factory=dict)
    excluded_agents: list[ExcludedAgent] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    # --- Blocco B.1: prontezza di esecuzione, sempre presenti ---
    execution_ready: bool = False
    unavailable_capabilities: list[str] = field(default_factory=list)
    simulation_only_capabilities: list[str] = field(default_factory=list)
    execution_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "normalized_goal": self.normalized_goal,
            "detected_intents": self.detected_intents,
            "selected_agents": [a.__dict__ for a in self.selected_agents],
            "activeAgentIds": self.activeAgentIds,
            "missing_information": self.missing_information,
            "clarifying_questions": self.clarifying_questions,
            "selection_reasons": self.selection_reasons,
            "excluded_agents": [a.__dict__ for a in self.excluded_agents],
            "risk_flags": self.risk_flags,
            "execution_ready": self.execution_ready,
            "unavailable_capabilities": self.unavailable_capabilities,
            "simulation_only_capabilities": self.simulation_only_capabilities,
            "execution_warnings": self.execution_warnings,
        }


def _esito_non_pronto(status: str, *, normalized_goal: str, detected_intents=None,
                       missing_information=None, clarifying_questions=None, risk_flags=None,
                       unavailable_capabilities=None, execution_warnings=None) -> SelectionResult:
    return SelectionResult(
        status=status,
        normalized_goal=normalized_goal,
        detected_intents=detected_intents or [],
        selected_agents=[],
        activeAgentIds=[],
        missing_information=missing_information or [],
        clarifying_questions=(clarifying_questions or [])[:3],
        selection_reasons={},
        excluded_agents=[],
        risk_flags=risk_flags or [],
        execution_ready=False,
        unavailable_capabilities=unavailable_capabilities or [],
        simulation_only_capabilities=[],
        execution_warnings=execution_warnings or [],
    )


def select_agents(goal_text: str) -> SelectionResult:
    """Punto d'ingresso principale del Blocco B. Deterministico: la stessa
    richiesta produce sempre la stessa risposta (nessuno stato globale
    mutabile, nessuna casualità, nessun LLM)."""
    normalized = _normalizza(goal_text)

    intent = classify_intent(goal_text)
    risk_flags = list(intent.get("risk_flags", []))

    # 1) Sicurezza prima di tutto: azione esterna reale esplicitamente
    #    richiesta, o linguaggio manifestamente illegale/ingannevole. Una
    #    normale richiesta di bozze/strategie/materiali simulati NON è mai
    #    considerata rischiosa.
    if intent.get("requires_external_action") or _match_any(normalized, _RISK_DENYLIST_KW):
        flags = risk_flags or ["azione_esterna_non_autorizzata"]
        return _esito_non_pronto(STATUS_BLOCKED_RISK, normalized_goal=normalized, risk_flags=flags)

    # 2) Richiesta chiaramente fuori dal dominio di ACTELYA 3 (marketing/
    #    vendite/contenuti): nessuna capability disponibile può soddisfarla.
    if _match_any(normalized, _OUT_OF_DOMAIN_KW):
        return _esito_non_pronto(STATUS_UNSUPPORTED, normalized_goal=normalized, risk_flags=risk_flags)

    capabilities = detect_capabilities(goal_text)

    # 3) Nessuna capability riconosciuta ma nessun segnale "fuori dominio":
    #    richiesta genuinamente vaga/ambigua all'interno del nostro dominio.
    if not capabilities:
        return _esito_non_pronto(
            STATUS_NEEDS_CLARIFICATION, normalized_goal=normalized,
            missing_information=["tipo_di_deliverable"],
            clarifying_questions=[
                "Che tipo di risultato desideri (strategia, contenuti social, campagna pubblicitaria, "
                "lead generation, report)?",
            ],
            risk_flags=risk_flags,
        )

    # 4) Contesto aziendale indispensabile: mai inventato. Riusa
    #    context.py, unica fonte di verità per azienda/prodotto mancanti.
    ctx = extract_goal_context(goal_text)
    if ctx.missing_critical:
        return _esito_non_pronto(
            STATUS_NEEDS_CLARIFICATION, normalized_goal=normalized,
            detected_intents=capabilities,
            missing_information=list(ctx.missing_critical),
            clarifying_questions=list(ctx.questions),
            risk_flags=risk_flags,
        )

    # 5) Selezione vera e propria: compliance convocata quando si produce
    #    contenuto rivolto al pubblico (in M2 è comunque sempre revisionato).
    capabilities_effettive = list(capabilities)
    if any(c in capabilities_effettive for c in _CONTENT_FACING_CAPABILITIES) and "review_compliance" not in capabilities_effettive:
        capabilities_effettive.append("review_compliance")

    # 6) Prontezza di esecuzione (Blocco B.1): il brain non dichiara mai
    #    eseguibile un piano che M2 non può davvero trasformare in
    #    task/deliverable. Una capability qui è "non disponibile" se non ha
    #    né un agente M2 operativo né un producer di simulazione — mai un
    #    piano parziale creato in silenzio in quel caso.
    unavailable = [
        c for c in capabilities_effettive
        if (m := mapping_by_capability(c)) is not None and m.execution_mode == EXECUTION_MODE_UNAVAILABLE
    ]
    if unavailable:
        eseguibili = [c for c in capabilities_effettive if c not in unavailable]
        if not eseguibili:
            return _esito_non_pronto(
                STATUS_UNSUPPORTED, normalized_goal=normalized, detected_intents=capabilities_effettive,
                risk_flags=risk_flags, unavailable_capabilities=unavailable,
                execution_warnings=[
                    f"Nessuna capability richiesta è ad oggi eseguibile: {', '.join(unavailable)}.",
                ],
            )
        return _esito_non_pronto(
            STATUS_NEEDS_CLARIFICATION, normalized_goal=normalized, detected_intents=capabilities_effettive,
            risk_flags=risk_flags, unavailable_capabilities=unavailable,
            clarifying_questions=[
                f"Posso procedere subito con {eseguibili}, ma {unavailable} non è ancora eseguibile "
                f"(nessun task M2 disponibile): vuoi procedere solo con le parti disponibili?",
            ],
            execution_warnings=[
                f"Capability non eseguibili escluse dalla proposta: {', '.join(unavailable)}.",
            ],
        )

    simulation_only = [
        c for c in capabilities_effettive
        if (m := mapping_by_capability(c)) is not None and m.execution_mode == EXECUTION_MODE_SIMULATION
    ]

    selected: list[SelectedAgent] = []
    excluded: list[ExcludedAgent] = []
    for group in agent_groups():
        matched = [c for c in group.capabilities if c in capabilities_effettive]
        if matched:
            selected.append(SelectedAgent(
                agent_id=group.frontend_agent_id,
                m2_agent_id=group.m2_agent_id,
                capability=matched[0],
                capabilities=matched,
                reason=(
                    f"Capability {matched} rilevata nell'obiettivo -> {group.role_name} "
                    f"({group.mappings[0].typical_use_cases})"
                ),
            ))
        else:
            excluded.append(ExcludedAgent(
                agent_id=group.frontend_agent_id,
                m2_agent_id=group.m2_agent_id,
                capability=group.capabilities[0],
                capabilities=list(group.capabilities),
                reason=f"Nessun segnale per {list(group.capabilities)} nell'obiettivo.",
            ))

    active_ids = [a.agent_id for a in selected]
    selection_reasons = {a.agent_id: a.reason for a in selected}
    execution_ready = len(simulation_only) == 0  # nessuna capability solo indisponibile è già stata esclusa sopra
    execution_warnings = (
        [f"Capability eseguite in simulazione dal brain, non da M2: {', '.join(simulation_only)}."]
        if simulation_only else []
    )

    return SelectionResult(
        status=STATUS_READY,
        normalized_goal=normalized,
        detected_intents=capabilities_effettive,
        selected_agents=selected,
        activeAgentIds=active_ids,
        missing_information=[],
        clarifying_questions=[],
        selection_reasons=selection_reasons,
        excluded_agents=excluded,
        risk_flags=risk_flags,
        execution_ready=execution_ready,
        unavailable_capabilities=[],
        simulation_only_capabilities=simulation_only,
        execution_warnings=execution_warnings,
    )
