"""Content Creator — orchestrazione completa: decisione del contenuto da
produrre (decision.py), generazione reale via Requesty passando SEMPRE dal
Tool Execution Gateway (app/tools/gateway.py — mai un aggiramento), validazione
strutturale (validation.py) e semantica anti-allucinazione (domains/reel_semantic.py,
riusata, mai duplicata), versionamento, approvazione, e collegamento con asset
multimediali reali prodotti da domains/reel.py (video) e domains/flyer.py
(immagine) — mai una duplicazione della loro logica, solo un aggancio di stato.

Nessun contenuto e' MAI dichiarato pronto senza superare la validazione
strutturale; un timeout/esito incerto produce ESITO_INCERTO, mai un
contenuto inventato per non bloccare il flusso."""
from __future__ import annotations

import json
import logging
from typing import Optional

from ...integrations import requesty_gateway
from ...integrations.requesty_gateway import RequestyErroreSanificato, RequestyNonConfigurato
from ...models import new_id, now_iso
from ...tools import gateway as tool_gateway
from ...tools.gateway import ToolGatewayError
from ..estimator import PRICE_PER_TOKEN
from ..knowledge import current_facts_map
from ..reel_semantic import semantic_validate_generic_content
from . import decision
from .models import MEDIA_DEPENDENT_TYPES
from .validation import CONTENT_SCHEMA, campi_testuali_per_validazione_semantica, validate_content

logger = logging.getLogger("actelya.content_creator")

AGENT_ID = "content-creator"
TOOL_ID = "requesty_llm"
MAX_TOKENS_DEFAULT = 900
REQUIRED_ORG_FIELDS = ("ragione_sociale", "settore")


class ContentCreatorError(Exception):
    """Rifiuto esplicito della pipeline — sempre con un `code` stabile."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


async def _company_context(db, org_id: str) -> tuple[dict, list[str]]:
    """Identica nello spirito a domains/reel.py::_company_context (stesso
    Fact Ledger, stessa priorità DICHIARATO/ESTRATTO/VERIFICATO): mai un
    valore inventato, solo ciò che è già dichiarato/estratto/verificato."""
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0}) or {}
    facts = await current_facts_map(db, org_id)
    contesto = {
        "ragione_sociale": org.get("ragione_sociale") or "",
        "nome_commerciale": org.get("nome_commerciale") or "",
        "settore": org.get("settore") or facts.get("settore", {}).get("value", ""),
        "sito_web": org.get("sito_web") or facts.get("sito_web", {}).get("value", ""),
        "obiettivi_commerciali": org.get("obiettivi_commerciali") or facts.get("obiettivi_commerciali", {}).get("value", ""),
    }
    for extra_field in ("prodotto", "pubblico_target", "tono_di_voce"):
        if extra_field in facts:
            contesto[extra_field] = facts[extra_field]["value"]
    mancanti = [f for f in REQUIRED_ORG_FIELDS if not (contesto.get(f) or "").strip()]
    return contesto, mancanti


async def _ai_real_mode_attivo(db, org_id: str) -> bool:
    settings = await db.settings.find_one({"id": org_id}) or {}
    return bool(settings.get("ai_real_mode"))


async def _requesty_connection(db, org_id: str) -> Optional[dict]:
    return await db.ai_connections.find_one(
        {"organization_id": org_id, "provider_type": "requesty", "verified": True, "active": True}, {"_id": 0},
    )


async def create_content_item(db, *, org_id: str, actor: str, objective: str, channel: str, funnel_stage: str,
                              content_type: Optional[str], campaign_id: Optional[str], tone_override: Optional[str],
                              constraints: str, brief: str, quantity: int = 1) -> dict:
    """Decide (decision.py) quale/i tipo/i di contenuto produrre e crea un
    content_item BOZZA per ciascuno — la decisione stessa è persistita
    (motivazione_tipo), mai un'inferenza silenziosa e irripetibile.

    'quantity' (default 1, comportamento invariato per ogni chiamante
    esistente): quanti content_item DISTINTI creare (una generazione reale
    indipendente ciascuno — mai un solo item con N varianti interne spacciate
    per N contenuti separati). Tutti gli item della stessa richiesta
    condividono 'content_group_id'/'content_group_size', cosi' il chiamante
    puo' verificare quanti sono stati davvero prodotti rispetto al
    richiesto."""
    piano = decision.decide_content_plan(
        channel=channel, funnel_stage=funnel_stage, explicit_type=content_type, quantity=quantity)
    group_id = new_id("contentgroup")
    group_size = len(piano["content_types"])
    creati = []
    for indice, tipo in enumerate(piano["content_types"], start=1):
        brief_effettivo = brief
        if group_size > 1:
            brief_effettivo = (
                f"{brief}\n\n(Questo e' il contenuto {indice} di {group_size} richiesti: deve essere "
                "chiaramente distinto dagli altri per angolo/apertura/esempio, non una riformulazione minima.)"
            )
        rec = {
            "id": new_id("content"), "organization_id": org_id, "content_type": tipo,
            "objective": objective, "channel": channel, "funnel_stage": funnel_stage,
            "campaign_id": campaign_id, "tone_override": tone_override, "constraints": constraints,
            "brief": brief_effettivo, "motivazione_tipo": piano["motivazione"], "tono_suggerito": piano["tono_suggerito"],
            "content_group_id": group_id, "content_group_size": group_size, "content_group_index": indice,
            "status": "BOZZA", "content": None, "generazione": {}, "nota_revisione": None,
            "semantic_check": {"status": "NON_VERIFICATO", "affermazioni_contestate": []},
            "approved": False, "approved_by": None, "approved_at": None,
            "media_link": None,
            "history": [{"at": now_iso(), "status": "BOZZA", "actor": actor, "motivo": "Creato"}],
            "created_by": actor, "created_at": now_iso(), "updated_at": now_iso(),
        }
        await db.content_items.insert_one(rec)
        rec.pop("_id", None)
        creati.append(rec)
    return {"content_types_decisi": piano["content_types"], "motivazione": piano["motivazione"], "items": creati,
            "content_group_id": group_id, "content_group_size": group_size}


async def generate_content_item(db, item: dict, *, actor: str, user: Optional[dict] = None) -> dict:
    """Genera davvero il contenuto (Requesty, via Tool Execution Gateway),
    valida struttura + semantica, e porta l'item allo stato successivo
    corretto. Solleva ContentCreatorError con un codice esplicito su ogni
    rifiuto — mai un'esecuzione silenziosa o un contenuto inventato."""
    org_id = item["organization_id"]
    if item["status"] not in ("BOZZA", "BLOCCATO"):
        raise ContentCreatorError("STATO_NON_VALIDO", f"Impossibile generare dallo stato attuale: {item['status']}.")

    if not await _ai_real_mode_attivo(db, org_id):
        raise ContentCreatorError("AI_NON_REALE", "Modalità AI REALE non attiva per questa organizzazione (Impostazioni).")

    try:
        await tool_gateway.authorize(
            db, org_id=org_id, agent_id=AGENT_ID, tool_id=TOOL_ID,
            approved=True, estimated_cost=0.01, user=user, actor=actor,
        )
    except ToolGatewayError as exc:
        raise ContentCreatorError(exc.code, str(exc)) from exc

    conn = await _requesty_connection(db, org_id)
    if not conn or not (conn.get("effective_model") or "").strip():
        raise ContentCreatorError(
            "CONFIGURAZIONE_INCOMPLETA",
            "Connessione Requesty verificata ma senza 'modello effettivo' configurato (Connessioni e API).",
        )

    contesto, mancanti = await _company_context(db, org_id)
    if mancanti:
        raise ContentCreatorError(
            "CONTESTO_INCOMPLETO", f"Informazioni aziendali mancanti nel Fact Ledger: {', '.join(mancanti)}.",
        )

    tipo = item["content_type"]

    def _campo(chiave):
        return contesto.get(chiave, "") or "informazione non disponibile"

    system = (
        "Sei l'agente Content Creator di ACTELYA. REGOLA ASSOLUTA, più importante di ogni altra: usa "
        "ESCLUSIVAMENTE le informazioni aziendali fornite nel messaggio utente. Non inventare MAI nome, "
        "prodotto, caratteristiche, benefici, prezzi, pubblico target o promesse non esplicitamente "
        "indicati: se un'informazione è 'informazione non disponibile', resta generico e onesto invece di "
        "inventare un dettaglio. Rispondi SOLO con un oggetto JSON conforme allo schema richiesto, in "
        "italiano, sintetico in ogni campo."
    )
    messaggio = (
        f"Tipo di contenuto da produrre: {tipo}\n"
        f"Obiettivo: {item['objective']}\n"
        f"Canale: {item['channel']}\n"
        f"Fase di funnel: {item['funnel_stage']}\n"
        f"Tono suggerito: {item.get('tone_override') or item.get('tono_suggerito') or 'neutro'}\n"
        f"Ragione sociale: {_campo('ragione_sociale')}\n"
        f"Settore: {_campo('settore')}\n"
        f"Prodotto: {_campo('prodotto')}\n"
        f"Pubblico target: {_campo('pubblico_target')}\n"
        f"Tono di voce del brand: {_campo('tono_di_voce')}\n"
        f"Vincoli: {item.get('constraints') or 'nessuno'}\n"
        f"Brief aggiuntivo: {item.get('brief') or 'nessuno'}\n"
        + (f"Richiesta di modifica rispetto a un tentativo precedente (tienine conto): {item.get('nota_revisione')}\n"
           if item.get("nota_revisione") else "")
        + "\nGenera, in un unico oggetto JSON: titolo (stringa vuota se non pertinente al tipo), corpo del "
          "testo, call to action (stringa vuota se non pertinente), da 0 a 6 hashtag pertinenti, almeno una "
          "variante alternativa del corpo in 'varianti'."
    )

    await db.content_items.update_one({"id": item["id"]}, {"$set": {"status": "GENERAZIONE_IN_CORSO", "updated_at": now_iso()}})

    try:
        risultato = requesty_gateway.genera_json(
            model_id_requesty=conn["effective_model"], system=system, messaggio_utente=messaggio,
            schema_json=CONTENT_SCHEMA, schema_nome="actelya_content_item",
            max_tokens=conn.get("max_tokens") or MAX_TOKENS_DEFAULT, timeout=conn.get("timeout") or 60,
        )
    except RequestyNonConfigurato as exc:
        await db.content_items.update_one({"id": item["id"]}, {"$set": {
            "status": "BLOCCATO",
            "generazione": {"ultimo_errore_codice": "credenziale_assente", "ultimo_errore_messaggio": str(exc)},
            "updated_at": now_iso(),
        }})
        await tool_gateway.record_execution(db, org_id=org_id, tool_id=TOOL_ID, agent_id=AGENT_ID,
                                            outcome="BLOCCATO", user=user, actor=actor)
        raise ContentCreatorError("credenziale_assente", str(exc)) from exc
    except RequestyErroreSanificato as exc:
        nuovo_stato = "ESITO_INCERTO" if exc.codice == "esito_incerto" else "BLOCCATO"
        await db.content_items.update_one({"id": item["id"]}, {"$set": {
            "status": nuovo_stato,
            "generazione": {"ultimo_errore_codice": exc.codice, "ultimo_errore_messaggio": exc.messaggio},
            "updated_at": now_iso(),
        }})
        await tool_gateway.record_execution(db, org_id=org_id, tool_id=TOOL_ID, agent_id=AGENT_ID,
                                            outcome=nuovo_stato, user=user, actor=actor)
        raise ContentCreatorError(exc.codice, exc.messaggio) from exc

    # La chiamata e' gia' partita ed e' stata risposta: va sempre contabilizzata,
    # indipendentemente da cosa succede dopo (JSON non valido, validazione bloccata).
    stima_costo = round(((risultato.input_tokens or 0) + (risultato.output_tokens or 0)) * PRICE_PER_TOKEN, 6)
    await tool_gateway.record_execution(db, org_id=org_id, tool_id=TOOL_ID, agent_id=AGENT_ID,
                                        actual_cost=stima_costo, outcome="OK", user=user, actor=actor)

    try:
        contenuto = json.loads(risultato.testo)
    except (json.JSONDecodeError, TypeError):
        await db.content_items.update_one({"id": item["id"]}, {"$set": {
            "status": "BLOCCATO",
            "generazione": {"ultimo_errore_codice": "risposta_non_valida",
                           "ultimo_errore_messaggio": "Risposta non è un JSON valido.",
                           "modello_effettivo": risultato.modello_effettivo,
                           "input_tokens": risultato.input_tokens, "output_tokens": risultato.output_tokens,
                           "stima_costo_usd": stima_costo, "troncata": risultato.troncata,
                           "errori_validazione": ["Risposta non è un JSON valido."]},
            "updated_at": now_iso(),
        }})
        raise ContentCreatorError("risposta_non_valida", "La risposta di Requesty non è un JSON valido.")

    if risultato.troncata:
        validazione = {
            "status": "BLOCCATO",
            "errors": ["Risposta troncata: il limite di token è stato raggiunto. Aumenta 'Max token' sulla "
                      "connessione Requesty o riprova."],
            "warnings": [],
        }
    else:
        validazione = validate_content(tipo, contenuto)

    semantic_check = {"status": "NON_VERIFICATO", "affermazioni_contestate": []}
    if validazione["status"] == "COMPLETATO":
        semantic_check = semantic_validate_generic_content(
            campi_testuali_per_validazione_semantica(contenuto), contesto, item.get("brief", ""),
        )

    nuovo_stato = "IN_ATTESA_APPROVAZIONE" if validazione["status"] == "COMPLETATO" else "BLOCCATO"

    await db.content_items.update_one(
        {"id": item["id"]},
        {"$set": {
            "status": nuovo_stato, "content": contenuto, "semantic_check": semantic_check,
            "generazione": {"modello_effettivo": risultato.modello_effettivo, "input_tokens": risultato.input_tokens,
                           "output_tokens": risultato.output_tokens, "stima_costo_usd": stima_costo,
                           "troncata": risultato.troncata, "errori_validazione": validazione["errors"]},
            "updated_at": now_iso(),
        }, "$push": {"history": {"at": now_iso(), "status": nuovo_stato, "actor": actor}}},
    )
    return await db.content_items.find_one({"id": item["id"]}, {"_id": 0})


async def approve_content_item(db, item: dict, *, actor: str, approve: bool, note: str) -> dict:
    """Approva o rifiuta un contenuto in IN_ATTESA_APPROVAZIONE. Un contenuto
    approvato che dipende da un asset multimediale reale (MEDIA_DEPENDENT_TYPES)
    passa a IN_ATTESA_ASSET (mai dichiarato COMPLETATO senza l'asset vero);
    altrimenti diventa APPROVATO, deliverable finale."""
    if item["status"] != "IN_ATTESA_APPROVAZIONE":
        raise ValueError(f"Approvabile solo da IN_ATTESA_APPROVAZIONE (stato attuale: {item['status']}).")
    if not approve:
        nuovo_stato = "RIFIUTATO"
    elif item["content_type"] in MEDIA_DEPENDENT_TYPES:
        nuovo_stato = "IN_ATTESA_ASSET"
    else:
        nuovo_stato = "APPROVATO"
    await db.content_items.update_one(
        {"id": item["id"]},
        {"$set": {"status": nuovo_stato, "approved": approve, "approved_by": actor, "approved_at": now_iso(),
                  "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "status": nuovo_stato, "actor": actor, "motivo": note}}},
    )
    return await db.content_items.find_one({"id": item["id"]}, {"_id": 0})


async def request_revision(db, item: dict, *, actor: str, note: str) -> dict:
    """Richiede una modifica: fotografa la versione corrente (mai persa) e
    riporta l'item a BOZZA, pronto per una nuova generazione che tenga conto
    della nota — stesso pattern di domains/reel.py::_snapshot_content_version."""
    if item["status"] not in ("IN_ATTESA_APPROVAZIONE", "RIFIUTATO", "BLOCCATO", "APPROVATO", "IN_ATTESA_ASSET"):
        raise ValueError(f"Richiesta di modifica non applicabile allo stato attuale: {item['status']}.")
    ultimo = await db.content_item_versions.find_one({"content_item_id": item["id"]}, sort=[("version", -1)])
    versione = (ultimo["version"] + 1) if ultimo else 1
    await db.content_item_versions.insert_one({
        "id": new_id("contentver"), "organization_id": item["organization_id"], "content_item_id": item["id"],
        "version": versione, "content": item.get("content"), "generazione": item.get("generazione"),
        "semantic_check": item.get("semantic_check"),
        "nota_revisione_che_ha_portato_alla_modifica": note, "superseded_at": now_iso(), "created_by": actor,
    })
    await db.content_items.update_one(
        {"id": item["id"]},
        {"$set": {"status": "BOZZA", "nota_revisione": note, "approved": False, "approved_by": None,
                  "approved_at": None, "media_link": None, "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "status": "BOZZA", "actor": actor, "motivo": f"Richiesta modifica: {note}"}}},
    )
    return await db.content_items.find_one({"id": item["id"]}, {"_id": 0})


async def resolve_uncertain(db, item: dict, *, actor: str, note: str = "") -> dict:
    if item["status"] != "ESITO_INCERTO":
        raise ValueError(f"Risolvibile solo da ESITO_INCERTO (stato attuale: {item['status']}).")
    await db.content_items.update_one(
        {"id": item["id"]},
        {"$set": {"status": "BOZZA", "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "status": "BOZZA", "actor": actor,
                               "motivo": note or "Esito incerto risolto manualmente: si può rigenerare"}}},
    )
    return await db.content_items.find_one({"id": item["id"]}, {"_id": 0})


async def link_media_project(db, item: dict, *, kind: str, project_id: str, actor: str) -> dict:
    """Collega il content_item a un progetto reale (domains/reel.py per
    video, domains/flyer.py per immagine) — mai la creazione di quel
    progetto qui: la creazione resta responsabilità del laboratorio
    corrispondente, questo è solo l'aggancio di stato."""
    if item["status"] != "IN_ATTESA_ASSET":
        raise ValueError(f"Collegamento asset possibile solo da IN_ATTESA_ASSET (stato attuale: {item['status']}).")
    if kind not in ("reel", "flyer"):
        raise ValueError(f"Tipo di progetto multimediale sconosciuto: '{kind}'.")
    await db.content_items.update_one(
        {"id": item["id"]},
        {"$set": {"media_link": {"kind": kind, "project_id": project_id}, "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "status": item["status"], "actor": actor,
                               "motivo": f"Collegato progetto {kind}:{project_id}"}}},
    )
    return await sync_media_status(db, item["id"])


async def sync_media_status(db, item_id: str) -> dict:
    """Interroga (sola lettura) lo stato del progetto multimediale collegato
    e completa il content_item SOLO se l'asset è davvero pronto (URL
    riproducibile) — mai un completamento dichiarato senza quella conferma.
    Richiamabile più volte (idempotente): se l'asset non è ancora pronto,
    l'item resta IN_ATTESA_ASSET senza errore."""
    item = await db.content_items.find_one({"id": item_id}, {"_id": 0})
    if not item or item["status"] != "IN_ATTESA_ASSET" or not item.get("media_link"):
        return item
    link = item["media_link"]
    pronto = False
    if link["kind"] == "reel":
        progetto = await db.reel_projects.find_one({"id": link["project_id"]}, {"_id": 0})
        pronto = bool(progetto and progetto.get("video_status") == "VIDEO_PRONTO" and progetto.get("video_url"))
    elif link["kind"] == "flyer":
        progetto = await db.flyer_projects.find_one({"id": link["project_id"]}, {"_id": 0})
        pronto = bool(progetto and progetto.get("image_status") == "IMMAGINE_PRONTA" and progetto.get("image_url"))
    if not pronto:
        return item
    await db.content_items.update_one(
        {"id": item_id},
        {"$set": {"status": "COMPLETATO", "updated_at": now_iso()},
         "$push": {"history": {"at": now_iso(), "status": "COMPLETATO", "motivo": "Asset multimediale collegato pronto"}}},
    )
    return await db.content_items.find_one({"id": item_id}, {"_id": 0})


async def recover_on_startup(db) -> None:
    res = await db.content_items.update_many(
        {"status": "GENERAZIONE_IN_CORSO"}, {"$set": {"status": "BOZZA", "updated_at": now_iso()}},
    )
    if res.modified_count:
        logger.info("Content Creator recovery: %s contenuti riportati in BOZZA", res.modified_count)
