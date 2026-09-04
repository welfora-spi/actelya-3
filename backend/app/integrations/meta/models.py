"""Meta Graph API — modelli dati (dataclass), nessuna dipendenza da Mongo/
FastAPI: puri contenitori di risultati, stesso stile di integrations/
runway_gateway.py."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TokenValidazione:
    valido: bool
    app_id: Optional[str]
    scopes: list[str] = field(default_factory=list)
    expires_at: Optional[str] = None  # ISO 8601, None se non fornito da Meta o mai in scadenza
    messaggio: str = ""


@dataclass
class PageInfo:
    page_id: str
    page_name: str
    instagram_business_account_id: Optional[str]


@dataclass
class InstagramAccountInfo:
    ig_user_id: str
    username: str


@dataclass
class PubblicazioneRiuscita:
    external_post_id: str
    permalink: Optional[str] = None
    raw: dict = field(default_factory=dict)  # risposta grezza Graph API (redatta: mai un token al suo interno)


@dataclass
class ContainerStato:
    container_id: str
    status_code: str  # "IN_PROGRESS" | "FINISHED" | "ERROR" | "EXPIRED" | "PUBLISHED"
    status: Optional[str] = None  # descrizione testuale, se fornita da Meta


@dataclass
class MetricheRaccolte:
    data_available: bool
    impressions: Optional[int] = None
    reach: Optional[int] = None
    views: Optional[int] = None  # plays/views per video/reel
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    saves: Optional[int] = None
    clicks: Optional[int] = None
    note: str = ""
