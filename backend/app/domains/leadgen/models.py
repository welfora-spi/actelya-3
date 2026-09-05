"""Lead Generation — costanti, stati e corpi Pydantic condivisi da tutto il
dominio. Nessuna logica qui: solo la forma dei dati (vedi pipeline.py per
l'orchestrazione, compliance.py/scoring.py/dedup.py per le regole)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# ==================== File ====================
ALLOWED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".pdf", ".docx", ".txt"}
ALLOWED_MIME_BY_EXT = {
    ".csv": {"text/csv", "application/vnd.ms-excel", "text/plain", "application/csv"},
    ".tsv": {"text/tab-separated-values", "text/plain"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "application/zip", "application/octet-stream"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "application/zip", "application/octet-stream"},
    ".txt": {"text/plain"},
}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024        # 15 MB per file
MAX_ROWS_PARSED = 20_000                      # righe tabellari lette al massimo
MAX_COLS_PARSED = 80                          # colonne lette al massimo
MAX_TEXT_CHARS_EXTRACTED = 400_000            # testo estratto da PDF/DOCX/TXT

FILE_STATUS = ("CARICATO", "VALIDATO", "RIFIUTATO")

# ==================== Import job ====================
JOB_STATUS = ("UPLOADED", "PARSING", "NORMALIZED", "SCORING", "REVIEW_REQUIRED",
             "READY_FOR_APPROVAL", "APPROVED", "EXPORTED", "FAILED", "PARTIAL", "CANCELLED")

# ==================== Provenienza/stato di ciascun valore ====================
DATA_METHOD = ("FORNITO", "ESTRATTO", "PUBBLICO", "VERIFICATO", "INFERITO",
              "NON_VERIFICATO", "CONTRADDITTORIO", "MANCANTE", "SCADUTO")

# ==================== Qualificazione lead ====================
QUALIFICATION_STATUS = ("QUALIFIED", "REVIEW_REQUIRED", "INCOMPLETE", "EXCLUDED", "DO_NOT_CONTACT")

# ==================== Gate compliance ====================
COMPLIANCE_STATUS = ("READY", "NEEDS_CLARIFICATION", "REVIEW_REQUIRED", "APPROVAL_REQUIRED", "BLOCKED", "DO_NOT_CONTACT")

# ==================== Campagna ====================
CAMPAIGN_STATUS = ("BOZZA", "IN_LAVORAZIONE", "REVIEW_REQUIRED", "READY_FOR_APPROVAL", "APPROVATA", "ESPORTATA", "ANNULLATA")

EXPORT_FORMATS = ("csv", "xlsx")

# Colonne target riconosciute dal mapping automatico (etichetta -> nome campo canonico).
CANONICAL_FIELDS = (
    "ragione_sociale", "nome", "cognome", "ruolo", "email", "telefono", "sito", "dominio",
    "settore", "citta", "provincia", "regione", "paese", "dimensione", "fatturato",
    "dipendenti", "fonte", "consenso", "note", "stato_crm", "cliente_esistente", "ultima_interazione",
)


# ==================== Corpi richiesta ====================
class MappingBody(BaseModel):
    # {nome_colonna_file: campo_canonico}
    mapping: dict[str, str] = Field(default_factory=dict)


class ICPBody(BaseModel):
    settori_inclusi: list[str] = Field(default_factory=list)
    settori_esclusi: list[str] = Field(default_factory=list)
    localita: list[str] = Field(default_factory=list)
    dimensione_min: Optional[int] = None
    dimensione_max: Optional[int] = None
    fatturato_min: Optional[float] = None
    ruoli_decisionali: list[str] = Field(default_factory=list)
    segnali_ammessi: list[str] = Field(default_factory=list)
    incompatibilita: list[str] = Field(default_factory=list)


class CampaignBody(BaseModel):
    name: str
    goal_id: Optional[str] = None
    plan_id: Optional[str] = None
    task_id: Optional[str] = None
    icp: ICPBody = Field(default_factory=ICPBody)
    channels: list[str] = Field(default_factory=list)
    message: str = ""
    target_quantity: Optional[int] = None
    budget: Optional[float] = None
    deadline: Optional[str] = None
    owner: Optional[str] = None
    kpi: list[str] = Field(default_factory=list)
    exclude_existing_customers: bool = True


class SearchBody(BaseModel):
    campaign_id: str
    query: str = ""
    settori: list[str] = Field(default_factory=list)
    localita: list[str] = Field(default_factory=list)
    # Limite massimo esplicito: una ricerca e' un'azione one-shot verso
    # adapter esterni/interni, non una lista paginabile (i record creati
    # entrano comunque nella lista lead, quella si' paginata — vedi
    # pagination.py). 50 e' un tetto di sicurezza, mai superabile dal client.
    max_risultati: int = Field(default=20, ge=1, le=50)


class MergeDecisionBody(BaseModel):
    action: str  # "MERGE" | "KEEP_SEPARATE"


class ExportBody(BaseModel):
    campaign_id: str
    format: str = "csv"
    include_persons: bool = True


class ReviewApprovalBody(BaseModel):
    approve: bool
    note: str = ""
