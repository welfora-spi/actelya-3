"""Brain — safety net specifico del brain: verifica che un deliverable
prodotto con contesto reale (azienda/prodotto/localita/pubblico) sia
davvero COERENTE con quel contesto, e non un contenuto generico o estraneo
al dominio marketing/vendite (es. contenuti pensionistici ereditati da
ACTELYA originale, che qui NON deve mai comparire).

Si affianca, senza sostituirlo, al validatore strutturale gia' presente in
m2/deliverables.py::validate_deliverable (vuoto/placeholder/PII/status
campagna): quel validatore resta l'unica autorita' sullo stato finale del
deliverable persistito (COMPLETATO/COMPLETATO_CON_AVVISI/BLOCCATO). Questo
modulo e' un controllo AGGIUNTIVO, eseguito PRIMA di proporre un contenuto
come deliverable_override: se fallisce, l'override viene scartato e si
ricade sul produttore generico di m2/deliverables.py (mai un contenuto
incoerente o fuori dominio proposto come se fosse valido)."""
from __future__ import annotations

import json
from typing import Callable

from .context import GoalContext

FORBIDDEN_DOMAIN_TERMS = [
    "pensione", "pensionistic", "inps", "tfr", "rpo", "welfora",
    "previdenz", "montante contributivo", "assegno previdenziale",
]

_GENERIC_FALLBACK_MARKERS = ["test_actelya", "lorem ipsum", "azienda generica"]


def _testo_completo(content: dict) -> str:
    return json.dumps(content, ensure_ascii=False).lower()


def check_forbidden_domains(content: dict) -> list[str]:
    testo = _testo_completo(content)
    return [f"dominio vietato rilevato: '{t}'" for t in FORBIDDEN_DOMAIN_TERMS if t in testo]


def check_context_coherence(content: dict, ctx: GoalContext) -> list[str]:
    """Errori se il deliverable NON menziona le entita' indispensabili del
    contesto (azienda/prodotto): un contenuto che le ignora e' generico per
    costruzione, anche se strutturalmente valido secondo validate_deliverable()."""
    errori: list[str] = []
    testo = _testo_completo(content)

    for marker in _GENERIC_FALLBACK_MARKERS:
        if marker in testo:
            errori.append(f"contenuto generico non ammesso: contiene '{marker}'")

    for campo, valore in (("azienda", ctx.azienda), ("prodotto", ctx.prodotto)):
        if valore and valore.lower() not in testo:
            errori.append(f"il contenuto non menziona {campo} '{valore}': incoerente col contesto dell'obiettivo")

    return errori


def guard_content(
    deliverable_type: str, content: dict, ctx: GoalContext, *, validate_deliverable: Callable
) -> tuple[bool, list[str]]:
    """Ritorna (ok, motivi). ok=True SOLO se il validatore strutturale M2 non
    blocca il contenuto E non emergono incoerenze o domini vietati. Non
    modifica mai il contenuto: solo lo accetta o lo scarta."""
    motivi: list[str] = []

    strutturale = validate_deliverable(deliverable_type, content)
    if strutturale["status"] == "BLOCCATO":
        motivi += [f"validatore M2: {e}" for e in strutturale.get("errors", [])]

    motivi += check_forbidden_domains(content)
    motivi += check_context_coherence(content, ctx)

    return (len(motivi) == 0), motivi
