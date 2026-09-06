"""Lead Generation — decide COSA fare dopo aver qualificato/arricchito un
lead: continuare l'enrichment (con quale capability ASTRATTA — mai un nome
di provider, vedi Tool Registry), scartare, tenere in nurturing, o renderlo
pronto per l'handoff a Sales. Deterministico, nessuna chiamata AI.

Le capability richieste si calcolano leggendo DIRETTAMENTE i campi del
record (non solo 'missing_data' di scoring.py, che traccia soltanto i campi
rilevanti per il PUNTEGGIO ICP): un lead può essere QUALIFIED per l'ICP ma
privo di un canale di contatto (email/telefono) — in quel caso l'arricchimento
resta necessario PRIMA dell'handoff a Sales, che altrimenti riceverebbe un
lead non raggiungibile."""
from __future__ import annotations

# campo del record -> capability astratta del Tool Registry che potrebbe
# colmarlo. Un agente non conosce MAI il provider concreto (Apollo/Hunter/
# Tavily/...): solo la capability, risolta dal Tool Registry/Gateway quando
# un provider reale sarà collegato (vedi app/tools/registry.py).
CAPABILITY_PER_CAMPO_MANCANTE: dict[str, str] = {
    "email": "EMAIL_DISCOVERY",
    "telefono": "PERSON_ENRICHMENT",
    "settore": "COMPANY_ENRICHMENT",
    "dimensione": "COMPANY_ENRICHMENT",
    "localita": "COMPANY_ENRICHMENT",
}
# Campi la cui assenza blocca comunque l'handoff a Sales anche a fronte di un
# punteggio QUALIFIED: senza un canale di contatto Sales non può agire.
_CAMPI_CONTATTO = ("email", "telefono")

AZIONE_CONTINUA_ENRICHMENT = "CONTINUA_ENRICHMENT"
AZIONE_SCARTA = "SCARTA"
AZIONE_NURTURING = "NURTURING"
AZIONE_PRONTO_PER_SALES = "PRONTO_PER_SALES"

NEXT_ACTIONS = (AZIONE_CONTINUA_ENRICHMENT, AZIONE_SCARTA, AZIONE_NURTURING, AZIONE_PRONTO_PER_SALES)


def _valore(record: dict, campo: str) -> str:
    v = record.get(campo)
    if isinstance(v, dict):
        return str(v.get("value") or "").strip()
    return str(v or "").strip()


def _campi_arricchibili_vuoti(record: dict, *, missing_data: list[str]) -> list[str]:
    """Unione di: (a) i campi che scoring.py ha già segnalato mancanti
    (settore/localita/dimensione) e (b) i canali di contatto, verificati
    direttamente sul record (scoring.py non li traccia in missing_data,
    essendo irrilevanti per il punteggio ICP ma essenziali per la
    contattabilità)."""
    vuoti = set(c for c in (missing_data or []) if c in CAPABILITY_PER_CAMPO_MANCANTE)
    for campo in _CAMPI_CONTATTO:
        if not _valore(record, campo):
            vuoti.add(campo)
    return sorted(vuoti)


def decide_next_action(*, qualification_status: str, missing_data: list[str],
                       record: dict | None = None) -> dict:
    """Ritorna {'azione', 'motivazione', 'capability_richieste'}. Un
    'EXCLUDED'/'DO_NOT_CONTACT' è SEMPRE scartato, mai un ulteriore
    tentativo di arricchimento o contatto (stesso principio assoluto già
    applicato da scoring.py::_qualifica — mai negoziabile qui)."""
    record = record or {}

    if qualification_status in ("EXCLUDED", "DO_NOT_CONTACT"):
        return {
            "azione": AZIONE_SCARTA,
            "motivazione": f"Qualificazione '{qualification_status}': lead escluso, nessun ulteriore "
                          f"arricchimento o contatto.",
            "capability_richieste": [],
        }

    campi_vuoti = _campi_arricchibili_vuoti(record, missing_data=missing_data)
    capability_richieste = sorted({CAPABILITY_PER_CAMPO_MANCANTE[c] for c in campi_vuoti})

    if qualification_status in ("INCOMPLETE", "REVIEW_REQUIRED"):
        if capability_richieste:
            return {
                "azione": AZIONE_CONTINUA_ENRICHMENT,
                "motivazione": f"Dati mancanti ({', '.join(campi_vuoti)}): arricchimento necessario prima "
                              f"di una decisione definitiva.",
                "capability_richieste": capability_richieste,
            }
        return {
            "azione": AZIONE_NURTURING,
            "motivazione": f"Qualificazione '{qualification_status}' senza ulteriori dati recuperabili "
                          f"tramite una capability nota: non ancora pronto per Sales, tenuto in nurturing.",
            "capability_richieste": [],
        }

    if qualification_status == "QUALIFIED":
        # Basta UN canale di contatto (email O telefono) per essere
        # raggiungibile: non si richiede mai la presenza di entrambi.
        ha_contatto = any(_valore(record, c) for c in _CAMPI_CONTATTO)
        if not ha_contatto:
            capability_contatto = sorted({CAPABILITY_PER_CAMPO_MANCANTE[c] for c in _CAMPI_CONTATTO})
            return {
                "azione": AZIONE_CONTINUA_ENRICHMENT,
                "motivazione": "Punteggio ICP sufficiente ma nessun canale di contatto disponibile: "
                              "l'arricchimento resta necessario prima dell'handoff (Sales non potrebbe "
                              "altrimenti raggiungere il lead).",
                "capability_richieste": capability_contatto,
            }
        return {
            "azione": AZIONE_PRONTO_PER_SALES,
            "motivazione": "Punteggio, compliance e contattabilità sufficienti: pronto per l'handoff a Sales.",
            "capability_richieste": [],
        }

    return {
        "azione": AZIONE_NURTURING,
        "motivazione": f"Stato '{qualification_status}' non gestito esplicitamente: tenuto in nurturing "
                      f"per prudenza (mai uno scarto o un handoff non giustificato).",
        "capability_richieste": [],
    }
