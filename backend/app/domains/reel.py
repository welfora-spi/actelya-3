"""Agente marketing — Reel (Requesty reale) + video reale (Runway).

Genera un progetto di reel (concept, hook, sceneggiatura, storyboard scena per
scena, voice-over, testi a schermo, caption, CTA, durata/formato, prompt per un
futuro generatore video) tramite UNA chiamata reale a Requesty, mai statica/
hardcoded. Usa automaticamente azienda/prodotto/settore/sito dal Fact Ledger
(domains/knowledge.py): non richiede mai di nuovo dati gia' noti.

Prima di autorizzare una generazione video (reale, a pagamento, su Runway),
il contenuto passa una validazione SEMANTICA deterministica (reel_semantic.py:
nessuna affermazione su prodotto/servizio/pubblico/prezzo/territorio puo'
essere estranea al Fact Ledger o al brief) -- vedi verifica_semantica() e
POST /projects/{id}/verifica-semantica (nessuna chiamata AI, richiamabile in
ogni momento, anche su un progetto gia' esistente).

Tre stati distinti, MAI confusi fra loro (requisito esplicito):
- progetto_pronto (testo): testo + storyboard validi (status == PROGETTO_PRONTO).
- video_pronto: True SOLO se l'ultimo job Runway e' SUCCEEDED con un URL
  realmente riproducibile (mai un MP4 simulato/hardcoded).
- video_approvato: True SOLO dopo un'approvazione esplicita del video (mai
  implicita nell'approvazione del solo progetto testuale).

I job video (reel_video_jobs) sono versionati e mai sovrascritti: una
richiesta di modifica del video crea sempre una NUOVA versione, la cronologia
resta consultabile (GET /projects/{id}/video/jobs).

Fuori da M2 (m2/engine.py) di proposito: M2 e' dichiaratamente e strutturalmente
solo-SIMULAZIONE (vedi m2/engine.py::_assert_simulation, che rifiuta con 409 se
ai_real_mode e' attivo) — questo modulo e' l'unico punto dell'app che esegue
DAVVERO generazioni reali (testo Requesty, video Runway), sempre gated da
ai_real_mode + connessione verificata + budget/tetto di costo + conferma
esplicita per-chiamata (mai automatica, mai duplicata su refresh)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import db
from ..deps import get_current_user, require_roles, rate_limit, assert_same_org
from ..audit import log_audit
from ..models import now_iso, base_record, new_id
from ..config import DEFAULT_ORG_ID
from ..security import decrypt_secret
from .knowledge import current_facts_map
from .estimator import PRICE_PER_TOKEN
from .reel_semantic import semantic_validate_reel_content
from . import social_memory
from ..integrations import requesty_gateway, runway_gateway
from ..integrations.requesty_gateway import RequestyErroreSanificato, RequestyNonConfigurato
from ..integrations.runway_gateway import RunwayErroreSanificato, RunwayNonConfigurato

logger = logging.getLogger("actelya.reel")
router = APIRouter(prefix="/reel", tags=["reel"])

# Stati di un job video (reel_video_jobs.status). Ogni tentativo e' una nuova
# versione, mai sovrascritta: vedi _crea_video_job / GET .../video/jobs.
VIDEO_JOB_ATTIVI = frozenset({"IN_CODA", "IN_GENERAZIONE"})
VIDEO_JOB_TERMINALI = frozenset({"VIDEO_PRONTO", "BLOCCATO", "FALLITO", "ESITO_INCERTO"})

POLL_INTERVALLO_SECONDI = 5
POLL_DURATA_MASSIMA_SECONDI = 600  # 10 minuti: oltre, il job resta IN_GENERAZIONE e va aggiornato manualmente

# Fatti aziendali minimi richiesti prima di generare (mai chiesti di nuovo se gia'
# noti, mai inventati se assenti: si blocca e si indica cosa manca).
REQUIRED_ORG_FIELDS = ("ragione_sociale", "settore")

MAX_TOKENS_DEFAULT = 3200  # margine ampio: lo storyboard (l'ultimo campo, il piu' lungo) non deve mai essere troncato

# Ordine dei campi (sia in 'required' sia in 'properties'): i campi corti e
# obbligatori vengono PRIMA dello storyboard (il piu' lungo), cosi' se il
# modello dovesse comunque avvicinarsi al limite di token, i campi piu'
# importanti risultano gia' scritti -- solo lo storyboard rischierebbe un
# troncamento, mai 'prompt_video_generativo' o gli altri campi corti.
REEL_SCHEMA = {
    "type": "object",
    "required": ["formato", "durata_secondi", "cta", "hook", "prompt_video_generativo",
                "concept", "caption", "hashtags", "testi_a_schermo", "voice_over_completo",
                "sceneggiatura", "storyboard"],
    "properties": {
        "formato": {"type": "string"},
        "durata_secondi": {"type": "number"},
        "cta": {"type": "string"},
        "hook": {"type": "string"},
        "prompt_video_generativo": {"type": "string"},
        "concept": {"type": "string"},
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "testi_a_schermo": {"type": "array", "items": {"type": "string"}},
        "voice_over_completo": {"type": "string"},
        "sceneggiatura": {"type": "string"},
        "storyboard": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["numero_scena", "durata_secondi", "testo_a_schermo", "voice_over", "descrizione_visiva"],
                "properties": {
                    "numero_scena": {"type": "integer"},
                    "durata_secondi": {"type": "number"},
                    "testo_a_schermo": {"type": "string"},
                    "voice_over": {"type": "string"},
                    "descrizione_visiva": {"type": "string"},
                },
            },
        },
    },
}

_REFUSAL_RE = re.compile(
    r"non posso|non sono in grado|mi dispiace|non è possibile|non e' possibile|"
    r"as an ai|i can'?t|i cannot|i'm sorry|cannot comply",
    re.IGNORECASE,
)


def _brand(org: dict) -> str:
    return (org.get("nome_commerciale") or org.get("ragione_sociale") or "l'azienda").strip()


async def _company_context(org_id: str) -> tuple[dict, list[str]]:
    """Fatti aziendali correnti: profilo organizzazione + Fact Ledger. Ritorna
    (contesto, campi_obbligatori_mancanti). Mai un valore inventato: solo cio' che
    e' gia' dichiarato/estratto/verificato."""
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


async def _registra_spesa_reale(org_id: str, project_id: str, input_tokens, output_tokens) -> Optional[float]:
    """Contabilizza SEMPRE una chiamata reale che ha consumato token, anche se il
    contenuto risultante viene poi BLOCCATO dalla validazione: una chiamata gia'
    inviata a Requesty ha un costo reale indipendentemente dall'esito. Riusa la
    STESSA collezione 'executions' gia' letta da domains/budget.py -> get_budget()
    (nessun secondo meccanismo di budget). Il costo e' una STIMA (stesso tasso
    'PRICE_PER_TOKEN' usato altrove nell'app per le stime, non il listino prezzi
    esatto di Requesty per il modello specifico, che non e' configurato in questa
    fase): mai spacciata per una cifra fatturata esatta, ma sempre registrata
    perche' il budget residuo rifletta che una chiamata reale e' avvenuta."""
    if input_tokens is None or output_tokens is None:
        return None
    stima = round((input_tokens + output_tokens) * PRICE_PER_TOKEN, 6)
    await db.executions.insert_one({
        "id": new_id("exec"), "organization_id": org_id, "real_cost": stima,
        "source": "reel", "reel_project_id": project_id, "created_at": now_iso(),
    })
    return stima


def _is_refusal_or_forbidden(v) -> bool:
    s = str(v or "").strip()
    if not s or s.lower() in ("unknown", "todo", "n/a", "na", "none", "null", "-", "?"):
        return True
    return bool(_REFUSAL_RE.search(s))


def validate_reel_content(c: dict) -> dict:
    """Valida il contenuto restituito da Requesty. status in
    COMPLETATO/COMPLETATO_CON_AVVISI/BLOCCATO -- mai un progetto 'pronto' con
    testo o storyboard vuoti/rifiutati."""
    errors, warnings = [], []
    if not isinstance(c, dict):
        return {"status": "BLOCCATO", "warnings": [], "errors": ["Contenuto non e' un oggetto JSON valido"]}

    for label, key, min_len in (
        ("Concept", "concept", 15), ("Hook", "hook", 5), ("Sceneggiatura", "sceneggiatura", 40),
        ("Voice-over completo", "voice_over_completo", 20), ("Caption", "caption", 10), ("CTA", "cta", 3),
        ("Prompt per generatore video", "prompt_video_generativo", 20), ("Formato", "formato", 2),
    ):
        v = c.get(key)
        if not isinstance(v, str) or not v.strip() or _is_refusal_or_forbidden(v):
            errors.append(f"{label}: mancante, vuoto o non producibile")
        elif len(v.strip()) < min_len:
            errors.append(f"{label}: contenuto non sufficientemente sostanziale")

    storyboard = c.get("storyboard")
    if not isinstance(storyboard, list) or len(storyboard) < 2:
        errors.append("storyboard: almeno 2 scene richieste")
    else:
        for i, scena in enumerate(storyboard, 1):
            if not isinstance(scena, dict):
                errors.append(f"Scena {i}: formato non valido")
                continue
            for k, ml in (("descrizione_visiva", 10), ("voice_over", 3)):
                v = scena.get(k)
                if not isinstance(v, str) or not v.strip() or _is_refusal_or_forbidden(v) or len(v.strip()) < ml:
                    errors.append(f"Scena {i} {k}: mancante o non sostanziale")
            durata = scena.get("durata_secondi")
            if not isinstance(durata, (int, float)) or durata <= 0:
                errors.append(f"Scena {i}: durata_secondi mancante o non valida")

    durata_tot = c.get("durata_secondi")
    if not isinstance(durata_tot, (int, float)) or durata_tot <= 0:
        errors.append("durata_secondi: mancante o non valida")

    testi = c.get("testi_a_schermo")
    if not isinstance(testi, list) or len([t for t in testi if isinstance(t, str) and t.strip()]) < 1:
        errors.append("testi_a_schermo: almeno un testo a schermo richiesto")

    hashtags = c.get("hashtags")
    if not isinstance(hashtags, list) or len([h for h in hashtags if isinstance(h, str) and h.strip()]) < 2:
        errors.append("hashtags: almeno 2 hashtag pertinenti richiesti")

    if errors:
        return {"status": "BLOCCATO", "warnings": warnings, "errors": errors}
    return {"status": "COMPLETATO", "warnings": warnings, "errors": []}


async def _snapshot_content_version(org_id: str, project_id: str, p_prima: dict, actor: str) -> None:
    """Fotografa il contenuto testuale PRIMA di una nuova generazione che lo
    sovrascrivera'. Mai chiamata sulla primissima generazione (p_prima non ha
    ancora 'content'): esiste una versione da fotografare solo a partire
    dalla seconda generazione in poi (dopo un 'richiedi-modifica')."""
    ultimo = await db.reel_content_versions.find_one({"reel_project_id": project_id}, sort=[("version", -1)])
    versione = (ultimo["version"] + 1) if ultimo else 1
    await db.reel_content_versions.insert_one({
        "id": new_id("reelver"), "organization_id": org_id, "reel_project_id": project_id,
        "version": versione, "content": p_prima.get("content"), "generazione": p_prima.get("generazione"),
        "semantic_check": p_prima.get("semantic_check"), "nota_revisione_che_ha_portato_alla_modifica": p_prima.get("nota_revisione"),
        "superseded_at": now_iso(), "created_by": actor,
    })


def _public_content_version(v: dict) -> dict:
    return {
        "version": v["version"], "content": v.get("content"), "generazione": v.get("generazione"),
        "semantic_check": v.get("semantic_check"),
        "nota_revisione_che_ha_portato_alla_modifica": v.get("nota_revisione_che_ha_portato_alla_modifica"),
        "superseded_at": v.get("superseded_at"), "created_by": v.get("created_by"),
    }


def _public(p: dict) -> dict:
    return {
        "id": p["id"], "brief": p.get("brief", ""), "status": p["status"],
        # Progetto reel (testo + storyboard) -- MAI confuso col video.
        "progetto_pronto": p.get("progetto_pronto", False),
        "progetto_approvato": p.get("progetto_approvato", False),
        "progetto_approvato_da": p.get("progetto_approvato_da"),
        "progetto_approvato_at": p.get("progetto_approvato_at"),
        "content": p.get("content"),
        "fact_snapshot": p.get("fact_snapshot", {}),
        "generazione": p.get("generazione", {}),
        "nota_revisione": p.get("nota_revisione"),
        # Validazione semantica deterministica (nessuna chiamata AI): condizione
        # necessaria (non sufficiente da sola) per autorizzare il video.
        "semantic_check": p.get("semantic_check", {"status": "NON_VERIFICATO", "affermazioni_contestate": []}),
        # Video reel -- SEMPRE distinto dal progetto testuale: video_pronto e'
        # True SOLO se esiste davvero un job Runway SUCCEEDED con un URL.
        "video_status": p.get("video_status", "NON_RICHIESTO"),
        "video_pronto": p.get("video_status") == "VIDEO_PRONTO" and bool(p.get("video_url")),
        "video_url": p.get("video_url"),
        "video_approvato": p.get("video_approvato", False),
        "video_approvato_da": p.get("video_approvato_da"),
        "video_approvato_at": p.get("video_approvato_at"),
        "video_nota_revisione": p.get("video_nota_revisione"),
        "created_at": p.get("created_at"), "updated_at": p.get("updated_at"),
    }


class NewReelBody(BaseModel):
    brief: str = ""


@router.get("/projects")
async def list_projects(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.reel_projects.find({"organization_id": org_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [_public(p) for p in rows]


@router.get("/projects/{project_id}")
async def get_project(project_id: str, user: dict = Depends(get_current_user)):
    p = await db.reel_projects.find_one({"id": project_id}, {"_id": 0})
    assert_same_org(p, user, "Progetto reel non trovato")
    return _public(p)


@router.post("/projects")
async def create_project(body: NewReelBody, user: dict = Depends(require_roles("OPERATORE", "ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    contesto, mancanti = await _company_context(org_id)
    if mancanti:
        raise HTTPException(
            status_code=400,
            detail=f"Informazioni aziendali mancanti nel Fact Ledger: {', '.join(mancanti)}. "
                   "Completale in Onboarding/Profilo prima di creare un progetto reel.",
        )
    rec = base_record(org_id, user["id"])
    rec.update({
        "id": new_id("reel"), "brief": body.brief.strip(), "status": "BOZZA",
        "progetto_pronto": False, "content": None, "fact_snapshot": contesto,
        "generazione": {}, "progetto_approvato": False, "progetto_approvato_da": None, "progetto_approvato_at": None,
        "nota_revisione": None,
        "semantic_check": {"status": "NON_VERIFICATO", "affermazioni_contestate": []},
        "video_status": "NON_RICHIESTO", "video_url": None, "video_approvato": False,
        "video_approvato_da": None, "video_approvato_at": None, "video_nota_revisione": None,
    })
    await db.reel_projects.insert_one(rec)
    await log_audit(org_id=org_id, user=user, action="CREATE_REEL_PROJECT",
                    entity_type="reel_project", entity_id=rec["id"], details={"brief": body.brief.strip()})
    return _public(rec)


async def _readiness(org_id: str) -> dict:
    """Condizioni per una generazione reale, tutte verificate PRIMA di ogni
    chiamata di rete: mai una chiamata a costo se una condizione manca."""
    settings = await db.settings.find_one({"id": org_id}) or {}
    ai_real = bool(settings.get("ai_real_mode"))
    conn = await db.ai_connections.find_one({
        "organization_id": org_id, "provider_type": "requesty", "verified": True, "active": True,
    }, {"_id": 0})
    budget = await db.budgets.find_one({"id": org_id}) or {}
    spent_rows = await db.executions.find({"organization_id": org_id}, {"_id": 0, "real_cost": 1}).to_list(1000)
    spent = sum(r.get("real_cost", 0.0) for r in spent_rows)
    residuo = round(budget.get("general_limit", 0.0) - spent, 6)
    motivi = []
    if not ai_real:
        motivi.append("Modalita' AI REALE non attiva (Impostazioni).")
    if not conn:
        motivi.append("Nessuna connessione Requesty verificata e attiva (Connessioni).")
    elif not (conn.get("effective_model") or "").strip():
        motivi.append("La connessione Requesty non ha un 'modello effettivo' configurato.")
    if not budget.get("general_limit", 0.0) > 0:
        motivi.append("Nessun budget generale configurato (Budget).")
    return {"pronto": not motivi, "motivi": motivi, "connessione": conn, "budget_residuo": residuo}


@router.post("/projects/{project_id}/generate/preview")
async def generate_preview(project_id: str, user: dict = Depends(require_roles("ADMIN"))):
    """Nessuna chiamata reale: mostra solo se le condizioni per generare sono
    soddisfatte e quale modello/connessione verrebbe usato."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    r = await _readiness(org_id)
    conn = r.pop("connessione", None)
    return {
        **r,
        "provider": "requesty",
        "modello_effettivo": (conn or {}).get("effective_model"),
        "budget_residuo": r["budget_residuo"],
        "message": "Verra' effettuata UNA chiamata reale a Requesty. Nessuna chiamata parte senza conferma esplicita.",
    }


class ConfirmBody(BaseModel):
    confirm: bool = False


@router.post("/projects/{project_id}/generate")
async def generate(project_id: str, body: ConfirmBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rate_limit(f"reel_generate:{project_id}", max_calls=5, window_seconds=60)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta prima di una chiamata reale a Requesty.")

    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    if p["status"] == "PROGETTO_PRONTO":
        raise HTTPException(status_code=409, detail="Progetto gia' pronto: crea un nuovo progetto per rigenerare.")
    if p["status"] == "ESITO_INCERTO":
        raise HTTPException(
            status_code=409,
            detail="L'esito dell'ultimo tentativo e' incerto (richiesta inviata, risposta mai ricevuta): "
                   "risolvilo prima di riprovare (POST /reel/projects/{id}/risolvi-esito-incerto).",
        )

    r = await _readiness(org_id)
    if not r["pronto"]:
        raise HTTPException(status_code=409, detail="; ".join(r["motivi"]))
    conn = r["connessione"]

    contesto, mancanti = await _company_context(org_id)
    if mancanti:
        raise HTTPException(status_code=400, detail=f"Informazioni aziendali mancanti: {', '.join(mancanti)}.")

    def _campo(chiave):
        return contesto.get(chiave, "") or "informazione non disponibile"

    # Item 13/17: memoria persistente + apprendimento, SOLO orientativi (mai
    # una fonte di fatti aziendali, mai vincolanti — vedi social_memory.py).
    # Stringa vuota per qualunque org senza storico: il prompt resta
    # invariato rispetto a prima di questa funzione.
    memoria_ctx = await social_memory.get_memory_context(db, org_id)
    memoria_blocco = social_memory.render_memory_block(memoria_ctx)

    system = (
        "Sei un agente marketing di ACTELYA specializzato nella creazione di reel per social media. "
        "REGOLA ASSOLUTA, piu' importante di ogni altra: usa ESCLUSIVAMENTE le informazioni aziendali "
        "fornite nel messaggio utente. Non inventare MAI nome, prodotto, caratteristiche, benefici, "
        "prezzi, pubblico target, territorio servito, tipologia di clienti o promesse che non siano "
        "esplicitamente indicati. Se un'informazione e' 'informazione non disponibile', NON inventarla e "
        "NON menzionarla in modo specifico: usa formulazioni generiche e oneste (es. 'la nostra soluzione', "
        "'i nostri clienti') invece di dettagli inventati. Meglio un contenuto generico ma onesto che uno "
        "dettagliato ma inventato.\n"
        "REGOLA SUL FORMATO: rispondi SOLO con un oggetto JSON conforme allo schema richiesto, in italiano. "
        "Sii SINTETICO in ogni campo (concept/hook/caption/cta: 1 frase breve; sceneggiatura: poche frasi; "
        "voice_over_completo: massimo 60 parole; storyboard: al massimo 3 scene, ciascuna con descrizioni "
        "brevi) cosi' l'intero JSON, storyboard incluso, rientra nel budget di token disponibile: un campo "
        "obbligatorio mancante o troncato e' un errore grave, un campo breve non lo e' mai."
    )
    messaggio = (
        f"Azienda: {_brand(contesto)}\n"
        f"Ragione sociale: {_campo('ragione_sociale')}\n"
        f"Settore: {_campo('settore')}\n"
        f"Sito web: {_campo('sito_web')}\n"
        f"Obiettivi commerciali: {_campo('obiettivi_commerciali')}\n"
        f"Prodotto: {_campo('prodotto')}\n"
        f"Pubblico target: {_campo('pubblico_target')}\n"
        f"Tono di voce: {_campo('tono_di_voce')}\n"
        f"Brief creativo aggiuntivo: {p.get('brief') or 'nessuno: crea un reel generico e coerente col settore indicato, senza inventare dettagli specifici sul prodotto'}\n"
        + (f"Richiesta di modifica rispetto a un tentativo precedente (tienine conto): {p.get('nota_revisione')}\n" if p.get("nota_revisione") else "")
        + (f"\n{memoria_blocco}\n" if memoria_blocco else "")
        + "\n"
        "Genera, IN QUEST'ORDINE (i campi piu' corti prima, lo storyboard per ultimo perche' e' il piu' "
        "lungo): formato del video, durata totale in secondi, CTA, hook, prompt dettagliato in inglese per "
        "un futuro generatore video (Runway/HeyGen), concept, caption per il post, da 2 a 6 hashtag "
        "pertinenti (senza spazi, es. '#panetteria', mai un hashtag generico che non abbia relazione con "
        "settore/prodotto/localita' dichiarati), elenco dei testi a schermo, voice-over completo, "
        "sceneggiatura, storyboard scena per scena (max 3 scene, con durata in secondi, testo a schermo, "
        "voice-over e descrizione visiva per ciascuna)."
    )

    await db.reel_projects.update_one({"id": project_id}, {"$set": {"status": "GENERAZIONE_IN_CORSO", "updated_at": now_iso()}})

    try:
        risultato = requesty_gateway.genera_json(
            model_id_requesty=conn["effective_model"], system=system, messaggio_utente=messaggio,
            schema_json=REEL_SCHEMA, schema_nome="actelya_reel_project",
            max_tokens=conn.get("max_tokens") or MAX_TOKENS_DEFAULT, timeout=conn.get("timeout") or 60,
        )
    except RequestyNonConfigurato as exc:
        await db.reel_projects.update_one({"id": project_id}, {"$set": {
            "status": "BLOCCATO", "generazione": {"ultimo_errore_codice": "credenziale_assente", "ultimo_errore_messaggio": str(exc)},
            "updated_at": now_iso()}})
        raise HTTPException(status_code=409, detail=str(exc))
    except RequestyErroreSanificato as exc:
        nuovo_status = "ESITO_INCERTO" if exc.codice == "esito_incerto" else "BLOCCATO"
        await db.reel_projects.update_one({"id": project_id}, {"$set": {
            "status": nuovo_status,
            "generazione": {"ultimo_errore_codice": exc.codice, "ultimo_errore_messaggio": exc.messaggio},
            "updated_at": now_iso()}})
        await log_audit(org_id=org_id, user=user, action="REEL_GENERATE_ERROR",
                        entity_type="reel_project", entity_id=project_id, status="ERROR",
                        reason=exc.codice, details={"codice_errore": exc.codice})
        raise HTTPException(status_code=502, detail=exc.messaggio)

    # La chiamata e' gia' partita ed e' stata risposta (usage disponibile): va
    # sempre contabilizzata sul budget, indipendentemente da cosa succede dopo
    # (JSON non valido, troncamento, validazione BLOCCATA).
    stima_costo = await _registra_spesa_reale(org_id, project_id, risultato.input_tokens, risultato.output_tokens)

    try:
        contenuto = json.loads(risultato.testo)
    except (json.JSONDecodeError, TypeError):
        await db.reel_projects.update_one({"id": project_id}, {"$set": {
            "status": "BLOCCATO",
            "generazione": {"ultimo_errore_codice": "risposta_non_valida",
                           "ultimo_errore_messaggio": "Risposta non e' un JSON valido.",
                           "errori_validazione": ["Risposta non e' un JSON valido."], "avvisi_validazione": [],
                           "modello_effettivo": risultato.modello_effettivo,
                           "input_tokens": risultato.input_tokens, "output_tokens": risultato.output_tokens,
                           "stima_costo_usd": stima_costo, "troncata": risultato.troncata},
            "updated_at": now_iso()}})
        await log_audit(org_id=org_id, user=user, action="REEL_GENERATE_ERROR",
                        entity_type="reel_project", entity_id=project_id, status="ERROR", reason="risposta_non_valida",
                        details={"stima_costo_usd": stima_costo})
        raise HTTPException(status_code=502, detail="La risposta di Requesty non e' un JSON valido (chiamata comunque addebitata: vedi budget).")

    if risultato.troncata:
        validazione = {
            "status": "BLOCCATO", "warnings": [],
            "errors": ["Risposta troncata: il limite di token e' stato raggiunto prima di completare il JSON. "
                      "Riprova (il prompt e' gia' ottimizzato per stare nel limite; se accade di nuovo, "
                      "aumenta 'Max token' sulla connessione Requesty in Connessioni e API)."],
        }
    else:
        validazione = validate_reel_content(contenuto)

    nuovo_status = "PROGETTO_PRONTO" if validazione["status"] in ("COMPLETATO", "COMPLETATO_CON_AVVISI") else "BLOCCATO"
    generazione = {
        "modello_effettivo": risultato.modello_effettivo, "input_tokens": risultato.input_tokens,
        "output_tokens": risultato.output_tokens, "latenza_ms": risultato.latenza_ms,
        "troncata": risultato.troncata, "stima_costo_usd": stima_costo,
        "errori_validazione": validazione["errors"], "avvisi_validazione": validazione["warnings"],
    }
    # Validazione semantica deterministica automatica appena il testo e' pronto:
    # nessuna chiamata AI, e' un requisito PRIMA di poter anche solo proporre il
    # video (vedi _video_readiness). Ricalcolabile in ogni momento senza costo
    # via POST .../verifica-semantica.
    semantic = semantic_validate_reel_content(contenuto, contesto, p.get("brief", "")) if nuovo_status == "PROGETTO_PRONTO" \
        else {"status": "NON_VERIFICATO", "affermazioni_contestate": []}
    # Item 10 (revision loop): un contenuto testuale gia' esistente viene
    # SEMPRE fotografato prima di essere sovrascritto dalla nuova
    # generazione -- mai perso. Solo la generazione VIDEO era gia' versionata
    # (reel_video_jobs); questo applica lo stesso principio al testo/
    # storyboard, cosi' 'richiedi modifica' -> nuova generazione non cancella
    # la versione precedente, solo la supera (consultabile via GET
    # .../content/versions).
    if p.get("content"):
        await _snapshot_content_version(org_id, project_id, p, user.get("id", "system"))
    await db.reel_projects.update_one({"id": project_id}, {"$set": {
        "status": nuovo_status, "progetto_pronto": nuovo_status == "PROGETTO_PRONTO",
        "content": contenuto, "generazione": generazione, "semantic_check": semantic, "updated_at": now_iso(),
        # Una nuova generazione testo invalida sempre l'eventuale video/approvazione precedenti:
        # il video deve sempre corrispondere al progetto testuale corrente, mai a uno superato.
        "video_status": "NON_RICHIESTO", "video_url": None, "video_approvato": False,
        "video_approvato_da": None, "video_approvato_at": None,
    }})
    await log_audit(org_id=org_id, user=user, action="REEL_GENERATED",
                    entity_type="reel_project", entity_id=project_id,
                    details={"status": nuovo_status, "modello_effettivo": risultato.modello_effettivo,
                             "input_tokens": risultato.input_tokens, "output_tokens": risultato.output_tokens,
                             "latenza_ms": risultato.latenza_ms, "stima_costo_usd": stima_costo,
                             "errori_validazione": validazione["errors"]})
    p2 = await db.reel_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


class ResolveUncertainBody(BaseModel):
    nota: str


@router.post("/projects/{project_id}/risolvi-esito-incerto")
async def risolvi_esito_incerto(project_id: str, body: ResolveUncertainBody, user: dict = Depends(require_roles("ADMIN"))):
    """Sblocca manualmente un progetto con esito incerto (richiesta inviata a
    Requesty, risposta mai arrivata): NON rigenera automaticamente, si limita a
    riportare il progetto in uno stato da cui un nuovo tentativo esplicito e'
    possibile. La verifica dell'esito reale (e del relativo costo) resta a carico
    dell'amministratore."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    if p["status"] != "ESITO_INCERTO":
        raise HTTPException(status_code=409, detail="Il progetto non ha un esito incerto da risolvere.")
    if not body.nota.strip():
        raise HTTPException(status_code=422, detail="Nota di risoluzione obbligatoria")
    await db.reel_projects.update_one({"id": project_id}, {"$set": {"status": "BLOCCATO", "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="REEL_RESOLVE_UNCERTAIN",
                    entity_type="reel_project", entity_id=project_id, details={"nota": body.nota.strip()})
    p2 = await db.reel_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


@router.post("/projects/{project_id}/approve")
async def approve_project(project_id: str, user: dict = Depends(require_roles("ADMIN", "APPROVATORE"))):
    """Approva il PROGETTO reel (testo + storyboard validi): PROGETTO_REEL_PRONTO
    -> approvato. Non genera mai un video e non equivale MAI a un'approvazione
    del video (vedi POST .../video/approve, distinta e successiva)."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    if p["status"] != "PROGETTO_PRONTO":
        raise HTTPException(status_code=409, detail="Solo un progetto reel PRONTO (testo + storyboard validi) puo' essere approvato.")
    await db.reel_projects.update_one({"id": project_id}, {"$set": {
        "progetto_approvato": True, "progetto_approvato_da": user.get("email") or user.get("id"),
        "progetto_approvato_at": now_iso(), "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="REEL_PROJECT_APPROVED",
                    entity_type="reel_project", entity_id=project_id)
    p2 = await db.reel_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


@router.get("/projects/{project_id}/content/versions")
async def list_content_versions(project_id: str, user: dict = Depends(get_current_user)):
    """Cronologia delle versioni testuali SUPERATE (mai la corrente, gia'
    disponibile in GET /projects/{id}::content): item 10 -- nessuna
    versione precedente viene mai persa quando si richiede una modifica."""
    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    rows = await db.reel_content_versions.find(
        {"reel_project_id": project_id}, {"_id": 0}).sort("version", -1).to_list(200)
    return [_public_content_version(v) for v in rows]


@router.post("/projects/{project_id}/verifica-semantica")
async def verifica_semantica(project_id: str, user: dict = Depends(require_roles("OPERATORE", "ADMIN", "APPROVATORE"))):
    """Ricalcola la validazione semantica deterministica sul contenuto GIA'
    presente (nessuna chiamata AI, nessun costo, richiamabile in ogni momento
    anche su un progetto creato prima che questo controllo esistesse)."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    if not p.get("content"):
        raise HTTPException(status_code=409, detail="Nessun contenuto da verificare: genera prima il progetto reel.")
    semantic = semantic_validate_reel_content(p["content"], p.get("fact_snapshot", {}), p.get("brief", ""))
    await db.reel_projects.update_one({"id": project_id}, {"$set": {"semantic_check": semantic, "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="REEL_SEMANTIC_CHECK",
                    entity_type="reel_project", entity_id=project_id,
                    details={"status": semantic["status"], "n_affermazioni_contestate": len(semantic["affermazioni_contestate"])})
    p2 = await db.reel_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


class RichiediModificaBody(BaseModel):
    nota: str


@router.post("/projects/{project_id}/richiedi-modifica")
async def richiedi_modifica(project_id: str, body: RichiediModificaBody,
                            user: dict = Depends(require_roles("ADMIN", "APPROVATORE", "OPERATORE"))):
    """Richiede una revisione: NON rigenera automaticamente (nessun addebito
    implicito). Riporta il progetto in BOZZA cosi' un nuovo tentativo di
    generazione reale resta un'azione esplicita e confermata separatamente."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    if p["status"] not in ("PROGETTO_PRONTO", "BLOCCATO"):
        raise HTTPException(status_code=409, detail="Richiesta di modifica non applicabile allo stato corrente del progetto.")
    if not body.nota.strip():
        raise HTTPException(status_code=422, detail="Nota di modifica obbligatoria")
    await db.reel_projects.update_one({"id": project_id}, {"$set": {
        "status": "BOZZA", "progetto_pronto": False, "progetto_approvato": False,
        "progetto_approvato_da": None, "progetto_approvato_at": None,
        "nota_revisione": body.nota.strip(), "semantic_check": {"status": "NON_VERIFICATO", "affermazioni_contestate": []},
        # Un nuovo testo invalida il video precedente: mai un video approvato
        # collegato a una sceneggiatura che sta per cambiare.
        "video_status": "NON_RICHIESTO", "video_url": None, "video_approvato": False,
        "video_approvato_da": None, "video_approvato_at": None,
        "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="REEL_REVISION_REQUESTED",
                    entity_type="reel_project", entity_id=project_id, details={"nota": body.nota.strip()})
    # Item 13: la richiesta di modifica e' un dato utile per il Social Media
    # Manager (capire cosa viene chiesto piu' spesso), mai un dump del
    # contenuto -- solo la nota stessa, gia' fornita esplicitamente dall'utente.
    await social_memory.record_entry(
        db, org_id, "revision_pattern", summary=body.nota.strip(),
        source_project_id=project_id, actor=user.get("email") or user.get("id"),
    )
    p2 = await db.reel_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


# ===================== VIDEO (Runway reale) =====================

async def _video_readiness(org_id: str, project: dict) -> dict:
    """Condizioni per una generazione video reale, tutte verificate PRIMA di
    ogni chiamata di rete: mai una chiamata a pagamento se una condizione
    manca. Distinta da _readiness() (testo/Requesty): stessa filosofia,
    connessione/provider diversi."""
    motivi = []
    if project["status"] != "PROGETTO_PRONTO":
        motivi.append("Il progetto reel (testo/storyboard) non e' PRONTO.")
    semantic = project.get("semantic_check") or {"status": "NON_VERIFICATO"}
    if semantic.get("status") != "OK":
        motivi.append(
            f"Validazione semantica non superata ({semantic.get('status', 'NON_VERIFICATO')}): "
            f"{len(semantic.get('affermazioni_contestate', []))} affermazione/i non riconducibili al Fact Ledger/brief."
        )
    if project.get("video_status") in VIDEO_JOB_ATTIVI:
        motivi.append("Una generazione video e' gia' in corso per questo progetto.")

    settings = await db.settings.find_one({"id": org_id}) or {}
    ai_real = bool(settings.get("ai_real_mode"))
    if not ai_real:
        motivi.append("Modalita' AI REALE non attiva (Impostazioni).")
    conn = await db.video_connections.find_one({
        "organization_id": org_id, "provider_type": "runway", "verified": True, "active": True,
    }, {"_id": 0})
    if not conn:
        motivi.append("Nessuna connessione Runway verificata e attiva (Connessioni e API).")
    elif not (conn.get("effective_model") or "").strip():
        motivi.append("La connessione Runway non ha un 'modello effettivo' configurato.")

    # NOTA UNITA' DI MISURA: 'budget_residuo' qui sotto resta espresso in $ USD
    # (stesso budget generale usato per Requesty, vedi domains/budget.py): serve
    # solo a verificare che un budget sia stato configurato affatto. Il tetto
    # di costo PER-GENERAZIONE Runway (conn.max_cost_per_generation, verificato
    # in video_generate) e' invece in CREDITI Runway, un'unita' diversa: Runway
    # non espone un tasso credito->valuta generico via API, quindi i due importi
    # non sono ancora sommati in un unico residuo -- mostrati sempre separati,
    # mai convertiti/mescolati (nessuna cifra inventata).
    budget = await db.budgets.find_one({"id": org_id}) or {}
    spent_rows = await db.executions.find({"organization_id": org_id}, {"_id": 0, "real_cost": 1}).to_list(1000)
    spent = sum(r.get("real_cost", 0.0) for r in spent_rows)
    residuo = round(budget.get("general_limit", 0.0) - spent, 6)
    if not budget.get("general_limit", 0.0) > 0:
        motivi.append("Nessun budget generale configurato (Budget).")

    return {"pronto": not motivi, "motivi": motivi, "connessione": conn, "budget_residuo": residuo}


def _durata_runway(content: dict) -> int:
    """Clamp della durata del reel (tipicamente 15-30s) sulla durata massima di
    UNA clip Runway per-generazione (4/6/8s a seconda del modello): questa fase
    genera UNA clip singola dal prompt_video_generativo, non un montaggio
    multi-scena (predisposizione esplicita per un lavoro futuro, vedi
    docstring del modulo)."""
    try:
        d = float(content.get("durata_secondi") or 8)
    except (TypeError, ValueError):
        d = 8
    candidati = (4, 6, 8)
    return min(candidati, key=lambda c: abs(c - d))


def _ratio_runway(content: dict, default_ratio: str) -> str:
    formato = str(content.get("formato") or "").lower()
    if "16:9" in formato or "1280:720" in formato:
        return "1280:720"
    if "9:16" in formato or "720:1280" in formato:
        return "720:1280"
    return default_ratio or "720:1280"


def _public_job(j: dict) -> dict:
    return {
        "id": j["id"], "version": j["version"], "status": j["status"], "provider": j.get("provider", "runway"),
        "modello": j.get("modello"), "task_id_remoto": j.get("task_id_remoto"),
        "durata_secondi": j.get("durata_secondi"), "ratio": j.get("ratio"),
        "stima_costo_credits": j.get("stima_costo_credits"), "costo_credits": j.get("costo_credits"),
        "output_url": j.get("output_url"), "errore_codice": j.get("errore_codice"), "errore_messaggio": j.get("errore_messaggio"),
        "created_by": j.get("created_by"), "created_at": j.get("created_at"), "updated_at": j.get("updated_at"),
    }


@router.get("/projects/{project_id}/video/jobs")
async def list_video_jobs(project_id: str, user: dict = Depends(get_current_user)):
    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    rows = await db.reel_video_jobs.find({"reel_project_id": project_id}, {"_id": 0}).sort("version", -1).to_list(100)
    return [_public_job(j) for j in rows]


@router.post("/projects/{project_id}/video/preview")
async def video_preview(project_id: str, user: dict = Depends(require_roles("ADMIN"))):
    """Nessuna chiamata reale: mostra provider/modello/durata/formato/tetto di
    costo configurato/budget residuo e se le condizioni sono soddisfatte."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    r = await _video_readiness(org_id, p)
    conn = r.pop("connessione", None)
    content = p.get("content") or {}
    return {
        **r,
        "provider": "runway",
        "modello_effettivo": (conn or {}).get("effective_model"),
        "durata_secondi": _durata_runway(content) if content else None,
        "ratio": _ratio_runway(content, (conn or {}).get("default_ratio", "720:1280")) if content else None,
        "costo_massimo_credits": (conn or {}).get("max_cost_per_generation"),
        "message": "Verra' avviata UNA generazione video reale su Runway a partire dal prompt gia' prodotto da "
                   "Requesty. Nessuna chiamata parte senza conferma esplicita.",
    }


async def _crea_video_job(org_id: str, project: dict, actor: str) -> dict:
    ultimo = await db.reel_video_jobs.find_one({"reel_project_id": project["id"]}, sort=[("version", -1)])
    versione = (ultimo["version"] + 1) if ultimo else 1
    job = base_record(org_id, actor)
    job.update({
        "id": new_id("vjob"), "reel_project_id": project["id"], "version": versione,
        "status": "IN_CODA", "provider": "runway", "modello": None, "task_id_remoto": None,
        "durata_secondi": None, "ratio": None, "stima_costo_credits": None, "costo_credits": None,
        "output_url": None, "errore_codice": None, "errore_messaggio": None,
    })
    await db.reel_video_jobs.insert_one(job)
    job.pop("_id", None)
    return job


async def _poll_video_job(org_id: str, project_id: str, job_id: str, api_key_encrypted: str) -> None:
    """Polling in background (sola lettura, GRATUITO su Runway): mai una
    seconda chiamata di generazione, solo GET tasks.retrieve fino a stato
    terminale o timeout locale. Errori di polling non fanno MAI fallire il
    job silenziosamente: il job resta IN_GENERAZIONE e va aggiornato
    manualmente (vedi POST .../video/jobs/{job_id}/aggiorna-stato)."""
    try:
        api_key = decrypt_secret(api_key_encrypted)
    except Exception:
        logger.error("Impossibile decifrare la credenziale Runway per il polling del job %s", job_id)
        return
    trascorso = 0
    while trascorso < POLL_DURATA_MASSIMA_SECONDI:
        await asyncio.sleep(POLL_INTERVALLO_SECONDI)
        trascorso += POLL_INTERVALLO_SECONDI
        job = await db.reel_video_jobs.find_one({"id": job_id})
        if not job or job["status"] not in VIDEO_JOB_ATTIVI:
            return  # job risolto/annullato altrove (es. aggiornamento manuale)
        try:
            stato = await asyncio.to_thread(runway_gateway.recupera_stato_task, api_key, job["task_id_remoto"])
        except Exception:
            logger.warning("Polling Runway fallito per il job %s (nuovo tentativo al prossimo ciclo)", job_id)
            continue
        if stato.status in runway_gateway.STATI_TERMINALI:
            await _applica_stato_terminale(org_id, project_id, job_id, stato)
            return
    logger.warning("Polling Runway terminato per timeout locale (job %s ancora IN_GENERAZIONE su Runway)", job_id)


async def _applica_stato_terminale(org_id: str, project_id: str, job_id: str, stato) -> None:
    if stato.status == "SUCCEEDED":
        nuovo_status_job, nuovo_status_video = "VIDEO_PRONTO", "VIDEO_PRONTO"
        url = stato.output_urls[0] if stato.output_urls else None
    elif stato.status == "FAILED":
        nuovo_status_job, nuovo_status_video, url = "FALLITO", "FALLITO", None
    else:  # CANCELLED
        nuovo_status_job, nuovo_status_video, url = "BLOCCATO", "BLOCCATO", None

    await db.reel_video_jobs.update_one({"id": job_id}, {"$set": {
        "status": nuovo_status_job, "output_url": url, "costo_credits": stato.costo_credits,
        "errore_codice": stato.errore_codice, "errore_messaggio": stato.errore_messaggio, "updated_at": now_iso(),
    }})
    await db.reel_projects.update_one({"id": project_id}, {"$set": {
        "video_status": nuovo_status_video, "video_url": url, "updated_at": now_iso(),
    }})
    await log_audit(org_id=org_id, user={"email": "system"}, action="REEL_VIDEO_JOB_TERMINAL",
                    entity_type="reel_video_job", entity_id=job_id,
                    details={"status": nuovo_status_job, "costo_credits": stato.costo_credits})


@router.post("/projects/{project_id}/video/generate")
async def video_generate(project_id: str, body: ConfirmBody, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rate_limit(f"reel_video_generate:{project_id}", max_calls=5, window_seconds=60)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Conferma esplicita richiesta prima di una generazione video reale su Runway.")

    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")

    r = await _video_readiness(org_id, p)
    if not r["pronto"]:
        raise HTTPException(status_code=409, detail="; ".join(r["motivi"]))
    conn = r["connessione"]
    content = p["content"]

    job = await _crea_video_job(org_id, p, user.get("id", "system"))
    durata, ratio = _durata_runway(content), _ratio_runway(content, conn.get("default_ratio", "720:1280"))
    await db.reel_video_jobs.update_one({"id": job["id"]}, {"$set": {
        "modello": conn["effective_model"], "durata_secondi": durata, "ratio": ratio, "updated_at": now_iso()}})
    await db.reel_projects.update_one({"id": project_id}, {"$set": {"video_status": "IN_CODA", "updated_at": now_iso()}})

    api_key = decrypt_secret(conn["api_key_encrypted"])
    try:
        avviato = runway_gateway.avvia_generazione_video(
            api_key=api_key, model=conn["effective_model"], prompt_text=content["prompt_video_generativo"],
            duration=durata, ratio=ratio, timeout=conn.get("timeout") or 30,
        )
    except RunwayNonConfigurato as exc:
        await db.reel_video_jobs.update_one({"id": job["id"]}, {"$set": {"status": "BLOCCATO", "errore_codice": "credenziale_assente", "errore_messaggio": str(exc), "updated_at": now_iso()}})
        await db.reel_projects.update_one({"id": project_id}, {"$set": {"video_status": "BLOCCATO", "updated_at": now_iso()}})
        raise HTTPException(status_code=409, detail=str(exc))
    except RunwayErroreSanificato as exc:
        nuovo = "ESITO_INCERTO" if exc.codice == "esito_incerto" else "BLOCCATO"
        await db.reel_video_jobs.update_one({"id": job["id"]}, {"$set": {"status": nuovo, "errore_codice": exc.codice, "errore_messaggio": exc.messaggio, "updated_at": now_iso()}})
        await db.reel_projects.update_one({"id": project_id}, {"$set": {"video_status": nuovo, "updated_at": now_iso()}})
        await log_audit(org_id=org_id, user=user, action="REEL_VIDEO_GENERATE_ERROR",
                        entity_type="reel_video_job", entity_id=job["id"], status="ERROR", reason=exc.codice)
        raise HTTPException(status_code=502, detail=exc.messaggio)

    # Tetto di costo (in CREDITI Runway, non $: Runway non espone un tasso di
    # cambio credito->valuta generico, vedi docstring _video_readiness) --
    # verificato SUBITO dopo la creazione del task (Runway non offre una stima
    # senza impegnarsi): se lo supera, tentativo di annullamento immediato
    # (best-effort, mai fatale se fallisce) prima che il task passi in RUNNING.
    tetto = conn.get("max_cost_per_generation")
    if tetto and avviato.stima_costo_credits and avviato.stima_costo_credits > tetto:
        annullato = await asyncio.to_thread(runway_gateway.annulla_task, api_key, avviato.task_id, conn.get("timeout") or 30)
        await db.reel_video_jobs.update_one({"id": job["id"]}, {"$set": {
            "status": "BLOCCATO", "task_id_remoto": avviato.task_id, "stima_costo_credits": avviato.stima_costo_credits,
            "errore_codice": "tetto_costo_superato",
            "errore_messaggio": f"Stima costo ({avviato.stima_costo_credits} crediti) oltre il tetto configurato "
                                f"({tetto} crediti). Task {'annullato' if annullato else 'annullamento non riuscito: verificare manualmente su Runway'}.",
            "updated_at": now_iso()}})
        await db.reel_projects.update_one({"id": project_id}, {"$set": {"video_status": "BLOCCATO", "updated_at": now_iso()}})
        await log_audit(org_id=org_id, user=user, action="REEL_VIDEO_COST_CAP_EXCEEDED",
                        entity_type="reel_video_job", entity_id=job["id"], status="ERROR",
                        details={"stima_costo_credits": avviato.stima_costo_credits, "tetto": tetto, "annullato": annullato})
        raise HTTPException(status_code=409, detail=f"Stima costo ({avviato.stima_costo_credits} crediti) oltre il tetto configurato ({tetto} crediti).")

    await db.reel_video_jobs.update_one({"id": job["id"]}, {"$set": {
        "status": "IN_GENERAZIONE", "task_id_remoto": avviato.task_id,
        "stima_costo_credits": avviato.stima_costo_credits, "updated_at": now_iso()}})
    await db.reel_projects.update_one({"id": project_id}, {"$set": {"video_status": "IN_GENERAZIONE", "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="REEL_VIDEO_GENERATE_STARTED",
                    entity_type="reel_video_job", entity_id=job["id"],
                    details={"task_id_remoto": avviato.task_id, "stima_costo_credits": avviato.stima_costo_credits,
                             "modello": conn["effective_model"], "durata_secondi": durata, "ratio": ratio})

    asyncio.create_task(_poll_video_job(org_id, project_id, job["id"], conn["api_key_encrypted"]))

    p2 = await db.reel_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


@router.post("/projects/{project_id}/video/jobs/{job_id}/aggiorna-stato")
async def video_job_refresh(project_id: str, job_id: str, user: dict = Depends(get_current_user)):
    """Aggiornamento manuale dello stato (sola lettura, GRATUITO): utile se il
    polling in background e' scaduto per timeout locale, o per verificare lo
    stato subito dopo un riavvio del backend (il polling in-memory non
    sopravvive a un restart, il job resta IN_GENERAZIONE finche' non richiamato)."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    job = await db.reel_video_jobs.find_one({"id": job_id, "reel_project_id": project_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job video non trovato")
    if job["status"] not in VIDEO_JOB_ATTIVI:
        return _public_job(job)
    conn = await db.video_connections.find_one({"organization_id": org_id, "provider_type": "runway"}, {"_id": 0})
    if not conn or not conn.get("api_key_encrypted"):
        raise HTTPException(status_code=409, detail="Nessuna connessione Runway configurata per verificare lo stato.")
    api_key = decrypt_secret(conn["api_key_encrypted"])
    try:
        stato = runway_gateway.recupera_stato_task(api_key, job["task_id_remoto"])
    except RunwayErroreSanificato as exc:
        raise HTTPException(status_code=502, detail=exc.messaggio)
    if stato.status in runway_gateway.STATI_TERMINALI:
        await _applica_stato_terminale(org_id, project_id, job_id, stato)
    job2 = await db.reel_video_jobs.find_one({"id": job_id}, {"_id": 0})
    return _public_job(job2)


@router.post("/projects/{project_id}/video/approve")
async def video_approve(project_id: str, user: dict = Depends(require_roles("ADMIN", "APPROVATORE"))):
    """Approva il VIDEO: consentito SOLO se esiste davvero un video riproducibile
    (video_status == VIDEO_PRONTO). Distinto e indipendente dall'approvazione
    del progetto testuale (POST .../approve)."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    if p.get("video_status") != "VIDEO_PRONTO" or not p.get("video_url"):
        raise HTTPException(status_code=409, detail="Nessun video realmente riproducibile da approvare.")
    await db.reel_projects.update_one({"id": project_id}, {"$set": {
        "video_approvato": True, "video_approvato_da": user.get("email") or user.get("id"),
        "video_approvato_at": now_iso(), "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="REEL_VIDEO_APPROVED", entity_type="reel_project", entity_id=project_id)
    # Item 13: reel completo (testo+video) approvato -> preferenza di formato
    # utile alle prossime generazioni (mai un fatto aziendale, solo uno stile
    # gia' gradito). Riassunto SOLO (hook/concept troncati), mai il contenuto
    # integrale del progetto.
    content = p.get("content") or {}
    await social_memory.record_entry(
        db, org_id, "format_preference", summary=f"reel {content.get('formato', '')} approvato".strip(),
        data={"formato": content.get("formato")}, source_project_id=project_id,
        actor=user.get("email") or user.get("id"),
    )
    await social_memory.record_entry(
        db, org_id, "content_summary", summary=f"Reel approvato — hook: {content.get('hook', '')}",
        source_project_id=project_id, actor=user.get("email") or user.get("id"),
    )
    p2 = await db.reel_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)


@router.post("/projects/{project_id}/video/richiedi-modifica")
async def video_richiedi_modifica(project_id: str, body: RichiediModificaBody,
                                  user: dict = Depends(require_roles("ADMIN", "APPROVATORE", "OPERATORE"))):
    """Richiede una nuova versione del video: NON cancella la cronologia (il
    job precedente resta consultabile in GET .../video/jobs), si limita a
    togliere l'approvazione e permettere un nuovo POST .../video/generate
    (nuova versione, nuovo costo, nuova conferma esplicita)."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    p = await db.reel_projects.find_one({"id": project_id})
    assert_same_org(p, user, "Progetto reel non trovato")
    if p.get("video_status") not in ("VIDEO_PRONTO", "BLOCCATO", "FALLITO"):
        raise HTTPException(status_code=409, detail="Richiesta di modifica video non applicabile allo stato corrente.")
    if not body.nota.strip():
        raise HTTPException(status_code=422, detail="Nota di modifica obbligatoria")
    await db.reel_projects.update_one({"id": project_id}, {"$set": {
        "video_status": "NON_RICHIESTO", "video_url": None, "video_approvato": False,
        "video_approvato_da": None, "video_approvato_at": None,
        "video_nota_revisione": body.nota.strip(), "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="REEL_VIDEO_REVISION_REQUESTED",
                    entity_type="reel_project", entity_id=project_id, details={"nota": body.nota.strip()})
    p2 = await db.reel_projects.find_one({"id": project_id}, {"_id": 0})
    return _public(p2)
