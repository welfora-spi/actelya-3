"""Milestone 2 — Blocco 5: sei deliverable versionati e validati (SIMULAZIONE).
Produttori DETERMINISTICI (nessuna chiamata AI) + validatori SEPARATI per tipo.
Regole comuni: rifiuto di vuoti/UNKNOWN/TODO/N/A/rifiuti/contenuti non producibili;
placeholder ammessi SOLO nei campi variabili; campagna sempre DRAFT; lead gen senza PII;
KPI con dati SIMULATO o NON_DISPONIBILE dichiarati. Versionamento atomico senza sovrascrittura."""
import re
from pymongo.errors import DuplicateKeyError

from ..models import new_id, now_iso
from ..domains.validators import validate_email_deliverable

# ---------------- Pattern e valori vietati ----------------
PLACEHOLDER_RE = re.compile(r"\[[^\]]+\]")
PII_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PII_PHONE_RE = re.compile(r"(?:(?:\+|00)\d{1,3}[\s.\-]?)?(?:\d[\s.\-]?){8,}\d")
REFUSAL_RE = re.compile(
    r"non posso|non sono in grado|mi dispiace|non è possibile|non e' possibile|"
    r"as an ai|i can'?t|i cannot|i'm sorry|cannot comply|non produc|contenuto non disponibile",
    re.IGNORECASE,
)
FORBIDDEN_VALUES = {"", "unknown", "todo", "n/a", "na", "none", "null", "tbd", "-", "?", "xxx", "..."}


def _is_forbidden(v: str) -> bool:
    s = v.strip().lower()
    return s in FORBIDDEN_VALUES or bool(REFUSAL_RE.search(v))


def _placeholder_ratio(text: str) -> float:
    if not text:
        return 1.0
    stripped = PLACEHOLDER_RE.sub("", text)
    non_ph = len(re.sub(r"\s", "", stripped))
    total = len(re.sub(r"\s", "", text)) or 1
    return 1.0 - (non_ph / total)


def _check_text(label, value, min_len, *, variable=False):
    """Valida un campo testuale sostanziale. Ritorna (errors, warnings)."""
    errs, warns = [], []
    if not isinstance(value, str) or not value.strip():
        return [f"{label}: mancante o vuoto"], warns
    v = value.strip()
    if _is_forbidden(v):
        return [f"{label}: valore non producibile o segnaposto non ammesso"], warns
    ph = PLACEHOLDER_RE.findall(v)
    if ph and not variable:
        errs.append(f"{label}: placeholder non ammesso in un campo non variabile")
    if _placeholder_ratio(v) > 0.5:
        errs.append(f"{label}: composto prevalentemente da placeholder")
    elif ph and variable:
        warns.append(f"{label}: placeholder da personalizzare prima dell'uso")
    if len(re.sub(r"\s", "", v)) < min_len:
        errs.append(f"{label}: contenuto non sufficientemente sostanziale")
    return errs, warns


def _no_pii(label, text, errs):
    if PII_EMAIL_RE.search(text or "") or PII_PHONE_RE.search(text or ""):
        errs.append(f"{label}: rilevata possibile PII/contatto reale (vietato)")


def _finalize(errors, warnings):
    if errors:
        return {"status": "BLOCCATO", "warnings": warnings, "errors": errors}
    if warnings:
        return {"status": "COMPLETATO_CON_AVVISI", "warnings": warnings, "errors": []}
    return {"status": "COMPLETATO", "warnings": [], "errors": []}


# ==================== VALIDATORI (uno per tipo) ====================
def validate_marketing_strategy(c):
    errs, warns = [], []
    for lbl, key, ml in (("Titolo", "title", 8), ("Executive summary", "executive_summary", 100),
                         ("Value proposition", "value_proposition", 25), ("Posizionamento", "positioning", 20)):
        e, w = _check_text(lbl, c.get(key), ml); errs += e; warns += w
    segs = c.get("target_segments") or []
    if len(segs) < 2:
        errs.append("target_segments: almeno 2 segmenti richiesti")
    for i, s in enumerate(segs, 1):
        e, w = _check_text(f"Segmento {i} nome", (s or {}).get("name"), 3); errs += e; warns += w
        e, w = _check_text(f"Segmento {i} descrizione", (s or {}).get("description"), 15); errs += e; warns += w
    for lbl, key, mn in (("channels", "channels", 2), ("objectives", "objectives", 2)):
        lst = c.get(key) or []
        if len([x for x in lst if isinstance(x, str) and x.strip() and not _is_forbidden(x)]) < mn:
            errs.append(f"{lbl}: almeno {mn} elementi sostanziali richiesti")
    return _finalize(errs, warns)


def validate_editorial_plan(c):
    errs, warns = [], []
    for lbl, key, ml in (("Titolo", "title", 8), ("Cadenza", "cadence", 6), ("Tone of voice", "tone_of_voice", 10)):
        e, w = _check_text(lbl, c.get(key), ml); errs += e; warns += w
    if len([p for p in (c.get("pillars") or []) if isinstance(p, str) and p.strip() and not _is_forbidden(p)]) < 2:
        errs.append("pillars: almeno 2 pilastri di contenuto richiesti")
    cal = c.get("calendar") or []
    if len(cal) < 3:
        errs.append("calendar: almeno 3 voci di calendario richieste")
    for i, item in enumerate(cal, 1):
        for k, ml in (("topic", 6), ("format", 3), ("channel", 3)):
            e, w = _check_text(f"Calendario {i} {k}", (item or {}).get(k), ml); errs += e; warns += w
    return _finalize(errs, warns)


def validate_social_content(c):
    errs, warns = [], []
    e, w = _check_text("Piattaforma", c.get("platform"), 3); errs += e; warns += w
    posts = c.get("posts") or []
    if len(posts) < 2:
        errs.append("posts: almeno 2 post richiesti")
    for i, p in enumerate(posts, 1):
        e, w = _check_text(f"Post {i} hook", (p or {}).get("hook"), 6); errs += e; warns += w
        e, w = _check_text(f"Post {i} body", (p or {}).get("body"), 20, variable=True); errs += e; warns += w
        e, w = _check_text(f"Post {i} cta", (p or {}).get("cta"), 4, variable=True); errs += e; warns += w
        tags = (p or {}).get("hashtags") or []
        if len([t for t in tags if isinstance(t, str) and t.strip()]) < 1:
            errs.append(f"Post {i}: almeno 1 hashtag richiesto")
    return _finalize(errs, warns)


def validate_ad_campaign_draft(c):
    errs, warns = [], []
    if c.get("status") != "DRAFT":
        errs.append("Campagna: status deve essere DRAFT (mai pubblicata)")
    if c.get("published") not in (False, None):
        errs.append("Campagna: 'published' deve essere False (nessuna pubblicazione reale)")
    e, w = _check_text("Obiettivo", c.get("objective"), 8); errs += e; warns += w
    e, w = _check_text("Audience", (c.get("audience") or {}).get("description"), 15); errs += e; warns += w
    _no_pii("Audience", (c.get("audience") or {}).get("description", ""), errs)
    e, w = _check_text("Budget simulato", str(c.get("budget_simulato") or ""), 3); errs += e; warns += w
    variants = c.get("ad_variants") or []
    if len(variants) < 2:
        errs.append("ad_variants: almeno 2 varianti richieste")
    for i, v in enumerate(variants, 1):
        e, w = _check_text(f"Variante {i} headline", (v or {}).get("headline"), 6); errs += e; warns += w
        e, w = _check_text(f"Variante {i} primary_text", (v or {}).get("primary_text"), 15, variable=True); errs += e; warns += w
        e, w = _check_text(f"Variante {i} cta", (v or {}).get("cta"), 4, variable=True); errs += e; warns += w
        _no_pii(f"Variante {i}", (v or {}).get("primary_text", ""), errs)
    return _finalize(errs, warns)


def validate_lead_gen_plan(c):
    errs, warns = [], []
    e, w = _check_text("Titolo", c.get("title"), 8); errs += e; warns += w
    e, w = _check_text("ICP", c.get("icp"), 20); errs += e; warns += w
    crit = [x for x in (c.get("criteria") or []) if isinstance(x, str) and x.strip() and not _is_forbidden(x)]
    if len(crit) < 3:
        errs.append("criteria: almeno 3 criteri di targeting richiesti")
    if len([x for x in (c.get("channels") or []) if isinstance(x, str) and x.strip()]) < 2:
        errs.append("channels: almeno 2 canali richiesti")
    seq = c.get("outreach_sequence") or []
    if len(seq) < 2:
        errs.append("outreach_sequence: almeno 2 step richiesti")
    for i, s in enumerate(seq, 1):
        e, w = _check_text(f"Step {i} template", (s or {}).get("message_template"), 25, variable=True); errs += e; warns += w
        _no_pii(f"Step {i}", (s or {}).get("message_template", ""), errs)
    # Nessuna PII/contatto reale in tutto il piano
    blob = " ".join(str(x) for x in [c.get("icp", "")] + (c.get("criteria") or []))
    _no_pii("Lead gen", blob, errs)
    return _finalize(errs, warns)


def validate_kpi_report(c):
    errs, warns = [], []
    e, w = _check_text("Titolo", c.get("title"), 8); errs += e; warns += w
    e, w = _check_text("Periodo", c.get("period"), 4); errs += e; warns += w
    kpis = c.get("kpis") or []
    if len(kpis) < 3:
        errs.append("kpis: almeno 3 indicatori richiesti")
    for i, k in enumerate(kpis, 1):
        e, w = _check_text(f"KPI {i} nome", (k or {}).get("name"), 3); errs += e; warns += w
        if "target" not in (k or {}) or (k or {}).get("target") in (None, ""):
            errs.append(f"KPI {i}: target mancante")
        src = (k or {}).get("source")
        if src not in ("SIMULATO", "NON_DISPONIBILE"):
            errs.append(f"KPI {i}: source deve essere SIMULATO o NON_DISPONIBILE (nessun dato inventato come reale)")
            continue
        cur = (k or {}).get("current")
        if src == "NON_DISPONIBILE":
            if cur not in (None, "NON_DISPONIBILE"):
                errs.append(f"KPI {i}: current deve essere NON_DISPONIBILE quando la fonte non è disponibile")
            else:
                warns.append(f"KPI {i}: valore corrente non disponibile (dichiarato)")
        else:  # SIMULATO
            if cur in (None, "", "NON_DISPONIBILE"):
                errs.append(f"KPI {i}: current simulato mancante")
    return _finalize(errs, warns)


def validate_video_reel_project(c):
    """Placeholder strutturale per il task M2 'video_reel_project' (Blocco
    brain/service.py -> capability REALE 'video_reel'): il contenuto vero
    (sceneggiatura, storyboard, video) vive in domains/reel.py, MAI
    generato da M2 (che resta dichiaratamente solo-simulazione, vedi
    m2/engine.py::_assert_simulation). Questo validatore accetta SOLO il
    riferimento gia' creato da reel.create_project: nessun contenuto reale
    viene mai validato o prodotto qui."""
    if not isinstance(c, dict) or not c.get("reel_project_id"):
        return {"status": "BLOCCATO", "warnings": [], "errors": ["reel_project_id mancante: nessun progetto reel collegato"]}
    return {
        "status": "COMPLETATO_CON_AVVISI",
        "warnings": ["Contenuto reale (testo Requesty + video Runway) gestito nel laboratorio Reel, "
                     "non generato da M2: apri il progetto per generarlo e approvarlo."],
        "errors": [],
    }


def validate_flyer_project(c):
    """Stesso pattern di validate_video_reel_project: placeholder strutturale
    per il task M2 'flyer_project' (capability REALE 'flyer_image'). Il
    contenuto vero (copy, prompt immagine, immagine) vive in domains/flyer.py."""
    if not isinstance(c, dict) or not c.get("flyer_project_id"):
        return {"status": "BLOCCATO", "warnings": [], "errors": ["flyer_project_id mancante: nessun progetto flyer collegato"]}
    return {
        "status": "COMPLETATO_CON_AVVISI",
        "warnings": ["Contenuto reale (copy + immagine Requesty) gestito nel laboratorio Flyer, "
                     "non generato da M2: apri il progetto per generarlo e approvarlo."],
        "errors": [],
    }


def _validato_con_riferimento(c, chiave_id: str, laboratorio: str, nota_contenuto: str) -> dict:
    """Stesso pattern di validate_video_reel_project/validate_flyer_project:
    placeholder strutturale per un task REALE il cui contenuto vero vive in
    un laboratorio dedicato, MAI generato o validato da M2 — richiede solo
    che il riferimento (id) già creato dal laboratorio sia presente."""
    if not isinstance(c, dict) or not c.get(chiave_id):
        return {"status": "BLOCCATO", "warnings": [], "errors": [f"{chiave_id} mancante: nessun {laboratorio} collegato"]}
    return {
        "status": "COMPLETATO_CON_AVVISI",
        "warnings": [f"{nota_contenuto} gestito nel laboratorio {laboratorio}, non generato da M2: "
                    f"apri il laboratorio per proseguire e approvare."],
        "errors": [],
    }


def _validato_senza_riferimento(c, laboratorio: str, nota_contenuto: str) -> dict:
    """Stesso principio di _validato_con_riferimento, per un task REALE che
    NON crea automaticamente un'entità (richiede una scelta specifica
    dell'utente nel laboratorio, es. un lead o un'opportunità già scelti):
    nessun id da verificare, solo che il task sia davvero in modalità REALE."""
    if not isinstance(c, dict) or c.get("mode") != "REALE":
        return {"status": "BLOCCATO", "warnings": [], "errors": ["Task non in modalità REALE: nessun contenuto da collegare"]}
    return {
        "status": "COMPLETATO_CON_AVVISI",
        "warnings": [f"{nota_contenuto} gestito nel laboratorio {laboratorio}, non generato da M2: "
                    f"apri il laboratorio per scegliere l'elemento specifico e proseguire."],
        "errors": [],
    }


def validate_lead_gen_campaign(c):
    return _validato_con_riferimento(c, "lead_campaign_id", "Lead Generation",
                                     "Import, qualifica e approvazione dei prospect reali")


def validate_content_item(c):
    if not isinstance(c, dict) or not c.get("content_item_ids"):
        return {"status": "BLOCCATO", "warnings": [], "errors": ["content_item_ids mancante: nessun contenuto collegato"]}
    return {
        "status": "COMPLETATO_CON_AVVISI",
        "warnings": ["Generazione e approvazione del contenuto reale gestite nel laboratorio Content Creator, "
                    "non generate da M2: apri il laboratorio per proseguire."],
        "errors": [],
    }


def validate_appointment_setter_task(c):
    return _validato_senza_riferimento(c, "Appointment Setter",
                                       "Proposta slot, approvazione e prenotazione reale")


def validate_sales_opportunity(c):
    return _validato_senza_riferimento(c, "Sales", "Strategia, messaggio e gestione della pipeline commerciale")


def validate_analyst_report(c):
    """A differenza degli altri task REALI, qui il contenuto è già
    interamente calcolato al momento della creazione del piano (KPI reali +
    insight, vedi domains/analyst/pipeline.py::compute_report): nessun
    ulteriore passaggio di generazione manca nel laboratorio."""
    if not isinstance(c, dict) or not c.get("analyst_report_id"):
        return {"status": "BLOCCATO", "warnings": [], "errors": ["analyst_report_id mancante: nessun report collegato"]}
    return {
        "status": "COMPLETATO_CON_AVVISI",
        "warnings": ["Report KPI reale già calcolato (Lead Generation/Sales/Appointment Setter/Tool Execution "
                    "Gateway): apri il laboratorio Analyst per consultare KPI e insight."],
        "errors": [],
    }


VALIDATORS = {
    "marketing_strategy": validate_marketing_strategy,
    "editorial_plan": validate_editorial_plan,
    "social_content": validate_social_content,
    "ad_campaign_draft": validate_ad_campaign_draft,
    "lead_gen_plan": validate_lead_gen_plan,
    "kpi_report": validate_kpi_report,
    "email": validate_email_deliverable,   # compatibilità Milestone 1
    "video_reel_project": validate_video_reel_project,
    "flyer_project": validate_flyer_project,
    "lead_gen_campaign": validate_lead_gen_campaign,
    "content_item": validate_content_item,
    "appointment_setter_task": validate_appointment_setter_task,
    "sales_opportunity": validate_sales_opportunity,
    "analyst_report": validate_analyst_report,
}


def validate_deliverable(deliverable_type: str, content: dict) -> dict:
    fn = VALIDATORS.get(deliverable_type)
    if not fn:
        return {"status": "BLOCCATO", "warnings": [], "errors": [f"Tipo deliverable sconosciuto: {deliverable_type}"]}
    return fn(content or {})


# ==================== PRODUTTORI (simulati, deterministici) ====================
def _brand(org_profile):
    return (org_profile or {}).get("nome_commerciale") or (org_profile or {}).get("ragione_sociale") or "l'azienda"


def produce_marketing_strategy(task, plan, org):
    b = _brand(org)
    return {
        "title": f"Strategia di marketing — {b}",
        "executive_summary": (f"Strategia simulata per {b}: rafforzare il posizionamento nel mercato B2B, "
                              "aumentare la generazione di domanda e migliorare il tasso di conversione dei lead "
                              "attraverso contenuti di valore e canali mirati nel prossimo trimestre."),
        "value_proposition": f"{b} aiuta i team marketing e vendite a ottenere risultati misurabili con un percorso guidato.",
        "positioning": "Soluzione affidabile e trasparente, orientata al valore concreto e alla conformità.",
        "target_segments": [
            {"name": "PMI B2B", "description": "Aziende 10-200 dipendenti che vogliono strutturare marketing e vendite."},
            {"name": "Startup in crescita", "description": "Team snelli che necessitano di processi ripetibili e misurabili."},
        ],
        "channels": ["LinkedIn", "Email marketing", "SEO/Contenuti", "Eventi di settore"],
        "objectives": ["Aumentare la notorietà del brand del 20% (simulato)",
                       "Generare 50 lead qualificati al mese (simulato)"],
        "mode": "SIMULAZIONE",
    }


def produce_editorial_plan(task, plan, org):
    return {
        "title": f"Piano editoriale — {_brand(org)}",
        "cadence": "3 contenuti a settimana",
        "tone_of_voice": "Professionale, chiaro e orientato al valore, con esempi concreti.",
        "pillars": ["Educazione del mercato", "Case study e risultati", "Novità di prodotto"],
        "calendar": [
            {"slot": "Settimana 1 - Lun", "topic": "Come strutturare la generazione di domanda", "format": "articolo", "channel": "Blog"},
            {"slot": "Settimana 1 - Mer", "topic": "Case study simulato di un cliente B2B", "format": "post", "channel": "LinkedIn"},
            {"slot": "Settimana 1 - Ven", "topic": "Checklist per il primo trimestre", "format": "carosello", "channel": "LinkedIn"},
        ],
        "mode": "SIMULAZIONE",
    }


def produce_social_content(task, plan, org):
    return {
        "platform": "LinkedIn",
        "posts": [
            {"hook": "Il 70% dei team marketing spreca budget: ecco come evitarlo.",
             "body": "Ciao [Nome], in questo post condividiamo 3 leve per allineare marketing e vendite e migliorare i risultati.",
             "cta": "Scopri di più nei commenti", "hashtags": ["#marketing", "#b2b", "#growth"]},
            {"hook": "Un piano editoriale non è un calendario: è una strategia.",
             "body": "Ecco come costruiamo contenuti che generano domanda reale, passo dopo passo, per [Azienda].",
             "cta": "Salva questo post", "hashtags": ["#contentmarketing", "#leadgen"]},
        ],
        "mode": "SIMULAZIONE",
    }


def produce_ad_campaign_draft(task, plan, org):
    return {
        "status": "DRAFT",
        "published": False,
        "objective": "Generazione di lead qualificati (simulato, solo bozza)",
        "audience": {"description": "Professionisti marketing e vendite, 25-45 anni, interessi B2B SaaS in Italia.",
                     "note": "Nessuna PII: solo criteri aggregati e simulati."},
        "budget_simulato": "€500 totali (SIMULATO, nessuna spesa reale)",
        "ad_variants": [
            {"headline": "Struttura il tuo motore di crescita B2B",
             "primary_text": "Scopri come [Azienda] può generare domanda qualificata con un percorso guidato e misurabile.",
             "cta": "Registrati"},
            {"headline": "Marketing e vendite finalmente allineati",
             "primary_text": "Un metodo chiaro e trasparente per ottenere risultati concreti nel prossimo trimestre.",
             "cta": "Scopri di più"},
        ],
        "mode": "SIMULAZIONE",
    }


def produce_lead_gen_plan(task, plan, org):
    return {
        "title": f"Piano di lead generation — {_brand(org)}",
        "icp": "Aziende B2B SaaS con 10-200 dipendenti in Italia, con team marketing strutturato (profilo, non contatti reali).",
        "criteria": ["Settore: software/servizi B2B", "Dimensione: 10-200 dipendenti",
                     "Area geografica: Italia", "Ruolo target: Head of Marketing / Sales Director"],
        "channels": ["LinkedIn Sales Navigator (ricerca per criteri)", "Eventi e webinar di settore"],
        "outreach_sequence": [
            {"step": 1, "message_template": "Ciao [Nome], ho visto il lavoro di [Azienda] nel settore e volevo condividere un'idea utile per la vostra crescita."},
            {"step": 2, "message_template": "Ciao [Nome], torno con un secondo messaggio: se utile posso inviarti una checklist pensata per team come quello di [Azienda]."},
        ],
        "note": "Solo criteri e template: nessun contatto reale, nessuna PII, nessun invio.",
        "mode": "SIMULAZIONE",
    }


def produce_kpi_report(task, plan, org):
    return {
        "title": f"Report KPI — {_brand(org)}",
        "period": "Q2 2026 (simulato)",
        "kpis": [
            {"name": "Lead qualificati", "target": 50, "current": 32, "source": "SIMULATO", "unit": "lead/mese"},
            {"name": "Tasso di conversione lead→cliente", "target": "5%", "current": "NON_DISPONIBILE", "source": "NON_DISPONIBILE"},
            {"name": "Costo per acquisizione (CAC)", "target": 120, "current": 140, "source": "SIMULATO", "unit": "EUR"},
        ],
        "note": "Valori SIMULATO o NON_DISPONIBILE: nessun dato reale è stato raccolto o inventato.",
        "mode": "SIMULAZIONE",
    }


def produce_email(task, plan, org):
    b = _brand(org)
    return {
        "oggetto": f"Una proposta di valore per {b}",
        "proposta": "Un percorso guidato per allineare marketing e vendite e ottenere risultati misurabili.",
        "contenuto_completo": (f"Ciao [Nome],\n\nti scrivo da {b}. Aiutiamo team come il tuo a strutturare la "
                               "generazione di domanda con un metodo chiaro e trasparente. Vorrei mostrarti un "
                               "esempio concreto pensato per [Azienda].\n\nA presto,\n[Firma]"),
        "cta": "Prenota una call conoscitiva",
        "mode": "SIMULAZIONE",
    }


PRODUCERS = {
    "marketing_strategy": produce_marketing_strategy,
    "editorial_plan": produce_editorial_plan,
    "social_content": produce_social_content,
    "ad_campaign_draft": produce_ad_campaign_draft,
    "lead_gen_plan": produce_lead_gen_plan,
    "kpi_report": produce_kpi_report,
    "email": produce_email,
}


def produce_deliverable(deliverable_type: str, task: dict, plan: dict, org_profile: dict) -> dict:
    fn = PRODUCERS.get(deliverable_type)
    if not fn:
        raise ValueError(f"Nessun produttore per il tipo deliverable '{deliverable_type}'")
    return fn(task, plan, org_profile)


# ==================== VERSIONAMENTO ATOMICO (nessuna sovrascrittura) ====================
async def create_deliverable_version(db, *, org_id, plan, task, content, validation, agent_id, actor="system"):
    """Crea una NUOVA versione del deliverable per (plan_id, task_id) senza sovrascrivere
    le precedenti. Concorrenza-safe grazie all'indice unico (plan_id, task_id, version):
    in caso di collisione ritenta con la versione successiva. Marca is_current in modo
    esclusivo (indice unico partial su is_current per task)."""
    plan_id, task_id = task["plan_id"], task["id"]
    for _ in range(8):
        latest = await db.deliverables.find(
            {"plan_id": plan_id, "task_id": task_id}).sort("version", -1).limit(1).to_list(1)
        version = (latest[0]["version"] + 1) if latest else 1
        doc = {
            "id": new_id("deliv"), "organization_id": org_id,
            "plan_id": plan_id, "task_id": task_id, "plan_version": task["version"],
            "goal_id": task.get("goal_id"), "agent_id": agent_id,
            "deliverable_type": task["deliverable_type"], "artifact_slot": task.get("artifact_slot"),
            "version": version, "is_current": False,
            "status": validation["status"],
            "valid": validation["status"] in ("COMPLETATO", "COMPLETATO_CON_AVVISI"),
            "warnings": validation.get("warnings", []), "errors": validation.get("errors", []),
            "content": content, "created_by": actor, "updated_by": actor,
            "created_at": now_iso(), "updated_at": now_iso(), "change_history": [],
            "mode": "SIMULAZIONE",
        }
        try:
            await db.deliverables.insert_one(doc)
        except DuplicateKeyError:
            continue  # versione già presa da un writer concorrente: ritenta con la successiva
        # Marca questa versione come corrente in modo esclusivo
        await db.deliverables.update_many(
            {"plan_id": plan_id, "task_id": task_id, "id": {"$ne": doc["id"]}},
            {"$set": {"is_current": False}})
        try:
            await db.deliverables.update_one({"id": doc["id"]}, {"$set": {"is_current": True}})
            doc["is_current"] = True
        except DuplicateKeyError:
            pass  # un'altra versione è già corrente (concorrenza): questa resta non corrente
        doc.pop("_id", None)
        return doc
    raise RuntimeError("Versionamento deliverable fallito dopo ripetuti tentativi")
