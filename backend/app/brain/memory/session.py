"""Brain — memoria temporanea della sessione (Blocco C).

Storage ESCLUSIVAMENTE in-memory (un dict Python protetto da lock): nessuna
scrittura su disco, nessun MongoDB, nessuna persistenza tra riavvii del
processo. Serve a far collaborare gli agenti nella stessa sessione
(richiesta originale, contesto, chiarimenti, agenti convocati, handoff,
decisioni, avvisi/errori) senza duplicare lo stato già persistito da M2
(plans/tasks/deliverables restano SOLO in MongoDB, qui solo referenziati
per id).

Thread-safe (RLock), con limiti configurabili su numero di sessioni, numero
di eventi per sessione e dimensione di un singolo elemento: un limite
superato viene sempre RIFIUTATO esplicitamente (mai troncato, mai una
sessione attiva eliminata in silenzio per far posto a una nuova). Ogni
lettura e scrittura passa per una copia difensiva (deepcopy): il chiamante
non può mai alterare lo stato interno modificando un dict restituito. I
campi il cui nome somiglia a una credenziale sono redatti ricorsivamente
prima di essere memorizzati, come in gateways/connector_gateway.py."""
from __future__ import annotations

import copy
import json
import threading
from typing import Optional

from ...models import new_id, now_iso
from ..safety.errors import BrainError

DEFAULT_MAX_SESSIONS = 500
DEFAULT_MAX_EVENTS_PER_SESSION = 500
DEFAULT_MAX_PAYLOAD_BYTES = 20_000  # per singolo elemento aggiunto/aggiornato

_CAMPI_SENSIBILI = ("api_key", "password", "token", "secret", "authorization", "credential")

# Campi scalari: sostituiti interamente da update_session().
_SCALAR_FIELDS = (
    "plan_id", "goal_id", "original_request", "normalized_request", "business_context",
    "selected_agents", "activeAgentIds", "status", "llm_understanding", "llm_plan",
)
# Campi lista: SOLO append (mai sovrascritti) via append_to_session().
_LIST_FIELDS = ("clarifications", "decisions", "handoffs", "deliverable_refs", "warnings", "errors")


class LimiteMemoriaSuperato(BrainError):
    """Un'operazione sulla memoria di sessione ha superato un limite
    configurato (numero massimo di sessioni, di eventi per sessione, o
    dimensione di un singolo elemento): rifiutata esplicitamente, mai
    troncata né scartata in silenzio."""


class SessioneNonTrovata(BrainError):
    """Operazione richiesta su un session_id assente dallo store."""


def _redact(valore):
    if isinstance(valore, dict):
        pulito = {}
        for k, v in valore.items():
            if any(p in str(k).lower() for p in _CAMPI_SENSIBILI):
                pulito[k] = "[REDACTED]"
            else:
                pulito[k] = _redact(v)
        return pulito
    if isinstance(valore, list):
        return [_redact(v) for v in valore]
    return valore


def _payload_size(valore) -> int:
    try:
        return len(json.dumps(valore, ensure_ascii=False, default=str))
    except TypeError:
        return len(str(valore))


def _empty_session(session_id: str, *, plan_id=None, goal_id=None, original_request=None) -> dict:
    ts = now_iso()
    return {
        "session_id": session_id,
        "plan_id": plan_id,
        "goal_id": goal_id,
        "created_at": ts,
        "updated_at": ts,
        "original_request": original_request,
        "normalized_request": None,
        "business_context": {},
        "selected_agents": [],
        "activeAgentIds": [],
        "status": "CREATED",
        "clarifications": [],
        "decisions": [],
        "handoffs": [],
        "deliverable_refs": [],
        "warnings": [],
        "errors": [],
    }


class SessionStore:
    """Un'istanza per processo in produzione (get_session_store()); i test
    creano istanze proprie per isolamento completo tra un caso e l'altro."""

    def __init__(self, *, max_sessions: int = DEFAULT_MAX_SESSIONS,
                 max_events_per_session: int = DEFAULT_MAX_EVENTS_PER_SESSION,
                 max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES) -> None:
        self._max_sessions = max_sessions
        self._max_events_per_session = max_events_per_session
        self._max_payload_bytes = max_payload_bytes
        self._lock = threading.RLock()
        self._sessions: dict[str, dict] = {}

    def _check_size(self, label: str, valore) -> None:
        size = _payload_size(valore)
        if size > self._max_payload_bytes:
            raise LimiteMemoriaSuperato(
                f"'{label}' supera il limite di dimensione consentito "
                f"({size} > {self._max_payload_bytes} byte): rifiutato, nulla è stato memorizzato."
            )

    def create_session(self, *, session_id: Optional[str] = None, plan_id=None, goal_id=None,
                        original_request=None) -> dict:
        """Idempotente: se session_id esiste già, ritorna quella sessione
        SENZA sovrascriverla (mai un reset implicito di una sessione attiva)."""
        with self._lock:
            sid = session_id or new_id("session")
            if sid in self._sessions:
                return copy.deepcopy(self._sessions[sid])
            if len(self._sessions) >= self._max_sessions:
                raise LimiteMemoriaSuperato(
                    f"Limite massimo di sessioni raggiunto ({self._max_sessions}): nuova sessione "
                    "rifiutata, nessuna sessione attiva è stata eliminata per farle posto."
                )
            if original_request is not None:
                self._check_size("original_request", original_request)
            rec = _empty_session(sid, plan_id=plan_id, goal_id=goal_id, original_request=original_request)
            self._sessions[sid] = rec
            return copy.deepcopy(rec)

    def get_session(self, session_id: str) -> Optional[dict]:
        with self._lock:
            rec = self._sessions.get(session_id)
            return copy.deepcopy(rec) if rec is not None else None

    # Alias esplicito richiesto dal contratto: fotografia immutabile dello stato.
    def snapshot(self, session_id: str) -> Optional[dict]:
        return self.get_session(session_id)

    def update_session(self, session_id: str, **campi) -> dict:
        with self._lock:
            rec = self._sessions.get(session_id)
            if rec is None:
                raise SessioneNonTrovata(f"Sessione '{session_id}' non trovata.")
            for k, v in campi.items():
                if k not in _SCALAR_FIELDS:
                    raise ValueError(
                        f"Campo '{k}' non aggiornabile con update_session() "
                        f"(campi lista vanno aggiunti con append_to_session())."
                    )
                self._check_size(k, v)
            for k, v in campi.items():
                rec[k] = _redact(copy.deepcopy(v)) if isinstance(v, (dict, list)) else v
            rec["updated_at"] = now_iso()
            return copy.deepcopy(rec)

    def append_to_session(self, session_id: str, field_name: str, item) -> dict:
        """Aggiunge SEMPRE in coda, senza mai sovrascrivere gli elementi
        già presenti nel campo lista indicato."""
        with self._lock:
            rec = self._sessions.get(session_id)
            if rec is None:
                raise SessioneNonTrovata(f"Sessione '{session_id}' non trovata.")
            if field_name not in _LIST_FIELDS:
                raise ValueError(f"Campo '{field_name}' non è un campo lista appendibile.")
            self._check_size(field_name, item)
            totale_eventi = sum(len(rec[f]) for f in _LIST_FIELDS)
            if totale_eventi >= self._max_events_per_session:
                raise LimiteMemoriaSuperato(
                    f"Limite massimo di eventi per sessione raggiunto ({self._max_events_per_session}) "
                    f"per la sessione '{session_id}': elemento rifiutato, nessun evento precedente "
                    "è stato rimosso."
                )
            rec[field_name].append(_redact(copy.deepcopy(item)) if isinstance(item, (dict, list)) else item)
            rec["updated_at"] = now_iso()
            return copy.deepcopy(rec)

    def find_by_plan_id(self, plan_id: str) -> list[dict]:
        with self._lock:
            return [copy.deepcopy(r) for r in self._sessions.values() if r.get("plan_id") == plan_id]

    def find_by_goal_id(self, goal_id: str) -> list[dict]:
        with self._lock:
            return [copy.deepcopy(r) for r in self._sessions.values() if r.get("goal_id") == goal_id]

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def reset(self) -> None:
        """Solo per i test: azzera completamente lo store in-memory."""
        with self._lock:
            self._sessions.clear()


_default_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """Istanza condivisa di processo (lazy singleton). I test dovrebbero
    preferire SessionStore() diretto per isolamento tra casi."""
    global _default_store
    if _default_store is None:
        _default_store = SessionStore()
    return _default_store
