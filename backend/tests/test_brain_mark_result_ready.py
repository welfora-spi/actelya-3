"""Brain — Correzione C.0: RESULT_READY_FOR_APPROVAL NON deve essere
registrato alla sola creazione del piano, ma SOLO tramite
service.mark_result_ready_for_approval(), dopo verifica esplicita che il
risultato sia realmente pronto.

Nessun MongoDB reale: la parte che esercita create_plan_with_brain() usa un
piccolo database fittizio interamente in-memory (_FakeDB, definito in questo
file), che implementa SOLO il sottoinsieme dell'API di Motor realmente
usato da m2/engine.py::create_plan e da create_plan_with_brain per questo
percorso — nessun processo MongoDB, nessuna connessione di rete (bloccata
attivamente per tutta la durata dei test)."""
import copy
import os
import socket
from types import SimpleNamespace

# Stesso segnaposto usato in test_brain_service_session_audit.py: serve solo
# a soddisfare la lettura di os.environ["MONGO_URL"] al momento dell'import
# di app.brain.service (-> app.m2.engine -> app.db -> app.config).
# AsyncIOMotorClient non apre alcun socket alla costruzione, e in questo
# file il `db` reale non viene comunque mai usato: si usa sempre _FakeDB.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "actelya3_test_unused")

import pytest

from app.brain import service as SVC
from app.brain.audit.memory_audit import EVENT_RESULT_READY_FOR_APPROVAL, get_audit_log
from app.brain.memory.session import get_session_store
from app.brain.planning.handoff import HANDOFF_READY, HANDOFF_WAITING_DEPENDENCY


class _NetworkCallAttempted(Exception):
    pass


@pytest.fixture(autouse=True)
def block_all_network(monkeypatch):
    """Vedi test_brain_service_session_audit.py: solo le connessioni di
    rete REALI in uscita sono bloccate (asyncio.run() su Windows apre
    internamente un self-pipe locale con socket.socket(), non una
    connessione esterna)."""
    def _blocked(*args, **kwargs):
        raise _NetworkCallAttempted("Tentativo di connessione di rete bloccato nei test brain.")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


@pytest.fixture(autouse=True)
def reset_singleton_stores():
    get_session_store().reset()
    get_audit_log().reset()
    yield
    get_session_store().reset()
    get_audit_log().reset()


import asyncio


def run(coro):
    return asyncio.run(coro)


# ==================== _FakeDB: sostituto in-memory minimale di Motor ====================
def _apply_set(doc: dict, set_ops: dict) -> None:
    for key, value in set_ops.items():
        if "." in key:
            parts = key.split(".")
            target = doc
            for p in parts[:-1]:
                target = target.setdefault(p, {})
            target[parts[-1]] = value
        else:
            doc[key] = value


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field, direction=1):
        self._docs.sort(key=lambda d: d.get(field), reverse=(direction < 0))
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, n):
        return [copy.deepcopy(d) for d in self._docs[:n]]


class _FakeCollection:
    def __init__(self):
        self._docs: list[dict] = []

    async def insert_one(self, doc):
        self._docs.append(copy.deepcopy(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    def find(self, query=None, projection=None):
        query = query or {}
        matched = [d for d in self._docs if all(d.get(k) == v for k, v in query.items())]
        return _FakeCursor(matched)

    async def find_one(self, query=None, projection=None):
        query = query or {}
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                return copy.deepcopy(d)
        return None

    async def update_one(self, query, update):
        query = query or {}
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                _apply_set(d, update.get("$set", {}))
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    async def update_many(self, query, update):
        query = query or {}
        count = 0
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                _apply_set(d, update.get("$set", {}))
                count += 1
        return SimpleNamespace(matched_count=count)

    async def count_documents(self, query=None):
        query = query or {}
        return len([d for d in self._docs if all(d.get(k) == v for k, v in query.items())])


class _FakeDB:
    """Nessun processo MongoDB, nessuna rete: un dict di collezioni fittizie
    in memoria, sufficiente al solo percorso di create_plan_with_brain()
    esercitato da questi test (creazione piano, MAI esecuzione task)."""

    def __init__(self):
        self._collections: dict[str, _FakeCollection] = {}

    def __getattr__(self, name):
        if name not in self._collections:
            self._collections[name] = _FakeCollection()
        return self._collections[name]


FOCACCINE_GOAL = (
    "Prepara una campagna social per pubblicizzare le focaccine artigianali del "
    "Bakery & Coffee di Merate. Crea una strategia locale, un piano editoriale e "
    "tre post per Instagram e Facebook rivolti alle famiglie e ai lavoratori della "
    "zona. Usa dati simulati, non contattare clienti e non pubblicare nulla."
)


# ==================== creazione piano: NON genera RESULT_READY_FOR_APPROVAL ====================
def test_creazione_piano_non_genera_result_ready_for_approval():
    async def scenario():
        db = _FakeDB()
        return await SVC.create_plan_with_brain(db, "org-test", "user-test", FOCACCINE_GOAL)

    res = run(scenario())
    assert res["requires_clarification"] is False
    assert res["plan"] is not None

    eventi = get_audit_log().filter(session_id=res["session_id"])
    tipi = [e["event_type"] for e in eventi]
    assert EVENT_RESULT_READY_FOR_APPROVAL not in tipi


def test_sessione_dopo_la_creazione_e_plan_created():
    async def scenario():
        db = _FakeDB()
        return await SVC.create_plan_with_brain(db, "org-test", "user-test", FOCACCINE_GOAL)

    res = run(scenario())
    assert res["session_state"]["status"] == "PLAN_CREATED"
    assert res["session_state"]["plan_id"] == res["plan"]["id"]


def test_handoff_iniziali_sono_waiting_dependency():
    async def scenario():
        db = _FakeDB()
        return await SVC.create_plan_with_brain(db, "org-test", "user-test", FOCACCINE_GOAL)

    res = run(scenario())
    # Il piano CAMPAGNA per l'obiettivo focaccine ha task dipendenti
    # (editorial_plan dipende da marketing_strategy, ecc.): almeno un
    # handoff deve essere stato calcolato.
    handoffs = res["session_state"]["handoffs"]
    assert handoffs
    assert all(h["status"] == HANDOFF_WAITING_DEPENDENCY for h in handoffs)
    assert res.get("handoff_status") == HANDOFF_WAITING_DEPENDENCY or res.get("handoff_status") == "WAITING_DEPENDENCY"


# ==================== mark_result_ready_for_approval: condizioni mancanti ====================
def _piano_valido_base():
    tasks = [
        {"id": "t1", "task_status": "COMPLETATA", "approved": True},
        {"id": "t2", "task_status": "COMPLETATA", "approved": True},
    ]
    handoffs = [
        {"handoff_id": "h1", "status": HANDOFF_READY},
    ]
    deliverables = {
        "t1": {"valid": True, "status": "COMPLETATO"},
        "t2": {"valid": True, "status": "COMPLETATO_CON_AVVISI"},
    }
    return tasks, handoffs, deliverables


def test_risultato_incompleto_non_puo_essere_marcato_pronto():
    res = SVC.mark_result_ready_for_approval(
        session_id="s1", plan_id="p1", tasks=[], handoffs=[], deliverables_by_task_id={},
    )
    assert res["ready"] is False
    assert res["event_id"] is None
    assert get_audit_log().filter(session_id="s1", event_type=EVENT_RESULT_READY_FOR_APPROVAL) == []


def test_task_incompleto_blocca_la_marcatura():
    tasks, handoffs, deliverables = _piano_valido_base()
    tasks[0]["task_status"] = "IN_ESECUZIONE"
    res = SVC.mark_result_ready_for_approval(
        session_id="s1", plan_id="p1", tasks=tasks, handoffs=handoffs, deliverables_by_task_id=deliverables,
    )
    assert res["ready"] is False
    assert any("non completati" in m for m in res["missing_conditions"])
    assert get_audit_log().filter(session_id="s1", event_type=EVENT_RESULT_READY_FOR_APPROVAL) == []


def test_task_non_approvato_blocca_la_marcatura():
    tasks, handoffs, deliverables = _piano_valido_base()
    tasks[1]["approved"] = False
    res = SVC.mark_result_ready_for_approval(
        session_id="s1", plan_id="p1", tasks=tasks, handoffs=handoffs, deliverables_by_task_id=deliverables,
        requires_approval=True,
    )
    assert res["ready"] is False
    assert any("senza approvazione" in m for m in res["missing_conditions"])


def test_handoff_non_pronto_blocca_la_marcatura():
    tasks, handoffs, deliverables = _piano_valido_base()
    handoffs[0]["status"] = "WAITING_DEPENDENCY"
    res = SVC.mark_result_ready_for_approval(
        session_id="s1", plan_id="p1", tasks=tasks, handoffs=handoffs, deliverables_by_task_id=deliverables,
    )
    assert res["ready"] is False
    assert any("handoff non pronti" in m for m in res["missing_conditions"])


def test_deliverable_mancante_blocca_la_marcatura():
    tasks, handoffs, deliverables = _piano_valido_base()
    del deliverables["t2"]
    res = SVC.mark_result_ready_for_approval(
        session_id="s1", plan_id="p1", tasks=tasks, handoffs=handoffs, deliverables_by_task_id=deliverables,
    )
    assert res["ready"] is False
    assert any("t2" in m for m in res["missing_conditions"])


def test_deliverable_non_valido_blocca_la_marcatura():
    tasks, handoffs, deliverables = _piano_valido_base()
    deliverables["t1"]["valid"] = False
    res = SVC.mark_result_ready_for_approval(
        session_id="s1", plan_id="p1", tasks=tasks, handoffs=handoffs, deliverables_by_task_id=deliverables,
    )
    assert res["ready"] is False


def test_errore_bloccante_impedisce_la_marcatura():
    tasks, handoffs, deliverables = _piano_valido_base()
    res = SVC.mark_result_ready_for_approval(
        session_id="s1", plan_id="p1", tasks=tasks, handoffs=handoffs, deliverables_by_task_id=deliverables,
        blocking_errors=["errore critico simulato"],
    )
    assert res["ready"] is False
    assert any("errori bloccanti" in m for m in res["missing_conditions"])


# ==================== mark_result_ready_for_approval: caso valido + idempotenza ====================
def test_risultato_valido_genera_un_solo_evento():
    tasks, handoffs, deliverables = _piano_valido_base()
    res = SVC.mark_result_ready_for_approval(
        session_id="s1", plan_id="p1", tasks=tasks, handoffs=handoffs, deliverables_by_task_id=deliverables,
    )
    assert res["ready"] is True
    assert res["missing_conditions"] == []
    assert res["event_id"] is not None
    assert res["already_marked"] is False

    eventi = get_audit_log().filter(session_id="s1", plan_id="p1", event_type=EVENT_RESULT_READY_FOR_APPROVAL)
    assert len(eventi) == 1
    assert get_session_store().get_session("s1") is None  # sessione non esisteva: nessun errore, solo audit


def test_chiamata_duplicata_non_genera_eventi_duplicati():
    tasks, handoffs, deliverables = _piano_valido_base()
    res1 = SVC.mark_result_ready_for_approval(
        session_id="s1", plan_id="p1", tasks=tasks, handoffs=handoffs, deliverables_by_task_id=deliverables,
    )
    res2 = SVC.mark_result_ready_for_approval(
        session_id="s1", plan_id="p1", tasks=tasks, handoffs=handoffs, deliverables_by_task_id=deliverables,
    )
    assert res1["ready"] is True and res2["ready"] is True
    assert res1["event_id"] == res2["event_id"]
    assert res2["already_marked"] is True

    eventi = get_audit_log().filter(session_id="s1", plan_id="p1", event_type=EVENT_RESULT_READY_FOR_APPROVAL)
    assert len(eventi) == 1


def test_marcatura_aggiorna_lo_stato_della_sessione_se_esiste():
    store = get_session_store()
    sess = store.create_session(session_id="s-reale", original_request="r")
    store.update_session("s-reale", plan_id="p1", status="PLAN_CREATED")

    tasks, handoffs, deliverables = _piano_valido_base()
    res = SVC.mark_result_ready_for_approval(
        session_id="s-reale", plan_id="p1", tasks=tasks, handoffs=handoffs, deliverables_by_task_id=deliverables,
    )
    assert res["ready"] is True
    assert store.get_session("s-reale")["status"] == "RESULT_READY_FOR_APPROVAL"


# ==================== zero traffico esterno (verifica statica aggiuntiva) ====================
def test_service_non_importa_librerie_http_dirette():
    import ast
    import pathlib

    source = pathlib.Path(SVC.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "aiohttp", "smtplib", "ftplib"}
    assert not (found & forbidden)
