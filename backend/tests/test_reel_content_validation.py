"""Validazione del contenuto reel prodotto da Requesty: pure functions, nessun
DB, nessuna rete. Garantisce che un progetto non venga MAI dichiarato
'pronto' con testo/storyboard vuoti, rifiutati o insufficienti."""
from app.domains.reel import validate_reel_content, _brand, _is_refusal_or_forbidden


def _base_content(**overrides):
    c = {
        "concept": "Un reel che mostra come il prodotto risolve un problema quotidiano del cliente target.",
        "hook": "Hai mai perso tempo a fare questo a mano?",
        "sceneggiatura": "Scena 1: apertura con il problema. Scena 2: introduzione del prodotto. Scena 3: risultato finale.",
        "storyboard": [
            {"numero_scena": 1, "descrizione_visiva": "Persona frustrata alla scrivania",
             "durata_secondi": 4, "testo_a_schermo": "Il problema", "voice_over": "Conosci questa scena?"},
            {"numero_scena": 2, "descrizione_visiva": "Uso del prodotto in azione",
             "durata_secondi": 5, "testo_a_schermo": "La soluzione", "voice_over": "Ecco come risolviamo."},
        ],
        "voice_over_completo": "Conosci questa scena? Ecco come risolviamo il problema con il nostro prodotto.",
        "testi_a_schermo": ["Il problema", "La soluzione"],
        "hashtags": ["#novita", "#soluzione"],
        "caption": "Basta perdere tempo. Scopri la soluzione.",
        "cta": "Scopri di più",
        "durata_secondi": 20,
        "formato": "9:16",
        "prompt_video_generativo": "Vertical 9:16 video, scene 1: frustrated person at desk, scene 2: product in use, clean modern style.",
    }
    c.update(overrides)
    return c


def test_contenuto_valido_completo():
    r = validate_reel_content(_base_content())
    assert r["status"] == "COMPLETATO"
    assert r["errors"] == []


def test_contenuto_non_dict():
    r = validate_reel_content("non un dizionario")
    assert r["status"] == "BLOCCATO"


def test_campo_vuoto_blocca():
    r = validate_reel_content(_base_content(concept=""))
    assert r["status"] == "BLOCCATO"
    assert any("Concept" in e for e in r["errors"])


def test_rifiuto_del_modello_bloccato():
    r = validate_reel_content(_base_content(hook="Mi dispiace, non posso aiutarti con questo compito."))
    assert r["status"] == "BLOCCATO"
    assert any("Hook" in e for e in r["errors"])


def test_storyboard_con_una_sola_scena_bloccato():
    c = _base_content()
    c["storyboard"] = c["storyboard"][:1]
    r = validate_reel_content(c)
    assert r["status"] == "BLOCCATO"
    assert any("storyboard" in e for e in r["errors"])


def test_hashtags_mancanti_blocca():
    r = validate_reel_content(_base_content(hashtags=[]))
    assert r["status"] == "BLOCCATO"
    assert any("hashtag" in e for e in r["errors"])


def test_hashtag_singolo_insufficiente():
    r = validate_reel_content(_base_content(hashtags=["#solo"]))
    assert r["status"] == "BLOCCATO"


def test_scena_senza_durata_bloccata():
    c = _base_content()
    c["storyboard"][0]["durata_secondi"] = 0
    r = validate_reel_content(c)
    assert r["status"] == "BLOCCATO"


def test_durata_totale_mancante_bloccata():
    r = validate_reel_content(_base_content(durata_secondi=None))
    assert r["status"] == "BLOCCATO"


def test_testi_a_schermo_vuoti_bloccati():
    r = validate_reel_content(_base_content(testi_a_schermo=[]))
    assert r["status"] == "BLOCCATO"


def test_is_refusal_or_forbidden():
    assert _is_refusal_or_forbidden("") is True
    assert _is_refusal_or_forbidden("N/A") is True
    assert _is_refusal_or_forbidden("I cannot help with that request.") is True
    assert _is_refusal_or_forbidden("Un contenuto valido e sostanziale.") is False


def test_brand_preferisce_nome_commerciale():
    assert _brand({"nome_commerciale": "Acme", "ragione_sociale": "Acme S.r.l."}) == "Acme"
    assert _brand({"ragione_sociale": "Acme S.r.l."}) == "Acme S.r.l."
    assert _brand({}) == "l'azienda"
