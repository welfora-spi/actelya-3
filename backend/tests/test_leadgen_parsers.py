"""Lead Generation — test dei parser deterministici (CSV/TSV/XLSX/PDF/DOCX/TXT).
Nessuna rete, nessun database: solo byte in memoria costruiti dal test."""
import io

import pytest

from app.domains.leadgen.parsers import ParseError, parse_file


def test_csv_semplice():
    content = "ragione_sociale,email,citta\nAcme Srl,info@acme.it,Milano\nBeta Spa,info@beta.it,Roma\n".encode("utf-8")
    r = parse_file(".csv", content)
    assert r.columns == ["ragione_sociale", "email", "citta"]
    assert len(r.rows) == 2
    assert r.rows[0] == ["Acme Srl", "info@acme.it", "Milano"]


def test_csv_delimitatore_punto_e_virgola_rilevato():
    content = "ragione_sociale;email\nAcme Srl;info@acme.it\n".encode("utf-8")
    r = parse_file(".csv", content)
    assert r.columns == ["ragione_sociale", "email"]
    assert r.rows == [["Acme Srl", "info@acme.it"]]


def test_tsv():
    content = "ragione_sociale\temail\nAcme Srl\tinfo@acme.it\n".encode("utf-8")
    r = parse_file(".tsv", content)
    assert r.columns == ["ragione_sociale", "email"]
    assert r.rows == [["Acme Srl", "info@acme.it"]]


def test_csv_vuoto():
    r = parse_file(".csv", b"")
    assert r.columns == []
    assert r.rows == []
    assert r.avvisi


def test_csv_righe_troncate(monkeypatch):
    import app.domains.leadgen.parsers as parsers_mod
    monkeypatch.setattr(parsers_mod, "MAX_ROWS_PARSED", 3)
    righe = "a,b\n" + "\n".join(f"v{i},w{i}" for i in range(10))
    r = parse_file(".csv", righe.encode("utf-8"))
    assert len(r.rows) == 3
    assert any("troncate" in a for a in r.avvisi)


def test_csv_encoding_latin1():
    content = "ragione_sociale,citta\nCaffè Ítalo,Città\n".encode("latin-1")
    r = parse_file(".csv", content)
    assert r.columns[0] == "ragione_sociale"
    assert len(r.rows) == 1


def _xlsx_bytes(header, righe):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for r in righe:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_semplice():
    content = _xlsx_bytes(["ragione_sociale", "email"], [["Acme Srl", "info@acme.it"]])
    r = parse_file(".xlsx", content)
    assert r.columns == ["ragione_sociale", "email"]
    assert r.rows == [["Acme Srl", "info@acme.it"]]


def test_xlsx_corrotto_solleva_parse_error():
    with pytest.raises(ParseError):
        parse_file(".xlsx", b"non e' davvero un file xlsx")


def test_pdf_protetto_da_password_rifiutato():
    # Un PDF minimale malformato/non decodificabile deve produrre ParseError,
    # mai un crash non gestito.
    with pytest.raises(ParseError):
        parse_file(".pdf", b"%PDF-1.4 dati non validi")


def _pdf_bytes_semplice(testo):
    from pypdf import PdfWriter
    import pypdf
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_pdf_senza_testo_segnala_avviso():
    content = _pdf_bytes_semplice("")
    r = parse_file(".pdf", content)
    assert any("OCR" in a or "estraibile" in a for a in r.avvisi)


def _docx_bytes_con_tabella(header, righe):
    import docx
    document = docx.Document()
    tabella = document.add_table(rows=1, cols=len(header))
    for i, h in enumerate(header):
        tabella.rows[0].cells[i].text = h
    for riga in righe:
        cells = tabella.add_row().cells
        for i, v in enumerate(riga):
            cells[i].text = v
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def test_docx_con_tabella_estrae_righe():
    content = _docx_bytes_con_tabella(["ragione_sociale", "email"], [["Acme Srl", "info@acme.it"]])
    r = parse_file(".docx", content)
    assert r.columns == ["ragione_sociale", "email"]
    assert r.rows == [["Acme Srl", "info@acme.it"]]


def _docx_bytes_solo_testo(testo):
    import docx
    document = docx.Document()
    for riga in testo.splitlines():
        document.add_paragraph(riga)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def test_docx_solo_testo_libero_senza_tabella():
    content = _docx_bytes_solo_testo("Presentazione aziendale.\nNessun dato tabellare qui.")
    r = parse_file(".docx", content)
    assert r.columns == []
    assert r.rows == []
    assert "Presentazione aziendale" in r.testo_libero


def test_docx_corrotto_solleva_parse_error():
    with pytest.raises(ParseError):
        parse_file(".docx", b"non e' un docx valido")


def test_txt_con_struttura_tabellare_rilevata():
    content = "ragione_sociale;email\nAcme Srl;info@acme.it\nBeta Spa;info@beta.it\n".encode("utf-8")
    r = parse_file(".txt", content)
    assert r.columns == ["ragione_sociale", "email"]
    assert len(r.rows) == 2


def test_txt_libero_senza_struttura():
    content = "Questo e' un testo libero.\nSenza alcuna struttura tabellare riconoscibile.\n".encode("utf-8")
    r = parse_file(".txt", content)
    assert r.columns == []
    assert r.rows == []
    assert "testo libero" in r.testo_libero


def test_formato_non_supportato():
    with pytest.raises(ParseError):
        parse_file(".exe", b"binario qualunque")
