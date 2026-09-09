"""Revisione editoriale UMANA sulle singole bozze di un deliverable M2
multi-bozza (oggi: social_content -> array "posts"). Distinta per costruzione
dai revisori automatici non distruttivi di reviews.py (compliance_reviewer/
auditor: findings di sola lettura, deterministici, mai una decisione) — qui
invece si persiste la decisione di una PERSONA (Approva/Rifiuta/Richiedi
modifica), associata a deliverable+bozza+VERSIONE esatti, con autore, data e
motivazione quando richiesta.

Bug reale colmato in prova (2026-09-09, piano plan-c632efad5881492ea9fe): il
ramo "social_content" (capability "social", distinto da content_item) non
aveva ALCUN meccanismo di decisione post-generazione — solo content_item
(laboratorio Content Creator) lo aveva.

Ogni bozza ha ora una propria CATENA DI VERSIONI, indipendente dalle altre
bozze dello stesso deliverable e indipendente dalla versione del deliverable
M2 stesso (che resta uno storico immutabile, mai riscritto — stesso
principio di content_creator/pipeline.py e di
engine.py::enrich_content_item_deliverables_live): la versione 1 di ogni
bozza E' il contenuto originale del deliverable; una versione successiva
nasce SOLO da una richiesta di modifica applicata esplicitamente (mai
automaticamente), vive in una collezione separata (deliverable_item_versions)
e non tocca ne' il deliverable ne' le altre bozze. Una decisione e' terminale
SOLO per la versione a cui si riferisce: non impedisce mai di decidere una
versione successiva della STESSA bozza."""
from pymongo.errors import DuplicateKeyError

from ..models import new_id, now_iso

# Deliverable_type -> nome del campo array che contiene le bozze indipendenti.
# Solo social_content oggi: editorial_plan e' un unico documento strategico
# interno (calendario/pillar), mai una "bozza" consegnata all'utente da
# approvare singolarmente. Estendibile in futuro senza toccare la logica sotto.
MULTI_ITEM_FIELD = {"social_content": "posts"}

DECISIONE_APPROVATO = "APPROVATO"
DECISIONE_RIFIUTATO = "RIFIUTATO"
DECISIONE_MODIFICA_RICHIESTA = "MODIFICA_RICHIESTA"
DECISIONI_VALIDE = {DECISIONE_APPROVATO, DECISIONE_RIFIUTATO, DECISIONE_MODIFICA_RICHIESTA}
STATO_IN_ATTESA_REVISIONE = "IN_ATTESA_REVISIONE"
# Tutte e tre le decisioni sono terminali per la VERSIONE a cui si
# riferiscono (mai per la bozza in assoluto): una richiesta di modifica
# applicata produce una versione successiva, con una decisione propria,
# libera dal vincolo della precedente.
STATI_TERMINALI = DECISIONI_VALIDE


class DecisionError(ValueError):
    """Errore applicativo (dati invalidi, transizione non consentita, versione
    superata, decisione duplicata, conferma mancante): sempre un 4xx per il
    chiamante HTTP, mai un errore interno generico."""


def campo_bozze(deliverable_type: str):
    return MULTI_ITEM_FIELD.get(deliverable_type)


def _numero_bozze(deliverable: dict) -> int:
    campo = campo_bozze(deliverable.get("deliverable_type"))
    if not campo:
        return 0
    return len((deliverable.get("content") or {}).get(campo) or [])


def _contenuto_originale_item(deliverable: dict, item_index: int) -> dict:
    campo = campo_bozze(deliverable.get("deliverable_type"))
    lista = (deliverable.get("content") or {}).get(campo) or []
    return dict(lista[item_index]) if 0 <= item_index < len(lista) else {}


async def _versioni_item(db, deliverable_id: str, item_index: int) -> list[dict]:
    """Tutte le versioni >= 2 di una bozza (la versione 1 e' sempre il
    contenuto originale del deliverable, non duplicato qui), ordinate."""
    return await db.deliverable_item_versions.find(
        {"deliverable_id": deliverable_id, "item_index": item_index}, {"_id": 0},
    ).sort("version", 1).to_list(50)


async def _decisione(db, deliverable_id: str, item_index: int, version: int) -> dict:
    rec = await db.deliverable_item_decisions.find_one(
        {"deliverable_id": deliverable_id, "item_index": item_index, "version": version}, {"_id": 0})
    return rec or {
        "id": None, "deliverable_id": deliverable_id, "item_index": item_index, "version": version,
        "status": STATO_IN_ATTESA_REVISIONE, "decided_by": None, "decided_at": None, "reason": None, "history": [],
    }


async def get_item_state(db, deliverable: dict, item_index: int) -> dict:
    """Stato completo e leggibile di UNA bozza: versione corrente, suo
    contenuto, sua decisione, e lo storico di TUTTE le versioni precedenti
    con la decisione che ciascuna ha ricevuto — nulla sparisce mai da una
    modifica successiva."""
    versioni_extra = await _versioni_item(db, deliverable["id"], item_index)
    n_totale = 1 + len(versioni_extra)  # versione 1 (originale) + eventuali successive
    storico = []
    for v in range(1, n_totale):  # tutte tranne la corrente
        contenuto_v = (_contenuto_originale_item(deliverable, item_index) if v == 1
                       else next(x["content"] for x in versioni_extra if x["version"] == v))
        meta_v = ({} if v == 1 else next(x for x in versioni_extra if x["version"] == v))
        decisione_v = await _decisione(db, deliverable["id"], item_index, v)
        storico.append({
            "version": v, "content": contenuto_v, "source": meta_v.get("source", "originale"),
            "edit_note": meta_v.get("edit_note"), "mode": meta_v.get("mode"),
            "generation": meta_v.get("generation"), "created_by": meta_v.get("created_by"),
            "created_at": meta_v.get("created_at"), "decision": decisione_v,
        })
    versione_corrente = n_totale
    if versione_corrente == 1:
        contenuto_corrente = _contenuto_originale_item(deliverable, item_index)
        meta_corrente = {"source": "originale"}
    else:
        meta_corrente = next(x for x in versioni_extra if x["version"] == versione_corrente)
        contenuto_corrente = meta_corrente["content"]
    decisione_corrente = await _decisione(db, deliverable["id"], item_index, versione_corrente)
    return {
        "item_index": item_index, "current_version": versione_corrente, "content": contenuto_corrente,
        "source": meta_corrente.get("source", "originale"), "edit_note": meta_corrente.get("edit_note"),
        "decision": decisione_corrente, "history": storico,
    }


async def get_item_decisions(db, deliverable: dict) -> list[dict]:
    """Stato editoriale corrente (versione corrente + storico) per ciascuna
    bozza del deliverable passato. Bozze mai decise tornano esplicitamente
    IN_ATTESA_REVISIONE, mai omesse o assunte approvate."""
    n = _numero_bozze(deliverable)
    if n == 0:
        return []
    return [await get_item_state(db, deliverable, i) for i in range(n)]


def _valida_bozza_decidibile(deliverable: dict, item_index: int) -> int:
    if deliverable.get("deliverable_type") not in MULTI_ITEM_FIELD:
        raise DecisionError(
            f"Il deliverable_type {deliverable.get('deliverable_type')!r} non ha bozze indipendenti da decidere.")
    if not deliverable.get("is_current"):
        raise DecisionError(
            "Questa versione del deliverable non è più quella corrente: nessuna decisione su una versione superata.")
    n = _numero_bozze(deliverable)
    if not isinstance(item_index, int) or item_index < 0 or item_index >= n:
        raise DecisionError(f"Indice bozza fuori intervallo (0-{max(n - 1, 0)}).")
    return n


async def decide_item(db, *, org_id, plan_id, deliverable, item_index, decision, actor, reason=None):
    """Registra UNA decisione umana sulla versione CORRENTE di UNA bozza. Mai
    una generazione/rigenerazione: solo persistenza. Solleva DecisionError
    (mai un'eccezione generica) per ogni condizione non valida."""
    _valida_bozza_decidibile(deliverable, item_index)
    if decision not in DECISIONI_VALIDE:
        raise DecisionError(f"Decisione non valida: {decision!r}.")
    motivo = (reason or "").strip() or None
    if decision in (DECISIONE_RIFIUTATO, DECISIONE_MODIFICA_RICHIESTA) and not motivo:
        raise DecisionError("Motivazione obbligatoria per rifiuto o richiesta di modifica.")

    stato = await get_item_state(db, deliverable, item_index)
    versione = stato["current_version"]
    esistente = stato["decision"] if stato["decision"].get("id") else None
    if esistente and esistente.get("status") in STATI_TERMINALI:
        raise DecisionError(
            f"Questa versione ({versione}) è già stata decisa ({esistente['status']} da "
            f"{esistente.get('decided_by')} il {esistente.get('decided_at')}): decisione duplicata non consentita.")

    now = now_iso()
    voce_storico = {"decision": decision, "actor": actor, "at": now, "reason": motivo}
    if esistente:
        await db.deliverable_item_decisions.update_one(
            {"id": esistente["id"]},
            {"$set": {"status": decision, "decided_by": actor, "decided_at": now, "reason": motivo},
             "$push": {"history": voce_storico}},
        )
        rec_id = esistente["id"]
    else:
        rec_id = new_id("delivdecision")
        try:
            await db.deliverable_item_decisions.insert_one({
                "id": rec_id, "organization_id": org_id, "plan_id": plan_id,
                "deliverable_id": deliverable["id"], "deliverable_version": deliverable.get("version"),
                "task_id": deliverable.get("task_id"), "deliverable_type": deliverable.get("deliverable_type"),
                "item_index": item_index, "version": versione, "status": decision, "decided_by": actor,
                "decided_at": now, "reason": motivo, "history": [voce_storico], "created_at": now,
            })
        except DuplicateKeyError:
            gia_scritta = await db.deliverable_item_decisions.find_one(
                {"deliverable_id": deliverable["id"], "item_index": item_index, "version": versione})
            raise DecisionError(
                f"Decisione già registrata in una richiesta concorrente "
                f"({(gia_scritta or {}).get('status')} da {(gia_scritta or {}).get('decided_by')}).")
    rec = await db.deliverable_item_decisions.find_one({"id": rec_id}, {"_id": 0})
    return rec


async def preview_edit_cost(deliverable: dict, item_index: int) -> dict:
    """SOLA stima (mai un addebito): costo previsto per rigenerare UNA sola
    bozza, calcolato come quota proporzionale della stessa formula di
    preventivo del task social_content (domains/estimator.py) — mai una
    cifra inventata a parte, coerente con quanto gia' mostrato in
    approvazione del piano."""
    from ..domains.estimator import estimate_for_agents
    from .agents_registry import AGENT_CONTRACTS
    n = _valida_bozza_decidibile(deliverable, item_index)
    stima_task = estimate_for_agents(["content_social"], AGENT_CONTRACTS)
    quota = 1.0 / max(n, 1)
    margine = stima_task["safety_margin"]
    cost_probable = round(stima_task["cost_probable"] * quota, 6)
    cost_max = round(stima_task["cost_max"] * quota * (1 + margine), 6)
    return {
        "item_index": item_index, "cost_probable": cost_probable, "cost_max": cost_max,
        "currency": "USD", "safety_margin": margine, "mode": "SIMULAZIONE",
    }


def _applica_modifica_simulata(contenuto: dict, nota: str) -> dict:
    """Percorso SIMULATO (nessuna chiamata reale, nessun costo): applica la
    nota di modifica in modo deterministico e chiaramente dichiarato tale —
    mai spacciato per una revisione reale basata su fatti verificati."""
    nuovo = dict(contenuto)
    corpo = nuovo.get("body") or ""
    nuovo["body"] = f"{corpo} [SIMULATO — revisione secondo la richiesta: {nota}]".strip()
    return nuovo


async def apply_edit(db, *, org_id, plan_id, deliverable, item_index, actor, confirm: bool) -> dict:
    """Applica la richiesta di modifica CORRENTE di una bozza, producendo una
    NUOVA VERSIONE indipendente — mai riscrive la versione precedente (resta
    consultabile in 'history' con la sua decisione), mai tocca le altre
    bozze dello stesso deliverable, mai approva automaticamente la nuova
    versione (nasce sempre IN_ATTESA_REVISIONE). Richiede confirm=True:
    stessa autorizzazione applicativa esplicita PRIMA di ogni chiamata a
    pagamento gia' usata altrove (content_creator/pipeline.py::generate,
    '?confirm=true'); una richiesta di modifica da sola non avvia MAI
    questa funzione."""
    if not confirm:
        raise DecisionError(
            "Conferma esplicita richiesta prima di applicare una modifica (può comportare una spesa reale).")
    _valida_bozza_decidibile(deliverable, item_index)
    stato = await get_item_state(db, deliverable, item_index)
    if stato["decision"].get("status") != DECISIONE_MODIFICA_RICHIESTA:
        raise DecisionError(
            "Solo una bozza con una richiesta di modifica in attesa (nella sua versione corrente) può essere "
            "aggiornata a una nuova versione.")
    nota = stato["decision"].get("reason") or ""
    contenuto_attuale = stato["content"]
    nuova_versione = stato["current_version"] + 1

    from .real_content import REAL_ELIGIBLE_TYPES, check_readiness, generate_social_content_item_revision
    from ..tools import cost_ledger

    reale_idoneo = (deliverable.get("mode") == "REALE"
                    and deliverable.get("deliverable_type") in REAL_ELIGIBLE_TYPES)
    modo = "SIMULAZIONE"
    generazione = None
    if reale_idoneo:
        readiness = await check_readiness(db, org_id)
        if readiness.pronto:
            stima = await preview_edit_cost(deliverable, item_index)
            stima_preflight = stima["cost_max"]
            riservato, motivo_budget = await cost_ledger.reserve_budget(
                db, org_id=org_id, tool_id="requesty_llm", estimated_cost=stima_preflight)
            if not riservato:
                raise DecisionError(f"Budget: {motivo_budget}")
            try:
                esito = await generate_social_content_item_revision(
                    db, org_id, readiness.ref, contenuto_attuale, nota)
            except Exception:
                await cost_ledger.release_reservation(db, org_id=org_id, estimated_cost=stima_preflight)
                raise
            if esito.esito != "OK":
                # La chiamata e' comunque partita: se un costo reale e' noto
                # (token restituiti), va registrato SEMPRE, indipendentemente
                # dall'esito (mai una spesa reale classificata come mai
                # avvenuta solo perche' il risultato non era utilizzabile).
                if esito.stima_costo_usd is not None:
                    await cost_ledger.record_cost(
                        db, org_id=org_id, tool_id="requesty_llm", agent_id="content_social_revisione",
                        amount=esito.stima_costo_usd)
                    await cost_ledger.reconcile_reservation(db, org_id=org_id, estimated_cost=stima_preflight)
                else:
                    await cost_ledger.release_reservation(db, org_id=org_id, estimated_cost=stima_preflight)
                raise DecisionError(f"Generazione reale non riuscita ({esito.codice_errore}): {esito.messaggio}")
            await cost_ledger.record_cost(
                db, org_id=org_id, tool_id="requesty_llm", agent_id="content_social_revisione",
                amount=esito.stima_costo_usd or 0.0)
            await cost_ledger.reconcile_reservation(db, org_id=org_id, estimated_cost=stima_preflight)
            modo = "REALE"
            nuovo_contenuto = esito.content
            generazione = {
                "provider": esito.provider, "modello_effettivo": esito.modello_effettivo,
                "input_tokens": esito.input_tokens, "output_tokens": esito.output_tokens,
                "stima_costo_usd": esito.stima_costo_usd,
            }
        else:
            nuovo_contenuto = _applica_modifica_simulata(contenuto_attuale, nota)
    else:
        nuovo_contenuto = _applica_modifica_simulata(contenuto_attuale, nota)

    now = now_iso()
    doc = {
        "id": new_id("delivitemver"), "organization_id": org_id, "plan_id": plan_id,
        "deliverable_id": deliverable["id"], "item_index": item_index, "version": nuova_versione,
        "content": nuovo_contenuto, "source": "modifica_editoriale", "edit_note": nota, "mode": modo,
        "generation": generazione, "based_on_version": nuova_versione - 1,
        "created_by": actor, "created_at": now,
    }
    try:
        await db.deliverable_item_versions.insert_one(doc)
    except DuplicateKeyError:
        raise DecisionError("Una nuova versione per questa bozza è già stata applicata in una richiesta concorrente.")
    doc.pop("_id", None)
    return doc


async def enrich_multi_item_deliverables_with_decisions(db, deliverables: list) -> list:
    """Aggiunge, SENZA modificare il deliverable stesso (storico immutabile),
    un campo 'item_decisions' con lo stato editoriale corrente + lo storico
    di ciascuna bozza — stesso principio di sola-lettura-arricchita gia'
    usato per content_item in engine.py::enrich_content_item_deliverables_live."""
    for d in deliverables:
        if campo_bozze(d.get("deliverable_type")):
            d["item_decisions"] = await get_item_decisions(db, d)
    return deliverables
