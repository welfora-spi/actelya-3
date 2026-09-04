"""Meta Graph API — client HTTP di basso livello (item 4/17, DECISIONE
UFFICIALE "100% REALE"). Nessun SDK ufficiale Meta per Python usato
(pesante, orientato al marketing/ads API): chiamate REST dirette via
`requests` (gia' dipendenza dell'app, vedi requirements.txt), stesso
principio "nessuna implementazione HTTP grezza sparsa nel codice" del resto
dell'app -- ogni chiamata Graph API passa da qui, un solo punto.

Retry SOLO per condizioni transitorie (item 17): errori di rete, HTTP 5xx,
rate limit (rispettando Retry-After quando presente). MAI un retry per
errori di autenticazione/permessi/media non valido/parametri invalidi:
quelli si propagano subito, un secondo tentativo identico fallirebbe allo
stesso modo e rischierebbe di mascherare il problema reale."""
from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import urlparse

from .errors import (
    MetaAuthError,
    MetaConnectorError,
    MetaInvalidAccount,
    MetaMediaProcessingError,
    MetaPermissionError,
    MetaPublishError,
    MetaRateLimitError,
    MetaTimeout,
)

# Host non pubblicamente raggiungibili da Meta (item 10): localhost, IP
# privati/loopback, domini interni. Un controllo euristico sull'hostname,
# non una risoluzione DNS/IP completa (nessuna chiamata di rete qui) — ma
# sufficiente a impedire l'errore piu' comune e piu' dannoso: passare un
# URL locale di sviluppo a un provider esterno che non potra' mai
# raggiungerlo (il container/post fallirebbe comunque, ma solo dopo aver
# gia' provato ad accedervi — meglio bloccarlo subito, con un errore
# leggibile invece di un fallimento Meta generico dopo secondi di attesa)."""
_HOST_NON_PUBBLICI_RE = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|::1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|"
    r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|.*\.local|.*\.internal)$",
    re.IGNORECASE,
)


def assert_public_media_url(url: str) -> None:
    """Solleva MetaMediaProcessingError se l'URL non e' pubblicamente
    raggiungibile (schema http/https + host non locale/privato). Va
    chiamata PRIMA di ogni publish_page_photo/video e create_media_container
    (facebook.py/instagram.py): Meta scarica l'asset da questo URL, un
    indirizzo locale fallirebbe sempre e silenziosamente lato provider."""
    if not url or not isinstance(url, str):
        raise MetaMediaProcessingError("Nessun URL asset fornito.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise MetaMediaProcessingError(f"URL asset non valido (schema '{parsed.scheme}'): serve http/https pubblicamente raggiungibile.")
    host = (parsed.hostname or "").lower()
    if not host or _HOST_NON_PUBBLICI_RE.match(host):
        raise MetaMediaProcessingError(
            f"URL asset non pubblicamente raggiungibile da Meta ('{host or url}'): "
            "serve un URL pubblico (es. storage/CDN), mai un indirizzo locale/privato."
        )

GRAPH_API_BASE = "https://graph.facebook.com"
DEFAULT_API_VERSION = "v21.0"
DEFAULT_TIMEOUT_SECONDI = 30.0
MAX_RETRY_DEFAULT = 2
BACKOFF_BASE_SECONDI = 1.5

# Codici di errore Graph API documentati come rate-limit/transitori
# (https://developers.facebook.com/docs/graph-api/guides/error-handling/):
# 4 = generico limite applicazione, 17 = limite utente, 32 = limite pagina,
# 613 = limite chiamate custom.
_CODICI_RATE_LIMIT = {4, 17, 32, 613}
# 190 = OAuthException (token scaduto/non valido). 10/200-299 = permessi.
_CODICE_AUTH = 190
_CODICI_PERMESSO = set(range(200, 300)) | {10}
# 100 = parametro non valido, 36001-36011 circa = errori di elaborazione
# media Instagram (variano per versione API): trattati caso per caso dal
# chiamante (instagram.py), qui il client si limita a classificare quanto
# e' generalmente riconoscibile.


def _redigi(url: str) -> str:
    """Non logga/espone mai il token nell'URL (query string access_token=...)."""
    if "access_token=" not in url:
        return url
    base, _, resto = url.partition("access_token=")
    coda = resto.split("&", 1)
    suffisso = f"&{coda[1]}" if len(coda) > 1 else ""
    return f"{base}access_token=[REDACTED]{suffisso}"


def _classifica_errore_graph(status_code: int, body: dict) -> MetaConnectorError:
    errore = (body or {}).get("error") or {}
    codice = errore.get("code")
    messaggio_meta = errore.get("message") or "Errore Graph API non specificato."
    if codice == _CODICE_AUTH:
        return MetaAuthError(f"Token Meta non valido o scaduto (codice {codice}).")
    if codice in _CODICI_PERMESSO:
        return MetaPermissionError(f"Permesso Meta mancante per questa azione (codice {codice}): {messaggio_meta}")
    if codice in _CODICI_RATE_LIMIT or status_code == 429:
        return MetaRateLimitError(f"Limite di frequenza Meta raggiunto (codice {codice}).")
    if status_code in (400, 100) or codice == 100:
        return MetaPublishError(f"Parametri non validi per Meta: {messaggio_meta}")
    if status_code == 404:
        return MetaInvalidAccount(f"Risorsa Meta non trovata: {messaggio_meta}")
    return MetaPublishError(f"Errore Meta (status {status_code}, codice {codice}): {messaggio_meta}")


def graph_request(
    method: str,
    path: str,
    *,
    access_token: str,
    params: Optional[dict] = None,
    data: Optional[dict] = None,
    api_version: str = DEFAULT_API_VERSION,
    timeout: float = DEFAULT_TIMEOUT_SECONDI,
    max_retries: int = MAX_RETRY_DEFAULT,
) -> dict:
    """UNA chiamata Graph API con retry solo per condizioni transitorie.
    Ritorna il JSON decodificato in caso di successo (status 2xx). Solleva
    sempre un MetaConnectorError tipizzato (mai un'eccezione grezza di
    `requests`) — MetaTimeout se la richiesta parte ma non arriva risposta
    (esito non verificabile, mai un secondo tentativo automatico per quel
    caso specifico: la decisione se ritentare spetta al chiamante, che
    conosce lo stato applicativo — vedi domains/social_publishing.py)."""
    import requests  # importata solo qui: mai caricata finche' non serve davvero una chiamata

    if not access_token:
        raise MetaAuthError("Nessun access token Meta fornito.")

    url = f"{GRAPH_API_BASE}/{api_version}/{path.lstrip('/')}"
    p = dict(params or {})
    p["access_token"] = access_token

    tentativo = 0
    while True:
        try:
            resp = requests.request(method, url, params=p, data=data, timeout=timeout)
        except requests.exceptions.Timeout as exc:
            raise MetaTimeout() from exc
        except requests.exceptions.RequestException as exc:
            if tentativo < max_retries:
                time.sleep(BACKOFF_BASE_SECONDI * (2 ** tentativo))
                tentativo += 1
                continue
            raise MetaConnectorError("rete", f"Impossibile raggiungere Meta Graph API dopo {tentativo + 1} tentativi (errore di rete).") from exc

        try:
            corpo = resp.json()
        except ValueError:
            corpo = {}

        if 200 <= resp.status_code < 300:
            return corpo

        errore = _classifica_errore_graph(resp.status_code, corpo)
        ritentabile = isinstance(errore, MetaRateLimitError) or resp.status_code >= 500
        if ritentabile and tentativo < max_retries:
            retry_after = resp.headers.get("Retry-After")
            attesa = float(retry_after) if retry_after and retry_after.isdigit() else BACKOFF_BASE_SECONDI * (2 ** tentativo)
            time.sleep(attesa)
            tentativo += 1
            continue
        raise errore
