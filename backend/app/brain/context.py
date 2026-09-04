"""Brain — estrazione del contesto dell'obiettivo (Fase 1 integrazione minima).

Estrae dal testo libero dell'obiettivo le entita' necessarie a produrre un
deliverable coerente (azienda, prodotto/servizio, localita', pubblico,
canali, tono, vincoli), con euristiche deterministiche locali (regex + liste
di parole chiave), nello stesso spirito di orchestrator/intents.py e
core/data_minimization.py di ACTELYA originale: nessuna chiamata AI, nessuna
casualita', risultato riproducibile a parita' di input.

azienda e prodotto sono i soli campi INDISPENSABILI: senza di essi non e'
possibile produrre un deliverable concreto (solo un contenuto generico), e
extract_goal_context() lo segnala con missing_critical valorizzato e domande
di chiarimento pronte per l'utente. localita/pubblico/canali/tono sono
arricchimenti: se assenti il piano procede comunque, con un contenuto meno
specifico."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

_CANALI_NOTI = [
    "Instagram", "Facebook", "LinkedIn", "TikTok", "YouTube", "X", "Twitter",
    "Google Ads", "Meta Ads", "Blog", "Newsletter", "Email", "WhatsApp", "Pinterest",
]

# Campo etichettato esplicito ("Azienda:", "Brand:", "Azienda/brand:"): ha
# sempre priorita' sui pattern euristici sotto, perche' e' una dichiarazione
# diretta invece di un'inferenza da linguaggio naturale. Generico per
# costruzione: cattura qualunque testo dopo l'etichetta, nessun nome fisso.
_PATTERN_AZIENDA_LABEL = re.compile(
    r"(?:azienda\s*/\s*brand|azienda|brand)\s*[:\-]\s*([^\n,.;]+)", re.IGNORECASE
)
_PATTERN_PRODOTTO_LABEL = re.compile(
    r"prodott[oi](?:\s*/\s*servizi[oe])?\s*[:\-]\s*([^\n,.;]+)", re.IGNORECASE
)

_PATTERN_AZIENDA_LOCALITA = re.compile(
    r"(?:del|dei|della|dello|di)\s+([A-Z][\w&'\-]*(?:\s+(?:[A-Z][\w&'\-]*|and|e|&))*)"
    r"\s+di\s+([A-Z][\wàèéìòùÀ-Ù]+)"
)
_PATTERN_AZIENDA_SEMPLICE = re.compile(r"(?:del|dei|della|dello)\s+([A-Z][\w&'\-]*(?:\s+[A-Z][\w&'\-]*)*)")
_PATTERN_LOCALITA_SEMPLICE = re.compile(r"\bdi\s+([A-Z][\wàèéìòù]+)\b")
# Prima versione: richiedeva SEMPRE una clausola "del/della/di" dopo il
# prodotto (es. "le focaccine DEL Bakery & Coffee"). Non catturava mai un
# prodotto seguito da un riferimento temporale invece che dal nome
# dell'azienda -- esattamente il caso "promuovere le focaccine QUESTO
# WEEKEND" (nessun "del/della/di" dopo "focaccine"): il prodotto restava
# indefinito e veniva chiesto di nuovo anche se gia' scritto per intero
# nella frase. Corretto con un lookahead che ferma la cattura, oltre alla
# clausola "del/...", anche davanti a un riferimento temporale comune
# (questo/prossimo/per + giorno della settimana/oggi/domani/entro/durante)
# o a fine frase/stringa -- mai includendo la data nel nome del prodotto.
_PATTERN_PRODOTTO = re.compile(
    r"(?:pubblicizz\w*|promuov\w*|vend\w*|lanc\w*|far\s+conoscere)\s+(?:le|il|i|gli|la|l')?\s*"
    r"([a-zàèéìòù][\wàèéìòù\s]*?)"
    r"(?=\s+(?:del|dei|della|dello|di)\b"
    r"|\s+(?:questo|quest['’]|prossim\w*|entro|durante|oggi|domani)\b"
    r"|\s+per\s+(?:sabato|domenica|luned[ìi]|marted[ìi]|mercoled[ìi]|gioved[ìi]|venerd[ìi]|il\s+weekend|questo\s+weekend)\b"
    r"|[.,;!?]|$)",
    re.IGNORECASE,
)
_PATTERN_PRODOTTO_DESTINAZIONE = re.compile(
    r"(?:campagna|reel|video|contenut[oi]|pubblicit[aà])[^\n,.;]*?\s+per\s+"
    r"([\wàèéìòùÀ-Ù&'\-]+(?:\s+[\wàèéìòùÀ-Ù&'\-]+){0,5})\s*$",
    re.IGNORECASE,
)
_PATTERN_PUBBLICO = re.compile(
    r"rivolt\w*\s+(?:a|alle|ai|al|all')\s+([\wàèéìòù\s]+?)(?:\.|,|;|$)", re.IGNORECASE
)
_PATTERN_TONO = re.compile(
    r"tono\s+(?:di voce\s+)?(informale|professionale|amichevole|autorevole|caldo|giovane|elegante|di quartiere)",
    re.IGNORECASE,
)
_PATTERN_VINCOLO_NEGATIVO = re.compile(
    r"\b(?:non|senza|mai)\s+(?:\w+\s+){0,2}(?:contatt\w*|invi\w*|pubblic\w*|spedi\w*|mand\w*)\w*[^.,;]*",
    re.IGNORECASE,
)
_PATTERN_DATI_SIMULATI = re.compile(r"dati\s+simulat\w*", re.IGNORECASE)

_DOMANDE = {
    "azienda": "Qual e' il nome dell'azienda, attivita' o brand per cui creare i contenuti?",
    "prodotto": "Quale prodotto o servizio specifico va promosso?",
}


@dataclass
class GoalContext:
    azienda: str | None = None
    prodotto: str | None = None
    localita: str | None = None
    pubblico: str | None = None
    canali: list[str] = field(default_factory=list)
    tono: str | None = None
    vincoli: list[str] = field(default_factory=list)
    missing_critical: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    def come_dict(self) -> dict:
        return asdict(self)


def _estrai_canali(testo: str) -> list[str]:
    trovati = []
    for canale in _CANALI_NOTI:
        if re.search(rf"\b{re.escape(canale)}\b", testo, re.IGNORECASE) and canale not in trovati:
            trovati.append(canale)
    return trovati


def extract_goal_context(goal_text: str) -> GoalContext:
    testo = goal_text or ""
    ctx = GoalContext()

    ma_label = _PATTERN_AZIENDA_LABEL.search(testo)
    if ma_label:
        ctx.azienda = ma_label.group(1).strip()

    m = _PATTERN_AZIENDA_LOCALITA.search(testo)
    if m:
        if not ctx.azienda:
            ctx.azienda = m.group(1).strip()
        ctx.localita = m.group(2).strip()
    else:
        if not ctx.azienda:
            ma = _PATTERN_AZIENDA_SEMPLICE.search(testo)
            if ma:
                ctx.azienda = ma.group(1).strip()
        ml = _PATTERN_LOCALITA_SEMPLICE.search(testo)
        if ml and ml.group(1) != ctx.azienda:
            ctx.localita = ml.group(1).strip()

    mp_label = _PATTERN_PRODOTTO_LABEL.search(testo)
    if mp_label:
        ctx.prodotto = mp_label.group(1).strip()
    else:
        mp = _PATTERN_PRODOTTO.search(testo)
        if mp:
            ctx.prodotto = mp.group(1).strip()
        else:
            mp_dest = _PATTERN_PRODOTTO_DESTINAZIONE.search(testo.strip())
            if mp_dest:
                ctx.prodotto = mp_dest.group(1).strip()

    mpub = _PATTERN_PUBBLICO.search(testo)
    if mpub:
        ctx.pubblico = mpub.group(1).strip()

    ctx.canali = _estrai_canali(testo)

    mt = _PATTERN_TONO.search(testo)
    if mt:
        ctx.tono = mt.group(1).strip().lower()

    for mv in _PATTERN_VINCOLO_NEGATIVO.finditer(testo):
        vincolo = mv.group(0).strip().rstrip(".")
        if vincolo and vincolo not in ctx.vincoli:
            ctx.vincoli.append(vincolo)
    if _PATTERN_DATI_SIMULATI.search(testo) and "usare solo dati simulati" not in ctx.vincoli:
        ctx.vincoli.append("usare solo dati simulati")

    for campo in ("azienda", "prodotto"):
        if not getattr(ctx, campo):
            ctx.missing_critical.append(campo)
            ctx.questions.append(_DOMANDE[campo])

    return ctx


# Etichetta usata per ricomponere una risposta di chiarimento in un campo
# che extract_goal_context() sa riconoscere (vedi _PATTERN_*_LABEL sopra):
# stessa sintassi in entrambe le direzioni, cosi' rispondere "ACTELYA 3" alla
# domanda sull'azienda produce un testo che l'estrazione rilegge subito come
# azienda, per qualunque nome, senza logica dedicata.
_LABEL_PER_CAMPO = {"azienda": "Azienda/brand", "prodotto": "Prodotto/servizio"}


def augment_goal_text(original_text: str, missing_information: list, answers: list) -> str:
    """Ricostruisce il testo dell'obiettivo aggiungendo le risposte
    dell'utente alle domande di chiarimento, senza scartare nulla del testo
    originale. Quando la domanda risposta corrisponde a un campo noto
    (azienda/prodotto) usa l'etichetta esplicita in modo che l'estrazione la
    rilegga in modo affidabile; altrimenti aggiunge la risposta come
    frase libera (utile per le domande generiche tipo "che tipo di
    contenuto vuoi?", pensate per far emergere una capability, non un
    campo di contesto)."""
    parti = [(original_text or "").strip()]
    for i, risposta in enumerate(answers or []):
        risposta = (risposta or "").strip()
        if not risposta:
            continue
        campo = missing_information[i] if i < len(missing_information or []) else None
        etichetta = _LABEL_PER_CAMPO.get(campo)
        if etichetta:
            parti.append(f"{etichetta}: {risposta}.")
        else:
            parti.append(risposta if risposta.endswith((".", "!", "?")) else f"{risposta}.")
    return " ".join(p for p in parti if p)
