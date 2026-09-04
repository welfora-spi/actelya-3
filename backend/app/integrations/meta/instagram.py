"""Meta Graph API — pubblicazione reale su Instagram Professional (item 9).
Flusso a container in TRE passi, mai un singolo POST (Instagram non
pubblica direttamente da un upload, a differenza di Facebook Page):

    1. create_media_container()  -> POST /{ig-user-id}/media (crea, non pubblica)
    2. get_container_status()    -> GET /{container_id}?fields=status_code (poll)
    3. publish_container()       -> POST /{ig-user-id}/media_publish (pubblica davvero)

Le funzioni qui sono BLOCCHI PURI (una chiamata Graph API ciascuna): il
polling/l'orchestrazione (quando aspettare, per quanto, cosa fare se il
container resta IN_PROGRESS per un video pesante) vive in
domains/social_publishing.py, con lo STESSO pattern gia' usato per i job
video Runway (domains/reel.py::_poll_video_job) — mai una seconda
implementazione di polling parallela."""
from __future__ import annotations

from typing import Optional

from .client import assert_public_media_url, graph_request
from .errors import MetaMediaProcessingError
from .models import ContainerStato, MetricheRaccolte, PubblicazioneRiuscita

# Stati terminali di un container (status_code): FINISHED (pronto per la
# pubblicazione), ERROR (elaborazione fallita), EXPIRED (container scaduto,
# 24h senza pubblicazione — va ricreato).
CONTAINER_STATI_TERMINALI = frozenset({"FINISHED", "ERROR", "EXPIRED"})


def create_media_container(
    access_token: str, ig_user_id: str, *, caption: str,
    image_url: Optional[str] = None, video_url: Optional[str] = None, is_reel: bool = False,
    api_version: str = "v21.0", timeout: float = 30.0,
) -> str:
    """Crea il container (NON pubblica ancora nulla, nessun post visibile).
    Esattamente uno tra image_url/video_url va fornito. Ritorna il
    container_id, da passare a get_container_status()/publish_container()."""
    if bool(image_url) == bool(video_url):
        raise MetaMediaProcessingError("Fornire ESATTAMENTE uno tra image_url e video_url per il container Instagram.")
    data: dict = {"caption": caption}
    if image_url:
        assert_public_media_url(image_url)
        data["image_url"] = image_url
    else:
        assert_public_media_url(video_url)
        data["video_url"] = video_url
        data["media_type"] = "REELS" if is_reel else "VIDEO"
    corpo = graph_request("POST", f"{ig_user_id}/media", access_token=access_token, data=data,
                          api_version=api_version, timeout=timeout, max_retries=1)
    return corpo["id"]


def get_container_status(access_token: str, container_id: str, *, api_version: str = "v21.0",
                         timeout: float = 15.0) -> ContainerStato:
    """Sola lettura, gratuita: interrogabile quante volte serve durante
    l'elaborazione (stesso principio di reel.py::recupera_stato_task per
    Runway, mai un costo aggiuntivo)."""
    corpo = graph_request("GET", container_id, access_token=access_token,
                          params={"fields": "status_code,status"},
                          api_version=api_version, timeout=timeout, max_retries=1)
    return ContainerStato(container_id=container_id, status_code=corpo.get("status_code", "IN_PROGRESS"),
                          status=corpo.get("status"))


def publish_container(access_token: str, ig_user_id: str, container_id: str, *, api_version: str = "v21.0",
                      timeout: float = 30.0) -> PubblicazioneRiuscita:
    """Pubblica DAVVERO (il post diventa visibile): richiede un container in
    stato FINISHED — chiamare solo dopo get_container_status() terminale."""
    corpo = graph_request("POST", f"{ig_user_id}/media_publish", access_token=access_token,
                          data={"creation_id": container_id},
                          api_version=api_version, timeout=timeout, max_retries=1)
    return PubblicazioneRiuscita(external_post_id=corpo["id"], raw=corpo)


def get_media_permalink(access_token: str, media_id: str, *, api_version: str = "v21.0",
                        timeout: float = 15.0) -> Optional[str]:
    corpo = graph_request("GET", media_id, access_token=access_token, params={"fields": "permalink"},
                          api_version=api_version, timeout=timeout, max_retries=1)
    return corpo.get("permalink")


# Metriche Instagram Media Insights: nomi correnti (Graph API v21+, media
# pubblicati da Instagram Professional). 'plays' sostituisce 'video_views'
# per i Reel dalle versioni piu' recenti dell'API: entrambi tentati, mai un
# errore bloccante se una singola metrica non e' disponibile (item 18).
_METRICHE_MEDIA = ("impressions", "reach", "likes", "comments", "shares", "saved", "plays")


def get_media_insights(access_token: str, media_id: str, *, api_version: str = "v21.0",
                       timeout: float = 20.0) -> MetricheRaccolte:
    try:
        corpo = graph_request("GET", f"{media_id}/insights", access_token=access_token,
                              params={"metric": ",".join(_METRICHE_MEDIA)},
                              api_version=api_version, timeout=timeout, max_retries=1)
    except Exception as exc:
        return MetricheRaccolte(data_available=False, note=f"Metriche non recuperabili: {getattr(exc, 'messaggio', str(exc))}")

    valori: dict[str, int] = {}
    for voce in corpo.get("data") or []:
        nome = voce.get("name")
        valore = voce.get("values", [{}])[0].get("value") if voce.get("values") else voce.get("total_value", {}).get("value")
        if nome and isinstance(valore, (int, float)):
            valori[nome] = int(valore)

    if not valori:
        return MetricheRaccolte(data_available=False, note="Nessuna metrica disponibile per questo media (troppo recente o account non idoneo per gli insights).")

    return MetricheRaccolte(
        data_available=True, impressions=valori.get("impressions"), reach=valori.get("reach"),
        views=valori.get("plays"), likes=valori.get("likes"), comments=valori.get("comments"),
        shares=valori.get("shares"), saves=valori.get("saved"),
    )
