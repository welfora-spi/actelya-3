"""Milestone 2 — dispatch REALE per il task M2 'content_item' (Content
Creator). A differenza di editorial_plan/social_content (real_content.py,
generazione diretta dentro M2), il task M2 'content_item' e' un semplice
puntatore a uno o piu' content_item del laboratorio domains/content_creator,
che possiede la propria pipeline (decisione formato, generazione reale via
Requesty/Tool Execution Gateway, validazione strutturale + semantica) —
mai duplicata qui.

Principio chiave, distinto per costruzione (non solo per etichetta):
l'approvazione del PIANO autorizza la SPESA per generare bozze reali, mai
la decisione editoriale sul contenuto — questo modulo non chiama MAI
content_creator/pipeline.py::approve_content_item. Un content_item generato
resta sempre IN_ATTESA_APPROVAZIONE (bozza pronta, non approvata) finche' un
umano non agisce nel laboratorio Content Creator (endpoint gia' esistente,
invariato) — anche quando nessuna contestazione semantica e' stata
rilevata. Un task M2 'content_item' non e' mai dichiarato completato per
aver soltanto creato un content_item vuoto o inoltrato una richiesta senza
attendere il risultato, e non lo e' nemmeno se il numero di contenuti
distinti realmente prodotti e' inferiore a quello richiesto."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..domains.content_creator import pipeline as cc_pipeline
from ..domains.content_creator.pipeline import ContentCreatorError

CONTENT_ITEM_TYPE = "content_item"

# Unico codice trattato come transitorio/di rete (sicuro ritentare fino a
# MAX_ATTEMPTS, stesso principio di real_content.py). Ogni altro codice
# (config/permessi/contesto incompleto/risposta non valida/esito incerto)
# richiede intervento umano: mai un retry cieco.
_RETRY_CODES = {"rete"}

# Stessa cifra usata come estimated_cost da tool_gateway.authorize prima di
# OGNI chiamata reale (content_creator/pipeline.py::generate_content_item):
# usata qui per verificare, PRIMA di ogni item successivo al primo, che il
# costo gia' realmente sostenuto non abbia gia' eroso la riserva del task
# (task.inputs.cost, riservata atomicamente su execution.approved_cap PRIMA
# di questo dispatch — vedi m2/engine.py::_reserve_execution_budget). Un
# item che costa piu' della stima non deve mai permettere che i successivi
# continuino a spendere oltre quanto riservato per l'intero task.
_STIMA_COSTO_PER_ITEM = 0.01


@dataclass
class ContentItemOutcome:
    esito: str  # "OK" | "ERRORE"
    items: list = field(default_factory=list)  # content_items risultanti (pubblici, senza _id)
    codice_errore: Optional[str] = None
    messaggio: Optional[str] = None
    retryable: bool = False
    stima_costo_usd: float = 0.0
    requested_quantity: int = 1
    produced_count: int = 0
    contested_ids: list = field(default_factory=list)  # content_item con semantic_check CONTESTATO


async def execute_content_item_task(db, task: dict) -> ContentItemOutcome:
    override = task.get("inputs", {}).get("deliverable_override") or {}
    item_ids = override.get("content_item_ids") or []
    if not item_ids:
        return ContentItemOutcome(esito="ERRORE", codice_errore="nessun_content_item", requested_quantity=0,
                                   messaggio="Il task non referenzia alcun content_item da generare.")

    requested_quantity = len(item_ids)
    budget_residuo = float(task.get("inputs", {}).get("cost", 0.0))  # riserva atomica gia' effettuata a monte
    risultati = []
    costo_totale = 0.0
    bloccanti = []       # [(item_id, codice, messaggio)] errori tecnici non ritentabili automaticamente
    retryable_error = None  # (codice, messaggio) del primo errore di rete incontrato

    for item_id in item_ids:
        item = await db.content_items.find_one({"id": item_id}, {"_id": 0})
        if not item:
            bloccanti.append((item_id, "content_item_mancante", f"content_item '{item_id}' non trovato."))
            continue

        if item["status"] in ("BOZZA", "BLOCCATO"):
            # Il costo reale gia' sostenuto (costo_totale) puo' superare la
            # stima per-item se una generazione precedente e' costata piu'
            # del previsto: verificato PRIMA di ogni nuova chiamata, non solo
            # una volta per l'intero task — mai continuare a spendere oltre
            # quanto riservato per QUESTO task solo perche' la riserva
            # complessiva era stata approvata a monte.
            if costo_totale + _STIMA_COSTO_PER_ITEM > budget_residuo + 1e-9:
                bloccanti.append((item_id, "budget_task_esaurito",
                                  f"Riserva del task ({budget_residuo:.4f} USD) gia' esaurita dai contenuti "
                                  f"precedenti ({costo_totale:.4f} USD): nessuna nuova chiamata reale."))
                continue
            try:
                item = await cc_pipeline.generate_content_item(db, item, actor="system-auto-dispatch", user=None)
            except ContentCreatorError as exc:
                aggiornato = await db.content_items.find_one({"id": item_id}, {"_id": 0}) or item
                costo_totale += (aggiornato.get("generazione") or {}).get("stima_costo_usd") or 0.0
                if exc.code in _RETRY_CODES and retryable_error is None:
                    retryable_error = (exc.code, str(exc))
                else:
                    bloccanti.append((item_id, exc.code, str(exc)))
                continue
        costo_totale += (item.get("generazione") or {}).get("stima_costo_usd") or 0.0

        if item["status"] == "ESITO_INCERTO":
            bloccanti.append((item_id, "esito_incerto",
                              "Esito incerto dal provider reale: richiede verifica manuale nel laboratorio "
                              "Content Creator, nessun nuovo tentativo automatico."))
            continue
        if item["status"] == "BLOCCATO":
            errori = (item.get("generazione") or {}).get("errori_validazione") or []
            bloccanti.append((item_id, "validazione_bloccata", "; ".join(errori) or "Contenuto non valido."))
            continue

        # IN_ATTESA_APPROVAZIONE: bozza reale pronta. MAI approvata qui — la
        # spesa e' gia' autorizzata (approvazione del piano), la decisione
        # editoriale resta SEMPRE umana, contestata o no (Content Creator).
        risultati.append(item)

    produced = sum(1 for i in risultati if i.get("status") == "IN_ATTESA_APPROVAZIONE")
    contestati = [i["id"] for i in risultati if (i.get("semantic_check") or {}).get("status") == "CONTESTATO"]

    if retryable_error and not bloccanti and produced < requested_quantity:
        codice, msg = retryable_error
        return ContentItemOutcome(esito="ERRORE", codice_errore=codice, messaggio=msg, retryable=True,
                                   stima_costo_usd=costo_totale, items=risultati,
                                   requested_quantity=requested_quantity, produced_count=produced,
                                   contested_ids=contestati)

    if bloccanti:
        dettagli = "; ".join(f"{iid}: {c} — {m}" for iid, c, m in bloccanti)
        return ContentItemOutcome(
            esito="ERRORE", codice_errore="parziale" if produced else bloccanti[0][1],
            messaggio=f"{produced}/{requested_quantity} contenuti completati; bloccati: {dettagli}",
            stima_costo_usd=costo_totale, items=risultati,
            requested_quantity=requested_quantity, produced_count=produced, contested_ids=contestati)

    return ContentItemOutcome(esito="OK", items=risultati, stima_costo_usd=costo_totale,
                              requested_quantity=requested_quantity, produced_count=produced,
                              contested_ids=contestati)


async def resume_blocked_content_item_tasks(db):
    """Scansione di ripresa (chiamata dal worker di poll, stesso lock di
    auto_dispatch_worker_loop): un task 'content_item' BLOCCATA per un
    motivo TECNICO (non budget, non pianificazione — vedi
    blocked_reason_code) torna IN_CODA da solo quando TUTTI i suoi
    content_item non sono piu' in uno stato che richiede un nuovo tentativo
    (BOZZA/BLOCCATO/ESITO_INCERTO) — es. un umano ha corretto/rigenerato
    l'item bloccato direttamente nel laboratorio Content Creator. Al
    prossimo giro il dispatch normale (execute_content_item_task) salta
    SEMPRE gli item gia' IN_ATTESA_APPROVAZIONE/APPROVATO (mai una
    rigenerazione o un riaddebito di cio' che e' gia' pronto)."""
    ripresi = []
    async for task in db.tasks.find({
        "deliverable_type": CONTENT_ITEM_TYPE, "task_status": "BLOCCATA",
        # Stesso marcatore di auto_dispatch_worker_loop: mai un piano
        # storico (approvato prima di questa correzione, quindi privo del
        # marcatore) ripreso automaticamente, indipendentemente dal motivo
        # del blocco.
        "auto_dispatch_requested_at": {"$exists": True},
        "blocked_reason_code": {"$in": ["esito_incerto", "validazione_bloccata", "content_item_mancante"]},
    }):
        item_ids = (task.get("inputs", {}).get("deliverable_override") or {}).get("content_item_ids") or []
        if not item_ids:
            continue
        items = await db.content_items.find({"id": {"$in": item_ids}}).to_list(len(item_ids))
        if len(items) != len(item_ids):
            continue  # un id referenziato non esiste piu': non riprendere alla cieca
        if any(i["status"] in ("BOZZA", "BLOCCATO", "ESITO_INCERTO") for i in items):
            continue  # ancora almeno un item che richiede un nuovo tentativo: non ancora pronto
        await db.tasks.update_one(
            {"id": task["id"], "task_status": "BLOCCATA"},  # riconferma atomica dello stato prima di riattivare
            {"$set": {"task_status": "IN_CODA", "lease_owner": None,
                     "warnings": task.get("warnings", []) + [
                         "Ripreso automaticamente: i contenuti bloccati sono stati risolti nel laboratorio "
                         "Content Creator."]}},
        )
        ripresi.append(task["id"])
    return ripresi
