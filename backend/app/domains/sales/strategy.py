"""Sales Agent — logica decisionale DETERMINISTICA (nessuna chiamata AI):
interpretazione del lead, stima dell'interesse, scelta di canale/timing, e
gestione delle risposte del prospect (next best action) attraverso l'intera
pipeline commerciale. La scrittura del TESTO del messaggio è sempre delegata
a Content Creator (domains/content_creator) — mai duplicata qui: Sales
decide COSA e PERCHÉ, non scrive il contenuto."""
from __future__ import annotations

from typing import Optional

from .models import RESPONSE_TYPES, STAGE_TERMINALI


def _valore(record: dict, campo: str) -> str:
    v = record.get(campo)
    if isinstance(v, dict):
        return str(v.get("value") or "").strip()
    return str(v or "").strip()


def analyze_lead(lead: dict) -> dict:
    """Ritorna {'pain_point','value_proposition','canale','stima_interesse',
    'motivazione'} — deterministico, basato SOLO sui componenti di scoring
    già calcolati da Lead Generation (mai una nuova inferenza sui dati grezzi:
    la stessa fonte di verità, mai una seconda interpretazione parallela)."""
    componenti_positivi = [c for c in (lead.get("score_components") or []) if c.get("punti", 0) > 0]
    motivi = [c["motivo"] for c in componenti_positivi if c.get("motivo")]
    pain_point = (
        "Coerenza con il segmento target dichiarato (" + "; ".join(motivi[:2]) + ")."
        if motivi else "Nessun segnale specifico disponibile dallo scoring: approccio generico sul settore dichiarato."
    )
    settore = _valore(lead, "settore") or "il settore dichiarato"
    value_proposition = f"Posizionare l'offerta come soluzione rilevante per aziende del settore '{settore}'."

    email = _valore(lead, "email")
    telefono = _valore(lead, "telefono")
    canale = "email" if email else ("telefono" if telefono else None)

    score = lead.get("score", 0.0) or 0.0
    if score >= 70:
        stima_interesse = "ALTA"
    elif score >= 50:
        stima_interesse = "MEDIA"
    else:
        stima_interesse = "BASSA"

    return {
        "pain_point": pain_point, "value_proposition": value_proposition, "canale": canale,
        "stima_interesse": stima_interesse,
        "motivazione": f"Punteggio ICP {score:g} (interesse {stima_interesse.lower()}); canale scelto in base "
                      f"al primo contatto disponibile ({canale or 'nessuno disponibile'}).",
    }


# (stage_corrente, response_type) -> (nuovo_stage, next_best_action). Una
# combinazione assente qui non transiziona mai in automatico (vedi
# decide_next_action: ricade sempre in ESCALATION_UMANA, mai una
# transizione inventata).
_TABELLA_TRANSIZIONI: dict[tuple[str, str], tuple[str, str]] = {}
for _stage in ("CONTATTATO", "IN_RELAZIONE", "FOLLOW_UP"):
    _TABELLA_TRANSIZIONI.update({
        (_stage, "POSITIVA"): ("RICHIESTA_APPUNTAMENTO", "PROPONI_APPUNTAMENTO"),
        (_stage, "RICHIESTA_APPUNTAMENTO"): ("RICHIESTA_APPUNTAMENTO", "PROPONI_APPUNTAMENTO"),
        (_stage, "RICHIESTA_INFORMAZIONI"): ("IN_RELAZIONE", "INVIA_INFORMAZIONI"),
        (_stage, "OBIEZIONE_PREZZO"): ("IN_RELAZIONE", "GESTISCI_OBIEZIONE_PREZZO"),
        (_stage, "NON_INTERESSATO"): ("PERSO", "NESSUNA_AZIONE"),
        (_stage, "NEGATIVA"): ("PERSO", "NESSUNA_AZIONE"),
        (_stage, "RICONTATTO_FUTURO"): ("FOLLOW_UP", "PIANIFICA_RICONTATTO"),
        (_stage, "NESSUNA_RISPOSTA"): ("FOLLOW_UP", "INVIA_FOLLOW_UP"),
        (_stage, "ESCALATION"): (_stage, "ESCALATION_UMANA"),
    })
# Il PRIMO contatto (da CONTATTATO) non ha ancora avuto un "botta e risposta":
# una risposta positiva porta a proporre un appuntamento solo se già in
# relazione — da CONTATTATO una POSITIVA apre la relazione, non salta
# direttamente alla richiesta di appuntamento (coerente con "IN_RELAZIONE"
# come stage intermedio esplicito richiesto).
_TABELLA_TRANSIZIONI[("CONTATTATO", "POSITIVA")] = ("IN_RELAZIONE", "PROPONI_APPUNTAMENTO")


def decide_next_action(*, stage: str, response_type: Optional[str]) -> dict:
    """Ritorna {'nuovo_stage','next_best_action','motivazione','richiede_escalation'}.
    Uno stage terminale (VINTO/PERSO) non transiziona mai oltre in automatico
    — richiede un'azione umana esplicita, fuori da questa funzione."""
    if stage in STAGE_TERMINALI:
        return {
            "nuovo_stage": stage, "next_best_action": "NESSUNA_AZIONE",
            "motivazione": f"Opportunità già in stato terminale '{stage}': nessuna transizione automatica.",
            "richiede_escalation": False,
        }
    if response_type is None:
        return {
            "nuovo_stage": stage, "next_best_action": "NESSUNA_AZIONE",
            "motivazione": "Nessuna risposta ancora ricevuta: nessuna transizione.",
            "richiede_escalation": False,
        }
    if response_type not in RESPONSE_TYPES:
        raise ValueError(f"Tipo di risposta sconosciuto: '{response_type}'.")

    chiave = (stage, response_type)
    if chiave in _TABELLA_TRANSIZIONI:
        nuovo_stage, azione = _TABELLA_TRANSIZIONI[chiave]
        return {
            "nuovo_stage": nuovo_stage, "next_best_action": azione,
            "motivazione": f"Risposta '{response_type}' da stage '{stage}': transizione a '{nuovo_stage}'.",
            "richiede_escalation": response_type == "ESCALATION",
        }
    return {
        "nuovo_stage": stage, "next_best_action": "ESCALATION_UMANA",
        "motivazione": f"Nessuna regola definita per (stage='{stage}', risposta='{response_type}'): "
                      f"serve una decisione umana, mai una transizione inventata.",
        "richiede_escalation": True,
    }
