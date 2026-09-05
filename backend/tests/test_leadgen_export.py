"""Lead Generation — test dell'export CSV/XLSX: DO_NOT_CONTACT mai
esportato, formula injection sempre neutralizzata, riapertura del file
prodotto verificata."""
import csv
import io

from app.domains.leadgen.export import export_csv, export_records, export_xlsx, prepare_export_rows


def _rec(**campi):
    r = {}
    for k, v in campi.items():
        if k == "qualification_status":
            r[k] = v
        else:
            r[k] = {"value": v}
    return r


def test_do_not_contact_mai_esportato():
    records = [
        _rec(ragione_sociale="Acme Srl", qualification_status="QUALIFIED"),
        _rec(ragione_sociale="Blacklisted Srl", qualification_status="DO_NOT_CONTACT"),
    ]
    righe = prepare_export_rows(records)
    nomi = [r["ragione_sociale"] for r in righe]
    assert "Acme Srl" in nomi
    assert "Blacklisted Srl" not in nomi


def test_formula_injection_neutralizzata():
    records = [_rec(ragione_sociale="=cmd|'/c calc'!A1", qualification_status="QUALIFIED")]
    righe = prepare_export_rows(records)
    assert righe[0]["ragione_sociale"].startswith("'=")


def test_solo_campi_ammessi_esportati():
    records = [_rec(ragione_sociale="Acme", campo_interno_non_ammesso="segreto", qualification_status="QUALIFIED")]
    righe = prepare_export_rows(records, fields=("ragione_sociale",))
    assert "campo_interno_non_ammesso" not in righe[0]


def test_export_csv_riapribile():
    records = [_rec(ragione_sociale="Acme Srl", email="info@acme.it", qualification_status="QUALIFIED")]
    contenuto = export_csv(records, fields=("ragione_sociale", "email"))
    testo = contenuto.decode("utf-8-sig")
    righe = list(csv.DictReader(io.StringIO(testo)))
    assert righe[0]["ragione_sociale"] == "Acme Srl"
    assert righe[0]["email"] == "info@acme.it"


def test_export_xlsx_riapribile():
    records = [_rec(ragione_sociale="Acme Srl", email="info@acme.it", qualification_status="QUALIFIED")]
    contenuto = export_xlsx(records, fields=("ragione_sociale", "email"))
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(contenuto))
    ws = wb.active
    righe = list(ws.iter_rows(values_only=True))
    assert righe[0] == ("ragione_sociale", "email")
    assert righe[1] == ("Acme Srl", "info@acme.it")


def test_export_records_sceglie_formato():
    records = [_rec(ragione_sociale="Acme", qualification_status="QUALIFIED")]
    contenuto, content_type, ext = export_records(records, "xlsx")
    assert ext == "xlsx"
    assert "spreadsheetml" in content_type
    contenuto2, content_type2, ext2 = export_records(records, "csv")
    assert ext2 == "csv"
    assert "csv" in content_type2
