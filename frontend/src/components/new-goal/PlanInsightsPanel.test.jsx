import { render, screen } from "@testing-library/react";
import PlanInsightsPanel from "./PlanInsightsPanel";

const PIANO_COMPLETO = {
  priorita: "ALTA", urgenza: "MEDIA", scadenza: "2026-12-01",
  budget_totale: 2000, budget_allocato: 1800, budget_residuo_operativo: 45.5,
  budget_status: "OK", allocazioni_budget: [{ etichetta: "social", importo: 1000 }],
  pubblico: "famiglie locali", canali: ["Instagram", "Facebook"],
  strategia_proposta: "Campagna locale mirata",
  rischi_valutati: [{ categoria: "spesa", severita: "MEDIA", azione: "APPROVAL" }],
  kpi: ["engagement"], approvazioni_necessarie: ["pubblicazione"],
  assunzioni: ["pubblico gia' noto"],
  correzioni: [{ tipo: "capability_scartata", dettaglio: "'leadgen' scartata." }],
};

describe("PlanInsightsPanel", () => {
  it("non renderizza nulla quando normalizedPlan e' assente", () => {
    const { container } = render(<PlanInsightsPanel normalizedPlan={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("mostra tutte le sezioni quando i dati sono completi", () => {
    render(<PlanInsightsPanel normalizedPlan={PIANO_COMPLETO} />);
    const panel = screen.getByTestId("plan-insights");
    expect(panel).toHaveTextContent("Priorita': ALTA");
    expect(panel).toHaveTextContent("Urgenza: MEDIA");
    expect(panel).toHaveTextContent("Scadenza: 2026-12-01");
    expect(panel).toHaveTextContent("2000");
    expect(panel).toHaveTextContent("allocato: 1800");
    expect(panel).toHaveTextContent("residuo operativo: 45.5");
    expect(panel).toHaveTextContent("social: 1000");
    expect(panel).toHaveTextContent("famiglie locali");
    expect(panel).toHaveTextContent("Instagram");
    expect(panel).toHaveTextContent("Campagna locale mirata");
    expect(panel).toHaveTextContent("spesa");
    expect(panel).toHaveTextContent("APPROVAL");
    expect(panel).toHaveTextContent("engagement");
    expect(panel).toHaveTextContent("pubblicazione");
    expect(panel).toHaveTextContent("pubblico gia' noto");
    expect(panel).toHaveTextContent("leadgen");
  });

  it("nasconde la sezione budget quando NON_APPLICABILE", () => {
    render(<PlanInsightsPanel normalizedPlan={{ ...PIANO_COMPLETO, budget_status: "NON_APPLICABILE", budget_totale: null }} />);
    const panel = screen.getByTestId("plan-insights");
    expect(panel).not.toHaveTextContent("Budget");
  });

  it("con campi opzionali assenti non mostra le sezioni corrispondenti ne' errori", () => {
    render(<PlanInsightsPanel normalizedPlan={{ priorita: "MEDIA", urgenza: "MEDIA", budget_status: "NON_APPLICABILE" }} />);
    const panel = screen.getByTestId("plan-insights");
    expect(panel).not.toHaveTextContent("Rischi valutati");
    expect(panel).not.toHaveTextContent("KPI");
    expect(panel).not.toHaveTextContent("Approvazioni necessarie");
    expect(panel).not.toHaveTextContent("Assunzioni");
    expect(panel).not.toHaveTextContent("Correzioni applicate dal validatore");
    expect(panel.textContent).not.toMatch(/undefined|null/);
  });

  it("mai JSON grezzo nel testo del pannello", () => {
    render(<PlanInsightsPanel normalizedPlan={PIANO_COMPLETO} />);
    const panel = screen.getByTestId("plan-insights");
    expect(panel.textContent).not.toMatch(/[{[]"[a-z_]+":/);
  });
});
