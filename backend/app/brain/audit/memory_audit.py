"""Brain — audit append-only in-memory delle decisioni del brain (Blocco C).

Registra, in ordine e senza mai modificare o cancellare un evento già
scritto, le decisioni prese durante triage/selezione/handoff: chi ha
deciso cosa, perché, e con quale esito. Interamente in-memory (nessun
MongoDB, nessuna scrittura su disco): AuditSink è un'interfaccia minima
pensata per poter, in un blocco futuro, affiancare o sostituire questa
implementazione con una che scriva anche sulla collezione MongoDB
`audit_logs` già usata da m2/engine.py — senza cambiare i chiamanti."""
from __future__ import annotations

import copy
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

from ...models import new_id, now_iso
from ..safety.errors import BrainError

DEFAULT_MAX_EVENTS = 5000

EVENT_REQUEST_RECEIVED = "REQUEST_RECEIVED"
EVENT_TRIAGE_COMPLETED = "TRIAGE_COMPLETED"
EVENT_AGENT_SELECTED = "AGENT_SELECTED"
EVENT_AGENT_EXCLUDED = "AGENT_EXCLUDED"
EVENT_CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
EVENT_PLAN_ALLOWED = "PLAN_ALLOWED"
EVENT_PLAN_BLOCKED = "PLAN_BLOCKED"
EVENT_HANDOFF_READY = "HANDOFF_READY"
EVENT_HANDOFF_WAITING = "HANDOFF_WAITING"
EVENT_HANDOFF_REJECTED = "HANDOFF_REJECTED"
EVENT_EXTERNAL_ACTION_BLOCKED = "EXTERNAL_ACTION_BLOCKED"
EVENT_ERROR_FALLBACK = "ERROR_FALLBACK"
EVENT_RESULT_READY_FOR_APPROVAL = "RESULT_READY_FOR_APPROVAL"
# ---- CEO Agent 100% reale: proposta LLM opzionale (blocchi 6/7/9/10) ----
EVENT_LLM_PROPOSAL_RECEIVED = "LLM_PROPOSAL_RECEIVED"
EVENT_LLM_PROPOSAL_UNAVAILABLE = "LLM_PROPOSAL_UNAVAILABLE"
EVENT_LLM_CORRECTION_APPLIED = "LLM_CORRECTION_APPLIED"
EVENT_RISK_ESCALATED_BY_LLM = "RISK_ESCALATED_BY_LLM"
EVENT_BUDGET_CLARIFICATION_REQUIRED = "BUDGET_CLARIFICATION_REQUIRED"

ALLOWED_EVENT_TYPES = frozenset({
    EVENT_REQUEST_RECEIVED, EVENT_TRIAGE_COMPLETED, EVENT_AGENT_SELECTED, EVENT_AGENT_EXCLUDED,
    EVENT_CLARIFICATION_REQUIRED, EVENT_PLAN_ALLOWED, EVENT_PLAN_BLOCKED, EVENT_HANDOFF_READY,
    EVENT_HANDOFF_WAITING, EVENT_HANDOFF_REJECTED, EVENT_EXTERNAL_ACTION_BLOCKED,
    EVENT_ERROR_FALLBACK, EVENT_RESULT_READY_FOR_APPROVAL,
    EVENT_LLM_PROPOSAL_RECEIVED, EVENT_LLM_PROPOSAL_UNAVAILABLE, EVENT_LLM_CORRECTION_APPLIED,
    EVENT_RISK_ESCALATED_BY_LLM, EVENT_BUDGET_CLARIFICATION_REQUIRED,
})

_CAMPI_SENSIBILI = ("api_key", "password", "token", "secret", "authorization", "credential")


class LimiteAuditSuperato(BrainError):
    """Il registro audit ha raggiunto il numero massimo configurato di
    eventi: il nuovo evento è rifiutato esplicitamente, nessun evento
    precedente viene mai eliminato per farne spazio (append-only)."""


class TipoEventoNonValido(BrainError):
    """event_type fuori dalla whitelist chiusa ALLOWED_EVENT_TYPES: nessun
    evento generico o non tipizzato viene mai accettato."""


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


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    sequence_number: int
    timestamp: str
    session_id: Optional[str]
    goal_id: Optional[str]
    plan_id: Optional[str]
    event_type: str
    actor: str
    decision: str
    reason: str
    metadata: dict

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "sequence_number": self.sequence_number,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "goal_id": self.goal_id,
            "plan_id": self.plan_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "decision": self.decision,
            "reason": self.reason,
            "metadata": copy.deepcopy(self.metadata),
        }


class AuditSink(ABC):
    """Interfaccia minima: qualunque implementazione futura (es. un adapter
    che scrive anche su m2 audit_logs) può sostituire AuditLog senza che i
    chiamanti (service.py) debbano cambiare."""

    @abstractmethod
    def record(self, *, event_type: str, session_id: Optional[str] = None, goal_id: Optional[str] = None,
               plan_id: Optional[str] = None, actor: str = "system", decision: str = "",
               reason: str = "", metadata: Optional[dict] = None) -> dict:
        ...


class AuditLog(AuditSink):
    """Un'istanza per processo in produzione (get_audit_log()); i test
    creano istanze proprie, con clock iniettabile, per determinismo
    completo."""

    def __init__(self, *, clock: Optional[Callable[[], str]] = None, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        self._clock = clock or now_iso
        self._max_events = max_events
        self._lock = threading.RLock()
        self._events: list[AuditEvent] = []
        self._seq = 0

    def record(self, *, event_type: str, session_id: Optional[str] = None, goal_id: Optional[str] = None,
               plan_id: Optional[str] = None, actor: str = "system", decision: str = "",
               reason: str = "", metadata: Optional[dict] = None) -> dict:
        if event_type not in ALLOWED_EVENT_TYPES:
            raise TipoEventoNonValido(f"Tipo di evento audit sconosciuto: '{event_type}'.")
        with self._lock:
            if len(self._events) >= self._max_events:
                raise LimiteAuditSuperato(
                    f"Limite massimo di eventi audit raggiunto ({self._max_events}): evento rifiutato, "
                    "nessun evento precedente è stato eliminato (registro append-only)."
                )
            self._seq += 1
            ev = AuditEvent(
                event_id=new_id("audit"),
                sequence_number=self._seq,
                timestamp=self._clock(),
                session_id=session_id, goal_id=goal_id, plan_id=plan_id,
                event_type=event_type, actor=actor, decision=decision, reason=reason,
                metadata=_redact(copy.deepcopy(metadata or {})),
            )
            self._events.append(ev)
            return ev.to_dict()

    def events(self) -> list[dict]:
        with self._lock:
            return [e.to_dict() for e in self._events]

    def filter(self, *, session_id: Optional[str] = None, plan_id: Optional[str] = None,
               goal_id: Optional[str] = None, event_type: Optional[str] = None) -> list[dict]:
        with self._lock:
            eventi = list(self._events)
        if session_id is not None:
            eventi = [e for e in eventi if e.session_id == session_id]
        if plan_id is not None:
            eventi = [e for e in eventi if e.plan_id == plan_id]
        if goal_id is not None:
            eventi = [e for e in eventi if e.goal_id == goal_id]
        if event_type is not None:
            eventi = [e for e in eventi if e.event_type == event_type]
        return [e.to_dict() for e in eventi]

    def reset(self) -> None:
        """Solo per i test: azzera completamente il registro."""
        with self._lock:
            self._events.clear()
            self._seq = 0


_default_log: Optional[AuditLog] = None


def get_audit_log() -> AuditLog:
    """Istanza condivisa di processo (lazy singleton). I test dovrebbero
    preferire AuditLog() diretto (con clock iniettabile) per isolamento e
    determinismo completo tra un caso e l'altro."""
    global _default_log
    if _default_log is None:
        _default_log = AuditLog()
    return _default_log
