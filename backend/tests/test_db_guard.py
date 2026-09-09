"""Test mirato — guardia contro scritture accidentali sul database
applicativo reale (backend/tests/conftest.py::_forbid_real_database_in_tests).

Dimostra il RIFIUTO PREVENTIVO: non tenta mai una scrittura reale per
verificarlo (la sentinella fallisce prima che una operazione di rete parta
anche solo per errore)."""
import asyncio

import pytest

from app import audit as audit_module


def test_guardia_blocca_il_db_reale_senza_sostituzione_esplicita():
    """Nessun monkeypatch di app.audit.db in questo test: resta la
    sentinella di default (autouse). Il solo accesso a 'db.audit_logs'
    dentro log_audit deve fallire PRIMA di qualunque scrittura — mai un
    tentativo di scrittura reale usato per dimostrarlo."""
    async def scenario():
        with pytest.raises(RuntimeError, match="Database applicativo reale"):
            await audit_module.log_audit(org_id="org-guard-test", user={"id": "t", "email": "t@test"},
                                         action="TEST_ACTION_MAI_SCRITTA")
    asyncio.run(scenario())


def test_guardia_non_interferisce_con_una_sostituzione_esplicita(monkeypatch):
    """Controprova: un test che sostituisce esplicitamente la dipendenza
    (come fanno test_m2_auto_dispatch.py/test_m2_content_quantity_and_review.py
    tramite il loro helper _db(monkeypatch)) continua a funzionare
    normalmente — la guardia non e' un blocco assoluto, solo un tetto che
    richiede una scelta esplicita."""
    class _FakeCollection:
        def __init__(self):
            self.inserted = []

        async def insert_one(self, doc):
            self.inserted.append(doc)

    class _FakeDb:
        def __init__(self):
            self.audit_logs = _FakeCollection()

    fake_db = _FakeDb()
    monkeypatch.setattr(audit_module, "db", fake_db)

    async def scenario():
        await audit_module.log_audit(org_id="org-guard-test", user={"id": "t", "email": "t@test"},
                                     action="TEST_ACTION_CONSENTITA")
        return fake_db.audit_logs.inserted

    inserted = asyncio.run(scenario())
    assert len(inserted) == 1
    assert inserted[0]["action"] == "TEST_ACTION_CONSENTITA"
