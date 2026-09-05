"""Lead Generation — paginazione server-side coerente per OGNI lista del
dominio (file, campagne, lead/aziende/persone, duplicati da revisionare):
contratto identico ovunque (`page`/`page_size`/`items`/`total`/`pages`), mai
l'intero dataset caricato in un solo payload, mai un campo di ordinamento
libero passato direttamente a .sort() (solo un'allowlist esplicita per
endpoint, altrimenti 400 — nessuna 'iniezione di ordinamento' su un campo
non previsto/non indicizzato)."""
from __future__ import annotations

import math
from typing import Optional

from fastapi import HTTPException

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def resolve_sort(sort_by: Optional[str], sort_dir: str, allowed: dict, default_field: str) -> tuple[str, int]:
    """allowed: {nome_pubblico: percorso_campo_mongo}. Ritorna (campo_mongo, direzione) o
    solleva 400 su un valore non ammesso — mai un ordinamento silenzioso su un campo diverso
    da quello richiesto."""
    chiave = sort_by or default_field
    campo = allowed.get(chiave)
    if campo is None:
        ammessi = ", ".join(sorted(allowed.keys()))
        raise HTTPException(status_code=400, detail=f"sort_by non valido: usare uno tra {ammessi}.")
    if sort_dir not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="sort_dir non valido: usare 'asc' o 'desc'.")
    return campo, (1 if sort_dir == "asc" else -1)


async def paginate(collection, query: dict, *, page: int, page_size: int,
                   sort_field: str, direction: int, projection: Optional[dict] = None) -> dict:
    """Pagina 'query' su 'collection'. page/page_size vengono solo bloccati a un minimo/
    massimo sicuro (mai un errore per un numero fuori range): una pagina oltre l'ultima
    ritorna semplicemente 'items: []', con 'total'/'pages' comunque corretti, cosi' il
    client puo' sempre capire dove si trova senza un redirect silenzioso a un'altra pagina."""
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    total = await collection.count_documents(query)
    pages = math.ceil(total / page_size) if total else 0
    skip = (page - 1) * page_size
    cursor = collection.find(query, projection if projection is not None else {"_id": 0})
    cursor = cursor.sort(sort_field, direction).skip(skip).limit(page_size)
    items = await cursor.to_list(page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}
