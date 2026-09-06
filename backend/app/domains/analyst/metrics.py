"""Analyst/KPI — calcolo DETERMINISTICO dei KPI (nessuna chiamata AI): ogni
funzione riceve conteggi REALI già aggregati da pipeline.py (mai una
chiamata Mongo qui, per restare testabile senza database) e restituisce un
KPI completo di formula/fonte/affidabilità/indicatore di dato mancante — mai
un valore inventato quando il volume è insufficiente o il dato non esiste."""
from __future__ import annotations

from typing import Optional

# Sotto questa soglia di osservazioni un rapporto è statisticamente troppo
# rumoroso per essere dichiarato affidabile — mai nascosto, solo etichettato.
_SOGLIA_ALTA = 20
_SOGLIA_MEDIA = 5


def _affidabilita(denominatore: int) -> str:
    if denominatore <= 0:
        return "NON_DISPONIBILE"
    if denominatore >= _SOGLIA_ALTA:
        return "ALTA"
    if denominatore >= _SOGLIA_MEDIA:
        return "MEDIA"
    return "BASSA"


def _kpi(kpi_id: str, *, value: Optional[float], formula: str, source: str, time_range_days: int,
        reliability: str, missing_data: bool, note: str = "") -> dict:
    return {
        "kpi_id": kpi_id, "value": value, "formula": formula, "source": source,
        "time_range_days": time_range_days, "reliability": reliability,
        "missing_data": missing_data, "note": note,
    }


def _rapporto(kpi_id: str, *, numeratore: int, denominatore: int, formula: str, source: str,
             time_range_days: int, note_zero: str = "") -> dict:
    if denominatore <= 0:
        return _kpi(kpi_id, value=None, formula=formula, source=source, time_range_days=time_range_days,
                   reliability="NON_DISPONIBILE", missing_data=True,
                   note=note_zero or "Nessuna osservazione nel periodo: valore non calcolabile.")
    valore = round(100.0 * numeratore / denominatore, 1)
    return _kpi(kpi_id, value=valore, formula=formula, source=source, time_range_days=time_range_days,
               reliability=_affidabilita(denominatore), missing_data=False)


def conversion_rate(*, lead_count: int, qualified_count: int, time_range_days: int) -> dict:
    return _rapporto(
        "conversion_rate", numeratore=qualified_count, denominatore=lead_count,
        formula="100 * lead_qualificati / lead_totali",
        source="lead_companies + lead_persons (qualification_status)", time_range_days=time_range_days,
    )


def lead_velocity(*, lead_count: int, time_range_days: int) -> dict:
    if time_range_days <= 0:
        return _kpi("lead_velocity", value=None, formula="lead_totali / giorni",
                   source="lead_companies + lead_persons", time_range_days=time_range_days,
                   reliability="NON_DISPONIBILE", missing_data=True, note="Intervallo temporale non valido.")
    valore = round(lead_count / time_range_days, 2)
    return _kpi("lead_velocity", value=valore, formula="lead_totali / giorni",
               source="lead_companies + lead_persons", time_range_days=time_range_days,
               reliability=_affidabilita(lead_count), missing_data=lead_count == 0,
               note="" if lead_count else "Nessun lead acquisito nel periodo.")


def response_rate(*, contattati_o_oltre: int, con_risposta: int, time_range_days: int) -> dict:
    return _rapporto(
        "response_rate", numeratore=con_risposta, denominatore=contattati_o_oltre,
        formula="100 * opportunità con una risposta registrata / opportunità contattate",
        source="sales_opportunities (stage)", time_range_days=time_range_days,
        note_zero="Nessuna opportunità ancora contattata nel periodo.",
    )


def appointment_rate(*, opportunita_totali: int, con_appuntamento: int, time_range_days: int) -> dict:
    return _rapporto(
        "appointment_rate", numeratore=con_appuntamento, denominatore=opportunita_totali,
        formula="100 * opportunità con appuntamento fissato o oltre / opportunità totali",
        source="sales_opportunities (stage)", time_range_days=time_range_days,
    )


def close_rate(*, vinte: int, perse: int, time_range_days: int) -> dict:
    return _rapporto(
        "close_rate", numeratore=vinte, denominatore=vinte + perse,
        formula="100 * opportunità vinte / (vinte + perse)",
        source="sales_opportunities (stage)", time_range_days=time_range_days,
        note_zero="Nessuna opportunità ancora chiusa (vinta o persa) nel periodo.",
    )


def funnel_drop_off(*, conteggi_per_stage: dict, ordine_stage: tuple, time_range_days: int) -> dict:
    """conteggi_per_stage[stage] = numero di opportunità la cui STORIA include
    quello stage (non solo lo stage attuale): un drop-off reale calcolato
    sulla progressione effettiva, non sulla sola istantanea corrente."""
    passi = []
    for i in range(len(ordine_stage) - 1):
        attuale, successivo = ordine_stage[i], ordine_stage[i + 1]
        raggiunto_attuale = conteggi_per_stage.get(attuale, 0)
        raggiunto_successivo = conteggi_per_stage.get(successivo, 0)
        if raggiunto_attuale <= 0:
            passi.append({"da": attuale, "a": successivo, "drop_pct": None, "missing_data": True})
            continue
        drop = round(100.0 * (1 - (raggiunto_successivo / raggiunto_attuale)), 1)
        passi.append({"da": attuale, "a": successivo, "drop_pct": drop, "missing_data": False})
    totale_osservazioni = sum(conteggi_per_stage.values())
    return _kpi(
        "funnel_drop_off", value=None, formula="100 * (1 - opportunità che hanno raggiunto lo stage successivo / opportunità che hanno raggiunto lo stage corrente)",
        source="sales_opportunities (history)", time_range_days=time_range_days,
        reliability=_affidabilita(totale_osservazioni), missing_data=totale_osservazioni == 0,
        note="",
    ) | {"passi": passi}


def escalation_rate(*, escalation_count: int, opportunita_totali: int, time_range_days: int) -> dict:
    return _rapporto(
        "escalation_rate", numeratore=escalation_count, denominatore=opportunita_totali,
        formula="100 * opportunità in escalation / opportunità totali",
        source="sales_opportunities (escalation_richiesta)", time_range_days=time_range_days,
    )


def non_disponibile(kpi_id: str, *, note: str, time_range_days: int, source: str = "") -> dict:
    """Un KPI dichiarato esplicitamente NON_DISPONIBILE (mai un valore
    inventato) quando non esiste ancora una fonte dati reale collegata."""
    return _kpi(kpi_id, value=None, formula="", source=source, time_range_days=time_range_days,
               reliability="NON_DISPONIBILE", missing_data=True, note=note)


def cost_per_unit(kpi_id: str, *, costo_totale: float, unita: int, formula: str, source: str,
                  time_range_days: int) -> dict:
    if unita <= 0:
        return _kpi(kpi_id, value=None, formula=formula, source=source, time_range_days=time_range_days,
                   reliability="NON_DISPONIBILE", missing_data=True,
                   note="Nessuna unità nel periodo: costo per unità non calcolabile.")
    valore = round(costo_totale / unita, 4)
    nota = "" if costo_totale > 0 else "Nessun costo reale registrato nel periodo (nessuna chiamata a pagamento eseguita)."
    return _kpi(kpi_id, value=valore, formula=formula, source=source, time_range_days=time_range_days,
               reliability=_affidabilita(unita), missing_data=False, note=nota)
