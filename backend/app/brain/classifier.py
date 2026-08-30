"""Brain — triage: classificazione dell'obiettivo + decisione se procedere o
chiedere chiarimenti, prima di costruire il piano.

Riusa, senza duplicarla, la classificazione deterministica gia' presente nel
corpo operativo M2 (m2.planner.classify_objective, che a sua volta usa
domains.intent.classify_intent per il tipo di intento — sicurezza/azione
esterna): il brain non re-implementa queste regole, le interpella e aggiunge
SOLO la sintesi finale (procedi / chiedi chiarimento) e le domande di
contesto mancanti. E' l'analogo, qui completamente deterministico e senza
alcuna chiamata a un modello, del ruolo di triage del CEO AI in ACTELYA
originale (orchestrator/ceo.py): interviene SOLO quando la classificazione
di base non basta a procedere con sicurezza."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..m2.planner import classify_objective
from .context import GoalContext, extract_goal_context


@dataclass
class Triage:
    objective_type: str
    intent_type: str
    risk_flags: list[str] = field(default_factory=list)
    requires_clarification: bool = False
    questions: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)

    def come_dict(self) -> dict:
        return asdict(self)


def triage_goal(goal_text: str) -> Triage:
    ctx: GoalContext = extract_goal_context(goal_text)
    cls = classify_objective(goal_text)  # riusa il planner M2, invariato

    questions = list(ctx.questions)
    requires_clarification = bool(ctx.missing_critical) or bool(cls["requires_clarification"])
    if cls["requires_clarification"] and cls["objective_type"] == "AMBIGUO":
        questions.append(
            "Che tipo di deliverable desideri (strategia, contenuti social, campagna, "
            "lead generation, report o email)?"
        )

    return Triage(
        objective_type=cls["objective_type"],
        intent_type=cls["intent"]["intent_type"],
        risk_flags=cls["intent"]["risk_flags"],
        requires_clarification=requires_clarification,
        questions=questions,
        context=ctx.come_dict(),
    )
