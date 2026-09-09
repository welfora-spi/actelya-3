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

describe("Onboarding — evidenze del Fact Ledger e persistenza della Discovery", () => {
  beforeEach(() => jest.clearAllMocks());

  const FACTS_MISTI = {
    ragione_sociale: { id: "fact-1", field: "ragione_sociale", value: "SPI Tool", method: "DICHIARATO",
                      source: "onboarding_ceo", confidence: 0.9, state: "ATTIVO", evidence: [] },
    prodotti_servizi_candidati: {
      id: "fact-2", field: "prodotti_servizi_candidati", value: "SPI Pension, ACTELYA", method: "ESTRATTO",
      source: "spitool.it", confidence: 0.6, state: "ATTIVO",
      evidence: [{ url: "https://www.spitool.it/", acquisito_il: "2026-09-09T12:25:08Z",
                  estratto: "SPI Pension, ACTELYA", source: "spitool.it" }],
    },
    tono_di_voce: { id: "fact-3", field: "tono_di_voce", value: "Professionale e diretto", method: "ESTRATTO",
                   source: "discovery_sito", confidence: 0.7, state: "ATTIVO", evidence: [] },
  };
  const RUN_LETTO = {
    id: "disco-1", status: "COMPLETATO", mode: "SIMULATO", warnings: [],
    real_fetch: { url: "https://www.spitool.it/", esito: "CONTENUTO_LETTO", acquisito_il: "2026-09-09T12:25:08Z",
                 social_links: [], via_rendering_js: true },
  };

  function mockLoadFull({ facts = FACTS_MISTI, runs = [RUN_LETTO] } = {}) {
    api.get.mockImplementation((url) => {
      if (url === "/onboarding/status") return Promise.resolve({ data: STATUS_READY });
      if (url === "/knowledge/facts/current") return Promise.resolve({ data: facts });
      if (url === "/knowledge/conflicts") return Promise.resolve({ data: {} });
      if (url === "/discovery/runs") return Promise.resolve({ data: runs });
      return Promise.resolve({ data: {} });
    });
  }

  it("un fatto con evidenza mostra URL cliccabile, data e un estratto leggibile", async () => {
    mockLoadFull();
    renderOnboarding();
    await screen.findByText("SPI Tool");

    const cell = screen.getByTestId("fact-evidence-prodotti_servizi_candidati");
    const link = cell.querySelector('a[href="https://www.spitool.it/"]');
    expect(link).toBeInTheDocument();
    expect(cell).toHaveTextContent("acquisita il 2026-09-09T12:25:08Z");
    expect(cell).toHaveTextContent("SPI Pension, ACTELYA");
  });

  it("un fatto ESTRATTO senza evidenza (euristica pregressa) lo dichiara esplicitamente, mai una fonte inventata", async () => {
    mockLoadFull();
    renderOnboarding();
    await screen.findByText("SPI Tool");

    const cell = screen.getByTestId("fact-no-evidence-tono_di_voce");
    expect(cell).toHaveTextContent("Nessuna evidenza puntuale disponibile");
    expect(cell).toHaveTextContent("stima euristica");
  });

  it("distingue dichiarato / estratto con evidenza / estratto euristico nella colonna provenienza", async () => {
    mockLoadFull();
    renderOnboarding();
    await screen.findByText("SPI Tool");

    expect(screen.getByTestId("fact-provenance-ragione_sociale")).toHaveTextContent("Dichiarato dall'utente");
    expect(screen.getByTestId("fact-provenance-prodotti_servizi_candidati")).toHaveTextContent("con evidenza");
    expect(screen.getByTestId("fact-provenance-tono_di_voce")).toHaveTextContent("euristica, senza evidenza");
  });

  it("l'esito dell'ultima Discovery resta consultabile subito al caricamento della pagina (persistenza dopo refresh)", async () => {
    mockLoadFull();
    renderOnboarding();

    // Nessun click su "Avvia Discovery": il run deve comparire da /discovery/runs al mount.
    const badge = await screen.findByTestId("discovery-fetch-badge");
    expect(badge).toHaveTextContent("Pagina letta realmente");
    expect(api.post).not.toHaveBeenCalled();
  });

  it("chiarisce che mode=SIMULATO e real_fetch.esito=CONTENUTO_LETTO descrivono due fasi distinte, non un'etichetta contraddittoria", async () => {
    mockLoadFull();
    renderOnboarding();
    await screen.findByTestId("discovery-summary");

    expect(screen.getByText(/Sempre simulata/)).toBeInTheDocument();
    expect(screen.getByTestId("discovery-fetch-badge")).toHaveTextContent("Pagina letta realmente");
  });
});
