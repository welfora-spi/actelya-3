"""Brain — riconoscimento di campi etichettati ("Azienda/brand: X",
"Prodotto: Y") in context.py, e ricomposizione del testo con le risposte di
chiarimento (augment_goal_text). Puramente deterministico, nessun db,
nessuna rete: verifica sia il caso segnalato (ACTELYA 3) sia che la
soluzione sia generica (nessun nome fisso, nessuna eccezione dedicata)."""
from app.brain.context import augment_goal_text, extract_goal_context


# ---------------- riconoscimento etichettato: caso segnalato ----------------
def test_azienda_brand_actelya3_riconosciuta():
    ctx = extract_goal_context(
        "Crea un reel per Instagram per pubblicizzare i nostri prodotti. Azienda/brand: ACTELYA 3."
    )
    assert ctx.azienda == "ACTELYA 3"
    assert "azienda" not in ctx.missing_critical


# ---------------- generico: deve funzionare con QUALSIASI nome, non solo ACTELYA 3 ----------------
def test_azienda_brand_nome_diverso_riconosciuta():
    ctx = extract_goal_context("Crea un post. Azienda/brand: Rossi Bike Shop.")
    assert ctx.azienda == "Rossi Bike Shop"


def test_solo_azienda_senza_slash_brand():
    ctx = extract_goal_context("Crea un post. Azienda: Verdi Fioristi.")
    assert ctx.azienda == "Verdi Fioristi"


def test_solo_brand_senza_parola_azienda():
    ctx = extract_goal_context("Crea un post. Brand: Blu Notte Cocktail Bar.")
    assert ctx.azienda == "Blu Notte Cocktail Bar"


def test_prodotto_etichettato_riconosciuto():
    ctx = extract_goal_context("Crea un reel. Azienda/brand: ACTELYA 3. Prodotto: panini artigianali.")
    assert ctx.azienda == "ACTELYA 3"
    assert ctx.prodotto == "panini artigianali"
    assert ctx.missing_critical == []


def test_prodotto_servizio_etichettato():
    ctx = extract_goal_context("Crea un post. Azienda: Studio Legale Bianchi. Prodotto/servizio: consulenza contrattuale.")
    assert ctx.prodotto == "consulenza contrattuale"


# ---------------- l'etichetta ha priorita', ma le euristiche restano intatte ----------------
def test_pattern_euristico_del_x_di_y_invariato():
    FOCACCINE_GOAL = (
        "Prepara una campagna social per pubblicizzare le focaccine artigianali del "
        "Bakery & Coffee di Merate. Crea una strategia locale, un piano editoriale e "
        "tre post per Instagram e Facebook rivolti alle famiglie e ai lavoratori della "
        "zona. Usa dati simulati, non contattare clienti e non pubblicare nulla."
    )
    ctx = extract_goal_context(FOCACCINE_GOAL)
    assert ctx.azienda == "Bakery & Coffee"
    assert ctx.localita == "Merate"
    assert ctx.prodotto and "focaccine" in ctx.prodotto.lower()
    assert ctx.missing_critical == []


def test_nessuna_etichetta_nessun_pattern_resta_mancante():
    ctx = extract_goal_context("Fai qualcosa di utile per il mio business")
    assert ctx.azienda is None
    assert set(ctx.missing_critical) == {"azienda", "prodotto"}


# ---------------- augment_goal_text: ricompone il testo con le risposte ----------------
def test_augment_goal_text_aggiunge_campi_etichettati():
    risultato = augment_goal_text(
        "Crea un reel per Instagram.",
        ["azienda", "prodotto"],
        ["ACTELYA 3", "panini artigianali"],
    )
    assert "Crea un reel per Instagram." in risultato
    assert "Azienda/brand: ACTELYA 3." in risultato
    assert "Prodotto/servizio: panini artigianali." in risultato

    ctx = extract_goal_context(risultato)
    assert ctx.azienda == "ACTELYA 3"
    assert ctx.prodotto == "panini artigianali"
    assert ctx.missing_critical == []


def test_augment_goal_text_risposta_vuota_ignorata():
    risultato = augment_goal_text("Testo originale.", ["azienda", "prodotto"], ["ACTELYA 3", "  "])
    assert "Azienda/brand: ACTELYA 3." in risultato
    assert "Prodotto/servizio" not in risultato


def test_augment_goal_text_campo_sconosciuto_aggiunto_come_frase_libera():
    risultato = augment_goal_text(
        "Fai qualcosa di utile per il mio business.",
        ["tipo_di_deliverable"],
        ["Contenuti social per Instagram"],
    )
    assert "Contenuti social per Instagram." in risultato
    assert "Fai qualcosa di utile per il mio business." in risultato


def test_augment_goal_text_nessuna_risposta_ritorna_testo_originale():
    assert augment_goal_text("Testo originale.", [], []) == "Testo originale."
