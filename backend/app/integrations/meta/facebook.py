"""Meta Graph API — pubblicazione reale su Facebook Page (item 8). UNA
chiamata REST per tipo di contenuto (Graph API di Facebook non richiede il
flusso a container multi-step di Instagram, vedi instagram.py): foto/video
per URL pubblicamente raggiungibile, testo semplice come post di bacheca.

Come per gli altri gateway reali dell'app (Requesty, Runway): nessuna
chiamata parte da qui senza che il chiamante (domains/social_publishing.py)
abbia gia' verificato TUTTI i gate di sicurezza — questo modulo si limita a
eseguire la chiamata e a interpretarne la risposta, mai a decidere se
l'azione e' autorizzata."""
from __future__ import annotations

from typing import Optional

from .client import assert_public_media_url, graph_request
from .models import MetricheRaccolte, PubblicazioneRiuscita


def publish_page_post(
    access_token: str, page_id: str, *, message: str, link: Optional[str] = None,
    api_version: str = "v21.0", timeout: float = 30.0,
) -> PubblicazioneRiuscita:
    """Post di solo testo (con link opzionale, es. CTA verso il sito).
    POST /{page-id}/feed."""
    corpo = graph_request(
        "POST", f"{page_id}/feed", access_token=access_token,
        data={"message": message, **({"link": link} if link else {})},
        api_version=api_version, timeout=timeout, max_retries=2,
    )
    return PubblicazioneRiuscita(external_post_id=corpo["id"], raw=corpo)


def publish_page_photo(
    access_token: str, page_id: str, *, image_url: str, caption: str,
    api_version: str = "v21.0", timeout: float = 30.0,
) -> PubblicazioneRiuscita:
    """Post con immagine. POST /{page-id}/photos con 'url' (Meta scarica
    l'immagine da quell'URL: deve essere pubblicamente raggiungibile, vedi
    domains/social_publishing.py::_public_asset_url — mai un localhost)."""
    assert_public_media_url(image_url)
    corpo = graph_request(
        "POST", f"{page_id}/photos", access_token=access_token,
        data={"url": image_url, "caption": caption, "published": "true"},
        api_version=api_version, timeout=timeout, max_retries=2,
    )
    return PubblicazioneRiuscita(external_post_id=corpo.get("post_id") or corpo["id"], raw=corpo)


def publish_page_video(
    access_token: str, page_id: str, *, video_url: str, description: str,
    api_version: str = "v21.0", timeout: float = 60.0,
) -> PubblicazioneRiuscita:
    """Post con video/reel. POST /{page-id}/videos con 'file_url' (Meta
    scarica il video da quell'URL — stesso vincolo di publish_page_photo:
    URL pubblicamente raggiungibile). Video grandi vengono elaborati in
    modo asincrono lato Meta: la risposta immediata contiene comunque un id
    utilizzabile per verificarne poi lo stato (get_post_status)."""
    assert_public_media_url(video_url)
    corpo = graph_request(
        "POST", f"{page_id}/videos", access_token=access_token,
        data={"file_url": video_url, "description": description},
        api_version=api_version, timeout=timeout, max_retries=1,  # video piu' pesanti: meno retry, timeout piu' alto
    )
    return PubblicazioneRiuscita(external_post_id=corpo["id"], raw=corpo)


def get_post_status(access_token: str, post_id: str, *, api_version: str = "v21.0", timeout: float = 15.0) -> dict:
    """Sola lettura, gratuita: stato/permalink del post gia' pubblicato."""
    return graph_request("GET", post_id, access_token=access_token,
                         params={"fields": "id,permalink_url,status_type"},
                         api_version=api_version, timeout=timeout, max_retries=1)


# Metriche Page Insights per singolo post: nomi metrica correnti (Graph API
# v21+). Meta rinomina/deprecare periodicamente le metriche insight: se una
# non e' (piu') disponibile, il valore resta 'null' -- MAI un valore
# inventato o un errore bloccante per l'intera raccolta (vedi item 18).
_METRICHE_POST = (
    "post_impressions", "post_impressions_unique", "post_video_views",
    "post_reactions_like_total", "post_activity_by_action_type",
)


def get_post_insights(access_token: str, post_id: str, *, api_version: str = "v21.0",
                      timeout: float = 20.0) -> MetricheRaccolte:
    try:
        corpo = graph_request("GET", f"{post_id}/insights", access_token=access_token,
                              params={"metric": ",".join(_METRICHE_POST)},
                              api_version=api_version, timeout=timeout, max_retries=1)
    except Exception as exc:  # una raccolta metriche fallita non e' un errore bloccante: dato non disponibile
        return MetricheRaccolte(data_available=False, note=f"Metriche non recuperabili: {getattr(exc, 'messaggio', str(exc))}")

    valori: dict[str, int] = {}
    for voce in corpo.get("data") or []:
        nome = voce.get("name")
        valori_serie = voce.get("values") or []
        if nome and valori_serie:
            v = valori_serie[-1].get("value")
            if isinstance(v, (int, float)):
                valori[nome] = int(v)

    if not valori:
        return MetricheRaccolte(data_available=False, note="Nessuna metrica disponibile per questo post (troppo recente o insights non abilitati).")

    return MetricheRaccolte(
        data_available=True,
        impressions=valori.get("post_impressions"),
        reach=valori.get("post_impressions_unique"),
        views=valori.get("post_video_views"),
        likes=valori.get("post_reactions_like_total"),
    )
