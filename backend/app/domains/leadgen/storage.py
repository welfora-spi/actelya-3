"""Lead Generation — storage sicuro dei file caricati.

I byte del file vivono SOLO su disco locale (mai in Mongo, mai nel repository
-- 'uploads/' e' gia' in .gitignore), sotto un percorso per organizzazione,
nominato con un id GENERATO (mai il nome file originale: previene path
traversal per costruzione, non solo per controllo). Il nome originale, il
tipo e la provenienza restano solo metadati in Mongo (domains/leadgen/router.py)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

# backend/app/domains/leadgen/storage.py -> parents[3] = backend/
BASE_UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads" / "leadgen"

_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_-]")


def _safe_segment(value: str) -> str:
    """Riduce un id a soli caratteri sicuri per un nome di file/cartella:
    difesa in profondita', anche se org_id/file_id sono sempre generati da
    new_id() (mai testo utente) — mai fidarsi ciecamente di un id."""
    cleaned = _SAFE_SEGMENT_RE.sub("", value or "")
    if not cleaned:
        raise ValueError("Identificativo non valido per lo storage file.")
    return cleaned


def _org_dir(org_id: str) -> Path:
    d = BASE_UPLOAD_DIR / _safe_segment(org_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_within(base: Path, path: Path) -> Path:
    resolved = path.resolve()
    base_resolved = base.resolve()
    if base_resolved not in resolved.parents and resolved != base_resolved:
        raise ValueError("Percorso file al di fuori dell'area consentita.")
    return resolved


def compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def save_file_bytes(org_id: str, file_id: str, content: bytes) -> str:
    """Ritorna il percorso relativo (org_id/file_id) salvato — mai il
    percorso assoluto del filesystem host, che non deve mai raggiungere il
    frontend o la risposta di un endpoint."""
    org_dir = _org_dir(org_id)
    target = org_dir / _safe_segment(file_id)
    _resolve_within(BASE_UPLOAD_DIR, target)
    target.write_bytes(content)
    return f"{org_id}/{file_id}"


def read_file_bytes(org_id: str, file_id: str) -> bytes:
    org_dir = _org_dir(org_id)
    target = org_dir / _safe_segment(file_id)
    resolved = _resolve_within(BASE_UPLOAD_DIR, target)
    if not resolved.is_file():
        raise FileNotFoundError(f"File non trovato: {file_id}")
    return resolved.read_bytes()


def delete_file(org_id: str, file_id: str) -> bool:
    org_dir = _org_dir(org_id)
    target = org_dir / _safe_segment(file_id)
    resolved = _resolve_within(BASE_UPLOAD_DIR, target)
    if resolved.is_file():
        resolved.unlink()
        return True
    return False
