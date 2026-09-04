"""Brain — connector gateway (Blocco A, esteso per il Social Media Manager
production-ready — DECISIONE UFFICIALE "100% REALE").

Punto UNICO da cui deve passare qualunque azione esterna (email, social,
CRM, ads, calendario, webhook, pagamenti...). QUESTO FILE non contiene — per
costruzione, non solo per configurazione — nessuna implementazione HTTP,
email, social, CRM o webhook: verificato da un test dedicato che ispeziona
l'AST del modulo (test_brain_connector_gateway.py). Un'azione reale è
possibile SOLO se un adapter reale è stato esplicitamente REGISTRATO su
QUESTA istanza (vedi register_real_adapter()) — mai globale, mai implicito:
un'istanza "nuda" (come quella creata da ogni test, o dalla singleton di
processo finché nessuno vi registra nulla) resta bloccata esattamente come
prima, qualunque sia il valore di REAL_EXTERNAL_ACTIONS/CONNECTOR_MODE.

L'adapter stesso (definito altrove — app/integrations/meta/, mai qui) fa da
sola qualunque chiamata di rete reale: questo file non importa mai
requests/httpx/una libreria HTTP, resta un puro dispatcher con audit trail,
anche quando dispaccia a un adapter reale.

Nessuna dipendenza da MongoDB: il registro dei tentativi è in-memory,
consultabile nei test tramite ConnectorGateway.attempts()."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

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
    # Aggiunti per il Social Media Manager (domains/social_publishing.py):
    # operazioni di sola LETTURA verso un provider social (mai una scrittura,
    # mai un'azione con effetti collaterali) — restano comunque SEMPRE
    # dry_run/bloccate come ogni altra azione qui, per costruzione: nessun
    # adapter reale esiste in questo file per nessuno dei due.
    "get_publish_status",
    "retrieve_metrics",
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
    # Il chiamante puo' chiedere "real": il gateway la concede SOLO se
    # TUTTE le condizioni in ConnectorGateway.request() sono vere per
    # QUESTA istanza — mai per il solo fatto di averla chiesta.
    requested_mode: str = "dry_run"


@dataclass
class ConnectorAttempt:
    attempt_id: str
    action_type: str
    payload_minimized: dict
    reason: str
    requested_mode: str
    result_status: str  # "DRY_RUN" | "BLOCCATO" | "IN_CORSO" | "ESEGUITO_REALE" | "ERRORE_REALE"
    created_at: str


@dataclass
class ConnectorResult:
    attempt_id: str
    status: str  # "DRY_RUN" | "ESEGUITO_REALE"
    action_type: str
    reason: str
    executed: bool = False
    # Dati restituiti dall'adapter reale (es. external_post_id, permalink):
    # SEMPRE vuoto per il percorso dry-run, mai un valore inventato qui —
    # il gateway si limita a ripassare cio' che l'adapter ha davvero
    # ricevuto dal provider.
    data: dict = field(default_factory=dict)


# Tipo dell'adapter reale registrabile: riceve la ConnectorRequest completa
# (payload incluso — es. organization_id, channel — per permettere
# all'adapter di risolvere le CREDENZIALI PER QUELLA organizzazione, mai una
# credenziale globale di processo) e ritorna un dict di dati reali del
# provider, oppure solleva un'eccezione (mai silenziosamente ignorata: vedi
# ConnectorGateway._esegui_reale).
RealAdapter = Callable[["ConnectorRequest"], dict]


class ConnectorGateway:
    """Registro in-memory dei tentativi + registro (anch'esso in-memory, per
    ISTANZA) di adapter reali. Un'istanza per processo in produzione (vedi
    get_connector_gateway()); i test ne creano istanze proprie per
    isolamento completo tra un test e l'altro — un'istanza su cui nessun
    adapter e' mai stato registrato resta bloccata esattamente come prima
    di questa estensione, qualunque sia la configurazione globale."""

    def __init__(self) -> None:
        self._attempts: list[ConnectorAttempt] = []
        self._real_adapters: dict[str, RealAdapter] = {}

    def register_real_adapter(self, action_type: str, adapter: RealAdapter) -> None:
        """Registra l'UNICO adapter reale per questo action_type su QUESTA
        istanza. Mai silenzioso: un action_type fuori whitelist e' rifiutato
        subito, non al momento della prima richiesta reale."""
        if action_type not in ALLOWED_ACTION_TYPES:
            raise RichiestaConnettoreNonValida(f"Tipo di azione esterna sconosciuto: '{action_type}'.")
        self._real_adapters[action_type] = adapter

    def unregister_real_adapter(self, action_type: str) -> None:
        self._real_adapters.pop(action_type, None)

    def request(self, req: ConnectorRequest) -> ConnectorResult:
        if req.action_type not in ALLOWED_ACTION_TYPES:
            raise RichiestaConnettoreNonValida(f"Tipo di azione esterna sconosciuto: '{req.action_type}'.")
        if not isinstance(req.payload, dict):
            raise RichiestaConnettoreNonValida("Il payload deve essere un dizionario.")

        # Prima barriera (INVARIATA rispetto a prima di questa estensione):
        # qualunque segnale che la richiesta o la configurazione globale
        # "suggeriscano" reale attiva subito una verifica completa — mai un
        # dry_run silenzioso quando qualcosa non torna.
        config_suggerisce_reale = (
            req.requested_mode != "dry_run"
            or config.CONNECTOR_MODE != "dry_run"
            or config.REAL_EXTERNAL_ACTIONS
        )
        adapter = self._real_adapters.get(req.action_type)
        # Seconda barriera: TUTTE e QUATTRO le condizioni devono essere vere
        # per concedere il reale — richiesta esplicita, ENTRAMBI i flag di
        # configurazione centrale, E un adapter reale registrato su QUESTA
        # istanza per QUESTO action_type. Nessuna da sola e' mai sufficiente.
        reale_consentito = (
            req.requested_mode == "real"
            and config.REAL_EXTERNAL_ACTIONS
            and config.CONNECTOR_MODE == "real"
            and adapter is not None
        )

        if config_suggerisce_reale and not reale_consentito:
            attempt = self._registra(req, "BLOCCATO")
            raise AzioneEsternaBloccata(
                f"Tentativo di azione esterna reale bloccato (tentativo {attempt.attempt_id}, "
                f"azione '{req.action_type}'): condizioni per l'esecuzione reale non tutte soddisfatte "
                "(REAL_EXTERNAL_ACTIONS, CONNECTOR_MODE, adapter reale registrato)."
            )

        if reale_consentito:
            return self._esegui_reale(req, adapter)

        attempt = self._registra(req, "DRY_RUN")
        return ConnectorResult(
            attempt_id=attempt.attempt_id,
            status="DRY_RUN",
            action_type=req.action_type,
            reason=req.reason,
            executed=False,
        )

    def _esegui_reale(self, req: ConnectorRequest, adapter: RealAdapter) -> ConnectorResult:
        # Registrato PRIMA della chiamata reale (stesso principio "esito
        # incerto" gia' usato per Requesty/Runway): anche un crash o un
        # timeout a meta' chiamata lascia un tentativo IN_CORSO tracciato,
        # mai un'azione reale scomparsa senza traccia.
        attempt = self._registra(req, "IN_CORSO")
        try:
            dati = adapter(req)
        except Exception:
            self._aggiorna_esito(attempt.attempt_id, "ERRORE_REALE")
            raise
        self._aggiorna_esito(attempt.attempt_id, "ESEGUITO_REALE")
        return ConnectorResult(
            attempt_id=attempt.attempt_id,
            status="ESEGUITO_REALE",
            action_type=req.action_type,
            reason=req.reason,
            executed=True,
            data=dati if isinstance(dati, dict) else {},
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

    def _aggiorna_esito(self, attempt_id: str, nuovo_status: str) -> None:
        for a in self._attempts:
            if a.attempt_id == attempt_id:
                a.result_status = nuovo_status
                return

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
