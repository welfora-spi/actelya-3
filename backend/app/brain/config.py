"""Brain — configurazione centrale di sicurezza (Blocco A).

Punto UNICO da cui il resto del brain legge se sono ammesse azioni esterne
reali. In questa fase l'unico stato possibile è quello sicuro:

    REAL_EXTERNAL_ACTIONS = False
    AI_PROVIDER_MODE      = "mock"
    CONNECTOR_MODE        = "dry_run"

Regole (garantite dai resolver qui sotto, mai da un valore letto altrove):
- variabile d'ambiente assente  -> valore sicuro di default;
- valore vuoto o non riconosciuto -> valore sicuro di default (mai un
  errore che potrebbe essere ignorato, mai un fallback permissivo);
- per AI_PROVIDER_MODE e CONNECTOR_MODE, in questa fase esiste UN SOLO
  valore riconosciuto ("mock"/"dry_run"): non c'è alcuna stringa che possa
  far risolvere la modalità a qualcosa di diverso da quella sicura, perché
  nessuna modalità reale è ancora implementata da nessuna parte;
- nessuna lettura di credenziali qui, nessuna inizializzazione di provider;
- nessuna chiamata di rete: questo modulo fa solo `os.environ.get`.

`gateways/connector_gateway.py` legge questi valori (più precisamente:
gli attributi di QUESTO modulo, non l'ambiente direttamente) come seconda
barriera, indipendente da cosa i singoli chiamanti dichiarano di volere.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off", ""}

# Unico valore ammesso in questa fase: nessuna modalità reale esiste ancora.
_SAFE_AI_PROVIDER_MODE = "mock"
_SAFE_CONNECTOR_MODE = "dry_run"


def resolve_real_external_actions(env: Optional[Mapping[str, str]] = None) -> bool:
    """True SOLO se la variabile è esplicitamente e inequivocabilmente
    valorizzata come vera. Qualunque altra cosa (assente, vuota, valore
    non riconosciuto) resta False: il default sicuro non richiede alcuna
    azione da parte di chi configura l'ambiente."""
    source = os.environ if env is None else env
    raw = source.get("REAL_EXTERNAL_ACTIONS")
    if raw is None:
        return False
    normalized = raw.strip().lower()
    if normalized in _TRUTHY:
        return True
    return False


def resolve_ai_provider_mode(env: Optional[Mapping[str, str]] = None) -> str:
    """'mock' per qualunque input diverso dalla stringa 'mock' stessa
    (assente, vuoto, 'real', 'live', refusi...): non esiste, in questa
    fase, alcun valore che sblocchi una modalità diversa da mock."""
    source = os.environ if env is None else env
    raw = source.get("AI_PROVIDER_MODE")
    if raw is None:
        return _SAFE_AI_PROVIDER_MODE
    normalized = raw.strip().lower()
    if normalized == _SAFE_AI_PROVIDER_MODE:
        return _SAFE_AI_PROVIDER_MODE
    return _SAFE_AI_PROVIDER_MODE


def resolve_connector_mode(env: Optional[Mapping[str, str]] = None) -> str:
    """'dry_run' per qualunque input diverso dalla stringa 'dry_run' stessa
    — stessa logica di resolve_ai_provider_mode()."""
    source = os.environ if env is None else env
    raw = source.get("CONNECTOR_MODE")
    if raw is None:
        return _SAFE_CONNECTOR_MODE
    normalized = raw.strip().lower()
    if normalized == _SAFE_CONNECTOR_MODE:
        return _SAFE_CONNECTOR_MODE
    return _SAFE_CONNECTOR_MODE


# Valori risolti una volta, al caricamento del modulo, dall'ambiente reale.
# Letti da gateways/connector_gateway.py come attributi di QUESTO modulo
# (non da os.environ direttamente), così un test può sovrascriverli con
# monkeypatch senza toccare l'ambiente di processo.
REAL_EXTERNAL_ACTIONS: bool = resolve_real_external_actions()
AI_PROVIDER_MODE: str = resolve_ai_provider_mode()
CONNECTOR_MODE: str = resolve_connector_mode()
