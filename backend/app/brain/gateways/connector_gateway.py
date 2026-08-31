"""Brain — connector gateway (Blocco A).

Punto UNICO da cui deve passare qualunque futura azione esterna (email,
social, CRM, ads, calendario, webhook, pagamenti...). In questa fase
l'UNICA modalità esistente è DRY_RUN: questo file non contiene — per
costruzione, non solo per configurazione — nessuna implementazione HTTP,
email, social, CRM o webhook. Anche se qualcuno impostasse
REAL_EXTERNAL_ACTIONS/CONNECTOR_MODE su un valore che chiede l'esecuzione
reale, non esiste qui alcun codice in grado di eseguirla: il gateway
registra il tentativo e solleva sempre AzioneEsternaBloccata prima di
qualunque cosa che assomigli a un'azione.

Nessuna chiamata di rete, nessuna dipendenza da MongoDB: il registro dei
tentativi è in-memory, consultabile nei test tramite
ConnectorGateway.attempts()."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .. import config
from ..safety.errors import AzioneEsternaBloccata, RichiestaConnettoreNonValida

# Whitelist chiusa dei tipi di azione esterna riconosciuti. Un action_type
# fuori da questo insieme viene SEMPRE rifiutato: nessun fallback silenzioso
# a un tipo generico.
ALLOWED_ACTION_TYPES = frozenset({
    "send_email",
    "publish_social",
    "crm_write",
    "ads_campaign",
    "calendar_event",
    "webhook_call",
    "payment",
})

_CAMPI_SENSIBILI = ("api_key", "password", "token", "secret", "authorization", "credential")


def _minimizza_payload(payload: dict) -> dict:
    """Copia il payload redigendo ricorsivamente qualunque campo il cui
    nome somigli a una credenziale. Non modifica MAI il dict originale
    (nuovo dict a ogni livello, mai un riferimento condiviso)."""
    pulito: dict = {}
    for chiave, valore in payload.items():
        if any(p in str(chiave).lower() for p in _CAMPI_SENSIBILI):
            pulito[chiave] = "[REDACTED]"
        elif isinstance(valore, dict):
            pulito[chiave] = _minimizza_payload(valore)
        else:
            pulito[chiave] = valore
    return pulito


@dataclass
class ConnectorRequest:
    action_type: str
    payload: dict = field(default_factory=dict)
    reason: str = ""
    # Il chiamante può "chiedere" una modalità diversa da dry_run: il
    # gateway la rifiuta SEMPRE in questa fase (vedi ConnectorGateway.request).
    requested_mode: str = "dry_run"


@dataclass
class ConnectorAttempt:
    attempt_id: str
    action_type: str
    payload_minimized: dict
    reason: str
    requested_mode: str
    result_status: str  # "DRY_RUN" | "BLOCCATO"
    created_at: str


@dataclass
class ConnectorResult:
    attempt_id: str
    status: str  # sempre "DRY_RUN" quando la richiesta va a buon fine
    action_type: str
    reason: str
    executed: bool = False


class ConnectorGateway:
    """Registro in-memory dei tentativi. Un'istanza per processo in
    produzione (vedi get_connector_gateway()); i test ne creano istanze
    proprie per isolamento completo tra un test e l'altro."""

    def __init__(self) -> None:
        self._attempts: list[ConnectorAttempt] = []

    def request(self, req: ConnectorRequest) -> ConnectorResult:
        if req.action_type not in ALLOWED_ACTION_TYPES:
            raise RichiestaConnettoreNonValida(f"Tipo di azione esterna sconosciuto: '{req.action_type}'.")
        if not isinstance(req.payload, dict):
            raise RichiestaConnettoreNonValida("Il payload deve essere un dizionario.")

        modalita_reale_richiesta = (
            req.requested_mode != "dry_run"
            or config.CONNECTOR_MODE != "dry_run"
            or config.REAL_EXTERNAL_ACTIONS
        )
        if modalita_reale_richiesta:
            attempt = self._registra(req, "BLOCCATO")
            raise AzioneEsternaBloccata(
                f"Tentativo di azione esterna reale bloccato (tentativo {attempt.attempt_id}, "
                f"azione '{req.action_type}'): nessuna modalità reale è consentita in questa fase."
            )

        attempt = self._registra(req, "DRY_RUN")
        return ConnectorResult(
            attempt_id=attempt.attempt_id,
            status="DRY_RUN",
            action_type=req.action_type,
            reason=req.reason,
            executed=False,
        )

    def _registra(self, req: ConnectorRequest, status: str) -> ConnectorAttempt:
        attempt = ConnectorAttempt(
            attempt_id=str(uuid.uuid4()),
            action_type=req.action_type,
            payload_minimized=_minimizza_payload(req.payload if isinstance(req.payload, dict) else {}),
            reason=req.reason,
            requested_mode=req.requested_mode,
            result_status=status,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._attempts.append(attempt)
        return attempt

    def attempts(self) -> list[ConnectorAttempt]:
        """Copia della lista: il chiamante non può alterare il registro
        interno modificando il valore restituito."""
        return list(self._attempts)


_default_gateway: Optional[ConnectorGateway] = None


def get_connector_gateway() -> ConnectorGateway:
    """Istanza condivisa di processo (lazy singleton). I test dovrebbero
    preferire `ConnectorGateway()` diretto per isolamento tra casi."""
    global _default_gateway
    if _default_gateway is None:
        _default_gateway = ConnectorGateway()
    return _default_gateway
