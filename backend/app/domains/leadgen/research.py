"""Lead Generation — interfaccia astratta per fonti di lead/company data, mai
legata a un singolo servizio. Ogni adapter dichiara se e' CONFIGURATO; un
adapter non configurato ritorna sempre esplicitamente NON_DISPONIBILE (mai
un finto risultato vuoto spacciato per 'nessun prospect trovato'). Il core
del Lead Generation Specialist funziona SENZA alcun adapter esterno: i due
adapter sempre disponibili sono quelli su dati gia' presenti in ACTELYA
(file caricati, campagne precedenti dello stesso tenant)."""
from __future__ import annotations

import ipaddress
import re
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

STATO_OK = "OK"
STATO_NON_DISPONIBILE = "NON_DISPONIBILE"

# ---------------- Stesso schema di protezione SSRF di domains/discovery.py ----------------
# Duplicato di proposito (non importato da discovery.py): discovery.py e' un
# modulo gia' consolidato e testato in un blocco precedente, con i propri
# punti di monkeypatch nei test — condividerlo introdurrebbe un accoppiamento
# fra due sottosistemi diversi (Research Service del CEO vs Lead Generation
# Specialist) per un risparmio di poche righe, a fronte di un rischio di
# regressione su un modulo gia' completato. La logica e' la STESSA (schema
# http/https, TLD interni, risoluzione DNS reale, verifica ripetuta a ogni
# hop di redirect, IPv4/IPv6 privato/loopback/link-local/riservato escluso).
_TLD_INTERNI = (".local", ".internal", ".test", ".invalid", ".localhost")
MAX_REDIRECT = 3
FETCH_TIMEOUT_SECONDI = 8.0
FETCH_MAX_BYTES = 300_000
CONTENT_TYPE_CONSENTITI = ("text/html", "application/xhtml+xml")

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<[^>]+>")


def _ip_pubblico(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified)


def _schema_e_host_validi(url: str) -> tuple[bool, str, int]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "", 0
    if parsed.scheme not in ("http", "https"):
        return False, "", 0
    host = (parsed.hostname or "").lower()
    if not host or host == "localhost" or any(host.endswith(tld) for tld in _TLD_INTERNI):
        return False, "", 0
    porta = parsed.port or (443 if parsed.scheme == "https" else 80)
    return True, host, porta


def _dns_pubblico(host: str, porta: int) -> bool:
    try:
        risultati = socket.getaddrinfo(host, porta, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OverflowError):
        return False
    indirizzi = {r[4][0] for r in risultati if r[4]}
    return bool(indirizzi) and all(_ip_pubblico(ip) for ip in indirizzi)


def _url_pubblico_e_risolvibile(url: str) -> bool:
    ok, host, porta = _schema_e_host_validi(url)
    return ok and _dns_pubblico(host, porta)


def fetch_pagina_pubblica(url: str) -> Optional[dict]:
    """Un solo GET, SOLO verso host pubblici e risolvibili, con redirect
    seguiti manualmente e riverificati a ogni hop (mai allow_redirects=True).
    Nessuna eccezione propagata: qualunque problema fa tornare None."""
    import requests

    corrente = url
    for _ in range(MAX_REDIRECT + 1):
        if not _url_pubblico_e_risolvibile(corrente):
            return None
        try:
            risposta = requests.get(
                corrente, timeout=FETCH_TIMEOUT_SECONDI, allow_redirects=False, stream=True,
                headers={"User-Agent": "ACTELYA-LeadGeneration/1.0"},
            )
        except Exception:
            return None
        try:
            if risposta.status_code in (301, 302, 303, 307, 308):
                location = risposta.headers.get("Location")
                if not location:
                    return None
                corrente = urljoin(corrente, location)
                continue
            if risposta.status_code != 200:
                return None
            content_type = (risposta.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if content_type and content_type not in CONTENT_TYPE_CONSENTITI:
                return None
            corpo = bytearray()
            for chunk in risposta.iter_content(chunk_size=8192):
                if chunk:
                    corpo.extend(chunk)
                if len(corpo) >= FETCH_MAX_BYTES:
                    break
            testo = bytes(corpo[:FETCH_MAX_BYTES]).decode("utf-8", errors="replace")
            titolo = None
            m = _TITLE_RE.search(testo)
            if m:
                titolo = re.sub(r"\s+", " ", m.group(1)).strip()[:200] or None
            descrizione = None
            m2 = _META_DESC_RE.search(testo)
            if m2:
                descrizione = re.sub(r"\s+", " ", m2.group(1)).strip()[:400] or None
            return {"url": corrente, "titolo": titolo, "descrizione": descrizione}
        finally:
            risposta.close()
    return None


# ==================== Interfaccia adapter ====================
@dataclass
class SourceSearchResult:
    status: str                          # OK | NON_DISPONIBILE
    records: list = field(default_factory=list)   # list[dict] campi grezzi (mai normalizzati qui)
    motivo: Optional[str] = None

    def come_dict(self) -> dict:
        return {"status": self.status, "records": self.records, "motivo": self.motivo}


class ProspectSourceAdapter(ABC):
    source_id: str = "sconosciuta"

    @property
    @abstractmethod
    def configured(self) -> bool:
        ...

    @abstractmethod
    async def search(self, *, query: str, urls: Optional[list] = None, limit: int = 20) -> SourceSearchResult:
        ...


class PublicUrlAdapter(ProspectSourceAdapter):
    """Ricerca web pubblica CONTROLLATA: nessun motore di ricerca integrato
    (nessuna API di search configurata in questo ambiente) — opera SOLO su
    URL pubblici espliciti forniti dal chiamante (mai un crawler, mai una
    query libera trasformata in navigazione autonoma). Sempre disponibile
    (non richiede credenziali), ma esplicitamente limitata: senza URL
    espliciti ritorna NON_DISPONIBILE con motivo chiaro."""
    source_id = "web_pubblico"

    @property
    def configured(self) -> bool:
        return True

    async def search(self, *, query: str = "", urls: Optional[list] = None, limit: int = 20) -> SourceSearchResult:
        import asyncio

        urls = [u for u in (urls or []) if u][:limit]
        if not urls:
            return SourceSearchResult(
                STATO_NON_DISPONIBILE, [],
                "Nessun motore di ricerca web configurato in questo ambiente: fornire URL pubblici espliciti da verificare.",
            )
        record: list[dict] = []
        for u in urls:
            pagina = await asyncio.to_thread(fetch_pagina_pubblica, u)
            if pagina is None:
                continue
            record.append({
                "sito": pagina["url"], "ragione_sociale": pagina.get("titolo") or "",
                "note": pagina.get("descrizione") or "", "fonte": pagina["url"],
            })
        return SourceSearchResult(STATO_OK, record)


class InternalDataAdapter(ProspectSourceAdapter):
    """Dati gia' presenti in ACTELYA per la stessa organizzazione (campagne
    precedenti): sempre disponibile, nessuna rete."""
    source_id = "dati_interni"

    def __init__(self, db, org_id: str):
        self._db = db
        self._org_id = org_id

    @property
    def configured(self) -> bool:
        return True

    async def search(self, *, query: str = "", urls: Optional[list] = None, limit: int = 20) -> SourceSearchResult:
        try:
            righe = await self._db.lead_companies.find(
                {"organization_id": self._org_id}, {"_id": 0}
            ).sort("created_at", -1).to_list(limit)
        except (AttributeError, TypeError):
            return SourceSearchResult(STATO_NON_DISPONIBILE, [], "Database non disponibile in questo contesto.")
        record = []
        for r in righe:
            record.append({
                "ragione_sociale": (r.get("ragione_sociale") or {}).get("value") or "",
                "dominio": (r.get("dominio") or {}).get("value") or "",
                "settore": (r.get("settore") or {}).get("value") or "",
                "citta": (r.get("citta") or {}).get("value") or "",
                "fonte": f"campagna precedente ({r.get('id')})",
            })
        return SourceSearchResult(STATO_OK, record)


class _NonConfiguratoAdapter(ProspectSourceAdapter):
    """Predisposto: nessun provider/CRM commerciale integrato in questa
    fase. Dichiara sempre NON_DISPONIBILE, mai un risultato inventato."""

    def __init__(self, source_id: str, etichetta: str):
        self.source_id = source_id
        self._etichetta = etichetta

    @property
    def configured(self) -> bool:
        return False

    async def search(self, *, query: str = "", urls: Optional[list] = None, limit: int = 20) -> SourceSearchResult:
        return SourceSearchResult(STATO_NON_DISPONIBILE, [], f"{self._etichetta}: nessun provider configurato in questa fase.")


def build_adapters(db, org_id: str) -> dict:
    """Registro degli adapter disponibili per organizzazione. Estendere qui
    quando un provider/CRM reale verra' collegato: nessun altro punto del
    dominio deve essere modificato (router.py/pipeline.py leggono solo
    'configured' e 'search()')."""
    return {
        "web_pubblico": PublicUrlAdapter(),
        "dati_interni": InternalDataAdapter(db, org_id),
        "directory_pubbliche": _NonConfiguratoAdapter("directory_pubbliche", "Directory/dataset pubblici"),
        "provider_commerciale": _NonConfiguratoAdapter("provider_commerciale", "Provider commerciale di lead/company data"),
        "crm": _NonConfiguratoAdapter("crm", "Connettore CRM"),
    }
