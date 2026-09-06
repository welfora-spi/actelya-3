"""Cost ledger condiviso per il Tool Execution Gateway (Fase 1) — traccia la
spesa REALE per organizzazione/strumento e applica, solo se configurato, un
tetto di spesa giornaliero. Nessun blocco se l'organizzazione non ha
configurato un tetto: un limite che l'utente non ha impostato non viene mai
inventato qui (stesso principio di ogni altro guardrail in questo progetto:
mai un vincolo silenzioso non richiesto)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..models import new_id, now_iso


class BudgetExceededError(Exception):
    pass


def _oggi() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def get_daily_cap(db, org_id: str) -> Optional[float]:
    doc = await db.organization_budgets.find_one({"organization_id": org_id}, {"_id": 0, "daily_cap_usd": 1})
    return doc.get("daily_cap_usd") if doc else None


async def set_daily_cap(db, org_id: str, daily_cap_usd: Optional[float], actor: str) -> None:
    await db.organization_budgets.update_one(
        {"organization_id": org_id},
        {"$set": {"organization_id": org_id, "daily_cap_usd": daily_cap_usd,
                  "updated_at": now_iso(), "updated_by": actor}},
        upsert=True,
    )


async def spent_today(db, org_id: str, *, tool_id: Optional[str] = None) -> float:
    query = {"organization_id": org_id, "day": _oggi()}
    if tool_id:
        query["tool_id"] = tool_id
    righe = await db.tool_cost_events.find(query, {"_id": 0, "amount": 1}).to_list(10000)
    return round(sum(r["amount"] for r in righe), 6)


async def check_budget(db, *, org_id: str, tool_id: str, estimated_cost: float) -> None:
    """Solleva BudgetExceededError SOLO se l'organizzazione ha configurato un
    tetto giornaliero (set_daily_cap) e la spesa odierna + la stima lo
    supererebbe. Va chiamata PRIMA della chiamata reale (stima), mai dopo."""
    cap = await get_daily_cap(db, org_id)
    if cap is None:
        return
    speso = await spent_today(db, org_id)
    if speso + estimated_cost > cap:
        raise BudgetExceededError(
            f"Budget giornaliero superato per l'organizzazione: già spesi {speso:.4f}, "
            f"tetto {cap:.4f}, stima ulteriore {estimated_cost:.4f} per '{tool_id}'."
        )


async def record_cost(db, *, org_id: str, tool_id: str, agent_id: str, amount: float, currency: str = "USD") -> None:
    """Registra il costo REALMENTE sostenuto (mai una stima) in un evento
    append-only — mai un update in place: la storia della spesa non si
    riscrive."""
    await db.tool_cost_events.insert_one({
        "id": new_id("costevt"), "organization_id": org_id, "tool_id": tool_id, "agent_id": agent_id,
        "amount": amount, "currency": currency, "day": _oggi(), "created_at": now_iso(),
    })
