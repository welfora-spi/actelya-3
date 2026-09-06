"""Content Creator — costanti, stati e corpi Pydantic. Nessuna logica qui."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Ogni tipo di contenuto che l'agente sa produrre. Un tipo non richiesto
# esplicitamente viene scelto da decision.py in base a canale/fase funnel —
# mai lasciato all'LLM (la decisione di COSA produrre precede la chiamata,
# non ne e' un effetto collaterale).
CONTENT_TYPES = (
    "post_social", "caption", "carosello_testuale", "reel_script", "storyboard",
    "video_script", "voiceover_script", "ad_copy", "headline", "cta",
    "landing_copy", "email", "newsletter", "articolo_blog", "contenuto_seo",
    "comunicazione_commerciale", "offerta", "contenuto_informativo",
    "brief_immagine", "brief_video", "brief_audio",
)

# Tipi che sono un BRIEF per un asset multimediale reale prodotto altrove
# (mai duplicato qui): il Content Creator prepara testo/prompt, poi collega
# lo stato del progetto reale (domains/reel.py per video, domains/flyer.py
# per immagini) tramite pipeline.py::link_media_project/sync_media_status.
MEDIA_DEPENDENT_TYPES: dict[str, str] = {
    "storyboard": "reel", "video_script": "reel", "voiceover_script": "reel",
    "brief_video": "reel", "brief_immagine": "flyer",
}

FUNNEL_STAGES = ("TOFU", "MOFU", "BOFU", "RETENTION")

STATUS = (
    "BOZZA", "GENERAZIONE_IN_CORSO", "ESITO_INCERTO", "BLOCCATO",
    "IN_ATTESA_APPROVAZIONE", "APPROVATO", "RIFIUTATO",
    "IN_ATTESA_ASSET", "COMPLETATO",
)


class ContentRequestBody(BaseModel):
    objective: str = Field(min_length=1)
    channel: str = "generico"
    funnel_stage: str = "MOFU"
    content_type: Optional[str] = None   # se assente, lo decide l'agente (decision.py)
    campaign_id: Optional[str] = None
    tone_override: Optional[str] = None
    constraints: str = ""
    brief: str = ""


class ConfirmBody(BaseModel):
    confirm: bool = False


class ApprovalBody(BaseModel):
    approve: bool
    note: str = ""


class RevisionRequestBody(BaseModel):
    note: str = Field(min_length=1)


class ResolveUncertainBody(BaseModel):
    note: str = ""


class LinkMediaBody(BaseModel):
    kind: str  # "reel" | "flyer"
    project_id: str = Field(min_length=1)
