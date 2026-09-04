"""Brain — test per llm_validator.py (CEO Agent 100% reale, blocchi 7/9/10):
ogni suggerimento della proposta LLM e' verificato contro i registry reali
(agent_map.py) PRIMA di essere usato — una capability/agente non presente
nella selezione deterministica viene sempre scartato, mai aggiunto al piano.
Budget: assente ma indispensabile -> chiarimento; valori in disaccordo ->
chiarimento; allocazioni oltre il totale -> normalizzate/ridotte, mai un
blocco silenzioso. Rischi: normalizzati e aggregati, mai applicati qui."""
from app.brain.llm_schema import CeoLLMProposal
from app.brain.llm_validator import estrai_budget_deterministico, validate_and_normalize
from app.brain.risk_registry import AZIONE_APPROVAL, AZIONE_BLOCK, AZIONE_NONE


# ---------------- estrai_budget_deterministico ----------------
def test_estrai_budget_vari_formati():
    assert estrai_budget_deterministico("Ho 2000 euro di budget") == 2000.0
    assert estrai_budget_deterministico("budget di €1.500") == 1500.0
    assert estrai_budget_deterministico("500€ disponibili") == 500.0
    assert estrai_budget_deterministico("nessun numero qui") is None
    assert estrai_budget_deterministico("") is None


# ---------------- percorso deterministico puro (proposta=None) ----------------
def test_nessuna_proposta_budget_da_regex():
    p = validate_and_normalize(None, goal_text="Ho 2000 euro di budget per una campagna ads",
                               detected_intents=["ads"])
    assert p.origine == "DETERMINISTICO"
    assert p.budget_totale == 2000.0
    assert p.budget_status == "OK"


def test_nessuna_proposta_ads_senza_budget_richiede_chiarimento():
    p = validate_and_normalize(None, goal_text="Lancia una campagna ads", detected_intents=["ads"])
    assert p.budget_status == "ASSENTE_INDISPENSABILE"
    assert p.richiede_chiarimento_budget is True


def test_nessuna_proposta_senza_ads_budget_non_applicabile():
    p = validate_and_normalize(None, goal_text="Scrivi un post per Instagram", detected_intents=["social"])
    assert p.budget_status == "NON_APPLICABILE"
    assert p.richiede_chiarimento_budget is False


# ---------------- capability/agenti: validate DIRETTAMENTE contro il registry reale ----------------
def test_capability_reale_ma_non_rilevata_da_keyword_viene_accettata():
    """Il cuore della correzione architetturale: 'leadgen' e' una capability
    reale e operativa (agent_map.py) che l'LLM puo' proporre anche quando
    NESSUNA parola chiave l'ha rilevata (detected_intents=['social'] soltanto,
    qui a rappresentare il fallback deterministico se il provider fallisse
    — MAI usato per filtrare l'LLM): deve entrare nel piano, non essere
    scartata solo perche' assente dal rilevamento a keyword."""
    proposta = CeoLLMProposal(
        intent="x", strategia_proposta="y",
        agenti_suggeriti=[{"capability": "social", "motivazione": "m"}, {"capability": "leadgen", "motivazione": "m2"}],
    )
    p = validate_and_normalize(proposta, goal_text="Voglio aumentare i clienti", detected_intents=["social"])
    assert set(p.capability_validate) == {"social", "leadgen"}
    assert p.capability_extra_scartate == []
    assert not any(c.tipo == "capability_scartata" for c in p.correzioni)


def test_capability_inesistente_scartata_senza_eccezione():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y",
                              capability_richieste=["capability-mai-esistita"])
    p = validate_and_normalize(proposta, goal_text="Scrivi un post", detected_intents=["social"])
    assert p.capability_validate == []
    assert "capability-mai-esistita" in p.capability_extra_scartate


def test_capability_predisposta_non_operativa_scartata():
    """'appointments'/'nurturing' esistono nel registry ma sono PREDISPOSTE
    (execution_mode UNAVAILABLE, nessun agente M2 operativo ne' producer):
    esistere nel registry non basta, devono anche essere davvero eseguibili."""
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y",
                              capability_richieste=["appointments"])
    p = validate_and_normalize(proposta, goal_text="Fissa degli appuntamenti", detected_intents=[])
    assert p.capability_validate == []
    assert "appointments" in p.capability_extra_scartate


def test_task_su_capability_reale_non_rilevata_da_keyword_mantenuto():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y", task_proposti=[
        {"nome": "task social", "capability": "social", "ordine": 1},
        {"nome": "task leadgen", "capability": "leadgen", "ordine": 2},
    ])
    p = validate_and_normalize(proposta, goal_text="Voglio aumentare i clienti", detected_intents=["social"])
    nomi = {t["nome"] for t in p.task_proposti_validati}
    assert nomi == {"task social", "task leadgen"}
    assert not any(c.tipo == "task_scartato" for c in p.correzioni)


def test_task_su_capability_inesistente_scartato():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y", task_proposti=[
        {"nome": "task social", "capability": "social", "ordine": 1},
        {"nome": "task fantasma", "capability": "capability-mai-esistita", "ordine": 2},
    ])
    p = validate_and_normalize(proposta, goal_text="Scrivi un post", detected_intents=["social"])
    nomi = [t["nome"] for t in p.task_proposti_validati]
    assert nomi == ["task social"]
    assert any(c.tipo == "task_scartato" for c in p.correzioni)


# ---------------- budget con proposta LLM ----------------
def test_budget_llm_e_testo_in_disaccordo_richiede_chiarimento():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y", budget_totale=5000.0)
    p = validate_and_normalize(proposta, goal_text="Ho 500 euro di budget", detected_intents=["ads"])
    assert p.budget_status == "CONTRADDITTORIO"
    assert p.richiede_chiarimento_budget is True


def test_budget_llm_coerente_con_testo_ok():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y", budget_totale=2000.0)
    p = validate_and_normalize(proposta, goal_text="Ho 2000 euro di budget", detected_intents=["ads"])
    assert p.budget_status == "OK"
    assert p.budget_totale == 2000.0


def test_allocazioni_oltre_il_totale_vengono_ridotte():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y", budget_totale=1000.0, allocazioni_budget=[
        {"etichetta": "social", "importo": 800.0}, {"etichetta": "ads", "importo": 800.0},
    ])
    p = validate_and_normalize(proposta, goal_text="", detected_intents=["ads"])
    assert p.budget_status == "RIDOTTO_PER_RISPETTARE_LIMITE"
    assert p.budget_allocato == 1000.0
    assert any(c.tipo == "budget_ridotto" for c in p.correzioni)
    # Le singole voci (per task/canale) restano visibili, non solo il totale:
    # ridotte proporzionalmente, mai scartate.
    assert len(p.allocazioni_budget) == 2
    assert sum(a["importo"] for a in p.allocazioni_budget) == 1000.0
    assert p.allocazioni_budget[0]["etichetta"] == "social"


def test_allocazioni_entro_il_totale_restano_intatte():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y", budget_totale=1000.0, allocazioni_budget=[
        {"etichetta": "social", "importo": 300.0}, {"etichetta": "ads", "importo": 400.0},
    ])
    p = validate_and_normalize(proposta, goal_text="", detected_intents=["ads"])
    assert p.budget_status == "OK"
    assert p.allocazioni_budget == [{"etichetta": "social", "importo": 300.0}, {"etichetta": "ads", "importo": 400.0}]


def test_budget_assente_e_ads_richiesto_richiede_chiarimento_anche_con_proposta():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y")
    p = validate_and_normalize(proposta, goal_text="Lancia una campagna ads", detected_intents=["ads"])
    assert p.budget_status == "ASSENTE_INDISPENSABILE"
    assert p.richiede_chiarimento_budget is True


# ---------------- rischi: normalizzati e aggregati, mai applicati qui ----------------
def test_rischi_aggregati_azione_piu_severa():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y", rischi=[
        {"categoria": "spesa", "severita": "MEDIA"}, {"categoria": "consenso", "severita": "BASSA"},
    ])
    p = validate_and_normalize(proposta, goal_text="", detected_intents=["social"])
    assert p.azione_rischio_aggregata == AZIONE_APPROVAL  # spesa/MEDIA = APPROVAL, la piu' severa
    assert len(p.rischi_valutati) == 2


def test_rischio_bloccante_riflesso_nellazione_aggregata():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y", rischi=[
        {"categoria": "irreversibile", "severita": "BASSA"},
    ])
    p = validate_and_normalize(proposta, goal_text="", detected_intents=["social"])
    assert p.azione_rischio_aggregata == AZIONE_BLOCK


def test_nessun_rischio_azione_none():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y")
    p = validate_and_normalize(proposta, goal_text="", detected_intents=["social"])
    assert p.azione_rischio_aggregata == AZIONE_NONE


# ---------------- domande aggiuntive: dedup contro chiarimenti gia' dati ----------------
def test_dati_mancanti_deduplica_contro_chiarimenti_gia_dati():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y",
                              dati_mancanti=["Qual e' il logo aziendale?", "Qual e' il target?"])
    p = validate_and_normalize(
        proposta, goal_text="", detected_intents=["social"],
        chiarimenti_gia_dati={"qual e' il target?"},
    )
    assert p.domande_aggiuntive == ["Qual e' il logo aziendale?"]


def test_metadati_provider_propagati():
    proposta = CeoLLMProposal(intent="x", strategia_proposta="y")
    p = validate_and_normalize(proposta, goal_text="", detected_intents=["social"],
                               provider_effettivo="openai", modello_effettivo="gpt-4o")
    assert p.origine == "LLM"
    assert p.provider_effettivo == "openai"
    assert p.modello_effettivo == "gpt-4o"
