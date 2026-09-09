"""Milestone 2 — modelli, enumerazioni, costruttori di record e indici.
Additivo rispetto a M1: nessuna collezione M1 viene modificata in modo distruttivo.
Tutto opera in MODALITA' SIMULAZIONE."""
from ..models import new_id, now_iso, base_record

# ---------------- Enumerazioni ----------------
OBJECTIVE_TYPES = ["STRATEGIA", "CAMPAGNA", "CONTENUTO", "LEAD_GEN", "REPORT", "EMAIL", "AMBIGUO"]

PLAN_STATUS = [
    "BOZZA", "IN_ATTESA_APPROVAZIONE", "APPROVATO_PARZIALE", "APPROVATO",
    "IN_ESECUZIONE", "COMPLETATO", "BLOCCATO", "ANNULLATO",
]

TASK_STATUS = [
    "PIANIFICATA", "IN_ATTESA_APPROVAZIONE", "IN_CODA", "IN_ESECUZIONE",
    "COMPLETATA", "FALLITA", "BLOCCATA", "SALTATA", "ARRESTATA",
]

DELIVERABLE_TYPES = [
    "marketing_strategy", "editorial_plan", "social_content",
    "ad_campaign_draft", "lead_gen_plan", "kpi_report", "email",
]

REVIEW_TYPES = ["compliance", "audit", "tech"]


# ---------------- Costruttori di record (con audit comuni) ----------------
def new_plan(org_id, user_id, goal_id, objective_type, dag, topo_order, estimate, version=1):
    rec = base_record(org_id, user_id)
    rec.update({
        "id": new_id("plan"),
        "goal_id": goal_id,
        "objective_type": objective_type,
        "plan_status": "BOZZA",
        "dag": dag,                     # {"nodes": [task_id...], "edges": [[from,to]...]}
        "topo_order": topo_order,       # [task_id, ...]
        "estimate": estimate,
        "version": version,
        "is_current": True,
        "superseded_by": None,
        "mode": "SIMULAZIONE",
    })
    return rec


def new_task(org_id, user_id, plan_id, goal_id, version, seq, name, agent_id,
             deliverable_type, inputs, depends_on, artifact_slot=None):
    rec = base_record(org_id, user_id)
    tid = new_id("task")
    rec.update({
        "id": tid,
        "plan_id": plan_id,
        "goal_id": goal_id,
        "version": version,
        "seq": seq,
        "name": name,
        "agent_id": agent_id,
        "deliverable_type": deliverable_type,
        "artifact_slot": artifact_slot or f"{deliverable_type}-{seq}",
        "inputs": inputs,
        "depends_on": depends_on or [],
        "task_status": "IN_ATTESA_APPROVAZIONE",  # non accodabile finché non approvata
        "approved": False,
        "attempt": 0,
        "idempotency_key": f"{plan_id}:{version}:{tid}",
        "lease_owner": None,
        "lease_expires_at": None,
        "tokens_input": 0,
        "tokens_output": 0,
        "cost": 0.0,
        "deliverable_id": None,
        "warnings": [],
        "confirmed": False,
        "started_at": None,
        "finished_at": None,
        "mode": "SIMULAZIONE",
    })
    return rec


def new_review(org_id, reviewer_agent, plan_id, task_id, deliverable_id, review_type, findings, severity="info"):
    ts = now_iso()
    return {
        "id": new_id("review"),
        "organization_id": org_id,
        "reviewer_agent": reviewer_agent,
        "actor": reviewer_agent,
        "plan_id": plan_id,
        "task_id": task_id,
        "deliverable_id": deliverable_id,
        "review_type": review_type,
        "findings": findings,
        "severity": severity,
        "non_destructive": True,
        "created_at": ts,
        "updated_at": ts,
        "change_history": [],
    }


# ---------------- Indici (idempotenti, additivi) ----------------
async def create_m2_indexes(db):
    # Piani: id unico, versione logica unica per goal
    await db.plans.create_index("id", unique=True)
    await db.plans.create_index([("goal_id", 1), ("version", 1)], unique=True)
    # Vincolo atomico equivalente alla transazione: al più UNA versione corrente per goal
    await db.plans.create_index(
        [("goal_id", 1)], unique=True, name="uniq_current_per_goal",
        partialFilterExpression={"is_current": True},
    )

    # Task: id unico, ordine unico nel piano, idempotenza per attempt
    await db.tasks.create_index("id", unique=True)
    await db.tasks.create_index([("plan_id", 1), ("seq", 1)], unique=True)
    await db.tasks.create_index("idempotency_key", unique=True)
    # Avvio automatico dopo approvazione (engine.py::auto_dispatch_worker_loop):
    # query sul solo marcatore persistito, mai sulla vecchia coda storica.
    await db.tasks.create_index([("task_status", 1), ("auto_dispatch_requested_at", 1)])

    # Deliverable M2: chiave che include task_id + version (consente PIU' deliverable
    # dello stesso tipo nello stesso piano, uno per task/slot). Partial: solo record M2.
    await db.deliverables.create_index(
        [("plan_id", 1), ("task_id", 1), ("version", 1)], unique=True,
        name="uniq_deliverable_task_version",
        partialFilterExpression={"plan_id": {"$exists": True}, "task_id": {"$exists": True}},
    )
    # Slot alternativo (piu' deliverable stesso tipo via artifact_slot distinti)
    await db.deliverables.create_index(
        [("plan_id", 1), ("deliverable_type", 1), ("artifact_slot", 1), ("version", 1)],
        unique=True, name="uniq_deliverable_slot_version",
        partialFilterExpression={"plan_id": {"$exists": True}, "artifact_slot": {"$exists": True}},
    )
    # Al più UNA versione corrente per (plan, task): versionamento non sovrascrivente.
    await db.deliverables.create_index(
        [("plan_id", 1), ("task_id", 1)], unique=True,
        name="uniq_current_deliverable_per_task",
        partialFilterExpression={"is_current": True},
    )

    # Una sola execution per versione di piano
    await db.executions.create_index(
        [("plan_id", 1), ("plan_version", 1)], unique=True,
        name="uniq_execution_plan_version",
        partialFilterExpression={"plan_id": {"$exists": True}},
    )

    # Lease worker (lock persistente): un solo lease per task
    await db.worker_leases.create_index("task_id", unique=True)
    await db.worker_leases.create_index("expires_at")

    # Revisioni e handoff
    await db.reviews.create_index("id", unique=True)
    await db.reviews.create_index([("plan_id", 1), ("task_id", 1)])
    # Una revisione per (deliverable, tipo): idempotenza, non distruttiva.
    await db.reviews.create_index(
        [("deliverable_id", 1), ("review_type", 1)], unique=True,
        name="uniq_review_per_deliverable_type",
        partialFilterExpression={"deliverable_id": {"$exists": True}},
    )
    await db.handoffs.create_index("id", unique=True)
    await db.handoffs.create_index([("plan_id", 1)])

    # Decisioni editoriali umane sulle singole bozze di un deliverable multi-item
    # (es. social_content -> "posts"): al piu' UNA decisione per (deliverable,
    # indice bozza, VERSIONE della bozza) — una decisione e' terminale solo
    # per la versione a cui si riferisce, mai per la bozza in assoluto (una
    # versione successiva, nata da una richiesta di modifica applicata, ha
    # una propria decisione libera). Protezione atomica contro decisioni
    # duplicate/in corsa, oltre al controllo applicativo in
    # m2/deliverable_review.py.
    await db.deliverable_item_decisions.create_index("id", unique=True)
    # L'indice precedente (senza 'version', da una versione di questo codice
    # precedente all'introduzione del versionamento per bozza) non viene mai
    # sostituito automaticamente da create_index con un nome diverso — resta
    # a imporre il proprio vincolo piu' restrittivo (una sola decisione per
    # bozza IN ASSOLUTO) insieme al nuovo, bloccando la decisione di una
    # versione 2 dopo la 1. Va rimosso esplicitamente, mai lasciato residuo.
    try:
        await db.deliverable_item_decisions.drop_index("uniq_decision_per_deliverable_item")
    except Exception:
        pass  # mai esistito in questo database: nulla da rimuovere.
    await db.deliverable_item_decisions.create_index(
        [("deliverable_id", 1), ("item_index", 1), ("version", 1)], unique=True,
        name="uniq_decision_per_deliverable_item_version",
    )
    await db.deliverable_item_decisions.create_index([("plan_id", 1)])

    # Versioni successive di UNA singola bozza (nate da una richiesta di
    # modifica applicata esplicitamente): al piu' UNA versione N per
    # (deliverable, indice bozza) — mai due modifiche concorrenti che
    # producono la stessa versione. La versione 1 e' sempre il contenuto
    # originale del deliverable (mai duplicata in questa collezione).
    await db.deliverable_item_versions.create_index("id", unique=True)
    await db.deliverable_item_versions.create_index(
        [("deliverable_id", 1), ("item_index", 1), ("version", 1)], unique=True,
        name="uniq_version_per_deliverable_item",
    )
    await db.deliverable_item_versions.create_index([("plan_id", 1)])


async def swap_current_version(db, goal_id, new_plan_id, actor="system", audit=None):
    """Sposta is_current sulla nuova versione in modo atomico.
    - Se MongoDB supporta le transazioni (replica set): swap transazionale (rollback automatico).
    - Altrimenti (standalone): unset-old -> set-new; se set-new FALLISCE, RIPRISTINA la
      versione corrente precedente e registra l'errore nell'audit. Mai lasciare il goal
      senza versione corrente in modo silenzioso."""
    if audit is None:
        from ..audit import log_audit as audit  # lazy import, evita cicli

    client = db.client
    # 1) Tentativo transazionale
    try:
        async with await client.start_session() as s:
            async with s.start_transaction():
                await db.plans.update_many(
                    {"goal_id": goal_id, "is_current": True, "id": {"$ne": new_plan_id}},
                    {"$set": {"is_current": False, "superseded_by": new_plan_id, "updated_at": now_iso()}},
                    session=s,
                )
                res = await db.plans.update_one(
                    {"id": new_plan_id},
                    {"$set": {"is_current": True, "updated_at": now_iso()}},
                    session=s,
                )
                if res.matched_count == 0:
                    raise RuntimeError("nuovo piano inesistente")
        return True
    except Exception as tx_err:
        msg = str(tx_err)
        unsupported = (
            "Transaction numbers are only allowed" in msg
            or "Transactions are not supported" in msg
            or ("not supported" in msg.lower() and "transaction" in msg.lower())
            or getattr(tx_err, "code", None) in (20, 251, 263)
        )
        if not unsupported:
            # Deployment con transazioni: rollback avvenuto, la corrente e' intatta.
            await audit(org_id=None, user={"email": actor}, action="SWAP_CURRENT_VERSION_FAILED",
                        entity_type="plan", entity_id=new_plan_id, status="ERROR",
                        reason="Transazione annullata; versione corrente precedente preservata")
            raise

    # 2) Fallback standalone con RIPRISTINO su fallimento
    prev = await db.plans.find(
        {"goal_id": goal_id, "is_current": True, "id": {"$ne": new_plan_id}},
        {"_id": 0, "id": 1},
    ).to_list(100)
    prev_ids = [p["id"] for p in prev]

    await db.plans.update_many(
        {"goal_id": goal_id, "is_current": True, "id": {"$ne": new_plan_id}},
        {"$set": {"is_current": False, "superseded_by": new_plan_id, "updated_at": now_iso()}},
    )
    try:
        res = await db.plans.update_one(
            {"id": new_plan_id}, {"$set": {"is_current": True, "updated_at": now_iso()}},
        )
        if res.matched_count == 0:
            raise RuntimeError("set-new non ha aggiornato alcun documento")
        return True
    except Exception as set_err:
        # RIPRISTINO: riporta corrente la versione precedente. Mai lasciare senza corrente.
        if prev_ids:
            await db.plans.update_many(
                {"id": {"$in": prev_ids}},
                {"$set": {"is_current": True, "superseded_by": None, "updated_at": now_iso()}},
            )
        await audit(org_id=None, user={"email": actor}, action="SWAP_CURRENT_VERSION_FAILED",
                    entity_type="plan", entity_id=new_plan_id, status="ERROR",
                    reason="set-new fallito; ripristinata la versione corrente precedente")
        raise
