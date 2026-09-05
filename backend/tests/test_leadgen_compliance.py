"""Lead Generation — test del gate compliance deterministico. Nessun esito
qui deve mai essere aggirabile: uno stato DO_NOT_CONTACT/BLOCKED non deve
mai risultare declassato da 'piu_severo' con un esito piu' permissivo."""
import pytest

from app.domains.leadgen.compliance import evaluate_compliance, piu_severo


def _rec(**campi):
    r = {}
    for k, v in campi.items():
        r[k] = {"value": v, "original": v, "method": "ESTRATTO"}
    return r


def test_azienda_senza_persona_e_ready():
    r = _rec(ragione_sociale="Acme Srl", email="info@acme.it")
    d = evaluate_compliance(r, is_person=False)
    assert d.status == "READY"


def test_do_not_contact_prevale_su_tutto():
    r = _rec(stato_crm="DO_NOT_CONTACT", nome="Mario")
    d = evaluate_compliance(r, is_person=True)
    assert d.status == "DO_NOT_CONTACT"


def test_consenso_negato_e_do_not_contact():
    r = _rec(consenso="opt-out")
    d = evaluate_compliance(r, is_person=True)
    assert d.status == "DO_NOT_CONTACT"


def test_categoria_particolare_rilevata_blocca_anche_azienda():
    r = _rec(ragione_sociale="Acme", note="Il contatto ha problemi di salute")
    d = evaluate_compliance(r, is_person=False)
    assert d.status == "BLOCKED"


def test_persona_senza_fonte_bloccata():
    r = _rec(nome="Mario", consenso="dichiarato")
    d = evaluate_compliance(r, is_person=True)
    assert d.status == "BLOCKED"
    assert "provenienza" in d.motivi[0].lower()


def test_persona_senza_consenso_needs_clarification():
    r = _rec(nome="Mario", fonte="file caricato dall'utente")
    d = evaluate_compliance(r, is_person=True)
    assert d.status == "NEEDS_CLARIFICATION"


def test_email_inferita_richiede_approvazione():
    r = _rec(nome="Mario", fonte="file", consenso="dichiarato")
    r["email"] = {"value": "mario.rossi@acme.it", "original": "", "method": "INFERITO"}
    d = evaluate_compliance(r, is_person=True)
    assert d.status == "APPROVAL_REQUIRED"


def test_persona_completa_e_ready():
    r = _rec(nome="Mario", fonte="LinkedIn pubblico", consenso="dichiarato", email="mario@acme.it")
    d = evaluate_compliance(r, is_person=True)
    assert d.status == "READY"


@pytest.mark.parametrize("a,b,atteso", [
    ("READY", "BLOCKED", "BLOCKED"),
    ("BLOCKED", "READY", "BLOCKED"),
    ("DO_NOT_CONTACT", "READY", "DO_NOT_CONTACT"),
    ("NEEDS_CLARIFICATION", "REVIEW_REQUIRED", "NEEDS_CLARIFICATION"),
])
def test_piu_severo_non_declassa_mai_un_blocco(a, b, atteso):
    assert piu_severo(a, b) == atteso
