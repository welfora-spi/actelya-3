"""Lead Generation — gate di compliance deterministico (privacy/GDPR).

Punto UNICO e non aggirabile: nessun punteggio, suggerimento del modello o
richiesta dell'utente puo' mai cambiare l'esito calcolato qui (scoring.py e
pipeline.py leggono questo esito e lo applicano come un tetto, mai come un
suggerimento negoziabile). Non e' consulenza legale: sono regole esplicite,
registrate, configurabili per organizzazione a livello di soglie — non di
principio."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_DO_NOT_CONTACT_STATI = {"do_not_contact", "blacklist", "opt-out", "opt_out", "non contattare"}
_CONSENSO_NEGATIVO = {"no", "false", "negato", "revocato", "opt-out", "opt_out"}

# Denylist conservativa per categorie particolari di dati personali (GDPR
# art. 9): rilevazione euristica su testo libero (note/ruolo), MAI accurata
# al 100% per costruzione — un falso positivo blocca comunque in modo
# sicuro (mai un falso negativo silenzioso che lasci passare un dato
# sensibile), un falso negativo resta comunque soggetto a review umana a
# valle.
_CATEGORIE_PARTICOLARI_KW = [
    r"\bsalute\b", r"\bmalattia\b", r"\bdisabilit[aà]\b", r"\breligion", r"\betnia\b",
    r"orientamento sessuale", r"\bsindacal", r"opinioni politiche", r"dati biometrici",
    r"dati genetici", r"\bcasellario\b", r"precedenti penali",
]
_CATEGORIE_PARTICOLARI_RE = re.compile("|".join(_CATEGORIE_PARTICOLARI_KW), re.IGNORECASE)


def _valore(record: dict, campo: str) -> str:
    cella = record.get(campo)
    if isinstance(cella, dict):
        return str(cella.get("value") or "").strip()
    return str(cella or "").strip()


@dataclass
class ComplianceDecision:
    status: str
    motivi: list[str] = field(default_factory=list)

    def come_dict(self) -> dict:
        return {"status": self.status, "motivi": self.motivi}


def _e_do_not_contact(record: dict) -> bool:
    stato_crm = _valore(record, "stato_crm").lower()
    consenso = _valore(record, "consenso").lower()
    return stato_crm in _DO_NOT_CONTACT_STATI or consenso in _CONSENSO_NEGATIVO


def _testo_libero_record(record: dict) -> str:
    parti = [_valore(record, c) for c in ("note", "ruolo")]
    return " ".join(p for p in parti if p)


def evaluate_compliance(record: dict, *, is_person: bool) -> ComplianceDecision:
    """record: dict di campi normalizzati (vedi normalize.py). is_person:
    True quando il record rappresenta un contatto/persona (non solo
    un'azienda) — le regole piu' severe si applicano SOLO in quel caso: una
    lista di sole aziende puo' restare READY senza dati personali associati
    a un individuo identificabile."""
    if _e_do_not_contact(record):
        return ComplianceDecision("DO_NOT_CONTACT", ["Il record e' contrassegnato come opt-out/blacklist/do-not-contact."])

    if _CATEGORIE_PARTICOLARI_RE.search(_testo_libero_record(record)):
        return ComplianceDecision("BLOCKED", ["Rilevate possibili categorie particolari di dati personali (GDPR art. 9): mai raccolte."])

    if not is_person:
        return ComplianceDecision("READY", [])

    fonte = _valore(record, "fonte")
    if not fonte:
        return ComplianceDecision("BLOCKED", ["Nessuna provenienza registrata per un contatto persona: non ammesso in lista."])

    consenso = _valore(record, "consenso")
    if not consenso:
        return ComplianceDecision("NEEDS_CLARIFICATION", ["Consenso/base giuridica non dichiarati per questo contatto."])

    if (record.get("email") or {}).get("method") == "INFERITO":
        return ComplianceDecision("APPROVAL_REQUIRED",
                                  ["Email dedotta per pattern, mai verificata: richiede approvazione esplicita prima di ogni uso."])

    return ComplianceDecision("READY", [])


# Un tetto: la decisione di compliance non e' MAI declassata da un punteggio
# commerciale piu' favorevole (vedi scoring.py::apply_compliance_ceiling).
_ORDINE_SEVERITA = ("READY", "REVIEW_REQUIRED", "NEEDS_CLARIFICATION", "APPROVAL_REQUIRED", "BLOCKED", "DO_NOT_CONTACT")


def piu_severo(a: str, b: str) -> str:
    ia = _ORDINE_SEVERITA.index(a) if a in _ORDINE_SEVERITA else 0
    ib = _ORDINE_SEVERITA.index(b) if b in _ORDINE_SEVERITA else 0
    return a if ia >= ib else b
