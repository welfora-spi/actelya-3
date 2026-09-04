"""Validazione semantica DETERMINISTICA del contenuto reel (nessuna chiamata AI):
verifica che le affermazioni sul prodotto/servizio, pubblico, prezzo e territorio
generate da Requesty siano riconducibili al Fact Ledger o al brief approvato,
prima di autorizzare una generazione video (reale, a pagamento) su Runway.

Non e' una comprensione semantica vera e propria (richiederebbe un secondo
giudice AI, con un secondo costo e una seconda superficie di errore): e' un
controllo per CATEGORIE di affermazione ad alto rischio di allucinazione
(pubblico, servizio/prodotto, prezzo, territorio, claim generici tipo 'leader
di mercato'), con lo stesso stile deterministico/regex gia' usato altrove
nell'app (vedi m2/deliverables.py -> PLACEHOLDER_RE/PII_EMAIL_RE/REFUSAL_RE):
esplicita, testabile, senza falsi positivi 'a sensazione'. Puo' avere falsi
positivi legittimi (frasi generiche che contengono per caso una parola
sorvegliata): per questo il progetto resta correggibile (nuova generazione o
brief piu' ricco), mai bloccato in modo permanente."""
from __future__ import annotations

import re

# Categoria -> parole/espressioni sorvegliate. Una categoria viene contestata
# SOLO se il relativo campo del Fact Ledger/brief non la copre (vedi
# _campo_copre_categoria): non e' un elenco di parole vietate in assoluto.
CLAIM_KEYWORDS: dict[str, list[str]] = {
    "pubblico": [
        "privati", "aziende", "famiglie", "professionisti", "imprese",
        "clienti privati", "clienti aziendali", "pmi", "consumatori",
        "utenti privati", "b2b", "b2c",
    ],
    "servizio_prodotto": [
        "supporto", "assistenza", "intervento", "interventi", "riparazione",
        "riparazioni", "installazione", "manutenzione", "consulenza",
        "formazione", "assistenza tecnica", "help desk", "helpdesk",
        "problemi informatici", "problemi tecnici",
    ],
    "prezzo": [
        "gratis", "gratuito", "gratuita", "sconto", "offerta", "prezzo",
        "prezzi", "€", "euro", "promozione", "risparmi", "risparmio",
    ],
    "territorio": [
        "in tutta italia", "a domicilio", "zona", "provincia", "regione",
        "vicino a te", "nella tua città", "nella tua citta", "sul territorio",
        "sul territorio nazionale",
    ],
    # Item #5 (DECISIONE UFFICIALE): elenco ampliato dopo prova manuale reale
    # — frasi come "partner affidabile", "servizi di qualità", "esperienza e
    # professionalità", "soluzioni pensate per le tue esigenze" NON venivano
    # contestate perché la lista copriva solo forme sostantivate isolate
    # ("affidabilità", non l'aggettivo "affidabile") o frasi troppo lunghe e
    # specifiche ("anni di esperienza", non "esperienza" da sola). Nessun
    # campo Fact Ledger dedicato per questa categoria (vedi
    # CATEGORIA_CAMPI_LEDGER): resta autorizzata SOLO se il testo compare
    # verbatim nel brief dell'utente — mai un claim promozionale generico
    # lasciato passare in silenzio.
    "benefici_generici": [
        "il migliore", "leader", "numero 1", "numero uno", "garantito",
        "garantita", "24 ore su 24", "esperienza pluriennale", "da oltre",
        "anni di esperienza", "esperienza", "soluzioni su misura", "su misura",
        "affidabilità", "affidabilita", "affidabile", "affidabili",
        "qualità", "qualita", "di qualita", "professionalità", "professionalita",
        "partner affidabile", "le tue esigenze", "le vostre esigenze",
        "rispondere alle esigenze", "pensate per",
    ],
}

# Categoria -> campo/i del Fact Ledger (o del brief) che, se valorizzati,
# autorizzano quella categoria di affermazione (perche' allora ha una base
# reale dichiarata, non inventata dal modello).
CATEGORIA_CAMPI_LEDGER: dict[str, tuple[str, ...]] = {
    "pubblico": ("pubblico_target",),
    "servizio_prodotto": ("prodotto",),
    # prezzo/territorio/benefici_generici non hanno un campo Fact Ledger
    # dedicato in questa fase: sono autorizzati SOLO se il testo esatto
    # compare gia' nel brief fornito dall'utente (mai altrimenti).
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _normalizza(testo: str) -> str:
    return (testo or "").strip().lower()


def _frasi(testo: str) -> list[str]:
    testo = (testo or "").strip()
    if not testo:
        return []
    return [f.strip() for f in _SENTENCE_SPLIT_RE.split(testo) if f.strip()]


def _campi_testuali(content: dict) -> list[tuple[str, str]]:
    """(nome_campo, testo) per ogni campo testuale rilevante del contenuto reel,
    storyboard incluso (ogni scena, con etichetta dedicata)."""
    campi = [
        ("concept", content.get("concept", "")),
        ("hook", content.get("hook", "")),
        ("sceneggiatura", content.get("sceneggiatura", "")),
        ("voice_over_completo", content.get("voice_over_completo", "")),
        ("caption", content.get("caption", "")),
        ("cta", content.get("cta", "")),
    ]
    for t in content.get("testi_a_schermo") or []:
        campi.append(("testi_a_schermo", str(t)))
    for h in content.get("hashtags") or []:
        campi.append(("hashtags", str(h)))
    for i, scena in enumerate(content.get("storyboard") or [], 1):
        if not isinstance(scena, dict):
            continue
        campi.append((f"storyboard[{i}].descrizione_visiva", scena.get("descrizione_visiva", "")))
        campi.append((f"storyboard[{i}].testo_a_schermo", scena.get("testo_a_schermo", "")))
        campi.append((f"storyboard[{i}].voice_over", scena.get("voice_over", "")))
    return campi


def _categoria_autorizzata(categoria: str, contesto: dict, brief: str) -> bool:
    campi_ledger = CATEGORIA_CAMPI_LEDGER.get(categoria, ())
    for campo in campi_ledger:
        valore = _normalizza(contesto.get(campo, ""))
        if valore and valore != "informazione non disponibile":
            return True
    # Fallback comune a tutte le categorie: se la parola sorvegliata compare
    # gia' verbatim nel brief fornito dall'utente, e' un'affermazione voluta
    # dall'utente, non un'allucinazione del modello.
    return False


def _scan_campi(campi: list[tuple[str, str]], contesto: dict, brief: str) -> dict:
    """Nucleo condiviso della scansione (mai duplicato): usato sia per il
    contenuto reel sia per il contenuto flyer (domains/flyer.py), ciascuno
    con la propria lista di campi testuali rilevanti (vedi _campi_testuali
    qui sotto e flyer.py::_campi_testuali_flyer)."""
    brief_norm = _normalizza(brief)
    contestate = []
    viste = set()  # evita duplicati esatti (stessa frase/categoria da campi diversi)

    for campo, testo in campi:
        for frase in _frasi(testo):
            frase_norm = _normalizza(frase)
            for categoria, parole in CLAIM_KEYWORDS.items():
                for parola in parole:
                    if parola not in frase_norm:
                        continue
                    if parola in brief_norm:
                        continue  # esplicitamente richiesto dall'utente nel brief
                    if _categoria_autorizzata(categoria, contesto, brief):
                        continue
                    chiave = (categoria, frase_norm)
                    if chiave in viste:
                        continue
                    viste.add(chiave)
                    contestate.append({
                        "categoria": categoria, "campo": campo, "frase": frase, "parola_chiave": parola,
                    })

    status = "CONTESTATO" if contestate else "OK"
    return {"status": status, "affermazioni_contestate": contestate}


def semantic_validate_reel_content(content: dict, contesto: dict, brief: str = "") -> dict:
    """Ritorna {'status': 'OK'|'CONTESTATO', 'affermazioni_contestate': [...]}.
    Ogni voce contestata: {categoria, campo, frase, parola_chiave}. Non solleva
    mai un'eccezione: un contenuto malformato produce solo 'nessuna frase da
    controllare' (nessun testo da validare), non un errore bloccante qui (la
    validazione strutturale e' gia' fatta da validate_reel_content)."""
    if not isinstance(content, dict):
        return {"status": "OK", "affermazioni_contestate": []}
    return _scan_campi(_campi_testuali(content), contesto, brief)


def semantic_validate_generic_content(campi_testuali: list[tuple[str, str]], contesto: dict, brief: str = "") -> dict:
    """Stessa scansione, per contenuti diversi dal reel (es. flyer): il
    chiamante fornisce direttamente l'elenco (campo, testo) da controllare."""
    return _scan_campi(campi_testuali, contesto, brief)
