"""Content Creator — test diretti del motore di decisione e della
validazione strutturale (nessun Mongo, nessuna rete)."""
import pytest

from app.domains.content_creator import decision
from app.domains.content_creator.validation import validate_content


def test_decide_content_plan_tipo_esplicito_vince_sempre():
    piano = decision.decide_content_plan(channel="instagram", funnel_stage="BOFU", explicit_type="email")
    assert piano["content_types"] == ["email"]
    assert "richiesto esplicitamente" in piano["motivazione"]


def test_decide_content_plan_mapping_canale_quando_nessun_tipo_esplicito():
    piano = decision.decide_content_plan(channel="blog", funnel_stage="TOFU", explicit_type=None)
    assert piano["content_types"] == ["articolo_blog", "contenuto_seo"]
    assert "blog" in piano["motivazione"]


def test_decide_content_plan_canale_sconosciuto_usa_generico():
    piano = decision.decide_content_plan(channel="canale-inesistente", funnel_stage="MOFU", explicit_type=None)
    assert piano["content_types"] == ["contenuto_informativo"]


def test_decide_content_plan_tipo_esplicito_sconosciuto_solleva_errore():
    with pytest.raises(ValueError):
        decision.decide_content_plan(channel="instagram", funnel_stage="MOFU", explicit_type="tipo-inesistente")


def test_decide_content_plan_tono_dipende_dalla_fase_funnel():
    tofu = decision.decide_content_plan(channel="email", funnel_stage="TOFU", explicit_type=None)
    bofu = decision.decide_content_plan(channel="email", funnel_stage="BOFU", explicit_type=None)
    assert tofu["tono_suggerito"] != bofu["tono_suggerito"]


def test_validate_content_post_social_richiede_corpo_e_cta():
    esito = validate_content("post_social", {"titolo": "", "corpo": "", "cta": "", "hashtags": [], "varianti": []})
    assert esito["status"] == "BLOCCATO"
    assert any("corpo" in e for e in esito["errors"])
    assert any("cta" in e for e in esito["errors"])


def test_validate_content_post_social_completo_passa():
    contenuto = {
        "titolo": "", "corpo": "Scopri come Acme risolve il tuo problema quotidiano in pochi minuti.",
        "cta": "Scopri di più", "hashtags": ["#acme"], "varianti": ["Variante alternativa del corpo del post."],
    }
    esito = validate_content("post_social", contenuto)
    assert esito["status"] == "COMPLETATO"


def test_validate_content_headline_non_richiede_corpo():
    esito = validate_content("headline", {"titolo": "Risparmia tempo ogni giorno", "corpo": "", "cta": "", "hashtags": [], "varianti": []})
    assert esito["status"] == "COMPLETATO"


def test_validate_content_carosello_richiede_almeno_due_varianti():
    contenuto = {"titolo": "", "corpo": "Testo abbastanza lungo per il carosello testuale.", "cta": "", "hashtags": [], "varianti": ["solo una"]}
    esito = validate_content("carosello_testuale", contenuto)
    assert esito["status"] == "BLOCCATO"
    assert any("varianti" in e for e in esito["errors"])


def test_validate_content_rifiuta_testo_di_rifiuto_llm():
    contenuto = {"titolo": "", "corpo": "Mi dispiace, non posso generare questo contenuto.", "cta": "vai", "hashtags": [], "varianti": ["x" * 20]}
    esito = validate_content("post_social", contenuto)
    assert esito["status"] == "BLOCCATO"


def test_validate_content_non_dict_e_sempre_bloccato():
    esito = validate_content("post_social", None)
    assert esito["status"] == "BLOCCATO"


def test_validate_content_tipo_sconosciuto_usa_requisiti_di_default():
    esito = validate_content("tipo-inesistente", {"corpo": "Testo abbastanza lungo da superare il minimo di default."})
    assert esito["status"] == "COMPLETATO"
