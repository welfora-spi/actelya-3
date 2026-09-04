import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Onboarding from "@/pages/Onboarding";
import api from "@/lib/api";

jest.mock("@/lib/api", () => {
  const get = jest.fn();
  const post = jest.fn(() => Promise.resolve({ data: {} }));
  return { __esModule: true, default: { get, post }, formatApiError: (d) => d || "" };
});

const STATUS_READY = {
  onboarding_status: "IN_CORSO", missing_core_fields: [], open_conflicts: 0, ready_to_complete: true,
};
const FACTS = {
  ragione_sociale: { id: "fact-1", field: "ragione_sociale", value: "Panetteria Rossi", method: "DICHIARATO",
                    source: "onboarding_ceo", confidence: 0.9, state: "ATTIVO" },
};

function mockLoad({ status = STATUS_READY, facts = FACTS, conflicts = {} } = {}) {
  api.get.mockImplementation((url) => {
    if (url === "/onboarding/status") return Promise.resolve({ data: status });
    if (url === "/knowledge/facts/current") return Promise.resolve({ data: facts });
    if (url === "/knowledge/conflicts") return Promise.resolve({ data: conflicts });
    return Promise.resolve({ data: {} });
  });
}

function renderOnboarding() {
  return render(<MemoryRouter><Onboarding /></MemoryRouter>);
}

describe("Onboarding", () => {
  beforeEach(() => jest.clearAllMocks());

  it("shows the Fact Ledger and enables completion when ready", async () => {
    mockLoad();
    renderOnboarding();

    expect(await screen.findByText("Panetteria Rossi")).toBeInTheDocument();
    expect(screen.getByText("Tutti i campi base sono presenti.")).toBeInTheDocument();
    expect(screen.getByTestId("onboarding-complete")).not.toBeDisabled();
  });

  it("lists missing core fields and disables completion", async () => {
    mockLoad({ status: { ...STATUS_READY, missing_core_fields: ["settore", "sito_web"], ready_to_complete: false } });
    renderOnboarding();

    expect(await screen.findByText(/Campi mancanti: settore, sito_web/)).toBeInTheDocument();
    expect(screen.getByTestId("onboarding-complete")).toBeDisabled();
  });

  it("shows open contradictions and resolves one on confirm", async () => {
    const conflicts = {
      settore: [
        { id: "fact-a", value: "Settore A", method: "DICHIARATO", source: "onboarding_ceo" },
        { id: "fact-b", value: "Settore B", method: "DICHIARATO", source: "manuale" },
      ],
    };
    mockLoad({ status: { ...STATUS_READY, open_conflicts: 1, ready_to_complete: false }, conflicts });
    renderOnboarding();

    expect(await screen.findByText("Contraddizioni da risolvere")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("conflict-confirm-fact-b"));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/knowledge/facts/fact-b/confirm"));
  });
});
