"""Analyst/KPI — test diretti di metrics.py e insights.py (nessun Mongo,
nessuna rete): ogni KPI con formula/fonte/affidabilità/missing_data
espliciti, mai un valore inventato quando il campione è insufficiente."""
from app.domains.analyst import metrics
from app.domains.analyst.insights import generate_insights


def test_conversion_rate_calcola_percentuale_corretta():
    kpi = metrics.conversion_rate(lead_count=20, qualified_count=5, time_range_days=30)
    assert kpi["value"] == 25.0
    assert kpi["missing_data"] is False
    assert kpi["reliability"] == "ALTA"


def test_conversion_rate_nessun_lead_e_non_disponibile():
    kpi = metrics.conversion_rate(lead_count=0, qualified_count=0, time_range_days=30)
    assert kpi["value"] is None
    assert kpi["missing_data"] is True
    assert kpi["reliability"] == "NON_DISPONIBILE"


def test_conversion_rate_campione_piccolo_e_affidabilita_bassa():
    kpi = metrics.conversion_rate(lead_count=3, qualified_count=1, time_range_days=30)
    assert kpi["reliability"] == "BASSA"


def test_lead_velocity_calcola_lead_al_giorno():
    kpi = metrics.lead_velocity(lead_count=30, time_range_days=30)
    assert kpi["value"] == 1.0


def test_close_rate_nessuna_chiusura_e_non_disponibile():
    kpi = metrics.close_rate(vinte=0, perse=0, time_range_days=30)
    assert kpi["missing_data"] is True


def test_close_rate_calcola_correttamente():
    kpi = metrics.close_rate(vinte=3, perse=7, time_range_days=30)
    assert kpi["value"] == 30.0


def test_funnel_drop_off_calcola_passi_tra_stage_consecutivi():
    conteggi = {"QUALIFICATO": 10, "CONTATTATO": 10, "IN_RELAZIONE": 4}
    ordine = ("QUALIFICATO", "CONTATTATO", "IN_RELAZIONE", "FOLLOW_UP")
    kpi = metrics.funnel_drop_off(conteggi_per_stage=conteggi, ordine_stage=ordine, time_range_days=30)
    passi = {p["da"]: p for p in kpi["passi"]}
    assert passi["QUALIFICATO"]["drop_pct"] == 0.0  # 10 -> 10, nessun abbandono
    assert passi["CONTATTATO"]["drop_pct"] == 60.0  # 10 -> 4
    assert passi["IN_RELAZIONE"]["drop_pct"] == 100.0  # 4 -> 0 (nessuno ha ancora raggiunto FOLLOW_UP)


def test_funnel_drop_off_stage_mai_raggiunto_e_missing_data():
    conteggi = {"QUALIFICATO": 0, "CONTATTATO": 0}
    ordine = ("QUALIFICATO", "CONTATTATO")
    kpi = metrics.funnel_drop_off(conteggi_per_stage=conteggi, ordine_stage=ordine, time_range_days=30)
    assert kpi["passi"][0]["missing_data"] is True
    assert kpi["missing_data"] is True


def test_cost_per_unit_nessuna_unita_e_non_disponibile():
    kpi = metrics.cost_per_unit("cost_per_lead", costo_totale=10.0, unita=0, formula="x", source="y", time_range_days=30)
    assert kpi["missing_data"] is True


def test_cost_per_unit_costo_zero_e_esplicitamente_segnalato():
    kpi = metrics.cost_per_unit("cost_per_lead", costo_totale=0.0, unita=10, formula="x", source="y", time_range_days=30)
    assert kpi["value"] == 0.0
    assert "Nessun costo reale" in kpi["note"]


def test_non_disponibile_e_sempre_missing_data():
    kpi = metrics.non_disponibile("roas", note="nessuna integrazione", time_range_days=30)
    assert kpi["value"] is None
    assert kpi["missing_data"] is True
    assert kpi["reliability"] == "NON_DISPONIBILE"


# ==================== insights.py ====================
def test_generate_insights_lead_sufficienti_ma_conversione_bassa():
    kpis = {
        "conversion_rate": metrics.conversion_rate(lead_count=20, qualified_count=10, time_range_days=30),
        "close_rate": metrics.close_rate(vinte=1, perse=9, time_range_days=30),
    }
    insights = generate_insights(kpis=kpis, lead_count=20, escalation_pct=None)
    titoli = [i["titolo"] for i in insights]
    assert any("Sales converte poco" in t for t in titoli)
    assert insights[0]["target_agent"] == "sales-agent"


def test_generate_insights_dati_insufficienti_fallback_onesto():
    kpis = {"conversion_rate": metrics.conversion_rate(lead_count=0, qualified_count=0, time_range_days=30),
           "close_rate": metrics.close_rate(vinte=0, perse=0, time_range_days=30)}
    insights = generate_insights(kpis=kpis, lead_count=0, escalation_pct=None)
    assert len(insights) == 1
    assert "insufficienti" in insights[0]["titolo"].lower()


def test_generate_insights_alta_escalation_segnala_al_coordinatore():
    kpis = {"conversion_rate": metrics.conversion_rate(lead_count=0, qualified_count=0, time_range_days=30),
           "close_rate": metrics.close_rate(vinte=0, perse=0, time_range_days=30)}
    escalation_alta = metrics.escalation_rate(escalation_count=5, opportunita_totali=10, time_range_days=30)
    insights = generate_insights(kpis=kpis, lead_count=0, escalation_pct=escalation_alta)
    assert any(i["target_agent"] == "coordinatore-actelya" and "intervento umano" in i["titolo"].lower() for i in insights)


def test_generate_insights_drop_off_alto_segnala_al_sales():
    kpis = {
        "conversion_rate": metrics.conversion_rate(lead_count=0, qualified_count=0, time_range_days=30),
        "close_rate": metrics.close_rate(vinte=0, perse=0, time_range_days=30),
        "funnel_drop_off": metrics.funnel_drop_off(
            conteggi_per_stage={"QUALIFICATO": 10, "CONTATTATO": 2},
            ordine_stage=("QUALIFICATO", "CONTATTATO"), time_range_days=30,
        ),
    }
    insights = generate_insights(kpis=kpis, lead_count=0, escalation_pct=None)
    assert any("Abbandono elevato" in i["titolo"] for i in insights)
