"""Brain — registro rischi deterministico (CEO Agent 100% reale, blocco 10).

Normalizza qualunque rischio (proveniente dalle regole deterministiche di
domains/intent.py::classify_intent O da una proposta LLM validata) in una
categoria controllata + un livello di severita', e decide un'azione tra un
insieme chiuso: BLOCK (l'azione concreta resta bloccata finche' non
approvata esplicitamente — MAI la creazione del piano, vedi service.py) >
APPROVAL (piano creato ma richiede approvazione esplicita prima di ogni
effetto esterno) > CLARIFICATION (serve una domanda prima di procedere) >
REVIEW_TASK (piano creato, task di revisione aggiunto) > NONE.

Fix P0 "separazione PLANNING/EXECUTION": nessuna di queste azioni impedisce
piu' la creazione di piano/task/deliverable — quella resta bloccata solo per
il linguaggio manifestamente illegale/ingannevole intercettato a monte da
agent_selector.py::precheck_risk_and_domain (denylist). Qui si decide solo
quanta cautela serve prima dell'effetto ESTERNO REALE corrispondente.

Regola non negoziabile (sezione 10 della specifica): un rischio proposto dal
modello puo' SOLO aggiungere cautela, mai rimuoverla. Se il gate
deterministico ha gia' deciso BLOCKED_RISK (denylist), nessuna categoria/
severita' qui puo' mai riportarlo a un esito piu' permissivo — questo modulo
viene interpellato SOLO per arricchire un esito gia' READY/NEEDS_CLARIFICATION
deterministico, mai per giudicare se sostituirlo."""
from __future__ import annotations

from dataclasses import dataclass

AZIONE_BLOCK = "BLOCK"
AZIONE_APPROVAL = "APPROVAL"
AZIONE_CLARIFICATION = "CLARIFICATION"
AZIONE_REVIEW_TASK = "REVIEW_TASK"
AZIONE_NONE = "NONE"

_ORDINE_SEVERITA = {"BASSA": 0, "MEDIA": 1, "ALTA": 2}

# Categoria -> azione di base (prima di modulare per severita'). Include sia
# le categorie gia' prodotte da domains/intent.py::classify_intent (invio,
# spesa, dati_personali, consenso, irreversibile) sia categorie aggiuntive
# che una proposta LLM puo' segnalare.
_AZIONE_BASE: dict[str, str] = {
    # Fix P0 "separazione PLANNING/EXECUTION": un invio richiesto nel testo
    # (o un'azione esterna generica non altrimenti classificata) non blocca
    # PIU' la creazione del piano — richiede approvazione esplicita PRIMA
    # dell'effetto esterno reale (Tool Execution Gateway), esattamente come
    # spesa/dati_personali qui sotto. Resta bloccante SOLO cio' che e' gia'
    # intercettato a monte dalla denylist deterministica (illegale/ingannevole,
    # vedi agent_selector.py::_RISK_DENYLIST_KW) o un'azione IRREVERSIBILE
    # (cancellazione definitiva): quella resta la sola categoria che la
    # normalizzazione LLM (llm_validator.py) puo' ancora segnalare come BLOCK,
    # e anche in quel caso il piano viene comunque creato (vedi service.py) —
    # solo l'azione irreversibile specifica resta bloccata fino a
    # un'approvazione esplicita, mai l'intero obiettivo.
    "invio": AZIONE_APPROVAL,
    "azione_esterna_non_autorizzata": AZIONE_APPROVAL,
    "irreversibile": AZIONE_BLOCK,
    "spesa": AZIONE_APPROVAL,
    "dati_personali": AZIONE_APPROVAL,
    "consenso": AZIONE_CLARIFICATION,
    "budget_insufficiente": AZIONE_CLARIFICATION,
    "budget_contraddittorio": AZIONE_CLARIFICATION,
    "claim_non_supportato": AZIONE_REVIEW_TASK,
    "reputazionale": AZIONE_APPROVAL,
    "legale": AZIONE_APPROVAL,
    "compliance": AZIONE_APPROVAL,
    "qualita": AZIONE_REVIEW_TASK,
}
_AZIONE_DEFAULT_CATEGORIA_SCONOSCIUTA = AZIONE_REVIEW_TASK


def _normalizza_categoria(categoria: str) -> str:
    return (categoria or "").strip().lower().replace(" ", "_")


def _normalizza_severita(severita: str) -> str:
    s = (severita or "MEDIA").strip().upper()
    return s if s in _ORDINE_SEVERITA else "MEDIA"


@dataclass(frozen=True)
class RiskDecision:
    categoria: str
    severita: str
    azione: str
    motivo: str


def resolve_risk_action(categoria: str, severita: str = "MEDIA") -> RiskDecision:
    """Un BLOCK di base non e' MAI declassato dalla severita' (un rischio
    strutturalmente bloccante resta tale anche se dichiarato 'BASSA'
    severita' da chi lo propone: la severita' modula solo azioni non
    bloccanti). Una severita' BASSA puo' derubricare un'APPROVAL a
    REVIEW_TASK (mai a NONE: un rischio segnalato lascia sempre una
    traccia). Una severita' ALTA puo' innalzare un REVIEW_TASK/CLARIFICATION
    ad APPROVAL, mai fino a BLOCK (solo le categorie esplicitamente
    bloccanti sopra possono produrre BLOCK)."""
    cat = _normalizza_categoria(categoria)
    sev = _normalizza_severita(severita)
    base = _AZIONE_BASE.get(cat, _AZIONE_DEFAULT_CATEGORIA_SCONOSCIUTA)

    azione = base
    if base == AZIONE_BLOCK:
        azione = AZIONE_BLOCK
    elif sev == "ALTA" and base in (AZIONE_REVIEW_TASK, AZIONE_CLARIFICATION):
        azione = AZIONE_APPROVAL
    elif sev == "BASSA" and base == AZIONE_APPROVAL:
        azione = AZIONE_REVIEW_TASK

    motivo = f"Categoria '{cat}' (severita' {sev}) -> azione base '{base}', risolta in '{azione}'."
    return RiskDecision(categoria=cat, severita=sev, azione=azione, motivo=motivo)


def azione_piu_severa(a: str, b: str) -> str:
    """Ordine di severita' totale fra le cinque azioni: usato per
    aggregare piu' rischi in un'unica decisione finale, senza mai perdere
    la piu' cautelativa fra tutte quelle emerse."""
    ordine = [AZIONE_NONE, AZIONE_REVIEW_TASK, AZIONE_CLARIFICATION, AZIONE_APPROVAL, AZIONE_BLOCK]
    return a if ordine.index(a) >= ordine.index(b) else b
