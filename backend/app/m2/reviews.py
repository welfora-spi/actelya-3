"""Milestone 2 — Blocco 6: revisori NON distruttivi (SIMULAZIONE).
Compliance e Auditor producono record di revisione persistiti (collezione `reviews`)
collegati a plan/task/deliverable/agente/organizzazione. NON modificano né sostituiscono
i deliverable. Deterministici, nessuna chiamata reale."""
import json
from pymongo.errors import DuplicateKeyError

from ..models import new_id, now_iso
from .models import new_review
from .agents_registry import assert_action_allowed
from .deliverables import PII_EMAIL_RE, PII_PHONE_RE, PLACEHOLDER_RE

_SEV_ORDER = {"info": 0, "warning": 1, "high": 2}


def _max_sev(findings):
    if not findings:
        return "info"
    return max(findings, key=lambda f: _SEV_ORDER.get(f.get("severity", "info"), 0))["severity"]


async def _audit(db, *, org_id, actor, action, entity_id, details=None):
    await db.audit_logs.insert_one({
        "id": new_id("audit"), "organization_id": org_id, "actor": actor, "action": action,
        "entity_type": "review", "entity_id": entity_id, "details": details or {},
        "status": "OK", "reason": "", "at": now_iso(),
    })


# ---------------- Revisione Compliance (non distruttiva) ----------------
def run_compliance(deliverable, task):
    findings = []
    content = deliverable.get("content", {}) or {}
    dtype = deliverable.get("deliverable_type")
    text = json.dumps(content, ensure_ascii=False)

    if PII_EMAIL_RE.search(text) or PII_PHONE_RE.search(text):
        findings.append({"code": "PII", "severity": "high",
                         "message": "Rilevata possibile PII/contatto reale: vietato in SIMULAZIONE."})
    if dtype in ("lead_gen_plan", "email"):
        findings.append({"code": "GDPR", "severity": "warning",
                         "message": "Verificare consenso/base giuridica prima di qualsiasi invio reale."})
    if dtype == "ad_campaign_draft" and content.get("status") != "DRAFT":
        findings.append({"code": "CAMPAIGN_STATUS", "severity": "high",
                         "message": "La campagna deve restare in stato DRAFT (mai pubblicata)."})
    if PLACEHOLDER_RE.search(text):
        findings.append({"code": "PLACEHOLDER", "severity": "info",
                         "message": "Presenti placeholder da personalizzare prima dell'uso."})
    if deliverable.get("status") == "BLOCCATO":
        findings.append({"code": "NON_CONFORME", "severity": "high",
                         "message": "Deliverable bloccato dal validatore: non conforme."})
    if not findings:
        findings.append({"code": "OK", "severity": "info", "message": "Nessun rilievo di conformità."})
    return findings, _max_sev(findings)


# ---------------- Revisione Audit indipendente (non distruttiva) ----------------
def run_audit(deliverable, task):
    findings = []
    expected_valid = deliverable.get("status") in ("COMPLETATO", "COMPLETATO_CON_AVVISI")
    if deliverable.get("valid") != expected_valid:
        findings.append({"code": "VALID_MISMATCH", "severity": "high",
                         "message": "Flag 'valid' incoerente con lo stato del deliverable."})
    for k in ("plan_id", "task_id", "agent_id", "organization_id", "version"):
        v = deliverable.get(k)
        if v in (None, ""):
            findings.append({"code": "MISSING_LINK", "severity": "high",
                             "message": f"Collegamento mancante: {k}."})
    if deliverable.get("mode") != "SIMULAZIONE":
        findings.append({"code": "MODE", "severity": "high",
                         "message": "Deliverable non in modalità SIMULAZIONE."})
    text = json.dumps(deliverable.get("content", {}), ensure_ascii=False).lower()
    if any(s in text for s in ("api_key", "password", "access_token", "secret")):
        findings.append({"code": "SECRET", "severity": "high",
                         "message": "Possibile segreto nel contenuto del deliverable."})
    findings.append({"code": "TRACE", "severity": "info",
                     "message": f"Tracciabilità: costo registrato={task.get('cost', 0)}, tentativo={task.get('attempt', 0)}."})
    return findings, _max_sev(findings)


REVIEWERS = [
    ("compliance_reviewer", "compliance", run_compliance),
    ("auditor", "audit", run_audit),
]


# ---------------- Persistenza idempotente (una revisione per tipo/deliverable) ----------------
async def create_review(db, *, org_id, reviewer_agent, plan_id, task_id, deliverable_id,
                        review_type, findings, severity, actor="system"):
    existing = await db.reviews.find_one(
        {"deliverable_id": deliverable_id, "review_type": review_type}, {"_id": 0})
    if existing:
        return existing
    rec = new_review(org_id, reviewer_agent, plan_id, task_id, deliverable_id, review_type, findings, severity)
    try:
        await db.reviews.insert_one(rec)
    except DuplicateKeyError:
        return await db.reviews.find_one(
            {"deliverable_id": deliverable_id, "review_type": review_type}, {"_id": 0})
    await _audit(db, org_id=org_id, actor=actor, action="CREATE_REVIEW", entity_id=rec["id"],
                 details={"review_type": review_type, "severity": severity,
                          "deliverable_id": deliverable_id, "reviewer_agent": reviewer_agent})
    rec.pop("_id", None)
    return rec


async def review_deliverable(db, deliverable, task, actor="system"):
    """Esegue Compliance + Auditor e persiste le revisioni. NON tocca il deliverable."""
    results = []
    for agent_id, rtype, fn in REVIEWERS:
        assert_action_allowed(agent_id, "revisione")  # blocco sicuro: reviewer non modifica/cancella
        findings, severity = fn(deliverable, task)
        rec = await create_review(
            db, org_id=deliverable["organization_id"], reviewer_agent=agent_id,
            plan_id=deliverable["plan_id"], task_id=deliverable["task_id"],
            deliverable_id=deliverable["id"], review_type=rtype,
            findings=findings, severity=severity, actor=actor)
        results.append(rec)
    return results
