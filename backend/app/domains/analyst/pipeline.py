"""Analyst/KPI — orchestrazione: aggrega dati REALI già presenti in ACTELYA
(Lead Generation, Sales, Appointment Setter, Tool Execution Gateway — mai un
dato inventato, mai una chiamata a un provider esterno), calcola i KPI
(metrics.py) e genera insight strutturati (insights.py), poi persiste il
report per organizzazione."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ...models import new_id, now_iso
from ..sales.models import PIPELINE_STAGES
from . import metrics
from .insights import generate_insights

_STAGES_OLTRE_CONTATTATO = (
    "IN_RELAZIONE", "FOLLOW_UP", "RICHIESTA_APPUNTAMENTO", "APPUNTAMENTO_FISSATO",
    "OPPORTUNITA", "PROPOSTA", "NEGOZIAZIONE", "VINTO", "PERSO",
)
_STAGES_CONTATTATO_O_OLTRE = ("CONTATTATO",) + _STAGES_OLTRE_CONTATTATO
_STAGES_CON_APPUNTAMENTO = ("APPUNTAMENTO_FISSATO", "OPPORTUNITA", "PROPOSTA", "NEGOZIAZIONE", "VINTO")


async def compute_report(db, *, org_id: str, time_range_days: int, actor: str) -> dict:
    inizio_iso = (datetime.now(timezone.utc) - timedelta(days=time_range_days)).isoformat()
    query_periodo = {"organization_id": org_id, "created_at": {"$gte": inizio_iso}}

    aziende = await db.lead_companies.find(query_periodo, {"_id": 0, "qualification_status": 1}).to_list(100000)
    persone = await db.lead_persons.find(query_periodo, {"_id": 0, "qualification_status": 1}).to_list(100000)
    lead_count = len(aziende) + len(persone)
    qualified_count = sum(1 for l in aziende + persone if l.get("qualification_status") == "QUALIFIED")

    opportunita = await db.sales_opportunities.find(
        query_periodo, {"_id": 0, "stage": 1, "history": 1, "escalation_richiesta": 1},
    ).to_list(100000)
    opportunita_totali = len(opportunita)
    contattati_o_oltre = sum(1 for o in opportunita if o["stage"] in _STAGES_CONTATTATO_O_OLTRE)
    con_risposta = sum(1 for o in opportunita if o["stage"] in _STAGES_OLTRE_CONTATTATO)
    con_appuntamento = sum(1 for o in opportunita if o["stage"] in _STAGES_CON_APPUNTAMENTO)
    vinte = sum(1 for o in opportunita if o["stage"] == "VINTO")
    perse = sum(1 for o in opportunita if o["stage"] == "PERSO")
    escalation_count = sum(1 for o in opportunita if o.get("escalation_richiesta"))

    conteggi_per_stage = {stage: 0 for stage in PIPELINE_STAGES}
    for o in opportunita:
        stage_visitati = {h.get("stage") for h in (o.get("history") or [])}
        for stage in PIPELINE_STAGES:
            if stage in stage_visitati:
                conteggi_per_stage[stage] += 1

    prenotazioni = await db.appointment_bookings.find(
        query_periodo, {"_id": 0, "status": 1},
    ).to_list(100000)
    prenotazioni_confermate = sum(1 for p in prenotazioni if p.get("status") == "CONFERMATA")

    eventi_costo = await db.tool_cost_events.find(
        {"organization_id": org_id, "created_at": {"$gte": inizio_iso}}, {"_id": 0, "amount": 1, "agent_id": 1},
    ).to_list(100000)
    costo_totale = sum(e.get("amount", 0.0) for e in eventi_costo)
    costo_leadgen = sum(e.get("amount", 0.0) for e in eventi_costo if e.get("agent_id") == "lead-gen-specialist")
    costo_appointments = sum(e.get("amount", 0.0) for e in eventi_costo if e.get("agent_id") == "appointment-setter")

    kpis = {
        "conversion_rate": metrics.conversion_rate(
            lead_count=lead_count, qualified_count=qualified_count, time_range_days=time_range_days),
        "lead_velocity": metrics.lead_velocity(lead_count=lead_count, time_range_days=time_range_days),
        "response_rate": metrics.response_rate(
            contattati_o_oltre=contattati_o_oltre, con_risposta=con_risposta, time_range_days=time_range_days),
        "appointment_rate": metrics.appointment_rate(
            opportunita_totali=opportunita_totali, con_appuntamento=con_appuntamento, time_range_days=time_range_days),
        "close_rate": metrics.close_rate(vinte=vinte, perse=perse, time_range_days=time_range_days),
        "funnel_drop_off": metrics.funnel_drop_off(
            conteggi_per_stage=conteggi_per_stage, ordine_stage=PIPELINE_STAGES, time_range_days=time_range_days),
        "cost_per_lead": metrics.cost_per_unit(
            "cost_per_lead", costo_totale=costo_leadgen, unita=lead_count,
            formula="costo tool Lead Generation / lead totali",
            source="tool_cost_events (agent_id=lead-gen-specialist) + lead_companies/lead_persons",
            time_range_days=time_range_days),
        "cost_per_appointment": metrics.cost_per_unit(
            "cost_per_appointment", costo_totale=costo_appointments, unita=prenotazioni_confermate,
            formula="costo tool Appointment Setter / prenotazioni confermate",
            source="tool_cost_events (agent_id=appointment-setter) + appointment_bookings",
            time_range_days=time_range_days),
        "cost_per_acquisition": metrics.cost_per_unit(
            "cost_per_acquisition", costo_totale=costo_totale, unita=vinte,
            formula="costo totale di tutti gli strumenti / opportunità vinte",
            source="tool_cost_events + sales_opportunities", time_range_days=time_range_days),
        # Non calcolabili senza un'integrazione reale non ancora collegata in
        # questa fase (Fase 2 del catalogo strumenti): mai un valore inventato.
        "engagement": metrics.non_disponibile(
            "engagement", note="Nessuna integrazione Meta Insights/GA4 con dati reali collegata per questa organizzazione.",
            time_range_days=time_range_days),
        "roi": metrics.non_disponibile(
            "roi", note="Nessun dato di ricavo/fatturato per opportunità tracciato in questa fase.",
            time_range_days=time_range_days),
        "roas": metrics.non_disponibile(
            "roas", note="Nessuna integrazione advertising (Meta Ads/Google Ads) collegata in questa fase.",
            time_range_days=time_range_days),
    }
    escalation_kpi = metrics.escalation_rate(
        escalation_count=escalation_count, opportunita_totali=opportunita_totali, time_range_days=time_range_days)

    insight_list = generate_insights(kpis=kpis, lead_count=lead_count, escalation_pct=escalation_kpi)

    report = {
        "id": new_id("analystreport"), "organization_id": org_id, "time_range_days": time_range_days,
        "generated_at": now_iso(), "generated_by": actor,
        "kpis": kpis, "escalation_rate": escalation_kpi, "insights": insight_list,
    }
    await db.analyst_reports.insert_one(report)
    report.pop("_id", None)
    return report


async def list_reports(db, *, org_id: str, limit: int = 20) -> list:
    return await db.analyst_reports.find(
        {"organization_id": org_id}, {"_id": 0}).sort("generated_at", -1).to_list(limit)


async def insights_for_agent(db, *, org_id: str, agent_id: str, limit_reports: int = 5) -> list:
    """Estrae (sola lettura) gli insight indirizzati a un agente specifico
    dagli ultimi report — mai una nuova interpretazione qui, solo un filtro."""
    reports = await db.analyst_reports.find(
        {"organization_id": org_id}, {"_id": 0, "id": 1, "generated_at": 1, "insights": 1},
    ).sort("generated_at", -1).to_list(limit_reports)
    risultati = []
    for r in reports:
        for insight in r.get("insights", []):
            if insight.get("target_agent") == agent_id:
                risultati.append({**insight, "report_id": r["id"], "generated_at": r["generated_at"]})
    return risultati
