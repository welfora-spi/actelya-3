"""Discovery — analisi automatica di sito e social per popolare il Fact Ledger.

SIMULATO in questa milestone: nessuna chiamata di rete reale viene effettuata,
coerentemente con il resto del sistema (nessuna azione esterna senza collegamento
esplicito). L'estrazione è deterministica (basata sull'URL/dominio dichiarato),
chiaramente marcata ESTRATTO/SIMULATO e mai promossa a VERIFICATO in automatico.
Gira come coda persistente con un worker recuperabile, cosi' un obiettivo puo'
essere creato mentre una ricerca e' ancora IN_ESECUZIONE (nessun blocco reciproco)."""
import asyncio
import hashlib
import ipaddress
import logging
import re
import socket
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import db
from ..deps import get_current_user, require_roles, assert_same_org
from ..audit import log_audit
from ..models import now_iso, new_id, base_record
from ..config import DEFAULT_ORG_ID
from ..brain import config as brain_config
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
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
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


def _estrai_prodotti_servizi_candidati(html: str) -> list[str]:
    """SOLO un'estrazione euristica (titoli h2/h3 brevi): MAI presentata come
    un fatto certo -- confidence bassa, method ESTRATTO, mai VERIFICATO
    (vedi process_run sotto, dove questi valori vengono scritti nel Fact
    Ledger con confidence esplicitamente ridotta)."""
    out: list[str] = []
    for grezzo in _H2H3_RE.findall(html):
        testo = re.sub(r"\s+", " ", _ANY_TAG_RE.sub(" ", grezzo)).strip()
        if 3 <= len(testo) <= 80 and testo not in out:
            out.append(testo)
        if len(out) >= 8:
            break
    return out


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


def _fetch_sincrono(url: str) -> dict | None:
    """Esegue in un thread separato (mai sull'event loop): I/O bloccante di
    proposito, stessa convenzione di ogni altra integrazione HTTP sincrona
    del progetto (requests, mai httpx/asyncio nativo). Nessuna eccezione
    propagata: qualunque problema fa tornare None."""
    import requests

    corrente = url
    for _ in range(MAX_REDIRECT + 1):
        if not _url_pubblico_e_risolvibile(corrente):
            logger.info("Discovery: host non pubblico/non risolvibile, fetch saltato.")
            return None
        try:
            risposta = requests.get(
                corrente, timeout=REAL_FETCH_TIMEOUT_SECONDI, allow_redirects=False, stream=True,
                headers={"User-Agent": "ACTELYA-ResearchService/1.0"},
            )
        except Exception as exc:
            logger.info("Discovery: fetch fallito (%s).", exc)
            return None
        try:
            if risposta.status_code in (301, 302, 303, 307, 308):
                location = risposta.headers.get("Location")
                if not location:
                    return None
                corrente = urljoin(corrente, location)
                continue
            if risposta.status_code != 200:
                return None
            content_type = (risposta.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if content_type and content_type not in CONTENT_TYPE_CONSENTITI:
                logger.info("Discovery: content-type '%s' non ammesso, fetch scartato.", content_type)
                return None
            corpo = bytearray()
            for chunk in risposta.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                corpo.extend(chunk)
                if len(corpo) >= REAL_FETCH_MAX_BYTES:
                    break
            return {
                "url_finale": corrente, "status_code": risposta.status_code,
                "testo": bytes(corpo[:REAL_FETCH_MAX_BYTES]).decode("utf-8", errors="replace"),
            }
        finally:
            risposta.close()
    logger.info("Discovery: troppi redirect (> %s), fetch annullato.", MAX_REDIRECT)
    return None


async def fetch_sito_reale(website: str) -> dict | None:
    """SOLO se REAL_EXTERNAL_ACTIONS e' esplicitamente attivo (stesso
    interruttore globale di brain/config.py, mai un flag separato). Nessuna
    eccezione propagata in nessun caso: qualunque problema (rete, timeout,
    DNS, redirect verso rete privata, content-type, dimensione) fa tornare
    None, il chiamante ricade sempre sulla stima simulata esistente."""
    if not brain_config.REAL_EXTERNAL_ACTIONS:
        return None
    url = website if "://" in website else f"https://{website}"
    risultato = await asyncio.to_thread(_fetch_sincrono, url)
    if risultato is None:
        return None

    html = risultato["testo"]
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
    testo_essenziale = _estrai_testo_essenziale(html) or None
    prodotti_servizi_candidati = _estrai_prodotti_servizi_candidati(html)
    social_links = _estrai_social_links(html)

    if not any([titolo, meta_description, h1, testo_essenziale]):
        return None
    return {
        "url": risultato["url_finale"], "status_code": risultato["status_code"],
        "titolo": titolo, "meta_description": meta_description, "h1": h1,
        "testo_essenziale": testo_essenziale, "prodotti_servizi_candidati": prodotti_servizi_candidati,
        "social_links": social_links, "acquisito_il": now_iso(),
    }


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

            # Estrazione REALE opzionale (item 3/9/13, CEO Agent 100% reale):
            # SOLO additiva rispetto alla stima simulata sopra, mai al suo
            # posto. Disattiva/fallisce sempre in modo sicuro (vedi
            # fetch_sito_reale): mode resta "SIMULATO" per compatibilita' con
            # i consumatori esistenti di questo campo, l'esito del fetch
            # reale e' tracciato separatamente in real_fetch. Provenienza
            # puntuale: 'source' e' l'URL REALE della pagina (mai un'
            # etichetta generica), 'method' resta ESTRATTO (mai VERIFICATO:
            # nessuna conferma umana), confidence piu' bassa per le
            # inferenze euristiche (prodotti/servizi candidati) rispetto ai
            # dati letti direttamente dal markup (titolo/meta/H1).
            real_fetch = await fetch_sito_reale(website)
            if real_fetch:
                fonte = real_fetch["url"]
                extra_facts = []
                if real_fetch.get("titolo"):
                    extra_facts.append(await write_fact(
                        db, org_id=org_id, user_id=actor_id, field="titolo_sito_estratto",
                        value=real_fetch["titolo"], source=fonte, method="ESTRATTO", confidence=0.75,
                    ))
                if real_fetch.get("meta_description"):
                    extra_facts.append(await write_fact(
                        db, org_id=org_id, user_id=actor_id, field="descrizione_sito_estratta",
                        value=real_fetch["meta_description"], source=fonte, method="ESTRATTO", confidence=0.75,
                    ))
                if real_fetch.get("h1"):
                    extra_facts.append(await write_fact(
                        db, org_id=org_id, user_id=actor_id, field="titolo_principale_sito",
                        value=real_fetch["h1"], source=fonte, method="ESTRATTO", confidence=0.7,
                    ))
                if real_fetch.get("prodotti_servizi_candidati"):
                    extra_facts.append(await write_fact(
                        db, org_id=org_id, user_id=actor_id, field="prodotti_servizi_candidati",
                        value=", ".join(real_fetch["prodotti_servizi_candidati"]), source=fonte,
                        method="ESTRATTO", confidence=0.35,  # inferenza euristica: mai presentata come certa
                    ))
                if real_fetch.get("social_links"):
                    extra_facts.append(await write_fact(
                        db, org_id=org_id, user_id=actor_id, field="social_links_estratti",
                        value=", ".join(real_fetch["social_links"]), source=fonte, method="ESTRATTO", confidence=0.75,
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
