import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Deliverables from "@/pages/Deliverables";
import api from "@/lib/api";
import { AuthProvider } from "@/context/AuthContext";

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

  it("content_item usa il proprio renderer dedicato, mai il fallback generico ne' JSON grezzo come presentazione principale", async () => {
    const d = row({
      id: "d-content-item", deliverable_type: "content_item", status: "COMPLETATO_CON_AVVISI",
      content: {
        content_item_ids: ["c1"], requested_quantity: 1, produced_count: 1, contested_ids: [],
        items: [{ content_item_id: "c1", content_type: "post_social", status: "IN_ATTESA_APPROVAZIONE",
                 content: { titolo: "T", corpo: "Corpo leggibile", cta: "Vai", hashtags: [], varianti: [] },
                 semantic_check: { status: "OK", affermazioni_contestate: [] } }],
      },
    });
    api.get.mockImplementation((url) => {
      if (url === "/deliverables") return Promise.resolve({ data: [d] });
      if (url === "/auth/me") return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" } } });
      return Promise.reject(new Error("unexpected " + url));
    });
    render(
      <MemoryRouter initialEntries={["/deliverable"]}>
        <AuthProvider><Deliverables /></AuthProvider>
      </MemoryRouter>
    );
    expect(await screen.findByTestId("content-item-deliverable-preview")).toBeInTheDocument();
    expect(screen.getByText("Corpo leggibile")).toBeInTheDocument();
    expect(screen.queryByTestId("generic-deliverable-preview")).not.toBeInTheDocument();
    // il JSON resta un dettaglio opzionale collassato, non la presentazione principale
    const details = document.querySelector("details");
    expect(details.open).toBeFalsy();
  });

  it("mostra lo stato editoriale di ciascuna bozza (allineato al dettaglio piano), quando presente", async () => {
    await renderWithRows([
      row({
        id: "d-soc", deliverable_type: "social_content", content: { platform: "Instagram", posts: [] },
        item_decisions: [
          { item_index: 0, current_version: 2, decision: { status: "MODIFICA_RICHIESTA" } },
          { item_index: 1, current_version: 1, decision: { status: "APPROVATO" } },
        ],
      }),
    ]);
    const riepilogo = await screen.findByTestId("item-decisions-summary");
    expect(riepilogo.querySelector('[data-testid="item-decisions-summary-row-0"]')).toHaveTextContent("v2");
    expect(riepilogo.querySelector('[data-testid="item-decisions-summary-row-0"]')).toHaveTextContent("MODIFICA_RICHIESTA");
    expect(riepilogo.querySelector('[data-testid="item-decisions-summary-row-1"]')).toHaveTextContent("APPROVATO");
  });

  it("nessun riepilogo di stato bozze per un deliverable senza item_decisions", async () => {
    await renderWithRows([row({ id: "d-email", deliverable_type: "email", content: { oggetto: "Ciao", contenuto_completo: "Corpo" } })]);
    expect(screen.queryByTestId("item-decisions-summary")).not.toBeInTheDocument();
  });
});
