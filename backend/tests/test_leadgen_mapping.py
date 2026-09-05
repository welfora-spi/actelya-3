"""Lead Generation — test del mapping automatico/manuale delle colonne."""
from app.domains.leadgen.mapping import apply_mapping, auto_map_columns


def test_auto_map_riconosce_alias_noti():
    m = auto_map_columns(["Ragione Sociale", "E-mail", "Città", "Colonna Sconosciuta XYZ"])
    assert m["Ragione Sociale"] == "ragione_sociale"
    assert m["E-mail"] == "email"
    assert m["Città"] == "citta"
    assert m["Colonna Sconosciuta XYZ"] is None


def test_auto_map_non_assegna_due_colonne_allo_stesso_campo():
    m = auto_map_columns(["Email", "E-mail"])
    valori = list(m.values())
    assert valori.count("email") == 1


def test_apply_mapping_costruisce_record_canonici():
    columns = ["Ragione Sociale", "E-mail", "Colonna Ignota"]
    rows = [["Acme Srl", "info@acme.it", "valore ignorato"]]
    mapping = {"Ragione Sociale": "ragione_sociale", "E-mail": "email", "Colonna Ignota": None}
    record = apply_mapping(columns, rows, mapping)
    assert record == [{"ragione_sociale": "Acme Srl", "email": "info@acme.it"}]


def test_apply_mapping_ignora_campo_non_canonico():
    columns = ["X"]
    rows = [["valore"]]
    mapping = {"X": "campo_non_esistente"}
    assert apply_mapping(columns, rows, mapping) == [{}]


def test_apply_mapping_riga_piu_corta_delle_colonne():
    columns = ["ragione_sociale", "email"]
    rows = [["Acme Srl"]]  # manca la seconda colonna
    mapping = {"ragione_sociale": "ragione_sociale", "email": "email"}
    record = apply_mapping(columns, rows, mapping)
    assert record == [{"ragione_sociale": "Acme Srl"}]
