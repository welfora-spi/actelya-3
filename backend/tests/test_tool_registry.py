"""Professional Tool Registry — test diretti (nessuna rete, nessun Mongo per
la parte statica) più un livello di integrazione per lo stato calcolato per
organizzazione."""
import asyncio
import uuid

from motor.motor_asyncio import AsyncIOMotorClient

from app.brain.skills import STATUS_NOT_CONFIGURED, STATUS_REAL
from app.tools import registry as R
from app.tools.status import computed_status_for


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


def run(coro):
    return asyncio.run(coro)


def test_registro_valido_senza_eccezioni():
    R.validate_registry()  # non deve sollevare


def test_nessun_tool_id_duplicato():
    ids = [t.tool_id for t in R.TOOLS.values()]
    assert len(ids) == len(set(ids))


def test_ogni_tool_ha_almeno_un_agente_autorizzato():
    for t in R.TOOLS.values():
        assert t.allowed_agents, f"{t.tool_id} privo di agenti"


def test_tool_real_ha_sempre_code_complete():
    for t in R.TOOLS.values():
        if t.base_mode == STATUS_REAL:
            assert t.code_complete is True, f"{t.tool_id} e' REAL ma code_complete=False"


def test_tool_senza_codice_non_puo_dichiararsi_real():
    # __post_init__ deve degradare a NOT_CONFIGURED anche se qualcuno
    # provasse a costruire una voce incoerente.
    tool = R.ToolSpec("prova", "categoria", "Provider", ("resp-marketing",), (), (),
                      base_mode=STATUS_REAL, code_complete=False)
    assert tool.base_mode == STATUS_NOT_CONFIGURED


def test_tools_for_agent_filtra_correttamente():
    strumenti = R.tools_for_agent("appointment-setter")
    ids = {t.tool_id for t in strumenti}
    assert "google_calendar" in ids
    assert "calendly_booking" in ids
    assert "requesty_llm" not in ids  # non autorizzato per questo agente


def test_tools_for_category_ordinati_per_priorita():
    strumenti = R.tools_for_category("llm")
    assert [t.tool_id for t in strumenti][0] == "requesty_llm"  # priority=1


def test_catalogo_copre_tutti_i_23_punti_richiesti():
    # 22 categorie di provider (il punto 4 del catalogo, "Sicurezza degli
    # strumenti", e' un requisito trasversale per OGNI tool, non una
    # categoria di provider a se' — riflesso nei campi di ToolSpec
    # (supported_modes/idempotency_strategy/retry_policy/requires_approval),
    # non in una categoria dedicata).
    assert len(R.all_categories()) == 22
    assert len(R.TOOLS) == 63


def test_provider_gia_reali_sono_censiti_come_real():
    for tool_id in ("requesty_llm", "openai_llm", "anthropic_llm", "gemini_llm", "runway_video",
                    "meta_graph_social", "meta_insights", "google_calendar", "microsoft_calendar",
                    "actelya_audit_log", "local_document_parsers"):
        t = R.get_tool(tool_id)
        assert t is not None, tool_id
        assert t.base_mode == STATUS_REAL, f"{tool_id} dovrebbe essere REAL"


def test_provider_non_implementati_sono_non_configurato():
    for tool_id in ("tavily_search", "apollo_prospect", "hubspot_crm", "brevo_email_marketing",
                    "twilio_sms", "mcp_automation"):
        t = R.get_tool(tool_id)
        assert t is not None, tool_id
        assert t.base_mode == STATUS_NOT_CONFIGURED
        assert t.code_complete is False


def test_calendly_e_onestamente_parziale_non_real():
    """Correzione: solo verify() (Personal Access Token) e' reale in
    CalendlyAdapter — list_busy()/create_event()/cancel_event() sono
    tutti stub. Il registro non deve MAI dichiararlo REAL/code_complete."""
    t = R.get_tool("calendly_booking")
    assert t is not None
    assert t.code_complete is False
    assert t.base_mode == STATUS_NOT_CONFIGURED
    assert t.capabilities == ("account_verification",)  # mai 'read_availability' o 'booking'


# ==================== Stato calcolato per organizzazione (MongoDB reale) ====================
def test_status_tool_non_implementato_e_sempre_non_configurato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            tool = R.get_tool("apollo_prospect")
            stato = await computed_status_for(tool, org, db)
            assert stato == "NON_CONFIGURATO"
            return True
        finally:
            client.close()
    assert run(scenario())


def test_status_calendario_legge_lo_stato_reale_della_connessione():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.appointment_connections.insert_one({
                "id": "conn-1", "organization_id": org, "provider_type": "google_calendar",
                "status": "VERIFICATO",
            })
            tool = R.get_tool("google_calendar")
            stato = await computed_status_for(tool, org, db)
            assert stato == "VERIFICATO"
            return True
        finally:
            await db.appointment_connections.delete_many({"organization_id": org})
            client.close()
    assert run(scenario())


def test_status_calendario_senza_connessione_e_non_configurato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            tool = R.get_tool("microsoft_calendar")
            stato = await computed_status_for(tool, org, db)
            assert stato == "NON_CONFIGURATO"
            return True
        finally:
            client.close()
    assert run(scenario())


def test_status_llm_verificato_e_attivo_e_real():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.ai_connections.insert_one({
                "id": "aiconn-1", "organization_id": org, "provider_type": "openai",
                "verified": True, "active": True,
            })
            tool = R.get_tool("openai_llm")
            stato = await computed_status_for(tool, org, db)
            assert stato == "VERIFICATO"
            return True
        finally:
            await db.ai_connections.delete_many({"organization_id": org})
            client.close()
    assert run(scenario())


def test_status_llm_non_verificato_e_non_configurato():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.ai_connections.insert_one({
                "id": "aiconn-2", "organization_id": org, "provider_type": "openai",
                "verified": False, "active": True,
            })
            tool = R.get_tool("openai_llm")
            stato = await computed_status_for(tool, org, db)
            assert stato == "NON_CONFIGURATO"
            return True
        finally:
            await db.ai_connections.delete_many({"organization_id": org})
            client.close()
    assert run(scenario())


def test_status_tool_sempre_interno_e_real_senza_alcuna_connessione():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            tool = R.get_tool("local_document_parsers")
            stato = await computed_status_for(tool, org, db)
            assert stato == "VERIFICATO"
            return True
        finally:
            client.close()
    assert run(scenario())
