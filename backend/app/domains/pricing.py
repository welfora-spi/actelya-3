"""Prezzi per-token noti per provider/modello — usati per contabilizzare le
chiamate LLM REALI con una cifra piu' vicina al costo vero rispetto alla
stima unica e generica (estimator.py::PRICE_PER_TOKEN, un blended-price
pensato per le proiezioni SIMULATE di preventivo, non per la
riconciliazione di una spesa reale gia' avvenuta).

Non un listino esaustivo ne' garantito aggiornato in tempo reale (i
provider cambiano prezzi senza preavviso): copre i modelli diretti piu'
comuni con prezzi pubblici verificabili al momento della scrittura
(2026-09), space per un controllo periodico. Per qualunque provider/modello
NON in tabella (incluso 'requesty', che rivende con un markup non
dichiarato qui) il chiamante deve ricadere sul blended estimate esistente —
mai un prezzo indovinato spacciato per preciso."""
from __future__ import annotations

from typing import Optional

# {provider_type: [(prefisso_modello, prezzo_input_per_token, prezzo_output_per_token), ...]}
# Il prefisso permette di far corrispondere varianti datate (es.
# "gpt-4o-2024-08-06" -> prefisso "gpt-4o") senza un elenco infinito di
# alias esatti. Controllato in ordine: il primo prefisso che corrisponde
# vince, quindi le voci piu' specifiche vanno elencate PRIMA di quelle piu'
# generiche dello stesso provider.
_PREZZI_NOTI: dict[str, list[tuple[str, float, float]]] = {
    "openai": [
        ("gpt-4o-mini", 0.15 / 1_000_000, 0.60 / 1_000_000),
        ("gpt-4o", 2.50 / 1_000_000, 10.00 / 1_000_000),
        ("gpt-4.1-mini", 0.40 / 1_000_000, 1.60 / 1_000_000),
        ("gpt-4.1", 2.00 / 1_000_000, 8.00 / 1_000_000),
    ],
    "anthropic": [
        ("claude-3-5-haiku", 0.80 / 1_000_000, 4.00 / 1_000_000),
        ("claude-3-haiku", 0.25 / 1_000_000, 1.25 / 1_000_000),
        ("claude-haiku", 0.80 / 1_000_000, 4.00 / 1_000_000),
        ("claude-sonnet", 3.00 / 1_000_000, 15.00 / 1_000_000),
        ("claude-3-5-sonnet", 3.00 / 1_000_000, 15.00 / 1_000_000),
        ("claude-3-opus", 15.00 / 1_000_000, 75.00 / 1_000_000),
        ("claude-opus", 15.00 / 1_000_000, 75.00 / 1_000_000),
    ],
    "gemini": [
        ("gemini-1.5-flash", 0.075 / 1_000_000, 0.30 / 1_000_000),
        ("gemini-2.0-flash", 0.10 / 1_000_000, 0.40 / 1_000_000),
        ("gemini-1.5-pro", 1.25 / 1_000_000, 5.00 / 1_000_000),
        ("gemini-2.5-pro", 1.25 / 1_000_000, 5.00 / 1_000_000),
    ],
    # 'requesty' e' un reseller multi-provider con markup non dichiarato
    # all'app: nessun prezzo affidabile qui per costruzione, sempre fallback.
}


def prezzo_per_token(provider_type: str, model: Optional[str]) -> Optional[tuple[float, float]]:
    """Ritorna (prezzo_input_per_token, prezzo_output_per_token) se il
    provider/modello e' in tabella, altrimenti None — il chiamante deve
    ricadere sul blended estimate (estimator.py::PRICE_PER_TOKEN) e
    idealmente segnalare che si tratta di una stima, non di un prezzo
    reale noto."""
    modello = (model or "").lower()
    for prefisso, p_in, p_out in _PREZZI_NOTI.get((provider_type or "").lower(), []):
        if modello.startswith(prefisso):
            return p_in, p_out
    return None


def costo_reale(provider_type: str, model: Optional[str], input_tokens: int, output_tokens: int,
                fallback_price_per_token: float) -> tuple[float, bool]:
    """Ritorna (costo_usd, prezzo_noto). prezzo_noto=False significa che il
    costo e' stato calcolato con la stima generica blended (fallback), non
    con un prezzo verificato per questo provider/modello specifico — il
    chiamante puo' usarlo per segnalarlo esplicitamente invece di
    presentarlo come una cifra precisa."""
    prezzi = prezzo_per_token(provider_type, model)
    if prezzi is None:
        return round((input_tokens + output_tokens) * fallback_price_per_token, 6), False
    p_in, p_out = prezzi
    return round(input_tokens * p_in + output_tokens * p_out, 6), True
