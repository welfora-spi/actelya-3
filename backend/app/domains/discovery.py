"""Discovery — analisi automatica di sito e social per popolare il Fact Ledger.

La stima di tono/pubblico resta SEMPRE l'euristica deterministica (basata
sull'URL/dominio dichiarato, mai promossa a VERIFICATO in automatico — vedi
TONES/AUDIENCES sotto). Il fetch REALE della pagina pubblica dichiarata
(fetch_sito_reale) e' invece un'estrazione vera (titolo/meta/H1/testo/link
social), gia con protezioni SSRF complete a ogni hop — attivo SOLO per
un'organizzazione che ha esplicitamente concesso il permesso dedicato
(settings.discovery_real_fetch, vedi domains/settings.py — indipendente dal
flag globale REAL_EXTERNAL_ACTIONS, che resta quello di connettori/
pubblicazione social). Nessuna chiamata AI, nessun costo: solo un GET HTTP
(+ un rendering JS opzionale, stesso permesso, quando il fetch statico non
basta — vedi _fetch_con_rendering_js). Gira come coda persistente con un
worker recuperabile, cosi' un obiettivo puo' essere creato mentre una
ricerca e' ancora IN_ESECUZIONE (nessun blocco reciproco)."""
import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import db
from ..deps import get_current_user, require_roles, assert_same_org
from ..audit import log_audit
from ..models import now_iso, new_id, base_record
from ..config import DEFAULT_ORG_ID
from .knowledge import write_fact

logger = logging.getLogger("actelya.discovery")
router = APIRouter(prefix="/discovery", tags=["discovery"])

_worker_task = None
RUN_DELAY_SECONDS = 2  # simulates "search in progress" so status is observably IN_ESECUZIONE

TONES = ["Professionale e diretto", "Amichevole e informale", "Autorevole e tecnico"]
AUDIENCES = ["Piccole e medie imprese locali", "Consumatori privati nel territorio servito",
            "Professionisti e studi di settore"]

# ================== Fetch reale OPZIONALE del sito dichiarato (item 3/9/13) ==================
# La stima di tono/pubblico resta SEMPRE l'euristica deterministica sopra (mai
# promossa a "capita davvero il sito": servirebbe NLP reale, fuori scopo qui).
# Questo blocco aggiunge SOLO, quando possibile, un'estrazione vera di
# titolo/meta-description/H1/testo essenziale/prodotti-servizi candidati/link
# social dalla pagina pubblica dichiarata, mai al posto della stima simulata,
# sempre in aggiunta e sempre disattivabile (REAL_EXTERNAL_ACTIONS).
#
# Protezione SSRF a piu' livelli, ciascuno verificato ad OGNI hop (compresi i
# redirect, mai solo sull'URL iniziale):
# 1) schema HTTP/HTTPS obbligatorio, host non vuoto, nessun TLD/hostname
#    interno (.local/.internal/.test/.invalid/.localhost, 'localhost' nudo);
# 2) risoluzione DNS REALE dell'host (mai fidarsi del solo hostname: previene
#    DNS rebinding verso un IP privato dietro un nome pubblico) e verifica che
#    OGNI indirizzo risolto (IPv4 e IPv6) sia pubblico (non privato, non
#    loopback, non link-local, non riservato, non multicast, non unspecified);
# 3) redirect seguiti manualmente (mai allow_redirects=True, che nascondrebbe
#    gli hop intermedi), fino a MAX_REDIRECT, con la STESSA verifica 1+2
#    ripetuta a ogni hop;
# 4) Content-Type deve essere HTML (mai un binario/PDF processato come testo);
# 5) dimensione limitata in streaming (mai l'intero corpo scaricato prima di
#    troncare: uno stream illimitato lato server non deve mai riempire la
#    memoria del processo).
_TLD_INTERNI = (".local", ".internal", ".test", ".invalid", ".localhost")
MAX_REDIRECT = 3
REAL_FETCH_TIMEOUT_SECONDI = 8.0
REAL_FETCH_MAX_BYTES = 300_000
CONTENT_TYPE_CONSENTITI = ("text/html", "application/xhtml+xml")

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', re.IGNORECASE
)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_H2H3_RE = re.compile(r"<h[23][^>]*>(.*?)</h[23]>", re.IGNORECASE | re.DOTALL)
# <noscript> incluso: il browser lo lascia SEMPRE nel DOM anche a rendering
# JS riuscito (non lo rimuove, si limita a non visualizzarlo) — un
# messaggio "abilita JavaScript" li' dentro non deve mai far apparire
# insufficiente un rendering che in realta' ha prodotto contenuto vero
# (osservato realmente su spitool.it durante la verifica di questa
# correzione: senza questa esclusione, il fallback JS veniva scartato
# nonostante avesse letto la pagina con successo).
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_JSONLD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                        re.IGNORECASE | re.DOTALL)
_SOCIAL_HREF_RE = re.compile(
    r'href=["\'](((?:https?:)?//(?:www\.)?(?:instagram|facebook|linkedin|tiktok|youtube|twitter|x)\.com/[^"\'\s]+))["\']',
    re.IGNORECASE,
)


def _ip_pubblico(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified)


def _schema_e_host_validi(url: str) -> tuple[bool, str, int]:
    """Solo controllo sintattico (schema/host/TLD interni): NESSUna
    risoluzione DNS qui (fatta separatamente in _dns_pubblico, cosi' resta
    testabile senza una vera rete)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "", 0
    if parsed.scheme not in ("http", "https"):
        return False, "", 0
    host = (parsed.hostname or "").lower()
    if not host or host == "localhost" or any(host.endswith(tld) for tld in _TLD_INTERNI):
        return False, "", 0
    porta = parsed.port or (443 if parsed.scheme == "https" else 80)
    return True, host, porta


def _dns_pubblico(host: str, porta: int) -> bool:
    try:
        risultati = socket.getaddrinfo(host, porta, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OverflowError):
        return False
    indirizzi = {r[4][0] for r in risultati if r[4]}
    if not indirizzi:
        return False
    return all(_ip_pubblico(ip) for ip in indirizzi)


def _url_pubblico_e_risolvibile(url: str) -> bool:
    ok, host, porta = _schema_e_host_validi(url)
    if not ok:
        return False
    return _dns_pubblico(host, porta)


def _estrai_testo_essenziale(html: str, max_chars: int = 1500) -> str:
    senza_script = _SCRIPT_STYLE_RE.sub(" ", html)
    senza_tag = _ANY_TAG_RE.sub(" ", senza_script)
    return re.sub(r"\s+", " ", senza_tag).strip()[:max_chars]


def _estrai_prodotti_da_jsonld(html: str) -> list[str]:
    """Prodotti/servizi che il sito stesso dichiara in dati strutturati
    schema.org (JSON-LD, <script type="application/ld+json">) — lo STESSO
    formato machine-readable che Google e gli altri motori di ricerca usano
    per capire l'offerta di un'organizzazione. Quando presente e' un
    segnale strutturale molto piu' affidabile di un titolo h2/h3 (il sito
    dichiara esplicitamente "questi sono i miei prodotti/servizi", non e'
    un'inferenza da formattazione visiva che puo' confondere un nome
    prodotto con un titolo di sezione o uno slogan). Generico per
    costruzione: nessun nome fisso, nessuna azienda specifica — funziona
    per qualunque organizzazione che pubblichi Organization.makesOffer o un
    OfferCatalog, entrambi vocabolario standard schema.org."""
    nomi: list[str] = []
    for blocco in _JSONLD_RE.findall(html):
        try:
            dati = json.loads(blocco.strip())
        except (ValueError, TypeError):
            continue
        for voce in (dati if isinstance(dati, list) else [dati]):
            if not isinstance(voce, dict):
                continue
            offerte = voce.get("makesOffer")
            if isinstance(offerte, dict):
                offerte = [offerte]
            if not isinstance(offerte, list):
                catalogo = voce.get("hasOfferCatalog")
                offerte = catalogo.get("itemListElement") if isinstance(catalogo, dict) else None
            if not isinstance(offerte, list):
                continue
            for offerta in offerte:
                if not isinstance(offerta, dict):
                    continue
                item = offerta.get("itemOffered") if isinstance(offerta.get("itemOffered"), dict) else offerta
                nome = (item.get("name") or "").strip() if isinstance(item, dict) else ""
                if nome and 1 <= len(nome) <= 80 and nome not in nomi:
                    nomi.append(nome)
        if len(nomi) >= 12:
            break
    return nomi[:12]


# Parole che segnalano una didascalia/slogan di sezione o un riferimento al
# PUBBLICO invece di un nome di prodotto/servizio — usate SOLO per scartare
# titoli h2/h3 palesemente non-prodotto nel fallback euristico sotto (mai
# per riconoscere un prodotto specifico: nessun nome di azienda qui).
_TITOLO_NON_PRODOTTO_RE = re.compile(
    r"\b(chi (siamo|offre|vive)|un (unico|solo) (metodo|team)|costruiti attorno|due mondi|"
    r"professionisti e |consulenti\b|pmi e |attivit[aà]\b|persone|famiglie|clienti\b)",
    re.IGNORECASE,
)


def _estrai_prodotti_servizi_candidati(html: str) -> list[str]:
    """Fallback SOLO euristico (titoli h2/h3 brevi, esclusi quelli che
    sembrano didascalie di sezione o riferimenti al pubblico anziche' nomi
    di prodotto) — usato SOLO quando il sito non pubblica dati strutturati
    (vedi _estrai_prodotti_da_jsonld, sempre preferito quando disponibile).
    MAI presentato come un fatto certo — confidence bassa, method ESTRATTO,
    mai VERIFICATO (vedi process_run, dove questi valori vengono scritti
    nel Fact Ledger con confidence esplicitamente ridotta)."""
    out: list[str] = []
    for grezzo in _H2H3_RE.findall(html):
        testo = re.sub(r"\s+", " ", _ANY_TAG_RE.sub(" ", grezzo)).strip()
        if not (3 <= len(testo) <= 80) or testo in out:
            continue
        if _TITOLO_NON_PRODOTTO_RE.search(testo):
            continue
        out.append(testo)
        if len(out) >= 8:
            break
    return out


def _estrai_prodotti_servizi(html: str) -> tuple[list[str], str | None]:
    """Punto UNICO da cui process_run ottiene i candidati prodotto/servizio:
    preferisce sempre i dati strutturati (fonte='jsonld', confidence piu'
    alta ma comunque MAI 'certa' — resta un'estrazione automatica, non una
    conferma umana) e ricade sull'euristica (fonte='euristica', confidence
    bassa) solo se il sito non ne pubblica. Ritorna (lista, fonte) — fonte
    None se non e' stato trovato nulla in nessuno dei due modi."""
    dai_dati_strutturati = _estrai_prodotti_da_jsonld(html)
    if dai_dati_strutturati:
        return dai_dati_strutturati, "jsonld"
    euristici = _estrai_prodotti_servizi_candidati(html)
    if euristici:
        return euristici, "euristica"
    return [], None


def _estrai_social_links(html: str) -> list[str]:
    trovati: list[str] = []
    for m in _SOCIAL_HREF_RE.finditer(html):
        url = m.group(1)
        if url.startswith("//"):
            url = "https:" + url
        if url not in trovati:
            trovati.append(url)
        if len(trovati) >= 10:
            break
    return trovati


# Esiti possibili di un tentativo di lettura reale — SEMPRE uno di questi,
# mai un None indistinto: il chiamante (e la UI, vedi Onboarding.jsx) deve
# poter distinguere "profilo/pagina trovata e letta" da "accesso impedito"
# da "nessun risultato", non solo "simulato sì/no".
ESITO_LETTO = "CONTENUTO_LETTO"
ESITO_INSUFFICIENTE_JS = "CONTENUTO_INSUFFICIENTE_RICHIEDE_JS"
ESITO_ACCESSO_IMPEDITO = "ACCESSO_IMPEDITO"
ESITO_NESSUN_RISULTATO = "NESSUN_RISULTATO"


async def _discovery_real_fetch_abilitato(db_conn, org_id: str) -> bool:
    """Permesso SPECIFICO per Discovery (settings.discovery_real_fetch, vedi
    domains/settings.py) — MAI il flag globale REAL_EXTERNAL_ACTIONS, che
    resta quello di connettori/pubblicazione social e non deve essere
    acceso solo per leggere una pagina pubblica senza costo."""
    try:
        s = await db_conn.settings.find_one({"id": org_id}, {"_id": 0, "discovery_real_fetch": 1})
    except (AttributeError, TypeError):
        return False
    return bool(s and s.get("discovery_real_fetch"))


def _fetch_sincrono(url: str) -> dict:
    """Esegue in un thread separato (mai sull'event loop): I/O bloccante di
    proposito, stessa convenzione di ogni altra integrazione HTTP sincrona
    del progetto (requests, mai httpx/asyncio nativo). Nessuna eccezione
    propagata: ogni esito (incluso ogni tipo di fallimento) torna come
    dict con 'ok' e 'motivo' espliciti, mai un None indistinto — il
    chiamante deve poter dire ACCESSO_IMPEDITO da NESSUN_RISULTATO."""
    import requests

    corrente = url
    for _ in range(MAX_REDIRECT + 1):
        if not _url_pubblico_e_risolvibile(corrente):
            logger.info("Discovery: host non pubblico/non risolvibile, fetch saltato.")
            return {"ok": False, "motivo": "host_non_pubblico", "url_tentato": corrente}
        try:
            risposta = requests.get(
                corrente, timeout=REAL_FETCH_TIMEOUT_SECONDI, allow_redirects=False, stream=True,
                headers={"User-Agent": "ACTELYA-ResearchService/1.0"},
            )
        except Exception as exc:
            logger.info("Discovery: fetch fallito (%s).", exc)
            return {"ok": False, "motivo": "errore_rete", "url_tentato": corrente, "dettaglio": str(exc)}
        try:
            if risposta.status_code in (301, 302, 303, 307, 308):
                location = risposta.headers.get("Location")
                if not location:
                    return {"ok": False, "motivo": "redirect_senza_location", "url_tentato": corrente}
                corrente = urljoin(corrente, location)
                continue
            if risposta.status_code != 200:
                return {"ok": False, "motivo": "status_non_ok", "url_tentato": corrente,
                       "status_code": risposta.status_code}
            content_type = (risposta.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if content_type and content_type not in CONTENT_TYPE_CONSENTITI:
                logger.info("Discovery: content-type '%s' non ammesso, fetch scartato.", content_type)
                return {"ok": False, "motivo": "content_type_non_ammesso", "url_tentato": corrente}
            corpo = bytearray()
            for chunk in risposta.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                corpo.extend(chunk)
                if len(corpo) >= REAL_FETCH_MAX_BYTES:
                    break
            return {
                "ok": True, "url_finale": corrente, "status_code": risposta.status_code,
                "testo": bytes(corpo[:REAL_FETCH_MAX_BYTES]).decode("utf-8", errors="replace"),
            }
        finally:
            risposta.close()
    logger.info("Discovery: troppi redirect (> %s), fetch annullato.", MAX_REDIRECT)
    return {"ok": False, "motivo": "troppi_redirect", "url_tentato": corrente}


_JS_REQUIRED_MARKERS = ("abilitare javascript", "enable javascript", "richiede javascript",
                        "javascript is required", "please enable javascript")
_TESTO_INSUFFICIENTE_SOGLIA = 200  # caratteri: sotto questa soglia, il fetch statico e' considerato inadeguato


def _contenuto_insufficiente(testo_essenziale: str | None, html: str) -> bool:
    """Vero quando il markup statico non porta contenuto utile — pagina
    JS-only (marker esplicito nel testo, o corpo troppo corto per essere
    una pagina reale) — mai un giudizio sulla qualita' del contenuto, solo
    sulla sua quantita'/presenza di un marcatore esplicito."""
    testo_norm = (testo_essenziale or "").strip().lower()
    if any(m in testo_norm for m in _JS_REQUIRED_MARKERS):
        return True
    return len(testo_norm) < _TESTO_INSUFFICIENTE_SOGLIA


def _estrai_campi(html: str) -> dict:
    titolo = None
    m = _TITLE_RE.search(html)
    if m:
        titolo = re.sub(r"\s+", " ", m.group(1)).strip()[:200] or None
    meta_description = None
    m2 = _META_DESC_RE.search(html)
    if m2:
        meta_description = re.sub(r"\s+", " ", m2.group(1)).strip()[:400] or None
    h1 = None
    m3 = _H1_RE.search(html)
    if m3:
        h1 = re.sub(r"\s+", " ", _ANY_TAG_RE.sub(" ", m3.group(1))).strip()[:200] or None
    prodotti, prodotti_fonte = _estrai_prodotti_servizi(html)
    return {
        "titolo": titolo, "meta_description": meta_description, "h1": h1,
        "testo_essenziale": _estrai_testo_essenziale(html) or None,
        "prodotti_servizi_candidati": prodotti,
        "prodotti_servizi_fonte": prodotti_fonte,  # "jsonld" | "euristica" | None
        "social_links": _estrai_social_links(html),
    }


# ============ Fallback di rendering JS (item esplicito di questa attivita') ============
# SOLO quando il fetch statico e' insufficiente (_contenuto_insufficiente),
# SOLO con lo stesso permesso dedicato di Discovery, MAI al posto del fetch
# statico. Soft dependency: se 'playwright' non e' installato (o il browser
# non e' stato scaricato con 'python -m playwright install chromium'),
# degrada silenziosamente (nessuna eccezione propagata, stesso principio di
# _fetch_sincrono) restituendo None — il chiamante ricade sull'esito del
# fetch statico, mai un crash per una dipendenza opzionale mancante.
#
# Protezione SSRF ANCHE qui, non solo sulla navigazione iniziale: ogni
# richiesta di rete che la pagina genera (script/XHR/iframe/redirect) passa
# da un intercettore (page.route) che rivalida host pubblico + DNS reale
# prima di lasciarla proseguire — una pagina malevola non puo' usare il
# browser come proxy verso una rete privata solo perche' la navigazione
# iniziale era pubblica.
REAL_FETCH_JS_TIMEOUT_MS = 12_000


async def _fetch_con_rendering_js(url: str) -> dict | None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("Discovery: playwright non installato, nessun fallback di rendering JS disponibile.")
        return None

    def _host_consentito(candidate_url: str) -> bool:
        try:
            return _url_pubblico_e_risolvibile(candidate_url)
        except Exception:
            return False

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(timeout=REAL_FETCH_JS_TIMEOUT_MS)
            try:
                context = await browser.new_context(user_agent="ACTELYA-ResearchService/1.0 (+JS-render)")
                page = await context.new_page()

                async def _guardia_ssrf(route):
                    req_url = route.request.url
                    if not req_url.startswith(("http://", "https://")) or not _host_consentito(req_url):
                        await route.abort()
                        return
                    await route.continue_()

                await page.route("**/*", _guardia_ssrf)
                if not _host_consentito(url):
                    return None
                risposta = await page.goto(url, timeout=REAL_FETCH_JS_TIMEOUT_MS, wait_until="networkidle")
                if risposta is None or not risposta.ok:
                    return None
                url_finale = page.url
                if not _host_consentito(url_finale):
                    return None
                html = await page.content()
                status_code = risposta.status
                return {"ok": True, "url_finale": url_finale, "status_code": status_code, "testo": html}
            finally:
                await browser.close()
    except Exception as exc:
        logger.info("Discovery: rendering JS fallito (%s).", exc)
        return None


async def fetch_sito_reale(db_conn, org_id: str, website: str) -> dict | None:
    """Ritorna SEMPRE un dict con 'esito' esplicito (CONTENUTO_LETTO /
    CONTENUTO_INSUFFICIENTE_RICHIEDE_JS / ACCESSO_IMPEDITO /
    NESSUN_RISULTATO) quando il permesso e' attivo, altrimenti None (nessun
    tentativo fatto, permesso non concesso — il chiamante ricade sempre
    sulla sola stima simulata esistente)."""
    if not await _discovery_real_fetch_abilitato(db_conn, org_id):
        return None
    url = website if "://" in website else f"https://{website}"

    esito_statico = await asyncio.to_thread(_fetch_sincrono, url)
    if not esito_statico.get("ok"):
        motivo = esito_statico.get("motivo")
        esito = ESITO_ACCESSO_IMPEDITO if motivo in (
            "host_non_pubblico", "status_non_ok", "content_type_non_ammesso", "troppi_redirect",
            "redirect_senza_location",
        ) else ESITO_NESSUN_RISULTATO
        return {"url": esito_statico.get("url_tentato") or url, "status_code": esito_statico.get("status_code"),
               "esito": esito, "motivo": motivo, "titolo": None, "meta_description": None, "h1": None,
               "testo_essenziale": None, "prodotti_servizi_candidati": [], "prodotti_servizi_fonte": None,
               "social_links": [], "acquisito_il": now_iso(), "via_rendering_js": False}

    campi = _estrai_campi(esito_statico["testo"])
    via_js = False
    if _contenuto_insufficiente(campi["testo_essenziale"], esito_statico["testo"]):
        risultato_js = await _fetch_con_rendering_js(esito_statico["url_finale"])
        if risultato_js and risultato_js.get("ok"):
            campi_js = _estrai_campi(risultato_js["testo"])
            if not _contenuto_insufficiente(campi_js["testo_essenziale"], risultato_js["testo"]):
                campi = campi_js
                esito_statico = {**esito_statico, "url_finale": risultato_js["url_finale"],
                                 "status_code": risultato_js["status_code"]}
                via_js = True

    if not any([campi["titolo"], campi["meta_description"], campi["h1"], campi["testo_essenziale"]]):
        return {"url": esito_statico["url_finale"], "status_code": esito_statico["status_code"],
               "esito": ESITO_NESSUN_RISULTATO, "motivo": "pagina_vuota_o_solo_javascript",
               "titolo": None, "meta_description": None, "h1": None, "testo_essenziale": None,
               "prodotti_servizi_candidati": [], "prodotti_servizi_fonte": None,
               "social_links": [], "acquisito_il": now_iso(), "via_rendering_js": via_js}

    esito_finale = (
        ESITO_LETTO if via_js or not _contenuto_insufficiente(campi["testo_essenziale"], "")
        else ESITO_INSUFFICIENTE_JS
    )
    return {
        "url": esito_statico["url_finale"], "status_code": esito_statico["status_code"], "esito": esito_finale,
        "motivo": None, **campi, "acquisito_il": now_iso(), "via_rendering_js": via_js,
    }


def _dominio_normalizzato(url: str) -> str:
    """Dominio nudo (host, minuscolo, senza 'www.') da un URL reale — usato
    come 'source' dei fatti da fetch reale: due pagine diverse dello STESSO
    sito (o lo stesso URL riletto con query/hash diversi) non devono
    contare come fonti indipendenti solo perche' l'URL esatto differisce
    (vedi write_fact::confirms)."""
    host = (urlparse(url).hostname or url).lower()
    return host[4:] if host.startswith("www.") else host


def _stable_choice(options: list, seed: str):
    if not options:
        return None
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return options[int(digest, 16) % len(options)]


class RunBody(BaseModel):
    pass


def _public(run: dict) -> dict:
    return {k: v for k, v in run.items() if k != "_id"}


@router.post("/run")
async def start_run(user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    org = await db.organizations.find_one({"id": org_id}, {"_id": 0}) or {}
    website = (org.get("sito_web") or "").strip()
    social = [s.strip() for s in (org.get("canali_utilizzati") or "").split(",") if s.strip()]
    if not website and not social:
        raise HTTPException(status_code=400,
                            detail="Nessun sito o canale social dichiarato: completa prima l'onboarding.")
    run = base_record(org_id, user["id"])
    run.update({
        "id": new_id("disco"), "status": "IN_CODA", "mode": "SIMULATO",
        "target_website": website, "target_social": social,
        "started_at": None, "finished_at": None, "facts_written": [], "warnings": [],
        "real_fetch": None,
    })
    await db.discovery_runs.insert_one(run)
    await log_audit(org_id=org_id, user=user, action="DISCOVERY_QUEUED",
                    entity_type="discovery_run", entity_id=run["id"], details={"website": website})
    return _public(run)


@router.get("/runs")
async def list_runs(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    rows = await db.discovery_runs.find({"organization_id": org_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return rows


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: dict = Depends(get_current_user)):
    run = await db.discovery_runs.find_one({"id": run_id}, {"_id": 0})
    assert_same_org(run, user, "Ricerca non trovata")
    return run


async def process_run(run: dict):
    run_id = run["id"]
    claimed = await db.discovery_runs.find_one_and_update(
        {"id": run_id, "status": "IN_CODA"},
        {"$set": {"status": "IN_ESECUZIONE", "started_at": now_iso()}},
    )
    if not claimed:
        return
    org_id = run["organization_id"]
    actor_id = run["created_by"]
    await asyncio.sleep(RUN_DELAY_SECONDS)

    facts_written = []
    warnings = list(run.get("warnings", []))
    website = run.get("target_website") or ""
    social = run.get("target_social") or []

    real_fetch = None
    try:
        if website:
            domain = urlparse(website if "://" in website else f"//{website}", scheme="").netloc or website
            tone = _stable_choice(TONES, domain)
            audience = _stable_choice(AUDIENCES, domain + "a")
            f1 = await write_fact(db, org_id=org_id, user_id=actor_id, field="tono_di_voce", value=tone,
                                  source="discovery_sito", method="ESTRATTO", confidence=0.55)
            f2 = await write_fact(db, org_id=org_id, user_id=actor_id, field="pubblico_target", value=audience,
                                  source="discovery_sito", method="ESTRATTO", confidence=0.55)
            facts_written.extend(f["id"] for f in (f1, f2) if f)

            # Estrazione REALE (permesso dedicato settings.discovery_real_fetch):
            # SOLO additiva rispetto alla stima simulata sopra, mai al suo
            # posto. Disattiva/fallisce sempre in modo sicuro (vedi
            # fetch_sito_reale): l'esito e' tracciato esplicitamente in
            # real_fetch['esito'] (CONTENUTO_LETTO/…RICHIEDE_JS/
            # ACCESSO_IMPEDITO/NESSUN_RISULTATO) — fatti scritti SOLO se il
            # contenuto e' stato davvero letto, mai per un accesso impedito
            # o una pagina vuota. 'source' per la deduplicazione/rinforzo e'
            # il DOMINIO (non l'URL esatto): pagine diverse dello stesso
            # sito non devono contare come fonti indipendenti (vedi
            # write_fact); l'URL esatto/il timestamp/uno stralcio del testo
            # restano comunque tracciati come evidenza sul fatto (evidence).
            real_fetch = await fetch_sito_reale(db, org_id, website)
            if real_fetch and real_fetch.get("esito") in (ESITO_ACCESSO_IMPEDITO, ESITO_NESSUN_RISULTATO,
                                                           ESITO_INSUFFICIENTE_JS):
                etichetta = {
                    ESITO_ACCESSO_IMPEDITO: f"Sito dichiarato non raggiungibile ({real_fetch.get('motivo')}): nessun fatto reale estratto.",
                    ESITO_NESSUN_RISULTATO: "Sito raggiunto ma senza contenuto utilizzabile: nessun fatto reale estratto.",
                    ESITO_INSUFFICIENTE_JS: "Il sito richiede JavaScript e il rendering di fallback non ha prodotto contenuto sufficiente: nessun fatto reale estratto.",
                }[real_fetch["esito"]]
                warnings.append(etichetta)
            elif real_fetch and real_fetch.get("esito") == ESITO_LETTO:
                fonte_dominio = _dominio_normalizzato(real_fetch["url"])
                evidenza_base = {"url": real_fetch["url"], "acquisito_il": real_fetch["acquisito_il"]}
                extra_facts = []
                if real_fetch.get("titolo"):
                    extra_facts.append(await write_fact(
                        db, org_id=org_id, user_id=actor_id, field="titolo_sito_estratto",
                        value=real_fetch["titolo"], source=fonte_dominio, method="ESTRATTO", confidence=0.75,
                        evidence={**evidenza_base, "estratto": real_fetch["titolo"][:200]},
                    ))
                if real_fetch.get("meta_description"):
                    extra_facts.append(await write_fact(
                        db, org_id=org_id, user_id=actor_id, field="descrizione_sito_estratta",
                        value=real_fetch["meta_description"], source=fonte_dominio, method="ESTRATTO", confidence=0.75,
                        evidence={**evidenza_base, "estratto": real_fetch["meta_description"][:400]},
                    ))
                if real_fetch.get("h1"):
                    extra_facts.append(await write_fact(
                        db, org_id=org_id, user_id=actor_id, field="titolo_principale_sito",
                        value=real_fetch["h1"], source=fonte_dominio, method="ESTRATTO", confidence=0.7,
                        evidence={**evidenza_base, "estratto": real_fetch["h1"][:200]},
                    ))
                if real_fetch.get("prodotti_servizi_candidati"):
                    valore = ", ".join(real_fetch["prodotti_servizi_candidati"])
                    # Confidenza differenziata per fonte (mai una cifra
                    # fissa uguale per entrambe): dati strutturati
                    # schema.org dichiarati dal sito stesso restano comunque
                    # ESTRATTO (mai VERIFICATO: nessuna conferma umana), ma
                    # sono un segnale strutturale, non un'inferenza da
                    # formattazione — l'euristica h2/h3 resta la piu' bassa.
                    fonte_prodotti = real_fetch.get("prodotti_servizi_fonte")
                    confidence_prodotti = 0.6 if fonte_prodotti == "jsonld" else 0.35
                    extra_facts.append(await write_fact(
                        db, org_id=org_id, user_id=actor_id, field="prodotti_servizi_candidati",
                        value=valore, source=fonte_dominio,
                        method="ESTRATTO", confidence=confidence_prodotti,
                        evidence={**evidenza_base, "estratto": valore[:400],
                                 "metodo_estrazione": fonte_prodotti or "sconosciuto"},
                    ))
                if real_fetch.get("social_links"):
                    valore = ", ".join(real_fetch["social_links"])
                    extra_facts.append(await write_fact(
                        db, org_id=org_id, user_id=actor_id, field="social_links_estratti",
                        value=valore, source=fonte_dominio, method="ESTRATTO", confidence=0.75,
                        evidence={**evidenza_base, "estratto": valore[:400]},
                    ))
                facts_written.extend(f["id"] for f in extra_facts if f)
        else:
            warnings.append("Nessun sito web dichiarato: analisi limitata ai social.")

        if social:
            f3 = await write_fact(db, org_id=org_id, user_id=actor_id, field="presenza_social",
                                  value=", ".join(social), source="discovery_social", method="ESTRATTO",
                                  confidence=0.55)
            facts_written.extend(f["id"] for f in (f3,) if f)
        else:
            warnings.append("Nessun canale social dichiarato.")

        await db.discovery_runs.update_one(
            {"id": run_id},
            {"$set": {"status": "COMPLETATO", "finished_at": now_iso(), "updated_at": now_iso(),
                      "facts_written": facts_written, "warnings": warnings, "real_fetch": real_fetch}},
        )
        await log_audit(org_id=org_id, user={"email": "system"}, action="DISCOVERY_COMPLETED",
                        entity_type="discovery_run", entity_id=run_id,
                        details={"facts_written": len(facts_written), "warnings": warnings})
    except Exception:
        logger.exception("Discovery run fallita")
        await db.discovery_runs.update_one(
            {"id": run_id},
            {"$set": {"status": "FALLITO", "finished_at": now_iso(), "updated_at": now_iso()}},
        )
        await log_audit(org_id=org_id, user={"email": "system"}, action="DISCOVERY_FAILED",
                        entity_type="discovery_run", entity_id=run_id, status="ERROR")


async def worker_loop():
    logger.info("Discovery worker avviato")
    while True:
        try:
            pending = await db.discovery_runs.find(
                {"status": "IN_CODA"}, {"_id": 0}).sort("created_at", 1).to_list(10)
            for run in pending:
                await process_run(run)
        except Exception:
            logger.exception("Errore nel discovery worker loop")
        await asyncio.sleep(1)


async def recover_on_startup():
    res = await db.discovery_runs.update_many(
        {"status": "IN_ESECUZIONE"},
        {"$set": {"status": "IN_CODA", "updated_at": now_iso()}},
    )
    if res.modified_count:
        logger.info("Discovery recovery: %s ricerche riportate in coda", res.modified_count)


def start_worker():
    global _worker_task
    if _worker_task is None:
        _worker_task = asyncio.create_task(worker_loop())
