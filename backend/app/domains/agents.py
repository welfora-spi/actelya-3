"""Agent contracts registry + simulated provider that produces deliverables.
No real AI calls in milestone 1: the provider is clearly marked SIMULAZIONE."""

AGENT_REGISTRY = {
    "marketing_strategist": {
        "id": "marketing_strategist", "name": "Marketing Strategist",
        "mission": "Definire strategia e messaggi chiave per l'obiettivo commerciale.",
        "responsibilities": ["Analisi target", "Angolo di comunicazione", "Struttura del messaggio"],
        "forbidden": ["Invio reale", "Spesa pubblicitaria", "Uso di dati personali reali"],
        "data_access": ["profilo_aziendale", "obiettivo"], "tools": ["provider_ai_simulato"],
        "required_inputs": ["goal", "org_profile"],
        "output_schema": {"angolo": "str", "messaggi_chiave": "list"},
        "required_fields": ["angolo"], "success_criteria": ["Angolo definito"],
        "block_criteria": ["Obiettivo vuoto"], "handoff_criteria": ["Passa a Content & Social"],
        "token_limit": 1200, "budget": 0.02, "timeout": 60, "operative": True,
    },
    "content_social": {
        "id": "content_social", "name": "Content & Social",
        "mission": "Produrre il contenuto (es. email commerciale) secondo il contratto.",
        "responsibilities": ["Scrittura oggetto/corpo/CTA", "Tono di voce coerente"],
        "forbidden": ["Invio reale", "Inventare fatti aziendali, persone o consensi"],
        "data_access": ["profilo_aziendale", "strategia"], "tools": ["provider_ai_simulato"],
        "required_inputs": ["angolo", "org_profile"],
        "output_schema": {"oggetto": "str", "contenuto_completo": "str", "cta": "str"},
        "required_fields": ["oggetto", "contenuto_completo", "cta"],
        "success_criteria": ["Campi email non vuoti"], "block_criteria": ["Campi vuoti o soli placeholder"],
        "handoff_criteria": ["Passa a Compliance Reviewer"],
        "token_limit": 1500, "budget": 0.03, "timeout": 60, "operative": True,
    },
    "compliance_reviewer": {
        "id": "compliance_reviewer", "name": "Compliance Reviewer",
        "mission": "Aggiungere avvisi di compliance senza distruggere il deliverable.",
        "responsibilities": ["Verifica disclaimer", "Segnalazione rischi consenso/GDPR"],
        "forbidden": ["Cancellare un deliverable producibile", "Autorizzare invii"],
        "data_access": ["deliverable", "profilo_aziendale"], "tools": [],
        "required_inputs": ["deliverable"],
        "output_schema": {"warnings": "list"}, "required_fields": [],
        "success_criteria": ["Revisione completata"], "block_criteria": [],
        "handoff_criteria": ["Ritorna all'orchestratore"],
        "token_limit": 800, "budget": 0.01, "timeout": 60, "operative": True,
    },
    "advertising": {"id": "advertising", "name": "Advertising", "mission": "Pianificare campagne adv.",
                    "responsibilities": [], "forbidden": ["Spesa reale"], "data_access": [], "tools": [],
                    "required_inputs": [], "output_schema": {}, "required_fields": [],
                    "success_criteria": [], "block_criteria": [], "handoff_criteria": [],
                    "token_limit": 1200, "budget": 0.02, "timeout": 60, "operative": False},
    "lead_gen_sdr": {"id": "lead_gen_sdr", "name": "Lead Generation / SDR", "mission": "Generare e qualificare lead.",
                     "responsibilities": [], "forbidden": ["Contatto reale"], "data_access": [], "tools": [],
                     "required_inputs": [], "output_schema": {}, "required_fields": [],
                     "success_criteria": [], "block_criteria": [], "handoff_criteria": [],
                     "token_limit": 1200, "budget": 0.02, "timeout": 60, "operative": False},
    "appointment_setter": {"id": "appointment_setter", "name": "Appointment Setter", "mission": "Fissare appuntamenti.",
                           "responsibilities": [], "forbidden": ["Invio reale"], "data_access": [], "tools": [],
                           "required_inputs": [], "output_schema": {}, "required_fields": [],
                           "success_criteria": [], "block_criteria": [], "handoff_criteria": [],
                           "token_limit": 1000, "budget": 0.02, "timeout": 60, "operative": False},
    "nurturing": {"id": "nurturing", "name": "Nurturing", "mission": "Sequenze di nurturing.",
                  "responsibilities": [], "forbidden": ["Invio reale"], "data_access": [], "tools": [],
                  "required_inputs": [], "output_schema": {}, "required_fields": [],
                  "success_criteria": [], "block_criteria": [], "handoff_criteria": [],
                  "token_limit": 1000, "budget": 0.02, "timeout": 60, "operative": False},
    "analytics_performance": {"id": "analytics_performance", "name": "Analytics & Performance",
                              "mission": "Analisi KPI e performance.", "responsibilities": [], "forbidden": [],
                              "data_access": [], "tools": [], "required_inputs": [], "output_schema": {},
                              "required_fields": [], "success_criteria": [], "block_criteria": [],
                              "handoff_criteria": [], "token_limit": 1000, "budget": 0.02, "timeout": 60,
                              "operative": False},
    "tech_lead": {"id": "tech_lead", "name": "Tech Lead", "mission": "Supervisione tecnica e handoff.",
                  "responsibilities": [], "forbidden": [], "data_access": [], "tools": [],
                  "required_inputs": [], "output_schema": {}, "required_fields": [],
                  "success_criteria": [], "block_criteria": [], "handoff_criteria": [],
                  "token_limit": 800, "budget": 0.01, "timeout": 60, "operative": False},
    "auditor": {"id": "auditor", "name": "Auditor", "mission": "Verifica indipendente senza distruggere output.",
                "responsibilities": ["Controllo audit"], "forbidden": ["Cancellare deliverable"],
                "data_access": ["audit"], "tools": [], "required_inputs": [], "output_schema": {},
                "required_fields": [], "success_criteria": [], "block_criteria": [], "handoff_criteria": [],
                "token_limit": 800, "budget": 0.01, "timeout": 60, "operative": True},
}


def select_agents_for_goal(intent_type: str) -> list[str]:
    """Orchestrator: pick the agents needed. Milestone 1 = email production pipeline."""
    return ["marketing_strategist", "content_social", "compliance_reviewer", "auditor"]


def simulated_email_deliverable(goal_text: str, org_profile: dict) -> dict:
    """Produce a SIMULATED but structurally valid email. Uses placeholders for variable fields only."""
    brand = (org_profile or {}).get("nome_commerciale") or (org_profile or {}).get("ragione_sociale") or "PrevidenzaServe"
    settore = (org_profile or {}).get("settore") or "consulenza previdenziale"
    firma = (org_profile or {}).get("firma_email") or "[Firma]"
    oggetto = f"[Nome], una consulenza previdenziale su misura per te"
    contenuto = (
        f"Gentile [Nome],\n\n"
        f"sono un consulente di {brand}, realtà specializzata in {settore}. "
        f"Aiutiamo professionisti e aziende come [Azienda] a costruire un piano previdenziale "
        f"chiaro, ottimizzando contributi e riducendo i rischi fiscali.\n\n"
        f"In una breve call di 20 minuti possiamo analizzare la tua posizione attuale e "
        f"individuare margini di miglioramento concreti, senza alcun impegno.\n\n"
        f"Se ti fa piacere, puoi prenotare direttamente qui: [Link appuntamento].\n\n"
        f"Un cordiale saluto,\n{firma}"
    )
    cta = "Prenota la tua consulenza gratuita al link: [Link appuntamento]"
    return {
        "type": "email",
        "hook": oggetto,
        "oggetto": oggetto,
        "proposta": f"Consulenza previdenziale personalizzata di {brand}",
        "contenuto_completo": contenuto,
        "cta": cta,
        "assumptions": [
            "Dati aziendali fittizi/segnaposto usati come da richiesta.",
            "Nessun destinatario reale, nessun invio.",
        ],
        "mode": "SIMULAZIONE",
    }
