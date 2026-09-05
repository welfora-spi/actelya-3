"""Lead Generation — test dello scoring esplicabile. Un opt-out o una regola
di compliance deve SEMPRE prevalere sul punteggio commerciale, qualunque
sia il punteggio ottenuto."""
from app.domains.leadgen.scoring import score_record


def _rec(**campi):
    r = {}
    for k, v in campi.items():
        r[k] = {"value": v, "original": v, "method": "ESTRATTO"}
    return r


ICP_BASE = {
    "settori_inclusi": ["software"], "settori_esclusi": ["gioco d'azzardo"],
    "localita": ["milano"], "dimensione_min": 10, "dimensione_max": 200,
    "ruoli_decisionali": ["marketing", "sales"],
}


def test_record_coerente_con_icp_qualificato():
    r = _rec(ragione_sociale="Acme Srl", email="info@acme.it", telefono="0212345",
             sito="acme.it", settore="software", citta="Milano", dipendenti="50")
    esito = score_record(r, ICP_BASE, is_person=False, compliance_status="READY")
    assert esito.qualification_status == "QUALIFIED"
    assert esito.score > 50
    assert all(c.motivo for c in esito.componenti)  # ogni componente e' motivato


def test_settore_escluso_esclude_sempre_anche_con_dati_ottimi():
    r = _rec(ragione_sociale="Casino Spa", email="info@casino.it", telefono="0212345",
             sito="casino.it", settore="gioco d'azzardo", citta="Milano", dipendenti="50")
    esito = score_record(r, ICP_BASE, is_person=False, compliance_status="READY")
    assert esito.qualification_status == "EXCLUDED"
    assert "settore_escluso" in esito.regole_applicate


def test_compliance_do_not_contact_prevale_su_punteggio_alto():
    r = _rec(ragione_sociale="Acme Srl", email="info@acme.it", telefono="0212345",
             sito="acme.it", settore="software", citta="Milano", dipendenti="50")
    esito = score_record(r, ICP_BASE, is_person=True, compliance_status="DO_NOT_CONTACT")
    assert esito.qualification_status == "DO_NOT_CONTACT"


def test_compliance_blocked_esclude_anche_con_punteggio_alto():
    r = _rec(ragione_sociale="Acme Srl", settore="software", citta="Milano", dipendenti="50")
    esito = score_record(r, ICP_BASE, is_person=True, compliance_status="BLOCKED")
    assert esito.qualification_status == "EXCLUDED"


def test_cliente_esistente_escluso_quando_richiesto():
    r = _rec(ragione_sociale="Acme Srl", settore="software", citta="Milano",
             dipendenti="50", cliente_esistente="true")
    esito = score_record(r, ICP_BASE, is_person=False, compliance_status="READY",
                         exclude_existing_customers=True)
    assert esito.qualification_status == "EXCLUDED"
    assert "cliente_esistente_escluso" in esito.regole_applicate


def test_cliente_esistente_non_escluso_se_flag_disattivato():
    r = _rec(ragione_sociale="Acme Srl", email="info@acme.it", telefono="0212345",
             sito="acme.it", settore="software", citta="Milano", dipendenti="50", cliente_esistente="true")
    esito = score_record(r, ICP_BASE, is_person=False, compliance_status="READY",
                         exclude_existing_customers=False)
    assert esito.qualification_status == "QUALIFIED"


def test_dati_insufficienti_e_incomplete():
    r = _rec(ragione_sociale="Acme Srl")
    esito = score_record(r, ICP_BASE, is_person=False, compliance_status="READY")
    assert esito.qualification_status in ("INCOMPLETE", "REVIEW_REQUIRED")
    assert len(esito.dati_mancanti) >= 2


def test_compliance_needs_clarification_forza_review():
    r = _rec(ragione_sociale="Acme Srl", email="info@acme.it", telefono="0212345",
             sito="acme.it", settore="software", citta="Milano", dipendenti="50")
    esito = score_record(r, ICP_BASE, is_person=True, compliance_status="NEEDS_CLARIFICATION")
    assert esito.qualification_status == "REVIEW_REQUIRED"


def test_ruolo_decisionale_coerente_aumenta_punteggio_persona():
    base = _rec(ragione_sociale="Acme Srl", settore="software", citta="Milano", dipendenti="50")
    con_ruolo = dict(base, ruolo={"value": "Head of Marketing", "original": "Head of Marketing", "method": "ESTRATTO"})
    senza_ruolo = dict(base, ruolo={"value": "Magazziniere", "original": "Magazziniere", "method": "ESTRATTO"})
    esito_con = score_record(con_ruolo, ICP_BASE, is_person=True, compliance_status="READY")
    esito_senza = score_record(senza_ruolo, ICP_BASE, is_person=True, compliance_status="READY")
    assert esito_con.score > esito_senza.score


def test_confidence_riflette_metodo_di_provenienza():
    r_verificato = {"ragione_sociale": {"value": "Acme", "original": "Acme", "method": "VERIFICATO"}}
    r_inferito = {"ragione_sociale": {"value": "Acme", "original": "Acme", "method": "INFERITO"}}
    e1 = score_record(r_verificato, ICP_BASE, is_person=False, compliance_status="READY")
    e2 = score_record(r_inferito, ICP_BASE, is_person=False, compliance_status="READY")
    assert e1.confidence > e2.confidence
