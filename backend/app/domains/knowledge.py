"""Fact Ledger — conoscenza aziendale condivisa fra tutti gli agenti.

Ogni informazione sull'azienda è un "fatto atomico" (campo, valore) con fonte,
metodo di acquisizione, affidabilità e stato. Nessun agente scrive direttamente
sul profilo azienda: passa da qui, cosi' ogni dato resta tracciabile e
riconciliabile fra fonti diverse (dichiarato, estratto, dedotto, verificato).

Regola di priorità fra metodi (più alto vince a parità di valore diverso):
VERIFICATO > DICHIARATO > ESTRATTO > DEDOTTO. Un fatto di priorità superiore
supera silenziosamente uno inferiore (lo stato del più debole diventa SCADUTO,
non richiede intervento). Un disaccordo fra fatti della STESSA priorità genera
CONTRADDITTORIO su entrambi: solo qui serve una domanda esplicita all'utente."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from ..db import db
from ..deps import get_current_user, require_roles, assert_same_org
from ..audit import log_audit
from ..models import now_iso, new_id, base_record
from ..config import DEFAULT_ORG_ID

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

METHOD_PRIORITY = {"VERIFICATO": 3, "DICHIARATO": 2, "ESTRATTO": 1, "DEDOTTO": 0}


def _public(f: dict) -> dict:
    return {
        "id": f["id"], "field": f["field"], "value": f["value"], "source": f["source"],
        "method": f["method"], "confidence": f.get("confidence", 0.0), "state": f.get("state", "ATTIVO"),
        "confirms": f.get("confirms", []), "conflicts_with": f.get("conflicts_with", []),
        "detected_at": f.get("detected_at"), "expires_at": f.get("expires_at"),
        "created_at": f.get("created_at"), "updated_at": f.get("updated_at"),
    }


async def write_fact(db, *, org_id: str, user_id: str, field: str, value: str, source: str,
                     method: str, confidence: float = 0.6, expires_at: Optional[str] = None) -> Optional[dict]:
    """Reconciles a new fact against the org's active facts for the same field.
    Returns the fact that ended up authoritative for this write (or None if value empty)."""
    value = (value or "").strip()
    if not value or method not in METHOD_PRIORITY:
        return None
    now = now_iso()
    active = await db.facts.find({"organization_id": org_id, "field": field, "state": "ATTIVO"}).to_list(50)

    matching = [f for f in active if f["value"].strip().lower() == value.lower()]
    if matching:
        best = max(matching, key=lambda f: f.get("confidence", 0.0))
        new_conf = min(1.0, best.get("confidence", 0.0) + 0.15)
        await db.facts.update_one(
            {"id": best["id"]},
            {"$set": {"confidence": new_conf, "updated_at": now, "updated_by": user_id},
             "$addToSet": {"confirms": source}},
        )
        best["confidence"] = new_conf
        return best

    new_rec = base_record(org_id, user_id)
    new_rec.update({
        "id": new_id("fact"), "field": field, "value": value, "source": source,
        "method": method, "confidence": confidence, "state": "ATTIVO",
        "detected_at": now, "expires_at": expires_at, "confirms": [], "conflicts_with": [],
    })

    if not active:
        await db.facts.insert_one(new_rec)
        new_rec.pop("_id", None)
        return new_rec

    new_prio = METHOD_PRIORITY[method]
    max_existing_prio = max(METHOD_PRIORITY.get(f["method"], 0) for f in active)

    if new_prio > max_existing_prio:
        # Higher authority silently supersedes: no conflict, no question to the user.
        ids = [f["id"] for f in active]
        await db.facts.update_many({"id": {"$in": ids}}, {"$set": {"state": "SCADUTO", "updated_at": now}})
        await db.facts.insert_one(new_rec)
        new_rec.pop("_id", None)
        return new_rec

    if new_prio < max_existing_prio:
        # Lower authority: kept for transparency/audit, but not authoritative and not a conflict.
        new_rec["state"] = "SCADUTO"
        await db.facts.insert_one(new_rec)
        new_rec.pop("_id", None)
        return new_rec

    # Same priority, disagreeing value: genuine contradiction — needs explicit resolution.
    same_prio_active = [f for f in active if METHOD_PRIORITY.get(f["method"], 0) == new_prio]
    ids = [f["id"] for f in same_prio_active]
    new_rec["state"] = "CONTRADDITTORIO"
    new_rec["conflicts_with"] = ids
    await db.facts.insert_one(new_rec)
    await db.facts.update_many({"id": {"$in": ids}}, {"$set": {"state": "CONTRADDITTORIO", "updated_at": now}})
    for fid in ids:
        await db.facts.update_one({"id": fid}, {"$addToSet": {"conflicts_with": new_rec["id"]}})
    new_rec.pop("_id", None)
    return new_rec


async def current_facts_map(db, org_id: str) -> dict:
    """One authoritative fact per field: highest method priority, then confidence, among ATTIVO."""
    rows = await db.facts.find({"organization_id": org_id, "state": "ATTIVO"}, {"_id": 0}).to_list(2000)
    best: dict = {}
    for f in rows:
        cur = best.get(f["field"])
        key = (METHOD_PRIORITY.get(f["method"], 0), f.get("confidence", 0.0))
        if not cur or key > (METHOD_PRIORITY.get(cur["method"], 0), cur.get("confidence", 0.0)):
            best[f["field"]] = f
    return best


class DeclareFactBody(BaseModel):
    field: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source: str = "manuale"
    confidence: float = 0.85


@router.get("/facts")
async def list_facts(field: Optional[str] = None, state: Optional[str] = None,
                     user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    q = {"organization_id": org_id}
    if field:
        q["field"] = field
    if state:
        q["state"] = state
    rows = await db.facts.find(q, {"_id": 0}).sort("detected_at", -1).to_list(1000)
    return [_public(f) for f in rows]


@router.get("/facts/current")
async def get_current_facts(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    best = await current_facts_map(db, org_id)
    return {field: _public(f) for field, f in best.items()}


@router.get("/conflicts")
async def list_conflicts(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.facts.find(
        {"organization_id": org_id, "state": "CONTRADDITTORIO"}, {"_id": 0}).sort("field", 1).to_list(500)
    by_field: dict = {}
    for f in rows:
        by_field.setdefault(f["field"], []).append(_public(f))
    return by_field


@router.post("/facts")
async def declare_fact(body: DeclareFactBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    fact = await write_fact(db, org_id=org_id, user_id=user["id"], field=body.field, value=body.value,
                            source=body.source, method="DICHIARATO", confidence=body.confidence)
    if not fact:
        raise HTTPException(status_code=400, detail="Valore vuoto")
    await log_audit(org_id=org_id, user=user, action="DECLARE_FACT",
                    entity_type="fact", entity_id=fact["id"],
                    details={"field": body.field, "state": fact.get("state")})
    return _public(fact)


@router.post("/facts/{fact_id}/confirm")
async def confirm_fact(fact_id: str, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    """Resolve a contradiction: this fact wins (becomes VERIFICATO/ATTIVO), the other
    contradictory facts for the same field are superseded (SCADUTO)."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    fact = await db.facts.find_one({"id": fact_id})
    assert_same_org(fact, user, "Fatto non trovato")
    now = now_iso()
    others = await db.facts.find({
        "organization_id": org_id, "field": fact["field"], "state": "CONTRADDITTORIO", "id": {"$ne": fact_id},
    }).to_list(50)
    await db.facts.update_one(
        {"id": fact_id},
        {"$set": {"state": "ATTIVO", "method": "VERIFICATO", "confidence": 1.0,
                  "updated_at": now, "updated_by": user["id"]}},
    )
    other_ids = [o["id"] for o in others]
    if other_ids:
        await db.facts.update_many({"id": {"$in": other_ids}}, {"$set": {"state": "SCADUTO", "updated_at": now}})
    await log_audit(org_id=org_id, user=user, action="CONFIRM_FACT",
                    entity_type="fact", entity_id=fact_id,
                    details={"field": fact["field"], "superseded": other_ids})
    out = await db.facts.find_one({"id": fact_id}, {"_id": 0})
    return _public(out)
