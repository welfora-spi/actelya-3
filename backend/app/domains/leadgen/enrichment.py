"""Lead Generation — applica il risultato di un arricchimento (oggi sempre
da un adapter di TEST: nessun provider reale — Apollo/Hunter/Tavily/Firecrawl
— e' collegato in questa fase, vedi Tool Registry). Valida, normalizza,
rileva conflitti (stessa scala di confidenza per metodo gia' usata da
scoring.py — mai una seconda scala parallela), aggiorna il lead e ricalcola
scoring + prossima azione. Nessuna chiamata di rete qui: il chiamante ha
gia' ottenuto 'result_fields' da un adapter (reale in futuro, fake nei
test) — questo modulo e' la logica applicativa che resta identica quando
l'adapter cambierà."""
from __future__ import annotations

from typing import Optional

from .compliance import evaluate_compliance
from .next_action import decide_next_action
from .normalize import normalize_domain, normalize_email, normalize_phone, normalize_text
from .scoring import _CONFIDENCE_PER_METODO, score_record

_NORMALIZER_PER_CAMPO = {
    "email": normalize_email, "telefono": normalize_phone, "dominio": normalize_domain, "sito": normalize_domain,
}


def _normalizza_campo(campo: str, valore: str, *, method: str):
    fn = _NORMALIZER_PER_CAMPO.get(campo)
    if fn:
        return fn(valore, method=method)
    return normalize_text(valore, method=method)


def apply_enrichment_result(record: dict, *, result_fields: dict, source_method: str = "ESTRATTO") -> dict:
    """Ritorna {'record': dict, 'conflitti': [...]}. Un campo già presente
    con priorità di confidenza >= a quella del nuovo valore non viene MAI
    sovrascritto (un dato verificato non è mai declassato da un dato
    arricchito); un disaccordo tra valori diversi con la STESSA priorità è
    sempre segnalato come conflitto, mai risolto in silenzio."""
    aggiornato = dict(record)
    conflitti: list[dict] = []
    nuova_confidenza = _CONFIDENCE_PER_METODO.get(source_method, 0.0)

    for campo, valore_grezzo in (result_fields or {}).items():
        if not str(valore_grezzo or "").strip():
            continue
        normalizzato = _normalizza_campo(campo, str(valore_grezzo), method=source_method)
        if not normalizzato.value:
            continue  # normalizzazione fallita (es. email non valida): mai un dato scartato dal formato salvato comunque
        esistente = aggiornato.get(campo)
        if not isinstance(esistente, dict) or not (esistente.get("value") or "").strip():
            aggiornato[campo] = normalizzato.come_dict()
            continue

        valore_esistente = (esistente.get("value") or "").strip().lower()
        if valore_esistente == (normalizzato.value or "").strip().lower():
            continue  # stesso valore: nessun conflitto, nessuna modifica

        confidenza_esistente = _CONFIDENCE_PER_METODO.get(esistente.get("method"), 0.0)
        if nuova_confidenza > confidenza_esistente:
            conflitti.append({
                "campo": campo, "valore_precedente": esistente.get("value"), "valore_nuovo": normalizzato.value,
                "risoluzione": "sostituito (priorità del nuovo dato superiore)",
            })
            aggiornato[campo] = normalizzato.come_dict()
        elif nuova_confidenza == confidenza_esistente:
            conflitti.append({
                "campo": campo, "valore_precedente": esistente.get("value"), "valore_nuovo": normalizzato.value,
                "risoluzione": "mantenuto il valore esistente (stessa priorità: conflitto non risolto automaticamente)",
            })
        else:
            conflitti.append({
                "campo": campo, "valore_precedente": esistente.get("value"), "valore_nuovo": normalizzato.value,
                "risoluzione": "scartato (priorità inferiore al dato già presente)",
            })

    return {"record": aggiornato, "conflitti": conflitti}


def rescore_after_enrichment(record: dict, *, icp: dict, is_person: bool,
                             exclude_existing_customers: bool = True) -> dict:
    """Rivaluta compliance + scoring + prossima azione sul record aggiornato
    — mai un vecchio punteggio/qualificazione tenuto dopo un arricchimento."""
    decisione = evaluate_compliance(record, is_person=is_person)
    esito = score_record(record, icp, is_person=is_person, compliance_status=decisione.status,
                         exclude_existing_customers=exclude_existing_customers)
    azione = decide_next_action(qualification_status=esito.qualification_status,
                                missing_data=esito.dati_mancanti, record=record)
    return {
        "score": esito.score, "score_components": [c.come_dict() for c in esito.componenti],
        "confidence": esito.confidence, "missing_data": esito.dati_mancanti,
        "qualification_status": esito.qualification_status,
        "compliance_status": decisione.status, "compliance_motivi": decisione.motivi,
        "rules_applied": esito.regole_applicate, "next_action": azione,
    }
