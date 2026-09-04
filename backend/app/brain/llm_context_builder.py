"""Brain — costruzione del contesto minimizzato inviato al provider LLM
(CEO Agent 100% reale, blocco 5).

Un solo punto di raccolta: richiesta originale, Company Profile, Fact Ledger
CON provenienza (valore/stato/fonte/metodo — mai solo il valore nudo),
agenti/capability realmente disponibili (dallo stesso registry che governa
la selezione deterministica, mai una lista parallela), deliverable
supportati, un breve registro di vincoli/compliance, budget/vincoli gia'
noti, chiarimenti gia' forniti in questa sessione. Applica minimizzazione
esplicita: MAI un token/credenziale/segreto, MAI un campo del profilo non
pertinente alla richiesta (es. nessun dato di fatturazione)."""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Optional

from .agents.agent_map import agent_groups, EXECUTION_MODE_UNAVAILABLE

# Registro di vincoli/compliance, breve e stabile: descrive al modello le
# regole che NON puo' mai aggirare (rinforzo esplicito nel prompt, la
# validazione VERA resta comunque sempre in llm_validator.py — questo testo
# non e' mai l'unica barriera).
CONSTRAINT_REGISTRY_TEXT = (
    "Vincoli non negoziabili: (1) non puoi creare, pubblicare, inviare o spendere nulla "
    "realmente: ogni output e' una PROPOSTA che verra' validata e, se prevede un effetto "
    "esterno, richiedera' sempre un'approvazione umana esplicita; (2) puoi suggerire SOLO "
    "capability/agenti dall'elenco fornito, mai inventarne di nuovi; (3) non puoi superare "
    "il budget indicato ne' aggirare un rischio di compliance; (4) se mancano dati "
    "indispensabili, elencali in 'dati_mancanti' invece di inventarli."
)


def _capability_disponibili() -> list[dict]:
    out = []
    for g in agent_groups():
        for m in g.mappings:
            if m.execution_mode == EXECUTION_MODE_UNAVAILABLE:
                continue
            out.append({
                "capability": m.capability, "agente": g.frontend_agent_id, "ruolo": g.role_name,
                "deliverable_type": m.deliverable_type, "modalita_esecuzione": m.execution_mode,
                "casi_uso": m.typical_use_cases,
            })
    return out


@dataclass
class BrainLLMContext:
    richiesta_originale: str
    company_profile: dict = dc_field(default_factory=dict)          # solo campi non sensibili
    fact_ledger: dict = dc_field(default_factory=dict)               # {campo: {value, method, source, confidence, state}}
    capability_disponibili: list = dc_field(default_factory=list)
    budget_residuo_operativo: Optional[float] = None                 # domains/budget.py, cap AI reale org
    vincoli_noti: list = dc_field(default_factory=list)
    chiarimenti_precedenti: list = dc_field(default_factory=list)    # [{domanda, risposta}]

    def come_prompt_utente(self) -> str:
        righe = [f"Richiesta originale dell'imprenditore: {self.richiesta_originale.strip()}"]

        if self.company_profile:
            righe.append("Company Profile: " + "; ".join(
                f"{k}={v}" for k, v in self.company_profile.items() if v
            ))

        if self.fact_ledger:
            righe.append("Fact Ledger (valore | metodo | fonte | confidence):")
            for campo, f in self.fact_ledger.items():
                righe.append(
                    f"- {campo}: {f.get('value')} | {f.get('method')} | {f.get('source')} | "
                    f"{f.get('confidence', 0.0):.2f}"
                )

        righe.append("Capability/agenti realmente disponibili (usa SOLO questi identificativi):")
        for c in self.capability_disponibili:
            righe.append(f"- capability='{c['capability']}' agente='{c['agente']}' ({c['casi_uso']})")

        if self.budget_residuo_operativo is not None:
            righe.append(f"Budget operativo residuo dell'organizzazione (per chiamate AI, non il budget di marketing dell'utente): {self.budget_residuo_operativo:.2f}")

        if self.vincoli_noti:
            righe.append("Vincoli gia' noti: " + "; ".join(self.vincoli_noti))

        if self.chiarimenti_precedenti:
            righe.append("Chiarimenti gia' forniti in questa sessione (NON richiederli di nuovo):")
            for c in self.chiarimenti_precedenti:
                if c.get("answer"):
                    righe.append(f"- D: {c.get('question')} R: {c.get('answer')}")

        righe.append(CONSTRAINT_REGISTRY_TEXT)
        return "\n".join(righe)


_CAMPI_PROFILO_NON_SENSIBILI = ("ragione_sociale", "nome_commerciale", "settore", "sito_web")


async def build_context(db, org_id: str, goal_text: str, *, chiarimenti_precedenti: Optional[list] = None) -> BrainLLMContext:
    """db=None o senza le collection attese -> contesto minimo (solo la
    richiesta originale): mai un'eccezione, la costruzione del contesto e'
    parte del percorso opzionale/reale, non deve mai bloccare il fallback
    deterministico."""
    ctx = BrainLLMContext(richiesta_originale=goal_text, chiarimenti_precedenti=chiarimenti_precedenti or [])
    if db is None:
        ctx.capability_disponibili = _capability_disponibili()
        return ctx
    try:
        org = await db.organizations.find_one({"id": org_id}, {"_id": 0}) or {}
        ctx.company_profile = {k: org.get(k) for k in _CAMPI_PROFILO_NON_SENSIBILI if org.get(k)}
    except (AttributeError, TypeError):
        pass
    try:
        from ..domains.knowledge import current_facts_map
        facts = await current_facts_map(db, org_id)
        ctx.fact_ledger = {
            k: {"value": f.get("value"), "method": f.get("method"), "source": f.get("source"),
                "confidence": f.get("confidence", 0.0)}
            for k, f in facts.items()
        }
    except (AttributeError, TypeError):
        pass
    try:
        budget = await db.budgets.find_one({"id": org_id}) or {}
        spent_rows = await db.executions.find({"organization_id": org_id}, {"_id": 0, "real_cost": 1}).to_list(1000)
        spesa = sum(r.get("real_cost", 0.0) for r in spent_rows)
        ctx.budget_residuo_operativo = round(budget.get("general_limit", 0.0) - spesa, 6)
    except (AttributeError, TypeError):
        pass

    ctx.capability_disponibili = _capability_disponibili()
    return ctx
