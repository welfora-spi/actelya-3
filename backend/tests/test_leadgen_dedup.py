"""Lead Generation — test di deduplica ed entity resolution. I duplicati
probabili (nome simile) devono SEMPRE richiedere review manuale, mai un
merge automatico; il merge non deve mai risolvere in silenzio un conflitto
di valore fra due record."""
from app.domains.leadgen.dedup import apply_merge, find_exact_duplicates, find_probable_duplicates


def _rec(id_, **campi):
    r = {"id": id_}
    for k, v in campi.items():
        r[k] = {"value": v, "original": v, "method": "ESTRATTO"}
    return r


def test_duplicati_esatti_per_dominio():
    records = [_rec("r1", dominio="acme.it"), _rec("r2", dominio="acme.it"), _rec("r3", dominio="beta.it")]
    gruppi = find_exact_duplicates(records)
    assert len(gruppi) == 1
    assert gruppi[0]["match_type"] == "ESATTO"
    assert set(gruppi[0]["record_ids"]) == {"r1", "r2"}


def test_duplicati_esatti_per_email():
    records = [_rec("r1", email="info@acme.it"), _rec("r2", email="info@acme.it")]
    gruppi = find_exact_duplicates(records)
    assert gruppi[0]["tipo"] == "email"


def test_nessun_duplicato_esatto_senza_chiavi_condivise():
    records = [_rec("r1", dominio="acme.it"), _rec("r2", dominio="beta.it")]
    assert find_exact_duplicates(records) == []


def test_duplicati_probabili_sempre_review_manuale():
    records = [
        _rec("r1", ragione_sociale="Acme Servizi Srl", citta="Milano"),
        _rec("r2", ragione_sociale="Acme Servizi S.r.l.", citta="Milano"),
    ]
    probabili = find_probable_duplicates(records)
    assert len(probabili) == 1
    assert probabili[0]["esito"] == "REVIEW_MANUALE"
    assert probabili[0]["match_type"] == "PROBABILE"


def test_duplicati_probabili_citta_diverse_non_confrontati():
    records = [
        _rec("r1", ragione_sociale="Acme Servizi Srl", citta="Milano"),
        _rec("r2", ragione_sociale="Acme Servizi Srl", citta="Roma"),
    ]
    assert find_probable_duplicates(records) == []


def test_duplicati_probabili_nomi_diversi_sotto_soglia():
    records = [
        _rec("r1", ragione_sociale="Acme Servizi Srl", citta="Milano"),
        _rec("r2", ragione_sociale="Beta Consulting Spa", citta="Milano"),
    ]
    assert find_probable_duplicates(records) == []


def test_merge_adotta_campo_mancante_dal_secondario():
    primario = _rec("r1", ragione_sociale="Acme Srl")
    secondario = _rec("r2", ragione_sociale="Acme Srl", email="info@acme.it")
    esito = apply_merge(primario, secondario, actor="user-1", now_iso="2026-01-01T00:00:00Z")
    assert esito.merged["email"]["value"] == "info@acme.it"
    assert "email" in esito.campi_adottati
    assert esito.contraddizioni == []


def test_merge_stesso_valore_nessuna_contraddizione():
    primario = _rec("r1", email="info@acme.it")
    secondario = _rec("r2", email="INFO@ACME.IT")
    esito = apply_merge(primario, secondario, actor="user-1", now_iso="2026-01-01T00:00:00Z")
    assert esito.contraddizioni == []


def test_merge_valori_diversi_segnala_contraddizione_senza_scegliere_in_silenzio():
    primario = _rec("r1", citta="Milano")
    secondario = _rec("r2", citta="Roma")
    esito = apply_merge(primario, secondario, actor="user-1", now_iso="2026-01-01T00:00:00Z")
    assert "citta" in esito.contraddizioni
    assert esito.merged["citta"]["method"] == "CONTRADDITTORIO"
    assert esito.merged["citta"]["conflicting_value"] == "Roma"
    # il valore attivo resta quello del primario (mai sovrascritto in silenzio)
    assert esito.merged["citta"]["value"] == "Milano"


def test_merge_registra_cronologia_e_provenienza():
    primario = _rec("r1", ragione_sociale="Acme")
    secondario = _rec("r2", ragione_sociale="Acme")
    esito = apply_merge(primario, secondario, actor="user-1", now_iso="2026-01-01T00:00:00Z")
    assert len(esito.merged["merge_history"]) == 1
    assert esito.merged["merge_history"][0]["by"] == "user-1"
    assert esito.merged["merged_from_ids"] == ["r2"]


def test_merge_non_modifica_gli_oggetti_originali():
    primario = _rec("r1", email="info@acme.it")
    secondario = _rec("r2", email="altra@beta.it")
    apply_merge(primario, secondario, actor="user-1", now_iso="2026-01-01T00:00:00Z")
    assert primario["email"]["value"] == "info@acme.it"  # invariato
