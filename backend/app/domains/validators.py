"""Deliverable validation: EMAIL minimum contract + placeholder policy + external prerequisites."""
import re

PLACEHOLDER_RE = re.compile(r"\[[^\]]+\]")
ALLOWED_PLACEHOLDERS = {"[nome]", "[azienda]", "[link appuntamento]", "[data]", "[firma]"}


def _nonempty(s) -> bool:
    return isinstance(s, str) and s.strip() != ""


def _placeholder_ratio(text: str) -> float:
    if not text:
        return 1.0
    stripped = PLACEHOLDER_RE.sub("", text)
    non_ph_chars = len(re.sub(r"\s", "", stripped))
    total_chars = len(re.sub(r"\s", "", text)) or 1
    return 1.0 - (non_ph_chars / total_chars)


def validate_email_deliverable(d: dict) -> dict:
    """Return {'status', 'warnings', 'errors'}. status in COMPLETATO/COMPLETATO_CON_AVVISI/BLOCCATO."""
    errors = []
    warnings = []

    oggetto = d.get("oggetto") or d.get("hook") or ""
    contenuto = d.get("contenuto_completo") or ""
    cta = d.get("cta") or ""
    proposta = d.get("proposta") or ""

    # Minimum contract: non-empty strings (not null, not whitespace).
    if not _nonempty(oggetto):
        errors.append("Oggetto/hook mancante o vuoto")
    if not _nonempty(contenuto):
        errors.append("Contenuto completo mancante o vuoto")
    if not _nonempty(cta):
        errors.append("CTA mancante o vuota")

    # Substantial text: key fields must not be predominantly placeholders.
    for label, val in (("Oggetto", oggetto), ("Proposta", proposta), ("CTA", cta), ("Corpo", contenuto)):
        if _nonempty(val) and _placeholder_ratio(val) > 0.6:
            errors.append(f"{label} composto prevalentemente da placeholder")

    if errors:
        return {"status": "BLOCCATO", "warnings": warnings, "errors": errors}

    # Placeholders present in variable fields -> completed with warnings.
    all_ph = PLACEHOLDER_RE.findall(f"{oggetto} {contenuto} {cta}")
    unknown = [p for p in all_ph if p.lower() not in ALLOWED_PLACEHOLDERS]
    if unknown:
        warnings.append(f"Placeholder non standard rilevati: {', '.join(sorted(set(unknown)))}")
    if all_ph:
        warnings.append("Presenti placeholder per campi variabili da personalizzare prima dell'uso.")
        return {"status": "COMPLETATO_CON_AVVISI", "warnings": warnings, "errors": []}

    return {"status": "COMPLETATO", "warnings": warnings, "errors": []}


def check_external_prerequisites(*, has_recipients: bool, has_consent: bool,
                                 integration_available: bool, has_approval: bool,
                                 budget_ok: bool) -> dict:
    """Return missing prerequisites for an external action (e.g. sending email)."""
    missing = []
    if not has_recipients:
        missing.append("destinatari")
    if not has_consent:
        missing.append("consenso / base giuridica")
    if not integration_available:
        missing.append("integrazione di invio")
    if not has_approval:
        missing.append("approvazione umana dell'azione esterna")
    if not budget_ok:
        missing.append("budget sufficiente")
    return {"ok": len(missing) == 0, "missing": missing}
