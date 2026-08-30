"""Brain — selezione dinamica delle capacita' di produzione.

Attenzione: NON seleziona agenti ne' modifica il DAG. La lista di task del
piano resta quella deterministica di m2/planner.py::decompose, invariata.
Qui si decide SOLO come ogni task esistente deve essere parametrizzato (es.
quanti post social produrre, su quali canali) in base al testo
dell'obiettivo e al GoalContext estratto — l'analogo minimo, senza aggiungere
o rimuovere task, di Classificazione.agenti_opzionali/skill_per_operatore in
ACTELYA originale."""
from __future__ import annotations

import re

from .context import GoalContext

_NUMERI_ITALIANI = {
    "un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4,
    "cinque": 5, "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
}
_PATTERN_NUM_POST = re.compile(r"\b(" + "|".join(_NUMERI_ITALIANI) + r"|\d+)\s+post\b", re.IGNORECASE)

DEFAULT_POST_COUNT = 2
MAX_POST_COUNT = 6


def _numero_post(testo: str) -> int:
    m = _PATTERN_NUM_POST.search(testo or "")
    if not m:
        return DEFAULT_POST_COUNT
    grezzo = m.group(1).lower()
    n = _NUMERI_ITALIANI.get(grezzo)
    if n is None:
        try:
            n = int(grezzo)
        except ValueError:
            return DEFAULT_POST_COUNT
    return max(1, min(n, MAX_POST_COUNT))


def select_capabilities(goal_text: str, ctx: GoalContext) -> dict:
    """Ritorna i parametri di produzione derivati deterministicamente dal
    testo e dal contesto: MAI una scelta casuale o affidata al modello."""
    return {
        "post_count": _numero_post(goal_text),
        "canali": ctx.canali or ["Instagram", "Facebook"],
    }
