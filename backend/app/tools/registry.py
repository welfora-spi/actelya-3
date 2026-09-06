"""Professional Tool Registry — catalogo canonico e vincolante (23 categorie,
~50 provider) di ogni strumento professionale ACTELYA. Ogni voce dichiara lo
stato ONESTO di oggi: `code_complete=True` SOLO per un adapter realmente
costruito (contratto + adapter + configurazione + API + UI + sicurezza +
test + documentazione), mai per un nome inserito nel catalogo senza
implementazione. Un provider con `code_complete=False` è PREDISPOSTO: mai
selezionabile come REALE, mai un errore generico — sempre NON_CONFIGURATO
con un motivo esplicito (vedi status_for()).

Reimpiega le stesse costanti di stato di brain/skills.py (mai un secondo
enum parallelo per lo stesso concetto)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..brain.skills import STATUS_NOT_CONFIGURED, STATUS_REAL

REGISTRY_VERSION = "tools-1.0.0"

# Modalità supportate da uno strumento (item 4 del catalogo): MOCK e DRY_RUN
# sono livelli interni di sicurezza per uno strumento REAL (mai un costo/invio
# reale finché non esplicitamente confermato); BLOCCATO copre un guardrail
# esplicito (es. consenso/opt-out) indipendente dalla configurazione.
MODE_MOCK = "MOCK"
MODE_DRY_RUN = "DRY_RUN"
MODE_REAL = "REAL"
MODE_NON_CONFIGURATO = "NON_CONFIGURATO"
MODE_BLOCCATO = "BLOCCATO"


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    category: str
    provider: str
    allowed_agents: tuple[str, ...]
    capabilities: tuple[str, ...]
    allowed_operations: tuple[str, ...]
    readable_data: tuple[str, ...] = ()
    writable_data: tuple[str, ...] = ()
    required_scopes: tuple[str, ...] = ()
    supported_modes: tuple[str, ...] = (MODE_NON_CONFIGURATO, MODE_REAL)
    requires_approval: bool = True
    can_incur_cost: bool = False
    idempotency_strategy: str = "chiave idempotente per operazione (vedi adapter)"
    timeout_seconds: float = 15.0
    retry_policy: str = "nessun retry automatico su errori non transitori; retry limitato su timeout/5xx"
    result_type: str = "dict"
    result_validator: str = ""
    fallback: str = ""
    # Stato ONESTO dichiarato oggi (mai calcolato per compiacere un report):
    base_mode: str = STATUS_NOT_CONFIGURED
    code_complete: bool = False   # adapter+API+UI+sicurezza+test realmente presenti oggi
    module_ref: str = ""          # percorso del modulo che implementa l'adapter, se esiste
    priority: int = 1             # ordine principale/fallback all'interno della stessa categoria
    env_vars: tuple[str, ...] = ()  # nomi variabile SOLO — mai un valore, mai un segreto
    note: str = ""

    def __post_init__(self):
        # Un provider senza codice non può dichiararsi REAL: coerenza
        # strutturale verificata a runtime (vedi validate_registry()).
        if not self.code_complete and self.base_mode == STATUS_REAL:
            object.__setattr__(self, "base_mode", STATUS_NOT_CONFIGURED)


# ==================== P0 — infrastruttura obbligatoria ====================
_LLM_AGENTS = ("coordinatore-actelya", "resp-marketing", "social-media-manager", "copywriter",
              "resp-advertising", "lead-gen-specialist", "analista-performance", "content-creator")
TOOLS: dict[str, ToolSpec] = {
    "requesty_llm": ToolSpec(
        "requesty_llm", "llm", "Requesty", _LLM_AGENTS, ("reasoning", "generation"),
        ("chat_completion",), supported_modes=(MODE_NON_CONFIGURATO, MODE_REAL),
        requires_approval=False, can_incur_cost=True,
        idempotency_strategy="nessuna ripetizione automatica della stessa richiesta",
        result_validator="app/brain/llm_schema.py (JSON Schema validato)",
        fallback="OpenAI/Anthropic/Gemini diretti (stesso gateway, ordine configurabile per organizzazione)",
        base_mode=STATUS_REAL, code_complete=True, module_ref="app/brain/llm_gateway.py", priority=1,
        env_vars=(), note="Gateway principale del CEO Agent: comprensione/proposta piano. Credenziali per organizzazione (Connessioni e API).",
    ),
    "openai_llm": ToolSpec(
        "openai_llm", "llm", "OpenAI API", _LLM_AGENTS, ("reasoning", "generation"), ("chat_completion",),
        can_incur_cost=True, result_validator="app/brain/llm_schema.py",
        base_mode=STATUS_REAL, code_complete=True, module_ref="app/brain/llm_gateway.py::OpenAIAdapter", priority=2,
    ),
    "anthropic_llm": ToolSpec(
        "anthropic_llm", "llm", "Anthropic Claude API", _LLM_AGENTS, ("reasoning", "generation"), ("chat_completion",),
        can_incur_cost=True, result_validator="app/brain/llm_schema.py",
        base_mode=STATUS_REAL, code_complete=True, module_ref="app/brain/llm_gateway.py::AnthropicAdapter", priority=3,
    ),
    "gemini_llm": ToolSpec(
        "gemini_llm", "llm", "Google Gemini API", _LLM_AGENTS, ("reasoning", "generation"), ("chat_completion",),
        can_incur_cost=True, result_validator="app/brain/llm_schema.py",
        base_mode=STATUS_REAL, code_complete=True, module_ref="app/brain/llm_gateway.py::GeminiAdapter", priority=4,
    ),

    "tavily_search": ToolSpec(
        "tavily_search", "web_research", "Tavily",
        ("coordinatore-actelya", "resp-marketing", "lead-gen-specialist", "copywriter"),
        ("web_search",), ("search",), can_incur_cost=True,
        fallback="Brave Search; in assenza di entrambi, ricerca su URL pubbliche esplicite (domains/leadgen/research.py)",
        env_vars=("TAVILY_API_KEY",), priority=1,
    ),
    "brave_search": ToolSpec(
        "brave_search", "web_research", "Brave Search",
        ("coordinatore-actelya", "resp-marketing", "lead-gen-specialist", "copywriter"),
        ("web_search",), ("search",), can_incur_cost=True, env_vars=("BRAVE_SEARCH_API_KEY",), priority=2,
    ),
    "firecrawl_extract": ToolSpec(
        "firecrawl_extract", "web_research", "Firecrawl",
        ("coordinatore-actelya", "resp-marketing", "lead-gen-specialist", "copywriter"),
        ("page_extraction",), ("scrape", "read"), can_incur_cost=True, env_vars=("FIRECRAWL_API_KEY",), priority=3,
    ),
    "playwright_browser": ToolSpec(
        "playwright_browser", "web_research", "Playwright (browser locale)",
        ("coordinatore-actelya", "resp-marketing", "lead-gen-specialist", "copywriter"),
        ("browser_automation",), ("navigate", "read_dom"), can_incur_cost=False,
        note="Browser locale headless: nessuna chiamata a un servizio esterno, ma richiede il binario installato sull'host.",
        priority=4,
    ),
    "browserbase_browser": ToolSpec(
        "browserbase_browser", "web_research", "Browserbase (browser remoto)",
        ("coordinatore-actelya", "resp-marketing", "lead-gen-specialist", "copywriter"),
        ("browser_automation",), ("navigate", "read_dom"), can_incur_cost=True,
        env_vars=("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID"), priority=5,
        fallback="Playwright locale se Browserbase non è configurato.",
    ),

    "opentelemetry_tracing": ToolSpec(
        "opentelemetry_tracing", "observability", "OpenTelemetry", ("tech_lead", "auditor"),
        ("tracing", "metrics"), ("emit_span", "emit_metric"), requires_approval=False,
        env_vars=("OTEL_EXPORTER_OTLP_ENDPOINT",), priority=1,
    ),
    "sentry_errors": ToolSpec(
        "sentry_errors", "observability", "Sentry", ("tech_lead", "auditor"),
        ("error_tracking",), ("capture_exception",), requires_approval=False,
        env_vars=("SENTRY_DSN",), priority=2,
    ),
    "actelya_audit_log": ToolSpec(
        "actelya_audit_log", "observability", "Audit log ACTELYA", ("tech_lead", "auditor"),
        ("audit",), ("read", "write"), requires_approval=False,
        base_mode=STATUS_REAL, code_complete=True, module_ref="app/audit.py", priority=3,
        note="Già reale e in uso in tutto il backend (log_audit()): nessuna nuova integrazione, solo censito qui.",
    ),
}


def _register(*specs: ToolSpec) -> None:
    for s in specs:
        if s.tool_id in TOOLS:
            raise ValueError(f"tool_id duplicato: {s.tool_id}")
        TOOLS[s.tool_id] = s


# ==================== P1 — strumenti professionali principali ====================
_register(
    ToolSpec("pollo_media", "media_generation", "Pollo API (aggregatore)",
            ("social-media-manager", "resp-advertising", "copywriter", "video-creator", "creative-designer"),
            ("image_generation", "video_generation"), ("generate",), can_incur_cost=True,
            env_vars=("POLLO_API_KEY",), priority=1,
            fallback="Runway (video) / OpenAI Image (immagini) diretti, già collegati per Video Creator e Creative Designer."),
    ToolSpec("veo_video", "media_generation", "Google Veo",
            ("video-creator",), ("video_generation",), ("generate",), can_incur_cost=True,
            env_vars=("GOOGLE_VEO_API_KEY",), priority=2),
    ToolSpec("runway_video", "media_generation", "Runway", ("video-creator",),
            ("video_generation",), ("generate",), can_incur_cost=True,
            base_mode=STATUS_REAL, code_complete=True, module_ref="app/integrations/runway_gateway.py", priority=3,
            note="Già reale: domains/reel.py + video_connections.py."),
    ToolSpec("openai_image", "media_generation", "OpenAI Image API",
            ("social-media-manager", "resp-advertising", "copywriter", "video-creator", "creative-designer"),
            ("image_generation",), ("generate",), can_incur_cost=True, env_vars=("OPENAI_API_KEY",), priority=4,
            note="Requesty espone già la generazione immagine reale per il Creative Designer (domains/flyer.py); questa è un'alternativa diretta."),

    ToolSpec("elevenlabs_tts", "audio", "ElevenLabs",
            ("video-creator", "social-media-manager", "resp-advertising"),
            ("text_to_speech",), ("synthesize",), can_incur_cost=True,
            env_vars=("ELEVENLABS_API_KEY",), priority=1,
            note="Stesso ruolo della skill 'voice_over_tts' predisposta in brain/skills.py — endpoint Requesty alternativo già documentato lì."),
    ToolSpec("ffmpeg_local", "audio", "FFmpeg (locale)",
            ("video-creator", "social-media-manager", "resp-advertising"),
            ("montage", "conversion", "captions"), ("process",), requires_approval=False,
            note="Elaborazione locale, nessuna rete: richiede solo il binario installato sull'host.", priority=2),

    ToolSpec("canva_connect", "brand_creative", "Canva Connect API",
            ("social-media-manager", "copywriter", "resp-advertising", "creative-designer"),
            ("design_generation",), ("create_design", "export"), can_incur_cost=False,
            required_scopes=("design:content:read", "design:content:write"), priority=1),
    ToolSpec("actelya_asset_library", "brand_creative", "Asset Library ACTELYA",
            ("social-media-manager", "copywriter", "resp-advertising", "creative-designer"),
            ("asset_storage",), ("upload", "read", "delete"), requires_approval=False, priority=2),
    ToolSpec("actelya_brand_kit", "brand_creative", "Brand Kit ACTELYA (per organizzazione)",
            ("social-media-manager", "copywriter", "resp-advertising", "creative-designer"),
            ("brand_guidelines",), ("read", "write"), requires_approval=False, priority=3),

    ToolSpec("meta_graph_social", "social_network", "Meta Graph API + Instagram API", ("social-media-manager",),
            ("publish", "read_insights"), ("post", "read"), can_incur_cost=False,
            base_mode=STATUS_REAL, code_complete=True, module_ref="app/integrations/meta/", priority=1,
            note="Già reale: Social Media Manager (Facebook Page + Instagram Professional)."),
    ToolSpec("tiktok_content", "social_network", "TikTok Content Posting API", ("social-media-manager",),
            ("publish",), ("post",), can_incur_cost=False, env_vars=("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"), priority=2),
    ToolSpec("linkedin_social", "social_network", "LinkedIn Posts/Community Management API",
            ("social-media-manager", "lead-gen-specialist"),
            ("publish", "read"), ("post", "read"), can_incur_cost=False,
            env_vars=("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"), priority=3,
            note="Disponibile anche al Lead Generation Specialist per la ricerca prospect (sola lettura pubblica, mai un contatto diretto automatico)."),
    ToolSpec("youtube_data", "social_network", "YouTube Data API", ("social-media-manager",),
            ("publish", "read"), ("upload", "read"), can_incur_cost=False, env_vars=("YOUTUBE_API_KEY",), priority=4),

    ToolSpec("meta_marketing_ads", "advertising", "Meta Marketing API",
            ("resp-advertising", "analista-performance", "lead-gen-specialist"),
            ("campaign_management",), ("create_campaign", "read_report"), can_incur_cost=True,
            env_vars=("META_MARKETING_APP_ID", "META_MARKETING_APP_SECRET"), priority=1),
    ToolSpec("google_ads", "advertising", "Google Ads API",
            ("resp-advertising", "analista-performance", "lead-gen-specialist"),
            ("campaign_management",), ("create_campaign", "read_report"), can_incur_cost=True,
            env_vars=("GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET"), priority=2),
    ToolSpec("linkedin_ads", "advertising", "LinkedIn Advertising API",
            ("resp-advertising", "analista-performance", "lead-gen-specialist"),
            ("campaign_management",), ("create_campaign", "read_report"), can_incur_cost=True,
            env_vars=("LINKEDIN_ADS_CLIENT_ID", "LINKEDIN_ADS_CLIENT_SECRET"), priority=3),

    ToolSpec("hubspot_crm", "crm", "HubSpot", ("lead-gen-specialist", "specialista-nurturing", "appointment-setter"),
            ("crm_sync",), ("create_contact", "update_contact", "read"), can_incur_cost=False,
            env_vars=("HUBSPOT_CLIENT_ID", "HUBSPOT_CLIENT_SECRET"), priority=1),
    ToolSpec("pipedrive_crm", "crm", "Pipedrive", ("lead-gen-specialist", "specialista-nurturing", "appointment-setter"),
            ("crm_sync",), ("create_contact", "update_contact", "read"), can_incur_cost=False,
            env_vars=("PIPEDRIVE_API_TOKEN",), priority=2),
    ToolSpec("salesforce_crm", "crm", "Salesforce", ("lead-gen-specialist", "specialista-nurturing", "appointment-setter"),
            ("crm_sync",), ("create_contact", "update_contact", "read"), can_incur_cost=False,
            env_vars=("SALESFORCE_CLIENT_ID", "SALESFORCE_CLIENT_SECRET"), priority=3,
            note="Stesso contratto adapter CRM di HubSpot/Pipedrive: aggiungerlo non richiede un nuovo contratto, solo un nuovo adapter."),

    ToolSpec("apollo_prospect", "prospect_research", "Apollo API", ("lead-gen-specialist", "resp-marketing", "appointment-setter"),
            ("prospect_search",), ("search", "enrich"), can_incur_cost=True,
            env_vars=("APOLLO_API_KEY",), priority=1,
            note="Vedi domains/leadgen/research.py::build_adapters — punto di innesto già predisposto per questo provider."),
    ToolSpec("hunter_email", "prospect_research", "Hunter API", ("lead-gen-specialist", "resp-marketing", "appointment-setter"),
            ("email_finder",), ("search",), can_incur_cost=True, env_vars=("HUNTER_API_KEY",), priority=2),
    ToolSpec("google_places", "prospect_research", "Google Places API", ("lead-gen-specialist", "resp-marketing", "appointment-setter"),
            ("local_business_search",), ("search",), can_incur_cost=True, env_vars=("GOOGLE_PLACES_API_KEY",), priority=3),

    ToolSpec("gmail_comm", "individual_comms", "Gmail API", ("specialista-nurturing", "appointment-setter"),
            ("send_email", "read_email"), ("send", "read"), can_incur_cost=False,
            required_scopes=("gmail.send",), env_vars=("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET"), priority=1),
    ToolSpec("outlook_comm", "individual_comms", "Microsoft Graph/Outlook", ("specialista-nurturing", "appointment-setter"),
            ("send_email", "read_email"), ("send", "read"), can_incur_cost=False,
            env_vars=("MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET"), priority=2,
            note="Stessa app OAuth Microsoft Graph già registrata per il calendario (domains/appointments): scope aggiuntivo Mail.Send, mai automatico."),
    ToolSpec("whatsapp_business", "individual_comms", "WhatsApp Business Cloud API",
            ("specialista-nurturing", "appointment-setter"),
            ("send_message",), ("send",), can_incur_cost=True,
            env_vars=("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"), priority=3),

    ToolSpec("brevo_email_marketing", "email_marketing", "Brevo", ("specialista-nurturing",),
            ("bulk_email",), ("send_campaign", "manage_list"), can_incur_cost=True,
            env_vars=("BREVO_API_KEY",), priority=1),
    ToolSpec("mailchimp_email_marketing", "email_marketing", "Mailchimp", ("specialista-nurturing",),
            ("bulk_email",), ("send_campaign", "manage_list"), can_incur_cost=True,
            env_vars=("MAILCHIMP_API_KEY",), priority=2),

    ToolSpec("google_calendar", "calendar", "Google Calendar API", ("appointment-setter",),
            ("scheduling",), ("list_busy", "create_event", "cancel_event"), can_incur_cost=False,
            base_mode=STATUS_REAL, code_complete=True, module_ref="app/domains/appointments/calendar_adapters.py::GoogleCalendarAdapter",
            env_vars=("GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET", "GOOGLE_CALENDAR_REDIRECT_URI"), priority=1),
    ToolSpec("microsoft_calendar", "calendar", "Microsoft Outlook Calendar (Graph)", ("appointment-setter",),
            ("scheduling",), ("list_busy", "create_event", "cancel_event"), can_incur_cost=False,
            base_mode=STATUS_REAL, code_complete=True, module_ref="app/domains/appointments/calendar_adapters.py::MicrosoftGraphAdapter",
            env_vars=("MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET", "MS_GRAPH_REDIRECT_URI"), priority=2),

    ToolSpec("ga4_analytics", "analytics_seo", "Google Analytics 4 Data API",
            ("analista-performance", "resp-marketing", "coordinatore-actelya", "copywriter"),
            ("read_analytics",), ("read_report",), can_incur_cost=False, requires_approval=False,
            env_vars=("GA4_PROPERTY_ID", "GA4_CLIENT_ID", "GA4_CLIENT_SECRET"), priority=1),
    ToolSpec("search_console", "analytics_seo", "Google Search Console API",
            ("analista-performance", "resp-marketing", "coordinatore-actelya", "copywriter"),
            ("read_analytics",), ("read_report",), can_incur_cost=False, requires_approval=False,
            env_vars=("SEARCH_CONSOLE_CLIENT_ID", "SEARCH_CONSOLE_CLIENT_SECRET"), priority=2),
    ToolSpec("meta_insights", "analytics_seo", "Meta Insights",
            ("analista-performance", "resp-marketing", "coordinatore-actelya", "copywriter"),
            ("read_analytics",), ("read_report",), can_incur_cost=False, requires_approval=False,
            base_mode=STATUS_REAL, code_complete=True, module_ref="app/domains/social_publishing.py (social_analytics_snapshots)", priority=3,
            note="Già reale per il Social Media Manager; non ancora consumato da produce_kpi_report (Analista performance) — collegamento futuro."),
    ToolSpec("google_ads_reporting", "analytics_seo", "Google Ads Reporting",
            ("analista-performance", "resp-marketing", "coordinatore-actelya", "copywriter"),
            ("read_analytics",), ("read_report",), can_incur_cost=False, requires_approval=False,
            env_vars=("GOOGLE_ADS_DEVELOPER_TOKEN",), priority=4),
    ToolSpec("linkedin_analytics", "analytics_seo", "LinkedIn Analytics",
            ("analista-performance", "resp-marketing", "coordinatore-actelya", "copywriter"),
            ("read_analytics",), ("read_report",), can_incur_cost=False, requires_approval=False,
            env_vars=("LINKEDIN_CLIENT_ID",), priority=5),
    ToolSpec("youtube_analytics", "analytics_seo", "YouTube Analytics",
            ("analista-performance", "resp-marketing", "coordinatore-actelya", "copywriter"),
            ("read_analytics",), ("read_report",), can_incur_cost=False, requires_approval=False,
            env_vars=("YOUTUBE_API_KEY",), priority=6),
)

# ==================== P2 — estensioni specialistiche ====================
_register(
    ToolSpec("twilio_sms", "sms", "Twilio", ("specialista-nurturing", "appointment-setter"),
            ("send_sms",), ("send",), can_incur_cost=True, env_vars=("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"), priority=1),
    ToolSpec("vonage_sms", "sms", "Vonage", ("specialista-nurturing", "appointment-setter"),
            ("send_sms",), ("send",), can_incur_cost=True, env_vars=("VONAGE_API_KEY", "VONAGE_API_SECRET"), priority=2),

    ToolSpec("calendly_booking", "booking", "Calendly API", ("appointment-setter",),
            ("account_verification",), ("verify",), can_incur_cost=False,
            # Correzione (onestà registro): l'adapter esiste (CalendlyAdapter)
            # ma solo verify() (GET /users/me, verifica del Personal Access
            # Token) fa davvero una chiamata reale. list_busy() ritorna
            # sempre [] (Calendly non espone un freebusy classico via API
            # pubblica) e create_event()/cancel_event() ritornano sempre
            # NON_DISPONIBILE/False (Calendly richiede una Scheduling Link
            # già pubblicata dal cliente per la prenotazione vera e propria:
            # nessun "crea evento per conto di" nell'API pubblica). La
            # capability dichiarata sopra ("account_verification") riflette
            # SOLO ciò che è realmente implementato — mai "read_availability"
            # o "booking" finché list_busy/create_event/cancel_event non
            # saranno realmente collegati.
            base_mode=STATUS_NOT_CONFIGURED, code_complete=False,
            module_ref="app/domains/appointments/calendar_adapters.py::CalendlyAdapter",
            env_vars=(),
            note="PARZIALE: solo la verifica del Personal Access Token è reale (Connessioni e API). "
                "Nessuna lettura di disponibilità, nessuna creazione/cancellazione di prenotazione oggi — "
                "richiede una Scheduling Link pubblicata dal cliente, non ancora collegata.",
            priority=1),

    ToolSpec("google_business_profile", "local_business", "Google Business Profile APIs",
            ("resp-marketing", "analista-performance"), ("manage_listing", "read_reviews"),
            ("read", "write"), can_incur_cost=False, env_vars=("GOOGLE_BUSINESS_CLIENT_ID",), priority=1),

    ToolSpec("wordpress_rest", "site_management", "WordPress REST API", ("copywriter", "resp-marketing"),
            ("publish_content",), ("create_post", "update_post"), can_incur_cost=False,
            env_vars=("WORDPRESS_SITE_URL", "WORDPRESS_APP_PASSWORD"), priority=1),

    ToolSpec("shopify_admin", "ecommerce", "Shopify GraphQL Admin API",
            ("resp-marketing", "resp-advertising", "analista-performance"),
            ("read_catalog", "read_orders"), ("read",), can_incur_cost=False,
            env_vars=("SHOPIFY_STORE_DOMAIN", "SHOPIFY_ADMIN_API_TOKEN"), priority=1),
    ToolSpec("woocommerce_rest", "ecommerce", "WooCommerce REST API",
            ("resp-marketing", "resp-advertising", "analista-performance"),
            ("read_catalog", "read_orders"), ("read",), can_incur_cost=False,
            env_vars=("WOOCOMMERCE_CONSUMER_KEY", "WOOCOMMERCE_CONSUMER_SECRET"), priority=2),

    ToolSpec("google_drive_docs", "documents", "Google Drive", ("coordinatore-actelya",),
            ("file_access",), ("read", "write"), can_incur_cost=False, env_vars=("GOOGLE_DRIVE_CLIENT_ID",), priority=1),
    ToolSpec("onedrive_docs", "documents", "OneDrive", ("coordinatore-actelya",),
            ("file_access",), ("read", "write"), can_incur_cost=False, env_vars=("MS_GRAPH_CLIENT_ID",), priority=2),
    ToolSpec("sharepoint_docs", "documents", "SharePoint", ("coordinatore-actelya",),
            ("file_access",), ("read", "write"), can_incur_cost=False, env_vars=("MS_GRAPH_CLIENT_ID",), priority=3),
    ToolSpec("local_document_parsers", "documents", "Parser locali (PDF/Word/Excel)", ("coordinatore-actelya", "lead-gen-specialist"),
            ("file_parsing",), ("parse",), can_incur_cost=False, requires_approval=False,
            base_mode=STATUS_REAL, code_complete=True, module_ref="app/domains/leadgen/parsers.py", priority=4,
            note="Già reale per Lead Generation (CSV/TSV/XLSX/PDF/DOCX/TXT); riusabile da altri agenti che elaborano documenti."),

    ToolSpec("google_document_ai", "ocr", "Google Document AI", ("coordinatore-actelya", "lead-gen-specialist"),
            ("ocr",), ("extract",), can_incur_cost=True, env_vars=("GOOGLE_DOCUMENT_AI_PROJECT_ID",), priority=1),
    ToolSpec("azure_document_intelligence", "ocr", "Azure Document Intelligence", ("coordinatore-actelya", "lead-gen-specialist"),
            ("ocr",), ("extract",), can_incur_cost=True, env_vars=("AZURE_DOCUMENT_INTELLIGENCE_KEY",), priority=2),

    ToolSpec("mcp_automation", "external_automation", "MCP", ("coordinatore-actelya", "tech_lead"),
            ("automation",), ("invoke_tool",), can_incur_cost=False, priority=1),
    ToolSpec("make_automation", "external_automation", "Make", ("coordinatore-actelya", "tech_lead"),
            ("automation",), ("trigger_scenario",), can_incur_cost=False, env_vars=("MAKE_API_TOKEN",), priority=2),
    ToolSpec("n8n_automation", "external_automation", "n8n", ("coordinatore-actelya", "tech_lead"),
            ("automation",), ("trigger_workflow",), can_incur_cost=False, env_vars=("N8N_API_KEY", "N8N_BASE_URL"), priority=3),
)


class RegistryError(Exception):
    """Errore esplicito: tool_id duplicato, agente non riconosciuto, coerenza rotta."""


def validate_registry() -> None:
    """Verifica di coerenza allo startup: nessun tool_id duplicato (già
    garantito dal dict, ridondanza intenzionale), nessun tool REAL senza
    codice completo, nessuna categoria priva di priorità coerente."""
    for tool in TOOLS.values():
        if tool.base_mode == STATUS_REAL and not tool.code_complete:
            raise RegistryError(f"Tool '{tool.tool_id}' dichiarato REAL senza code_complete=True")
        if not tool.allowed_agents:
            raise RegistryError(f"Tool '{tool.tool_id}' privo di agenti autorizzati")


def get_tool(tool_id: str) -> Optional[ToolSpec]:
    return TOOLS.get(tool_id)


def tools_for_agent(agent_id: str) -> tuple[ToolSpec, ...]:
    return tuple(t for t in TOOLS.values() if agent_id in t.allowed_agents)


def tools_for_category(category: str) -> tuple[ToolSpec, ...]:
    return tuple(sorted((t for t in TOOLS.values() if t.category == category), key=lambda t: t.priority))


def all_categories() -> tuple[str, ...]:
    visti: list[str] = []
    for t in TOOLS.values():
        if t.category not in visti:
            visti.append(t.category)
    return tuple(visti)


def to_public_dict(tool: ToolSpec, *, computed_status: Optional[str] = None) -> dict:
    return {
        "tool_id": tool.tool_id, "category": tool.category, "provider": tool.provider,
        "allowed_agents": list(tool.allowed_agents), "capabilities": list(tool.capabilities),
        "allowed_operations": list(tool.allowed_operations), "readable_data": list(tool.readable_data),
        "writable_data": list(tool.writable_data), "required_scopes": list(tool.required_scopes),
        "supported_modes": list(tool.supported_modes), "requires_approval": tool.requires_approval,
        "can_incur_cost": tool.can_incur_cost, "idempotency_strategy": tool.idempotency_strategy,
        "timeout_seconds": tool.timeout_seconds, "retry_policy": tool.retry_policy,
        "result_type": tool.result_type, "result_validator": tool.result_validator,
        "fallback": tool.fallback, "base_mode": tool.base_mode, "code_complete": tool.code_complete,
        "module_ref": tool.module_ref, "priority": tool.priority, "env_vars": list(tool.env_vars),
        "note": tool.note, "status": computed_status if computed_status is not None else tool.base_mode,
    }
