"""Lead Generation — normalizzazione dei valori con provenienza esplicita.

Ogni campo normalizzato conserva SEMPRE il valore originale (mai perso, mai
sovrascritto) e riceve un 'method' tra models.DATA_METHOD: mai un dato
mancante viene inventato, mai un'inferenza viene presentata come un fatto
verificato (resta 'INFERITO', non diventa mai 'VERIFICATO' automaticamente)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from .models import CANONICAL_FIELDS

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_DIGITS_RE = re.compile(r"[^\d+]")
_BOOL_TRUE = {"si", "sì", "yes", "true", "1", "vero", "x"}
_BOOL_FALSE = {"no", "false", "0", "falso", ""}


@dataclass
class NormalizedField:
    original: str
    value: Optional[str]
    method: str

    def come_dict(self) -> dict:
        return {"original": self.original, "value": self.value, "method": self.method}


def _vuoto(originale: str) -> NormalizedField:
    return NormalizedField(original=originale, value=None, method="MANCANTE")


def normalize_email(raw: str, *, method: str = "ESTRATTO") -> NormalizedField:
    originale = (raw or "").strip()
    if not originale:
        return _vuoto(originale)
    candidato = originale.lower()
    if not _EMAIL_RE.match(candidato):
        return NormalizedField(original=originale, value=None, method="NON_VERIFICATO")
    return NormalizedField(original=originale, value=candidato, method=method)


def normalize_phone(raw: str, *, method: str = "ESTRATTO") -> NormalizedField:
    originale = (raw or "").strip()
    if not originale:
        return _vuoto(originale)
    ripulito = _PHONE_DIGITS_RE.sub("", originale)
    cifre = ripulito.lstrip("+")
    if len(cifre) < 6 or not cifre.isdigit():
        return NormalizedField(original=originale, value=None, method="NON_VERIFICATO")
    if not ripulito.startswith("+"):
        # Nessun prefisso internazionale dichiarato: non lo si inventa (mai
        # assumere +39 o un altro paese senza segnale esplicito), si
        # normalizza solo la punteggiatura.
        return NormalizedField(original=originale, value=cifre, method=method)
    return NormalizedField(original=originale, value=ripulito, method=method)


def normalize_domain(raw: str, *, method: str = "ESTRATTO") -> NormalizedField:
    originale = (raw or "").strip()
    if not originale:
        return _vuoto(originale)
    candidato = originale if "://" in originale else f"//{originale}"
    host = (urlparse(candidato).netloc or "").lower()
    host = host.split(":")[0]  # rimuove eventuale porta
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return NormalizedField(original=originale, value=None, method="NON_VERIFICATO")
    return NormalizedField(original=originale, value=host, method=method)


def normalize_text(raw: str, *, method: str = "ESTRATTO", titlecase: bool = False) -> NormalizedField:
    originale = (raw or "").strip()
    if not originale:
        return _vuoto(originale)
    valore = re.sub(r"\s+", " ", originale)
    if titlecase:
        valore = valore.title()
    return NormalizedField(original=originale, value=valore, method=method)


def normalize_boolean(raw: str, *, method: str = "ESTRATTO") -> NormalizedField:
    originale = (raw or "").strip()
    candidato = originale.lower()
    if candidato in _BOOL_TRUE:
        return NormalizedField(original=originale, value="true", method=method)
    if candidato in _BOOL_FALSE:
        return NormalizedField(original=originale, value="false" if originale else None,
                               method=method if originale else "MANCANTE")
    return NormalizedField(original=originale, value=None, method="NON_VERIFICATO")


def normalize_number(raw: str, *, method: str = "ESTRATTO") -> NormalizedField:
    originale = (raw or "").strip()
    if not originale:
        return _vuoto(originale)
    pulito = originale.replace(".", "").replace(",", ".") if "," in originale and "." in originale else originale.replace(",", ".")
    try:
        numero = float(pulito)
    except ValueError:
        return NormalizedField(original=originale, value=None, method="NON_VERIFICATO")
    return NormalizedField(original=originale, value=str(numero), method=method)


# Campo canonico -> normalizzatore dedicato (default: normalize_text).
_NORMALIZERS = {
    "email": normalize_email,
    "telefono": normalize_phone,
    "sito": normalize_domain,
    "dominio": normalize_domain,
    "dimensione": normalize_number,
    "fatturato": normalize_number,
    "dipendenti": normalize_number,
    "cliente_esistente": normalize_boolean,
    "ragione_sociale": lambda r, method="ESTRATTO": normalize_text(r, method=method),
    "citta": lambda r, method="ESTRATTO": normalize_text(r, method=method, titlecase=True),
    "provincia": lambda r, method="ESTRATTO": normalize_text(r, method=method, titlecase=True),
    "regione": lambda r, method="ESTRATTO": normalize_text(r, method=method, titlecase=True),
    "paese": lambda r, method="ESTRATTO": normalize_text(r, method=method, titlecase=True),
}


def normalize_record(mapped_row: dict, *, method: str = "ESTRATTO") -> dict:
    """mapped_row: {campo_canonico: valore_grezzo}. Ritorna
    {campo_canonico: NormalizedField.come_dict()} per OGNI campo canonico
    noto presente in mapped_row (i campi assenti restano assenti dal
    risultato, mai inventati come MANCANTE su un campo mai fornito)."""
    out: dict = {}
    for campo, grezzo in mapped_row.items():
        if campo not in CANONICAL_FIELDS:
            continue
        normalizzatore = _NORMALIZERS.get(campo, normalize_text)
        out[campo] = normalizzatore(str(grezzo) if grezzo is not None else "", method=method).come_dict()
    return out
