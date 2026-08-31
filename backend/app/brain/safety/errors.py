"""Brain — tassonomia degli errori (Blocco A).

Nessuna dipendenza esterna, nessuna dipendenza da MongoDB. Ogni errore del
brain eredita da BrainError, così un chiamante può intercettare "qualunque
problema del brain" con un solo except, o un'eccezione specifica quando
serve una reazione diversa (es. NEEDS_CLARIFICATION vs azione bloccata)."""
from __future__ import annotations


class BrainError(Exception):
    """Base di tutti gli errori del brain."""


class ConfigurazioneNonSicura(BrainError):
    """La configurazione centrale (config.py) non può garantire una
    modalità sicura. Non dovrebbe mai accadere per costruzione — ogni
    valore non riconosciuto in config.py ricade sempre sul default sicuro
    — ma resta disponibile come guardia esplicita per un chiamante che
    voglia verificarlo comunque prima di un'operazione sensibile."""


class AzioneEsternaBloccata(BrainError):
    """Sollevata da gateways/connector_gateway.py quando viene richiesta,
    anche solo implicitamente (requested_mode diverso da 'dry_run', o
    configurazione manomessa), una modalità reale invece di dry-run.
    Il tentativo viene comunque registrato prima di sollevare l'eccezione."""


class RichiestaConnettoreNonValida(BrainError):
    """Tipo di azione esterna sconosciuto (fuori dalla whitelist chiusa) o
    payload malformato passato al connector gateway."""


class RispostaAgenteNonValida(BrainError):
    """Un agente (reale o simulato) ha prodotto un output che non rispetta
    lo schema/contratto atteso. Ispirata a core/errors.py::
    RispostaAgenteNonValida di ACTELYA originale: prevista per portare con
    sé costo/token già eventualmente sostenuti, quando in futuro esisterà
    un gateway AI reale (oggi sempre None: nessuna chiamata reale avviene)."""

    def __init__(
        self,
        reason: str,
        *,
        costo_usd: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.costo_usd = costo_usd
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class AttivitaBrainInterrotta(BrainError):
    """Un'attività del brain è stata interrotta in modo sicuro (fallback
    esplicito) prima del completamento — mai un'eccezione non gestita che
    lascia uno stato inconsistente. Usata dai blocchi successivi (triage,
    planning, synthesis) per segnalare un arresto deliberato."""
