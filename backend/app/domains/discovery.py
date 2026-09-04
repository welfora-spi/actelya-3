"""Discovery — analisi automatica di sito e social per popolare il Fact Ledger.

SIMULATO in questa milestone: nessuna chiamata di rete reale viene effettuata,
coerentemente con il resto del sistema (nessuna azione esterna senza collegamento
esplicito). L'estrazione è deterministica (basata sull'URL/dominio dichiarato),
chiaramente marcata ESTRATTO/SIMULATO e mai promossa a VERIFICATO in automatico.
Gira come coda persistente con un worker recuperabile, cosi' un obiettivo puo'
essere creato mentre una ricerca e' ancora IN_ESECUZIONE (nessun blocco reciproco)."""
import asyncio
import hashlib
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import db
from ..deps import get_current_user, require_roles, assert_same_org
from ..audit import log_audit
from ..models import now_iso, new_id, base_record
from ..config import DEFAULT_ORG_ID
from .knowledge import write_fact

logger = logging.getLogger("actelya.discovery")
router = APIRouter(prefix="/discovery", tags=["discovery"])

_worker_task = None
RUN_DELAY_SECONDS = 2  # simulates "search in progress" so status is observably IN_ESECUZIONE

TONES = ["Professionale e diretto", "Amichevole e informale", "Autorevole e tecnico"]
AUDIENCES = ["Piccole e medie imprese locali", "Consumatori privati nel territorio servito",
            "Professionisti e studi di settore"]


def _stable_choice(options: list, seed: str):
    if not options:
        return None
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return options[int(digest, 16) % len(options)]


class RunBody(BaseModel):
    pass


def _public(run: dict) -> dict:
    return {k: v for k, v in run.items() if k != "_id"}


@router.post("/run")
async def start_run(user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0}) or {}
    website = (org.get("sito_web") or "").strip()
    social = [s.strip() for s in (org.get("canali_utilizzati") or "").split(",") if s.strip()]
    if not website and not social:
        raise HTTPException(status_code=400,
                            detail="Nessun sito o canale social dichiarato: completa prima l'onboarding.")
    run = base_record(org_id, user["id"])
    run.update({
        "id": new_id("disco"), "status": "IN_CODA", "mode": "SIMULATO",
        "target_website": website, "target_social": social,
        "started_at": None, "finished_at": None, "facts_written": [], "warnings": [],
    })
    await db.discovery_runs.insert_one(run)
    await log_audit(org_id=org_id, user=user, action="DISCOVERY_QUEUED",
                    entity_type="discovery_run", entity_id=run["id"], details={"website": website})
    return _public(run)


@router.get("/runs")
async def list_runs(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.discovery_runs.find({"organization_id": org_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return rows


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: dict = Depends(get_current_user)):
    run = await db.discovery_runs.find_one({"id": run_id}, {"_id": 0})
    assert_same_org(run, user, "Ricerca non trovata")
    return run


async def process_run(run: dict):
    run_id = run["id"]
    claimed = await db.discovery_runs.find_one_and_update(
        {"id": run_id, "status": "IN_CODA"},
        {"$set": {"status": "IN_ESECUZIONE", "started_at": now_iso()}},
    )
    if not claimed:
        return
    org_id = run["organization_id"]
    actor_id = run["created_by"]
    await asyncio.sleep(RUN_DELAY_SECONDS)

    facts_written = []
    warnings = list(run.get("warnings", []))
    website = run.get("target_website") or ""
    social = run.get("target_social") or []
    seed = website or (social[0] if social else run_id)

    try:
        if website:
            domain = urlparse(website if "://" in website else f"//{website}", scheme="").netloc or website
            tone = _stable_choice(TONES, domain)
            audience = _stable_choice(AUDIENCES, domain + "a")
            f1 = await write_fact(db, org_id=org_id, user_id=actor_id, field="tono_di_voce", value=tone,
                                  source="discovery_sito", method="ESTRATTO", confidence=0.55)
            f2 = await write_fact(db, org_id=org_id, user_id=actor_id, field="pubblico_target", value=audience,
                                  source="discovery_sito", method="ESTRATTO", confidence=0.55)
            facts_written.extend(f["id"] for f in (f1, f2) if f)
        else:
            warnings.append("Nessun sito web dichiarato: analisi limitata ai social.")

        if social:
            f3 = await write_fact(db, org_id=org_id, user_id=actor_id, field="presenza_social",
                                  value=", ".join(social), source="discovery_social", method="ESTRATTO",
                                  confidence=0.55)
            facts_written.extend(f["id"] for f in (f3,) if f)
        else:
            warnings.append("Nessun canale social dichiarato.")

        await db.discovery_runs.update_one(
            {"id": run_id},
            {"$set": {"status": "COMPLETATO", "finished_at": now_iso(), "updated_at": now_iso(),
                      "facts_written": facts_written, "warnings": warnings}},
        )
        await log_audit(org_id=org_id, user={"email": "system"}, action="DISCOVERY_COMPLETED",
                        entity_type="discovery_run", entity_id=run_id,
                        details={"facts_written": len(facts_written), "warnings": warnings})
    except Exception:
        logger.exception("Discovery run fallita")
        await db.discovery_runs.update_one(
            {"id": run_id},
            {"$set": {"status": "FALLITO", "finished_at": now_iso(), "updated_at": now_iso()}},
        )
        await log_audit(org_id=org_id, user={"email": "system"}, action="DISCOVERY_FAILED",
                        entity_type="discovery_run", entity_id=run_id, status="ERROR")


async def worker_loop():
    logger.info("Discovery worker avviato")
    while True:
        try:
            pending = await db.discovery_runs.find(
                {"status": "IN_CODA"}, {"_id": 0}).sort("created_at", 1).to_list(10)
            for run in pending:
                await process_run(run)
        except Exception:
            logger.exception("Errore nel discovery worker loop")
        await asyncio.sleep(1)


async def recover_on_startup():
    res = await db.discovery_runs.update_many(
        {"status": "IN_ESECUZIONE"},
        {"$set": {"status": "IN_CODA", "updated_at": now_iso()}},
    )
    if res.modified_count:
        logger.info("Discovery recovery: %s ricerche riportate in coda", res.modified_count)


def start_worker():
    global _worker_task
    if _worker_task is None:
        _worker_task = asyncio.create_task(worker_loop())
