"""Brain — gateway astratto dei provider di generazione contenuti.

Analogo, in scala minima, a core/gateway_registry.py + core/provider_router.py
di ACTELYA originale: un unico punto di accesso dietro cui, in futuro, potra'
comparire un provider reale (DIRECT_API/gateway), senza che il chiamante
cambi. In QUESTA fase esiste UNA sola implementazione reale: MockContentGateway,
sempre deterministica, mai una chiamata di rete. E' la modalita' predefinita
e, per ora, l'unica selezionabile: qualunque altro valore di
BRAIN_PROVIDER_GATEWAY solleva un errore esplicito invece di ripiegare in
silenzio su un comportamento diverso da quello dichiarato (stesso principio
fail-safe di core/gateway_router.py::decidi_accesso)."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod


class ProviderGatewayError(Exception):
    """Gateway provider richiesto non disponibile in questa fase."""


class ContentGateway(ABC):
    @abstractmethod
    def fill(self, template: str, **valori: str) -> str:
        """Compila un template deterministico con i valori di contesto forniti."""


class MockContentGateway(ContentGateway):
    """Unica implementazione reale in questa fase: nessuna chiamata esterna,
    nessuna rete, nessun costo. Sostituisce solo i segnaposto {chiave} nel
    template con i valori forniti (str.format), fallendo esplicitamente se un
    valore necessario manca (mai un segnaposto lasciato in chiaro nel testo
    prodotto)."""

    def fill(self, template: str, **valori: str) -> str:
        return template.format(**valori)


def get_default_gateway() -> ContentGateway:
    nome = os.environ.get("BRAIN_PROVIDER_GATEWAY", "mock").strip().lower()
    if nome != "mock":
        raise ProviderGatewayError(
            f"Gateway provider '{nome}' non disponibile in questa fase: solo 'mock' e' "
            "implementato. Nessuna chiamata reale e' consentita nell'integrazione minima del brain."
        )
    return MockContentGateway()
