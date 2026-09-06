"""Sales Agent — test diretti di strategy.py (nessun Mongo, nessuna rete):
analisi del lead e macchina a stati delle risposte del prospect."""
import pytest

from app.domains.sales.strategy import analyze_lead, decide_next_action


def test_analyze_lead_sceglie_email_come_canale_se_disponibile():
    lead = {"email": {"value": "info@acme.it"}, "telefono": {"value": "0212345678"}, "score": 60, "score_components": []}
    analisi = analyze_lead(lead)
    assert analisi["canale"] == "email"


def test_analyze_lead_usa_telefono_se_email_assente():
    lead = {"telefono": {"value": "0212345678"}, "score": 60, "score_components": []}
    analisi = analyze_lead(lead)
    assert analisi["canale"] == "telefono"


def test_analyze_lead_nessun_canale_se_entrambi_assenti():
    lead = {"score": 60, "score_components": []}
    analisi = analyze_lead(lead)
    assert analisi["canale"] is None


def test_analyze_lead_stima_interesse_dipende_dal_punteggio():
    alto = analyze_lead({"score": 80, "score_components": []})
    medio = analyze_lead({"score": 55, "score_components": []})
    basso = analyze_lead({"score": 20, "score_components": []})
    assert alto["stima_interesse"] == "ALTA"
    assert medio["stima_interesse"] == "MEDIA"
    assert basso["stima_interesse"] == "BASSA"


def test_analyze_lead_pain_point_riflette_componenti_scoring_positivi():
    lead = {
        "score": 70, "score_components": [
            {"nome": "settore", "punti": 20.0, "motivo": "Settore 'software' coerente con l'ICP."},
            {"nome": "localita", "punti": 0.0, "motivo": "Localita' non coerente."},
        ],
    }
    analisi = analyze_lead(lead)
    assert "software" in analisi["pain_point"]


def test_decide_next_action_stage_terminale_non_transiziona_mai():
    for stage in ("VINTO", "PERSO"):
        esito = decide_next_action(stage=stage, response_type="POSITIVA")
        assert esito["nuovo_stage"] == stage
        assert esito["next_best_action"] == "NESSUNA_AZIONE"


def test_decide_next_action_nessuna_risposta_ancora_nessuna_transizione():
    esito = decide_next_action(stage="CONTATTATO", response_type=None)
    assert esito["nuovo_stage"] == "CONTATTATO"
    assert esito["richiede_escalation"] is False


def test_decide_next_action_tipo_risposta_sconosciuto_solleva_errore():
    with pytest.raises(ValueError):
        decide_next_action(stage="CONTATTATO", response_type="TIPO-INESISTENTE")


@pytest.mark.parametrize("stage", ["CONTATTATO", "IN_RELAZIONE", "FOLLOW_UP"])
def test_decide_next_action_positiva_porta_a_richiesta_appuntamento_o_relazione(stage):
    esito = decide_next_action(stage=stage, response_type="POSITIVA")
    assert esito["nuovo_stage"] in ("IN_RELAZIONE", "RICHIESTA_APPUNTAMENTO")
    assert esito["richiede_escalation"] is False


@pytest.mark.parametrize("stage", ["CONTATTATO", "IN_RELAZIONE", "FOLLOW_UP"])
def test_decide_next_action_non_interessato_e_negativa_chiudono_a_perso(stage):
    for risposta in ("NON_INTERESSATO", "NEGATIVA"):
        esito = decide_next_action(stage=stage, response_type=risposta)
        assert esito["nuovo_stage"] == "PERSO"


def test_decide_next_action_obiezione_prezzo_resta_in_relazione_con_azione_dedicata():
    esito = decide_next_action(stage="CONTATTATO", response_type="OBIEZIONE_PREZZO")
    assert esito["nuovo_stage"] == "IN_RELAZIONE"
    assert esito["next_best_action"] == "GESTISCI_OBIEZIONE_PREZZO"


def test_decide_next_action_escalation_segnala_sempre_richiede_escalation():
    esito = decide_next_action(stage="FOLLOW_UP", response_type="ESCALATION")
    assert esito["richiede_escalation"] is True


def test_decide_next_action_nessuna_regola_esplicita_ricade_in_escalation_umana():
    # Una risposta ricevuta prima ancora di un primo contatto (stage QUALIFICATO):
    # nessuna regola definita, mai una transizione inventata.
    esito = decide_next_action(stage="QUALIFICATO", response_type="POSITIVA")
    assert esito["nuovo_stage"] == "QUALIFICATO"
    assert esito["next_best_action"] == "ESCALATION_UMANA"
    assert esito["richiede_escalation"] is True
