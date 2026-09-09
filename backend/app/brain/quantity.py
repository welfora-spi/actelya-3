"""Estrazione deterministica della quantita' di contenuti richiesta in un
obiettivo in linguaggio naturale (es. 'tre post' -> 3). Nessuna chiamata AI,
nessuna dipendenza pesante — modulo separato da brain/service.py apposta,
cosi' resta importabile da solo (anche nei test) senza trascinare l'intero
grafo di import del servizio brain."""
from __future__ import annotations

import re

_NUMERI_ITALIANI = {
    "un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
}
_QUANTITA_RE = re.compile(
    r"\b(\d{1,2}|" + "|".join(_NUMERI_ITALIANI) + r")\s+"
    r"(post|contenuti|testi|articoli|caption|annunci)\b", re.IGNORECASE,
)


MASSIMO_CONSENTITO = 10  # tetto prudente: mai una generazione massiva da un solo obiettivo


def extract_requested_quantity_detailed(goal_text: str) -> dict:
    """Come extract_requested_quantity, ma restituisce anche il numero
    grezzo riconosciuto e se e' stato troncato — il chiamante (brain/
    service.py) deve rendere il troncamento esplicito (avviso persistito),
    mai un limite applicato in silenzio che l'utente non puo' notare."""
    m = _QUANTITA_RE.search(goal_text or "")
    if not m:
        return {"quantity": 1, "raw": None, "truncated": False}
    grezzo = m.group(1).lower()
    n = int(grezzo) if grezzo.isdigit() else _NUMERI_ITALIANI.get(grezzo, 1)
    n = max(1, n)
    applicata = min(n, MASSIMO_CONSENTITO)
    return {"quantity": applicata, "raw": n, "truncated": n > MASSIMO_CONSENTITO}


def extract_requested_quantity(goal_text: str) -> int:
    """Numero di contenuti distinti richiesti nel testo dell'obiettivo (es.
    'tre post', '3 contenuti') — deterministico, stesso principio di
    risk_registry.py (pattern espliciti, mai un'inferenza implicita).
    Default 1 quando non trovato: comportamento invariato per ogni obiettivo
    che non specifica una quantita'. Wrapper semplice su
    extract_requested_quantity_detailed per i chiamanti che non hanno
    bisogno di sapere se il tetto ha troncato la richiesta."""
    return extract_requested_quantity_detailed(goal_text)["quantity"]
