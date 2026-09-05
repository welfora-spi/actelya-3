"""Lead Generation — scoring deterministico e spiegabile contro un ICP.

Ogni punteggio si scompone in componenti motivate (mai un numero senza
spiegazione). La qualificazione finale e' SEMPRE vincolata dall'esito del
gate compliance (compliance.py): un punteggio alto non declassa mai un
BLOCKED/DO_NOT_CONTACT a qualcosa di piu' permissivo — vedi
apply_compliance_ceiling. L'esclusione clienti esistenti/settore vietato
prevale sempre sul punteggio commerciale."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

CAMPI_COMPLETEZZA = ("ragione_sociale", "email", "telefono", "sito", "settore", "citta")

# Confidence indicativa per metodo di provenienza (0-1): mai un valore
# VERIFICATO trattato come equivalente a uno INFERITO.
_CONFIDENCE_PER_METODO = {
    "VERIFICATO": 1.0, "FORNITO": 0.85, "ESTRATTO": 0.75, "PUBBLICO": 0.6,
    "INFERITO": 0.35, "NON_VERIFICATO": 0.2, "CONTRADDITTORIO": 0.15, "MANCANTE": 0.0, "SCADUTO": 0.1,
}


def _cella(record: dict, campo: str) -> dict:
    v = record.get(campo)
    return v if isinstance(v, dict) else {}


def _valore(record: dict, campo: str) -> str:
    return str(_cella(record, campo).get("value") or "").strip()


@dataclass
class ScoreComponent:
    nome: str
    punti: float
    motivo: str

    def come_dict(self) -> dict:
        return {"nome": self.nome, "punti": self.punti, "motivo": self.motivo}


@dataclass
class ScoringResult:
    score: float
    componenti: list = field(default_factory=list)     # list[ScoreComponent]
    confidence: float = 0.0
    dati_mancanti: list = field(default_factory=list)
    regole_applicate: list = field(default_factory=list)
    qualification_status: str = "REVIEW_REQUIRED"
    compliance_status: str = "READY"

    def come_dict(self) -> dict:
        return {
            "score": self.score, "componenti": [c.come_dict() for c in self.componenti],
            "confidence": self.confidence, "dati_mancanti": self.dati_mancanti,
            "regole_applicate": self.regole_applicate, "qualification_status": self.qualification_status,
            "compliance_status": self.compliance_status,
        }


def _score_settore(record: dict, icp: dict, dati_mancanti: list, regole: list) -> ScoreComponent:
    settore = _valore(record, "settore")
    if not settore:
        dati_mancanti.append("settore")
        return ScoreComponent("settore", 0.0, "Settore non dichiarato: nessun punto assegnato.")
    esclusi = {s.lower() for s in (icp.get("settori_esclusi") or [])}
    if settore.lower() in esclusi:
        regole.append("settore_escluso")
        return ScoreComponent("settore", -100.0, f"Settore '{settore}' esplicitamente escluso dall'ICP.")
    inclusi = {s.lower() for s in (icp.get("settori_inclusi") or [])}
    if inclusi:
        match = settore.lower() in inclusi
        return ScoreComponent("settore", 20.0 if match else 0.0,
                              f"Settore '{settore}' {'coerente' if match else 'non coerente'} con i settori inclusi dell'ICP.")
    return ScoreComponent("settore", 8.0, "Nessun filtro settore nell'ICP: punteggio neutro.")


def _score_localita(record: dict, icp: dict, dati_mancanti: list) -> ScoreComponent:
    citta = _valore(record, "citta")
    regione = _valore(record, "regione")
    localita_icp = [l.lower() for l in (icp.get("localita") or [])]
    if not citta and not regione:
        dati_mancanti.append("localita")
        return ScoreComponent("localita", 0.0, "Localita' non dichiarata: nessun punto assegnato.")
    if not localita_icp:
        return ScoreComponent("localita", 5.0, "Nessun filtro geografico nell'ICP: punteggio neutro.")
    match = citta.lower() in localita_icp or regione.lower() in localita_icp
    return ScoreComponent("localita", 15.0 if match else 0.0,
                          f"Localita' '{citta or regione}' {'coerente' if match else 'non coerente'} con l'ICP.")


def _score_dimensione(record: dict, icp: dict, dati_mancanti: list) -> ScoreComponent:
    grezzo = _valore(record, "dipendenti") or _valore(record, "dimensione")
    if not grezzo:
        dati_mancanti.append("dimensione")
        return ScoreComponent("dimensione", 0.0, "Dimensione aziendale non dichiarata: nessun punto assegnato.")
    try:
        valore = float(grezzo)
    except ValueError:
        return ScoreComponent("dimensione", 0.0, "Dimensione dichiarata non numerica: nessun punto assegnato.")
    dmin, dmax = icp.get("dimensione_min"), icp.get("dimensione_max")
    if dmin is None and dmax is None:
        return ScoreComponent("dimensione", 5.0, "Nessun filtro dimensione nell'ICP: punteggio neutro.")
    entro = (dmin is None or valore >= dmin) and (dmax is None or valore <= dmax)
    return ScoreComponent("dimensione", 15.0 if entro else 0.0,
                          f"Dimensione {valore:g} {'entro' if entro else 'fuori dal'} range ICP.")


def _score_ruolo(record: dict, icp: dict, is_person: bool) -> Optional[ScoreComponent]:
    if not is_person:
        return None
    ruolo = _valore(record, "ruolo")
    ruoli_icp = [r.lower() for r in (icp.get("ruoli_decisionali") or [])]
    if not ruolo:
        return ScoreComponent("ruolo", 0.0, "Ruolo del contatto non dichiarato: nessun punto assegnato.")
    if not ruoli_icp:
        return ScoreComponent("ruolo", 5.0, "Nessun ruolo decisionale specificato nell'ICP: punteggio neutro.")
    match = any(r in ruolo.lower() for r in ruoli_icp)
    return ScoreComponent("ruolo", 20.0 if match else 0.0,
                          f"Ruolo '{ruolo}' {'coerente' if match else 'non coerente'} con i ruoli decisionali dell'ICP.")


def _score_completezza_e_verificabilita(record: dict) -> list:
    compilati = sum(1 for c in CAMPI_COMPLETEZZA if _valore(record, c))
    comp = ScoreComponent("completezza_dati", compilati * 2.0, f"{compilati}/{len(CAMPI_COMPLETEZZA)} campi chiave compilati.")
    dominio_presente = bool(_valore(record, "dominio") or _valore(record, "sito"))
    verif = ScoreComponent("verificabilita", 10.0 if dominio_presente else 0.0,
                           "Dominio aziendale presente: piu' facilmente verificabile." if dominio_presente
                           else "Nessun dominio/sito dichiarato: verificabilita' limitata.")
    return [comp, verif]


def _confidence_media(record: dict) -> float:
    metodi = [_cella(record, c).get("method") for c in CAMPI_COMPLETEZZA]
    valori = [_CONFIDENCE_PER_METODO.get(m, 0.0) for m in metodi if m]
    return sum(valori) / len(valori) if valori else 0.0


def score_record(record: dict, icp: dict, *, is_person: bool, compliance_status: str,
                 exclude_existing_customers: bool = True) -> ScoringResult:
    dati_mancanti: list[str] = []
    regole: list[str] = []
    componenti = [
        _score_settore(record, icp, dati_mancanti, regole),
        _score_localita(record, icp, dati_mancanti),
        _score_dimensione(record, icp, dati_mancanti),
    ]
    ruolo_comp = _score_ruolo(record, icp, is_person)
    if ruolo_comp:
        componenti.append(ruolo_comp)
    componenti.extend(_score_completezza_e_verificabilita(record))

    score_grezzo = sum(c.punti for c in componenti)
    score = max(0.0, min(100.0, score_grezzo))
    confidence = round(_confidence_media(record), 2)

    cliente_esistente = _valore(record, "cliente_esistente") == "true"
    if exclude_existing_customers and cliente_esistente:
        regole.append("cliente_esistente_escluso")

    qualification = _qualifica(
        score=score, dati_mancanti=dati_mancanti, regole=regole,
        compliance_status=compliance_status,
    )

    return ScoringResult(
        score=round(score, 1), componenti=componenti, confidence=confidence,
        dati_mancanti=dati_mancanti, regole_applicate=regole,
        qualification_status=qualification, compliance_status=compliance_status,
    )


def _qualifica(*, score: float, dati_mancanti: list, regole: list, compliance_status: str) -> str:
    """Un opt-out o una regola di compliance PREVALE SEMPRE sul punteggio
    commerciale (vincolo esplicito, mai negoziabile): valutato per primo,
    prima di ogni considerazione sul punteggio."""
    if compliance_status == "DO_NOT_CONTACT":
        return "DO_NOT_CONTACT"
    if compliance_status == "BLOCKED":
        return "EXCLUDED"
    if "settore_escluso" in regole or "cliente_esistente_escluso" in regole:
        return "EXCLUDED"
    if compliance_status in ("NEEDS_CLARIFICATION", "APPROVAL_REQUIRED", "REVIEW_REQUIRED"):
        return "REVIEW_REQUIRED"
    if len(dati_mancanti) >= 2 and score < 40:
        return "INCOMPLETE"
    if score >= 50:
        return "QUALIFIED"
    return "REVIEW_REQUIRED"
