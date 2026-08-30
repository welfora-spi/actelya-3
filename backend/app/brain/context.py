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
import unicodedata
from dataclasses import asdict, dataclass, field

_CANALI_NOTI = [
    "Instagram", "Facebook", "LinkedIn", "TikTok", "YouTube", "X", "Twitter",
    "Google Ads", "Meta Ads", "Blog", "Newsletter", "Email", "WhatsApp", "Pinterest",
]

_PATTERN_AZIENDA_LOCALITA = re.compile(
    r"(?:del|dei|della|dello|di)\s+([A-Z][\w&'\-]*(?:\s+(?:[A-Z][\w&'\-]*|and|e|&))*)"
    r"\s+di\s+([A-Z][\wàèéìòùÀ-Ù]+)"
)
_PATTERN_AZIENDA_SEMPLICE = re.compile(r"(?:del|dei|della|dello)\s+([A-Z][\w&'\-]*(?:\s+[A-Z][\w&'\-]*)*)")
_PATTERN_LOCALITA_SEMPLICE = re.compile(r"\bdi\s+([A-Z][\wàèéìòù]+)\b")
_PATTERN_PRODOTTO = re.compile(
    r"(?:pubblicizzare|promuovere|vendere|lanciare|far conoscere)\s+(?:le|il|i|gli|la|l')?\s*"
    r"([a-zàèéìòù][\wàèéìòù\s]+?)\s+(?:del|dei|della|dello|di)\s",
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

    m = _PATTERN_AZIENDA_LOCALITA.search(testo)
    if m:
        ctx.azienda = m.group(1).strip()
        ctx.localita = m.group(2).strip()
    else:
        ma = _PATTERN_AZIENDA_SEMPLICE.search(testo)
        if ma:
            ctx.azienda = ma.group(1).strip()
        ml = _PATTERN_LOCALITA_SEMPLICE.search(testo)
        if ml and ml.group(1) != ctx.azienda:
            ctx.localita = ml.group(1).strip()

    mp = _PATTERN_PRODOTTO.search(testo)
    if mp:
        ctx.prodotto = mp.group(1).strip()

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
