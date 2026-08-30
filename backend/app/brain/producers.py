"""Brain — produttori di contenuto CONTESTUALI (deterministici, simulati).

Analoghi, per ruolo, ai produttori generici gia' presenti in
m2/deliverables.py::PRODUCERS, ma qui parametrizzati dal GoalContext estratto
dall'obiettivo (azienda, prodotto, localita, pubblico, canali) invece di usare
segnaposto fissi ("l'azienda", "PMI B2B"). Ogni produttore passa dal gateway
astratto (gateway.py) per comporre i testi: nessuna chiamata reale, nessuna
casualita'. Il risultato viene SEMPRE validato (m2/deliverables.py) e
verificato per coerenza (guard.py) da chi chiama, prima di essere proposto
come deliverable_override — questo modulo produce soltanto, non decide se il
contenuto e' accettabile."""
from __future__ import annotations

import re
import unicodedata

from .context import GoalContext
from .gateway import ContentGateway

_HOOK_TEMPLATES = [
    "Hai gia' provato {prodotto} di {azienda}? A {localita} e' il momento giusto.",
    "{azienda}: {prodotto} pensato per chi vive {localita} ogni giorno.",
    "Una pausa vera a {localita}: {prodotto} di {azienda} ti aspetta.",
    "Il sapore di {localita} in ogni proposta di {azienda}.",
    "{pubblico_breve}, questa e' per voi: {prodotto} di {azienda}.",
    "A {localita} si torna sempre da {azienda}, per {prodotto}.",
]
_CTA_TEMPLATES = [
    "Passa a trovarci", "Scoprilo di persona", "Vieni ad assaggiarlo",
    "Ti aspettiamo in negozio", "Scopri di piu' in bio", "Fatti un giro da noi",
]


def _slug(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo or "").encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9]+", "", t)
    return t or "locale"


def _segmenti_pubblico(ctx: GoalContext) -> list[dict]:
    pubblico = (ctx.pubblico or "").lower()
    localita = ctx.localita or "la zona"
    prodotto = ctx.prodotto or "l'offerta"
    candidati = []
    if "famigli" in pubblico:
        candidati.append({
            "name": "Famiglie della zona",
            "description": f"Nuclei familiari di {localita} che cercano {prodotto} genuino per la vita di tutti i giorni.",
        })
    if "lavorator" in pubblico:
        candidati.append({
            "name": "Lavoratori della zona",
            "description": f"Persone che lavorano nei dintorni di {localita} e cercano una pausa pratica e di qualita'.",
        })
    if "student" in pubblico:
        candidati.append({
            "name": "Studenti della zona",
            "description": f"Studenti di {localita} alla ricerca di un punto di riferimento comodo e accessibile.",
        })
    ripiego = [
        {"name": "Comunita' locale",
         "description": f"Residenti e frequentatori abituali di {localita}, attenti alla qualita' del territorio."},
        {"name": "Clienti di passaggio",
         "description": f"Persone che transitano per {localita} e scoprono {prodotto} per la prima volta."},
    ]
    for extra in ripiego:
        if len(candidati) >= 2:
            break
        candidati.append(extra)
    return candidati


def produce_marketing_strategy(ctx: GoalContext, cap: dict, gateway: ContentGateway) -> dict:
    azienda = ctx.azienda or "l'attivita'"
    prodotto = ctx.prodotto or "l'offerta"
    localita = ctx.localita or "la zona"
    canali = list(cap.get("canali") or ["Instagram", "Facebook"])
    return {
        "title": f"Strategia di marketing locale — {azienda} ({localita})",
        "executive_summary": gateway.fill(
            "Strategia locale simulata per {azienda}: rafforzare la presenza a {localita} "
            "puntando su {prodotto} come elemento distintivo, aumentando la notorieta' tra "
            "il pubblico del territorio e portando piu' persone in negozio attraverso "
            "contenuti social mirati e coerenti col tono di quartiere, nel prossimo mese.",
            azienda=azienda, prodotto=prodotto, localita=localita,
        ),
        "value_proposition": gateway.fill(
            "{azienda} porta a {localita} {prodotto} fatto con cura, pensato per chi vive e lavora nella zona.",
            azienda=azienda, prodotto=prodotto, localita=localita,
        ),
        "positioning": f"Realta' locale e artigianale di {localita}, vicina alla comunita' del quartiere.",
        "target_segments": _segmenti_pubblico(ctx),
        "channels": canali + (["Passaparola locale"] if len(canali) < 2 else []),
        "objectives": [
            f"Aumentare la notorieta' locale di {azienda} a {localita} (simulato)",
            f"Portare piu' visite in negozio grazie a {prodotto} (simulato)",
        ],
        "mode": "SIMULAZIONE",
    }


def produce_editorial_plan(ctx: GoalContext, cap: dict, gateway: ContentGateway) -> dict:
    azienda = ctx.azienda or "l'attivita'"
    prodotto = ctx.prodotto or "l'offerta"
    localita = ctx.localita or "la zona"
    tono = ctx.tono or "caldo, informale, di quartiere"
    canali = list(cap.get("canali") or ["Instagram", "Facebook"])
    principale, secondario = canali[0], canali[-1]
    return {
        "title": f"Piano editoriale — {azienda}",
        "cadence": "3 contenuti a settimana",
        "tone_of_voice": f"Tono {tono}, vicino alla vita quotidiana di {localita}.",
        "pillars": [f"{prodotto.capitalize()} e ingredienti", f"Vita di quartiere a {localita}", "Storie del team e della bottega"],
        "calendar": [
            {"slot": "Settimana 1 - Lun", "topic": f"Come nascono {prodotto} da {azienda}", "format": "post", "channel": principale},
            {"slot": "Settimana 1 - Mer", "topic": f"Un momento di pausa a {localita} con {azienda}", "format": "storia", "channel": secondario},
            {"slot": "Settimana 1 - Ven", "topic": f"I clienti di {localita} raccontano {azienda}", "format": "carosello", "channel": principale},
        ],
        "mode": "SIMULAZIONE",
    }


def produce_social_content(ctx: GoalContext, cap: dict, gateway: ContentGateway) -> dict:
    azienda = ctx.azienda or "l'attivita'"
    prodotto = ctx.prodotto or "l'offerta"
    localita = ctx.localita or "la zona"
    pubblico_breve = (ctx.pubblico or "il pubblico locale").split(" della zona")[0].strip().capitalize()
    canali = list(cap.get("canali") or ["Instagram", "Facebook"])
    n = max(2, int(cap.get("post_count", 2)))

    posts = []
    for i in range(n):
        canale = canali[i % len(canali)]
        hook = gateway.fill(
            _HOOK_TEMPLATES[i % len(_HOOK_TEMPLATES)],
            azienda=azienda, prodotto=prodotto, localita=localita, pubblico_breve=pubblico_breve,
        )
        body = gateway.fill(
            "Da {azienda}, a {localita}, {prodotto} preparato ogni giorno con cura per {pubblico_breve}. "
            "Vi aspettiamo per farvelo scoprire su {canale}.",
            azienda=azienda, prodotto=prodotto, localita=localita, pubblico_breve=pubblico_breve, canale=canale,
        )
        posts.append({
            "hook": hook,
            "body": body,
            "cta": _CTA_TEMPLATES[i % len(_CTA_TEMPLATES)],
            "hashtags": [f"#{_slug(localita)}", f"#{_slug(prodotto.split()[0] if prodotto else 'locale')}", f"#{_slug(azienda)}"],
        })

    return {
        "platform": " e ".join(canali),
        "posts": posts,
        "mode": "SIMULAZIONE",
    }


def produce_ad_campaign_draft(ctx: GoalContext, cap: dict, gateway: ContentGateway) -> dict:
    azienda = ctx.azienda or "l'attivita'"
    prodotto = ctx.prodotto or "l'offerta"
    localita = ctx.localita or "la zona"
    pubblico = ctx.pubblico or "pubblico locale"
    return {
        "status": "DRAFT",
        "published": False,
        "objective": f"Far conoscere {prodotto} di {azienda} a {localita} (simulato, solo bozza)",
        "audience": {
            "description": f"Persone che vivono o lavorano a {localita}, in particolare {pubblico}, interessate a {prodotto} locale.",
            "note": "Nessuna PII: solo criteri aggregati e simulati, nessun contatto reale.",
        },
        "budget_simulato": "EUR 150 totali (SIMULATO, nessuna spesa reale)",
        "ad_variants": [
            {"headline": f"{prodotto.capitalize()} di {azienda}, a {localita}",
             "primary_text": gateway.fill(
                 "Scopri {prodotto} preparato ogni giorno da {azienda}, nel cuore di {localita}.",
                 prodotto=prodotto, azienda=azienda, localita=localita),
             "cta": "Vieni a scoprirlo"},
            {"headline": f"A {localita} si torna sempre da {azienda}",
             "primary_text": gateway.fill(
                 "{azienda} ti aspetta a {localita} con {prodotto} fatto con cura, ogni giorno.",
                 azienda=azienda, localita=localita, prodotto=prodotto),
             "cta": "Passa a trovarci"},
        ],
        "mode": "SIMULAZIONE",
    }


def produce_kpi_report(ctx: GoalContext, cap: dict, gateway: ContentGateway) -> dict:
    azienda = ctx.azienda or "l'attivita'"
    localita = ctx.localita or "la zona"
    return {
        "title": f"Report KPI — {azienda} ({localita})",
        "period": "Prossimo mese (simulato)",
        "kpis": [
            {"name": "Interazioni sui post locali", "target": 200, "current": 140, "source": "SIMULATO", "unit": "interazioni/mese"},
            {"name": "Nuovi follower locali", "target": 80, "current": "NON_DISPONIBILE", "source": "NON_DISPONIBILE"},
            {"name": "Visite in negozio attribuibili alla campagna", "target": 60, "current": 35, "source": "SIMULATO", "unit": "visite/mese"},
        ],
        "note": f"Valori SIMULATO o NON_DISPONIBILE per {azienda}: nessun dato reale e' stato raccolto o inventato.",
        "mode": "SIMULAZIONE",
    }


def produce_lead_gen_plan(ctx: GoalContext, cap: dict, gateway: ContentGateway) -> dict:
    azienda = ctx.azienda or "l'attivita'"
    prodotto = ctx.prodotto or "l'offerta"
    localita = ctx.localita or "la zona"
    pubblico = ctx.pubblico or "pubblico locale"
    return {
        "title": f"Piano di lead generation locale — {azienda}",
        "icp": f"Persone e attivita' di {localita} interessate a {prodotto}, in particolare {pubblico} (profilo, non contatti reali).",
        "criteria": [f"Area geografica: {localita}", f"Interesse dichiarato per {prodotto}",
                    "Interazione con i canali social locali", f"Target: {pubblico}"],
        "channels": list(cap.get("canali") or ["Instagram", "Facebook"]),
        "outreach_sequence": [
            {"step": 1, "message_template": f"Ciao [Nome], grazie per l'interesse verso {azienda}! Ti va di scoprire di persona {prodotto}?"},
            {"step": 2, "message_template": f"Ciao [Nome], torniamo a scriverti: da {azienda} a {localita} trovi sempre {prodotto} fresco."},
        ],
        "note": "Solo criteri e template: nessun contatto reale, nessuna PII, nessun invio.",
        "mode": "SIMULAZIONE",
    }


BRAIN_PRODUCERS = {
    "marketing_strategy": produce_marketing_strategy,
    "editorial_plan": produce_editorial_plan,
    "social_content": produce_social_content,
    "ad_campaign_draft": produce_ad_campaign_draft,
    "kpi_report": produce_kpi_report,
    "lead_gen_plan": produce_lead_gen_plan,
}


def produce_brain_deliverable(deliverable_type: str, ctx: GoalContext, cap: dict, gateway: ContentGateway) -> dict | None:
    """None se non esiste un produttore contestuale per questo tipo: il
    chiamante deve ricadere sul produttore generico di m2/deliverables.py,
    mai bloccare il task per questo motivo."""
    fn = BRAIN_PRODUCERS.get(deliverable_type)
    if not fn:
        return None
    return fn(ctx, cap, gateway)
