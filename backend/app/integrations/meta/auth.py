"""Meta Graph API — validazione token/permessi/account (item 11). Ogni
funzione qui e' di SOLA LETTURA (nessuna pubblicazione, nessun costo,
nessun effetto collaterale su Meta): richiamabile in ogni momento per
verificare lo stato di una connessione, prima ancora di provare a
pubblicare qualcosa."""
from __future__ import annotations

from .client import graph_request
from .errors import MetaConnectorError, MetaInvalidAccount
from .models import InstagramAccountInfo, PageInfo, TokenValidazione


def validate_token(access_token: str, *, api_version: str = "v21.0", timeout: float = 15.0) -> TokenValidazione:
    """Verifica minima e universale: GET /me con QUALUNQUE token valido
    (utente o pagina) risponde con id/name. Non richiede app_id/app_secret
    (a differenza di debug_token sotto): e' il primo controllo, sempre
    disponibile."""
    try:
        corpo = graph_request("GET", "me", access_token=access_token, params={"fields": "id,name"},
                              api_version=api_version, timeout=timeout, max_retries=0)
    except MetaConnectorError as exc:
        return TokenValidazione(valido=False, app_id=None, messaggio=exc.messaggio)
    return TokenValidazione(valido=True, app_id=corpo.get("id"), messaggio=f"Token valido per {corpo.get('name', '?')}.")


def debug_token(access_token: str, *, app_id: str, app_secret: str,
                api_version: str = "v21.0", timeout: float = 15.0) -> TokenValidazione:
    """Introspezione completa (scopes, scadenza) via /debug_token — richiede
    un token applicativo (app_id|app_secret) per autenticare la chiamata di
    debug, come documentato da Meta. Usata quando le credenziali app sono
    disponibili; altrimenti validate_token() resta il controllo minimo."""
    app_token = f"{app_id}|{app_secret}"
    try:
        corpo = graph_request("GET", "debug_token", access_token=app_token,
                              params={"input_token": access_token},
                              api_version=api_version, timeout=timeout, max_retries=0)
    except MetaConnectorError as exc:
        return TokenValidazione(valido=False, app_id=None, messaggio=exc.messaggio)
    dati = corpo.get("data") or {}
    return TokenValidazione(
        valido=bool(dati.get("is_valid")),
        app_id=dati.get("app_id"),
        scopes=list(dati.get("scopes") or []),
        expires_at=(str(dati["expires_at"]) if dati.get("expires_at") else None),
        messaggio="Token valido." if dati.get("is_valid") else "Token non valido o scaduto.",
    )


def verify_page(access_token: str, page_id: str, *, api_version: str = "v21.0", timeout: float = 15.0) -> PageInfo:
    """Verifica che page_id sia una Pagina reale raggiungibile con questo
    token, e recupera l'eventuale Instagram Business Account collegato
    (necessario per il flusso di pubblicazione Instagram, vedi instagram.py)."""
    if not page_id:
        raise MetaInvalidAccount("Nessun page_id configurato.")
    corpo = graph_request("GET", page_id, access_token=access_token,
                          params={"fields": "id,name,instagram_business_account"},
                          api_version=api_version, timeout=timeout, max_retries=1)
    ig = (corpo.get("instagram_business_account") or {}).get("id")
    return PageInfo(page_id=corpo["id"], page_name=corpo.get("name", ""), instagram_business_account_id=ig)


def verify_instagram_account(access_token: str, ig_user_id: str, *, api_version: str = "v21.0",
                             timeout: float = 15.0) -> InstagramAccountInfo:
    if not ig_user_id:
        raise MetaInvalidAccount("Nessun Instagram Business Account ID configurato.")
    corpo = graph_request("GET", ig_user_id, access_token=access_token, params={"fields": "id,username"},
                          api_version=api_version, timeout=timeout, max_retries=1)
    return InstagramAccountInfo(ig_user_id=corpo["id"], username=corpo.get("username", ""))
