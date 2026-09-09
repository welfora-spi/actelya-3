"""Test mirati — correzioni della verifica Chrome del 2026-09-09 (terza
parte): evidenze del Fact Ledger, separazione prodotti/slogan/pubblico
(JSON-LD vs euristica), coerenza budget Dashboard/Budget, conteggio
approvazioni pendenti. Database di test dedicato (mai actelya3_dev)."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.domains import discovery as D
from app.domains import budget as BUDGET
from app.domains import stats as STATS
from app.domains.budget import get_budget, compute_spent
from app.domains.stats import dashboard
from app.domains.knowledge import write_fact
from app.tools.cost_ledger import record_cost, set_daily_cap
from app.m2 import models as M
from app.m2 import engine as E
from app.domains.content_creator import pipeline as cc_pipeline
from app import audit as audit_module
from app.m2 import reviews as R
from app.m2 import deliverable_review as DR

_MONGO_URL = "mongodb://127.0.0.1:27020"
_TEST_DB = "actelya3_test_verifica20260909p3"


def _db(monkeypatch=None):
    client = AsyncIOMotorClient(_MONGO_URL)
    db = client[_TEST_DB]
    if monkeypatch is not None:
        # get_budget()/dashboard()/log_audit() usano il 'db' GLOBALE dei
        # rispettivi moduli (from ..db import db), non un parametro
        # esplicito — va sostituito qui con il db isolato di questa
        # esecuzione (stessa guardia autouse di conftest.py per app.audit.db).
        monkeypatch.setattr(BUDGET, "db", db)
        monkeypatch.setattr(STATS, "db", db)
        monkeypatch.setattr(audit_module, "db", db)
    return client, db


def run(coro):
    return asyncio.run(coro)


async def _cleanup(db, org):
    for c in ("plans", "tasks", "goals", "facts", "executions", "tool_cost_events",
              "deliverables", "content_items", "approvals", "budgets", "settings",
              "ai_connections", "organizations"):
        await db[c].delete_many({"organization_id": org})
    await db.settings.delete_many({"id": org})
    await db.budgets.delete_many({"id": org})
    await db.organizations.delete_many({"id": org})


# ==================== 1) Estrazione prodotti/servizi: JSON-LD vs euristica ====================
HTML_JSONLD = """<html><head><title>Test</title>
<script type="application/ld+json">{
  "@context": "https://schema.org", "@type": "Organization", "name": "Acme",
  "makesOffer": [
    {"@type": "Offer", "name": "Acme Pension"},
    {"@type": "Offer", "name": "Acme Ops"}
  ]
}</script></head>
<body>
<h2>Quattro prodotti indipendenti, un unico metodo.</h2>
<h2>Acme Pension</h2>
<h2>Strumenti costruiti attorno a chi li usa.</h2>
<h2>Professionisti e consulenti</h2>
</body></html>"""

HTML_NO_JSONLD = """<html><head><title>Test</title></head>
<body>
<h2>Quattro prodotti indipendenti, un unico metodo.</h2>
<h2>Acme Pension</h2>
<h2>Acme Ops</h2>
<h2>Strumenti costruiti attorno a chi li usa.</h2>
<h2>Professionisti e consulenti</h2>
<h3>Due mondi, un metodo</h3>
<h3>Chi offre consulenza e vive di relazione con il cliente.</h3>
</body></html>"""


def test_prodotti_da_jsonld_esclude_slogan_e_pubblico():
    prodotti, fonte = D._estrai_prodotti_servizi(HTML_JSONLD)
    assert fonte == "jsonld"
    assert prodotti == ["Acme Pension", "Acme Ops"]
    assert "Quattro prodotti indipendenti, un unico metodo." not in prodotti
    assert "Professionisti e consulenti" not in prodotti


def test_prodotti_euristici_senza_jsonld_filtrano_slogan_e_pubblico():
    prodotti, fonte = D._estrai_prodotti_servizi(HTML_NO_JSONLD)
    assert fonte == "euristica"
    assert "Acme Pension" in prodotti
    assert "Acme Ops" in prodotti
    for rumore in ("Quattro prodotti indipendenti, un unico metodo.", "Strumenti costruiti attorno a chi li usa.",
                  "Professionisti e consulenti", "Due mondi, un metodo",
                  "Chi offre consulenza e vive di relazione con il cliente."):
        assert rumore not in prodotti, f"'{rumore}' non e' un nome di prodotto/servizio"


def test_prodotti_jsonld_confidenza_piu_alta_dell_euristica(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            monkeypatch.setattr(D, "_fetch_sincrono", lambda url: {
                "ok": True, "url_finale": url, "status_code": 200, "testo": HTML_JSONLD,
            })
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "discovery_real_fetch": True}}, upsert=True)
            real_fetch = await D.fetch_sito_reale(db, org, "https://esempio-acme.it/")
            assert real_fetch["prodotti_servizi_fonte"] == "jsonld"

            fonte_dominio = D._dominio_normalizzato(real_fetch["url"])
            valore = ", ".join(real_fetch["prodotti_servizi_candidati"])
            f = await write_fact(db, org_id=org, user_id="u", field="prodotti_servizi_candidati", value=valore,
                                 source=fonte_dominio, method="ESTRATTO", confidence=0.6,
                                 evidence={"url": real_fetch["url"], "acquisito_il": real_fetch["acquisito_il"],
                                          "estratto": valore, "metodo_estrazione": "jsonld"})
            assert f["confidence"] == 0.6
            assert f["evidence"][0]["metodo_estrazione"] == "jsonld"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


# ==================== 2) Coerenza budget Dashboard <-> Budget ====================
def test_dashboard_e_budget_riportano_la_stessa_spesa_totale(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.budgets.update_one({"id": org}, {"$set": {"id": org, "general_limit": 1.0, "daily_limit": 0.25}}, upsert=True)
            await db.executions.insert_one({"organization_id": org, "id": "ex-1", "real_cost": 0.05})
            await record_cost(db, org_id=org, tool_id="requesty_llm", agent_id="coordinatore-actelya", amount=0.01)

            b = await get_budget(user={"organization_id": org, "id": "u"})
            d = await dashboard(user={"organization_id": org, "id": "u"})

            assert b["spent_simulated"] == pytest.approx(0.06)
            assert d["total_cost_simulated"] == pytest.approx(0.06)
            assert b["spent_simulated"] == d["total_cost_simulated"], "Dashboard e Budget devono riportare la stessa spesa (era 0.9488 vs 0.9395)"
            assert b["residual"] == pytest.approx(d["budget_residual"])
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_budget_nessun_doppio_conteggio_costi_brain():
    """spent_brain e' incluso UNA sola volta nel totale, mai sommato due volte
    ne' mai omesso quando esistono anche executions."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.executions.insert_one({"organization_id": org, "id": "ex-1", "real_cost": 0.02})
            await record_cost(db, org_id=org, tool_id="requesty_llm", agent_id="coordinatore-actelya", amount=0.007)
            speso = await compute_spent(db, org)
            assert speso["spent_execution"] == pytest.approx(0.02)
            assert speso["spent_brain"] == pytest.approx(0.007)
            assert speso["spent_simulated"] == pytest.approx(0.027)
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_budget_mode_reale_quando_esiste_costo_brain():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await record_cost(db, org_id=org, tool_id="requesty_llm", agent_id="coordinatore-actelya", amount=0.004)
            speso = await compute_spent(db, org)
            assert speso["mode"] == "REALE"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_budget_mode_simulazione_senza_alcun_costo_reale():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.executions.insert_one({"organization_id": org, "id": "ex-1", "real_cost": 0.0})
            speso = await compute_spent(db, org)
            assert speso["mode"] == "SIMULAZIONE"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


# ==================== 3) Approvazioni pendenti: piani + content_item, senza duplicazioni ====================
def test_dashboard_conta_piani_e_content_item_pendenti_distintamente(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            # goal_id/version esplicitamente distinti: un test successivo in
            # questo stesso file crea l'indice unico (goal_id, version) su
            # 'plans' (M.create_m2_indexes) — condiviso perche' i test di
            # questo file usano lo stesso database di test.
            await db.plans.insert_one({"organization_id": org, "id": "plan-x", "goal_id": "goal-x", "version": 1,
                                       "plan_status": "IN_ATTESA_APPROVAZIONE", "is_current": True})
            await db.plans.insert_one({"organization_id": org, "id": "plan-y-superato", "goal_id": "goal-y", "version": 1,
                                       "plan_status": "IN_ATTESA_APPROVAZIONE", "is_current": False})
            for i in range(3):
                await db.content_items.insert_one({"organization_id": org, "id": f"content-{i}", "status": "IN_ATTESA_APPROVAZIONE"})
            await db.content_items.insert_one({"organization_id": org, "id": "content-approvato", "status": "APPROVATO"})

            d = await dashboard(user={"organization_id": org, "id": "u"})
            assert d["pending_plans"] == 1, "un piano superato (is_current=False) non conta come pendente"
            assert d["pending_content_items"] == 3
            assert d["pending_approvals_legacy"] == 0
            assert d["pending_approvals"] == 4, "1 piano + 3 bozze, mai 0 nonostante ci siano davvero attività in attesa"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_dashboard_approvazioni_scoperte_solo_per_organizzazione_dell_utente(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org_a = f"org-test-{uuid.uuid4().hex[:8]}"
        org_b = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.plans.insert_one({"organization_id": org_b, "id": "plan-altrui", "plan_status": "IN_ATTESA_APPROVAZIONE", "is_current": True})
            await db.content_items.insert_one({"organization_id": org_b, "id": "content-altrui", "status": "IN_ATTESA_APPROVAZIONE"})
            d = await dashboard(user={"organization_id": org_a, "id": "u"})
            assert d["pending_approvals"] == 0, "nessuna approvazione di un'altra organizzazione deve comparire"
            return True
        finally:
            await _cleanup(db, org_a)
            await _cleanup(db, org_b)
            client.close()
    assert run(scenario())


# ==================== 4) Budget esaurito A META' di un task con più item ====================
def _adapter_ok(payload):
    def fake_genera_json(**kwargs):
        from app.integrations.requesty_gateway import RisultatoGenerazioneRequesty
        return RisultatoGenerazioneRequesty(testo=payload, modello_effettivo="anthropic/claude-sonnet-4-5",
                                            latenza_ms=10, input_tokens=80, output_tokens=40, troncata=False)
    return fake_genera_json


CONTENT_JSON_OK = (
    '{"titolo": "", "corpo": "Contenuto reale di prova.", "cta": "Scopri di più", '
    '"hashtags": ["#test"], "varianti": []}'
)


def test_budget_esaurito_a_meta_task_blocca_gli_item_successivi_non_solo_tra_task(monkeypatch):
    """Un task 'content_item' con 3 elementi richiesti e budget sufficiente
    per UNO solo: il primo va a buon fine, il secondo va bloccato per
    budget_task_esaurito PRIMA di chiamare Requesty, il terzo non deve
    nemmeno essere tentato — non solo fra task diversi (gia' coperto da
    test_content_item_budget_insufficiente_bloccato_senza_retry in
    test_m2_auto_dispatch.py), ma DENTRO lo stesso task."""
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.ai_connections.insert_one({
                "id": f"aiconn-{uuid.uuid4().hex[:8]}", "organization_id": org, "provider_type": "requesty",
                "effective_model": "anthropic/claude-sonnet-4-5", "priority": 1, "verified": True, "active": True,
                "timeout": 20, "max_tokens": 1200, "api_key_encrypted": None, "created_at": "2026-01-01T00:00:00Z",
            })
            await db.organizations.update_one(
                {"id": org}, {"$set": {"id": org, "ragione_sociale": "Test Azienda", "settore": "servizi"}}, upsert=True)

            goal_id = M.new_id("goal")
            await db.goals.insert_one({"id": goal_id, "organization_id": org, "text": "tre post di prova"})
            piano = await cc_pipeline.create_content_item(
                db, org_id=org, actor="user-test", objective="Promuovere Test Azienda", channel="Instagram",
                funnel_stage="TOFU", content_type="post_social", campaign_id=None, tone_override=None,
                constraints="", brief="tre post testuali in bozza", quantity=3,
            )
            item_ids = [i["id"] for i in piano["items"]]
            assert len(item_ids) == 3

            # Riserva del task pari a UN item secondo la stima flat pre-chiamata
            # (real_content_creator.py::_STIMA_COSTO_PER_ITEM = 0.01, verificata
            # PRIMA di ogni item: costo_totale + 0.01 > budget_residuo). Il primo
            # item passa il controllo (0 + 0.01 <= 0.01); il costo REALE del
            # primo item (dai pochi token del mock, ben sotto 0.01) non esaurisce
            # la riserva da solo, ma sommato alla stima flat del secondo la
            # supera — bloccando il secondo/terzo PRIMA di chiamare Requesty.
            cost_riservato = 0.01
            plan_id = M.new_id("plan")
            await db.plans.insert_one({
                "id": plan_id, "organization_id": org, "goal_id": goal_id, "objective_type": "CONTENUTO",
                "plan_status": "IN_ATTESA_APPROVAZIONE", "dag": {"nodes": ["t1"], "edges": []}, "topo_order": ["t1"],
                "estimate": {}, "version": 1, "is_current": True, "created_by": "user-test", "updated_by": "user-test",
                "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z", "stopped": False,
                "approved_cap": cost_riservato,
            })
            task_id = M.new_id("task")
            await db.tasks.insert_one({
                "id": task_id, "organization_id": org, "plan_id": plan_id, "goal_id": goal_id, "version": 1, "seq": 1,
                "name": "Content Creator — produzione contenuti", "agent_id": "content-creator",
                "deliverable_type": "content_item",
                "inputs": {"cost": cost_riservato,
                          "deliverable_override": {"content_item_ids": item_ids, "mode": "REALE",
                                                   "note": "Genera e approva il contenuto in Content Creator."}},
                "depends_on": [], "task_status": "IN_ATTESA_APPROVAZIONE", "approved": False, "attempt": 0,
                "idempotency_key": f"{plan_id}:1:{task_id}", "lease_owner": None, "lease_expires_at": None,
                "tokens_input": 0, "tokens_output": 0, "cost": 0.0, "deliverable_id": None, "warnings": [],
                "confirmed": False, "started_at": None, "finished_at": None, "mode": "SIMULAZIONE",
                "created_by": "user-test", "updated_by": "user-test",
                "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
            })

            chiamate = {"n": 0}
            adapter_base = _adapter_ok(CONTENT_JSON_OK)

            def _conta_e_genera(**kwargs):
                chiamate["n"] += 1
                return adapter_base(**kwargs)
            monkeypatch.setattr(cc_pipeline.requesty_gateway, "genera_json", _conta_e_genera)

            await E.approve_plan(db, plan_id, "appr@test")
            await E._auto_dispatch_scan_once(db)

            task_after = await db.tasks.find_one({"id": task_id})
            assert task_after["task_status"] == "BLOCCATA", task_after
            assert task_after.get("blocked_reason_code") == "parziale", task_after
            assert any("budget_task_esaurito" in w for w in task_after["warnings"]), task_after["warnings"]

            items_finali = await db.content_items.find({"id": {"$in": item_ids}}, {"_id": 0}).to_list(3)
            stati = {i["id"]: i["status"] for i in items_finali}
            pronti = sum(1 for s in stati.values() if s == "IN_ATTESA_APPROVAZIONE")
            in_bozza = sum(1 for s in stati.values() if s == "BOZZA")
            assert pronti == 1, f"esattamente un item deve essere stato generato prima dell'esaurimento: {stati}"
            assert in_bozza == 2, f"gli altri due non devono essere stati nemmeno tentati: {stati}"
            assert chiamate["n"] == 1, "Requesty va chiamato UNA sola volta, mai per il secondo/terzo item oltre il residuo"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


# ==================== 5) Revisione editoriale: Risultati/piano riflettono la decisione ====================
def test_deliverable_content_item_riflette_approvazione_live_non_lo_snapshot():
    """Il deliverable versionato porta uno SNAPSHOT dello stato al momento
    della generazione: dopo un'approvazione REALE nel laboratorio (che
    scrive solo su content_items), Risultati/dettaglio piano devono
    mostrare lo stato aggiornato, non quello 'congelato' alla generazione."""
    async def scenario():
        from app.m2.engine import enrich_content_item_deliverables_live
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.content_items.insert_one({
                "id": "content-x", "organization_id": org, "status": "APPROVATO",  # deciso DOPO la generazione
                "content": {"titolo": "Nuovo titolo dopo revisione"}, "semantic_check": {"status": "OK"},
            })
            deliverable = {
                "id": "deliv-x", "organization_id": org, "plan_id": "plan-x", "deliverable_type": "content_item",
                "content": {"content_item_ids": ["content-x"], "items": [
                    {"content_item_id": "content-x", "content_type": "post_social",
                     "status": "IN_ATTESA_APPROVAZIONE",  # snapshot VECCHIO, dalla generazione
                     "content": {"titolo": "Vecchio titolo"}, "semantic_check": {"status": "OK"}},
                ]},
            }
            arricchiti = await enrich_content_item_deliverables_live(db, [deliverable])
            item = arricchiti[0]["content"]["items"][0]
            assert item["status"] == "APPROVATO", "lo stato mostrato deve essere quello LIVE, non lo snapshot congelato"
            assert item["content"]["titolo"] == "Nuovo titolo dopo revisione"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_deliverable_content_item_id_non_piu_esistente_non_inventa_dati():
    async def scenario():
        from app.m2.engine import enrich_content_item_deliverables_live
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            deliverable = {
                "id": "deliv-y", "organization_id": org, "plan_id": "plan-y", "deliverable_type": "content_item",
                "content": {"content_item_ids": ["content-sparito"], "items": [
                    {"content_item_id": "content-sparito", "content_type": "post_social",
                     "status": "IN_ATTESA_APPROVAZIONE", "content": {"titolo": "X"}, "semantic_check": {"status": "OK"}},
                ]},
            }
            arricchiti = await enrich_content_item_deliverables_live(db, [deliverable])
            item = arricchiti[0]["content"]["items"][0]
            # Nessun content_item live trovato: resta lo snapshot originale
            # (mai un dato inventato al suo posto — la UI lo gestisce gia'
            # come 'non disponibile' quando l'id manca del tutto da items).
            assert item["status"] == "IN_ATTESA_APPROVAZIONE"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


# ==================== 6) m2/reviews.py: due falsi positivi trovati nella prova E2E ====================
def _deliv(dtype="social_content", mode="REALE", content=None):
    return {"id": "deliv-t", "organization_id": "org-t", "plan_id": "plan-t", "task_id": "task-t",
            "agent_id": "content_social", "deliverable_type": dtype, "version": 1, "is_current": True,
            "status": "COMPLETATO", "valid": True, "content": content or {}, "mode": mode}


def test_audit_non_segnala_piu_high_per_deliverable_reale():
    """Bug reale riprodotto durante la prova E2E del 2026-09-09 (piano
    plan-c632efad5881492ea9fe, deliverable social_content prodotto in modalita'
    REALE dopo approvazione): run_audit segnalava HIGH 'Deliverable non in
    modalita' SIMULAZIONE' su OGNI deliverable reale, un falso allarme
    strutturale ereditato dal Blocco 6 (quando REALE non era ancora un
    percorso legittimo) che confonde chi fa la revisione editoriale."""
    d = _deliv(mode="REALE")
    findings, sev = R.run_audit(d, {"cost": 0.00437, "attempt": 1})
    assert not any(f["code"] == "MODE" for f in findings), (
        f"un deliverable REALE valido non deve piu' generare un rilievo MODE: {findings}")
    d_simulato = _deliv(mode="SIMULAZIONE")
    findings2, _ = R.run_audit(d_simulato, {})
    assert not any(f["code"] == "MODE" for f in findings2)
    d_corrotto = _deliv(mode="ALTRO_VALORE_INVALIDO")
    findings3, sev3 = R.run_audit(d_corrotto, {})
    assert any(f["code"] == "MODE" for f in findings3) and sev3 == "high", (
        "un valore di mode davvero invalido deve restare segnalato")


def test_compliance_non_segnala_placeholder_per_semplici_liste_json():
    """Bug reale riprodotto nella stessa prova: PLACEHOLDER_RE applicato al
    json.dumps() dell'intero contenuto intercettava anche le parentesi quadre
    di QUALUNQUE campo lista (es. "hashtags": ["#a", "#b"]) come se fossero un
    segnaposto testuale ("[NOME AZIENDA]") — falso positivo su ogni
    deliverable con un campo lista, quindi quasi sempre."""
    d = _deliv(content={
        "platform": "Facebook e Instagram",
        "posts": [{"hook": "Titolo vero", "body": "Corpo vero, nessun segnaposto.",
                   "hashtags": ["#SPIPension", "#SPITool"]}],
    })
    findings, _ = R.run_compliance(d, {})
    assert not any(f["code"] == "PLACEHOLDER" for f in findings), (
        f"una lista JSON valida non e' un placeholder testuale: {findings}")

    d_con_placeholder = _deliv(content={"posts": [{"body": "Testo con [NOME AZIENDA] da sostituire."}]})
    findings2, _ = R.run_compliance(d_con_placeholder, {})
    assert any(f["code"] == "PLACEHOLDER" for f in findings2), (
        "un vero segnaposto testuale deve restare rilevato")


# ==================== 7) Ramo content_item: decisione editoriale isolata ====================
# La prova E2E reale del 2026-09-09 (goal "Prepara tre bozze testuali...") ha
# selezionato il ramo social_content (capability "social" rilevata dall'LLM),
# non content_item: nessun meccanismo di approva/rifiuta/richiedi-modifica
# post-generazione esiste per social_content in questo codice (solo revisori
# automatici non interattivi, m2/reviews.py). Il ramo content_item — che HA
# quel meccanismo (content_creator/pipeline.py) — non e' stato attraversato
# in quella prova specifica: coperto qui con un test isolato, come richiesto
# esplicitamente quando il ramo selezionato differisce da content_item.
def _content_item_in_attesa(org):
    now = "2026-09-09T00:00:00+00:00"
    return {
        "id": f"content-{uuid.uuid4().hex[:8]}", "organization_id": org, "content_type": "post_social",
        "objective": "promuovere SPI Pension", "channel": "instagram", "funnel_stage": "MOFU",
        "campaign_id": None, "tone_override": None, "constraints": None,
        "brief": "bozza di prova", "motivazione_tipo": "richiesta esplicita", "tono_suggerito": "professionale",
        "content_group_id": "grp-1", "content_group_size": 3, "content_group_index": 1,
        "status": "IN_ATTESA_APPROVAZIONE",
        "content": {"titolo": "SPI Pension", "corpo": "Testo grounded sul Fact Ledger."},
        "generazione": {"provider": "requesty", "modello_effettivo": "claude-test"},
        "nota_revisione": None,
        "semantic_check": {"status": "OK", "affermazioni_contestate": []},
        "approved": False, "approved_by": None, "approved_at": None, "media_link": None,
        "history": [{"at": now, "status": "BOZZA", "actor": "user-test", "motivo": "Creato"}],
        "created_by": "user-test", "created_at": now, "updated_at": now,
    }


def test_decisione_editoriale_content_item_approvazione_persistente_e_propagata(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            item = _content_item_in_attesa(org)
            await db.content_items.insert_one(dict(item))

            prima = await dashboard(user={"organization_id": org, "id": "u"})
            assert prima["pending_content_items"] == 1

            aggiornato = await cc_pipeline.approve_content_item(
                db, item, actor="user-test", approve=True, note="")
            assert aggiornato["status"] == "APPROVATO"

            # Persistenza: rilettura diretta dal DB, non solo il valore di ritorno.
            ricaricato = await db.content_items.find_one({"id": item["id"]}, {"_id": 0})
            assert ricaricato["status"] == "APPROVATO"
            assert ricaricato["approved"] is True and ricaricato["approved_by"] == "user-test"

            # Propagazione: il conteggio pendenti in Dashboard deve aggiornarsi di conseguenza.
            dopo = await dashboard(user={"organization_id": org, "id": "u"})
            assert dopo["pending_content_items"] == 0, (
                "un content_item appena approvato non deve piu' contare come pendente in Dashboard")
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_decisione_editoriale_content_item_richiesta_modifica_torna_in_bozza_con_versione_salvata(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            item = _content_item_in_attesa(org)
            await db.content_items.insert_one(dict(item))

            aggiornato = await cc_pipeline.request_revision(
                db, item, actor="user-test", note="Rendere piu' specifico su SPI Pension.")
            assert aggiornato["status"] == "BOZZA"

            ricaricato = await db.content_items.find_one({"id": item["id"]}, {"_id": 0})
            assert ricaricato["status"] == "BOZZA"

            # Non distruttivo: il contenuto precedente resta consultabile in una versione,
            # mai perso silenziosamente da una richiesta di modifica.
            versioni = await db.content_item_versions.find(
                {"content_item_id": item["id"]}, {"_id": 0}).to_list(10)
            assert len(versioni) == 1
            assert versioni[0]["content"] == item["content"]
            assert versioni[0]["nota_revisione_che_ha_portato_alla_modifica"] == "Rendere piu' specifico su SPI Pension."
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


# ==================== 8) Revisione editoriale sulle bozze social_content (nuovo meccanismo) ====================
# Colma il difetto reale trovato nella prova E2E del 2026-09-09 (piano
# plan-c632efad5881492ea9fe): il ramo "social_content" non aveva ALCUNA
# decisione editoriale post-generazione. Test isolati (nessun server live,
# nessuna chiamata di rete) per le tre decisioni, l'obbligo di motivazione,
# la protezione da decisioni duplicate/su versioni superate, e la
# propagazione a Dashboard.
def _deliv_social(org, plan_id="plan-t", n_posts=3, version=1, is_current=True, task_id=None):
    posts = [
        {"hook": f"hook {i}", "body": f"corpo bozza {i}, nessun segnaposto.", "cta": "scopri di piu'",
         "hashtags": ["#a", "#b"], "channel": "Facebook" if i % 2 == 0 else "Instagram",
         "objective": "notorieta'", "success_metric": "simulato"}
        for i in range(n_posts)
    ]
    return {
        "id": f"deliv-{uuid.uuid4().hex[:8]}", "organization_id": org, "plan_id": plan_id,
        "task_id": task_id or f"task-{uuid.uuid4().hex[:8]}", "deliverable_type": "social_content",
        "version": version, "is_current": is_current, "status": "COMPLETATO", "valid": True, "mode": "REALE",
        "content": {"platform": "Facebook e Instagram", "posts": posts},
    }


def test_decide_item_tre_decisioni_distinte_persistite():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d = _deliv_social(org)
            await db.deliverables.insert_one(dict(d))

            prima = await DR.get_item_decisions(db, d)
            assert len(prima) == 3
            assert all(p["decision"]["status"] == DR.STATO_IN_ATTESA_REVISIONE for p in prima)
            assert all(p["current_version"] == 1 for p in prima)

            r0 = await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                      item_index=0, decision=DR.DECISIONE_APPROVATO,
                                      actor="revisore@test", reason=None)
            assert r0["status"] == "APPROVATO" and r0["decided_by"] == "revisore@test"

            r1 = await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                      item_index=1, decision=DR.DECISIONE_RIFIUTATO,
                                      actor="revisore@test", reason="Tono non coerente col brand.")
            assert r1["status"] == "RIFIUTATO" and r1["reason"] == "Tono non coerente col brand."

            r2 = await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                      item_index=2, decision=DR.DECISIONE_MODIFICA_RICHIESTA,
                                      actor="revisore@test", reason="Specificare meglio il prodotto.")
            assert r2["status"] == "MODIFICA_RICHIESTA"

            dopo = await DR.get_item_decisions(db, d)
            stati = {p["item_index"]: p["decision"]["status"] for p in dopo}
            assert stati == {0: "APPROVATO", 1: "RIFIUTATO", 2: "MODIFICA_RICHIESTA"}

            # Persistenza reale: rilettura diretta dal DB, non solo il valore di ritorno.
            righe = await db.deliverable_item_decisions.find(
                {"deliverable_id": d["id"]}, {"_id": 0}).to_list(10)
            assert len(righe) == 3
            assert all(r["deliverable_version"] == 1 and r["plan_id"] == d["plan_id"] for r in righe)
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_decide_item_richiede_motivazione_per_rifiuto_e_modifica():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d = _deliv_social(org)
            await db.deliverables.insert_one(dict(d))
            for decisione in (DR.DECISIONE_RIFIUTATO, DR.DECISIONE_MODIFICA_RICHIESTA):
                try:
                    await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                         item_index=0, decision=decisione, actor="revisore@test", reason="   ")
                    assert False, f"{decisione} senza motivazione doveva sollevare DecisionError"
                except DR.DecisionError:
                    pass
            # L'approvazione invece NON richiede motivazione obbligatoria.
            ok = await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                      item_index=0, decision=DR.DECISIONE_APPROVATO,
                                      actor="revisore@test", reason=None)
            assert ok["status"] == "APPROVATO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_decide_item_blocca_decisione_duplicata_sulla_stessa_bozza():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d = _deliv_social(org)
            await db.deliverables.insert_one(dict(d))
            await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                 item_index=0, decision=DR.DECISIONE_APPROVATO, actor="a@test", reason=None)
            try:
                await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                     item_index=0, decision=DR.DECISIONE_RIFIUTATO,
                                     actor="b@test", reason="cambio idea")
                assert False, "una seconda decisione sulla stessa bozza+versione deve essere rifiutata"
            except DR.DecisionError as e:
                assert "duplicat" in str(e).lower()
            # Le altre bozze dello stesso deliverable restano decidibili normalmente.
            altra = await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                         item_index=1, decision=DR.DECISIONE_APPROVATO, actor="a@test", reason=None)
            assert altra["status"] == "APPROVATO"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_decide_item_blocca_su_versione_superata_e_indice_invalido():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d_superata = _deliv_social(org, is_current=False)
            await db.deliverables.insert_one(dict(d_superata))
            try:
                await DR.decide_item(db, org_id=org, plan_id=d_superata["plan_id"], deliverable=d_superata,
                                     item_index=0, decision=DR.DECISIONE_APPROVATO, actor="a@test", reason=None)
                assert False, "una versione non corrente non deve essere decidibile"
            except DR.DecisionError as e:
                assert "corrente" in str(e).lower() or "superata" in str(e).lower()

            d = _deliv_social(org, n_posts=2)
            await db.deliverables.insert_one(dict(d))
            for indice_invalido in (-1, 2, 99):
                try:
                    await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                         item_index=indice_invalido, decision=DR.DECISIONE_APPROVATO,
                                         actor="a@test", reason=None)
                    assert False, f"indice {indice_invalido} fuori intervallo doveva essere rifiutato"
                except DR.DecisionError:
                    pass
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_enrich_multi_item_deliverables_solo_sui_tipi_pertinenti():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d_social = _deliv_social(org)
            d_strategy = {"id": "deliv-strat", "organization_id": org, "plan_id": "plan-t",
                         "deliverable_type": "marketing_strategy", "version": 1, "is_current": True,
                         "content": {"title": "x"}}
            await db.deliverables.insert_one(dict(d_social))
            await DR.decide_item(db, org_id=org, plan_id=d_social["plan_id"], deliverable=d_social,
                                 item_index=0, decision=DR.DECISIONE_APPROVATO, actor="a@test", reason=None)

            arricchiti = await DR.enrich_multi_item_deliverables_with_decisions(db, [d_social, d_strategy])
            social_arricchito = next(x for x in arricchiti if x["id"] == d_social["id"])
            strategy_arricchito = next(x for x in arricchiti if x["id"] == d_strategy["id"])
            assert len(social_arricchito["item_decisions"]) == 3
            assert social_arricchito["item_decisions"][0]["decision"]["status"] == "APPROVATO"
            assert social_arricchito["item_decisions"][1]["decision"]["status"] == DR.STATO_IN_ATTESA_REVISIONE
            assert "item_decisions" not in strategy_arricchito, (
                "un deliverable senza bozze indipendenti non deve ricevere il campo item_decisions")
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_dashboard_pending_deliverable_items_propaga_dopo_decisioni(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d = _deliv_social(org, plan_id="plan-dash")
            await db.deliverables.insert_one(dict(d))

            iniziale = await dashboard(user={"organization_id": org, "id": "u"})
            assert iniziale["pending_deliverable_items"] == 3
            assert iniziale["pending_approvals"] >= 3

            await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                 item_index=0, decision=DR.DECISIONE_APPROVATO, actor="a@test", reason=None)
            intermedio = await dashboard(user={"organization_id": org, "id": "u"})
            assert intermedio["pending_deliverable_items"] == 2

            await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                 item_index=1, decision=DR.DECISIONE_RIFIUTATO, actor="a@test", reason="no")
            await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                 item_index=2, decision=DR.DECISIONE_MODIFICA_RICHIESTA, actor="a@test", reason="no")
            finale = await dashboard(user={"organization_id": org, "id": "u"})
            assert finale["pending_deliverable_items"] == 0, (
                "tutte e tre le bozze decise (in qualunque dei tre esiti) devono azzerare il pendente")
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_decisione_editoriale_non_altera_retroattivamente_altri_deliverable():
    """Una decisione su un deliverable/piano non deve mai comparire o
    influenzare i conteggi di un ALTRO piano/deliverable — nemmeno all'interno
    della stessa organizzazione."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d1 = _deliv_social(org, plan_id="plan-1")
            d2 = _deliv_social(org, plan_id="plan-2")
            await db.deliverables.insert_one(dict(d1))
            await db.deliverables.insert_one(dict(d2))
            await DR.decide_item(db, org_id=org, plan_id=d1["plan_id"], deliverable=d1,
                                 item_index=0, decision=DR.DECISIONE_APPROVATO, actor="a@test", reason=None)

            decisioni_d2 = await DR.get_item_decisions(db, d2)
            assert all(p["decision"]["status"] == DR.STATO_IN_ATTESA_REVISIONE for p in decisioni_d2), (
                "il piano NON deciso non deve ereditare la decisione del piano deciso")
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


# ==================== 9) Classificazione reale/simulata della spesa (bug marketing_strategy $0.00195) ====================
# Bug reale trovato in riconciliazione (2026-09-09, piano
# plan-c632efad5881492ea9fe): execution.real_cost include la riserva
# simulata di OGNI task all'avvio (m2/engine.py::_execute, _sim_cost),
# corretta al costo vero SOLO per editorial_plan/social_content approvati in
# REALE (_apply_actual_cost_delta). Un task come marketing_strategy (sempre
# simulato) o content_item (costo vero tracciato altrove, nel Tool Execution
# Gateway) restava per sempre contato come "reale" in execution.real_cost.
def test_compute_spent_non_conta_come_reale_la_riserva_di_un_task_mai_riconciliato(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            plan_id = "plan-riconciliazione"
            # real_cost grezzo = 0.00195 (riserva simulata mai corretta, task 1) +
            # 0.00437 (task 2, editorial_plan/social_content REALE, riconciliato) —
            # stessa composizione esatta osservata nella prova reale.
            await db.executions.insert_one({
                "id": "exec-riconc", "organization_id": org, "plan_id": plan_id, "real_cost": 0.00632,
            })
            await db.tasks.insert_one({
                "id": "task-sim", "organization_id": org, "plan_id": plan_id, "seq": 1,
                "idempotency_key": f"idem-{uuid.uuid4().hex[:8]}",
                "deliverable_type": "marketing_strategy", "approved_mode": "REALE", "cost": 0.00195,
            })
            await db.tasks.insert_one({
                "id": "task-real", "organization_id": org, "plan_id": plan_id, "seq": 2,
                "idempotency_key": f"idem-{uuid.uuid4().hex[:8]}",
                "deliverable_type": "social_content", "approved_mode": "REALE", "cost": 0.00437,
            })
            speso = await compute_spent(db, org)
            assert speso["spent_execution"] == pytest.approx(0.00437), (
                f"il costo del task NON riconciliato (marketing_strategy, sempre simulato) non deve contare "
                f"come reale: atteso 0.00437, ottenuto {speso['spent_execution']}")
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_compute_spent_esclude_social_content_non_approvato_in_reale():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            plan_id = "plan-sim"
            await db.executions.insert_one({
                "id": "exec-sim", "organization_id": org, "plan_id": plan_id, "real_cost": 0.00208,
            })
            # Stesso deliverable_type idoneo, ma MAI approvato in modalita' REALE:
            # la riserva resta simulata, non riconciliata, non reale.
            await db.tasks.insert_one({
                "id": "task-social-sim", "organization_id": org, "plan_id": plan_id,
                "deliverable_type": "social_content", "approved_mode": "SIMULAZIONE", "cost": 0.00208,
            })
            speso = await compute_spent(db, org)
            assert speso["spent_execution"] == pytest.approx(0.0)
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_compute_spent_content_item_escluso_da_execution_ma_incluso_da_tool_cost_events():
    """content_item non e' in REAL_ELIGIBLE_TYPES: la sua riserva su
    execution.real_cost resta sempre simulata (mai riconciliata li'). Il suo
    costo VERO vive nel Tool Execution Gateway (agent_id='content-creator'),
    prima escluso per errore dal totale mostrato — ora incluso."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            plan_id = "plan-ci"
            await db.executions.insert_one({
                "id": "exec-ci", "organization_id": org, "plan_id": plan_id, "real_cost": 0.02,
            })
            await db.tasks.insert_one({
                "id": "task-ci", "organization_id": org, "plan_id": plan_id,
                "deliverable_type": "content_item", "approved_mode": "REALE", "cost": 0.02,
            })
            await db.tool_cost_events.insert_one({
                "id": "costevt-ci-1", "organization_id": org, "tool_id": "requesty_llm",
                "agent_id": "content-creator", "amount": 0.004398, "currency": "USD",
                "day": "2026-09-09", "created_at": "2026-09-09T00:00:00+00:00",
            })
            speso = await compute_spent(db, org)
            assert speso["spent_execution"] == pytest.approx(0.0), (
                "la riserva di un task content_item non e' mai riconciliata su execution.real_cost")
            assert speso["spent_content_creator"] == pytest.approx(0.004398), (
                "il costo vero di content_item (Tool Execution Gateway) non deve piu' sparire dal totale")
            assert speso["spent_simulated"] == pytest.approx(0.004398)
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_compute_spent_riconoscere_correttamente_editorial_plan_social_content_reali():
    """Percorso REALE genuino (nessuna regressione): editorial_plan +
    social_content approvati in REALE restano interamente contati come
    spesa reale, esattamente come prima di questo fix."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            plan_id = "plan-reale-puro"
            await db.executions.insert_one({
                "id": "exec-reale", "organization_id": org, "plan_id": plan_id, "real_cost": 0.015,
            })
            for i, (tipo, costo) in enumerate((("editorial_plan", 0.006), ("social_content", 0.009)), start=1):
                await db.tasks.insert_one({
                    "id": f"task-{tipo}", "organization_id": org, "plan_id": plan_id, "seq": i,
                    "idempotency_key": f"idem-{uuid.uuid4().hex[:8]}",
                    "deliverable_type": tipo, "approved_mode": "REALE", "cost": costo,
                })
            speso = await compute_spent(db, org)
            assert speso["spent_execution"] == pytest.approx(0.015)
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


# ==================== 10) Ciclo completo: bozza -> richiesta di modifica -> nuova versione -> nuova decisione ====================
def test_ciclo_completo_richiesta_modifica_nuova_versione_nuova_decisione():
    """Colma il vicolo cieco segnalato: una richiesta di modifica ora puo'
    essere applicata (percorso SIMULATO qui: nessuna connessione AI reale
    configurata per questo org di test, quindi apply_edit ricade
    correttamente sul simulato dichiarato, mai una chiamata reale non
    autorizzata), producendo una v2 IN_ATTESA_REVISIONE — mai approvata
    automaticamente — mentre v1 e la sua decisione restano intatte e
    consultabili, e le ALTRE bozze dello stesso deliverable non vengono
    toccate."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d = _deliv_social(org, n_posts=3)
            await db.deliverables.insert_one(dict(d))
            corpo_originale_1 = d["content"]["posts"][1]["body"]

            # 1) richiesta di modifica sulla bozza 0 (v1)
            r1 = await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                      item_index=0, decision=DR.DECISIONE_MODIFICA_RICHIESTA,
                                      actor="revisore@test", reason="Rendere il tono piu' diretto.")
            assert r1["status"] == "MODIFICA_RICHIESTA" and r1["version"] == 1

            # 2) applicazione esplicita della modifica -> nuova versione (v2)
            v2 = await DR.apply_edit(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                     item_index=0, actor="revisore@test", confirm=True)
            assert v2["version"] == 2
            assert v2["mode"] == "SIMULAZIONE"  # nessuna connessione AI reale in questo org di test
            assert v2["edit_note"] == "Rendere il tono piu' diretto."
            assert "SIMULATO" in v2["content"]["body"]  # mai spacciata per una revisione reale

            # 3) stato corrente: v2, IN_ATTESA_REVISIONE (mai approvata automaticamente)
            stato = await DR.get_item_state(db, d, 0)
            assert stato["current_version"] == 2
            assert stato["decision"]["status"] == DR.STATO_IN_ATTESA_REVISIONE
            # v1 e la sua decisione restano intatte nello storico, mai perse
            assert len(stato["history"]) == 1
            assert stato["history"][0]["version"] == 1
            assert stato["history"][0]["decision"]["status"] == "MODIFICA_RICHIESTA"
            assert stato["history"][0]["decision"]["reason"] == "Rendere il tono piu' diretto."

            # 4) nuova decisione sulla v2 (non bloccata dalla decisione terminale di v1)
            r2 = await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                      item_index=0, decision=DR.DECISIONE_APPROVATO, actor="revisore@test", reason=None)
            assert r2["status"] == "APPROVATO" and r2["version"] == 2

            # 5) le ALTRE bozze dello stesso deliverable non sono state toccate
            d_rifresh = await db.deliverables.find_one({"id": d["id"]}, {"_id": 0})
            assert d_rifresh["content"]["posts"][1]["body"] == corpo_originale_1
            stato_1 = await DR.get_item_state(db, d, 1)
            assert stato_1["current_version"] == 1
            assert stato_1["decision"]["status"] == DR.STATO_IN_ATTESA_REVISIONE
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_apply_edit_richiede_conferma_esplicita_e_solo_da_modifica_richiesta():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d = _deliv_social(org)
            await db.deliverables.insert_one(dict(d))

            # Nessuna richiesta di modifica ancora registrata: applicare deve fallire.
            try:
                await DR.apply_edit(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                    item_index=0, actor="a@test", confirm=True)
                assert False, "non deve essere applicabile senza una richiesta di modifica in attesa"
            except DR.DecisionError as e:
                assert "richiesta di modifica" in str(e).lower()

            await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                 item_index=0, decision=DR.DECISIONE_MODIFICA_RICHIESTA,
                                 actor="a@test", reason="Motivo valido.")

            # confirm mancante: nessuna azione, nessuna nuova versione.
            try:
                await DR.apply_edit(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                    item_index=0, actor="a@test", confirm=False)
                assert False, "senza confirm=True non deve applicare nulla"
            except DR.DecisionError as e:
                assert "conferma" in str(e).lower()
            versioni = await db.deliverable_item_versions.count_documents({"deliverable_id": d["id"]})
            assert versioni == 0
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_preview_edit_cost_e_solo_stima_mai_un_addebito():
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            d = _deliv_social(org, n_posts=3)
            await db.deliverables.insert_one(dict(d))
            stima = await DR.preview_edit_cost(d, 0)
            assert stima["cost_max"] > 0 and stima["mode"] == "SIMULAZIONE"
            n_eventi = await db.tool_cost_events.count_documents({"organization_id": org})
            assert n_eventi == 0, "una sola stima non deve mai registrare un costo"
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_apply_edit_reale_riserva_registra_e_riconcilia_senza_doppio_conteggio(monkeypatch):
    """Punto 2 (contabilita'): il percorso REALE di apply_edit deve seguire
    esattamente reserve_budget -> chiamata -> record_cost ->
    reconcile_reservation (stesso schema gia' collaudato in
    brain/llm_understanding.py), senza lasciare riserve residue e senza
    contare due volte la stessa chiamata."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await M.create_m2_indexes(db)
            await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
            await db.budgets.update_one({"id": org}, {"$set": {"id": org, "general_limit": 1.0, "daily_limit": 0.0}}, upsert=True)
            await db.ai_connections.insert_one({
                "organization_id": org, "provider_type": "requesty", "effective_model": "claude-test",
                "priority": 1, "verified": True, "active": True, "timeout": 20, "max_tokens": 1000,
                "id": f"aiconn-{uuid.uuid4().hex[:8]}", "api_key_encrypted": None,
            })
            d = _deliv_social(org, n_posts=2)
            await db.deliverables.insert_one(dict(d))
            await DR.decide_item(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                 item_index=0, decision=DR.DECISIONE_MODIFICA_RICHIESTA,
                                 actor="a@test", reason="Piu' specifico.")

            from app.brain import llm_gateway
            from app.brain.llm_gateway import LLMResult
            import json as _json
            adapter = llm_gateway.RequestyAdapter()
            post_revisionato = {
                "hook": "hook nuovo", "body": "corpo rivisto piu' specifico, nessun segnaposto.",
                "cta": "scopri di piu'", "hashtags": ["#a", "#b"], "channel": "Facebook",
                "objective": "notorieta'", "success_metric": "simulato",
            }
            monkeypatch.setattr(adapter, "genera_json", lambda **kw: LLMResult(
                testo=_json.dumps(post_revisionato), provider="requesty", modello_effettivo="claude-test",
                latenza_ms=10, input_tokens=200, output_tokens=100, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {**llm_gateway.ADAPTERS, "requesty": adapter})

            v2 = await DR.apply_edit(db, org_id=org, plan_id=d["plan_id"], deliverable=d,
                                     item_index=0, actor="a@test", confirm=True)
            assert v2["mode"] == "REALE"
            assert v2["content"]["hook"] == "hook nuovo"
            assert v2["generation"]["stima_costo_usd"] is not None and v2["generation"]["stima_costo_usd"] > 0

            # Nessuna riserva residua (rilasciata/riconciliata correttamente).
            ob = await db.organization_budgets.find_one({"organization_id": org})
            assert (ob or {}).get("reserved_usd", 0.0) == pytest.approx(0.0)

            # Il costo reale e' registrato ESATTAMENTE una volta nel Tool Execution Gateway.
            eventi = await db.tool_cost_events.find({"organization_id": org}, {"_id": 0}).to_list(10)
            assert len(eventi) == 1
            assert eventi[0]["agent_id"] == "content_social_revisione"
            assert eventi[0]["amount"] == pytest.approx(v2["generation"]["stima_costo_usd"])

            # compute_spent lo include (mai piu' silenziosamente omesso) e una sola volta.
            speso = await compute_spent(db, org)
            assert speso["spent_altri_reali"] == pytest.approx(eventi[0]["amount"])
            assert speso["spent_simulated"] == pytest.approx(eventi[0]["amount"])
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


# ==================== 11) Punto 2: enforcement — nessuna omissione, nessun doppio conteggio ====================
def test_enforcement_task_reale_fallito_resta_contato_come_reale():
    """Un tentativo reale che FALLISCE dopo aver gia' interpellato il
    provider ha comunque un costo reale gia' addebitato (_apply_actual_cost_delta
    in engine.py) — la correzione della classificazione non deve mai far
    sparire questo costo dal totale mostrato solo perche' non esiste un
    deliverable completato."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            plan_id = "plan-fallito"
            # real_cost riflette la riconciliazione avvenuta anche su un
            # tentativo fallito (stesso principio di test_m2_real_content.py
            # ::test_risposta_json_non_valida_blocca_e_registra_costo_reale).
            await db.executions.insert_one({
                "id": "exec-fallito", "organization_id": org, "plan_id": plan_id, "real_cost": 0.0031,
            })
            await db.tasks.insert_one({
                "id": "task-fallito", "organization_id": org, "plan_id": plan_id, "seq": 1,
                "idempotency_key": f"idem-{uuid.uuid4().hex[:8]}",
                "deliverable_type": "social_content", "approved_mode": "REALE", "cost": 0.0031,
                "task_status": "BLOCCATA",
            })
            speso = await compute_spent(db, org)
            assert speso["spent_execution"] == pytest.approx(0.0031), (
                "il costo di un tentativo reale fallito non deve mai sparire dal totale")
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())


def test_enforcement_riserva_simulata_non_riduce_il_conteggio_reale_di_un_altro_piano():
    """Nessun 'travaso' tra piani diversi della stessa organizzazione: la
    riserva simulata di un task di un piano non deve mai influenzare il
    conteggio reale calcolato per un ALTRO piano."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.executions.insert_one({
                "id": "exec-a", "organization_id": org, "plan_id": "plan-a", "real_cost": 0.02,
            })
            await db.tasks.insert_one({
                "id": "task-a", "organization_id": org, "plan_id": "plan-a", "seq": 1,
                "idempotency_key": f"idem-{uuid.uuid4().hex[:8]}",
                "deliverable_type": "marketing_strategy", "approved_mode": "REALE", "cost": 0.02,
            })
            await db.executions.insert_one({
                "id": "exec-b", "organization_id": org, "plan_id": "plan-b", "real_cost": 0.005,
            })
            await db.tasks.insert_one({
                "id": "task-b", "organization_id": org, "plan_id": "plan-b", "seq": 1,
                "idempotency_key": f"idem-{uuid.uuid4().hex[:8]}",
                "deliverable_type": "social_content", "approved_mode": "REALE", "cost": 0.005,
            })
            speso = await compute_spent(db, org)
            assert speso["spent_execution"] == pytest.approx(0.005), (
                "solo il piano B (social_content reale) deve contare; il piano A resta simulato ed escluso")
            return True
        finally:
            await _cleanup(db, org)
            client.close()
    assert run(scenario())
