"""Lead Generation Specialist — endpoint HTTP. Ogni endpoint applica
autenticazione (get_current_user), ruoli sulle scritture (require_roles),
isolamento per organizzazione (assert_same_org) e non restituisce mai un
percorso assoluto del filesystem host."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response

from ...audit import log_audit
from ...config import DEFAULT_ORG_ID
from ...db import db
from ...deps import assert_same_org, get_current_user, rate_limit, require_roles
from ...models import base_record, new_id, now_iso, touch
from . import pipeline
from .compliance import evaluate_compliance
from .export import export_records
from .mapping import auto_map_columns
from .models import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_BY_EXT,
    MAX_FILE_SIZE_BYTES,
    CampaignBody,
    ExportBody,
    MappingBody,
    MergeDecisionBody,
    ReviewApprovalBody,
    SearchBody,
)
from .pagination import DEFAULT_PAGE_SIZE, paginate, resolve_sort
from .parsers import ParseError, parse_file
from .research import build_adapters
from .scoring import score_record
from .storage import compute_hash, delete_file, read_file_bytes, save_file_bytes

router = APIRouter(prefix="/leadgen", tags=["leadgen"])


def _public_file(f: dict) -> dict:
    return {k: v for k, v in f.items() if k not in ("_id", "storage_path")}


def _public_job(j: dict) -> dict:
    return {k: v for k, v in j.items() if k not in ("_id", "columns", "rows", "mapping")}


# ==================== File ====================
@router.post("/files")
async def upload_file(upload: UploadFile = File(...), user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rate_limit(f"leadgen_upload:{org_id}", max_calls=20, window_seconds=60)

    nome_originale = upload.filename or "file"
    estensione = os.path.splitext(nome_originale)[1].lower()
    if estensione not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Estensione non supportata: '{estensione}'.")

    contenuto = await upload.read()
    if len(contenuto) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"File troppo grande: limite {MAX_FILE_SIZE_BYTES // (1024*1024)} MB.")
    if not contenuto:
        raise HTTPException(status_code=400, detail="File vuoto.")

    mime_dichiarato = (upload.content_type or "").split(";")[0].strip().lower()
    consentiti = ALLOWED_MIME_BY_EXT.get(estensione, set())
    if mime_dichiarato and consentiti and mime_dichiarato not in consentiti:
        raise HTTPException(status_code=400,
                            detail=f"Tipo MIME '{mime_dichiarato}' non coerente con l'estensione '{estensione}'.")

    hash_file = compute_hash(contenuto)
    esistente = await db.lead_files.find_one({"organization_id": org_id, "hash": hash_file}, {"_id": 0})
    if esistente:
        return _public_file(esistente)  # idempotente: stesso file (stesso hash) gia' caricato

    try:
        risultato_parsing = parse_file(estensione, contenuto)
    except ParseError as exc:
        rec = base_record(org_id, user["id"])
        rec.update({
            "id": new_id("leadfile"), "filename": nome_originale, "extension": estensione,
            "mime_type": mime_dichiarato, "size_bytes": len(contenuto), "hash": hash_file,
            "status": "RIFIUTATO", "rejection_reason": str(exc), "columns": [], "warnings": [],
        })
        await db.lead_files.insert_one(rec)
        await log_audit(org_id=org_id, user=user, action="LEADGEN_FILE_REJECTED",
                        entity_type="lead_file", entity_id=rec["id"], details={"reason": str(exc)})
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    file_id = new_id("leadfile")
    save_file_bytes(org_id, file_id, contenuto)  # mai il nome originale sul filesystem

    rec = base_record(org_id, user["id"])
    rec.update({
        "id": file_id, "filename": nome_originale, "extension": estensione,
        "mime_type": mime_dichiarato, "size_bytes": len(contenuto), "hash": hash_file,
        "status": "VALIDATO", "rejection_reason": None,
        "columns": risultato_parsing.columns, "row_count": len(risultato_parsing.rows),
        "has_free_text": bool(risultato_parsing.testo_libero), "warnings": risultato_parsing.avvisi,
        "suggested_mapping": auto_map_columns(risultato_parsing.columns),
    })
    await db.lead_files.insert_one(rec)
    await log_audit(org_id=org_id, user=user, action="LEADGEN_FILE_UPLOADED",
                    entity_type="lead_file", entity_id=file_id, details={"filename": nome_originale, "hash": hash_file})
    return _public_file(rec)


_FILES_SORT = {"created_at": "created_at", "filename": "filename", "size_bytes": "size_bytes", "status": "status"}


@router.get("/files")
async def list_files(page: int = 1, page_size: int = DEFAULT_PAGE_SIZE, status: Optional[str] = None,
                     sort_by: str = "created_at", sort_dir: str = "desc",
                     user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    query: dict = {"organization_id": org_id}
    if status:
        query["status"] = status
    campo, direzione = resolve_sort(sort_by, sort_dir, _FILES_SORT, "created_at")
    risultato = await paginate(db.lead_files, query, page=page, page_size=page_size,
                               sort_field=campo, direction=direzione)
    risultato["items"] = [_public_file(f) for f in risultato["items"]]
    return risultato


@router.get("/files/{file_id}")
async def get_file(file_id: str, user: dict = Depends(get_current_user)):
    f = await db.lead_files.find_one({"id": file_id}, {"_id": 0})
    assert_same_org(f, user, "File non trovato")
    return _public_file(f)


@router.get("/files/{file_id}/preview")
async def preview_file(file_id: str, righe: int = 10, user: dict = Depends(get_current_user)):
    f = await db.lead_files.find_one({"id": file_id})
    assert_same_org(f, user, "File non trovato")
    if f["status"] != "VALIDATO":
        raise HTTPException(status_code=409, detail="File non validato: nessuna anteprima disponibile.")
    try:
        contenuto = read_file_bytes(f["organization_id"], file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Contenuto file non piu' disponibile.")
    risultato = parse_file(f["extension"], contenuto)
    return {
        "columns": risultato.columns, "rows": risultato.rows[:max(1, min(righe, 50))],
        "suggested_mapping": auto_map_columns(risultato.columns), "warnings": risultato.avvisi,
        "testo_libero_estratto": bool(risultato.testo_libero),
    }


@router.delete("/files/{file_id}")
async def delete_file_endpoint(file_id: str, user: dict = Depends(require_roles("ADMIN"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    f = await db.lead_files.find_one({"id": file_id})
    assert_same_org(f, user, "File non trovato")
    delete_file(org_id, file_id)
    await db.lead_files.delete_one({"id": file_id})
    await log_audit(org_id=org_id, user=user, action="LEADGEN_FILE_DELETED",
                    entity_type="lead_file", entity_id=file_id)
    return {"ok": True}


# ==================== Campagne ====================
def _public_campaign(c: dict) -> dict:
    return {k: v for k, v in c.items() if k != "_id"}


@router.post("/campaigns")
async def create_campaign(body: CampaignBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rec = base_record(org_id, user["id"])
    rec.update({
        "id": new_id("leadcamp"), "name": body.name, "goal_id": body.goal_id, "plan_id": body.plan_id,
        "task_id": body.task_id, "icp": body.icp.model_dump(), "channels": body.channels,
        "message": body.message, "target_quantity": body.target_quantity, "budget": body.budget,
        "deadline": body.deadline, "owner": body.owner or user["id"], "kpi": body.kpi,
        "exclude_existing_customers": body.exclude_existing_customers,
        "status": "BOZZA", "version": 1,
    })
    await db.lead_campaigns.insert_one(rec)
    await log_audit(org_id=org_id, user=user, action="LEADGEN_CAMPAIGN_CREATED",
                    entity_type="lead_campaign", entity_id=rec["id"], details={"name": body.name})
    return _public_campaign(rec)


_CAMPAIGNS_SORT = {"created_at": "created_at", "name": "name", "status": "status"}


@router.get("/campaigns")
async def list_campaigns(page: int = 1, page_size: int = DEFAULT_PAGE_SIZE, status: Optional[str] = None,
                         sort_by: str = "created_at", sort_dir: str = "desc",
                         user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    query: dict = {"organization_id": org_id}
    if status:
        query["status"] = status
    campo, direzione = resolve_sort(sort_by, sort_dir, _CAMPAIGNS_SORT, "created_at")
    risultato = await paginate(db.lead_campaigns, query, page=page, page_size=page_size,
                               sort_field=campo, direction=direzione)
    risultato["items"] = [_public_campaign(c) for c in risultato["items"]]
    return risultato


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, user: dict = Depends(get_current_user)):
    c = await db.lead_campaigns.find_one({"id": campaign_id}, {"_id": 0})
    assert_same_org(c, user, "Campagna non trovata")
    return _public_campaign(c)


# ==================== Mapping + import ====================
@router.post("/files/{file_id}/import")
async def start_import(file_id: str, campaign_id: str, body: MappingBody,
                       user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    f = await db.lead_files.find_one({"id": file_id})
    assert_same_org(f, user, "File non trovato")
    if f["status"] != "VALIDATO":
        raise HTTPException(status_code=409, detail="File non validato: import non possibile.")
    campagna = await db.lead_campaigns.find_one({"id": campaign_id})
    assert_same_org(campagna, user, "Campagna non trovata")

    # Idempotenza (item 16): stesso file + stessa campagna + stesso mapping
    # gia' importato -> ritorna il job esistente, mai un secondo import.
    chiave_idempotenza = f"{file_id}:{campaign_id}:{hash(frozenset(body.mapping.items()))}"
    esistente = await db.lead_import_jobs.find_one(
        {"organization_id": org_id, "idempotency_key": chiave_idempotenza}, {"_id": 0}
    )
    if esistente:
        return _public_job(esistente)

    try:
        contenuto = read_file_bytes(org_id, file_id)
        risultato = parse_file(f["extension"], contenuto)
    except (FileNotFoundError, ParseError) as exc:
        raise HTTPException(status_code=409, detail=f"Impossibile rileggere il file per l'import: {exc}")

    mapping = body.mapping or auto_map_columns(risultato.columns)
    job = base_record(org_id, user["id"])
    job.update({
        "id": new_id("leadjob"), "file_id": file_id, "campaign_id": campaign_id, "mapping": mapping,
        "columns": risultato.columns, "rows": risultato.rows, "status": "UPLOADED",
        "idempotency_key": chiave_idempotenza, "started_at": None, "finished_at": None,
        "counts": {"parsed": 0, "normalized": 0, "qualified": 0, "review_required": 0,
                  "incomplete": 0, "excluded": 0, "do_not_contact": 0,
                  "duplicates_exact": 0, "duplicates_probable": 0},
        "warnings": risultato.avvisi,
    })
    await db.lead_import_jobs.insert_one(job)
    await db.lead_campaigns.update_one({"id": campaign_id}, {"$set": {"status": "IN_LAVORAZIONE", "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="LEADGEN_IMPORT_STARTED",
                    entity_type="lead_import_job", entity_id=job["id"],
                    details={"file_id": file_id, "campaign_id": campaign_id})
    return _public_job(job)


@router.get("/import-jobs/{job_id}")
async def get_import_job(job_id: str, user: dict = Depends(get_current_user)):
    j = await db.lead_import_jobs.find_one({"id": job_id}, {"_id": 0})
    assert_same_org(j, user, "Job di import non trovato")
    return _public_job(j)


# ==================== Lead (aziende/persone) ====================
_LEADS_SORT = {
    "score": "score", "created_at": "created_at",
    "ragione_sociale": "ragione_sociale.value", "qualification_status": "qualification_status",
}


@router.get("/campaigns/{campaign_id}/leads")
async def list_leads(campaign_id: str, tipo: str = "aziende", qualification_status: Optional[str] = None,
                     settore: Optional[str] = None, citta: Optional[str] = None,
                     page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
                     sort_by: str = "score", sort_dir: str = "desc",
                     user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    campagna = await db.lead_campaigns.find_one({"id": campaign_id})
    assert_same_org(campagna, user, "Campagna non trovata")

    collezione = db.lead_persons if tipo == "persone" else db.lead_companies
    query: dict = {"organization_id": org_id, "campaign_id": campaign_id}
    if qualification_status:
        query["qualification_status"] = qualification_status
    if settore:
        query["settore.value"] = settore
    if citta:
        query["citta.value"] = citta

    campo, direzione = resolve_sort(sort_by, sort_dir, _LEADS_SORT, "score")
    return await paginate(collezione, query, page=page, page_size=page_size, sort_field=campo, direction=direzione)


# ==================== Deduplica ====================
_DUPLICATES_SORT = {"created_at": "created_at", "similarita": "similarita"}


@router.get("/campaigns/{campaign_id}/duplicates")
async def list_duplicates(campaign_id: str, status: str = "PENDING",
                          page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
                          sort_by: str = "created_at", sort_dir: str = "asc",
                          user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    campagna = await db.lead_campaigns.find_one({"id": campaign_id})
    assert_same_org(campagna, user, "Campagna non trovata")
    query = {"organization_id": org_id, "campaign_id": campaign_id, "status": status}
    campo, direzione = resolve_sort(sort_by, sort_dir, _DUPLICATES_SORT, "created_at")
    return await paginate(db.lead_dedup_reviews, query, page=page, page_size=page_size,
                          sort_field=campo, direction=direzione)


@router.post("/duplicates/{review_id}/decision")
async def decide_duplicate(review_id: str, body: MergeDecisionBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    review = await db.lead_dedup_reviews.find_one({"id": review_id})
    assert_same_org(review, user, "Review duplicato non trovata")
    if review["status"] != "PENDING":
        raise HTTPException(status_code=409, detail=f"Review gia' decisa ({review['status']}).")
    if body.action not in ("MERGE", "KEEP_SEPARATE"):
        raise HTTPException(status_code=400, detail="Azione non valida: usare 'MERGE' o 'KEEP_SEPARATE'.")
    esito = await pipeline.apply_merge_decision(db, review, action=body.action, actor=user["id"])
    await log_audit(org_id=review["organization_id"], user=user, action="LEADGEN_DUPLICATE_DECIDED",
                    entity_type="lead_dedup_review", entity_id=review_id, details={"action": body.action})
    return esito


# ==================== Ricerca prospect ====================
@router.post("/search")
async def search_prospects(body: SearchBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    campagna = await db.lead_campaigns.find_one({"id": body.campaign_id})
    assert_same_org(campagna, user, "Campagna non trovata")
    rate_limit(f"leadgen_search:{org_id}", max_calls=20, window_seconds=60)

    adapters = build_adapters(db, org_id)
    risultati_per_fonte = {}
    nuovi_record = []
    for source_id, adapter in adapters.items():
        if not adapter.configured:
            risultati_per_fonte[source_id] = {"status": "NON_DISPONIBILE", "motivo": f"{source_id}: non configurato."}
            continue
        esito = await adapter.search(query=body.query, urls=None, limit=body.max_risultati)
        risultati_per_fonte[source_id] = esito.come_dict()
        if esito.status == "OK":
            for grezzo in esito.records:
                nuovi_record.append({"grezzo": grezzo, "fonte": source_id})

    icp = (campagna.get("icp") or {})
    escludi_clienti = campagna.get("exclude_existing_customers", True)
    creati = []
    from .normalize import normalize_record
    for voce in nuovi_record:
        normalizzato = normalize_record(voce["grezzo"], method="PUBBLICO")
        if not normalizzato:
            continue
        decisione = evaluate_compliance(normalizzato, is_person=False)
        esito_score = score_record(normalizzato, icp, is_person=False, compliance_status=decisione.status,
                                   exclude_existing_customers=escludi_clienti)
        documento = {
            "id": new_id("lead"), **normalizzato, "organization_id": org_id, "campaign_id": body.campaign_id,
            "import_job_id": None, "is_person": False,
            "score": esito_score.score, "score_components": [c.come_dict() for c in esito_score.componenti],
            "confidence": esito_score.confidence, "missing_data": esito_score.dati_mancanti,
            "qualification_status": esito_score.qualification_status, "compliance_status": decisione.status,
            "compliance_motivi": decisione.motivi, "rules_applied": esito_score.regole_applicate,
            "merge_history": [], "merged_from_ids": [], "created_at": now_iso(),
            "created_by": user["id"], "updated_at": now_iso(),
        }
        await db.lead_companies.insert_one(documento)
        creati.append(documento["id"])

    await log_audit(org_id=org_id, user=user, action="LEADGEN_SEARCH_EXECUTED",
                    entity_type="lead_campaign", entity_id=body.campaign_id,
                    details={"fonti": list(risultati_per_fonte.keys()), "record_creati": len(creati)})
    return {"sources": risultati_per_fonte, "created_record_ids": creati}


# ==================== Approvazione + export + handoff ====================
@router.post("/campaigns/{campaign_id}/approve")
async def approve_campaign(campaign_id: str, body: ReviewApprovalBody, user: dict = Depends(require_roles("ADMIN", "APPROVATORE"))):
    campagna = await db.lead_campaigns.find_one({"id": campaign_id})
    assert_same_org(campagna, user, "Campagna non trovata")
    pending = await db.lead_dedup_reviews.count_documents(
        {"campaign_id": campaign_id, "status": "PENDING"}
    )
    if body.approve and pending:
        raise HTTPException(status_code=409, detail=f"{pending} duplicati ancora da revisionare prima dell'approvazione.")
    nuovo_stato = "APPROVATA" if body.approve else campagna["status"]
    touch(campagna, user["id"], f"Approvazione lead gen: {'approvata' if body.approve else 'non approvata'} — {body.note}".strip())
    await db.lead_campaigns.update_one({"id": campaign_id}, {"$set": {"status": nuovo_stato, "updated_at": now_iso(),
                                                                       "change_history": campagna["change_history"]}})
    await log_audit(org_id=campagna["organization_id"], user=user, action="LEADGEN_CAMPAIGN_APPROVAL",
                    entity_type="lead_campaign", entity_id=campaign_id,
                    details={"approve": body.approve, "note": body.note})
    return {"id": campaign_id, "status": nuovo_stato}


@router.post("/campaigns/{campaign_id}/export")
async def export_campaign(campaign_id: str, body: ExportBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    campagna = await db.lead_campaigns.find_one({"id": campaign_id})
    assert_same_org(campagna, user, "Campagna non trovata")
    if campagna["status"] != "APPROVATA":
        raise HTTPException(status_code=409, detail="La campagna deve essere approvata prima dell'esportazione.")
    if body.format not in ("csv", "xlsx"):
        raise HTTPException(status_code=400, detail="Formato export non valido: usare 'csv' o 'xlsx'.")

    aziende = await db.lead_companies.find({"campaign_id": campaign_id}, {"_id": 0}).to_list(5000)
    persone = await db.lead_persons.find({"campaign_id": campaign_id}, {"_id": 0}).to_list(5000) if body.include_persons else []
    record = aziende + persone
    contenuto, content_type, estensione = export_records(record, body.format)

    esportazione = base_record(org_id, user["id"])
    esportazione.update({
        "id": new_id("leadexport"), "campaign_id": campaign_id, "format": body.format,
        "record_count": len(record),
    })
    await db.lead_exports.insert_one(esportazione)
    await db.lead_campaigns.update_one({"id": campaign_id}, {"$set": {"status": "ESPORTATA", "updated_at": now_iso()}})
    await log_audit(org_id=org_id, user=user, action="LEADGEN_CAMPAIGN_EXPORTED",
                    entity_type="lead_campaign", entity_id=campaign_id,
                    details={"format": body.format, "record_count": len(record)})
    return Response(content=contenuto, media_type=content_type,
                    headers={"Content-Disposition": f"attachment; filename=lead_{campaign_id}.{estensione}"})


@router.post("/campaigns/{campaign_id}/handoff")
async def handoff_campaign(campaign_id: str, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    """Pacchetto di handoff verso gli altri agenti (Copywriter, Social Media
    Manager, ecc.): SOLO segmenti/aggregati ammessi, mai dati personali non
    necessari. Richiede la campagna approvata (item 12: nessuna spesa/uso
    esterno senza approvazione)."""
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    campagna = await db.lead_campaigns.find_one({"id": campaign_id})
    assert_same_org(campagna, user, "Campagna non trovata")
    if campagna["status"] not in ("APPROVATA", "ESPORTATA"):
        raise HTTPException(status_code=409, detail="La campagna deve essere approvata prima dell'handoff.")

    aziende_qualificate = await db.lead_companies.count_documents(
        {"campaign_id": campaign_id, "qualification_status": "QUALIFIED"}
    )
    pacchetto = base_record(org_id, user["id"])
    pacchetto.update({
        "id": new_id("leadhandoff"), "campaign_id": campaign_id, "type": "lead_handoff_package",
        "status": "PRONTO", "qualified_count": aziende_qualificate,
        "icp": campagna.get("icp"), "channels": campagna.get("channels"),
    })
    await db.lead_handoff_packages.insert_one(pacchetto)
    await log_audit(org_id=org_id, user=user, action="LEADGEN_HANDOFF_CREATED",
                    entity_type="lead_campaign", entity_id=campaign_id,
                    details={"qualified_count": aziende_qualificate})
    return {k: v for k, v in pacchetto.items() if k != "_id"}
