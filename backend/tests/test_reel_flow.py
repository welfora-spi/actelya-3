"""Flusso reale (Mongo locale, MAI rete reale) dell'agente reel: usa il Fact
Ledger automaticamente, blocca la generazione finche' non sono soddisfatte
TUTTE le condizioni (AI REALE attiva, connessione Requesty verificata, budget,
conferma esplicita), distingue 'progetto pronto' da 'video pronto' (sempre
False), gestisce l'esito incerto senza permettere un nuovo tentativo silenzioso.
Il confine esterno (chiamata a Requesty) e' l'UNICO punto mockato. Un client
Mongo fresco per scenario (stesso pattern di tests/test_m2_block4.py): evita
il crash 'Event loop is closed' di Motor su piu' asyncio.run() nella sessione."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME
from app.domains import reel
from app.models import base_record
from app.integrations.requesty_gateway import RisultatoGenerazioneRequesty, RequestyErroreSanificato


def run(coro):
    return asyncio.run(coro)


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client[DB_NAME]


def _admin(org_id, tag="a"):
    return {"id": f"user-reel-admin-{tag}", "email": f"admin-reel-{tag}@test.local", "role": "ADMIN", "organization_id": org_id}


async def _seed_org(fresh_db, org_id, *, ragione_sociale="Acme S.r.l.", settore="software B2B"):
    org = base_record(org_id, "system")
    org.update({"id": org_id, "ragione_sociale": ragione_sociale, "nome_commerciale": ragione_sociale,
               "settore": settore, "sito_web": "https://acme.example"})
    await fresh_db.organizations.insert_one(org)


async def _seed_ready(fresh_db, org_id, *, model="anthropic/claude-sonnet-4-5"):
    await fresh_db.settings.update_one({"id": org_id}, {"$set": {"id": org_id, "ai_real_mode": True}}, upsert=True)
    await fresh_db.budgets.update_one({"id": org_id}, {"$set": {"id": org_id, "general_limit": 5.0, "daily_limit": 1.0}}, upsert=True)
    conn = base_record(org_id, "system")
    conn.update({"id": f"aiconn-{uuid.uuid4().hex[:8]}", "name": "Requesty", "provider_type": "requesty", "base_url": "",
                "logical_model": "claude-sonnet-5", "effective_model": model, "timeout": 60,
                "max_tokens": 1800, "max_budget_per_task": 1.0, "daily_budget": 10.0, "active": True,
                "priority": 1, "last_test_at": None, "last_test_result": "OK_REALE",
                "provider_returned_model": model, "verified": True, "api_key_encrypted": None, "api_key_masked": ""})
    await fresh_db.ai_connections.insert_one(conn)


def _fake_result(content_json: str, troncata=False):
    return RisultatoGenerazioneRequesty(
        testo=content_json, modello_effettivo="anthropic/claude-sonnet-4-5",
        latenza_ms=300, input_tokens=400, output_tokens=350, troncata=troncata,
    )


VALID_CONTENT = """{
  "concept": "Un reel che mostra come Acme S.r.l. risolve un problema quotidiano del team marketing.",
  "hook": "Perdi ore ogni settimana su questo?",
  "sceneggiatura": "Scena 1: apertura sul problema del cliente. Scena 2: introduzione del prodotto Acme. Scena 3: risultato e invito all'azione finale.",
  "storyboard": [
    {"numero_scena": 1, "descrizione_visiva": "Persona frustrata davanti al computer", "durata_secondi": 4, "testo_a_schermo": "Il problema", "voice_over": "Conosci questa scena?"},
    {"numero_scena": 2, "descrizione_visiva": "Prodotto Acme in uso, interfaccia semplice", "durata_secondi": 5, "testo_a_schermo": "La soluzione Acme", "voice_over": "Ecco come lo risolviamo con Acme."}
  ],
  "voice_over_completo": "Conosci questa scena? Ecco come lo risolviamo con Acme, in modo semplice e veloce.",
  "testi_a_schermo": ["Il problema", "La soluzione Acme"],
  "hashtags": ["#Acme", "#novita"],
  "caption": "Basta perdere tempo ogni settimana. Scopri Acme.",
  "cta": "Scopri di più",
  "durata_secondi": 20,
  "formato": "9:16",
  "prompt_video_generativo": "Vertical 9:16 video, scene 1: frustrated person at desk, scene 2: Acme product in use, clean modern corporate style."
}"""


async def _scenario(fn, *, orgs=1):
    client, fresh_db = _db()
    org_ids = [f"org-test-reel-{uuid.uuid4().hex[:8]}" for _ in range(orgs)]
    import app.domains.reel as reel_mod
    import app.audit as audit_mod
    old_db, old_audit_db = reel_mod.db, audit_mod.db
    reel_mod.db = fresh_db
    audit_mod.db = fresh_db
    try:
        return await fn(fresh_db, *org_ids)
    finally:
        reel_mod.db = old_db
        audit_mod.db = old_audit_db
        for org_id in org_ids:
            for coll in ("organizations", "facts", "settings", "budgets", "ai_connections",
                        "reel_projects", "audit_logs", "executions", "reel_content_versions",
                        "social_memory_entries"):
                await fresh_db[coll].delete_many({"organization_id": org_id} if coll != "organizations" else {"id": org_id})
        client.close()


def test_creazione_blocca_se_fact_ledger_incompleto():
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id, ragione_sociale="", settore="")
        with pytest.raises(Exception) as ei:
            await reel.create_project(reel.NewReelBody(brief=""), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 400

    run(_scenario(scenario))


def test_creazione_usa_fact_ledger_senza_richiedere_di_nuovo_i_dati():
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        p = await reel.create_project(reel.NewReelBody(brief="lancio nuova funzione"), _admin(org_id))
        assert p["status"] == "BOZZA"
        assert p["fact_snapshot"]["ragione_sociale"] == "Acme S.r.l."
        assert p["fact_snapshot"]["settore"] == "software B2B"

    run(_scenario(scenario))


def test_generate_bloccato_senza_ai_real_mode():
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        p = await reel.create_project(reel.NewReelBody(), _admin(org_id))
        with pytest.raises(Exception) as ei:
            await reel.generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 409
        assert "REALE" in ei.value.detail

    run(_scenario(scenario))


def test_generate_richiede_conferma_esplicita():
    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_ready(fresh_db, org_id)
        p = await reel.create_project(reel.NewReelBody(), _admin(org_id))
        with pytest.raises(Exception) as ei:
            await reel.generate(p["id"], reel.ConfirmBody(confirm=False), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 400

    run(_scenario(scenario))


def test_generate_ok_progetto_pronto_video_mai_pronto(monkeypatch):
    monkeypatch.setattr(reel.requesty_gateway, "genera_json", lambda **kw: _fake_result(VALID_CONTENT))

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_ready(fresh_db, org_id)
        p = await reel.create_project(reel.NewReelBody(brief="lancio nuova funzione"), _admin(org_id))
        result = await reel.generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))

        assert result["status"] == "PROGETTO_PRONTO"
        assert result["progetto_pronto"] is True
        assert result["video_pronto"] is False
        assert result["video_status"] == "NON_RICHIESTO"
        assert result["content"]["hook"].startswith("Perdi ore")
        assert result["generazione"]["input_tokens"] == 400

    run(_scenario(scenario))


def test_richiedi_modifica_poi_rigenera_conserva_versione_precedente(monkeypatch):
    """Item 10 (revision loop): la generazione precedente NON viene mai persa
    quando l'utente chiede una modifica e si rigenera -- resta consultabile
    in GET .../content/versions, il contenuto corrente resta SOLO quello
    piu' recente (mai una confusione tra le due)."""
    v2 = VALID_CONTENT.replace("Perdi ore ogni settimana su questo?", "Nuovo hook dopo la modifica richiesta.")
    calls = {"n": 0}

    def _genera(**kw):
        calls["n"] += 1
        return _fake_result(VALID_CONTENT if calls["n"] == 1 else v2)

    monkeypatch.setattr(reel.requesty_gateway, "genera_json", _genera)

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_ready(fresh_db, org_id)
        p = await reel.create_project(reel.NewReelBody(brief="lancio nuova funzione"), _admin(org_id))
        r1 = await reel.generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        assert r1["content"]["hook"].startswith("Perdi ore")

        # Nessuna versione ancora: solo la generazione corrente esiste.
        versions_before = await reel.list_content_versions(p["id"], _admin(org_id))
        assert versions_before == []

        await reel.richiedi_modifica(p["id"], reel.RichiediModificaBody(nota="Rendilo piu' diretto"), _admin(org_id))
        r2 = await reel.generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        assert r2["content"]["hook"] == "Nuovo hook dopo la modifica richiesta."

        versions_after = await reel.list_content_versions(p["id"], _admin(org_id))
        assert len(versions_after) == 1
        assert versions_after[0]["version"] == 1
        assert versions_after[0]["content"]["hook"].startswith("Perdi ore")
        assert versions_after[0]["nota_revisione_che_ha_portato_alla_modifica"] == "Rendilo piu' diretto"

        # Il progetto corrente mostra SOLO l'ultima versione, mai una mescolanza.
        p2 = await reel.get_project(p["id"], _admin(org_id))
        assert p2["content"]["hook"] == "Nuovo hook dopo la modifica richiesta."

    run(_scenario(scenario))


def test_memoria_pregressa_viene_iniettata_nel_prompt(monkeypatch):
    """Item 13/17: una preferenza/pattern gia' registrato per l'organizzazione
    (da un progetto precedente approvato) deve comparire nel prompt della
    generazione SUCCESSIVA, sempre etichettato come orientativo -- mai una
    fonte di fatti aziendali, mai un valore che sovrascrive il Fact Ledger."""
    catturato = {}

    def _genera(**kw):
        catturato.update(kw)
        return _fake_result(VALID_CONTENT)

    monkeypatch.setattr(reel.requesty_gateway, "genera_json", _genera)

    async def scenario(fresh_db, org_id):
        from app.domains import social_memory
        await _seed_org(fresh_db, org_id)
        await _seed_ready(fresh_db, org_id)
        await social_memory.record_entry(
            fresh_db, org_id, "revision_pattern", summary="chiesto piu' volte un tono piu' diretto",
        )
        p = await reel.create_project(reel.NewReelBody(brief="lancio nuova funzione"), _admin(org_id))
        await reel.generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))

        assert "orientativi" in catturato["messaggio_utente"]
        assert "chiesto piu' volte un tono piu' diretto" in catturato["messaggio_utente"]

    run(_scenario(scenario))


def test_generate_contenuto_non_valido_blocca_progetto(monkeypatch):
    monkeypatch.setattr(reel.requesty_gateway, "genera_json", lambda **kw: _fake_result('{"concept": ""}'))

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_ready(fresh_db, org_id)
        p = await reel.create_project(reel.NewReelBody(), _admin(org_id))
        result = await reel.generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        assert result["status"] == "BLOCCATO"
        assert result["progetto_pronto"] is False
        assert result["video_pronto"] is False

    run(_scenario(scenario))


def test_generate_esito_incerto_blocca_nuovi_tentativi(monkeypatch):
    def boom(**kw):
        raise RequestyErroreSanificato("esito_incerto", "Richiesta inviata, risposta mai arrivata.")

    monkeypatch.setattr(reel.requesty_gateway, "genera_json", boom)

    async def scenario(fresh_db, org_id):
        await _seed_org(fresh_db, org_id)
        await _seed_ready(fresh_db, org_id)
        p = await reel.create_project(reel.NewReelBody(), _admin(org_id))

        with pytest.raises(Exception) as ei:
            await reel.generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        assert getattr(ei.value, "status_code", None) == 502

        stato = await fresh_db.reel_projects.find_one({"id": p["id"]}, {"_id": 0})
        assert stato["status"] == "ESITO_INCERTO"

        with pytest.raises(Exception) as ei2:
            await reel.generate(p["id"], reel.ConfirmBody(confirm=True), _admin(org_id))
        assert getattr(ei2.value, "status_code", None) == 409

        risolto = await reel.risolvi_esito_incerto(
            p["id"], reel.ResolveUncertainBody(nota="verificato manualmente: nessun addebito"), _admin(org_id))
        assert risolto["status"] == "BLOCCATO"

    run(_scenario(scenario))


def test_isolamento_tenant():
    async def scenario(fresh_db, org_a, org_b):
        await _seed_org(fresh_db, org_a)
        await _seed_org(fresh_db, org_b)
        p = await reel.create_project(reel.NewReelBody(), _admin(org_a, "a"))
        with pytest.raises(Exception) as ei:
            await reel.get_project(p["id"], _admin(org_b, "b"))
        assert getattr(ei.value, "status_code", None) == 404

    run(_scenario(scenario, orgs=2))
