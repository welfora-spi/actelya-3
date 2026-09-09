"""Test mirati — quantita' richiesta vs prodotta e revisione semantica per il
task M2 'content_item' (correzione dei difetti emersi dalla prova reale
sul piano plan-c04ccec25ade43468f5d: 'tre post' -> un solo content_item,
item CONTESTATO approvato automaticamente).

Nessuna chiamata reale o a pagamento: requesty_gateway.genera_json e'
sostituito con un doppio di test. Database dedicato di test."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.m2 import models as M
from app.m2 import engine as E
from app.m2.real_content_creator import execute_content_item_task
from app.domains.content_creator import pipeline as cc_pipeline
from app.domains.content_creator import decision as cc_decision
from app.brain.quantity import extract_requested_quantity as _extract_requested_quantity
from app.tools.cost_ledger import set_daily_cap
from app import audit as audit_module


def _db(monkeypatch=None):
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27020")
    db = client["actelya3_test_m2auto"]
    if monkeypatch is not None:
        # tool_gateway.authorize()/log_audit scrivono sul db GLOBALE
        # (app/audit.py: 'from .db import db', legato a MONGO_URL/.env —
        # oggi il database reale actelya3_dev): mai lasciare che i test
        # scrivano li'. Si reindirizza sul db di test isolato di QUESTA
        # esecuzione, evitando anche il riuso del client Motor globale tra
        # event loop diversi di asyncio.run() (causa di 'Event loop is
        # closed' quando piu' test in sequenza toccano quel client).
        monkeypatch.setattr(audit_module, "db", db)
    return client, db


def run(coro):
    return asyncio.run(coro)


def _new_org():
    return f"org-test-qty-{uuid.uuid4().hex[:8]}"


async def _cleanup(db, *orgs):
    for org in orgs:
        for c in ("plans", "tasks", "executions", "deliverables", "audit_logs", "worker_leases",
                  "goals", "reviews", "ai_connections", "budgets", "content_items",
                  "content_item_versions", "tool_cost_events", "organization_budgets", "m2_locks"):
            await db[c].delete_many({"organization_id": org})
        await db.settings.delete_many({"id": org})


async def _setup_content_org(db, org, *, daily_cap=None):
    await M.create_m2_indexes(db)
    await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": True}}, upsert=True)
    await db.ai_connections.insert_one({
        "id": f"aiconn-{uuid.uuid4().hex[:8]}", "organization_id": org,
        "provider_type": "requesty", "effective_model": "anthropic/claude-sonnet-4-5",
        "priority": 1, "verified": True, "active": True,
        "timeout": 20, "max_tokens": 1200, "api_key_encrypted": None,
        "created_at": "2026-01-01T00:00:00Z",
    })
    await db.organizations.update_one(
        {"id": org}, {"$set": {"id": org, "ragione_sociale": "SPI Tool", "settore": "servizi informatici"}},
        upsert=True)
    if daily_cap is not None:
        await set_daily_cap(db, org, daily_cap, "test")


async def _make_content_item_task(db, org, *, quantity=1, approved_cap=None):
    """Stesso pattern usato realmente da brain/service.py dopo la correzione:
    create_content_item(quantity=...) -> N content_item -> un solo task M2
    con content_item_ids lungo N."""
    goal_id = M.new_id("goal")
    await db.goals.insert_one({"id": goal_id, "organization_id": org, "text": "N post per SPI Tool"})
    piano = await cc_pipeline.create_content_item(
        db, org_id=org, actor="user-test", objective="Promuovere SPI Tool", channel="Instagram",
        funnel_stage="TOFU", content_type="post_social", campaign_id=None, tone_override=None,
        constraints="", brief="post testuali in bozza", quantity=quantity,
    )
    item_ids = [i["id"] for i in piano["items"]]

    plan_id = M.new_id("plan")
    cap = approved_cap if approved_cap is not None else 0.01 * quantity
    await db.plans.insert_one({
        "id": plan_id, "organization_id": org, "goal_id": goal_id, "objective_type": "CONTENUTO",
        "plan_status": "IN_ATTESA_APPROVAZIONE", "dag": {"nodes": ["t1"], "edges": []}, "topo_order": ["t1"],
        "estimate": {}, "version": 1, "is_current": True, "created_by": "user-test", "updated_by": "user-test",
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z", "stopped": False,
        "approved_cap": cap,
    })
    task_id = M.new_id("task")
    await db.tasks.insert_one({
        "id": task_id, "organization_id": org, "plan_id": plan_id, "goal_id": goal_id, "version": 1, "seq": 1,
        "name": "Content Creator — produzione contenuti", "agent_id": "content-creator",
        "deliverable_type": "content_item",
        "inputs": {"cost": round(0.01 * quantity, 6), "requested_quantity": quantity,
                  "deliverable_override": {"content_item_ids": item_ids, "mode": "REALE",
                                           "note": "Genera e approva il contenuto in Content Creator."}},
        "depends_on": [], "task_status": "IN_ATTESA_APPROVAZIONE", "approved": False, "attempt": 0,
        "idempotency_key": f"{plan_id}:1:{task_id}", "lease_owner": None, "lease_expires_at": None,
        "tokens_input": 0, "tokens_output": 0, "cost": 0.0, "deliverable_id": None, "warnings": [],
        "confirmed": False, "started_at": None, "finished_at": None, "mode": "SIMULAZIONE",
        "created_by": "user-test", "updated_by": "user-test",
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    })
    return plan_id, task_id, item_ids


def _fake_genera_json(payload):
    def fn(**kwargs):
        from app.integrations.requesty_gateway import RisultatoGenerazioneRequesty
        return RisultatoGenerazioneRequesty(testo=payload, modello_effettivo="anthropic/claude-sonnet-4-5",
                                            latenza_ms=40, input_tokens=70, output_tokens=35, troncata=False)
    return fn


def _mock_semantic_ok(monkeypatch):
    """Questi test verificano quantita'/recupero, non il controllo semantico
    (testato a parte): forza un esito OK cosi' il fixture di testo generico
    non venga contestato per ragioni indipendenti da cio' che il test vuole
    dimostrare."""
    monkeypatch.setattr(cc_pipeline, "semantic_validate_generic_content",
                        lambda campi, contesto, brief="": {"status": "OK", "affermazioni_contestate": []})


def _content_json(corpo_suffix=""):
    return (
        '{"titolo": "Titolo ' + corpo_suffix + '", '
        '"corpo": "Testo del post numero ' + corpo_suffix + ', sufficientemente lungo da superare la validazione minima.", '
        '"cta": "Visita www.spitool.it", "hashtags": ["#SPI"], '
        '"varianti": ["Variante A ' + corpo_suffix + '", "Variante B ' + corpo_suffix + '"]}'
    )


# ==================== 1. Estrazione quantita' (unita', nessun DB) ====================
@pytest.mark.parametrize("testo,attesa", [
    ("Crea tre post testuali per Facebook e Instagram", 3),
    ("Genera 3 contenuti per il lancio", 3),
    ("Scrivi due articoli per il blog", 2),
    ("Prepara un post per instagram", 1),
    ("Crea contenuti per la campagna", 1),  # nessun numero -> default invariato
    ("Genera 20 post per il lancio", 10),  # tetto prudente (cifra oltre il limite, mai capito alla lettera)
])
def test_estrazione_quantita_dal_testo(testo, attesa):
    assert _extract_requested_quantity(testo) == attesa


# ==================== 2. 'tre post' -> tre content_item distinti (mai un solo item con varianti) ====================
def test_richiesta_tre_post_produce_tre_content_item_distinti():
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            await M.create_m2_indexes(db)
            piano = await cc_pipeline.create_content_item(
                db, org_id=org, actor="user-test", objective="Promuovere SPI Tool", channel="generico",
                funnel_stage="MOFU", content_type=None, campaign_id=None, tone_override=None,
                constraints="", brief="tre post testuali in bozza", quantity=3,
            )
            return piano
        finally:
            await _cleanup(db, org)
            client.close()
    piano = run(scenario())
    assert len(piano["items"]) == 3
    ids = [i["id"] for i in piano["items"]]
    assert len(set(ids)) == 3, "i tre content_item devono avere id distinti, non essere lo stesso item ripetuto"
    assert all(i["content_group_size"] == 3 for i in piano["items"])
    assert {i["content_group_index"] for i in piano["items"]} == {1, 2, 3}


# ==================== 3. Le varianti interne non contano come post separati ====================
def test_varianti_interne_non_contano_come_post_distinti(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = _new_org()
        try:
            await _setup_content_org(db, org)
            plan_id, task_id, item_ids = await _make_content_item_task(db, org, quantity=1)
            assert len(item_ids) == 1  # un solo content_item richiesto
            _mock_semantic_ok(monkeypatch)
            monkeypatch.setattr(cc_pipeline.requesty_gateway, "genera_json", _fake_genera_json(_content_json("1")))
            task = await db.tasks.find_one({"id": task_id})
            task["approved_mode"] = "REALE"
            outcome = await execute_content_item_task(db, task)
            return outcome
        finally:
            await _cleanup(db, org)
            client.close()
    outcome = run(scenario())
    assert outcome.esito == "OK"
    assert outcome.requested_quantity == 1
    # Il contenuto generato ha 2 varianti interne (stesso post, formulazioni
    # alternative): produced_count conta i CONTENT_ITEM, non le varianti.
    assert outcome.produced_count == 1
    assert len(outcome.items[0]["content"]["varianti"]) == 2


# ==================== 4. Risultato parziale: mai dichiarato completato ====================
def test_risultato_parziale_non_dichiarato_completato(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = _new_org()
        try:
            await _setup_content_org(db, org)
            plan_id, task_id, item_ids = await _make_content_item_task(db, org, quantity=3, approved_cap=1.0)
            assert len(item_ids) == 3
            _mock_semantic_ok(monkeypatch)

            chiamate = {"n": 0}
            def comportamento(**kwargs):
                chiamate["n"] += 1
                if chiamate["n"] == 2:
                    # Il secondo contenuto generato risulta troppo corto ->
                    # validazione strutturale bloccata (BLOCCATO), non un
                    # errore di rete: nessun retry automatico.
                    return _fake_genera_json('{"titolo": "", "corpo": "x", "cta": "", "hashtags": [], "varianti": []}')(**kwargs)
                return _fake_genera_json(_content_json(str(chiamate["n"])))(**kwargs)
            monkeypatch.setattr(cc_pipeline.requesty_gateway, "genera_json", comportamento)

            await E.approve_task(db, plan_id, task_id, "appr@test")
            await E._auto_dispatch_scan_once(db)

            task_after = await db.tasks.find_one({"id": task_id})
            items_after = await db.content_items.find({"id": {"$in": item_ids}}).to_list(10)
            return task_after, items_after
        finally:
            await _cleanup(db, org)
            client.close()
    task_after, items_after = run(scenario())
    assert task_after["task_status"] != "COMPLETATA", task_after
    assert task_after["task_status"] == "BLOCCATA"
    assert any("2/3" in w or ("2" in w and "3" in w) for w in task_after["warnings"]), task_after["warnings"]
    pronti = [i for i in items_after if i["status"] == "IN_ATTESA_APPROVAZIONE"]
    assert len(pronti) == 2, "i due contenuti riusciti devono restare prodotti (bozza pronta), non scartati"
    assert task_after["deliverable_id"] is None, "nessun deliverable M2 quando il risultato e' parziale"


# ==================== 5. Recupero: non rigenera ne' rifattura gli elementi gia' completati ====================
def test_recupero_non_rigenera_elementi_gia_completati(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = _new_org()
        try:
            await _setup_content_org(db, org)
            plan_id, task_id, item_ids = await _make_content_item_task(db, org, quantity=2, approved_cap=1.0)
            _mock_semantic_ok(monkeypatch)

            from app.integrations.requesty_gateway import RequestyErroreSanificato

            chiamate = []
            def primo_giro(**kwargs):
                chiamate.append(1)
                if len(chiamate) == 1:
                    return _fake_genera_json(_content_json("A"))(**kwargs)
                raise RequestyErroreSanificato("errore_api", "Errore simulato sul secondo contenuto.")
            monkeypatch.setattr(cc_pipeline.requesty_gateway, "genera_json", primo_giro)

            task = await db.tasks.find_one({"id": task_id})
            task["approved_mode"] = "REALE"
            outcome1 = await execute_content_item_task(db, task)
            assert outcome1.esito == "ERRORE" and outcome1.produced_count == 1

            item1_dopo_primo = await db.content_items.find_one({"id": item_ids[0]})
            item2_dopo_primo = await db.content_items.find_one({"id": item_ids[1]})
            assert item1_dopo_primo["status"] == "IN_ATTESA_APPROVAZIONE"
            assert item2_dopo_primo["status"] == "BLOCCATO"  # eleggibile per un nuovo tentativo

            # Secondo tentativo (es. dopo un retry/riavvio): l'item 1, gia'
            # APPROVATO, non deve ricevere una seconda chiamata reale.
            chiamate_secondo_giro = []
            def secondo_giro(**kwargs):
                chiamate_secondo_giro.append(1)
                return _fake_genera_json(_content_json("B"))(**kwargs)
            monkeypatch.setattr(cc_pipeline.requesty_gateway, "genera_json", secondo_giro)

            task = await db.tasks.find_one({"id": task_id})
            task["approved_mode"] = "REALE"
            outcome2 = await execute_content_item_task(db, task)
            return outcome2, len(chiamate_secondo_giro)
        finally:
            await _cleanup(db, org)
            client.close()
    outcome2, n_chiamate_secondo_giro = run(scenario())
    assert n_chiamate_secondo_giro == 1, "solo l'item mancante deve generare una nuova chiamata reale, non quello gia' completato"
    assert outcome2.esito == "OK"
    assert outcome2.produced_count == 2


# ==================== 6/7. Contestazione semantica: mai approvata automaticamente, ma non blocca la bozza ====================
def test_contestazione_semantica_non_approvata_automaticamente_ma_bozza_e_leggibile(monkeypatch):
    """Ridisegno esplicito (vedi rapporto punto 2): l'approvazione del piano
    autorizza SOLO la spesa di generazione, mai la decisione editoriale —
    per QUALUNQUE item, contestato o no. La bozza contestata resta comunque
    leggibile (nessun vicolo cieco): il task si completa con un avviso
    esplicito che la segnala, non con un blocco tecnico."""
    async def scenario():
        client, db = _db(monkeypatch)
        org = _new_org()
        try:
            await _setup_content_org(db, org)
            plan_id, task_id, item_ids = await _make_content_item_task(db, org, quantity=1, approved_cap=1.0)
            monkeypatch.setattr(cc_pipeline.requesty_gateway, "genera_json", _fake_genera_json(_content_json("1")))
            monkeypatch.setattr(
                cc_pipeline, "semantic_validate_generic_content",
                lambda campi, contesto, brief="": {
                    "status": "CONTESTATO",
                    "affermazioni_contestate": [{"categoria": "benefici_generici", "campo": "corpo",
                                                 "frase": "affidabile", "parola_chiave": "affidabile"}],
                },
            )

            await E.approve_task(db, plan_id, task_id, "appr@test")
            await E._auto_dispatch_scan_once(db)

            task_after = await db.tasks.find_one({"id": task_id})
            item_after = await db.content_items.find_one({"id": item_ids[0]})
            deliverable = (await db.deliverables.find_one({"id": task_after["deliverable_id"]})
                          if task_after.get("deliverable_id") else None)
            return task_after, item_after, deliverable
        finally:
            await _cleanup(db, org)
            client.close()
    task_after, item_after, deliverable = run(scenario())
    # L'item resta esattamente dove lo lascia la generazione reale, in attesa
    # di una decisione umana — MAI approvato automaticamente, contestato o no.
    assert item_after["status"] == "IN_ATTESA_APPROVAZIONE", item_after
    assert item_after["approved"] is False
    assert item_after["semantic_check"]["status"] == "CONTESTATO"
    # Nessun vicolo cieco: il task si completa (la bozza e' stata prodotta),
    # non resta bloccato in attesa indefinita — ma la contestazione e'
    # dichiarata esplicitamente, mai nascosta dietro un "completato" muto.
    assert task_after["task_status"] == "COMPLETATA", task_after
    assert any("contestat" in w.lower() for w in task_after["warnings"]), task_after["warnings"]
    assert deliverable is not None, "la bozza contestata deve comunque essere leggibile tramite il deliverable"
    assert deliverable["content"]["contested_ids"] == [item_after["id"]]
    assert deliverable["content"]["items"][0]["content"] is not None
    assert deliverable["content"]["items"][0]["semantic_check"]["status"] == "CONTESTATO"


# ==================== 8. Costo e cap: il tetto del piano riflette la quantita' richiesta ====================
def test_cap_piano_proporzionale_alla_quantita_richiesta():
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            await M.create_m2_indexes(db)
            plan_id, task_id, item_ids = await _make_content_item_task(db, org, quantity=3)
            plan = await db.plans.find_one({"id": plan_id})
            task = await db.tasks.find_one({"id": task_id})
            return plan, task
        finally:
            await _cleanup(db, org)
            client.close()
    plan, task = run(scenario())
    assert plan["approved_cap"] > 0, "il tetto non deve restare 0 per una richiesta con costo reale atteso"
    assert plan["approved_cap"] == pytest.approx(0.03, abs=1e-9)
    assert task["inputs"]["cost"] == pytest.approx(0.03, abs=1e-9)
    assert task["inputs"]["requested_quantity"] == 3


# ==================== 9. Limite M2 (approved_cap) insufficiente: rispettato prima delle chiamate ====================
def test_cap_m2_insufficiente_blocca_prima_di_qualunque_chiamata(monkeypatch):
    async def scenario():
        client, db = _db(monkeypatch)
        org = _new_org()
        try:
            await _setup_content_org(db, org)
            # Tre item richiesti, ma il tetto approvato del piano copre solo
            # una singola generazione: il controllo M2 (budget_check, prima
            # ancora del gateway strumenti) deve bloccare l'esecuzione.
            plan_id, task_id, item_ids = await _make_content_item_task(db, org, quantity=3, approved_cap=0.01)
            calls = []
            def boom(**kwargs):
                calls.append(1)
                raise AssertionError("non deve mai chiamare Requesty: il tetto M2 e' gia' insufficiente")
            monkeypatch.setattr(cc_pipeline.requesty_gateway, "genera_json", boom)

            await E.approve_task(db, plan_id, task_id, "appr@test")
            await E._auto_dispatch_scan_once(db)

            task_after = await db.tasks.find_one({"id": task_id})
            return task_after, calls
        finally:
            await _cleanup(db, org)
            client.close()
    task_after, calls = run(scenario())
    assert calls == [], "nessuna chiamata reale con il tetto M2 gia' insufficiente per la quantita' richiesta"
    assert task_after["task_status"] == "BLOCCATA"


# ==================== 10. Canale multi-tipo: quantita' MAI moltiplicata per il numero di tipi ====================
def test_canale_multi_tipo_quantity_non_moltiplica_i_tipi():
    """Bug segnalato dalla prova reale: 'tre post' su un canale con piu'
    tipi ammessi produceva erroneamente tipi x quantity elementi invece di
    esattamente quantity. tiktok ammette 3 tipi (reel_script, storyboard,
    voiceover_script): quantity=2 deve dare ESATTAMENTE 2 content_types,
    ciclando i primi due tipi del canale, mai 6."""
    risultato = cc_decision.decide_content_plan(channel="tiktok", funnel_stage="MOFU",
                                                explicit_type=None, quantity=2)
    assert len(risultato["content_types"]) == 2
    assert risultato["content_types"] == ["reel_script", "storyboard"]

    # Controprova end-to-end: create_content_item deve produrre esattamente
    # 2 content_item (non 6) per lo stesso canale/quantita'.
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            await M.create_m2_indexes(db)
            piano = await cc_pipeline.create_content_item(
                db, org_id=org, actor="user-test", objective="Lancio prodotto", channel="tiktok",
                funnel_stage="MOFU", content_type=None, campaign_id=None, tone_override=None,
                constraints="", brief="due contenuti per tiktok", quantity=2,
            )
            return piano
        finally:
            await _cleanup(db, org)
            client.close()
    piano = run(scenario())
    assert len(piano["items"]) == 2, "quantity=2 su un canale a 3 tipi deve dare 2 content_item, non 6"
    assert {i["content_type"] for i in piano["items"]} == {"reel_script", "storyboard"}


# ==================== 11. Richiesta oltre il tetto: segnale esplicito, mai una soddisfazione silenziosa ====================
def test_quantita_oltre_tetto_massimo_segnala_troncamento_esplicito():
    """extract_requested_quantity_detailed e' cio' che brain/service.py usa
    (vedi app/brain/service.py righe ~996-1054) per decidere sia la
    quantita' EFFETTIVAMENTE applicata sia l'avviso esplicito di
    troncamento persistito sul task quando il testo ne chiede di piu' del
    tetto MASSIMO_CONSENTITO=10. Verifica diretta della funzione (unita'):
    la richiesta originale (raw=20) non deve mai sparire silenziosamente
    dietro una quantita' applicata piu' bassa."""
    from app.brain.quantity import extract_requested_quantity_detailed
    info = extract_requested_quantity_detailed("Genera 20 post per il lancio del prodotto")
    assert info["quantity"] == 10, "la quantita' APPLICATA resta limitata al tetto prudente"
    assert info["raw"] == 20, "la richiesta ORIGINALE non deve sparire: serve per l'avviso esplicito"
    assert info["truncated"] is True

    info_entro_tetto = extract_requested_quantity_detailed("Genera 5 post per il lancio")
    assert info_entro_tetto == {"quantity": 5, "raw": 5, "truncated": False}
    # NOTA (limite dichiarato): la persistenza di questo segnale sull'avviso
    # del task (brain/service.py::create_plan_with_brain, righe ~1021-1027)
    # e' stata verificata leggendo il codice sorgente, non con un test
    # automatico end-to-end — quella funzione attraversa l'intero triage del
    # Brain (selezione capability, possibili chiamate LLM per l'estrazione
    # del piano) e non e' isolabile senza un mocking sproporzionato rispetto
    # a questa verifica mirata. Il gap resta esplicitamente aperto nel
    # rapporto finale, non presentato come dimostrato.


# ==================== 12. Riserva atomica: due esecuzioni concorrenti sullo stesso tetto non possono entrambe passare ====================
def test_riserva_budget_concorrente_su_stessa_execution_non_supera_il_tetto():
    """Dimostra che _reserve_execution_budget (engine.py) e' davvero atomica:
    due 'worker' concorrenti (es. il poll periodico e un /tick manuale) che
    tentano di riservare 0.01 USD ciascuno su un'execution con tetto 0.01
    residuo NON possono entrambi riuscire — solo una riserva deve passare,
    l'altra deve tornare None senza alcuna scrittura parziale."""
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            execution_id = f"exec-race-{uuid.uuid4().hex[:8]}"
            await db.executions.insert_one({
                "id": execution_id, "organization_id": org, "plan_id": "plan-race-test",
                "real_cost": 0.0, "approved_cap": 0.01, "created_at": "2026-01-01T00:00:00Z",
            })
            risultati = await asyncio.gather(
                E._reserve_execution_budget(db, execution_id, 0.01),
                E._reserve_execution_budget(db, execution_id, 0.01),
            )
            execution_finale = await db.executions.find_one({"id": execution_id}, {"_id": 0})
            return risultati, execution_finale
        finally:
            await db.executions.delete_many({"organization_id": org})
            client.close()
    risultati, execution_finale = run(scenario())
    successi = [r for r in risultati if r is not None]
    falliti = [r for r in risultati if r is None]
    assert len(successi) == 1, f"esattamente una delle due riserve concorrenti deve riuscire, non {len(successi)}"
    assert len(falliti) == 1
    assert execution_finale["real_cost"] == pytest.approx(0.01, abs=1e-9), \
        "il costo reale non deve mai superare il tetto approvato per via di una corsa fra riserve concorrenti"


# ==================== 13. Ripresa: solo i blocchi TECNICI risalgono da soli, mai budget/pianificazione ====================
def test_ripresa_automatica_solo_per_blocchi_tecnici_risolti_non_per_budget():
    """resume_blocked_content_item_tasks deve riportare in coda un task
    BLOCCATA SOLO quando il motivo era tecnico (es. esito_incerto) E tutti i
    suoi content_item sono usciti dallo stato che richiedeva un nuovo
    tentativo. Un blocco di BUDGET o di PIANIFICAZIONE non deve mai risalire
    da solo: resta un difetto fermo finche' un umano non decide (nessun
    aumento automatico del tetto)."""
    async def scenario():
        client, db = _db()
        org = _new_org()
        try:
            await _setup_content_org(db, org)
            # --- Task A: bloccato per esito_incerto (TECNICO), item risolto nel frattempo ---
            plan_a, task_a, items_a = await _make_content_item_task(db, org, quantity=1, approved_cap=1.0)
            await db.tasks.update_one({"id": task_a}, {"$set": {
                "task_status": "BLOCCATA", "auto_dispatch_requested_at": "2026-01-01T00:00:00Z",
                "blocked_reason_code": "esito_incerto",
            }})
            # L'item viene risolto manualmente nel laboratorio Content Creator
            # (es. un operatore rigenera la bozza): non piu' in uno stato che
            # richiede un nuovo tentativo automatico.
            await db.content_items.update_one({"id": items_a[0]}, {"$set": {"status": "IN_ATTESA_APPROVAZIONE"}})

            # --- Task B: bloccato per budget_task_esaurito, item MAI risolto ma il motivo non e' tecnico ---
            plan_b, task_b, items_b = await _make_content_item_task(db, org, quantity=1, approved_cap=1.0)
            await db.tasks.update_one({"id": task_b}, {"$set": {
                "task_status": "BLOCCATA", "auto_dispatch_requested_at": "2026-01-01T00:00:00Z",
                "blocked_reason_code": "budget_task_esaurito",
            }})
            await db.content_items.update_one({"id": items_b[0]}, {"$set": {"status": "IN_ATTESA_APPROVAZIONE"}})

            # --- Task C: bloccato per esito_incerto (TECNICO) ma l'item NON e' ancora stato risolto ---
            plan_c, task_c, items_c = await _make_content_item_task(db, org, quantity=1, approved_cap=1.0)
            await db.tasks.update_one({"id": task_c}, {"$set": {
                "task_status": "BLOCCATA", "auto_dispatch_requested_at": "2026-01-01T00:00:00Z",
                "blocked_reason_code": "esito_incerto",
            }})
            # item_c resta nello stato originale (BOZZA/ESITO_INCERTO): non risolto.

            from app.m2.real_content_creator import resume_blocked_content_item_tasks
            ripresi = await resume_blocked_content_item_tasks(db)

            stati = {
                "a": (await db.tasks.find_one({"id": task_a}))["task_status"],
                "b": (await db.tasks.find_one({"id": task_b}))["task_status"],
                "c": (await db.tasks.find_one({"id": task_c}))["task_status"],
            }
            return ripresi, stati, {"a": task_a, "b": task_b, "c": task_c}
        finally:
            await _cleanup(db, org)
            client.close()
    ripresi, stati, ids = run(scenario())
    assert ids["a"] in ripresi, "il blocco tecnico risolto deve riprendere da solo"
    assert ids["b"] not in ripresi, "un blocco di budget non deve mai riprendere da solo"
    assert ids["c"] not in ripresi, "un blocco tecnico il cui item NON e' ancora risolto non deve riprendere"
    assert stati["a"] == "IN_CODA"
    assert stati["b"] == "BLOCCATA"
    assert stati["c"] == "BLOCCATA"


# ==================== 14. Costo REALE post-chiamata oltre il tetto: rilevato esplicitamente, blocca il seguito ====================
def test_costo_reale_post_chiamata_oltre_il_tetto_rilevato_e_blocca_task_successivi(monkeypatch):
    """LIMITE DICHIARATO (vedi rapporto, punto Budget): la riserva atomica
    pre-chiamata (_reserve_execution_budget) protegge solo la DECISIONE di
    partire con la chiamata, sulla base di una stima fissa (0.01 USD/
    elemento) — non puo' impedire che il costo EFFETTIVO, noto solo DOPO la
    risposta (dai token realmente restituiti), risulti piu' alto e superi il
    tetto approvato: quella spesa e' gia' avvenuta e non e' annullabile a
    posteriori. Cio' che e' garantito (vedi engine.py::_apply_actual_cost_delta):
    il superamento non resta un delta silenzioso — viene dichiarato in un
    avviso esplicito sul task, marcato sull'execution
    (budget_overrun_detected), e blocca ogni task SUCCESSIVO dello stesso
    piano finche' un umano non decide (mai un tetto aumentato da solo)."""
    async def scenario():
        client, db = _db(monkeypatch)
        org = _new_org()
        try:
            await _setup_content_org(db, org)
            # cap = stima = 0.01 USD (un solo elemento): la riserva pre-chiamata passa esattamente al limite.
            plan_id, task_id, item_ids = await _make_content_item_task(db, org, quantity=1, approved_cap=0.01)
            _mock_semantic_ok(monkeypatch)

            def genera_json_costoso(**kwargs):
                from app.integrations.requesty_gateway import RisultatoGenerazioneRequesty
                # 6000 token in ingresso: costo reale post-chiamata = 6000 * PRICE_PER_TOKEN (0.000002) = 0.012 USD,
                # ben oltre la stima fissa di 0.01 USD/elemento usata per la riserva pre-chiamata.
                return RisultatoGenerazioneRequesty(testo=_content_json("costoso"), modello_effettivo="anthropic/claude-sonnet-4-5",
                                                    latenza_ms=50, input_tokens=6000, output_tokens=0, troncata=False)
            monkeypatch.setattr(cc_pipeline.requesty_gateway, "genera_json", genera_json_costoso)

            await E.approve_task(db, plan_id, task_id, "appr@test")
            await E._auto_dispatch_scan_once(db)

            task_after = await db.tasks.find_one({"id": task_id})
            execution_after = await db.executions.find_one({"plan_id": plan_id}, {"_id": 0})

            # Un SECONDO task sullo STESSO piano/execution (es. un'altra
            # richiesta di contenuto approvata dopo la prima, stessa
            # execution): deve essere bloccato SENZA alcuna nuova chiamata
            # reale, perche' l'execution e' gia' marcata in superamento.
            piano2 = await cc_pipeline.create_content_item(
                db, org_id=org, actor="user-test", objective="Promuovere SPI Tool", channel="Instagram",
                funnel_stage="TOFU", content_type="post_social", campaign_id=None, tone_override=None,
                constraints="", brief="secondo contenuto sullo stesso piano", quantity=1,
            )
            item2_id = piano2["items"][0]["id"]
            task2_id = M.new_id("task")
            await db.tasks.insert_one({
                "id": task2_id, "organization_id": org, "plan_id": plan_id,
                "goal_id": (await db.plans.find_one({"id": plan_id}))["goal_id"], "version": 1, "seq": 2,
                "name": "Content Creator — secondo contenuto", "agent_id": "content-creator",
                "deliverable_type": "content_item",
                "inputs": {"cost": 0.01, "requested_quantity": 1,
                          "deliverable_override": {"content_item_ids": [item2_id], "mode": "REALE",
                                                   "note": "Genera e approva il contenuto in Content Creator."}},
                "depends_on": [], "task_status": "IN_ATTESA_APPROVAZIONE", "approved": False, "attempt": 0,
                "idempotency_key": f"{plan_id}:1:{task2_id}", "lease_owner": None, "lease_expires_at": None,
                "tokens_input": 0, "tokens_output": 0, "cost": 0.0, "deliverable_id": None, "warnings": [],
                "confirmed": False, "started_at": None, "finished_at": None, "mode": "SIMULAZIONE",
                "created_by": "user-test", "updated_by": "user-test",
                "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
            })
            calls = []
            def boom(**kwargs):
                calls.append(1)
                raise AssertionError("nessuna chiamata reale deve partire con l'execution gia' in superamento")
            monkeypatch.setattr(cc_pipeline.requesty_gateway, "genera_json", boom)
            await E.approve_task(db, plan_id, task2_id, "appr@test")
            await E._auto_dispatch_scan_once(db)
            task2_after = await db.tasks.find_one({"id": task2_id})

            return task_after, execution_after, task2_after, calls
        finally:
            await _cleanup(db, org)
            client.close()
    task_after, execution_after, task2_after, calls = run(scenario())
    # La prima generazione riesce comunque (contenuto valido): il task si completa normalmente.
    assert task_after["task_status"] == "COMPLETATA", task_after
    assert task_after["cost"] == pytest.approx(0.012, abs=1e-6), \
        "il costo effettivo riconciliato deve riflettere i token reali, non restare fermo alla stima"
    assert any("superato il tetto approvato" in w for w in task_after["warnings"]), task_after["warnings"]
    assert execution_after["real_cost"] > execution_after["approved_cap"]
    assert execution_after["budget_overrun_detected"] is True

    # Il secondo task, sulla STESSA execution ormai in superamento, viene
    # bloccato PRIMA di qualunque nuova chiamata reale.
    assert calls == [], "nessuna nuova chiamata reale deve partire su un'execution gia' in superamento"
    assert task2_after["task_status"] == "BLOCCATA", task2_after
    assert task2_after["blocked_reason_code"] == "budget_overrun_rilevato"
