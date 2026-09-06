"""Tool Execution Gateway (Fase 1) — punto di passaggio obbligato per
l'esecuzione di uno strumento censito nel Professional Tool Registry:

    Agente -> Skill -> Tool Registry -> autorizzazione -> connessione
    tenant -> approvazione -> budget -> adapter -> validazione ->
    persistenza -> audit.

Questo modulo copre i controlli CONDIVISI (autorizzazione dell'agente per lo
strumento, stato reale della connessione per l'organizzazione, approvazione
esplicita, budget) da eseguire SEMPRE prima di invocare l'adapter concreto
di un dominio (validazione/persistenza/audit specifici restano nel dominio
stesso, che li conosce). Non sostituisce Brain/M2/i domini esistenti: è il
controllo che un dominio deve richiamare esplicitamente nel punto in cui sta
per usare uno strumento REALE. Un dominio che invoca il proprio adapter
senza prima chiamare authorize() sta aggirando il gateway."""
from __future__ import annotations

from typing import Optional

from ..audit import log_audit
from . import registry as R
from .cost_ledger import BudgetExceededError, check_budget, record_cost
from .status import computed_status_for


class ToolGatewayError(Exception):
    """Rifiuto esplicito del gateway — sempre con un `code` stabile che il
    chiamante puo' distinguere (mai un messaggio generico da interpretare)."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


async def authorize(db, *, org_id: str, agent_id: str, tool_id: str,
                    approved: bool = False, estimated_cost: float = 0.0,
                    user: Optional[dict] = None, actor: str = "system") -> R.ToolSpec:
    """Autorizza l'uso di uno strumento da parte di un agente per
    un'organizzazione. Solleva ToolGatewayError con un codice esplicito in
    ogni caso di rifiuto — mai un'esecuzione silenziosa quando qualcosa non
    torna. NON invoca l'adapter: il chiamante lo fa SOLO dopo aver ricevuto
    l'autorizzazione, poi richiama record_execution() per registrare l'esito."""
    tool = R.get_tool(tool_id)
    if tool is None:
        raise ToolGatewayError("STRUMENTO_SCONOSCIUTO", f"Strumento '{tool_id}' non censito nel Tool Registry.")
    if agent_id not in tool.allowed_agents:
        raise ToolGatewayError(
            "AGENTE_NON_AUTORIZZATO",
            f"L'agente '{agent_id}' non è autorizzato a usare '{tool_id}' (vedi allowed_agents).",
        )
    stato = await computed_status_for(tool, org_id, db)
    if stato != "VERIFICATO":
        raise ToolGatewayError(
            "CONNESSIONE_NON_VERIFICATA",
            f"'{tool_id}' non è utilizzabile per questa organizzazione: stato attuale {stato}.",
        )
    if tool.requires_approval and not approved:
        raise ToolGatewayError(
            "APPROVAZIONE_RICHIESTA",
            f"'{tool_id}' richiede un'approvazione esplicita dell'azione (approved=True) prima dell'esecuzione.",
        )
    if tool.can_incur_cost and estimated_cost > 0:
        try:
            await check_budget(db, org_id=org_id, tool_id=tool_id, estimated_cost=estimated_cost)
        except BudgetExceededError as exc:
            raise ToolGatewayError("BUDGET_SUPERATO", str(exc)) from exc
    await log_audit(org_id=org_id, user=user or {"id": actor, "email": actor}, action="TOOL_GATEWAY_AUTHORIZED",
                    entity_type="tool", entity_id=tool_id,
                    details={"agent_id": agent_id, "status": stato, "estimated_cost": estimated_cost})
    return tool


async def record_execution(db, *, org_id: str, tool_id: str, agent_id: str,
                           actual_cost: float = 0.0, outcome: str = "OK",
                           user: Optional[dict] = None, actor: str = "system") -> None:
    """Da richiamare DOPO l'esecuzione reale dell'adapter (mai prima): registra
    il costo effettivamente sostenuto (se diverso da zero, mai una stima) e
    un audit dell'esito — `outcome` deve riportare l'esito reale, mai
    un'approvazione implicita in caso di errore."""
    if actual_cost > 0:
        await record_cost(db, org_id=org_id, tool_id=tool_id, agent_id=agent_id, amount=actual_cost)
    await log_audit(org_id=org_id, user=user or {"id": actor, "email": actor}, action="TOOL_GATEWAY_EXECUTED",
                    entity_type="tool", entity_id=tool_id,
                    details={"agent_id": agent_id, "outcome": outcome, "actual_cost": actual_cost})
