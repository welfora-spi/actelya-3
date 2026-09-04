"""Social Media Manager — memoria persistente (domains/social_memory.py).
Mongo locale reale, nessuna rete."""
import asyncio
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME
from app.domains import social_memory as mem


def run(coro):
    return asyncio.run(coro)


def _db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    return client, client[DB_NAME]


async def _scenario(fn):
    client, fresh_db = _db()
    org_id = f"org-test-mem-{uuid.uuid4().hex[:8]}"
    try:
        return await fn(fresh_db, org_id)
    finally:
        await fresh_db.social_memory_entries.delete_many({"organization_id": org_id})
        await fresh_db.social_analytics_snapshots.delete_many({"organization_id": org_id})
        client.close()


def test_tipo_non_riconosciuto_rifiutato():
    async def scenario(fresh_db, org_id):
        with pytest.raises(ValueError):
            await mem.record_entry(fresh_db, org_id, "tipo_inventato", summary="x")

    run(_scenario(scenario))


def test_nota_troppo_lunga_viene_troncata_non_rifiutata():
    async def scenario(fresh_db, org_id):
        testo = "a" * 1000
        doc = await mem.record_entry(fresh_db, org_id, "revision_pattern", summary=testo)
        assert len(doc["summary"]) <= mem.MAX_NOTE_CHARS
        assert doc["summary"].endswith("…")

    run(_scenario(scenario))


def test_org_senza_memoria_ritorna_contesto_vuoto():
    async def scenario(fresh_db, org_id):
        ctx = await mem.get_memory_context(fresh_db, org_id)
        assert ctx == {}
        assert mem.render_memory_block(ctx) == ""

    run(_scenario(scenario))


def test_get_memory_context_aggrega_per_tipo():
    async def scenario(fresh_db, org_id):
        await mem.record_entry(fresh_db, org_id, "format_preference", summary="reel verticale 9:16 approvato")
        await mem.record_entry(fresh_db, org_id, "revision_pattern", summary="chiesto piu' volte 'accorcia il testo'")
        ctx = await mem.get_memory_context(fresh_db, org_id)
        assert "reel verticale 9:16 approvato" in ctx["format_preferences"]
        assert "chiesto piu' volte 'accorcia il testo'" in ctx["revision_patterns"]
        assert ctx["n_entries"] == 2

        blocco = mem.render_memory_block(ctx)
        assert "orientativi" in blocco
        assert "reel verticale 9:16 approvato" in blocco

    run(_scenario(scenario))


def test_memoria_di_una_org_non_visibile_a_unaltra():
    async def scenario(fresh_db, org_a):
        org_b = f"org-test-mem-{uuid.uuid4().hex[:8]}"
        await mem.record_entry(fresh_db, org_a, "format_preference", summary="solo org A")
        ctx_b = await mem.get_memory_context(fresh_db, org_b)
        assert ctx_b == {}

    run(_scenario(scenario))


# ---------------- apprendimento (item 17): mai un consiglio senza dati sufficienti ----------------

async def _snapshot(fresh_db, org_id, *, package_id, source_kind, engagement):
    await fresh_db.social_analytics_snapshots.insert_one({
        "id": f"snap-{uuid.uuid4().hex[:8]}", "organization_id": org_id,
        "publishing_package_id": package_id, "source_kind": source_kind, "channel": "instagram",
        "data_available": True, "engagement_score": engagement,
        "impressions": 1000, "likes": 50, "comments": 5, "shares": 2, "saves": 3, "reach": None, "views": None, "clicks": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    })


def test_nessun_suggerimento_sotto_la_soglia_minima_di_campioni():
    async def scenario(fresh_db, org_id):
        await _snapshot(fresh_db, org_id, package_id="p1", source_kind="reel", engagement=8.0)
        # Un solo campione per 'reel', nessuno per 'flyer': dato insufficiente.
        suggerimenti = await mem.derive_learning_suggestions(fresh_db, org_id)
        assert suggerimenti == []

    run(_scenario(scenario))


def test_nessun_suggerimento_solo_dati_non_disponibili():
    async def scenario(fresh_db, org_id):
        # Snapshot dry-run reali (data_available=False, come nella produzione
        # di oggi): mai usati per un confronto, mai un suggerimento inventato.
        for i in range(3):
            await fresh_db.social_analytics_snapshots.insert_one({
                "id": f"snap-{i}", "organization_id": org_id, "publishing_package_id": f"p{i}",
                "source_kind": "reel", "channel": "instagram", "data_available": False,
                "engagement_score": None, "created_at": "2026-01-01T00:00:00+00:00",
            })
        suggerimenti = await mem.derive_learning_suggestions(fresh_db, org_id)
        assert suggerimenti == []

    run(_scenario(scenario))


def test_suggerimento_prodotto_con_dati_sufficienti_su_entrambi_i_formati():
    async def scenario(fresh_db, org_id):
        for i in range(2):
            await _snapshot(fresh_db, org_id, package_id=f"reel{i}", source_kind="reel", engagement=9.0)
        for i in range(2):
            await _snapshot(fresh_db, org_id, package_id=f"flyer{i}", source_kind="flyer", engagement=3.0)

        suggerimenti = await mem.derive_learning_suggestions(fresh_db, org_id)
        assert len(suggerimenti) == 1
        s = suggerimenti[0]
        assert s["tipo"] == "suggerimento"
        assert s["formato_consigliato"] == "reel"
        assert s["base_misurazioni"] == {"reel": 2, "flyer": 2}
        assert "reel" in s["riassunto"] and "flyer" in s["riassunto"]

    run(_scenario(scenario))
