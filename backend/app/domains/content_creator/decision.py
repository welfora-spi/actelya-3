"""Content Creator — motore di decisione DETERMINISTICO (nessuna chiamata AI):
dato un obiettivo, un canale e una fase di funnel, decide QUALE contenuto
produrre e perche'. La decisione precede sempre la generazione e non dipende
mai dal suo risultato (stesso principio di brain/capability_selector.py per
la scelta degli agenti — una decisione tracciabile, mai un effetto
collaterale del modello linguistico)."""
from __future__ import annotations

from typing import Optional

from .models import CONTENT_TYPES

CHANNEL_CONTENT_TYPES: dict[str, tuple[str, ...]] = {
    "instagram": ("post_social", "caption"),
    "facebook": ("post_social", "caption"),
    "tiktok": ("reel_script", "storyboard", "voiceover_script"),
    "linkedin": ("post_social",),
    "email": ("email",),
    "newsletter": ("newsletter",),
    "landing": ("landing_copy",),
    "blog": ("articolo_blog", "contenuto_seo"),
    "ads": ("ad_copy", "headline", "cta"),
    "sales": ("comunicazione_commerciale", "offerta"),
    "generico": ("contenuto_informativo",),
}

FUNNEL_TONE_HINT: dict[str, str] = {
    "TOFU": "informativo e discorsivo, nessuna richiesta di acquisto diretta",
    "MOFU": "consulenziale, mette a confronto benefici concreti",
    "BOFU": "diretto, con una call to action esplicita",
    "RETENTION": "personalizzato, orientato a mantenere una relazione gia' avviata",
}


def decide_content_plan(*, channel: str, funnel_stage: str, explicit_type: Optional[str], quantity: int = 1) -> dict:
    """Ritorna {'content_types': [...], 'motivazione': str, 'tono_suggerito': str}.
    Un tipo esplicitamente richiesto dall'utente vince sempre sul mapping
    canale->tipo: l'agente decide da solo SOLO quando non gli viene detto
    cosa produrre — mai un'invenzione quando l'istruzione e' gia' chiara.

    'quantity' (default 1, quindi comportamento invariato per ogni chiamante
    esistente): il numero TOTALE di content_item DISTINTI da produrre — MAI
    'numero di tipi decisi x quantity'. Se il canale ammette piu' tipi (es.
    tiktok -> reel_script/storyboard/voiceover_script), i tipi vengono
    ciclati fino a raggiungere ESATTAMENTE 'quantity' elementi totali, non
    moltiplicati: quantity=2 su un canale a 3 tipi da' 2 content_item (i
    primi due tipi del ciclo), mai 6."""
    canale = (channel or "generico").strip().lower()
    fase = (funnel_stage or "MOFU").strip().upper()
    tono = FUNNEL_TONE_HINT.get(fase, FUNNEL_TONE_HINT["MOFU"])
    quantity = max(1, int(quantity or 1))

    if explicit_type:
        if explicit_type not in CONTENT_TYPES:
            raise ValueError(f"Tipo di contenuto sconosciuto: '{explicit_type}'.")
        return {
            "content_types": [explicit_type] * quantity,
            "motivazione": f"Tipo di contenuto richiesto esplicitamente: '{explicit_type}'"
                          + (f" (x{quantity})." if quantity > 1 else "."),
            "tono_suggerito": tono,
        }

    tipi = CHANNEL_CONTENT_TYPES.get(canale, CHANNEL_CONTENT_TYPES["generico"])
    content_types = [tipi[i % len(tipi)] for i in range(quantity)]
    return {
        "content_types": content_types,
        "motivazione": (
            f"Nessun tipo di contenuto specificato: selezionato/i in base al canale '{canale}' "
            f"nella fase di funnel '{fase}' (mapping canale->formato)."
            + (f" {quantity} contenuti totali richiesti, tipi ciclati su {len(tipi)} disponibili per il canale."
               if quantity > 1 else "")
        ),
        "tono_suggerito": tono,
    }
