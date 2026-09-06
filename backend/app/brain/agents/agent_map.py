"""Brain — mappatura ufficiale degli agenti (Blocco B, corretta in B.1).

Unica fonte di verità che collega:
- capability M2 (m2/agents_registry.py::DELIVERABLE_CAPABILITY);
- agent_id M2 (m2/agents_registry.py::AGENT_CONTRACTS) — NON duplicato,
  solo referenziato per nome/stringa;
- agent_id frontend (frontend/src/components/meeting-room/agentRegistry.js)
  — letto e verificato manualmente (il backend non importa codice
  frontend): gli agent_id qui sotto DEVONO coincidere esattamente con
  quelli in AGENT_REGISTRY lato frontend;
- prontezza di esecuzione reale (execution_ready/execution_mode): una
  capability può essere selezionabile concettualmente ma NON ancora
  eseguibile da M2 — il brain non deve mai dichiarare eseguibile un piano
  che M2 non può davvero trasformare in task/deliverable.

execution_mode:
- "M2": la capability ha un agente M2 operativo (agents_registry.py,
  operative=True) E un producer deterministico che genera quel
  deliverable_type (m2/deliverables.py + brain/producers.py) — eseguibile
  oggi, per davvero.
- "BRAIN_SIMULATION": nessun agente M2 operativo, ma esiste un producer
  deterministico nel brain in grado di simulare un risultato coerente
  senza toccare M2 — NESSUNA capability è oggi in questo stato (verificato
  sul codice reale: né m2/deliverables.py né brain/producers.py hanno un
  producer per 'appointments'/'nurturing') — il valore resta previsto per
  quando un producer del genere esisterà.
- "UNAVAILABLE": nessun agente M2 operativo E nessun producer di
  simulazione: la capability non può produrre alcun risultato oggi.

Il Coordinatore ACTELYA ("coordinatore-actelya" lato frontend) NON è un
agente selezionabile: non compare in questa mappatura, non è mai incluso
in activeAgentIds — è gestito separatamente dal frontend tramite
agentRegistry.js::COORDINATOR_AGENT, sempre visibile di suo.

Due capability M2 esistono ma non hanno alcun ruolo frontend dedicato
(auditor, tech_lead): sono processi di revisione automatici, sempre
eseguiti da m2/reviews.py su ogni deliverable indipendentemente dalla
selezione dinamica — mai esposti come agente "convocabile" in questa fase
(vedi UNMAPPED_M2_ONLY_CAPABILITIES)."""
from __future__ import annotations

from dataclasses import dataclass, field

EXECUTION_MODE_M2 = "M2"
EXECUTION_MODE_SIMULATION = "BRAIN_SIMULATION"
EXECUTION_MODE_UNAVAILABLE = "UNAVAILABLE"
# "REAL": capability eseguita FUORI da M2 (che resta dichiaratamente solo-
# simulazione) tramite un dominio dedicato che parla per davvero con un
# gateway esterno, sempre dietro conferma esplicita (vedi domains/reel.py:
# Requesty per testo/storyboard, Runway per video). brain/service.py la
# instrada SENZA passare da m2.engine.create_plan.
EXECUTION_MODE_REAL = "REAL"


@dataclass(frozen=True)
class AgentMapping:
    capability: str          # capability M2 (m2/agents_registry.py::DELIVERABLE_CAPABILITY)
    m2_agent_id: str         # m2/agents_registry.py::AGENT_CONTRACTS
    frontend_agent_id: str   # frontend/src/components/meeting-room/agentRegistry.js
    role_name: str           # deve combaciare con agentRegistry.js::role_name
    typical_use_cases: str
    m2_operative: bool             # AGENT_CONTRACTS[...]["operative"] in M2 oggi
    execution_ready: bool          # True SOLO se execution_mode == "M2"
    execution_mode: str            # "M2" | "BRAIN_SIMULATION" | "UNAVAILABLE"
    deliverable_type: str | None = None   # tipo di deliverable M2 prodotto, se esiste
    implementation_note: str = ""         # spiegazione, obbligatoria se non "M2"
    notes: str = ""
    # ---- Specializzazione (separazione Agent/Capability/Skill/Provider,
    # vedi brain/skills.py per il dettaglio di ciascuna skill referenziata) ----
    mission: str = ""                          # responsabilita' dell'agente in una frase
    skills: tuple[str, ...] = ()                # skill_id di brain/skills.py posseduti da questo agente
    data_accessible: tuple[str, ...] = ()       # campi Fact Ledger/profilo consultabili
    quality_criteria: tuple[str, ...] = ()      # cosa rende il risultato accettabile
    excluded_when: tuple[str, ...] = ()         # condizioni per cui l'agente NON va selezionato


# Ordine deterministico: definisce anche l'ordine stabile con cui
# selected_agents/activeAgentIds vengono restituiti (mai un ordine
# dipendente da un set/dict Python).
AGENT_MAPPINGS: tuple[AgentMapping, ...] = (
    AgentMapping(
        "strategy", "marketing_strategist", "resp-marketing", "Responsabile marketing",
        "Strategia, posizionamento, priorità tra canali di attrazione.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="marketing_strategy",
        mission="Definire segmenti, value proposition e canali prioritari prima che chiunque altro produca contenuto.",
        skills=("marketing_strategy_m2",),
        data_accessible=("ragione_sociale", "settore", "obiettivi_commerciali", "sito_web"),
        quality_criteria=("almeno 2 segmenti target distinti", "value proposition riconducibile al settore dichiarato"),
        excluded_when=("la richiesta e' di sola analisi/lettura di risultati esistenti (capability 'analytics')",),
    ),
    AgentMapping(
        "editorial", "content_social", "social-media-manager", "Social media manager",
        "Piano editoriale, calendario contenuti organici.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="editorial_plan",
        mission="Trasformare la strategia in un calendario editoriale concreto (pilastri, cadenza, canali).",
        skills=("editorial_plan_m2",),
        data_accessible=("ragione_sociale", "settore", "canali dichiarati nell'obiettivo"),
        quality_criteria=("almeno 3 voci di calendario", "almeno 2 pilastri di contenuto"),
        excluded_when=("la richiesta e' un singolo post/reel isolato, non un piano ricorrente",),
    ),
    AgentMapping(
        "social", "content_social", "copywriter", "Copywriter",
        "Scrittura dei singoli post/contenuti social.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="social_content",
        notes="Stesso agente M2 di 'editorial' (content_social): capability diversa, ruolo frontend diverso.",
        mission="Scrivere hook, corpo e CTA di post pronti alla pubblicazione (bozza, mai inviata).",
        skills=("social_content_m2",),
        data_accessible=("ragione_sociale", "settore", "canali dichiarati nell'obiettivo"),
        quality_criteria=("almeno 2 post", "hashtag pertinenti, nessun placeholder non dichiarato"),
        excluded_when=("la richiesta chiede esplicitamente un reel/video (capability 'video_reel', mai sovrapposta a 'social')",),
    ),
    AgentMapping(
        "email", "content_social", "copywriter", "Copywriter",
        "Scrittura email.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="email",
        notes="Capability 'email' assegnata a content_social in M2; lato frontend mappata su Copywriter "
              "(stesso ruolo di 'social').",
        mission="Scrivere oggetto, proposta e corpo di un'email pronta alla revisione (bozza, mai inviata).",
        skills=("email_copy_m2",),
        data_accessible=("ragione_sociale", "settore"),
        quality_criteria=("oggetto/CTA non vuoti", "nessun destinatario reale, nessuna PII"),
    ),
    AgentMapping(
        "content", "content_creator", "content-creator", "Content Creator",
        "Produzione multi-formato di contenuti (landing, blog/SEO, comunicazioni commerciali/offerte, "
        "caroselli, contenuti informativi e qualunque altro formato richiesto esplicitamente) — decide "
        "cosa produrre, genera davvero il testo via Requesty, e collega l'asset multimediale reale "
        "(reel/flyer) quando il formato lo richiede.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_REAL, deliverable_type="content_item",
        implementation_note="Non e' un agente M2 operativo in senso stretto (nessun producer deterministico "
                             "in m2/deliverables.py): il piano M2 include un task 'content_item' collegato al "
                             "laboratorio reale in domains/content_creator (decisione del formato, generazione "
                             "reale via Requesty, validazione strutturale e semantica, approvazione, "
                             "collegamento asset). Agente CONSOLIDATO: riusa le skill/producer gia' esistenti "
                             "di copywriter/video-creator/creative-designer (mai rimossi, mai duplicati) per i "
                             "formati gia' coperti da quelle capability; copre nativamente i formati non "
                             "ancora presidiati da nessun agente (landing, blog/SEO, comunicazioni "
                             "commerciali/offerte, caroselli, contenuti informativi). 'm2_agent_id' qui e' "
                             "solo un'etichetta descrittiva, non una voce di m2/agents_registry.py::AGENT_CONTRACTS.",
        notes="Il task entra nello STESSO piano/DAG M2 delle altre capability (brain/service.py): un solo "
              "piano, mai un secondo percorso separato.",
        mission="Decidere quale contenuto produrre e perche', generarlo davvero grounded sul Fact Ledger, "
                "e portarlo fino al deliverable finale (incluso l'asset multimediale collegato, quando richiesto).",
        skills=("content_creation_requesty",),
        data_accessible=("ragione_sociale", "settore", "sito_web", "obiettivi_commerciali", "prodotto",
                         "pubblico_target", "tono_di_voce"),
        quality_criteria=("nessuna affermazione su prodotto/pubblico/prezzo/territorio estranea al Fact "
                          "Ledger o al brief (domains/reel_semantic.py)", "contenuto dichiarato pronto SOLO "
                          "dopo la validazione strutturale (domains/content_creator/validation.py)"),
        excluded_when=("il Fact Ledger non ha ragione_sociale/settore",),
    ),
    AgentMapping(
        "ads", "advertising", "resp-advertising", "Specialista advertising",
        "Bozza di campagna pubblicitaria (mai pubblicata).", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type="ad_campaign_draft",
        mission="Preparare varianti di annuncio e audience in bozza, sempre status=DRAFT, mai pubblicata.",
        skills=("ad_campaign_draft_m2",),
        data_accessible=("ragione_sociale", "settore", "obiettivi_commerciali"),
        quality_criteria=("almeno 2 varianti annuncio", "audience descritta senza PII"),
        excluded_when=("la richiesta e' di soli contenuti organici, nessun budget/campagna a pagamento menzionato",),
    ),
    AgentMapping(
        "leadgen", "lead_gen_sdr", "lead-gen-specialist", "Lead generation specialist",
        "Import/analisi di lead reali (upload file, ricerca prospect, scoring, deduplica, "
        "compliance, campagne, export) — nessun contatto reale automatico.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_REAL, deliverable_type="lead_gen_campaign",
        implementation_note="Non e' un agente M2 operativo in senso stretto (nessun producer "
                             "deterministico in m2/deliverables.py per questo percorso): il piano M2 "
                             "include un task 'lead_gen_campaign' collegato a una campagna reale in "
                             "domains/leadgen (upload, mapping, normalizzazione, deduplica, compliance, "
                             "scoring, approvazione, export/handoff). Funziona con ZERO provider esterni "
                             "configurati (adapter di ricerca non configurati tornano sempre "
                             "NON_DISPONIBILE, mai un risultato inventato); un opt-out/regola privacy "
                             "prevale sempre sul punteggio commerciale, mai bypassabile. 'm2_agent_id' "
                             "qui e' solo un'etichetta descrittiva, non una voce di "
                             "m2/agents_registry.py::AGENT_CONTRACTS.",
        notes="Il task entra nello STESSO piano/DAG M2 delle altre capability (brain/service.py): un "
              "solo piano, mai un secondo percorso separato. Il lavoro vero (upload, revisione "
              "duplicati, approvazione, export) avviene nel laboratorio Lead Generation.",
        mission="Definire l'ICP, importare/qualificare prospect reali (mai inventati) e preparare "
                "campagne pronte per l'approvazione — nessun contatto automatico.",
        skills=("lead_gen_plan_m2",),
        data_accessible=("ragione_sociale", "settore", "obiettivi_commerciali"),
        quality_criteria=("almeno un criterio ICP esplicito", "nessun record DO_NOT_CONTACT esportato",
                          "ogni valore ha uno stato di provenienza tracciabile"),
    ),
    AgentMapping(
        "analytics", "analytics_performance", "analista-performance", "Analista performance",
        "Report KPI REALI su lead/pipeline commerciale/appuntamenti/costi già presenti in ACTELYA, "
        "interpretazione (anomalie/pattern) e insight strutturati indirizzati agli agenti interessati.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_REAL, deliverable_type="analyst_report",
        implementation_note="Non e' un agente M2 operativo in senso stretto (il producer 'kpi_report_m2' resta "
                             "invariato per il percorso M2 diretto/simulato, non piu' usato da questo percorso): "
                             "il piano M2 include un task 'analyst_report' collegato al laboratorio reale in "
                             "domains/analyst, che calcola KPI REALI da dati gia' presenti (lead_companies/"
                             "lead_persons, sales_opportunities, appointment_bookings, tool_cost_events) — mai un "
                             "valore inventato: un KPI senza dati sufficienti e' sempre NON_DISPONIBILE, mai "
                             "sostituito da una stima. 'm2_agent_id' qui e' solo un'etichetta descrittiva, non una "
                             "voce di m2/agents_registry.py::AGENT_CONTRACTS.",
        notes="Il task entra nello STESSO piano/DAG M2 delle altre capability (brain/service.py): un solo piano, "
              "mai un secondo percorso separato.",
        mission="Calcolare KPI reali con fonte/formula/affidabilita' espliciti, interpretarli (mai solo "
                "visualizzarli), e indirizzare insight strutturati agli agenti giusti (CEO, Sales, Lead "
                "Generation, Content Creator) — mai un dato mancante sostituito da un'invenzione.",
        skills=("kpi_analysis_real",),
        data_accessible=("lead qualificati (lead_generation)", "pipeline commerciale (sales)",
                         "prenotazioni (appointment-setter)", "costi strumenti (Tool Execution Gateway)"),
        quality_criteria=("ogni KPI ha source/formula/valore/reliability/missing_data espliciti",
                          "nessun insight generato su un campione dichiarato insufficiente"),
        excluded_when=("la richiesta e' di creare/lanciare qualcosa di nuovo, non di leggere risultati esistenti",),
    ),
    AgentMapping(
        "review_compliance", "compliance_reviewer", "resp-compliance", "Responsabile compliance",
        "Verifica di conformità sui contenuti prodotti.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_M2, deliverable_type=None,
        implementation_note="Non produce un deliverable proprio: è una revisione automatica eseguita "
                             "da m2/reviews.py su ogni deliverable, non un task distinto del DAG.",
        notes="In M2 la revisione compliance è già eseguita automaticamente su ogni deliverable "
              "(m2/reviews.py, invariato). Qui selezionabile esplicitamente quando si produce "
              "contenuto rivolto al pubblico, per mostrarlo come collaboratore attivo in sala riunioni.",
        mission="Segnalare rischi di conformita' (GDPR, consenso, claim non supportati) su ogni deliverable pubblico.",
        skills=("compliance_review_m2",),
        data_accessible=("tutti i deliverable del piano corrente",),
        quality_criteria=("nessun deliverable rivolto al pubblico resta privo di revisione",),
    ),
    AgentMapping(
        "video_reel", "reel_video_creator", "video-creator", "Video creator (Reel)",
        "Reel/video verticale per Instagram/TikTok: concept, hook, sceneggiatura, storyboard, "
        "voice-over, caption, CTA via Requesty; video reale via Runway.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_REAL, deliverable_type="video_reel_project",
        implementation_note="Non e' un agente M2 operativo in senso stretto (nessun producer deterministico "
                             "in m2/deliverables.py): il piano M2 include comunque un task 'video_reel_project' "
                             "collegato a un progetto reale in domains/reel.py, generato davvero via Requesty "
                             "(testo) e Runway (video), sempre con conferma esplicita per ogni chiamata a "
                             "pagamento (mai automatica). 'm2_agent_id' qui e' solo un'etichetta descrittiva, "
                             "non una voce di m2/agents_registry.py::AGENT_CONTRACTS.",
        notes="Il task entra nello STESSO piano/DAG M2 delle altre capability (brain/service.py): un solo "
              "piano, mai un secondo percorso separato. Ruolo DISTINTO dal Creative/Graphic Designer "
              "(capability 'flyer_image'): il Video creator copre storyboard audiovisivo/montaggio/video, "
              "non layout statici.",
        mission="Ideare e produrre contenuto video reale: sceneggiatura e storyboard via Requesty, "
                "clip video via Runway, sempre grounded sul Fact Ledger, mai un'affermazione inventata.",
        skills=("reel_text_requesty", "reel_video_runway", "voice_over_tts"),
        data_accessible=("ragione_sociale", "settore", "sito_web", "obiettivi_commerciali", "prodotto",
                         "pubblico_target", "tono_di_voce"),
        quality_criteria=("nessuna affermazione su prodotto/pubblico/prezzo/territorio estranea al Fact Ledger "
                          "o al brief (domains/reel_semantic.py)", "video dichiarato pronto SOLO con un URL "
                          "realmente riproducibile"),
        excluded_when=("il Fact Ledger non ha ragione_sociale/settore (si chiede prima quello, mai un contenuto generico spacciato per specifico)",),
    ),
    AgentMapping(
        "flyer_image", "flyer_creative_designer", "creative-designer", "Creative/Graphic Designer",
        "Flyer/immagine promozionale: copy, layout concettuale, prompt immagine, generazione reale via Requesty.",
        True, execution_ready=True, execution_mode=EXECUTION_MODE_REAL, deliverable_type="flyer_project",
        implementation_note="Non e' un agente M2 operativo in senso stretto: il piano M2 include un task "
                             "'flyer_project' collegato a un progetto reale in domains/flyer.py, generato "
                             "davvero via Requesty (testo E immagine, confermato su docs.requesty.ai -- "
                             "POST /v1/images/generations), sempre con conferma esplicita.",
        notes="Ruolo DISTINTO dal Video creator: stesso pattern (obiettivo -> grounding -> skill -> "
              "provider -> validazione -> approvazione), capability e deliverable diversi (statico vs "
              "audiovisivo). Il task entra nello STESSO piano/DAG M2 delle altre capability.",
        mission="Comporre il messaggio (headline, sottotitolo, CTA) e il prompt visivo di un flyer promozionale, "
                "generare l'immagine reale, sempre grounded sul Fact Ledger, mai un'affermazione inventata.",
        skills=("flyer_image_generation",),
        data_accessible=("ragione_sociale", "settore", "sito_web", "obiettivi_commerciali", "prodotto",
                         "pubblico_target", "tono_di_voce"),
        quality_criteria=("nessuna affermazione su prodotto/pubblico/prezzo/territorio estranea al Fact "
                          "Ledger o al brief (domains/reel_semantic.py)", "immagine dichiarata pronta SOLO "
                          "con un URL realmente generato da Requesty"),
        excluded_when=("il Fact Ledger non ha ragione_sociale/settore",),
    ),
    AgentMapping(
        "audio_voiceover", "reel_video_creator", "video-creator", "Video creator (Reel)",
        "Voice-over/audio promozionale.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_REAL, deliverable_type=None,
        implementation_note="PREDISPOSTA: nessun provider TTS verificato oggi (brain/skills.py -> "
                             "voice_over_tts, sempre NOT_CONFIGURED). Lo script del voice-over resta "
                             "comunque disponibile in testo (prodotto dalla skill 'reel_text_requesty').",
        notes="Stesso agente/ruolo di 'video_reel' (Video/Creative specialist unico).",
        mission="Predisporre lo script del voice-over; la sintesi audio resta NOT_CONFIGURED.",
        skills=("voice_over_tts",),
        data_accessible=("ragione_sociale", "settore"),
    ),
    AgentMapping(
        "appointments", "appointment_setter", "appointment-setter", "Appointment setter",
        "Proporre e prenotare appuntamenti reali su calendario esterno (Google Calendar/Microsoft "
        "Graph/Calendly), sempre a partire da lead già approvati.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_REAL, deliverable_type="appointment_setter_task",
        implementation_note="Non e' un agente M2 operativo in senso stretto (nessun producer "
                             "deterministico in m2/deliverables.py): il piano M2 include un task "
                             "'appointment_setter_task' collegato al laboratorio reale in "
                             "domains/appointments (proposta slot, approvazione, prenotazione reale su "
                             "Google Calendar/Microsoft Graph/Calendly). Funziona con ZERO provider "
                             "esterni configurati (connessione calendario NON_CONFIGURATA finche' non "
                             "collegata): nessuna prenotazione e' mai dichiarata confermata senza una "
                             "risposta reale del provider (o del fake adapter nei test) — un errore o "
                             "timeout produce ESITO_INCERTO, mai una conferma inventata. Un lead con "
                             "consenso/opt-out/DO_NOT_CONTACT non entra mai in una proposta. "
                             "'m2_agent_id' qui e' solo un'etichetta descrittiva, non una voce di "
                             "m2/agents_registry.py::AGENT_CONTRACTS (che resta PREDISPOSTO/non "
                             "operativo per il percorso M2 simulato diretto).",
        notes="Il task entra nello STESSO piano/DAG M2 delle altre capability (brain/service.py): un "
              "solo piano, mai un secondo percorso separato. Il lavoro vero (selezione lead, proposta "
              "slot, approvazione, prenotazione, cancellazione/riprogrammazione) avviene nel "
              "laboratorio Appointment Setter.",
        mission="Selezionare slot compatibili con la disponibilità reale del calendario, ottenere "
                "l'approvazione umana e prenotare davvero — mai un contatto o una prenotazione senza "
                "conferma verificabile.",
        skills=("appointment_scheduling",),
        data_accessible=("lead approvato (lead_generation)", "disponibilità calendario collegato"),
        quality_criteria=("nessuna prenotazione dichiarata CONFERMATA senza risposta del provider",
                          "nessun lead DO_NOT_CONTACT/opt-out mai incluso in una proposta"),
        excluded_when=("nessun lead approvato disponibile e nessuna connessione calendario configurata",),
    ),
    AgentMapping(
        "sales", "sales_pipeline", "sales-agent", "Sales Agent",
        "Pipeline commerciale completa a partire da lead qualificati (Lead Generation): analisi, strategia di "
        "contatto, gestione delle risposte del prospect, obiezioni, handoff con Appointment Setter.", True,
        execution_ready=True, execution_mode=EXECUTION_MODE_REAL, deliverable_type="sales_opportunity",
        implementation_note="Non e' un agente M2 operativo in senso stretto (nessun producer deterministico in "
                             "m2/deliverables.py): il piano M2 include un task 'sales_opportunity' collegato al "
                             "laboratorio reale in domains/sales. Come 'appointments', non esiste un 'contenitore' "
                             "da creare subito: un'opportunità richiede un lead specifico già QUALIFIED/pronto per "
                             "l'handoff (next_action == PRONTO_PER_SALES, deciso da Lead Generation), azione "
                             "dell'utente nel laboratorio, non derivabile dal solo testo dell'obiettivo. "
                             "'m2_agent_id' qui e' solo un'etichetta descrittiva, non una voce di "
                             "m2/agents_registry.py::AGENT_CONTRACTS.",
        notes="Il task entra nello STESSO piano/DAG M2 delle altre capability (brain/service.py): un solo piano, "
              "mai un secondo percorso separato. Delega SEMPRE la scrittura del messaggio a Content Creator "
              "(capability 'content'): mai una seconda chiamata Requesty duplicata qui.",
        mission="Decidere strategia, canale, timing e next-best-action per ogni lead qualificato, gestire "
                "l'intera pipeline (fino a vinto/perso) reagendo alle risposte del prospect, e coordinarsi con "
                "Appointment Setter per gli appuntamenti — mai un contatto senza un canale reale disponibile.",
        skills=("sales_pipeline_management",),
        data_accessible=("lead qualificato (lead_generation)", "esito prenotazione (appointment-setter)"),
        quality_criteria=("nessuna transizione di stage senza una regola esplicita (strategy.py)",
                          "nessuna opportunità creata da un lead non PRONTO_PER_SALES"),
        excluded_when=("nessun lead pronto per l'handoff a Sales disponibile",),
    ),
    AgentMapping(
        "nurturing", "nurturing", "specialista-nurturing", "Specialista nurturing",
        "Mantenimento nel tempo dei lead non ancora pronti.", False,
        execution_ready=False, execution_mode=EXECUTION_MODE_UNAVAILABLE, deliverable_type=None,
        implementation_note="Stesso limite di 'appointments': nessun deliverable_type M2 e nessun "
                             "producer di simulazione nel brain per questa capability oggi.",
        mission="PREDISPOSTO: sequenze di nurturing (nessuna implementazione oggi).",
    ),
)

# Capability M2 che esistono ma NON sono esposte come agenti selezionabili
# dal brain in questa fase: processi automatici interni a M2, mai in
# activeAgentIds, mai in selected_agents/excluded_agents.
UNMAPPED_M2_ONLY_CAPABILITIES: dict[str, str] = {
    "review_audit": "auditor",   # eseguito automaticamente da m2/reviews.py su ogni deliverable
    "review_tech": "tech_lead",  # nessun ruolo frontend dedicato; fuori scope in questa fase
}

COORDINATOR_FRONTEND_ID = "coordinatore-actelya"


@dataclass(frozen=True)
class AgentGroup:
    """Un agente frontend può coprire più capability M2 (es. copywriter
    copre sia 'social' sia 'email', stesso agente M2 content_social)."""
    frontend_agent_id: str
    role_name: str
    mappings: tuple[AgentMapping, ...] = field(default_factory=tuple)

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(m.capability for m in self.mappings)

    @property
    def m2_agent_id(self) -> str:
        return self.mappings[0].m2_agent_id

    @property
    def m2_operative(self) -> bool:
        return self.mappings[0].m2_operative


def agent_groups() -> tuple[AgentGroup, ...]:
    """Raggruppa AGENT_MAPPINGS per agent_id frontend, preservando
    l'ordine di prima apparizione: un solo AgentGroup per ciascuno dei 9
    ruoli frontend, anche quando più capability M2 vi convergono."""
    order: list[str] = []
    grouped: dict[str, list[AgentMapping]] = {}
    for m in AGENT_MAPPINGS:
        if m.frontend_agent_id not in grouped:
            grouped[m.frontend_agent_id] = []
            order.append(m.frontend_agent_id)
        grouped[m.frontend_agent_id].append(m)
    return tuple(
        AgentGroup(frontend_agent_id=fid, role_name=grouped[fid][0].role_name, mappings=tuple(grouped[fid]))
        for fid in order
    )


ALL_FRONTEND_AGENT_IDS: frozenset = frozenset(m.frontend_agent_id for m in AGENT_MAPPINGS)


def mapping_by_capability(capability: str) -> AgentMapping | None:
    for m in AGENT_MAPPINGS:
        if m.capability == capability:
            return m
    return None


def group_by_frontend_id(agent_id: str) -> AgentGroup | None:
    for g in agent_groups():
        if g.frontend_agent_id == agent_id:
            return g
    return None
