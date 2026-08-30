"""Brain — test unitari puri (nessun DB, nessuna chiamata reale).
Copre context/classifier/capability_selector/producers/guard/gateway in isolamento,
prima dell'integrazione con m2/engine.py (vedi test_brain_focaccine.py per il
caso di accettazione end-to-end, che richiede MongoDB)."""
import pytest

from app.brain import capability_selector as CAP
from app.brain import context as CTX
from app.brain import classifier as CLS
from app.brain import gateway as GW
from app.brain import guard as G
from app.brain import producers as P

FOCACCINE_GOAL = (
    "Prepara una campagna social per pubblicizzare le focaccine artigianali del "
    "Bakery & Coffee di Merate. Crea una strategia locale, un piano editoriale e "
    "tre post per Instagram e Facebook rivolti alle famiglie e ai lavoratori della "
    "zona. Usa dati simulati, non contattare clienti e non pubblicare nulla."
)


# ---------------- context.py ----------------
def test_context_estrae_entita_focaccine():
    ctx = CTX.extract_goal_context(FOCACCINE_GOAL)
    assert ctx.azienda == "Bakery & Coffee"
    assert ctx.localita == "Merate"
    assert ctx.prodotto and "focaccine" in ctx.prodotto.lower()
    assert "Instagram" in ctx.canali and "Facebook" in ctx.canali
    assert ctx.pubblico and "famigli" in ctx.pubblico.lower() and "lavorator" in ctx.pubblico.lower()
    assert ctx.missing_critical == []
    assert ctx.questions == []
    assert any("dati simulati" in v for v in ctx.vincoli)
    assert any("contattare" in v for v in ctx.vincoli)
    assert any("pubblicare" in v for v in ctx.vincoli)


def test_context_segnala_campi_indispensabili_mancanti():
    ctx = CTX.extract_goal_context("Fai qualcosa di utile per me")
    assert set(ctx.missing_critical) == {"azienda", "prodotto"}
    assert len(ctx.questions) == 2


# ---------------- classifier.py ----------------
def test_triage_focaccine_non_richiede_chiarimento():
    triage = CLS.triage_goal(FOCACCINE_GOAL)
    assert triage.requires_clarification is False
    assert triage.objective_type == "CAMPAGNA"
    assert triage.questions == []


def test_triage_obiettivo_ambiguo_richiede_chiarimento():
    triage = CLS.triage_goal("Fai qualcosa di utile per me")
    assert triage.requires_clarification is True
    assert triage.questions  # almeno le domande su azienda/prodotto


# ---------------- capability_selector.py ----------------
def test_capability_selector_riconosce_tre_post():
    ctx = CTX.extract_goal_context(FOCACCINE_GOAL)
    cap = CAP.select_capabilities(FOCACCINE_GOAL, ctx)
    assert cap["post_count"] == 3
    assert cap["canali"] == ["Instagram", "Facebook"]


def test_capability_selector_default_senza_numero_esplicito():
    ctx = CTX.extract_goal_context("Scrivi dei post social per il lancio")
    cap = CAP.select_capabilities("Scrivi dei post social per il lancio", ctx)
    assert cap["post_count"] == CAP.DEFAULT_POST_COUNT


# ---------------- gateway.py ----------------
def test_mock_gateway_riempie_template():
    gw = GW.get_default_gateway()
    assert isinstance(gw, GW.MockContentGateway)
    assert gw.fill("Ciao {nome}", nome="Merate") == "Ciao Merate"


def test_gateway_non_mock_solleva_errore(monkeypatch):
    monkeypatch.setenv("BRAIN_PROVIDER_GATEWAY", "openrouter")
    with pytest.raises(GW.ProviderGatewayError):
        GW.get_default_gateway()


# ---------------- producers.py + guard.py (senza validate_deliverable M2) ----------------
def _ctx_focaccine():
    return CTX.extract_goal_context(FOCACCINE_GOAL)


def test_produce_social_content_rispetta_numero_post_e_contesto():
    ctx = _ctx_focaccine()
    cap = CAP.select_capabilities(FOCACCINE_GOAL, ctx)
    gw = GW.get_default_gateway()
    content = P.produce_social_content(ctx, cap, gw)
    assert len(content["posts"]) == 3
    assert "Instagram" in content["platform"] and "Facebook" in content["platform"]
    for post in content["posts"]:
        blob = (post["hook"] + post["body"]).lower()
        assert "bakery & coffee" in blob or "bakery" in blob
        assert "merate" in blob


def test_produce_marketing_strategy_menziona_contesto():
    ctx = _ctx_focaccine()
    cap = CAP.select_capabilities(FOCACCINE_GOAL, ctx)
    gw = GW.get_default_gateway()
    content = P.produce_marketing_strategy(ctx, cap, gw)
    assert len(content["target_segments"]) >= 2
    testo = (content["executive_summary"] + content["value_proposition"]).lower()
    assert "bakery & coffee" in testo
    assert "focaccine" in testo


def test_guard_context_coherence_rifiuta_contenuto_generico():
    ctx = _ctx_focaccine()
    contenuto_generico = {"title": "Strategia B2B generica", "note": "Nessun riferimento al cliente reale."}
    errori = G.check_context_coherence(contenuto_generico, ctx)
    assert any("azienda" in e for e in errori)
    assert any("prodotto" in e for e in errori)


def test_guard_context_coherence_accetta_contenuto_brain():
    ctx = _ctx_focaccine()
    cap = CAP.select_capabilities(FOCACCINE_GOAL, ctx)
    gw = GW.get_default_gateway()
    content = P.produce_marketing_strategy(ctx, cap, gw)
    assert G.check_context_coherence(content, ctx) == []


def test_guard_forbidden_domains_blocca_contenuto_pensionistico():
    errori = G.check_forbidden_domains({"testo": "Report sulla pensione INPS e sul TFR maturato"})
    assert errori
    assert G.check_forbidden_domains({"testo": "Piano editoriale per il forno locale"}) == []
