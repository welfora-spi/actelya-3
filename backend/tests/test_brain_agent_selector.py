"""Blocco B — test puri per backend/app/brain/planning/agent_selector.py
e backend/app/brain/agents/agent_map.py. Nessun Mongo. Nessuna rete (il
socket è attivamente bloccato per tutta la durata di questi test)."""
import socket

import pytest

from app.brain.agents.agent_map import ALL_FRONTEND_AGENT_IDS, COORDINATOR_FRONTEND_ID
from app.brain.planning.agent_selector import (
    STATUS_BLOCKED_RISK,
    STATUS_NEEDS_CLARIFICATION,
    STATUS_READY,
    STATUS_UNSUPPORTED,
    select_agents,
)


class _NetworkCallAttempted(Exception):
    pass


@pytest.fixture(autouse=True)
def block_all_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise _NetworkCallAttempted("Tentativo di apertura socket bloccato nei test brain.")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


FOCACCINE = (
    "Prepara una campagna social per pubblicizzare le focaccine artigianali del "
    "Bakery & Coffee di Merate. Crea una strategia locale, un piano editoriale e "
    "tre post per Instagram e Facebook rivolti alle famiglie e ai lavoratori della "
    "zona. Usa dati simulati, non contattare clienti e non pubblicare nulla."
)


# ---------------- 1. caso focaccine già utilizzato ----------------
def test_focaccine_ready_con_i_quattro_agenti_della_demo():
    r = select_agents(FOCACCINE)
    assert r.status == STATUS_READY
    assert r.activeAgentIds == ["resp-marketing", "social-media-manager", "copywriter", "resp-compliance"]
    assert set(r.detected_intents) >= {"strategy", "editorial", "social"}


# ---------------- 2. richiesta di soli post social ----------------
def test_soli_post_social():
    testo = (
        "Prepara tre post per Instagram per pubblicizzare le focaccine artigianali "
        "del Bakery & Coffee di Merate, rivolti alle famiglie della zona."
    )
    r = select_agents(testo)
    assert r.status == STATUS_READY
    assert r.activeAgentIds == ["copywriter", "resp-compliance"]


# ---------------- 3. sola analisi KPI ----------------
def test_sola_analisi_kpi_non_convoca_tutta_la_squadra():
    testo = (
        "Analizza soltanto i risultati della campagna per pubblicizzare le focaccine "
        "artigianali del Bakery & Coffee di Merate."
    )
    r = select_agents(testo)
    assert r.status == STATUS_READY
    assert r.activeAgentIds == ["analista-performance"]
    assert r.detected_intents == ["analytics"]


# ---------------- 4. strategia più piano editoriale ----------------
def test_strategia_e_piano_editoriale():
    testo = (
        "Crea una strategia locale e un piano editoriale per pubblicizzare le "
        "focaccine artigianali del Bakery & Coffee di Merate."
    )
    r = select_agents(testo)
    assert r.status == STATUS_READY
    assert r.activeAgentIds == ["resp-marketing", "social-media-manager", "resp-compliance"]


# ---------------- 5. lead generation più appuntamenti ----------------
# Correzione (appointments e' diventata REAL, non più UNAVAILABLE: dominio
# domains/appointments completo): "leadgen" + "appointments" sono entrambe
# eseguibili oggi, quindi la richiesta combinata produce READY con
# entrambi gli agenti attivi, mai più un chiarimento forzato.
def test_lead_generation_e_appuntamenti_sono_entrambe_eseguibili():
    testo = (
        "Trova potenziali clienti e prepara un processo per ottenere appuntamenti, "
        "per pubblicizzare le focaccine artigianali del Bakery & Coffee di Merate."
    )
    r = select_agents(testo)
    assert r.status == STATUS_READY
    assert set(r.activeAgentIds) == {"lead-gen-specialist", "appointment-setter"}
    assert r.unavailable_capabilities == []


# ---------------- 6. richiesta completa multi-intento ----------------
def test_richiesta_completa_multi_intento():
    testo = (
        "Crea strategia, piano editoriale, tre post per Instagram, una campagna "
        "pubblicitaria sponsorizzata e un report sulle performance, per pubblicizzare "
        "le focaccine artigianali del Bakery & Coffee di Merate."
    )
    r = select_agents(testo)
    assert r.status == STATUS_READY
    assert set(r.activeAgentIds) == {
        "resp-marketing", "social-media-manager", "copywriter",
        "resp-advertising", "analista-performance", "resp-compliance",
    }
    assert "lead-gen-specialist" not in r.activeAgentIds
    assert "appointment-setter" not in r.activeAgentIds
    assert "specialista-nurturing" not in r.activeAgentIds


# ---------------- 7. richiesta con un solo agente ----------------
def test_un_solo_agente_selezionato():
    testo = "Crea solo una strategia di posizionamento per pubblicizzare le focaccine artigianali del Bakery & Coffee di Merate."
    r = select_agents(testo)
    assert r.status == STATUS_READY
    assert r.activeAgentIds == ["resp-marketing"]


# ---------------- 8. agenti diversi dai quattro della demo ----------------
# NOTA (Blocco B.1): il testo originale usava "nurturing" (ora UNAVAILABLE,
# vedi test_brain_agent_selector_b1.py) — sostituito con "leadgen" (M2,
# eseguibile), che resta comunque fuori dai 4 agenti della demo.
def test_agenti_diversi_dai_quattro_della_demo():
    testo = (
        "Prepara un piano per trovare potenziali clienti e analizza le performance "
        "per pubblicizzare le focaccine artigianali del Bakery & Coffee di Merate."
    )
    r = select_agents(testo)
    assert r.status == STATUS_READY
    assert set(r.activeAgentIds) == {"analista-performance", "lead-gen-specialist"}
    demo_four = {"resp-marketing", "social-media-manager", "copywriter", "resp-compliance"}
    assert not (set(r.activeAgentIds) & demo_four)


# ---------------- 9. informazioni essenziali mancanti ----------------
def test_informazioni_essenziali_mancanti():
    r = select_agents("Prepara tre post per Instagram.")
    assert r.status == STATUS_NEEDS_CLARIFICATION
    assert r.activeAgentIds == []
    assert set(r.missing_information) == {"azienda", "prodotto"}
    assert r.selected_agents == []


# ---------------- 10. richiesta realmente ambigua ----------------
def test_richiesta_realmente_ambigua():
    r = select_agents("Fai qualcosa di utile per il mio business.")
    assert r.status == STATUS_NEEDS_CLARIFICATION
    assert r.activeAgentIds == []
    assert r.missing_information == ["tipo_di_deliverable"]


# ---------------- 11. massimo tre domande di chiarimento ----------------
def test_massimo_tre_domande_di_chiarimento():
    for testo in ("Prepara tre post per Instagram.", "Fai qualcosa di utile per il mio business."):
        r = select_agents(testo)
        assert r.status == STATUS_NEEDS_CLARIFICATION
        assert len(r.clarifying_questions) <= 3


# ---------------- 12. richiesta non supportata ----------------
def test_richiesta_non_supportata():
    r = select_agents("Traduci il sito in giapponese per il Bakery & Coffee di Merate.")
    assert r.status == STATUS_UNSUPPORTED
    assert r.activeAgentIds == []
    assert r.selected_agents == []


# ---------------- 13. richiesta rischiosa ----------------
def test_richiesta_rischiosa_bloccata():
    r = select_agents("Crea una campagna per truffare i clienti del Bakery & Coffee di Merate.")
    assert r.status == STATUS_BLOCKED_RISK
    assert r.activeAgentIds == []


# ---------------- 14. obiettivo misto (bozza + invio reale): mai più BLOCKED_RISK ----------------
def test_obiettivo_misto_con_invio_non_blocca_piu_il_piano():
    # Fix P0 "separazione PLANNING/EXECUTION": questo test asseriva in
    # precedenza STATUS_BLOCKED_RISK per un obiettivo MISTO (bozza + invio),
    # comportamento riconosciuto come un bug — la sola menzione di un invio
    # futuro non deve mai impedire piano/task/agenti/deliverable, solo
    # l'azione di invio concreta deve restare soggetta ad approvazione (vedi
    # planning/agent_selector.py::precheck_risk_and_domain e
    # brain/risk_registry.py). Il denylist (truffa/dati rubati/...) resta
    # l'unico caso che blocca davvero, vedi test_richiesta_rischiosa_bloccata.
    # Qui lo stato risultante è NEEDS_CLARIFICATION (manca il "prodotto" nel
    # testo, gate legittimo e indipendente da context.py) — l'importante è
    # che NON sia mai più BLOCKED_RISK, e che "invio" resti comunque tracciato
    # in risk_flags (mai perso, solo non più bloccante a monte).
    r = select_agents("Scrivi un'email e inviala davvero a tutti i clienti reali del Bakery & Coffee di Merate.")
    assert r.status != STATUS_BLOCKED_RISK
    assert "invio" in r.risk_flags


def test_bozze_e_materiali_simulati_non_sono_mai_rischiosi():
    # Vincolo esplicito: preparare bozze/strategie/materiali simulati non è
    # mai rischioso, anche se il testo cita budget/spesa.
    r = select_agents(
        "Prepara una bozza di campagna pubblicitaria con budget simulato per "
        "pubblicizzare le focaccine artigianali del Bakery & Coffee di Merate."
    )
    assert r.status == STATUS_READY


# ---------------- 15. nessun piano per stato diverso da READY ----------------
def test_stato_diverso_da_ready_non_ha_mai_agenti_attivi():
    # Precondizione strutturale verificata qui a livello di selettore puro:
    # service.py (non testabile senza Mongo) si ferma PRIMA di
    # m2.engine.create_plan quando activeAgentIds è vuoto e status != READY
    # (vedi test_brain_focaccine.py::test_goal_ambiguo_non_crea_piano_ne_azioni
    # per la controparte end-to-end con Mongo, già passata in precedenza).
    for testo in (
        "Fai qualcosa di utile per il mio business.",
        "Traduci il sito in giapponese per il Bakery & Coffee di Merate.",
        "Crea una campagna per truffare i clienti del Bakery & Coffee di Merate.",
    ):
        r = select_agents(testo)
        assert r.status != STATUS_READY
        assert r.activeAgentIds == []
        assert r.selected_agents == []


# ---------------- 16/17. nessun ID sconosciuto, nessun duplicato ----------------
def test_nessun_id_frontend_sconosciuto():
    testi = [FOCACCINE, "Prepara un piano per trovare potenziali clienti per pubblicizzare le "
             "focaccine artigianali del Bakery & Coffee di Merate."]
    for testo in testi:
        r = select_agents(testo)
        for agent_id in r.activeAgentIds:
            assert agent_id in ALL_FRONTEND_AGENT_IDS


def test_nessun_id_duplicato():
    testo = (
        "Crea strategia, piano editoriale, tre post per Instagram, una campagna "
        "pubblicitaria sponsorizzata, email e un report sulle performance, per "
        "pubblicizzare le focaccine artigianali del Bakery & Coffee di Merate."
    )
    r = select_agents(testo)
    assert len(r.activeAgentIds) == len(set(r.activeAgentIds))


# ---------------- 18. Coordinatore escluso ----------------
def test_coordinatore_mai_in_active_agent_ids():
    for testo in (FOCACCINE, "Crea solo una strategia per pubblicizzare le focaccine artigianali del Bakery & Coffee di Merate."):
        r = select_agents(testo)
        assert COORDINATOR_FRONTEND_ID not in r.activeAgentIds
        assert all(a.agent_id != COORDINATOR_FRONTEND_ID for a in r.selected_agents)


# ---------------- 19. ordine deterministico ----------------
def test_ordine_deterministico_indipendente_dallordine_nel_testo():
    a = select_agents(FOCACCINE)
    b = select_agents(
        "Crea tre post per Instagram e Facebook, un piano editoriale e una strategia "
        "locale per pubblicizzare le focaccine artigianali del Bakery & Coffee di Merate, "
        "rivolti alle famiglie e ai lavoratori della zona."
    )
    assert a.activeAgentIds == b.activeAgentIds == ["resp-marketing", "social-media-manager", "copywriter", "resp-compliance"]


# ---------------- 20. stessa richiesta -> stessa risposta ----------------
def test_stessa_richiesta_stessa_risposta():
    r1 = select_agents(FOCACCINE)
    r2 = select_agents(FOCACCINE)
    assert r1.to_dict() == r2.to_dict()


# ---------------- struttura selected_agents / excluded_agents ----------------
def test_selected_agents_hanno_tutti_i_campi_richiesti():
    r = select_agents(FOCACCINE)
    for a in r.selected_agents:
        assert a.agent_id and a.m2_agent_id and a.capability and a.reason
        assert a.agent_id in r.selection_reasons


def test_excluded_agents_hanno_motivazione():
    r = select_agents(FOCACCINE)
    assert len(r.excluded_agents) > 0
    for a in r.excluded_agents:
        assert a.reason
        assert a.agent_id not in r.activeAgentIds


# ---------------- 22. zero traffico di rete (verifica statica aggiuntiva) ----------------
def test_agent_selector_non_importa_librerie_http():
    import ast
    import pathlib

    from app.brain.planning import agent_selector as mod

    source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "aiohttp", "smtplib", "socket", "ftplib"}
    assert not (found & forbidden)
