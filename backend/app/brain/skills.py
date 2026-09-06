"""Brain — Registro Skill (capacità professionali).

Separazione concettuale esplicita (mai confusa nel codice):
- Agent  = professionista digitale (agents/agent_map.py -> AgentMapping/AgentGroup).
- Capability = cosa il professionista sa fare (stringa gia' usata da
  planning/agent_selector.py, es. 'strategy', 'video_reel').
- Skill = COME/con cosa svolge una capability (QUESTO modulo): una skill ha
  input/output, prerequisiti, provider ammessi, permessi, stato reale.
- Provider = servizio tecnico sostituibile dietro una skill (Requesty,
  Runway, HeyGen...): mai l'identita' dell'agente o della skill.
- Deliverable = risultato consegnato (m2/deliverables.py per le skill M2,
  domains/reel.py per le skill REALI).

Un agente puo' possedere piu' skill; una skill e' sempre riconducibile a
UNA capability (m2/agents_registry.py::DELIVERABLE_CAPABILITY per le skill
M2, agents/agent_map.py per quelle REALI). Il Brain seleziona prima gli
AGENTI (planning/agent_selector.py, invariato), poi per ciascuna capability
selezionata risolve la/le skill che la soddisfano (skills_for_capability).

Stato di una skill (skill_status, MAI hardcoded): calcolato a runtime
verificando se il provider richiesto e' davvero configurato/verificato
(stessa fonte di verita' usata da domains/reel.py -> _readiness/_video_
readiness: nessuna seconda verifica duplicata)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

STATUS_M2_SIMULATION = "M2_SIMULATION"      # eseguita oggi da M2 (deterministica, mai un costo reale)
STATUS_REAL = "REAL"                        # eseguita davvero da un provider esterno, dietro conferma
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"    # skill REALE ma nessun provider verificato per l'org
STATUS_UNAVAILABLE = "UNAVAILABLE"          # nessuna implementazione ne' reale ne' simulata oggi


@dataclass(frozen=True)
class Skill:
    skill_id: str                      # identificativo stabile, mai riassegnato
    name: str
    version: str
    description: str
    capability: str                    # capability soddisfatta (planning/agent_selector.py)
    deliverable_type: str              # tipo di risultato prodotto
    allowed_roles: tuple[str, ...]      # frontend_agent_id autorizzati a usarla (agents/agent_map.py)
    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    required_facts: tuple[str, ...] = ()        # campi Fact Ledger indispensabili (mai inventati se assenti)
    tools: tuple[str, ...] = ()                  # provider utilizzabili, in ordine di preferenza
    requires_approval: bool = True
    cost_hint: str = "nessuno (simulazione)"
    validation: str = ""
    handoff_to: tuple[str, ...] = ()
    fallback: str = ""
    base_mode: str = STATUS_M2_SIMULATION   # M2_SIMULATION | REAL | UNAVAILABLE (NOT_CONFIGURED e' derivato, mai dichiarato qui)
    # Nome del provider "principale" la cui disponibilita' reale determina se
    # una skill base_mode=REAL risulta REAL o NOT_CONFIGURED per una org.
    # Verificato da provider_status_checker (mai imposto, sempre calcolato).
    primary_provider: Optional[str] = None


# ==================== Skill M2 (simulazione, invariate: stesso producer/validator gia' in m2/deliverables.py) ====================
SKILLS: dict[str, Skill] = {
    "marketing_strategy_m2": Skill(
        "marketing_strategy_m2", "Strategia di marketing (simulata)", "1.0.0",
        "Segmenti, value proposition, posizionamento, canali, obiettivi — bozza deterministica.",
        capability="strategy", deliverable_type="marketing_strategy",
        allowed_roles=("resp-marketing",),
        required_facts=("ragione_sociale",), tools=("m2_producer",),
        cost_hint="nessuno (simulazione)", validation="m2/deliverables.py::validate_marketing_strategy",
        handoff_to=("content_social",), base_mode=STATUS_M2_SIMULATION,
    ),
    "editorial_plan_m2": Skill(
        "editorial_plan_m2", "Piano editoriale (simulato)", "1.0.0",
        "Cadenza, pilastri di contenuto, calendario — bozza deterministica.",
        capability="editorial", deliverable_type="editorial_plan",
        allowed_roles=("social-media-manager",), tools=("m2_producer",),
        validation="m2/deliverables.py::validate_editorial_plan", base_mode=STATUS_M2_SIMULATION,
    ),
    "social_content_m2": Skill(
        "social_content_m2", "Post social (simulati)", "1.0.0",
        "Hook, corpo, CTA, hashtag per N post — bozza deterministica.",
        capability="social", deliverable_type="social_content",
        allowed_roles=("copywriter",), tools=("m2_producer",),
        validation="m2/deliverables.py::validate_social_content", base_mode=STATUS_M2_SIMULATION,
    ),
    "email_copy_m2": Skill(
        "email_copy_m2", "Copy email (simulato)", "1.0.0",
        "Oggetto, proposta, corpo, CTA — bozza deterministica.",
        capability="email", deliverable_type="email",
        allowed_roles=("copywriter",), tools=("m2_producer",),
        validation="domains/validators.py::validate_email_deliverable", base_mode=STATUS_M2_SIMULATION,
    ),
    "ad_campaign_draft_m2": Skill(
        "ad_campaign_draft_m2", "Bozza campagna advertising (simulata)", "1.0.0",
        "Audience, varianti annuncio, budget simulato — sempre status=DRAFT, mai pubblicata.",
        capability="ads", deliverable_type="ad_campaign_draft",
        allowed_roles=("resp-advertising",), tools=("m2_producer",),
        validation="m2/deliverables.py::validate_ad_campaign_draft", base_mode=STATUS_M2_SIMULATION,
    ),
    "lead_gen_plan_m2": Skill(
        "lead_gen_plan_m2", "Lead generation — import e qualifica reale", "2.0.0",
        "Upload file (CSV/TSV/XLSX/PDF/DOCX/TXT), ricerca prospect, normalizzazione, deduplica, "
        "gate privacy/compliance e scoring spiegabile — dati reali (mai inventati), nessun "
        "contatto automatico. Funziona senza alcun provider esterno configurato.",
        capability="leadgen", deliverable_type="lead_gen_campaign",
        allowed_roles=("lead-gen-specialist",),
        validation="domains/leadgen/compliance.py::evaluate_compliance + domains/leadgen/scoring.py::score_record",
        base_mode=STATUS_M2_SIMULATION,
    ),
    "kpi_report_m2": Skill(
        "kpi_report_m2", "Report KPI (simulato)", "1.0.0",
        "Indicatori con target/valore SIMULATO o NON_DISPONIBILE — mai un dato reale inventato.",
        capability="analytics", deliverable_type="kpi_report",
        allowed_roles=("analista-performance",), tools=("m2_producer",),
        validation="m2/deliverables.py::validate_kpi_report", base_mode=STATUS_M2_SIMULATION,
    ),
    "compliance_review_m2": Skill(
        "compliance_review_m2", "Revisione compliance", "1.0.0",
        "Verifica automatica di conformita' su ogni deliverable rivolto al pubblico.",
        capability="review_compliance", deliverable_type=None,
        allowed_roles=("resp-compliance",), tools=("m2_reviewer",),
        requires_approval=False, cost_hint="nessuno", base_mode=STATUS_M2_SIMULATION,
    ),

    # ==================== Skill REALI (Video creator) ====================
    "reel_text_requesty": Skill(
        "reel_text_requesty", "Sceneggiatura e storyboard reel (Requesty)", "1.0.0",
        "Concept, hook, sceneggiatura, storyboard, voice-over, caption, CTA, prompt video — "
        "generazione REALE via Requesty, grounded sul Fact Ledger, mai statica.",
        capability="video_reel", deliverable_type="video_reel_project",
        allowed_roles=("video-creator",),
        required_inputs=("brief",), required_facts=("ragione_sociale", "settore"),
        tools=("requesty",), requires_approval=True, cost_hint="pochi centesimi per generazione (token Requesty)",
        validation="domains/reel_semantic.py::semantic_validate_reel_content + domains/reel.py::validate_reel_content",
        handoff_to=("reel_video_runway",), fallback="Progetto testuale resta in BOZZA/BLOCCATO: mai un contenuto inventato.",
        base_mode=STATUS_REAL, primary_provider="requesty",
    ),
    "reel_video_runway": Skill(
        "reel_video_runway", "Generazione video reel (Runway)", "1.0.0",
        "Clip video reale da un prompt_video_generativo gia' prodotto e validato semanticamente.",
        capability="video_reel", deliverable_type="video_reel_media",
        allowed_roles=("video-creator",),
        required_inputs=("prompt_video_generativo",),
        tools=("runway",), requires_approval=True,
        cost_hint="crediti Runway (tetto configurabile per generazione)",
        validation="Nessun video dichiarato pronto senza un URL realmente riproducibile (domains/reel.py).",
        fallback="Se il credito/provider manca: NOT_CONFIGURED, il progetto testuale resta comunque disponibile.",
        base_mode=STATUS_REAL, primary_provider="runway",
    ),

    # ==================== Skill REALE (Creative/Graphic Designer) ====================
    "flyer_image_generation": Skill(
        "flyer_image_generation", "Copy e immagine flyer (Requesty)", "1.0.0",
        "Headline, sottotitolo, CTA, prompt immagine e generazione REALE dell'immagine "
        "(POST /v1/images/generations, confermato su docs.requesty.ai) -- stessa connessione Requesty del testo.",
        capability="flyer_image", deliverable_type="flyer_project",
        allowed_roles=("creative-designer",),
        required_inputs=("brief",), required_facts=("ragione_sociale", "settore"), tools=("requesty",),
        requires_approval=True, cost_hint="pochi centesimi per il testo; immagine a tariffa Requesty (non stimata)",
        validation="domains/reel_semantic.py::semantic_validate_generic_content + domains/flyer.py::validate_flyer_content",
        fallback="Se la connessione Requesty non e' verificata: NOT_CONFIGURED, nessuna generazione.",
        base_mode=STATUS_REAL, primary_provider="requesty",
    ),

    # ==================== Skill REALE (Content Creator) ====================
    "content_creation_requesty": Skill(
        "content_creation_requesty", "Produzione contenuti multi-formato (Requesty)", "1.0.0",
        "Decide quale tipo di contenuto produrre (post, caption, email, landing, blog/SEO, script "
        "video/audio, brief immagine, comunicazioni commerciali...) in base a canale e fase di funnel "
        "(domains/content_creator/decision.py), genera il testo REALE via Requesty grounded sul Fact "
        "Ledger, valida struttura e claim, e collega l'asset multimediale reale (reel/flyer) quando il "
        "tipo lo richiede — mai un contenuto inventato, mai un asset dichiarato pronto senza conferma.",
        capability="content", deliverable_type="content_item",
        allowed_roles=("content-creator",),
        required_inputs=("objective", "channel"), required_facts=("ragione_sociale", "settore"),
        tools=("requesty",), requires_approval=True,
        cost_hint="pochi centesimi per generazione (token Requesty)",
        validation="domains/content_creator/validation.py::validate_content + "
                   "domains/reel_semantic.py::semantic_validate_generic_content",
        handoff_to=("reel_video_runway", "flyer_image_generation"),
        fallback="Connessione Requesty non verificata o modalità AI REALE non attiva: il contenuto resta "
                "in BOZZA, mai una generazione simulata spacciata per reale.",
        base_mode=STATUS_REAL, primary_provider="requesty",
    ),

    # ==================== Skill REALE (Analista performance) ====================
    "kpi_analysis_real": Skill(
        "kpi_analysis_real", "Analisi KPI reale", "1.0.0",
        "Calcola KPI reali (conversion_rate, lead_velocity, response_rate, appointment_rate, close_rate, "
        "funnel_drop_off, cost_per_lead/appointment/acquisition) da dati già presenti in ACTELYA (Lead "
        "Generation, Sales, Appointment Setter, Tool Execution Gateway), li interpreta con regole "
        "deterministiche e genera insight indirizzati agli agenti giusti — mai un dato inventato: un KPI "
        "senza dati sufficienti è sempre NON_DISPONIBILE.",
        capability="analytics", deliverable_type="analyst_report",
        allowed_roles=("analista-performance",),
        required_inputs=(), required_facts=(),
        tools=(), requires_approval=False, cost_hint="nessuno (solo letture, nessuna chiamata a pagamento)",
        validation="domains/analyst/metrics.py (ogni KPI con source/formula/reliability/missing_data espliciti)",
        handoff_to=("sales_pipeline_management", "content_creation_requesty", "lead_gen_plan_m2"),
        fallback="Meno di 5 osservazioni per un KPI: reliability BASSA o NON_DISPONIBILE, mai un valore stimato.",
        base_mode=STATUS_REAL,
    ),

    # ==================== Skill REALE (Sales Agent) ====================
    "sales_pipeline_management": Skill(
        "sales_pipeline_management", "Gestione pipeline commerciale", "1.0.0",
        "Analizza un lead pronto per l'handoff (Lead Generation), decide canale/timing/next-best-action, "
        "delega a Content Creator la scrittura del messaggio (mai una seconda chiamata Requesty qui), gestisce "
        "le risposte del prospect attraverso l'intera pipeline (new -> ... -> won/lost) e si collega in "
        "lettura all'esito reale di una prenotazione (Appointment Setter).",
        capability="sales", deliverable_type="sales_opportunity",
        allowed_roles=("sales-agent",),
        required_inputs=("lead_id", "lead_type"), required_facts=(),
        tools=(), requires_approval=False, cost_hint="nessuno (logica deterministica, nessuna chiamata a pagamento)",
        validation="domains/sales/strategy.py::decide_next_action (nessuna transizione di stage senza una regola esplicita)",
        handoff_to=("content_creation_requesty", "appointment_scheduling"),
        fallback="Nessun canale di contatto disponibile sul lead: l'opportunità resta con next_best_action "
                "ESCALATION_UMANA, mai un contatto tentato senza un canale reale.",
        # primary_provider intenzionalmente assente, stesso caso di
        # appointment_scheduling: nessun provider esterno da cui dipendere
        # (logica interamente deterministica) — skill_status() la mostra
        # comunque NOT_CONFIGURED in questo endpoint puramente informativo,
        # mai usato per bloccare il flusso reale (che non dipende da alcuna
        # connessione esterna).
        base_mode=STATUS_REAL,
    ),

    # ==================== Skill REALE (Appointment Setter) ====================
    "appointment_scheduling": Skill(
        "appointment_scheduling", "Proposta e prenotazione appuntamenti", "1.0.0",
        "Calcolo slot liberi da disponibilità+calendario reale (Google Calendar/Microsoft Graph/"
        "Calendly), proposta, approvazione, prenotazione reale, cancellazione/riprogrammazione.",
        capability="appointments", deliverable_type="appointment_setter_task",
        allowed_roles=("appointment-setter",),
        required_inputs=("lead_id", "connection_id"), required_facts=(),
        tools=("google_calendar", "microsoft_graph", "calendly"),
        requires_approval=True, cost_hint="nessuno (le API calendario dei provider supportati non sono a pagamento)",
        validation="domains/appointments/scheduling.py::compute_free_slots (nessuno slot oltre la disponibilità reale)",
        fallback="Connessione calendario non configurata/non verificata: proposta creata comunque, "
                "senza slot (mai uno slot inventato); prenotazione non disponibile finché non collegata.",
        # primary_provider intenzionalmente assente: a differenza di Requesty/Runway
        # (un solo provider possibile), qui l'org sceglie tra 3 provider diversi —
        # skill_status() la mostra sempre NOT_CONFIGURED in questo endpoint puramente
        # informativo (mai usato per bloccare il flusso reale, che legge sempre lo
        # stato vero della connessione da appointment_connections).
    ),

    # ==================== Skill PREDISPOSTA (nessun provider oggi, endpoint Requesty confermato ma non ancora collegato) ====================
    "voice_over_tts": Skill(
        "voice_over_tts", "Voice-over / TTS", "0.5.0-predisposta",
        "Sintesi vocale del voice_over_completo gia' scritto (endpoint Requesty POST /v1/audio/speech "
        "confermato su docs.requesty.ai, non ancora collegato in questa fase).",
        capability="audio_voiceover", deliverable_type=None,
        allowed_roles=("video-creator",), tools=("requesty",),
        fallback="Lo script del voice-over resta disponibile in testo (skill reel_text_requesty); l'audio resta NOT_CONFIGURED.",
        base_mode=STATUS_UNAVAILABLE, primary_provider="requesty",
    ),
    "avatar_video_heygen": Skill(
        "avatar_video_heygen", "Video avatar (HeyGen)", "0.0.0-predisposta",
        "Video con avatar parlante a partire da uno script.",
        capability="avatar_video", deliverable_type="avatar_video",
        allowed_roles=("video-creator",), tools=("heygen",),
        fallback="Nessuna implementazione: capability predisposta, mai eseguita.",
        base_mode=STATUS_UNAVAILABLE, primary_provider="heygen",
    ),
}


def get_skill(skill_id: str) -> Optional[Skill]:
    return SKILLS.get(skill_id)


def skills_for_capability(capability: str) -> tuple[Skill, ...]:
    return tuple(s for s in SKILLS.values() if s.capability == capability)


def skills_for_agent(frontend_agent_id: str) -> tuple[Skill, ...]:
    return tuple(s for s in SKILLS.values() if frontend_agent_id in s.allowed_roles)


async def skill_status(skill: Skill, org_id: str, db) -> str:
    """Stato REALE per una organizzazione: mai dichiarato staticamente per le
    skill base_mode=REAL. Verifica la STESSA fonte di verita' gia' usata da
    domains/reel.py (connessione verificata+attiva), nessuna seconda logica
    di provider readiness."""
    if skill.base_mode != STATUS_REAL:
        return skill.base_mode
    if not skill.primary_provider:
        return STATUS_NOT_CONFIGURED
    provider_collection = {
        "requesty": ("ai_connections", "requesty"),
        "runway": ("video_connections", "runway"),
    }.get(skill.primary_provider)
    if provider_collection is None:
        return STATUS_NOT_CONFIGURED  # image_provider/tts_provider/heygen: nessuna collezione esiste oggi
    collection, provider_type = provider_collection
    conn = await db[collection].find_one({
        "organization_id": org_id, "provider_type": provider_type, "verified": True, "active": True,
    })
    return STATUS_REAL if conn else STATUS_NOT_CONFIGURED


def skill_to_public_dict(skill: Skill) -> dict:
    return {
        "skill_id": skill.skill_id, "name": skill.name, "version": skill.version,
        "description": skill.description, "capability": skill.capability,
        "deliverable_type": skill.deliverable_type, "allowed_roles": list(skill.allowed_roles),
        "required_inputs": list(skill.required_inputs), "optional_inputs": list(skill.optional_inputs),
        "required_facts": list(skill.required_facts), "tools": list(skill.tools),
        "requires_approval": skill.requires_approval, "cost_hint": skill.cost_hint,
        "validation": skill.validation, "handoff_to": list(skill.handoff_to),
        "fallback": skill.fallback, "base_mode": skill.base_mode, "primary_provider": skill.primary_provider,
    }
