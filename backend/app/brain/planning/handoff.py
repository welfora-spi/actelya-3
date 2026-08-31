"""Brain — handoff strutturato tra task dipendenti (Blocco C).

Trasferisce il risultato di un task M2 (source_task) al task successivo che
ne dipende (target_task) SOLO quando è realmente pronto: deliverable
completo, valido, coerente con la versione attesa e (se richiesta)
approvato. Funzione pura, deterministica, senza alcun accesso a MongoDB: il
chiamante (service.py) fornisce già i dizionari di piano/task/deliverable
letti da M2 (m2/models.py, m2/deliverables.py, invariati), qui MAI
modificati né riscritti — solo letti.

Nessun contenuto viene mai inventato per colmare una dipendenza mancante:
se il deliverable sorgente non esiste o non è ancora valido/approvato, lo
stato dell'handoff lo dichiara esplicitamente (WAITING_DEPENDENCY /
REJECTED_INVALID / WAITING_APPROVAL / BLOCKED_INTEGRITY) e 'content' resta
None — solo lo stato READY porta con sé un contenuto (copia difensiva)."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Optional

from ...models import now_iso
from ..agents.agent_map import AGENT_MAPPINGS

# ---------------- Stati dell'handoff ----------------
HANDOFF_READY = "READY"
HANDOFF_WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
HANDOFF_REJECTED_INVALID = "REJECTED_INVALID"
HANDOFF_WAITING_APPROVAL = "WAITING_APPROVAL"
HANDOFF_BLOCKED_INTEGRITY = "BLOCKED_INTEGRITY"

HANDOFF_STATUSES = frozenset({
    HANDOFF_READY, HANDOFF_WAITING_DEPENDENCY, HANDOFF_REJECTED_INVALID,
    HANDOFF_WAITING_APPROVAL, HANDOFF_BLOCKED_INTEGRITY,
})

# ---------------- Stati di approvazione ----------------
APPROVAL_APPROVED = "APPROVED"
APPROVAL_NOT_REQUIRED = "NOT_REQUIRED"
APPROVAL_PENDING = "PENDING"

_DELIVERABLE_OK_STATUSES = ("COMPLETATO", "COMPLETATO_CON_AVVISI")


def _capability_for_deliverable_type(deliverable_type: Optional[str]) -> Optional[str]:
    if not deliverable_type:
        return None
    for m in AGENT_MAPPINGS:
        if m.deliverable_type == deliverable_type:
            return m.capability
    return None


def compute_content_digest(content: Optional[dict]) -> Optional[str]:
    """Digest deterministico sul contenuto normalizzato (chiavi ordinate,
    encoding stabile): stesso contenuto -> stesso digest, sempre."""
    if content is None:
        return None
    canonico = json.dumps(content, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def _compute_handoff_id(plan_id: str, source_task_id: str, target_task_id: str,
                         deliverable_id: Optional[str], deliverable_version: Optional[int]) -> str:
    """Deterministico: stessi (plan, source, target, deliverable, versione)
    -> stesso handoff_id, così un secondo tentativo dello stesso handoff è
    naturalmente deduplicabile confrontando handoff_id, senza stato globale."""
    raw = f"{plan_id}|{source_task_id}|{target_task_id}|{deliverable_id}|{deliverable_version}"
    return "handoff-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class Handoff:
    handoff_id: str
    plan_id: str
    source_task_id: str
    target_task_id: str
    source_agent_id: Optional[str]
    target_agent_id: Optional[str]
    source_capability: Optional[str]
    target_capability: Optional[str]
    deliverable_id: Optional[str]
    deliverable_type: Optional[str]
    deliverable_version: Optional[int]
    deliverable_status: Optional[str]
    approval_status: str
    content: Optional[dict]
    content_digest: Optional[str]
    created_at: str
    warnings: tuple
    provenance: dict
    status: str

    def to_dict(self) -> dict:
        return {
            "handoff_id": self.handoff_id,
            "plan_id": self.plan_id,
            "source_task_id": self.source_task_id,
            "target_task_id": self.target_task_id,
            "source_agent_id": self.source_agent_id,
            "target_agent_id": self.target_agent_id,
            "source_capability": self.source_capability,
            "target_capability": self.target_capability,
            "deliverable_id": self.deliverable_id,
            "deliverable_type": self.deliverable_type,
            "deliverable_version": self.deliverable_version,
            "deliverable_status": self.deliverable_status,
            "approval_status": self.approval_status,
            "content": copy.deepcopy(self.content) if self.content is not None else None,
            "content_digest": self.content_digest,
            "created_at": self.created_at,
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
            "status": self.status,
        }


def build_handoff(
    *,
    plan: dict,
    source_task: dict,
    target_task: dict,
    source_deliverable: Optional[dict] = None,
    requires_approval: bool = True,
    expected_deliverable_version: Optional[int] = None,
    expected_content_digest: Optional[str] = None,
    now: Optional[Callable[[], str]] = None,
) -> Handoff:
    """Costruisce un Handoff a partire da dizionari già letti dal chiamante
    (mai una query db qui dentro). Non modifica MAI source_task, target_task
    o source_deliverable: solo letture, e solo copie difensive in uscita."""
    _now = now or now_iso
    plan_id = plan["id"]
    source_task_id = source_task["id"]
    target_task_id = target_task["id"]
    source_agent_id = source_task.get("agent_id")
    target_agent_id = target_task.get("agent_id")
    source_capability = _capability_for_deliverable_type(source_task.get("deliverable_type"))
    target_capability = _capability_for_deliverable_type(target_task.get("deliverable_type"))

    warnings: list = []
    provenance = {
        "plan_status": plan.get("plan_status"),
        "source_task_status": source_task.get("task_status"),
        "target_task_status": target_task.get("task_status"),
        "checked_at": _now(),
    }

    def _esito(status: str, *, deliverable_id=None, deliverable_type=None, deliverable_version=None,
               deliverable_status=None, approval_status: str = APPROVAL_NOT_REQUIRED,
               content: Optional[dict] = None, digest: Optional[str] = None) -> Handoff:
        return Handoff(
            handoff_id=_compute_handoff_id(plan_id, source_task_id, target_task_id,
                                            deliverable_id, deliverable_version),
            plan_id=plan_id, source_task_id=source_task_id, target_task_id=target_task_id,
            source_agent_id=source_agent_id, target_agent_id=target_agent_id,
            source_capability=source_capability, target_capability=target_capability,
            deliverable_id=deliverable_id, deliverable_type=deliverable_type,
            deliverable_version=deliverable_version, deliverable_status=deliverable_status,
            approval_status=approval_status,
            content=copy.deepcopy(content) if content is not None else None,
            content_digest=digest, created_at=_now(),
            warnings=tuple(warnings), provenance=dict(provenance), status=status,
        )

    dep_declared = source_task_id in (target_task.get("depends_on") or [])
    if not dep_declared:
        warnings.append(
            f"'{source_task_id}' non è una dipendenza dichiarata di '{target_task_id}' nel DAG M2."
        )

    if not dep_declared or source_task.get("task_status") != "COMPLETATA" or source_deliverable is None:
        if source_deliverable is None:
            warnings.append("Deliverable sorgente non ancora prodotto.")
        elif source_task.get("task_status") != "COMPLETATA":
            warnings.append(f"Task sorgente non completato (stato attuale: {source_task.get('task_status')}).")
        return _esito(HANDOFF_WAITING_DEPENDENCY)

    d = source_deliverable
    if (
        d.get("plan_id") != plan_id
        or d.get("task_id") != source_task_id
        or d.get("deliverable_type") != source_task.get("deliverable_type")
    ):
        warnings.append("Il deliverable sorgente non corrisponde a questo piano/task: possibile riferimento errato.")
        return _esito(
            HANDOFF_BLOCKED_INTEGRITY, deliverable_id=d.get("id"), deliverable_type=d.get("deliverable_type"),
            deliverable_version=d.get("version"), deliverable_status=d.get("status"),
        )

    if expected_deliverable_version is not None and d.get("version") != expected_deliverable_version:
        warnings.append(
            f"Versione del deliverable non coerente: attesa {expected_deliverable_version}, "
            f"trovata {d.get('version')} (probabile versione obsoleta)."
        )
        return _esito(
            HANDOFF_BLOCKED_INTEGRITY, deliverable_id=d.get("id"), deliverable_type=d.get("deliverable_type"),
            deliverable_version=d.get("version"), deliverable_status=d.get("status"),
        )

    if not d.get("content") or d.get("status") not in _DELIVERABLE_OK_STATUSES or not d.get("valid", False):
        warnings.append("Deliverable sorgente incompleto, non valido o bloccato: nessun contenuto trasferibile.")
        return _esito(
            HANDOFF_REJECTED_INVALID, deliverable_id=d.get("id"), deliverable_type=d.get("deliverable_type"),
            deliverable_version=d.get("version"), deliverable_status=d.get("status"),
        )

    digest = compute_content_digest(d.get("content"))
    if expected_content_digest is not None and digest != expected_content_digest:
        warnings.append("Il contenuto del deliverable è stato alterato rispetto al digest atteso.")
        return _esito(
            HANDOFF_BLOCKED_INTEGRITY, deliverable_id=d.get("id"), deliverable_type=d.get("deliverable_type"),
            deliverable_version=d.get("version"), deliverable_status=d.get("status"), digest=digest,
        )

    approved = bool(source_task.get("approved"))
    if requires_approval and not approved:
        warnings.append("Deliverable valido ma non ancora approvato: trasferimento in attesa.")
        return _esito(
            HANDOFF_WAITING_APPROVAL, deliverable_id=d.get("id"), deliverable_type=d.get("deliverable_type"),
            deliverable_version=d.get("version"), deliverable_status=d.get("status"),
            approval_status=APPROVAL_PENDING, digest=digest,
        )

    return _esito(
        HANDOFF_READY, deliverable_id=d.get("id"), deliverable_type=d.get("deliverable_type"),
        deliverable_version=d.get("version"), deliverable_status=d.get("status"),
        approval_status=(APPROVAL_APPROVED if requires_approval else APPROVAL_NOT_REQUIRED),
        content=d.get("content"), digest=digest,
    )


def collect_task_handoffs(
    *,
    plan: dict,
    target_task: dict,
    tasks_by_id: dict,
    deliverables_by_task_id: dict,
    requires_approval: bool = True,
    now: Optional[Callable[[], str]] = None,
) -> list:
    """Costruisce un Handoff per ciascuna dipendenza dichiarata di
    target_task, NELL'ORDINE definito dal DAG M2 (target_task['depends_on']),
    mai un ordine arbitrario basato su set/dict."""
    handoffs = []
    for dep_id in target_task.get("depends_on") or []:
        source_task = tasks_by_id.get(dep_id)
        if source_task is None:
            continue
        source_deliverable = deliverables_by_task_id.get(dep_id)
        handoffs.append(build_handoff(
            plan=plan, source_task=source_task, target_task=target_task,
            source_deliverable=source_deliverable, requires_approval=requires_approval, now=now,
        ))
    return handoffs


def all_handoffs_ready(handoffs: list) -> bool:
    return all(h.status == HANDOFF_READY for h in handoffs)
