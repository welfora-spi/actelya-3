"""Analyst/KPI — interpretazione DETERMINISTICA dei KPI già calcolati
(metrics.py): confronta, individua anomalie/pattern noti, spiega la causa
probabile e propone un'azione, indirizzata a un agente specifico. Nessuna
chiamata AI: ogni regola è esplicita e testabile; quando i dati sono
insufficienti per una regola, quella regola semplicemente non produce un
insight — mai una conclusione inventata per riempire il report."""
from __future__ import annotations

# Soglie deliberatamente prudenti: un insight sbagliato costa più di un
# insight mancante (silenzio onesto preferibile a un'interpretazione forzata
# su un campione troppo piccolo).
_LEAD_SUFFICIENTI_MIN = 5
_CONVERSIONE_BASSA_MAX = 20.0
_ESCALATION_ALTA_MIN = 30.0
_DROP_OFF_ALTO_MIN = 60.0


def _valore_valido(kpi: dict) -> bool:
    return bool(kpi) and not kpi.get("missing_data") and kpi.get("value") is not None


def generate_insights(*, kpis: dict, lead_count: int, escalation_pct: dict | None = None) -> list[dict]:
    """Ritorna una lista di {'titolo','spiegazione','target_agent','kpi_correlati'}.
    kpis: dict kpi_id -> risultato di metrics.py. escalation_pct: KPI ausiliario
    (percentuale di opportunità con escalation_richiesta=True), calcolato da
    pipeline.py e passato qui separatamente perché non fa parte dei KPI
    "standard" richiesti ma alimenta comunque un'interpretazione reale."""
    insights: list[dict] = []

    conv = kpis.get("conversion_rate")
    close = kpis.get("close_rate")
    if lead_count >= _LEAD_SUFFICIENTI_MIN and _valore_valido(close) and close["value"] < _CONVERSIONE_BASSA_MAX:
        insights.append({
            "titolo": "Lead Generation produce lead sufficienti ma Sales converte poco",
            "spiegazione": (
                f"Nel periodo sono stati acquisiti {lead_count} lead (sufficienti per un'analisi), ma solo il "
                f"{close['value']}% delle opportunità aperte si è chiuso in una vendita (close_rate). Il "
                f"collo di bottiglia sembra nella fase commerciale, non nell'acquisizione."
            ),
            "target_agent": "sales-agent", "kpi_correlati": ["conversion_rate", "close_rate"],
        })

    drop = kpis.get("funnel_drop_off")
    if drop and not drop.get("missing_data"):
        for passo in drop.get("passi", []):
            if passo.get("drop_pct") is not None and passo["drop_pct"] >= _DROP_OFF_ALTO_MIN:
                insights.append({
                    "titolo": f"Abbandono elevato tra '{passo['da']}' e '{passo['a']}'",
                    "spiegazione": (
                        f"Il {passo['drop_pct']}% delle opportunità che raggiungono lo stage '{passo['da']}' "
                        f"non arriva a '{passo['a']}': vale la pena rivedere la strategia in questo punto "
                        f"specifico della pipeline."
                    ),
                    "target_agent": "sales-agent", "kpi_correlati": ["funnel_drop_off"],
                })
                break  # un solo insight di drop-off per report, il più significativo

    if escalation_pct and not escalation_pct.get("missing_data") and escalation_pct["value"] >= _ESCALATION_ALTA_MIN:
        insights.append({
            "titolo": "Alta percentuale di opportunità che richiedono intervento umano",
            "spiegazione": (
                f"Il {escalation_pct['value']}% delle opportunità commerciali attive è in escalation "
                f"(nessuna regola automatica applicabile): la pipeline potrebbe incontrare situazioni non "
                f"previste dalla strategia attuale, utile una revisione umana delle regole di transizione."
            ),
            "target_agent": "coordinatore-actelya", "kpi_correlati": [],
        })

    if not insights:
        insights.append({
            "titolo": "Dati insufficienti per un'interpretazione affidabile",
            "spiegazione": "Il volume di lead/opportunità nel periodo è troppo basso per individuare pattern "
                          "significativi senza rischiare falsi positivi: nessuna anomalia dichiarata.",
            "target_agent": "coordinatore-actelya", "kpi_correlati": [],
        })

    return insights
