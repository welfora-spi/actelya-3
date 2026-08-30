"""Hybrid semantic intent classifier: deterministic rules first, AI only for ambiguity.
In milestone 1 no real AI calls are made; the AI branch is a clearly-marked simulated stub."""
import re

# Deterministic triggers for external / sensitive actions (mandatory rules).
EXTERNAL_VERBS = [
    "invia", "inviare", "invio", "manda", "mandare", "spedisci", "spedire",
    "pubblica", "pubblicare", "posta", "contatta", "contattare", "chiama",
    "chiamare", "telefona", "programma invio", "schedula", "lancia", "attiva la campagna",
    "avvia la campagna",
]
PRODUCTION_VERBS = [
    "scrivi", "scrivere", "prepara", "preparare", "crea", "creare", "genera",
    "generare", "redigi", "redigere", "bozza", "progetta", "pianifica", "elabora",
]
SPEND_TERMS = ["spesa", "budget", "paga", "acquista", "advertising", "ads", "sponsorizza"]
PERSONAL_DATA_TERMS = ["prospect", "clienti", "contatti", "lista", "destinatari", "email dei", "mail ai"]
CONSENT_TERMS = ["consenso", "opt-in", "iscritti", "newsletter"]
IRREVERSIBLE_TERMS = ["elimina", "cancella", "rimuovi definitivamente"]


def _found(text: str, terms: list[str]) -> list[str]:
    return [t for t in terms if t in text]


# Remove negated external intents ("non inviare", "senza inviare", "mai pubblicare", ...)
_NEGATION_RE = re.compile(
    r"\b(non|senza|mai|no)\s+\w*\s*(invi\w*|mand\w*|spedi\w*|pubblic\w*|contatt\w*|"
    r"chiam\w*|telefon\w*|post\w*|lanci\w*|attiv\w*|avvi\w*)",
    flags=re.IGNORECASE,
)


def classify_intent(goal_text: str, ai_real_mode: bool = False) -> dict:
    raw = (goal_text or "").lower().strip()
    applied_rules = []
    risk_flags = []

    negated = bool(_NEGATION_RE.search(raw))
    # Text used for external-verb detection has negated spans stripped out.
    text_for_ext = _NEGATION_RE.sub(" ", raw)
    text = raw

    ext = _found(text_for_ext, EXTERNAL_VERBS)
    if negated:
        applied_rules.append("NEGAZIONE_INVIO: rilevata istruzione di NON inviare/pubblicare")
    prod = _found(text, PRODUCTION_VERBS)

    if ext:
        applied_rules.append("REGOLA_AZIONE_ESTERNA: rilevato verbo di invio/pubblicazione/contatto")
        risk_flags.append("invio")
    if _found(text, SPEND_TERMS):
        risk_flags.append("spesa")
        applied_rules.append("REGOLA_SPESA")
    if _found(text, PERSONAL_DATA_TERMS):
        risk_flags.append("dati_personali")
        applied_rules.append("REGOLA_DATI_PERSONALI")
    if _found(text, CONSENT_TERMS):
        risk_flags.append("consenso")
    if _found(text, IRREVERSIBLE_TERMS):
        risk_flags.append("irreversibile")
        applied_rules.append("REGOLA_IRREVERSIBILE")

    ai_classification = None
    decision_reason = ""

    if ext and prod:
        intent = "MISTO"
        decision_reason = "Richiesta di produzione + azione esterna: bozza consentita, invio soggetto ad approvazione."
    elif ext and not prod:
        intent = "AZIONE_ESTERNA"
        decision_reason = "Azione esterna richiesta esplicitamente."
    elif prod and not ext:
        intent = "PRODUZIONE"
        decision_reason = "Solo produzione di contenuto: nessuna azione esterna."
    else:
        # Ambiguous: AI would interpret. Simulated stub (no real call in milestone 1).
        intent = "AMBIGUO"
        ai_classification = {
            "mode": "SIMULAZIONE",
            "suggested": "PRODUZIONE",
            "note": "Classificazione AI simulata: in dubbio si produce solo una bozza prudente, nessun invio.",
        }
        applied_rules.append("AMBIGUITA: AI puo aumentare la cautela, mai aggirare una regola")
        # Sensitive ambiguity => block/ask; non-sensitive => prudent draft (PRODUZIONE).
        sensitive = bool(set(risk_flags) & {"invio", "spesa", "dati_personali", "consenso", "irreversibile"})
        if sensitive:
            decision_reason = "Ambiguità sensibile: richiedere chiarimento, nessuna azione esterna."
        else:
            intent = "PRODUZIONE"
            decision_reason = "Ambiguità non sensibile: prodotta bozza prudente senza azione esterna."

    return {
        "intent_type": intent,
        "intent_reason": decision_reason,
        "risk_flags": sorted(set(risk_flags)),
        "applied_rules": applied_rules,
        "ai_classification": ai_classification,
        "requires_external_action": intent in ("AZIONE_ESTERNA", "MISTO"),
        "requires_clarification": intent == "AMBIGUO",
    }
