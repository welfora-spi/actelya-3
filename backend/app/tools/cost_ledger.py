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
    """Tetto giornaliero del Tool Execution Gateway. Se l'organizzazione non
    ha mai chiamato set_daily_cap (organization_budgets.daily_cap_usd
    assente), ricade sul tetto giornaliero GIA' configurato dall'utente nel
    budget generale (domains/budget.py, campo 'daily_limit', se > 0) — mai
    trattato come 'nessun tetto' solo perche' impostato da un percorso
    diverso: sarebbe un vincolo che l'utente ha davvero richiesto ma che la
    riserva preventiva ignorerebbe in silenzio."""
    doc = await db.organization_budgets.find_one({"organization_id": org_id}, {"_id": 0, "daily_cap_usd": 1})
    if doc and doc.get("daily_cap_usd") is not None:
        return doc["daily_cap_usd"]
    budget = await db.budgets.find_one({"id": org_id}, {"_id": 0, "daily_limit": 1})
    daily_limit = (budget or {}).get("daily_limit") or 0.0
    return daily_limit if daily_limit > 0 else None


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


# ==================== Riserva atomica PREVENTIVA (prima della chiamata) ====================
# check_budget() sopra e' un controllo "leggi poi decidi": corretto per il
# solo scopo per cui e' nato (un avviso pre-esistente, non contrastato da
# chiamate concorrenti nella pratica dei domini che lo usano), ma non basta
# quando piu' percorsi reali (comprensione/chiarimenti/riesame del brain,
# ciascuno con eventuali retry/fallback fra provider) possono tentare una
# riserva sulla STESSA organizzazione in parallelo. reserve_budget() usa lo
# stesso principio gia' collaudato in m2/engine.py::_reserve_execution_budget:
# un solo find_one_and_update con filtro condizionale sul documento stesso,
# cosi' due riserve concorrenti che insieme supererebbero il tetto non
# possono MAI passare entrambe.
async def reserve_budget(db, *, org_id: str, tool_id: str, estimated_cost: float) -> tuple[bool, str]:
    """Da chiamare SEMPRE prima di una chiamata reale a pagamento. Ritorna
    (True, "") se la riserva e' andata a buon fine (o se l'organizzazione
    non ha configurato alcun tetto — mai un vincolo silenzioso non
    richiesto, stesso principio di check_budget), (False, motivo) se il
    tetto residuo non basta: in quel caso NESSUNA chiamata reale va
    effettuata. Ogni riserva riuscita va sempre chiusa con
    release_reservation() (chiamata mai avvenuta/fallita prima di
    consumare token) o reconcile_reservation() (chiamata avvenuta, costo
    reale gia' registrato con record_cost).

    Limite dichiarato (stesso principio di m2/engine.py::
    _general_budget_check): 'speso' e' letto da tool_cost_events PRIMA
    dell'operazione atomica, quindi una spesa REALE registrata nell'istante
    esatto fra questa lettura e l'operazione atomica sotto non e' vista da
    QUESTA riserva — non presentato come un tetto perfettamente rigido in
    ogni scenario di concorrenza, ma la corsa fra PIU' RISERVE (il caso
    reale per questo progetto: piu' tentativi/provider dello stesso
    obiettivo) resta comunque impossibile per costruzione, perche' il
    confronto finale avviene sul valore di 'reserved_usd' letto in modo
    atomico dal database al momento dell'update, non su una copia in
    memoria."""
    if estimated_cost <= 0:
        return True, ""
    cap = await get_daily_cap(db, org_id)
    if cap is None:
        return True, ""
    today = _oggi()
    # Passo 1 (SEMPRE sicuro, mai un DuplicateKeyError): il filtro e' solo
    # organization_id, la STESSA chiave dell'indice unico — un upsert non
    # puo' mai collidere con se stesso. $setOnInsert non tocca nulla se il
    # documento esiste gia' (qualunque sia 'reserved_day' al suo interno):
    # solo garantisce che un documento esista.
    #
    # (Il pattern precedente — upsert con filtro {organization_id,
    # reserved_day: {$ne: oggi}} — sembrava sicuro ma non lo era: se un
    # documento esisteva gia' con reserved_day GIA' uguale a oggi, quel
    # filtro non lo trovava, quindi l'upsert tentava un INSERT che violava
    # l'indice unico su organization_id -> DuplicateKeyError. Osservato
    # realmente contro l'organizzazione reale durante la verifica di questa
    # correzione, corretto qui.)
    await db.organization_budgets.update_one(
        {"organization_id": org_id},
        {"$setOnInsert": {"organization_id": org_id, "reserved_day": today, "reserved_usd": 0.0}},
        upsert=True,
    )
    # Passo 2 (sicuro: il documento esiste di sicuro ora, MAI upsert qui):
    # azzera la riserva se e' un nuovo giorno rispetto all'ultima volta.
    await db.organization_budgets.update_one(
        {"organization_id": org_id, "reserved_day": {"$ne": today}},
        {"$set": {"reserved_day": today, "reserved_usd": 0.0}},
    )
    # Passo 3 (atomico, protetto dalla concorrenza): incrementa SOLO se
    # spesa gia' registrata + riservato finora + questa stima resta entro
    # il tetto. 'cap' e' il valore GIA' risolto da get_daily_cap() (puo'
    # venire dal fallback budgets.daily_limit, che non esiste come campo
    # 'daily_cap_usd' su QUESTO documento) — confrontato come costante, mai
    # ri-letto da un campo che potrebbe non esserci.
    speso = await spent_today(db, org_id)
    aggiornato = await db.organization_budgets.find_one_and_update(
        {"organization_id": org_id, "reserved_day": today,
         "$expr": {"$lte": [{"$add": [{"$ifNull": ["$reserved_usd", 0.0]}, speso, estimated_cost]}, cap]}},
        {"$inc": {"reserved_usd": estimated_cost}},
        return_document=True,
    )
    if aggiornato is None:
        return False, (f"Budget giornaliero insufficiente per '{tool_id}': gia' spesi {speso:.4f} USD, "
                       f"tetto {cap:.4f} USD, stima aggiuntiva {estimated_cost:.4f} USD.")
    return True, ""


async def release_reservation(db, *, org_id: str, estimated_cost: float) -> None:
    """Rilascia una riserva di reserve_budget quando la chiamata reale non
    e' mai partita o e' fallita PRIMA di consumare token (nessun costo
    reale sostenuto) — mai una riserva 'fantasma' che resta a occupare il
    tetto per una chiamata che non e' avvenuta."""
    if estimated_cost <= 0:
        return
    await db.organization_budgets.update_one(
        {"organization_id": org_id}, {"$inc": {"reserved_usd": -estimated_cost}},
    )


async def reconcile_reservation(db, *, org_id: str, estimated_cost: float) -> None:
    """Da chiamare DOPO aver registrato il costo REALE con record_cost():
    la riserva (una stima) va rilasciata perche' spent_today() ora include
    gia' l'importo vero — trattenerla sommerebbe stima E costo reale,
    contando la stessa chiamata due volte sul tetto residuo."""
    await release_reservation(db, org_id=org_id, estimated_cost=estimated_cost)
