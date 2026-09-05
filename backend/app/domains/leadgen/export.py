"""Lead Generation — export controllato CSV/XLSX.

Regole non negoziabili, applicate SEMPRE prima di scrivere qualunque file:
- un record DO_NOT_CONTACT non e' MAI esportabile, qualunque sia la
  richiesta del chiamante;
- solo i campi esplicitamente ammessi vengono scritti (mai un campo interno
  come merge_history/id tecnici, mai un segreto);
- ogni valore che inizia con un carattere che un foglio di calcolo
  interpreta come inizio-formula (=, +, -, @) viene neutralizzato con un
  apice iniziale: previene la formula injection su apertura in Excel/Sheets
  (CSV injection), un rischio noto per export contenenti dati non fidati."""
from __future__ import annotations

import csv
import io

_PREFISSI_FORMULA = ("=", "+", "-", "@", "\t", "\r")

CAMPI_EXPORT_DEFAULT = (
    "ragione_sociale", "nome", "cognome", "ruolo", "email", "telefono", "sito", "dominio",
    "settore", "citta", "provincia", "regione", "paese", "score", "qualification_status",
    "fonte", "consenso",
)


def _valore_campo(record: dict, campo: str):
    v = record.get(campo)
    if isinstance(v, dict):
        return v.get("value")
    return v


def _neutralizza(valore: str) -> str:
    if valore and valore[0] in _PREFISSI_FORMULA:
        return "'" + valore
    return valore


def prepare_export_rows(records: list, fields: tuple = CAMPI_EXPORT_DEFAULT) -> list:
    """Filtra i record DO_NOT_CONTACT e proietta SOLO i campi ammessi,
    neutralizzando ogni valore per la scrittura sicura in CSV/XLSX."""
    righe = []
    for r in records:
        if r.get("qualification_status") == "DO_NOT_CONTACT":
            continue
        riga = {}
        for campo in fields:
            grezzo = _valore_campo(r, campo)
            riga[campo] = _neutralizza(str(grezzo)) if grezzo not in (None, "") else ""
        righe.append(riga)
    return righe


def export_csv(records: list, fields: tuple = CAMPI_EXPORT_DEFAULT) -> bytes:
    righe = prepare_export_rows(records, fields)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(fields))
    writer.writeheader()
    for r in righe:
        writer.writerow(r)
    return buf.getvalue().encode("utf-8-sig")  # BOM: apertura corretta in Excel con caratteri accentati


def export_xlsx(records: list, fields: tuple = CAMPI_EXPORT_DEFAULT) -> bytes:
    import openpyxl

    righe = prepare_export_rows(records, fields)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lead"
    ws.append(list(fields))
    for r in righe:
        ws.append([r.get(f, "") for f in fields])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_records(records: list, fmt: str, fields: tuple = CAMPI_EXPORT_DEFAULT) -> tuple:
    """Ritorna (contenuto_bytes, content_type, estensione)."""
    if fmt == "xlsx":
        return export_xlsx(records, fields), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    return export_csv(records, fields), "text/csv; charset=utf-8", "csv"
