import { render, screen } from "@testing-library/react";
import Deliverables from "@/pages/Deliverables";
import api from "@/lib/api";

jest.mock("@/lib/api", () => {
  const get = jest.fn();
  return { __esModule: true, default: { get }, formatApiError: (d) => d || "", absoluteAssetUrl: (u) => u };
});

// MultimodalProjectPanel effettua le proprie chiamate api quando riceve un
// projectId: fuori scope qui (testato altrove), sostituito con uno stub
// minimo per isolare esclusivamente il dispatch di Deliverables.jsx.
jest.mock("@/components/MultimodalProjectPanel", () => ({
  __esModule: true,
  default: () => <div data-testid="multimodal-stub" />,
}));

function row(overrides) {
  return { id: "d1", deliverable_type: "email", status: "COMPLETATO", mode: "SIMULAZIONE", content: {}, warnings: [], ...overrides };
}

async function renderWithRows(rows) {
  api.get.mockImplementation((url) => {
    if (url === "/deliverables") return Promise.resolve({ data: rows });
    return Promise.reject(new Error("unexpected " + url));
  });
  render(<Deliverables />);
  return screen.findByTestId("deliverables-list");
}

describe("Deliverables — dispatch esplicito per deliverable_type", () => {
  it("un tipo sconosciuto NON viene mai inviato a EmailPreview: usa il fallback neutro", async () => {
    await renderWithRows([row({ id: "d-unknown", deliverable_type: "lead_gen_campaign", content: { campaign_name: "X" } })]);

    expect(screen.queryByTestId("email-preview")).not.toBeInTheDocument();
    expect(screen.getByTestId("generic-deliverable-preview")).toBeInTheDocument();
    expect(screen.getByText("lead_gen_campaign")).toBeInTheDocument();
  });

  it("il tipo 'email' usa davvero EmailPreview", async () => {
    await renderWithRows([row({ id: "d-email", deliverable_type: "email", content: { oggetto: "Ciao", contenuto_completo: "Corpo" } })]);

    expect(screen.getByTestId("email-preview")).toBeInTheDocument();
    expect(screen.queryByTestId("generic-deliverable-preview")).not.toBeInTheDocument();
  });

  it("editorial_plan/social_content usano il proprio renderer dedicato, mai EmailPreview né il fallback generico", async () => {
    await renderWithRows([
      row({ id: "d-ed", deliverable_type: "editorial_plan", content: { title: "Piano", cadence: "settimanale", pillars: [], calendar: [] } }),
      row({ id: "d-soc", deliverable_type: "social_content", content: { platform: "Instagram", posts: [] } }),
    ]);

    expect(screen.getByTestId("editorial-plan-preview")).toBeInTheDocument();
    expect(screen.getByTestId("social-content-preview")).toBeInTheDocument();
    expect(screen.queryByTestId("email-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("generic-deliverable-preview")).not.toBeInTheDocument();
  });

  it("fallback generico: distingue payload con testo/titolo da payload realmente vuoto", async () => {
    await renderWithRows([
      row({ id: "d-titled", deliverable_type: "sales_opportunity", content: { title: "Opportunità Acme", body: "Dettagli qui" } }),
    ]);
    expect(screen.getByText("Opportunità Acme")).toBeInTheDocument();
    expect(screen.getByText("Dettagli qui")).toBeInTheDocument();
    expect(screen.queryByTestId("generic-deliverable-empty")).not.toBeInTheDocument();
  });

  it("fallback generico: payload realmente vuoto mostra il messaggio dedicato, non una scheda email vuota", async () => {
    await renderWithRows([row({ id: "d-empty", deliverable_type: "analyst_report", content: {} })]);
    expect(screen.getByTestId("generic-deliverable-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("email-preview")).not.toBeInTheDocument();
  });
});
