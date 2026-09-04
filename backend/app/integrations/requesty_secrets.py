"""Credenziale Requesty — Credential Manager di Windows (o storage sicuro nativo
equivalente su altri sistemi), MAI un file di questo progetto.

Porting minimale di core/secrets.py di ACTELYA v1: stesso service name di keyring
("welfora_ai") e stessa convenzione di chiave ("servizio:campo" -> "requesty:api_key"),
cosi' la credenziale gia' configurata da ACTELYA v1 sullo stesso PC viene riconosciuta
senza che l'utente debba reinserirla. Release single-org (vedi app/config.py ->
DEFAULT_ORG_ID): nessuna namespacing per organizzazione in questa fase.

Nessun segreto viene MAI scritto in Mongo, in un log, in un file .env o restituito
per intero da un endpoint: solo questo modulo parla con il Credential Manager.
"""
from __future__ import annotations

import keyring
import keyring.errors

_KEYRING_SERVICE = "welfora_ai"
_SERVIZIO_REQUESTY = "requesty"
_CAMPO_API_KEY = "api_key"


def _chiave(servizio: str, campo: str) -> str:
    return f"{servizio}:{campo}"


def salva_api_key_requesty(valore: str) -> None:
    if not valore or not valore.strip():
        raise ValueError("La API key non puo' essere vuota.")
    keyring.set_password(_KEYRING_SERVICE, _chiave(_SERVIZIO_REQUESTY, _CAMPO_API_KEY), valore.strip())


def leggi_api_key_requesty() -> str | None:
    """Valore REALE della credenziale. Da usare SOLO nel gateway al momento di una
    chiamata autorizzata: mai restituito da un endpoint, mai loggato."""
    try:
        return keyring.get_password(_KEYRING_SERVICE, _chiave(_SERVIZIO_REQUESTY, _CAMPO_API_KEY))
    except keyring.errors.KeyringError:
        return None


def elimina_api_key_requesty() -> None:
    try:
        keyring.delete_password(_KEYRING_SERVICE, _chiave(_SERVIZIO_REQUESTY, _CAMPO_API_KEY))
    except keyring.errors.PasswordDeleteError:
        pass  # gia' non configurata: nessun errore da propagare


def requesty_configurata() -> bool:
    return leggi_api_key_requesty() is not None


def requesty_api_key_mascherata() -> str | None:
    """SOLO le ultime 4 cifre/caratteri (es. "****7Kp2"): unica rappresentazione di
    una credenziale che puo' attraversare l'API verso il frontend."""
    valore = leggi_api_key_requesty()
    if not valore:
        return None
    ultimi = valore[-4:] if len(valore) >= 4 else valore
    return "*" * 4 + ultimi
