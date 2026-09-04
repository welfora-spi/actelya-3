"""Social Media Manager — memoria persistente (item 13, DECISIONE UFFICIALE
"COMPLETAMENTO END-TO-END SOCIAL MEDIA MANAGER").

brain/memory/session.py e' ESCLUSIVAMENTE in-memory (si perde ad ogni
riavvio del processo, per costruzione — vedi la sua docstring): serve a far
collaborare gli agenti nella stessa sessione, non a ricordare nulla tra una
richiesta e la successiva. Questo modulo aggiunge la memoria che DEVE
sopravvivere ai riavvii, in MongoDB, con una struttura esplicita e limitata:
- NON e' un dump indiscriminato della conversazione: solo voci tipizzate
  (ENTRY_TYPES), ciascuna con un riassunto troncato (MAX_NOTE_CHARS), mai il
  contenuto integrale di un progetto;
- ogni voce e' APPEND-ONLY, mai sovrascritta: la cronologia stessa e' già
  l'audit (ogni scrittura resta consultabile con la sua data/autore);
- get_memory_context()/render_memory_block() producono un blocco di prompt
  SEMPRE etichettato come preferenza/apprendimento pregresso, mai come fatto
  aziendale: il Fact Ledger (domains/knowledge.py) resta l'UNICA fonte di
  verità sui fatti, questa memoria non lo sostituisce né lo duplica;
- derive_learning_suggestions() distingue sempre dato misurato/inferenza/
  suggerimento (mai un consiglio silenzioso spacciato per fatto) e non
  produce alcun suggerimento sotto una soglia minima di campioni misurati."""
from __future__ import annotations

from typing import Optional

from ..models import new_id, now_iso

# Tipi di voce ammessi: whitelist chiusa, come in altri punti "di sicurezza"
# dell'app (es. brain/gateways/connector_gateway.py::ALLOWED_ACTION_TYPES).
ENTRY_TYPES = frozenset({
    "format_preference",   # formato scelto/approvato (reel|flyer): utile per capire cosa l'azienda preferisce
    "revision_pattern",    # nota di una richiesta di modifica (riassunto, mai il testo integrale del contenuto)
    "content_summary",     # breve riassunto di un contenuto approvato
    "publish_outcome",     # esito di un tentativo di pubblicazione (canale/formato/stato/dry_run)
    "performance_note",    # una metrica REALMENTE misurata da una pubblicazione (mai un valore inventato)
    "learning_suggestion", # suggerimento derivato da >=1 performance_note, sempre con base_misurazioni esplicita
})

MAX_NOTE_CHARS = 400  # una voce troppo lunga viene troncata, mai rifiutata: sempre qualcosa di utile registrato
MIN_SAMPLE_SIZE = 2   # sotto questa soglia derive_learning_suggestions() non propone nulla: dato insufficiente


def _tronca(testo: str) -> str:
    testo = (testo or "").strip()
    if len(testo) <= MAX_NOTE_CHARS:
        return testo
    return testo[:MAX_NOTE_CHARS - 1].rstrip() + "…"


async def record_entry(db, org_id: str, entry_type: str, *, summary: str,
                       data: Optional[dict] = None, source_project_id: Optional[str] = None,
                       actor: str = "system") -> dict:
    """Registra UNA voce di memoria. Mai una scrittura silenziosa di un tipo
    non riconosciuto: solleva ValueError esplicito (stesso stile "whitelist
    chiusa, mai un fallback permissivo" del resto dell'app)."""
    if entry_type not in ENTRY_TYPES:
        raise ValueError(f"Tipo di voce di memoria non riconosciuto: '{entry_type}'.")
    doc = {
        "id": new_id("mem"), "organization_id": org_id, "type": entry_type,
        "summary": _tronca(summary), "data": data or {},
        "source_project_id": source_project_id, "created_by": actor, "created_at": now_iso(),
    }
    await db.social_memory_entries.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def list_entries(db, org_id: str, *, entry_type: Optional[str] = None, limit: int = 100) -> list[dict]:
    query: dict = {"organization_id": org_id}
    if entry_type:
        query["type"] = entry_type
    rows = await db.social_memory_entries.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return rows


async def get_memory_context(db, org_id: str, *, limit: int = 30) -> dict:
    """Aggrega le voci più recenti in un riepilogo compatto e SICURO da
    iniettare in un prompt (mai il testo integrale di ogni voce). Ritorna un
    dict vuoto ({}) quando l'organizzazione non ha ancora memoria: nessun
    blocco viene mai aggiunto al prompt per un'organizzazione senza
    storico, cosi' il comportamento resta identico a prima di questa
    funzione per qualunque org nuova/di test."""
    rows = await db.social_memory_entries.find(
        {"organization_id": org_id}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    if not rows:
        return {}
    by_type: dict[str, list[str]] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r["summary"])
    return {
        "format_preferences": by_type.get("format_preference", [])[:5],
        "revision_patterns": by_type.get("revision_pattern", [])[:5],
        "learning_suggestions": by_type.get("learning_suggestion", [])[:3],
        "n_entries": len(rows),
    }


def render_memory_block(context: dict) -> str:
    """Trasforma get_memory_context() in testo per il prompt di generazione
    (reel.py/flyer.py). SEMPRE etichettato come orientativo/non vincolante:
    non e' mai una fonte di fatti aziendali (quelli restano il Fact Ledger,
    _company_context()), solo un suggerimento di stile/formato. Stringa
    vuota se non c'e' nulla di rilevante: il prompt resta invariato."""
    if not context:
        return ""
    righe = [
        "Preferenze e apprendimento da lavori precedenti per questa azienda "
        "(SOLO orientativi, MAI vincolanti, MAI una fonte di fatti aziendali — "
        "se in conflitto con le informazioni aziendali sopra, quelle sopra vincono sempre):"
    ]
    if context.get("format_preferences"):
        righe.append("- Formati approvati in passato: " + "; ".join(context["format_preferences"]))
    if context.get("revision_patterns"):
        righe.append("- Richieste di modifica ricorrenti in passato (evitare di ripetere lo stesso problema): "
                     + "; ".join(context["revision_patterns"]))
    if context.get("learning_suggestions"):
        righe.append("- Suggerimenti derivati da dati misurati (non garanzie): " + "; ".join(context["learning_suggestions"]))
    if len(righe) == 1:
        return ""  # solo l'intestazione, nessun dato utile: nessun blocco
    return "\n".join(righe)


async def derive_learning_suggestions(db, org_id: str) -> list[dict]:
    """Confronta l'engagement REALMENTE misurato (db.social_analytics_snapshots,
    scritto da domains/social_publishing.py) tra i formati 'reel' e 'flyer'.
    Non inventa MAI un dato: un formato senza snapshot con metriche
    disponibili viene semplicemente escluso dal confronto. Sotto
    MIN_SAMPLE_SIZE campioni per un formato, quel formato non entra nel
    confronto (dato insufficiente, mai un suggerimento su 1 solo campione).
    Ogni suggerimento restituito porta sempre 'base_misurazioni' (quanti
    campioni reali lo sostengono) e 'tipo': 'suggerimento' esplicito, mai
    presentato come un fatto."""
    snapshots = await db.social_analytics_snapshots.find(
        {"organization_id": org_id, "data_available": True}, {"_id": 0}).to_list(1000)
    per_formato: dict[str, list[float]] = {}
    for s in snapshots:
        formato = s.get("source_kind")
        engagement = s.get("engagement_score")
        if formato and isinstance(engagement, (int, float)):
            per_formato.setdefault(formato, []).append(float(engagement))

    formati_validi = {k: v for k, v in per_formato.items() if len(v) >= MIN_SAMPLE_SIZE}
    if len(formati_validi) < 2:
        return []  # serve almeno 2 formati con dati sufficienti per un confronto onesto

    medie = {k: sum(v) / len(v) for k, v in formati_validi.items()}
    migliore = max(medie, key=medie.get)
    peggiore = min(medie, key=medie.get)
    if migliore == peggiore or medie[migliore] <= medie[peggiore]:
        return []

    suggerimento = {
        "tipo": "suggerimento", "formato_consigliato": migliore,
        "riassunto": (
            f"Nei dati misurati finora, i contenuti '{migliore}' hanno un engagement medio "
            f"({medie[migliore]:.2f}) superiore a '{peggiore}' ({medie[peggiore]:.2f})."
        ),
        "base_misurazioni": {k: len(v) for k, v in formati_validi.items()},
    }
    return [suggerimento]
