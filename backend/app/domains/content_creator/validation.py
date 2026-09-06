"""Content Creator — schema JSON unico per la generazione, validazione
strutturale per tipo di contenuto e adattamento al validatore semantico
anti-allucinazione condiviso (domains/reel_semantic.py, MAI duplicato: solo
i campi testuali rilevanti cambiano da un dominio all'altro)."""
from __future__ import annotations

from ...m2.deliverables import FORBIDDEN_VALUES, REFUSAL_RE

# Uno schema unico per tutti i tipi di contenuto (un solo prompt/contratto):
# la RIGIDITA' per tipo (quali campi sono davvero obbligatori e quanto
# devono essere sostanziali) e' applicata da validate_content(), non qui.
CONTENT_SCHEMA = {
    "type": "object",
    "required": ["titolo", "corpo", "cta", "hashtags", "varianti"],
    "properties": {
        "titolo": {"type": "string"},
        "corpo": {"type": "string"},
        "cta": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "varianti": {"type": "array", "items": {"type": "string"}},
    },
}

# content_type -> campi obbligatori NON vuoti + lunghezza minima per campo
# testuale (min_<campo>) e per varianti (min_varianti). Un campo assente da
# questo elenco per un tipo non e' mai obbligatorio per quel tipo (es.
# 'titolo' non serve per una 'caption').
_REQUISITI_PER_TIPO: dict[str, dict] = {
    "post_social": {"richiesti": ("corpo", "cta"), "min_corpo": 20},
    "caption": {"richiesti": ("corpo",), "min_corpo": 10},
    "carosello_testuale": {"richiesti": ("corpo", "varianti"), "min_corpo": 20, "min_varianti": 2},
    "reel_script": {"richiesti": ("corpo",), "min_corpo": 40},
    "storyboard": {"richiesti": ("corpo", "varianti"), "min_corpo": 20, "min_varianti": 2},
    "video_script": {"richiesti": ("corpo",), "min_corpo": 40},
    "voiceover_script": {"richiesti": ("corpo",), "min_corpo": 20},
    "ad_copy": {"richiesti": ("titolo", "corpo", "cta"), "min_corpo": 15, "min_titolo": 3},
    "headline": {"richiesti": ("titolo",), "min_titolo": 3},
    "cta": {"richiesti": ("cta",), "min_cta": 2},
    "landing_copy": {"richiesti": ("titolo", "corpo", "cta"), "min_corpo": 60, "min_titolo": 3},
    "email": {"richiesti": ("titolo", "corpo", "cta"), "min_corpo": 40, "min_titolo": 3},
    "newsletter": {"richiesti": ("titolo", "corpo"), "min_corpo": 80, "min_titolo": 3},
    "articolo_blog": {"richiesti": ("titolo", "corpo"), "min_corpo": 150, "min_titolo": 3},
    "contenuto_seo": {"richiesti": ("titolo", "corpo"), "min_corpo": 100, "min_titolo": 3},
    "comunicazione_commerciale": {"richiesti": ("corpo", "cta"), "min_corpo": 30},
    "offerta": {"richiesti": ("titolo", "corpo", "cta"), "min_corpo": 20, "min_titolo": 3},
    "contenuto_informativo": {"richiesti": ("corpo",), "min_corpo": 40},
    "brief_immagine": {"richiesti": ("corpo",), "min_corpo": 20},
    "brief_video": {"richiesti": ("corpo",), "min_corpo": 20},
    "brief_audio": {"richiesti": ("corpo",), "min_corpo": 20},
}

_DEFAULT_REQUISITI = {"richiesti": ("corpo",), "min_corpo": 10}


def _vietato(v: str) -> bool:
    s = (v or "").strip().lower()
    return s in FORBIDDEN_VALUES or bool(REFUSAL_RE.search(v or ""))


def validate_content(content_type: str, content: dict) -> dict:
    """Valida il contenuto restituito da Requesty per il content_type dato.
    status in COMPLETATO/BLOCCATO — mai un contenuto 'pronto' con un campo
    obbligatorio vuoto, rifiutato o troppo corto per essere sostanziale."""
    if not isinstance(content, dict):
        return {"status": "BLOCCATO", "errors": ["Contenuto non è un oggetto JSON valido"], "warnings": []}

    requisiti = _REQUISITI_PER_TIPO.get(content_type, _DEFAULT_REQUISITI)
    errors: list[str] = []
    for campo in requisiti.get("richiesti", ()):
        if campo == "varianti":
            v = content.get("varianti")
            minimo = requisiti.get("min_varianti", 1)
            valide = [x for x in v if isinstance(x, str) and x.strip()] if isinstance(v, list) else []
            if len(valide) < minimo:
                errors.append(f"'varianti': servono almeno {minimo} varianti non vuote")
            continue
        v = content.get(campo)
        if not isinstance(v, str) or not v.strip() or _vietato(v):
            errors.append(f"'{campo}': mancante, vuoto o non producibile")
            continue
        minimo = requisiti.get(f"min_{campo}", 3)
        if len(v.strip()) < minimo:
            errors.append(f"'{campo}': contenuto non sufficientemente sostanziale (minimo {minimo} caratteri)")

    if errors:
        return {"status": "BLOCCATO", "errors": errors, "warnings": []}
    return {"status": "COMPLETATO", "errors": [], "warnings": []}


def campi_testuali_per_validazione_semantica(content: dict) -> list[tuple[str, str]]:
    """(nome_campo, testo) per ogni campo testuale del contenuto, da passare
    a reel_semantic.semantic_validate_generic_content — stesso principio di
    reel_semantic._campi_testuali/flyer.py::_campi_testuali_flyer, generico
    per qualunque content_type perche' lo schema e' unico."""
    if not isinstance(content, dict):
        return []
    campi = [
        ("titolo", content.get("titolo", "")),
        ("corpo", content.get("corpo", "")),
        ("cta", content.get("cta", "")),
    ]
    for i, variante in enumerate(content.get("varianti") or [], 1):
        campi.append((f"varianti[{i}]", str(variante)))
    for h in content.get("hashtags") or []:
        campi.append(("hashtags", str(h)))
    return campi
