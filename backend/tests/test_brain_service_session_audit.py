"""Brain — test puri per l'integrazione di memoria di sessione + audit nel
service (Blocco C, service.py::prepare_brain_session/create_plan_with_brain/
inspect_session). Copre SOLO il tratto del flusso che non richiede MongoDB:
prepare_brain_session() (triage + selezione agenti + memoria + audit) è
PURA per costruzione, e create_plan_with_brain() ritorna prima di toccare
qualunque `db` per ogni stato diverso da READY. Nessun Mongo, nessuna rete
(socket bloccato per tutta la durata dei test), nessun server avviato."""
import asyncio
import os
import socket

# app.brain.service importa app.m2.engine -> app.db -> app.config, che legge
# MONGO_URL/DB_NAME da os.environ AL MOMENTO DELL'IMPORT (solo per costruire
# la stringa di connessione: AsyncIOMotorClient non apre alcun socket finché
# non si esegue un'operazione async). Nessun test in questo file esegue mai
# un'operazione su `db` (i percorsi READY passano db=None e non lo toccano
# affatto): il valore è un segnaposto MAI usato per una connessione reale, e
# block_all_network sotto intercetterebbe comunque qualunque tentativo.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "actelya3_test_unused")

import pytest

from app.brain import service as SVC
from app.brain.audit.memory_audit import (
    EVENT_AGENT_EXCLUDED,
    EVENT_AGENT_SELECTED,
    EVENT_CLARIFICATION_REQUIRED,
    EVENT_EXTERNAL_ACTION_BLOCKED,
    EVENT_PLAN_ALLOWED,
    EVENT_PLAN_BLOCKED,
    EVENT_REQUEST_RECEIVED,
    get_audit_log,
)
from app.brain.memory.session import get_session_store
from app.brain.planning.agent_selector import (
    STATUS_BLOCKED_RISK,
    STATUS_NEEDS_CLARIFICATION,
    STATUS_READY,
    STATUS_UNSUPPORTED,
)


class _NetworkCallAttempted(Exception):
    pass


@pytest.fixture(autouse=True)
def block_all_network(monkeypatch):
    """Blocca solo le connessioni di rete REALI in uscita (socket.create_
    connection): a differenza degli altri file di test brain, qui alcuni
    casi usano asyncio.run(), che su Windows crea internamente una
    ProactorEventLoop e apre un self-pipe locale con socket.socket() — non
    un'uscita di rete. Bloccare anche socket.socket() romperebbe l'event
    loop stesso, non una chiamata esterna del brain."""
    def _blocked(*args, **kwargs):
        raise _NetworkCallAttempted("Tentativo di connessione di rete bloccato nei test brain.")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


@pytest.fixture(autouse=True)
def reset_singleton_stores():
    """service.py usa i singleton di processo (get_session_store()/
    get_audit_log()): li azzeriamo prima e dopo ogni test per isolamento
    completo tra un caso e l'altro."""
    get_session_store().reset()
    get_audit_log().reset()
    yield
    get_session_store().reset()
    get_audit_log().reset()


def run(coro):
    return asyncio.run(coro)


FOCACCINE_GOAL = (
    "Prepara una campagna social per pubblicizzare le focaccine artigianali del "
    "Bakery & Coffee di Merate. Crea una strategia locale, un piano editoriale e "
    "tre post per Instagram e Facebook rivolti alle famiglie e ai lavoratori della "
    "zona. Usa dati simulati, non contattare clienti e non pubblicare nulla."
)
GOAL_AMBIGUO = "Fai qualcosa di utile per me"
GOAL_FUORI_DOMINIO = "Traduci il sito in giapponese per il Bakery & Coffee di Merate."
GOAL_RISCHIOSO = "Crea una campagna per truffare i clienti del Bakery & Coffee di Merate."


# ---------------- 23. selezione agenti registrata nell'audit ----------------
def test_agenti_selezionati_ed_esclusi_registrati_nellaudit():
    prep = SVC.prepare_brain_session(FOCACCINE_GOAL)
    assert prep["selection"].status == STATUS_READY

    eventi = get_audit_log().filter(session_id=prep["session_id"])
    selezionati = [e for e in eventi if e["event_type"] == EVENT_AGENT_SELECTED]
    esclusi = [e for e in eventi if e["event_type"] == EVENT_AGENT_EXCLUDED]

    agent_ids_selezionati = {e["metadata"]["agent_id"] for e in selezionati}
    assert agent_ids_selezionati == set(prep["selection"].activeAgentIds)
    assert agent_ids_selezionati == {"resp-marketing", "social-media-manager", "copywriter", "resp-compliance"}
    assert esclusi  # almeno un agente non convocato per questa richiesta è tracciato come escluso

    assert prep["session_state"]["activeAgentIds"] == prep["selection"].activeAgentIds
    assert prep["session_state"]["status"] == STATUS_READY


# ---------------- 24. richiesta ambigua registrata correttamente ----------------
def test_richiesta_ambigua_registrata_correttamente():
    prep = SVC.prepare_brain_session(GOAL_AMBIGUO)
    assert prep["selection"].status == STATUS_NEEDS_CLARIFICATION

    eventi = get_audit_log().filter(session_id=prep["session_id"])
    tipi = [e["event_type"] for e in eventi]
    assert EVENT_REQUEST_RECEIVED in tipi
    assert EVENT_CLARIFICATION_REQUIRED in tipi
    assert EVENT_PLAN_ALLOWED not in tipi

    assert prep["session_state"]["status"] == STATUS_NEEDS_CLARIFICATION
    assert prep["session_state"]["clarifications"]  # domande di chiarimento salvate in memoria


# ---------------- 25. piano bloccato registrato correttamente ----------------
def test_piano_bloccato_per_rischio_registrato_correttamente():
    prep = SVC.prepare_brain_session(GOAL_RISCHIOSO)
    assert prep["selection"].status == STATUS_BLOCKED_RISK

    tipi = [e["event_type"] for e in get_audit_log().filter(session_id=prep["session_id"])]
    assert EVENT_PLAN_BLOCKED in tipi
    assert EVENT_EXTERNAL_ACTION_BLOCKED in tipi
    assert prep["session_state"]["status"] == STATUS_BLOCKED_RISK


def test_piano_bloccato_per_dominio_non_supportato_registrato_correttamente():
    prep = SVC.prepare_brain_session(GOAL_FUORI_DOMINIO)
    assert prep["selection"].status == STATUS_UNSUPPORTED

    tipi = [e["event_type"] for e in get_audit_log().filter(session_id=prep["session_id"])]
    assert EVENT_PLAN_BLOCKED in tipi
    assert EVENT_EXTERNAL_ACTION_BLOCKED not in tipi  # non è un'azione esterna: solo fuori dominio


# ---------------- 26. nessun piano creato per stati diversi da READY ----------------
@pytest.mark.parametrize("testo", [GOAL_AMBIGUO, GOAL_FUORI_DOMINIO, GOAL_RISCHIOSO])
def test_nessun_piano_creato_per_stati_diversi_da_ready(testo):
    async def scenario():
        # db=None: create_plan_with_brain non deve MAI toccarlo per questi stati.
        return await SVC.create_plan_with_brain(None, "org-test", "user-test", testo)

    res = run(scenario())
    assert res["plan"] is None
    assert res["tasks"] == []
    assert res["requires_clarification"] is True
    assert "session_id" in res and "audit_event_ids" in res and "session_state" in res
    assert res["session_state"]["plan_id"] is None  # mai valorizzato per stati non-READY


# ---------------- 27. stessa richiesta -> comportamento deterministico ----------------
def test_stessa_richiesta_produce_lo_stesso_esito():
    prep1 = SVC.prepare_brain_session(FOCACCINE_GOAL, session_id="s-determinismo")
    forma1 = prep1["selection"].to_dict()
    sequenza1 = [(e["event_type"], e["decision"]) for e in
                 get_audit_log().filter(session_id="s-determinismo")]

    get_session_store().reset()
    get_audit_log().reset()

    prep2 = SVC.prepare_brain_session(FOCACCINE_GOAL, session_id="s-determinismo")
    forma2 = prep2["selection"].to_dict()
    sequenza2 = [(e["event_type"], e["decision"]) for e in
                 get_audit_log().filter(session_id="s-determinismo")]

    assert forma1 == forma2
    assert sequenza1 == sequenza2


# ---------------- test obbligatorio: caso "focaccine su Instagram e Facebook" ----------------
def test_caso_focaccine_instagram_facebook_puro_senza_mongo():
    goal = "Voglio pubblicizzare le focaccine artigianali del Bakery & Coffee di Merate su Instagram e Facebook."
    prep = SVC.prepare_brain_session(goal)

    selection = prep["selection"]
    assert selection.status == STATUS_READY
    assert selection.activeAgentIds  # agenti selezionati
    assert "copywriter" in selection.activeAgentIds
    assert "resp-compliance" in selection.activeAgentIds

    sess = prep["session_state"]
    assert sess["status"] == STATUS_READY
    assert sess["activeAgentIds"] == selection.activeAgentIds
    assert sess["original_request"] == goal

    eventi = get_audit_log().filter(session_id=prep["session_id"])
    tipi = [e["event_type"] for e in eventi]
    assert EVENT_REQUEST_RECEIVED in tipi
    assert EVENT_PLAN_ALLOWED in tipi
    assert EVENT_AGENT_SELECTED in tipi
    assert all(e["session_id"] == prep["session_id"] for e in eventi)

    # nessuna uscita esterna: garantito dal fixture block_all_network per
    # l'intera durata del test (qualunque tentativo di apertura socket
    # avrebbe sollevato _NetworkCallAttempted prima di arrivare qui).


def test_inspect_session_pura_su_sessione_esistente_e_inesistente():
    prep = SVC.prepare_brain_session(FOCACCINE_GOAL)
    stato = SVC.inspect_session(prep["session_id"])
    assert stato["found"] is True
    assert stato["activeAgentIds"] == prep["selection"].activeAgentIds
    assert stato["plan_id"] is None  # nessun piano creato da prepare_brain_session da sola
    assert stato["audit_events"]
    assert stato["pending_approval"] is False  # RESULT_READY_FOR_APPROVAL non ancora registrato

    assoluto_inesistente = SVC.inspect_session("session-che-non-esiste")
    assert assoluto_inesistente["found"] is False
    assert assoluto_inesistente["audit_events"] == []


# ---------------- zero traffico di rete / nessun mongo (verifica statica aggiuntiva) ----------------
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
