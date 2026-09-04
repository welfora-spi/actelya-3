"""Brain — configurazione centrale di sicurezza (Blocco A, estesa per il
Social Media Manager production-ready — DECISIONE UFFICIALE "100% REALE").

Punto UNICO da cui il resto del brain legge se sono ammesse azioni esterne
reali. Il default resta SEMPRE quello sicuro:

    REAL_EXTERNAL_ACTIONS = False
    AI_PROVIDER_MODE      = "mock"
    CONNECTOR_MODE        = "dry_run"

Regole (garantite dai resolver qui sotto, mai da un valore letto altrove):
- variabile d'ambiente assente  -> valore sicuro di default;
- valore vuoto o non riconosciuto -> valore sicuro di default (mai un
  errore che potrebbe essere ignorato, mai un fallback permissivo);
- CONNECTOR_MODE può ora risolvere a "real" — MA solo se la variabile
  d'ambiente vale ESATTAMENTE "real" (case-insensitive): qualunque altro
  valore, assente, vuoto o refuso ricade sempre su "dry_run". Anche con
  CONNECTOR_MODE="real", nessuna azione esterna reale è possibile senza
  ANCHE REAL_EXTERNAL_ACTIONS=true (vedi gateways/connector_gateway.py,
  che verifica ENTRAMBI, più l'esistenza di un adapter reale registrato
  E la configurazione/verifica del connector specifico per l'organizzazione
  — nessuna delle quattro condizioni da sola è mai sufficiente);
- AI_PROVIDER_MODE resta 'mock' per costruzione in questa fase (i provider
  AI reali di ACTELYA 3 — Requesty, Runway — non passano da questo flag:
  hanno la propria gestione connessione/credenziali per organizzazione in
  domains/connections.py e domains/video_connections.py);
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

_SAFE_AI_PROVIDER_MODE = "mock"
_SAFE_CONNECTOR_MODE = "dry_run"
_REAL_CONNECTOR_MODE = "real"


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
    """'dry_run' per qualunque input diverso da 'real' (assente, vuoto,
    refuso, o letteralmente 'dry_run'): il default sicuro non richiede
    alcuna azione da chi configura l'ambiente. 'real' è l'UNICO valore che
    sblocca la modalità reale — e da solo NON è sufficiente: vedi
    gateways/connector_gateway.py per le condizioni aggiuntive."""
    source = os.environ if env is None else env
    raw = source.get("CONNECTOR_MODE")
    if raw is None:
        return _SAFE_CONNECTOR_MODE
    normalized = raw.strip().lower()
    if normalized == _REAL_CONNECTOR_MODE:
        return _REAL_CONNECTOR_MODE
    return _SAFE_CONNECTOR_MODE


# Valori risolti una volta, al caricamento del modulo, dall'ambiente reale.
# Letti da gateways/connector_gateway.py come attributi di QUESTO modulo
# (non da os.environ direttamente), così un test può sovrascriverli con
# monkeypatch senza toccare l'ambiente di processo.
REAL_EXTERNAL_ACTIONS: bool = resolve_real_external_actions()
AI_PROVIDER_MODE: str = resolve_ai_provider_mode()
CONNECTOR_MODE: str = resolve_connector_mode()
