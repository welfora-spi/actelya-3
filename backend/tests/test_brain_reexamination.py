"""Brain — riesame di una richiesta dopo risposte di chiarimento
(create_plan_with_brain(..., clarification=...)). Nessun MongoDB reale: un
_FakeDB in-memory copre il solo sottoinsieme dell'API Motor usato dal
percorso di creazione piano (stesso pattern di test_brain_mark_result_ready.py).
Nessuna rete (socket bloccato per l'intera durata dei test)."""
import copy
import os
import socket
from types import SimpleNamespace

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "actelya3_test_unused")

import pytest

from app.brain import service as SVC
from app.brain.audit.memory_audit import get_audit_log
from app.brain.memory.session import get_session_store
from app.brain.planning.agent_selector import STATUS_NEEDS_CLARIFICATION, STATUS_READY


class _NetworkCallAttempted(Exception):
    pass


@pytest.fixture(autouse=True)
def block_all_network(monkeypatch):
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


# ==================== _FakeDB (vedi test_brain_mark_result_ready.py) ====================
def _apply_set(doc, set_ops):
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

    async def to_list(self, n=None):
        docs = self._docs if n is None else self._docs[:n]
        return [copy.deepcopy(d) for d in docs]


class _FakeCollection:
    def __init__(self):
        self._docs = []

    async def insert_one(self, doc):
        self._docs.append(copy.deepcopy(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    def find(self, query=None, projection=None):
        query = query or {}
        return _FakeCursor([d for d in self._docs if all(d.get(k) == v for k, v in query.items())])

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
    def __init__(self):
        self._collections = {}

    def __getattr__(self, name):
        if name not in self._collections:
            self._collections[name] = _FakeCollection()
        return self._collections[name]


ORG = "org-test"
USER = "user-test"


def _clarify_payload(res):
    return {"missing_information": res["missing_information"], "answers": []}


# ==================== 1. richiesta vaga -> chiarimento con azienda+prodotto ====================
def test_richiesta_incompleta_mostra_chiarimenti():
    async def scenario():
        return await SVC.create_plan_with_brain(None, ORG, USER, "Crea un piano editoriale per Instagram.")

    res = run(scenario())
    assert res["status"] == STATUS_NEEDS_CLARIFICATION
    assert res["plan"] is None
    assert set(res["missing_information"]) == {"azienda", "prodotto"}
    assert len(res["clarifying_questions"]) == 2


# ==================== 2. risposte sufficienti -> READY + piano ====================
def test_risposte_sufficienti_creano_il_piano():
    async def scenario():
        db = _FakeDB()
        primo = await SVC.create_plan_with_brain(db, ORG, USER, "Crea un piano editoriale per Instagram.")
        secondo = await SVC.create_plan_with_brain(
            db, ORG, USER, primo["normalized_goal"],
            session_id=primo["session_id"],
            clarification={
                "missing_information": primo["missing_information"],
                "questions": primo["clarifying_questions"],
                "answers": ["ACTELYA 3", "panini artigianali"],
            },
        )
        return primo, secondo

    primo, secondo = run(scenario())
    assert secondo["status"] == STATUS_READY
    assert secondo["plan"] is not None
    assert secondo["requires_clarification"] is False
    # stessa sessione continuata, non una nuova
    assert secondo["session_id"] == primo["session_id"]


# ==================== 3. risposte parziali -> chiarimenti residui soltanto ====================
def test_risposte_parziali_mostrano_solo_i_chiarimenti_residui():
    async def scenario():
        db = _FakeDB()
        primo = await SVC.create_plan_with_brain(db, ORG, USER, "Crea un piano editoriale per Instagram.")
        secondo = await SVC.create_plan_with_brain(
            db, ORG, USER, primo["normalized_goal"],
            session_id=primo["session_id"],
            clarification={
                "missing_information": primo["missing_information"],
                "questions": primo["clarifying_questions"],
                "answers": ["ACTELYA 3", ""],  # prodotto lasciato vuoto
            },
        )
        return primo, secondo

    primo, secondo = run(scenario())
    assert secondo["status"] == STATUS_NEEDS_CLARIFICATION
    assert secondo["plan"] is None
    assert secondo["missing_information"] == ["prodotto"]
    assert len(secondo["clarifying_questions"]) == 1
    assert "prodotto" in secondo["clarifying_questions"][0].lower() or "servizio" in secondo["clarifying_questions"][0].lower()
    # l'azienda gia' risposta non deve ripresentarsi
    assert not any("azienda" in q.lower() for q in secondo["clarifying_questions"])


# ==================== 4. nessun piano creato mentre resta NEEDS_CLARIFICATION ====================
def test_nessun_piano_creato_se_resta_needs_clarification():
    async def scenario():
        db = _FakeDB()
        primo = await SVC.create_plan_with_brain(db, ORG, USER, "Crea un piano editoriale per Instagram.")
        secondo = await SVC.create_plan_with_brain(
            db, ORG, USER, primo["normalized_goal"], session_id=primo["session_id"],
            clarification={"missing_information": primo["missing_information"],
                          "questions": primo["clarifying_questions"], "answers": []},
        )
        return secondo

    res = run(scenario())
    assert res["status"] == STATUS_NEEDS_CLARIFICATION
    assert res["plan"] is None
    assert res["tasks"] == []


# ==================== 5. azienda/brand + prodotto espliciti fin dal primo giro -> READY subito ====================
def test_azienda_brand_e_prodotto_espliciti_ready_al_primo_giro():
    async def scenario():
        db = _FakeDB()
        return await SVC.create_plan_with_brain(
            db, ORG, USER,
            "Crea un piano editoriale per Instagram. Azienda/brand: ACTELYA 3. Prodotto: panini artigianali.",
        )

    res = run(scenario())
    assert res["status"] == STATUS_READY
    assert res["plan"] is not None
    assert res["requires_clarification"] is False
    assert not any("azienda" in q.lower() for q in res.get("clarifying_questions") or [])
