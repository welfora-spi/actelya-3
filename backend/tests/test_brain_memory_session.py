"""Brain — test puri per la memoria temporanea di sessione (Blocco C,
memory/session.py). Nessun Mongo, nessuna scrittura su disco, nessuna
rete (socket bloccato per tutta la durata dei test): ogni test crea una
propria SessionStore isolata, mai il singleton di processo."""
import socket
import threading

import pytest

from app.brain.memory.session import (
    LimiteMemoriaSuperato,
    SessioneNonTrovata,
    SessionStore,
)


class _NetworkCallAttempted(Exception):
    pass


@pytest.fixture(autouse=True)
def block_all_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise _NetworkCallAttempted("Tentativo di apertura socket bloccato nei test brain.")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


# ---------------- 10. creazione sessione ----------------
def test_creazione_sessione_valori_iniziali():
    store = SessionStore()
    sess = store.create_session(original_request="Crea una strategia per il mio negozio.")
    assert sess["session_id"]
    assert sess["original_request"] == "Crea una strategia per il mio negozio."
    assert sess["status"] == "CREATED"
    assert sess["activeAgentIds"] == []
    assert sess["clarifications"] == [] and sess["decisions"] == [] and sess["handoffs"] == []
    assert sess["warnings"] == [] and sess["errors"] == []


def test_creazione_sessione_idempotente_con_stesso_id():
    store = SessionStore()
    s1 = store.create_session(session_id="sess-fisso", original_request="prima richiesta")
    s2 = store.create_session(session_id="sess-fisso", original_request="seconda richiesta (ignorata)")
    assert s1 == s2
    assert store.get_session("sess-fisso")["original_request"] == "prima richiesta"


# ---------------- 11. recupero per session, plan e goal ----------------
def test_recupero_per_session_plan_goal():
    store = SessionStore()
    s1 = store.create_session(original_request="r1")
    s2 = store.create_session(original_request="r2")
    store.update_session(s1["session_id"], plan_id="plan-1", goal_id="goal-1")
    store.update_session(s2["session_id"], plan_id="plan-1", goal_id="goal-2")

    assert store.get_session(s1["session_id"])["original_request"] == "r1"
    assert store.get_session("inesistente") is None

    per_piano = store.find_by_plan_id("plan-1")
    assert {r["session_id"] for r in per_piano} == {s1["session_id"], s2["session_id"]}

    per_goal = store.find_by_goal_id("goal-2")
    assert [r["session_id"] for r in per_goal] == [s2["session_id"]]


# ---------------- 12. aggiornamento sessione ----------------
def test_update_session_aggiorna_solo_i_campi_scalari_passati():
    store = SessionStore()
    sess = store.create_session(original_request="r")
    aggiornata = store.update_session(sess["session_id"], status="NEEDS_CLARIFICATION",
                                       activeAgentIds=["resp-marketing"])
    assert aggiornata["status"] == "NEEDS_CLARIFICATION"
    assert aggiornata["activeAgentIds"] == ["resp-marketing"]
    assert aggiornata["original_request"] == "r"  # invariato


def test_update_session_su_campo_lista_solleva_valueerror():
    store = SessionStore()
    sess = store.create_session(original_request="r")
    with pytest.raises(ValueError):
        store.update_session(sess["session_id"], decisions=["non ammesso qui"])


def test_update_session_su_sessione_inesistente_solleva():
    store = SessionStore()
    with pytest.raises(SessioneNonTrovata):
        store.update_session("non-esiste", status="READY")


def test_append_to_session_aggiunge_senza_sovrascrivere():
    store = SessionStore()
    sess = store.create_session(original_request="r")
    sid = sess["session_id"]
    store.append_to_session(sid, "decisions", {"decision": "AGENT_SELECTED"})
    store.append_to_session(sid, "decisions", {"decision": "PLAN_ALLOWED"})
    aggiornata = store.get_session(sid)
    assert [d["decision"] for d in aggiornata["decisions"]] == ["AGENT_SELECTED", "PLAN_ALLOWED"]


def test_append_to_session_su_campo_scalare_solleva_valueerror():
    store = SessionStore()
    sess = store.create_session(original_request="r")
    with pytest.raises(ValueError):
        store.append_to_session(sess["session_id"], "status", "READY")


# ---------------- 13. copie difensive ----------------
def test_get_session_ritorna_copia_difensiva():
    store = SessionStore()
    sess = store.create_session(original_request="r")
    letta = store.get_session(sess["session_id"])
    letta["activeAgentIds"].append("iniettato")
    letta["business_context"]["hacked"] = True
    ancora = store.get_session(sess["session_id"])
    assert ancora["activeAgentIds"] == []
    assert "hacked" not in ancora["business_context"]


def test_update_session_non_e_influenzata_da_mutazioni_esterne_del_dict_passato():
    store = SessionStore()
    sess = store.create_session(original_request="r")
    ctx = {"azienda": "Bakery"}
    store.update_session(sess["session_id"], business_context=ctx)
    ctx["azienda"] = "MANOMESSO"
    assert store.get_session(sess["session_id"])["business_context"]["azienda"] == "Bakery"


def test_snapshot_e_alias_di_get_session():
    store = SessionStore()
    sess = store.create_session(original_request="r")
    assert store.snapshot(sess["session_id"]) == store.get_session(sess["session_id"])


# ---------------- 14. cancellazione e reset ----------------
def test_delete_session():
    store = SessionStore()
    sess = store.create_session(original_request="r")
    assert store.delete_session(sess["session_id"]) is True
    assert store.get_session(sess["session_id"]) is None
    assert store.delete_session(sess["session_id"]) is False  # già eliminata: nessun errore


def test_reset_azzera_completamente_lo_store():
    store = SessionStore()
    store.create_session(original_request="r1")
    store.create_session(original_request="r2")
    store.reset()
    assert store.find_by_plan_id("qualsiasi") == []
    nuova = store.create_session(session_id="dopo-reset", original_request="r3")
    assert nuova["session_id"] == "dopo-reset"


# ---------------- 15. limite numero sessioni ----------------
def test_limite_numero_sessioni_rifiuta_senza_eliminare_le_esistenti():
    store = SessionStore(max_sessions=2)
    store.create_session(session_id="s1", original_request="r1")
    store.create_session(session_id="s2", original_request="r2")
    with pytest.raises(LimiteMemoriaSuperato):
        store.create_session(session_id="s3", original_request="r3")
    # nessuna sessione attiva eliminata in silenzio
    assert store.get_session("s1") is not None
    assert store.get_session("s2") is not None
    assert store.get_session("s3") is None


# ---------------- 16. limite dimensione payload ----------------
def test_limite_dimensione_payload_rifiuta_elemento_troppo_grande():
    store = SessionStore(max_payload_bytes=100)
    sess = store.create_session(original_request="r")
    sid = sess["session_id"]
    grande = {"testo": "x" * 1000}
    with pytest.raises(LimiteMemoriaSuperato):
        store.append_to_session(sid, "decisions", grande)
    # nessun elemento aggiunto nonostante il rifiuto
    assert store.get_session(sid)["decisions"] == []


def test_limite_dimensione_payload_su_creazione_sessione():
    store = SessionStore(max_payload_bytes=10)
    with pytest.raises(LimiteMemoriaSuperato):
        store.create_session(original_request="una richiesta decisamente troppo lunga per il limite")


# ---------------- 17. thread-safety ----------------
def test_append_concorrente_da_piu_thread_non_perde_elementi():
    store = SessionStore(max_events_per_session=10_000)
    sess = store.create_session(original_request="r")
    sid = sess["session_id"]
    n_thread, n_per_thread = 8, 25

    def worker(i):
        for j in range(n_per_thread):
            store.append_to_session(sid, "decisions", {"thread": i, "seq": j})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_thread)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    finale = store.get_session(sid)
    assert len(finale["decisions"]) == n_thread * n_per_thread


def test_create_session_concorrente_rispetta_il_limite_esatto():
    store = SessionStore(max_sessions=5)
    esiti = []
    lock = threading.Lock()

    def worker(i):
        try:
            store.create_session(session_id=f"s{i}", original_request="r")
            with lock:
                esiti.append("ok")
        except LimiteMemoriaSuperato:
            with lock:
                esiti.append("rifiutata")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert esiti.count("ok") == 5
    assert esiti.count("rifiutata") == 15


# ---------------- 18. redazione credenziali ----------------
def test_redazione_credenziali_in_business_context():
    store = SessionStore()
    sess = store.create_session(original_request="r")
    store.update_session(sess["session_id"], business_context={
        "azienda": "Bakery & Coffee", "api_key": "sk-segreta-123", "note": {"password": "abc123"},
    })
    ctx = store.get_session(sess["session_id"])["business_context"]
    assert ctx["azienda"] == "Bakery & Coffee"
    assert ctx["api_key"] == "[REDACTED]"
    assert ctx["note"]["password"] == "[REDACTED]"


def test_redazione_credenziali_in_elemento_appeso():
    store = SessionStore()
    sess = store.create_session(original_request="r")
    sid = sess["session_id"]
    store.append_to_session(sid, "decisions", {"decision": "X", "token": "shhh", "authorization": "Bearer xyz"})
    d = store.get_session(sid)["decisions"][0]
    assert d["token"] == "[REDACTED]"
    assert d["authorization"] == "[REDACTED]"
    assert d["decision"] == "X"


# ---------------- zero traffico di rete (verifica statica aggiuntiva) ----------------
def test_session_module_non_importa_librerie_di_rete_o_db():
    import ast
    import pathlib

    from app.brain.memory import session as mod

    source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
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
