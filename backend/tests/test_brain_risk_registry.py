"""Brain — test per risk_registry.py (CEO Agent 100% reale, blocco 10): un
rischio proposto puo' SOLO aggiungere cautela, mai rimuoverla. Un BLOCK di
base non e' mai declassato dalla severita'; una severita' ALTA puo' innalzare
un'azione non bloccante fino ad APPROVAL (mai fino a BLOCK); una severita'
BASSA puo' derubricare un'APPROVAL a REVIEW_TASK (mai fino a NONE)."""
import pytest

from app.brain.risk_registry import (
    AZIONE_APPROVAL,
    AZIONE_BLOCK,
    AZIONE_CLARIFICATION,
    AZIONE_NONE,
    AZIONE_REVIEW_TASK,
    azione_piu_severa,
    resolve_risk_action,
)


@pytest.mark.parametrize("categoria,severita_qualunque", [
    ("invio", "BASSA"), ("invio", "ALTA"), ("azione_esterna_non_autorizzata", "BASSA"),
    ("irreversibile", "BASSA"), ("irreversibile", "ALTA"),
])
def test_categorie_bloccanti_mai_declassate(categoria, severita_qualunque):
    d = resolve_risk_action(categoria, severita_qualunque)
    assert d.azione == AZIONE_BLOCK


def test_spesa_severita_media_e_approval():
    d = resolve_risk_action("spesa", "MEDIA")
    assert d.azione == AZIONE_APPROVAL


def test_spesa_severita_bassa_derubricata_a_review_task():
    d = resolve_risk_action("spesa", "BASSA")
    assert d.azione == AZIONE_REVIEW_TASK


def test_claim_non_supportato_severita_alta_sale_ad_approval():
    d = resolve_risk_action("claim_non_supportato", "ALTA")
    assert d.azione == AZIONE_APPROVAL


def test_consenso_severita_alta_sale_ad_approval_mai_a_block():
    d = resolve_risk_action("consenso", "ALTA")
    assert d.azione == AZIONE_APPROVAL  # mai BLOCK: solo le categorie esplicitamente bloccanti lo producono


def test_categoria_sconosciuta_default_review_task():
    d = resolve_risk_action("categoria-mai-vista-prima", "MEDIA")
    assert d.azione == AZIONE_REVIEW_TASK


def test_severita_assente_o_non_valida_normalizzata_a_media():
    d1 = resolve_risk_action("spesa", "")
    d2 = resolve_risk_action("spesa", "valore-inventato")
    assert d1.severita == "MEDIA"
    assert d2.severita == "MEDIA"


def test_normalizzazione_categoria_case_insensitive_e_spazi():
    d = resolve_risk_action("Dati Personali", "MEDIA")
    assert d.categoria == "dati_personali"
    assert d.azione == AZIONE_APPROVAL


def test_azione_piu_severa_ordine_totale():
    ordine = [AZIONE_NONE, AZIONE_REVIEW_TASK, AZIONE_CLARIFICATION, AZIONE_APPROVAL, AZIONE_BLOCK]
    for i in range(len(ordine) - 1):
        assert azione_piu_severa(ordine[i], ordine[i + 1]) == ordine[i + 1]
        assert azione_piu_severa(ordine[i + 1], ordine[i]) == ordine[i + 1]
    assert azione_piu_severa(AZIONE_BLOCK, AZIONE_NONE) == AZIONE_BLOCK
