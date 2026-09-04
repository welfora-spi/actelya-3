"""M2 planner — riconoscimento di reel/Instagram/Facebook/TikTok come segnali
di contenuto organico (CONTENUTO), aggiunto per collegare la pagina "Nuovo
Obiettivo" al brain senza che richieste come "crea un reel per Instagram"
restino AMBIGUO solo perche' non usano le parole "social"/"post". Puramente
deterministico, nessun db, nessuna rete."""
from app.m2.planner import classify_objective


# ---------------- riconoscimento positivo ----------------
def test_reel_instagram_senza_altre_keyword_e_contenuto():
    r = classify_objective(
        "Crea un reel per Instagram per pubblicizzare i panini del Bakery & Coffee di Merate"
    )
    assert r["objective_type"] == "CONTENUTO"
    assert r["requires_clarification"] is False


def test_facebook_da_solo_e_contenuto():
    r = classify_objective("Prepara un video per Facebook sul nuovo menu del ristorante")
    assert r["objective_type"] == "CONTENUTO"


def test_tiktok_da_solo_e_contenuto():
    r = classify_objective("Scrivi un'idea per un video TikTok sui prodotti del forno")
    assert r["objective_type"] == "CONTENUTO"


def test_storie_e_carosello_sono_contenuto():
    assert classify_objective("Prepara delle storie per raccontare il dietro le quinte del negozio")["objective_type"] == "CONTENUTO"
    assert classify_objective("Crea un carosello per il nostro profilo")["objective_type"] == "CONTENUTO"


def test_determinismo_stesso_testo_stesso_risultato():
    testo = "Crea un reel per Instagram per pubblicizzare i panini del Bakery & Coffee di Merate"
    r1, r2 = classify_objective(testo), classify_objective(testo)
    assert r1["objective_type"] == r2["objective_type"] == "CONTENUTO"


# ---------------- falsi positivi da evitare: la priorita' delle categorie precedenti resta intatta ----------------
def test_report_con_instagram_resta_report_non_contenuto():
    r = classify_objective("Analizza i risultati del reel pubblicato su Instagram questo mese")
    assert r["objective_type"] == "REPORT"


def test_lead_gen_con_instagram_resta_lead_gen():
    r = classify_objective("Costruisci un piano di lead generation con contenuti per Instagram per prospect B2B")
    assert r["objective_type"] == "LEAD_GEN"


def test_campagna_con_instagram_resta_campagna_non_contenuto():
    r = classify_objective("Lancia una campagna ads su Instagram per il nuovo prodotto")
    assert r["objective_type"] == "CAMPAGNA"


def test_campagna_social_esplicita_resta_campagna():
    r = classify_objective("Prepara una campagna social e adv per il lancio di un nuovo prodotto")
    assert r["objective_type"] == "CAMPAGNA"


# ---------------- casi non correlati restano invariati (nessuna nuova keyword coinvolta) ----------------
def test_obiettivo_ambiguo_senza_alcuna_keyword_resta_ambiguo():
    r = classify_objective("Fai qualcosa di utile per il mio business")
    assert r["objective_type"] == "AMBIGUO"
    assert r["requires_clarification"] is True


def test_strategia_esplicita_resta_strategia():
    r = classify_objective("Prepara una strategia di posizionamento go-to-market")
    assert r["objective_type"] == "STRATEGIA"


def test_email_esplicita_resta_email():
    r = classify_objective("Scrivi una breve email commerciale per un cliente esistente")
    assert r["objective_type"] == "EMAIL"
