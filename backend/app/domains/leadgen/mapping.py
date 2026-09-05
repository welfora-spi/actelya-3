"""Lead Generation — mapping automatico delle colonne di un file caricato
verso i campi canonici (models.CANONICAL_FIELDS), con override manuale
sempre possibile (vedi router.py — l'automatico e' solo un suggerimento,
mai vincolante). Una colonna non riconosciuta resta 'sconosciuta': mai
associata a un campo canonico per tentativo."""
from __future__ import annotations

from .models import CANONICAL_FIELDS

# Alias noti (minuscolo, senza spazi/accenti) -> campo canonico. Elenco
# deliberatamente esplicito: nessuna euristica fuzzy che potrebbe associare
# per errore una colonna a un campo diverso da quello inteso.
_ALIAS = {
    "ragione sociale": "ragione_sociale", "ragione_sociale": "ragione_sociale", "azienda": "ragione_sociale",
    "company": "ragione_sociale", "company name": "ragione_sociale", "nome azienda": "ragione_sociale",
    "nome": "nome", "first name": "nome", "firstname": "nome",
    "cognome": "cognome", "last name": "cognome", "lastname": "cognome",
    "ruolo": "ruolo", "role": "ruolo", "job title": "ruolo", "posizione": "ruolo", "title": "ruolo",
    "email": "email", "e-mail": "email", "indirizzo email": "email", "mail": "email",
    "telefono": "telefono", "phone": "telefono", "numero di telefono": "telefono", "tel": "telefono",
    "sito": "sito", "sito web": "sito", "website": "sito", "web": "sito", "url": "sito",
    "dominio": "dominio", "domain": "dominio",
    "settore": "settore", "industry": "settore", "sector": "settore",
    "citta": "citta", "città": "citta", "city": "citta",
    "provincia": "provincia", "province": "provincia",
    "regione": "regione", "region": "regione",
    "paese": "paese", "country": "paese", "nazione": "paese",
    "dimensione": "dimensione", "size": "dimensione", "numero dipendenti": "dipendenti",
    "employees": "dipendenti", "dipendenti": "dipendenti",
    "fatturato": "fatturato", "revenue": "fatturato",
    "fonte": "fonte", "source": "fonte", "provenienza": "fonte",
    "consenso": "consenso", "consent": "consenso", "opt-in": "consenso", "opt_in": "consenso",
    "note": "note", "notes": "note",
    "stato crm": "stato_crm", "stato_crm": "stato_crm", "crm status": "stato_crm",
    "cliente esistente": "cliente_esistente", "cliente_esistente": "cliente_esistente", "existing customer": "cliente_esistente",
    "ultima interazione": "ultima_interazione", "last interaction": "ultima_interazione",
}


def _normalizza_intestazione(intestazione: str) -> str:
    return " ".join((intestazione or "").strip().lower().split())


def auto_map_columns(columns: list) -> dict:
    """Ritorna {nome_colonna_originale: campo_canonico|None}: None quando
    nessun alias noto corrisponde (colonna sconosciuta, resta ignorata a
    meno di un mapping manuale esplicito)."""
    mapping: dict[str, str | None] = {}
    usati: set[str] = set()
    for colonna in columns:
        chiave = _normalizza_intestazione(colonna)
        campo = _ALIAS.get(chiave)
        if campo and campo not in usati:
            mapping[colonna] = campo
            usati.add(campo)
        else:
            mapping[colonna] = None
    return mapping


def apply_mapping(columns: list, rows: list, mapping: dict) -> list:
    """Applica il mapping {colonna_originale: campo_canonico} a ciascuna
    riga tabellare, producendo {campo_canonico: valore_grezzo}. Colonne
    senza mapping (None o assente) vengono ignorate."""
    indice_colonna = {c: i for i, c in enumerate(columns)}
    risultato = []
    for riga in rows:
        record: dict[str, str] = {}
        for colonna, campo in mapping.items():
            if not campo or campo not in CANONICAL_FIELDS:
                continue
            i = indice_colonna.get(colonna)
            if i is None or i >= len(riga):
                continue
            record[campo] = riga[i]
        risultato.append(record)
    return risultato
