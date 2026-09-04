"""Brain — test per llm_understanding.py come orchestratore multi-provider
(CEO Agent 100% reale, blocchi 2/3/6/12): risoluzione configurazione per
organizzazione (primary/fallback ordinati da ai_connections), catena di
fallback che si ferma al primo successo, MAI un secondo tentativo sullo
stesso provider dopo un esito incerto, degrado sempre esplicito al
planner deterministico. Il trasporto verso i singoli provider e' un
doppio di test (llm_gateway.LLMProviderAdapter fittizio): la copertura del
trasporto HTTP reale dei quattro adapter vive in test_brain_llm_gateway.py."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.brain import llm_gateway
from app.brain import llm_understanding as LU
from app.brain.llm_gateway import LLMGatewayError, LLMResult


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client["actelya3_test"]


async def _cleanup(db, org):
    for c in ("settings", "ai_connections"):
        await db[c].delete_many({"organization_id": org})
    await db.settings.delete_many({"id": org})


def run(coro):
    return asyncio.run(coro)


class _AdapterFittizio:
    """Doppio di test per LLMProviderAdapter: comportamento controllato dal
    test (successo/errore/conteggio chiamate), nessuna rete."""

    def __init__(self, provider_id, comportamento):
        self.provider_id = provider_id
        self._comportamento = comportamento
        self.chiamate = 0

    def genera_json(self, **kwargs):
        self.chiamate += 1
        return self._comportamento(self.chiamate, **kwargs)


def _connessione(provider_type, model, priority=1, verified=True, active=True, timeout=20, max_tokens=1000):
    return {
        "provider_type": provider_type, "effective_model": model, "priority": priority,
        "verified": verified, "active": active, "timeout": timeout, "max_tokens": max_tokens,
        "id": f"aiconn-{uuid.uuid4().hex[:8]}", "api_key_encrypted": None,
    }


async def _setup(db, org, *, ai_real_mode=True, connessioni=None):
    await db.settings.update_one({"id": org}, {"$set": {"id": org, "ai_real_mode": ai_real_mode}}, upsert=True)
    for c in (connessioni or []):
        c["organization_id"] = org
        await db.ai_connections.insert_one(c)


PROPOSTA_JSON_VALIDA = (
    '{"intent": "aumentare i clienti", "strategia_proposta": "campagna locale mirata",'
    ' "priorita": "ALTA", "urgenza": "MEDIA", "agenti_suggeriti": [{"capability": "social", "motivazione": "richiesta esplicita"}]}'
)


# ---------------- resolve_org_llm_config ----------------
def test_db_none_nessuna_configurazione():
    cfg = run(LU.resolve_org_llm_config(None, "org-x"))
    assert cfg.ai_real_mode is False
    assert cfg.primary is None


def test_ai_real_mode_disattivo_letto_correttamente(monkeypatch):
    """resolve_org_llm_config() descrive COSA e' configurato indipendentemente
    da ai_real_mode (una connessione verificata resta 'primary' candidato);
    e' propose_plan() a rifiutarsi di usarla se ai_real_mode e' spento (vedi
    test_ai_real_mode_disattivo_degrada_a_deterministico piu' sotto) — le due
    responsabilita' restano separate."""
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, ai_real_mode=False, connessioni=[_connessione("openai", "gpt-4o")])
            cfg = await LU.resolve_org_llm_config(db, org)
            assert cfg.ai_real_mode is False
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_nessuna_connessione_verificata_nessun_primary(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, connessioni=[_connessione("openai", "gpt-4o", verified=False)])
            cfg = await LU.resolve_org_llm_config(db, org)
            assert cfg.primary is None
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_connessione_senza_modello_effettivo_scartata(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, connessioni=[_connessione("openai", "")])
            cfg = await LU.resolve_org_llm_config(db, org)
            assert cfg.primary is None
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_priorita_determina_primary_e_fallback_ordinati(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, connessioni=[
                _connessione("anthropic", "claude-x", priority=2),
                _connessione("openai", "gpt-4o", priority=1),
                _connessione("gemini", "gemini-x", priority=3),
            ])
            cfg = await LU.resolve_org_llm_config(db, org)
            assert cfg.primary.provider_type == "openai"
            assert [f.provider_type for f in cfg.fallbacks] == ["anthropic", "gemini"]
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_max_fallback_attempts_limita_la_catena(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await db.settings.update_one({"id": org}, {"$set": {
                "id": org, "ai_real_mode": True, "llm_max_fallback_attempts": 1,
            }}, upsert=True)
            for i, (pt, m) in enumerate([("openai", "a"), ("anthropic", "b"), ("gemini", "c")], start=1):
                c = _connessione(pt, m, priority=i)
                c["organization_id"] = org
                await db.ai_connections.insert_one(c)
            cfg = await LU.resolve_org_llm_config(db, org)
            assert len(cfg.fallbacks) == 1
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- propose_plan: degrado esplicito ----------------
def test_ai_real_mode_disattivo_degrada_a_deterministico():
    res = run(LU.propose_plan(None, "org-x", "voglio piu' clienti"))
    assert res.mode == LU.MODE_DETERMINISTICO
    assert "REALE" in res.motivo
    assert res.providers_tried == []


def test_ai_real_mode_disattivo_degrada_anche_con_connessione_configurata(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, ai_real_mode=False, connessioni=[_connessione("openai", "gpt-4o")])
            res = await LU.propose_plan(db, org, "voglio piu' clienti")
            assert res.mode == LU.MODE_DETERMINISTICO
            assert "REALE" in res.motivo
            assert res.providers_tried == []
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_ai_real_mode_attivo_senza_connessioni_degrada(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, connessioni=[])
            res = await LU.propose_plan(db, org, "voglio piu' clienti")
            assert res.mode == LU.MODE_DETERMINISTICO
            assert "connessione" in res.motivo.lower()
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- propose_plan: successo al primo tentativo, nessun fallback chiamato ----------------
def test_successo_primary_non_chiama_fallback(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, connessioni=[
                _connessione("openai", "gpt-4o", priority=1),
                _connessione("anthropic", "claude-x", priority=2),
            ])
            primary_ad = _AdapterFittizio("openai", lambda n, **kw: LLMResult(
                testo=PROPOSTA_JSON_VALIDA, provider="openai", modello_effettivo="gpt-4o",
                latenza_ms=10, input_tokens=5, output_tokens=5, troncata=False,
            ))
            fallback_ad = _AdapterFittizio("anthropic", lambda n, **kw: (_ for _ in ()).throw(
                AssertionError("il fallback non deve mai essere chiamato se il primary riesce")))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {"openai": primary_ad, "anthropic": fallback_ad, "gemini": None, "requesty": None})

            res = await LU.propose_plan(db, org, "voglio piu' clienti")
            assert res.mode == LU.MODE_REALE
            assert res.provider_effettivo == "openai"
            assert primary_ad.chiamate == 1
            assert fallback_ad.chiamate == 0
            assert len(res.providers_tried) == 1
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- propose_plan: primary fallisce, fallback riesce ----------------
def test_fallback_usato_solo_se_primary_fallisce(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, connessioni=[
                _connessione("openai", "gpt-4o", priority=1),
                _connessione("anthropic", "claude-x", priority=2),
            ])
            primary_ad = _AdapterFittizio("openai", lambda n, **kw: (_ for _ in ()).throw(
                LLMGatewayError("autenticazione", "credenziale non valida", "openai")))
            fallback_ad = _AdapterFittizio("anthropic", lambda n, **kw: LLMResult(
                testo=PROPOSTA_JSON_VALIDA, provider="anthropic", modello_effettivo="claude-x",
                latenza_ms=15, input_tokens=6, output_tokens=6, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {"openai": primary_ad, "anthropic": fallback_ad, "gemini": None, "requesty": None})

            res = await LU.propose_plan(db, org, "voglio piu' clienti")
            assert res.mode == LU.MODE_REALE
            assert res.provider_effettivo == "anthropic"
            assert len(res.providers_tried) == 2
            assert res.providers_tried[0].esito == "ERRORE"
            assert res.providers_tried[1].esito == "OK"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- propose_plan: tutti falliscono -> deterministico ----------------
def test_tutti_i_provider_falliscono_degrada_a_deterministico(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, connessioni=[
                _connessione("openai", "gpt-4o", priority=1),
                _connessione("anthropic", "claude-x", priority=2),
            ])
            primary_ad = _AdapterFittizio("openai", lambda n, **kw: (_ for _ in ()).throw(
                LLMGatewayError("rete", "irraggiungibile", "openai")))
            fallback_ad = _AdapterFittizio("anthropic", lambda n, **kw: (_ for _ in ()).throw(
                LLMGatewayError("limite_frequenza", "rate limit", "anthropic")))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {"openai": primary_ad, "anthropic": fallback_ad, "gemini": None, "requesty": None})

            res = await LU.propose_plan(db, org, "voglio piu' clienti")
            assert res.mode == LU.MODE_DETERMINISTICO
            assert res.proposta is None
            assert len(res.providers_tried) == 2
            assert "falliti" in res.motivo or "fallito" in res.motivo
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- esito incerto: mai un secondo tentativo sullo STESSO provider ----------------
def test_esito_incerto_non_ritenta_lo_stesso_provider_ma_puo_usare_un_fallback(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, connessioni=[
                _connessione("openai", "gpt-4o", priority=1),
                _connessione("anthropic", "claude-x", priority=2),
            ])
            primary_ad = _AdapterFittizio("openai", lambda n, **kw: (_ for _ in ()).throw(
                LLMGatewayError("esito_incerto", "timeout dopo invio", "openai")))
            fallback_ad = _AdapterFittizio("anthropic", lambda n, **kw: LLMResult(
                testo=PROPOSTA_JSON_VALIDA, provider="anthropic", modello_effettivo="claude-x",
                latenza_ms=15, input_tokens=6, output_tokens=6, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {"openai": primary_ad, "anthropic": fallback_ad, "gemini": None, "requesty": None})

            res = await LU.propose_plan(db, org, "voglio piu' clienti")
            assert primary_ad.chiamate == 1  # MAI un secondo tentativo sullo stesso provider
            assert res.mode == LU.MODE_REALE
            assert res.providers_tried[0].codice_errore == "esito_incerto"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


# ---------------- output non valido (JSON malformato / schema non conforme) ----------------
def test_json_malformato_tratta_come_fallimento_e_prova_il_fallback(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, connessioni=[
                _connessione("openai", "gpt-4o", priority=1),
                _connessione("anthropic", "claude-x", priority=2),
            ])
            primary_ad = _AdapterFittizio("openai", lambda n, **kw: LLMResult(
                testo="non e' un JSON {{{", provider="openai", modello_effettivo="gpt-4o",
                latenza_ms=10, input_tokens=1, output_tokens=1, troncata=False,
            ))
            fallback_ad = _AdapterFittizio("anthropic", lambda n, **kw: LLMResult(
                testo=PROPOSTA_JSON_VALIDA, provider="anthropic", modello_effettivo="claude-x",
                latenza_ms=15, input_tokens=6, output_tokens=6, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {"openai": primary_ad, "anthropic": fallback_ad, "gemini": None, "requesty": None})

            res = await LU.propose_plan(db, org, "voglio piu' clienti")
            assert res.mode == LU.MODE_REALE
            assert res.provider_effettivo == "anthropic"
            assert res.providers_tried[0].codice_errore == "risposta_non_valida"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())


def test_output_semanticamente_vuoto_e_trattato_come_fallimento(monkeypatch):
    async def scenario():
        client, db = _db()
        org = f"org-test-{uuid.uuid4().hex[:8]}"
        try:
            await _setup(db, org, connessioni=[_connessione("openai", "gpt-4o", priority=1)])
            primary_ad = _AdapterFittizio("openai", lambda n, **kw: LLMResult(
                testo='{"intent": "", "strategia_proposta": ""}', provider="openai", modello_effettivo="gpt-4o",
                latenza_ms=10, input_tokens=1, output_tokens=1, troncata=False,
            ))
            monkeypatch.setattr(llm_gateway, "ADAPTERS", {"openai": primary_ad, "anthropic": None, "gemini": None, "requesty": None})

            res = await LU.propose_plan(db, org, "voglio piu' clienti")
            assert res.mode == LU.MODE_DETERMINISTICO
            assert res.providers_tried[0].esito == "ERRORE"
            return True
        finally:
            await _cleanup(db, org)
            client.close()

    assert run(scenario())
