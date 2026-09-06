"""Analyst/KPI — endpoint HTTP. Sola lettura tranne la generazione di un
nuovo report (nessuna scrittura su altri domini: l'Analyst legge, non
modifica mai lead/opportunità/prenotazioni)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...audit import log_audit
from ...config import DEFAULT_ORG_ID
from ...db import db
from ...deps import assert_same_org, get_current_user, require_roles
from . import pipeline
from .models import GenerateReportBody

router = APIRouter(prefix="/analyst", tags=["analyst"])


@router.post("/reports")
async def generate_report(body: GenerateReportBody, user: dict = Depends(require_roles("ADMIN", "OPERATORE"))):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    report = await pipeline.compute_report(
        db, org_id=org_id, time_range_days=body.time_range_days, actor=user["id"])
    await log_audit(org_id=org_id, user=user, action="ANALYST_REPORT_GENERATED",
                    entity_type="analyst_report", entity_id=report["id"],
                    details={"time_range_days": body.time_range_days, "insight_count": len(report["insights"])})
    return report


@router.get("/reports")
async def list_reports(user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    return await pipeline.list_reports(db, org_id=org_id)


@router.get("/reports/{report_id}")
async def get_report(report_id: str, user: dict = Depends(get_current_user)):
    report = await db.analyst_reports.find_one({"id": report_id})
    assert_same_org(report, user, "Report non trovato")
    return {k: v for k, v in report.items() if k != "_id"}


@router.get("/insights/{agent_id}")
async def insights_for_agent(agent_id: str, user: dict = Depends(get_current_user)):
    org_id = user.get("organization_id") or DEFAULT_ORG_ID
    return await pipeline.insights_for_agent(db, org_id=org_id, agent_id=agent_id)
