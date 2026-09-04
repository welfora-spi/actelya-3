"""Validazione semantica deterministica (nessuna chiamata AI, nessun DB)."""
from app.domains.reel_semantic import semantic_validate_reel_content


def _content(**overrides):
    c = {
        "concept": "Un reel che mostra il lavoro quotidiano di SPI Passioni nel proprio settore.",
        "hook": "Scopri cosa facciamo ogni giorno.",
        "sceneggiatura": "Scena 1: presentazione. Scena 2: il lavoro sul campo. Scena 3: chiusura con invito.",
        "storyboard": [
            {"numero_scena": 1, "descrizione_visiva": "Team al lavoro", "durata_secondi": 4,
             "testo_a_schermo": "SPI Passioni", "voice_over": "Ecco chi siamo."},
            {"numero_scena": 2, "descrizione_visiva": "Dettaglio del lavoro svolto", "durata_secondi": 4,
             "testo_a_schermo": "Il nostro lavoro", "voice_over": "Così lavoriamo ogni giorno."},
        ],
        "voice_over_completo": "Ecco chi siamo. Così lavoriamo ogni giorno per il nostro settore.",
        "testi_a_schermo": ["SPI Passioni", "Il nostro lavoro"],
        "caption": "SPI Passioni, ogni giorno.",
        "cta": "Scopri di più",
        "durata_secondi": 16,
        "formato": "9:16",
        "prompt_video_generativo": "Vertical 9:16 video of a team at work, clean modern style.",
    }
    c.update(overrides)
    return c


CONTESTO_MINIMO = {"ragione_sociale": "SPI Passioni", "settore": "servizi", "sito_web": "informazione non disponibile",
                   "obiettivi_commerciali": "informazione non disponibile"}


def test_contenuto_onesto_senza_dettagli_extra_e_ok():
    r = semantic_validate_reel_content(_content(), CONTESTO_MINIMO, brief="")
    assert r["status"] == "OK"
    assert r["affermazioni_contestate"] == []


def test_pubblico_inventato_senza_fact_ledger_viene_contestato():
    c = _content(hook="Aiutiamo privati e aziende a risolvere ogni problema.")
    r = semantic_validate_reel_content(c, CONTESTO_MINIMO, brief="")
    assert r["status"] == "CONTESTATO"
    categorie = {a["categoria"] for a in r["affermazioni_contestate"]}
    assert "pubblico" in categorie


def test_pubblico_autorizzato_se_presente_nel_fact_ledger():
    contesto = dict(CONTESTO_MINIMO, pubblico_target="privati e piccole aziende")
    c = _content(hook="Aiutiamo privati e aziende a risolvere ogni problema.")
    r = semantic_validate_reel_content(c, contesto, brief="")
    categorie = {a["categoria"] for a in r["affermazioni_contestate"]}
    assert "pubblico" not in categorie


def test_servizio_inventato_senza_prodotto_in_fact_ledger():
    c = _content(concept="Offriamo supporto e assistenza per problemi informatici quotidiani.")
    r = semantic_validate_reel_content(c, CONTESTO_MINIMO, brief="")
    assert r["status"] == "CONTESTATO"
    categorie = {a["categoria"] for a in r["affermazioni_contestate"]}
    assert "servizio_prodotto" in categorie


def test_servizio_autorizzato_se_prodotto_dichiarato():
    contesto = dict(CONTESTO_MINIMO, prodotto="assistenza informatica per privati")
    c = _content(concept="Offriamo supporto e assistenza per problemi informatici quotidiani.")
    r = semantic_validate_reel_content(c, contesto, brief="")
    categorie = {a["categoria"] for a in r["affermazioni_contestate"]}
    assert "servizio_prodotto" not in categorie


def test_prezzo_e_territorio_sempre_contestati_senza_brief():
    c = _content(caption="Offerta speciale, sconto del 20% per chi ci contatta in tutta Italia.")
    r = semantic_validate_reel_content(c, CONTESTO_MINIMO, brief="")
    categorie = {a["categoria"] for a in r["affermazioni_contestate"]}
    assert "prezzo" in categorie
    assert "territorio" in categorie


def test_claim_presente_nel_brief_non_contestato():
    c = _content(hook="Aiutiamo privati con supporto rapido.")
    r = semantic_validate_reel_content(c, CONTESTO_MINIMO, brief="rivolto a privati, offriamo supporto rapido")
    assert r["status"] == "OK"


def test_affermazione_contestata_riporta_la_frase_esatta():
    c = _content(hook="Siamo leader nel nostro settore.")
    r = semantic_validate_reel_content(c, CONTESTO_MINIMO, brief="")
    assert r["status"] == "CONTESTATO"
    voci = r["affermazioni_contestate"]
    assert any("leader" in v["frase"].lower() for v in voci)
    assert all("campo" in v and "categoria" in v for v in voci)


def test_claim_qualitativi_generici_reali_ora_contestati():
    """Item #5 (DECISIONE UFFICIALE): frasi promozionali generiche osservate
    nella prova manuale reale — 'partner affidabile', 'servizi di qualità',
    'esperienza e professionalità', 'soluzioni pensate per le tue esigenze'
    — prima non venivano contestate (lista troppo stretta: copriva solo
    'affidabilità' sostantivata, non l'aggettivo 'affidabile'; 'anni di
    esperienza', non 'esperienza' da sola; nessuna voce per 'qualità' o
    'professionalità'). Nessun campo Fact Ledger le autorizza: devono
    restare CONTESTATO finché non sono nel brief."""
    frasi = [
        "Siamo un partner affidabile per la tua azienda.",
        "Offriamo servizi informatici di qualità.",
        "Esperienza e professionalità al tuo servizio.",
        "Soluzioni pensate per rispondere alle tue esigenze.",
    ]
    for frase in frasi:
        c = _content(concept=frase)
        r = semantic_validate_reel_content(c, CONTESTO_MINIMO, brief="")
        assert r["status"] == "CONTESTATO", f"Non contestata: {frase!r}"
        assert any(a["categoria"] == "benefici_generici" for a in r["affermazioni_contestate"]), frase


def test_claim_qualitativo_generico_autorizzato_se_nel_brief():
    c = _content(concept="Siamo un partner affidabile per la tua azienda.")
    r = semantic_validate_reel_content(c, CONTESTO_MINIMO, brief="ci presentiamo come partner affidabile")
    assert r["status"] == "OK"


def test_contenuto_malformato_non_solleva_eccezione():
    r = semantic_validate_reel_content("non un dizionario", CONTESTO_MINIMO, brief="")
    assert r["status"] == "OK"
    r2 = semantic_validate_reel_content({}, CONTESTO_MINIMO, brief="")
    assert r2["status"] == "OK"
