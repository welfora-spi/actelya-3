"""Lead Generation — test di normalizzazione con provenienza. Ogni valore
mantiene l'originale e riceve uno stato esplicito: mai un dato mancante
inventato, mai un'inferenza spacciata per verificata."""
from app.domains.leadgen.normalize import (
    normalize_boolean,
    normalize_domain,
    normalize_email,
    normalize_number,
    normalize_phone,
    normalize_record,
    normalize_text,
)


def test_email_valida():
    r = normalize_email("  Info@Acme.IT ")
    assert r.value == "info@acme.it"
    assert r.original == "Info@Acme.IT"
    assert r.method == "ESTRATTO"


def test_email_vuota_e_mancante():
    r = normalize_email("")
    assert r.value is None
    assert r.method == "MANCANTE"


def test_email_malformata_non_verificato():
    r = normalize_email("non-una-email")
    assert r.value is None
    assert r.original == "non-una-email"
    assert r.method == "NON_VERIFICATO"


def test_telefono_con_prefisso():
    r = normalize_phone("+39 02 1234567")
    assert r.value == "+390212 34567".replace(" ", "") or r.value.startswith("+39")


def test_telefono_senza_prefisso_non_inventato():
    r = normalize_phone("02 1234567")
    assert r.value is not None
    assert not r.value.startswith("+")  # mai un prefisso paese inventato


def test_telefono_troppo_corto_non_verificato():
    r = normalize_phone("123")
    assert r.value is None
    assert r.method == "NON_VERIFICATO"


def test_dominio_da_url():
    r = normalize_domain("https://www.Acme.it/pagina?x=1")
    assert r.value == "acme.it"


def test_dominio_da_testo_semplice():
    r = normalize_domain("acme.it")
    assert r.value == "acme.it"


def test_dominio_non_valido():
    r = normalize_domain("non un dominio")
    assert r.value is None
    assert r.method == "NON_VERIFICATO"


def test_booleano_vari_formati():
    assert normalize_boolean("Sì").value == "true"
    assert normalize_boolean("no").value == "false"
    assert normalize_boolean("").method == "MANCANTE"
    assert normalize_boolean("forse").method == "NON_VERIFICATO"


def test_numero_con_separatori_italiani():
    r = normalize_number("1.234,56")
    assert r.value == "1234.56"


def test_testo_collassa_spazi():
    r = normalize_text("  Acme   Srl  ")
    assert r.value == "Acme Srl"


def test_normalize_record_solo_campi_canonici_presenti():
    grezzo = {"ragione_sociale": "Acme Srl", "email": "info@acme.it", "campo_sconosciuto": "x"}
    r = normalize_record(grezzo)
    assert set(r.keys()) == {"ragione_sociale", "email"}
    assert r["email"]["value"] == "info@acme.it"
    assert r["email"]["original"] == "info@acme.it"


def test_normalize_record_metodo_propagato():
    r = normalize_record({"ragione_sociale": "Acme"}, method="PUBBLICO")
    assert r["ragione_sociale"]["method"] == "PUBBLICO"
