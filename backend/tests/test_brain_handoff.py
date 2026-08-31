"""Brain — test puri per l'handoff strutturato tra task (Blocco C,
planning/handoff.py). Nessun Mongo, nessuna rete (socket bloccato per
tutta la durata dei test): tutti i task/deliverable sono dizionari
costruiti a mano, esattamente nella forma prodotta da m2/models.py e
m2/deliverables.py, ma mai letti da un database reale."""
import socket

import pytest

from app.brain.planning import handoff as H


class _NetworkCallAttempted(Exception):
    pass


@pytest.fixture(autouse=True)
def block_all_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise _NetworkCallAttempted("Tentativo di apertura socket bloccato nei test brain.")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


PLAN = {"id": "plan-1", "plan_status": "APPROVATO"}


def _task(task_id, *, deliverable_type="marketing_strategy", depends_on=None,
          task_status="COMPLETATA", approved=True, agent_id="marketing_strategist"):
    return {
        "id": task_id, "plan_id": "plan-1", "deliverable_type": deliverable_type,
        "depends_on": depends_on or [], "task_status": task_status, "approved": approved,
        "agent_id": agent_id,
    }


def _deliverable(deliverable_id, task_id, *, version=1, status="COMPLETATO", valid=True,
                  deliverable_type="marketing_strategy", content=None):
    return {
        "id": deliverable_id, "plan_id": "plan-1", "task_id": task_id, "version": version,
        "status": status, "valid": valid, "deliverable_type": deliverable_type,
        "content": content if content is not None else {"title": "Strategia", "body": "contenuto sostanziale"},
    }


# ---------------- 1. handoff valido ----------------
def test_handoff_valido_e_ready():
    source = _task("t1")
    target = _task("t2", deliverable_type="editorial_plan", depends_on=["t1"], task_status="IN_ATTESA_APPROVAZIONE")
    deliv = _deliverable("d1", "t1")

    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv)

    assert h.status == H.HANDOFF_READY
    assert h.approval_status == H.APPROVAL_APPROVED
    assert h.content == deliv["content"]
    assert h.content_digest == H.compute_content_digest(deliv["content"])
    assert h.deliverable_id == "d1" and h.deliverable_version == 1
    assert h.source_capability == "strategy" and h.target_capability == "editorial"


# ---------------- 2. dipendenza mancante ----------------
def test_dipendenza_mancante_waiting_dependency():
    source = _task("t1", task_status="IN_CODA")  # non ancora completato
    target = _task("t2", depends_on=["t1"])
    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=None)
    assert h.status == H.HANDOFF_WAITING_DEPENDENCY
    assert h.content is None
    assert h.deliverable_id is None


def test_dipendenza_non_dichiarata_nel_dag_e_waiting_dependency():
    source = _task("t1")
    target = _task("t2", depends_on=["altro-task"])  # t1 non è tra le dipendenze dichiarate
    deliv = _deliverable("d1", "t1")
    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv)
    assert h.status == H.HANDOFF_WAITING_DEPENDENCY


# ---------------- 3. deliverable incompleto ----------------
def test_deliverable_incompleto_rejected_invalid():
    source = _task("t1")
    target = _task("t2", depends_on=["t1"])
    deliv = _deliverable("d1", "t1", content={})  # contenuto vuoto: incompleto
    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv)
    assert h.status == H.HANDOFF_REJECTED_INVALID
    assert h.content is None


def test_deliverable_bloccato_rejected_invalid():
    source = _task("t1")
    target = _task("t2", depends_on=["t1"])
    deliv = _deliverable("d1", "t1", status="BLOCCATO", valid=False)
    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv)
    assert h.status == H.HANDOFF_REJECTED_INVALID


# ---------------- 4. deliverable non approvato quando richiesto ----------------
def test_non_approvato_quando_richiesto_waiting_approval():
    source = _task("t1", approved=False)
    target = _task("t2", depends_on=["t1"])
    deliv = _deliverable("d1", "t1")
    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv,
                         requires_approval=True)
    assert h.status == H.HANDOFF_WAITING_APPROVAL
    assert h.approval_status == H.APPROVAL_PENDING
    assert h.content is None  # nessun contenuto trasferito prima dell'approvazione


def test_approvazione_non_richiesta_e_ready_anche_senza_approved():
    source = _task("t1", approved=False)
    target = _task("t2", depends_on=["t1"])
    deliv = _deliverable("d1", "t1")
    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv,
                         requires_approval=False)
    assert h.status == H.HANDOFF_READY
    assert h.approval_status == H.APPROVAL_NOT_REQUIRED


# ---------------- 5. versione obsoleta ----------------
def test_versione_obsoleta_blocked_integrity():
    source = _task("t1")
    target = _task("t2", depends_on=["t1"])
    deliv = _deliverable("d1", "t1", version=2)
    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv,
                         expected_deliverable_version=1)
    assert h.status == H.HANDOFF_BLOCKED_INTEGRITY


# ---------------- 6. digest alterato ----------------
def test_digest_alterato_blocked_integrity():
    source = _task("t1")
    target = _task("t2", depends_on=["t1"])
    deliv = _deliverable("d1", "t1")
    digest_atteso = "0" * 64  # sicuramente diverso dal digest reale
    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv,
                         expected_content_digest=digest_atteso)
    assert h.status == H.HANDOFF_BLOCKED_INTEGRITY


def test_digest_coerente_non_blocca():
    source = _task("t1")
    target = _task("t2", depends_on=["t1"])
    deliv = _deliverable("d1", "t1")
    digest_corretto = H.compute_content_digest(deliv["content"])
    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv,
                         expected_content_digest=digest_corretto)
    assert h.status == H.HANDOFF_READY


# ---------------- 7. deduplicazione dello stesso handoff ----------------
def test_stesso_handoff_produce_stesso_handoff_id():
    source = _task("t1")
    target = _task("t2", depends_on=["t1"])
    deliv = _deliverable("d1", "t1")
    h1 = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv)
    h2 = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv)
    assert h1.handoff_id == h2.handoff_id
    ledger = {h1.handoff_id: h1.to_dict()}
    ledger[h2.handoff_id] = h2.to_dict()
    assert len(ledger) == 1  # deduplicato per costruzione


def test_handoff_diverso_produce_id_diverso():
    source = _task("t1")
    target = _task("t2", depends_on=["t1"])
    deliv_v1 = _deliverable("d1", "t1", version=1)
    deliv_v2 = _deliverable("d1", "t1", version=2)
    h1 = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv_v1)
    h2 = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv_v2)
    assert h1.handoff_id != h2.handoff_id


# ---------------- 8. ordine delle dipendenze ----------------
def test_collect_task_handoffs_rispetta_ordine_del_dag():
    t1 = _task("t1", deliverable_type="marketing_strategy")
    t2 = _task("t2", deliverable_type="editorial_plan")
    t3 = _task("t3", deliverable_type="lead_gen_plan", depends_on=["t2", "t1"])  # ordine invertito nel DAG
    tasks_by_id = {"t1": t1, "t2": t2, "t3": t3}
    deliverables = {
        "t1": _deliverable("d1", "t1", deliverable_type="marketing_strategy"),
        "t2": _deliverable("d2", "t2", deliverable_type="editorial_plan"),
    }
    handoffs = H.collect_task_handoffs(
        plan=PLAN, target_task=t3, tasks_by_id=tasks_by_id, deliverables_by_task_id=deliverables,
    )
    assert [h.source_task_id for h in handoffs] == ["t2", "t1"]  # stesso ordine di depends_on
    assert H.all_handoffs_ready(handoffs) is True


def test_all_handoffs_ready_falso_se_una_dipendenza_non_pronta():
    t1 = _task("t1", task_status="IN_CODA")
    t2 = _task("t2", depends_on=["t1"])
    tasks_by_id = {"t1": t1, "t2": t2}
    handoffs = H.collect_task_handoffs(
        plan=PLAN, target_task=t2, tasks_by_id=tasks_by_id, deliverables_by_task_id={},
    )
    assert H.all_handoffs_ready(handoffs) is False
    assert handoffs[0].status == H.HANDOFF_WAITING_DEPENDENCY


# ---------------- 9. sorgente mai modificata ----------------
def test_source_task_target_task_deliverable_mai_modificati():
    import copy

    source = _task("t1")
    target = _task("t2", depends_on=["t1"])
    deliv = _deliverable("d1", "t1")
    source_prima, target_prima, deliv_prima = copy.deepcopy(source), copy.deepcopy(target), copy.deepcopy(deliv)

    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv)

    assert source == source_prima
    assert target == target_prima
    assert deliv == deliv_prima
    # il contenuto restituito è una copia: mutarlo non deve toccare il deliverable originale
    h.content["title"] = "MANOMESSO"
    assert deliv["content"]["title"] != "MANOMESSO"


def test_to_dict_restituisce_copie_difensive():
    source = _task("t1")
    target = _task("t2", depends_on=["t1"])
    deliv = _deliverable("d1", "t1")
    h = H.build_handoff(plan=PLAN, source_task=source, target_task=target, source_deliverable=deliv)

    d1 = h.to_dict()
    d1["content"]["title"] = "ALTERATO"
    d2 = h.to_dict()
    assert d2["content"]["title"] != "ALTERATO"


# ---------------- zero traffico di rete (verifica statica aggiuntiva) ----------------
def test_handoff_non_importa_librerie_di_rete_o_db():
    import ast
    import pathlib

    source = pathlib.Path(H.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "aiohttp", "smtplib", "socket", "ftplib", "pymongo", "motor"}
    assert not (found & forbidden)
