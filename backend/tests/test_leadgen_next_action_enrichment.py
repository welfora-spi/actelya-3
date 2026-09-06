"""Lead Generation — test diretti di next_action.py (nessun Mongo) e di
enrichment.py::apply_enrichment_result (nessuna rete): decisione della
prossima azione, mapping capability astratte, rilevamento conflitti con
priorità di confidenza."""
from app.domains.leadgen.enrichment import apply_enrichment_result, rescore_after_enrichment
from app.domains.leadgen.next_action import (
    AZIONE_CONTINUA_ENRICHMENT,
    AZIONE_NURTURING,
    AZIONE_PRONTO_PER_SALES,
    AZIONE_SCARTA,
    decide_next_action,
)


def test_excluded_e_sempre_scartato_indipendentemente_dai_dati_mancanti():
    esito = decide_next_action(qualification_status="EXCLUDED", missing_data=["settore"], record={})
    assert esito["azione"] == AZIONE_SCARTA
    assert esito["capability_richieste"] == []


def test_do_not_contact_e_sempre_scartato():
    esito = decide_next_action(qualification_status="DO_NOT_CONTACT", missing_data=[], record={})
    assert esito["azione"] == AZIONE_SCARTA


def test_incomplete_con_capability_nota_continua_enrichment():
    esito = decide_next_action(qualification_status="INCOMPLETE", missing_data=["settore"], record={})
    assert esito["azione"] == AZIONE_CONTINUA_ENRICHMENT
    assert "COMPANY_ENRICHMENT" in esito["capability_richieste"]


def test_incomplete_senza_capability_nota_va_in_nurturing():
    # nessun campo mancante mappato a una capability: entrambi i canali di
    # contatto presenti (altrimenti scatterebbe comunque una richiesta di
    # arricchimento) e nessun campo scoring segnalato come mancante.
    esito = decide_next_action(qualification_status="INCOMPLETE", missing_data=[],
                               record={"email": {"value": "a@b.it"}, "telefono": {"value": "3331234567"}})
    assert esito["azione"] == AZIONE_NURTURING


def test_qualified_senza_contatto_continua_enrichment_prima_dellhandoff():
    esito = decide_next_action(qualification_status="QUALIFIED", missing_data=[], record={})
    assert esito["azione"] == AZIONE_CONTINUA_ENRICHMENT
    assert "EMAIL_DISCOVERY" in esito["capability_richieste"]


def test_qualified_con_email_e_pronto_per_sales():
    esito = decide_next_action(qualification_status="QUALIFIED", missing_data=[],
                               record={"email": {"value": "a@b.it"}})
    assert esito["azione"] == AZIONE_PRONTO_PER_SALES


def test_qualified_con_solo_telefono_basta_per_lhandoff():
    esito = decide_next_action(qualification_status="QUALIFIED", missing_data=[],
                               record={"telefono": {"value": "3331234567"}})
    assert esito["azione"] == AZIONE_PRONTO_PER_SALES


def test_stato_non_gestito_ricade_in_nurturing_per_prudenza():
    esito = decide_next_action(qualification_status="MERGED_INTO_ALTRO", missing_data=[], record={})
    assert esito["azione"] == AZIONE_NURTURING


# ==================== enrichment.py ====================
def test_apply_enrichment_result_riempie_campo_vuoto():
    record = {"email": {"value": None, "method": "MANCANTE"}}
    esito = apply_enrichment_result(record, result_fields={"email": "mario.rossi@acme.it"}, source_method="ESTRATTO")
    assert esito["record"]["email"]["value"] == "mario.rossi@acme.it"
    assert esito["conflitti"] == []


def test_apply_enrichment_result_non_declassa_un_dato_verificato():
    record = {"email": {"value": "verificata@acme.it", "method": "VERIFICATO"}}
    esito = apply_enrichment_result(record, result_fields={"email": "diversa@acme.it"}, source_method="ESTRATTO")
    assert esito["record"]["email"]["value"] == "verificata@acme.it"  # invariato
    assert len(esito["conflitti"]) == 1
    assert esito["conflitti"][0]["risoluzione"] == "scartato (priorità inferiore al dato già presente)"


def test_apply_enrichment_result_sostituisce_se_priorita_superiore():
    record = {"email": {"value": "vecchia@acme.it", "method": "INFERITO"}}
    esito = apply_enrichment_result(record, result_fields={"email": "nuova@acme.it"}, source_method="VERIFICATO")
    assert esito["record"]["email"]["value"] == "nuova@acme.it"
    assert esito["conflitti"][0]["risoluzione"] == "sostituito (priorità del nuovo dato superiore)"


def test_apply_enrichment_result_stessa_priorita_segnala_conflitto_non_risolto():
    record = {"email": {"value": "a@acme.it", "method": "ESTRATTO"}}
    esito = apply_enrichment_result(record, result_fields={"email": "b@acme.it"}, source_method="ESTRATTO")
    assert esito["record"]["email"]["value"] == "a@acme.it"  # mantenuto
    assert "non risolto" in esito["conflitti"][0]["risoluzione"]


def test_apply_enrichment_result_stesso_valore_non_e_un_conflitto():
    record = {"email": {"value": "a@acme.it", "method": "ESTRATTO"}}
    esito = apply_enrichment_result(record, result_fields={"email": "A@ACME.IT"}, source_method="ESTRATTO")
    assert esito["conflitti"] == []


def test_apply_enrichment_result_valore_non_normalizzabile_ignorato():
    record = {"email": {"value": None, "method": "MANCANTE"}}
    esito = apply_enrichment_result(record, result_fields={"email": "non-e-una-email"}, source_method="ESTRATTO")
    assert esito["record"]["email"]["value"] is None  # non sovrascritto con un valore invalido
    assert esito["conflitti"] == []


def test_rescore_after_enrichment_aggiorna_qualificazione():
    record = {
        "ragione_sociale": {"value": "Acme Srl", "method": "FORNITO"},
        "settore": {"value": "software", "method": "FORNITO"},
        "citta": {"value": "Milano", "method": "FORNITO"},
        "email": {"value": "info@acme.it", "method": "ESTRATTO"},
        "dominio": {"value": "acme.it", "method": "ESTRATTO"},
    }
    ricalcolo = rescore_after_enrichment(record, icp={}, is_person=False)
    assert ricalcolo["qualification_status"] in ("QUALIFIED", "REVIEW_REQUIRED")
    assert "next_action" in ricalcolo
    assert ricalcolo["next_action"]["azione"] in (AZIONE_PRONTO_PER_SALES, AZIONE_NURTURING, AZIONE_CONTINUA_ENRICHMENT)
