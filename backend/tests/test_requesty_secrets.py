"""Wrapper Credential Manager per Requesty: mai il Credential Manager REALE nei
test automatici. Sostituisce keyring.get_password/set_password/delete_password
con uno store in memoria dedicato al test, cosi' la credenziale reale
eventualmente configurata sul PC (welfora_ai/requesty:api_key, gia' usata da
ACTELYA v1) non viene mai letta, sovrascritta o cancellata da questa suite."""
import pytest

from app.integrations import requesty_secrets as rs


@pytest.fixture(autouse=True)
def fake_keyring_store(monkeypatch):
    store: dict[tuple[str, str], str] = {}

    def fake_set(service, key, value):
        store[(service, key)] = value

    def fake_get(service, key):
        return store.get((service, key))

    def fake_delete(service, key):
        import keyring.errors
        if (service, key) not in store:
            raise keyring.errors.PasswordDeleteError("not found")
        del store[(service, key)]

    monkeypatch.setattr(rs.keyring, "set_password", fake_set)
    monkeypatch.setattr(rs.keyring, "get_password", fake_get)
    monkeypatch.setattr(rs.keyring, "delete_password", fake_delete)
    return store


def test_non_configurata_inizialmente():
    assert rs.requesty_configurata() is False
    assert rs.leggi_api_key_requesty() is None
    assert rs.requesty_api_key_mascherata() is None


def test_salva_e_legge():
    rs.salva_api_key_requesty("sk-req-abcdef1234567890")
    assert rs.requesty_configurata() is True
    assert rs.leggi_api_key_requesty() == "sk-req-abcdef1234567890"


def test_mascherata_non_espone_valore_completo():
    rs.salva_api_key_requesty("sk-req-abcdef1234567890")
    mask = rs.requesty_api_key_mascherata()
    assert mask is not None
    assert mask.endswith("7890")
    assert "sk-req-abcdef1234567890" not in mask
    assert len(mask) < len("sk-req-abcdef1234567890")


def test_elimina():
    rs.salva_api_key_requesty("sk-req-xxxxxxxxxxxxxxxx")
    rs.elimina_api_key_requesty()
    assert rs.requesty_configurata() is False


def test_elimina_idempotente_se_gia_assente():
    rs.elimina_api_key_requesty()  # non deve sollevare
    rs.elimina_api_key_requesty()


def test_salva_valore_vuoto_rifiutato():
    with pytest.raises(ValueError):
        rs.salva_api_key_requesty("")
    with pytest.raises(ValueError):
        rs.salva_api_key_requesty("   ")
