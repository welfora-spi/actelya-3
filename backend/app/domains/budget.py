from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..db import db
from ..deps import require_roles, get_current_user
from ..audit import log_audit
from ..models import now_iso
from ..config import DEFAULT_ORG_ID
from ..m2.real_content import REAL_ELIGIBLE_TYPES

router = APIRouter(prefix="/budget", tags=["budget"])


async def _real_cost_per_execution_corretto(db_conn, org_id: str) -> float:
    """Bug reale trovato in riconciliazione (2026-09-09, piano
    plan-c632efad5881492ea9fe, componente marketing_strategy ~$0.00195):
    execution.real_cost e' un campo di RISERVA/IMPEGNO sul tetto approvato
    (m2/engine.py::_execute, righe della riserva atomica) — incrementato per
    COSTRUZIONE per OGNI task all'avvio con una stima (_sim_cost), PRIMA
    ancora di sapere se quel task fara' mai una chiamata reale. Quella stima
    viene poi corretta al costo VERO (_apply_actual_cost_delta) SOLO per i
    task idonei alla generazione reale con adapter LLM diretto
    (editorial_plan/social_content, quando approvati in modalita' REALE — gli
    UNICI due tipi in REAL_ELIGIBLE_TYPES). Per QUALUNQUE altro task — un
    task puramente simulato come marketing_strategy, MA ANCHE un task
    content_item (la cui generazione reale passa dal laboratorio Content
    Creator e viene tracciata SOLO nel Tool Execution Gateway, mai
    riconciliata su questo stesso campo, vedi _spesa_content_creator sotto) —
    la riserva iniziale resta dentro real_cost SENZA MAI essere corretta: una
    stima mai addebitata da alcun provider (o, per content_item, addebitata
    altrove) veniva contata qui come se fosse spesa reale. La somma
    aritmetica tornava sempre (la riserva e' un numero reale nel database),
    ma la CLASSIFICAZIONE era sbagliata.

    Corretto QUI, a lettura, senza mai riscrivere il campo storico
    'real_cost' — che resta tracciabile esattamente come registrato
    all'epoca, e resta la base INVARIATA per l'enforcement del tetto
    approvato in m2/engine.py (nessuna modifica li', nessun rischio per quel
    meccanismo di sicurezza): per ciascuna execution si sottrae dal
    real_cost grezzo il costo dei task che NON sono editorial_plan/
    social_content approvati in modalita' REALE."""
    executions = await db_conn.executions.find(
        {"organization_id": org_id}, {"_id": 0, "id": 1, "plan_id": 1, "real_cost": 1}).to_list(1000)
    if not executions:
        return 0.0
    plan_ids = [e["plan_id"] for e in executions if e.get("plan_id")]
    tasks = await db_conn.tasks.find(
        {"plan_id": {"$in": plan_ids}},
        {"_id": 0, "plan_id": 1, "deliverable_type": 1, "approved_mode": 1, "cost": 1},
    ).to_list(5000) if plan_ids else []
    tasks_by_plan: dict = {}
    for t in tasks:
        tasks_by_plan.setdefault(t.get("plan_id"), []).append(t)

    totale = 0.0
    for e in executions:
        grezzo = e.get("real_cost", 0.0)
        costo_non_riconciliato = 0.0
        for t in tasks_by_plan.get(e.get("plan_id"), []):
            riconciliato_al_costo_vero = (
                t.get("deliverable_type") in REAL_ELIGIBLE_TYPES and t.get("approved_mode") == "REALE"
            )
            if not riconciliato_al_costo_vero:
                costo_non_riconciliato += t.get("cost", 0.0)
        totale += max(grezzo - costo_non_riconciliato, 0.0)
    return round(totale, 6)


class BudgetBody(BaseModel):
    general_limit: float
    daily_limit: float = 0.0


# Calcolo UNICO della spesa dell'organizzazione — usato sia da GET /budget
# sia da GET /dashboard (stats.py), che in precedenza duplicavano il conto
# in due modi diversi (uno sommava solo executions.real_cost, l'altro
# aggiungeva anche i costi di comprensione del brain): la stessa
# organizzazione mostrava due residui diversi nella stessa sessione. Un solo
# punto di calcolo, mai una seconda logica che puo' divergere di nuovo.
async def compute_spent(db_conn, org_id: str) -> dict:
    # Corretto (vedi _real_cost_per_execution_corretto sopra): la stima
    # simulata riservata per QUALUNQUE task all'avvio non resta piu' contata
    # come reale quando non e' mai stata riconciliata al costo vero.
    spent_execution = await _real_cost_per_execution_corretto(db_conn, org_id)
    # tool_cost_events e' l'UNICO registro scritto solo ed esclusivamente
    # per una chiamata reale davvero avvenuta (tools/cost_ledger.py::
    # record_cost — mai per una simulazione, mai per una stima), qualunque
    # sia l'agente/dominio che l'ha generata. E' quindi il segnale piu'
    # affidabile in assoluto per "e' stata sostenuta una spesa reale",
    # PIU' affidabile di deliverables.mode: un task reale FALLITO prima di
    # produrre un deliverable (es. content_item bloccato dopo aver gia'
    # interpellato Requesty) ha comunque un costo reale gia' registrato qui,
    # pur senza alcun deliverable REALE associato — non deve mai risultare
    # "SIMULAZIONE" solo perche' manca l'output finale.
    all_cost_events = await db_conn.tool_cost_events.find(
        {"organization_id": org_id}, {"_id": 0, "amount": 1, "agent_id": 1}).to_list(10000)
    spent_brain = round(sum(r.get("amount", 0.0) for r in all_cost_events
                            if r.get("agent_id") == "coordinatore-actelya"), 6)
    # Bug reale trovato nella stessa riconciliazione: la generazione reale di
    # content_item (laboratorio Content Creator) passa dal Tool Execution
    # Gateway (agent_id="content-creator"), MAI da executions.real_cost (vedi
    # sopra: quel campo per content_item resta la sola riserva simulata mai
    # corretta) — un commento precedente qui presumeva erroneamente che
    # fosse "gia' contata altrove" e la escludeva ESPLICITAMENTE dal totale:
    # spesa reale genuina, mai mostrata in nessun conteggio dell'organizzazione.
    spent_content_creator = round(sum(r.get("amount", 0.0) for r in all_cost_events
                                      if r.get("agent_id") == "content-creator"), 6)
    # Qualunque ALTRO agente reale (es. "content_social_revisione", la
    # revisione di una singola bozza social_content — m2/deliverable_review.py)
    # finisce qui, per costruzione, invece di essere silenziosamente escluso
    # come accadeva prima per "content-creator": un nuovo agente reale
    # aggiunto in futuro non deve MAI sparire dal totale solo perche' nessuno
    # ha ricordato di aggiungere il suo bucket qui.
    _agenti_gia_contati = {"coordinatore-actelya", "content-creator"}
    spent_altri_reali = round(sum(r.get("amount", 0.0) for r in all_cost_events
                                  if r.get("agent_id") not in _agenti_gia_contati), 6)
    spent = round(spent_execution + spent_brain + spent_content_creator + spent_altri_reali, 6)

    # Modalita' della spesa mostrata: execution.mode e' un campo storicamente
    # non affidabile (impostato a "SIMULAZIONE" alla creazione e mai
    # aggiornato quando l'esecuzione diventa reale — problema pre-esistente,
    # non risolto qui). Due segnali indipendenti e ONESTI:
    # - "e' successo qualcosa di reale" = qualunque riga in tool_cost_events
    #   (prova diretta di spesa reale, indipendente dall'esito — mai
    #   classificata "SIMULAZIONE" solo perche' un task reale e' fallito
    #   prima di produrre un deliverable) OPPURE almeno un deliverable con
    #   mode='REALE' (caso riuscito, gia' affidabile di suo);
    # - "e' successo anche qualcosa di simulato" = almeno un deliverable
    #   che NON e' mode='REALE' (un artefatto genuinamente simulato, non
    #   solo l'assenza di prova reale per quella parte).
    # Entrambi presenti insieme -> MISTA, mai un'unica etichetta che nasconde
    # l'altra componente.
    has_real_deliverable = await db_conn.deliverables.count_documents(
        {"organization_id": org_id, "mode": "REALE"}) > 0
    has_simulated_deliverable = await db_conn.deliverables.count_documents(
        {"organization_id": org_id, "mode": {"$ne": "REALE"}}) > 0
    has_real = len(all_cost_events) > 0 or has_real_deliverable
    if has_real and has_simulated_deliverable:
        mode = "MISTA"
    elif has_real:
        mode = "REALE"
    else:
        mode = "SIMULAZIONE"

    return {"spent_simulated": spent, "spent_execution": spent_execution, "spent_brain": spent_brain,
            "spent_content_creator": spent_content_creator, "spent_altri_reali": spent_altri_reali, "mode": mode}


@router.get("")
async def get_budget(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    b = await db.budgets.find_one({"id": org_id}, {"_id": 0}) or {
        "id": org_id, "general_limit": 0.0, "daily_limit": 0.0}
    speso = await compute_spent(db, org_id)
    b.update(speso)
    b["residual"] = round(b.get("general_limit", 0.0) - speso["spent_simulated"], 6)
    return b


@router.put("")
async def set_budget(body: BudgetBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    await db.budgets.update_one(
        {"id": org_id},
        {"$set": {"id": org_id, "general_limit": body.general_limit,
                  "daily_limit": body.daily_limit, "updated_at": now_iso(), "updated_by": user["id"]}},
        upsert=True,
    )
    await log_audit(org_id=org_id, user=user, action="SET_BUDGET",
                    entity_type="budget", entity_id=org_id,
                    details={"general_limit": body.general_limit, "daily_limit": body.daily_limit})
    return await get_budget(user)
