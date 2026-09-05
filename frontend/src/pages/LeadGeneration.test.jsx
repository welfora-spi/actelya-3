import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import LeadGeneration from "@/pages/LeadGeneration";
import { AuthProvider } from "@/context/AuthContext";

jest.mock("sonner", () => ({
  toast: { info: jest.fn(), warning: jest.fn(), success: jest.fn(), error: jest.fn() },
}));

const CAMPAIGN_BOZZA = {
  id: "leadcamp-1", name: "Hotel Nord Italia", status: "BOZZA",
  channels: ["email"], target_quantity: 50, budget: 500, deadline: "2026-12-01",
  icp: { settori_esclusi: [] },
};

const CAMPAIGN_APPROVATA = { ...CAMPAIGN_BOZZA, status: "APPROVATA" };

const FILE_VALIDATO = {
  id: "leadfile-1", filename: "lead.csv", extension: ".csv", status: "VALIDATO",
  row_count: 2, columns: ["ragione_sociale", "email"],
  suggested_mapping: { ragione_sociale: "ragione_sociale", email: "email" },
};

function page(items, { page: p = 1, page_size = 10, total } = {}) {
  const t = total != null ? total : items.length;
  return { items, total: t, page: p, page_size, pages: Math.max(0, Math.ceil(t / page_size)) };
}

const LEAD_1 = {
  id: "lead-1", ragione_sociale: { value: "Acme Srl" }, settore: { value: "software" },
  citta: { value: "Milano" }, score: 72, qualification_status: "QUALIFIED",
  compliance_status: "READY", missing_data: [],
};
const LEAD_2 = {
  id: "lead-2", ragione_sociale: { value: "Beta Spa" }, settore: { value: "turismo" },
  citta: { value: "Napoli" }, score: 40, qualification_status: "REVIEW_REQUIRED",
  compliance_status: "NEEDS_CLARIFICATION", missing_data: ["email"],
};

const DUPLICATE_PENDING = {
  id: "dedup-1", match_type: "ESATTO", tipo: "dominio", record_ids: ["lead-1", "lead-2"], status: "PENDING",
};

function mockApi({
  campaigns = page([CAMPAIGN_BOZZA]),
  files = page([FILE_VALIDATO]),
  leads = page([LEAD_1, LEAD_2]),
  duplicates = page([]),
} = {}) {
  const get = jest.fn((url, config) => {
    if (url === "/auth/me") {
      return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" } } });
    }
    if (url === "/leadgen/campaigns") return Promise.resolve({ data: campaigns });
    if (url === "/leadgen/files") return Promise.resolve({ data: files });
    if (url.match(/\/leadgen\/campaigns\/[^/]+$/)) return Promise.resolve({ data: campaigns.items[0] || CAMPAIGN_BOZZA });
    if (url.match(/\/leadgen\/campaigns\/[^/]+\/leads/)) return Promise.resolve({ data: leads });
    if (url.match(/\/leadgen\/campaigns\/[^/]+\/duplicates/)) return Promise.resolve({ data: duplicates });
    return Promise.reject({ response: { status: 404 } });
  });
  const post = jest.fn(() => Promise.resolve({ data: {} }));
  return { get, post };
}

let mockApiState = mockApi();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a) => mockApiState.get(...a), post: (...a) => mockApiState.post(...a) },
  formatApiError: (d) => d || "",
}));

let mockSearchParamsValue = new URLSearchParams();
jest.mock("react-router-dom", () => ({
  ...jest.requireActual("react-router-dom"),
  useSearchParams: () => [mockSearchParamsValue],
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/lead-generation"]}>
      <AuthProvider>
        <LeadGeneration />
      </AuthProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  mockSearchParamsValue = new URLSearchParams();
});

test("mostra l'elenco campagne e file caricati", async () => {
  mockApiState = mockApi();
  renderPage();
  expect(await screen.findByText("Hotel Nord Italia")).toBeInTheDocument();
  expect(await screen.findByText("lead.csv")).toBeInTheDocument();
});

test("stato vuoto quando non esistono campagne", async () => {
  mockApiState = mockApi({ campaigns: page([]) });
  renderPage();
  expect(await screen.findByText(/Nessuna campagna ancora/)).toBeInTheDocument();
});

test("selezionando una campagna mostra la tabella lead con punteggio, stato e provenienza", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));

  const table = await screen.findByTestId("leads-table");
  expect(within(table).getByText("Acme Srl")).toBeInTheDocument();
  expect(within(table).getByText("72")).toBeInTheDocument();
  expect(within(table).getByText("QUALIFIED")).toBeInTheDocument();
  expect(within(table).getByText("Beta Spa")).toBeInTheDocument();
  expect(within(table).getByText("email")).toBeInTheDocument(); // dato mancante mostrato
});

test("nessun JSON grezzo viene mai renderizzato", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));
  await screen.findByTestId("leads-table");
  expect(document.body.textContent).not.toMatch(/[{[]"[a-z_]+":/);
});

test("duplicati in sospeso (conteggio 'total', non solo la pagina corrente) bloccano l'approvazione", async () => {
  mockApiState = mockApi({ duplicates: page([DUPLICATE_PENDING], { total: 7, page_size: 1 }) });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));

  expect(await screen.findByText(/7 duplicati in attesa di revisione/)).toBeInTheDocument();
  const approveBtn = screen.getByTestId("lead-approve-btn");
  expect(approveBtn).toBeDisabled();
  expect(screen.getByText("Unisci")).toBeInTheDocument();
  expect(screen.getByText("Mantieni separati")).toBeInTheDocument();
});

test("una campagna approvata mostra le azioni di esportazione e handoff, non l'approvazione", async () => {
  mockApiState = mockApi({ campaigns: page([CAMPAIGN_APPROVATA]) });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));

  expect(await screen.findByText("Esporta CSV")).toBeInTheDocument();
  expect(screen.getByText("Esporta XLSX")).toBeInTheDocument();
  expect(screen.getByText("Prepara handoff")).toBeInTheDocument();
  expect(screen.queryByTestId("lead-approve-btn")).not.toBeInTheDocument();
});

test("il filtro per stato di qualificazione richiama la lista lead con il parametro corretto", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));
  await screen.findByTestId("leads-table");

  const select = screen.getByDisplayValue("Tutti gli stati");
  await user.selectOptions(select, "QUALIFIED");

  await waitFor(() => {
    const called = mockApiState.get.mock.calls.some(
      ([url, cfg]) => url.includes("/leads") && cfg?.params?.qualification_status === "QUALIFIED"
    );
    expect(called).toBe(true);
  });
});

test("il toggle aziende/persone richiama la lista lead con il tipo corretto", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));
  await screen.findByTestId("leads-table");

  await user.click(screen.getByText("Persone"));

  await waitFor(() => {
    const called = mockApiState.get.mock.calls.some(
      ([url, cfg]) => url.includes("/leads") && cfg?.params?.tipo === "persone"
    );
    expect(called).toBe(true);
  });
});

test("ripresa da Sala Riunioni: campaignId in query seleziona subito la campagna", async () => {
  mockSearchParamsValue = new URLSearchParams({ campaignId: "leadcamp-1" });
  mockApiState = mockApi();
  renderPage();
  const table = await screen.findByTestId("leads-table");
  expect(within(table).getByText("Acme Srl")).toBeInTheDocument();
});

test("apre il mapping quando si importa un file validato in una campagna selezionata", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));
  await screen.findByTestId("leads-table");

  await user.click(await screen.findByText(/Importa in/));
  expect(await screen.findByText(/Mapping colonne/)).toBeInTheDocument();
  expect(screen.getByText("Avvia import")).toBeInTheDocument();
});

// ==================== Paginazione ====================
test("con una sola pagina di risultati non mostra i controlli di paginazione", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));
  await screen.findByTestId("leads-table");
  expect(screen.queryByText("Successiva")).not.toBeInTheDocument();
});

test("dataset significativo: mostra i controlli, 'Successiva' richiama la pagina 2 mantenendo il filtro", async () => {
  mockApiState = mockApi({ leads: page([LEAD_1], { page: 1, page_size: 1, total: 25 }) });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));
  await screen.findByTestId("leads-table");

  expect(screen.getByText(/Pagina 1 di 25/)).toBeInTheDocument();
  expect(screen.getByText(/1–1 di 25 lead/)).toBeInTheDocument();

  const select = screen.getByDisplayValue("Tutti gli stati");
  await userEvent.selectOptions(select, "QUALIFIED");

  await user.click(screen.getByText("Successiva"));

  await waitFor(() => {
    const ultima = mockApiState.get.mock.calls.filter(([url]) => url.includes("/leads")).pop();
    expect(ultima[1].params.page).toBe(2);
    expect(ultima[1].params.qualification_status).toBe("QUALIFIED"); // il filtro resta applicato avanzando pagina
  });
});

test("'Precedente' e' disabilitato sulla prima pagina", async () => {
  mockApiState = mockApi({ leads: page([LEAD_1], { page: 1, page_size: 1, total: 3 }) });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));
  await screen.findByTestId("leads-table");
  expect(screen.getByText("Precedente")).toBeDisabled();
});

test("'Successiva' e' disabilitato sull'ultima pagina", async () => {
  mockApiState = mockApi({ leads: page([LEAD_2], { page: 3, page_size: 1, total: 3 }) });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));
  await screen.findByTestId("leads-table");
  expect(screen.getByText(/Pagina 3 di 3/)).toBeInTheDocument();
  expect(screen.getByText("Successiva")).toBeDisabled();
});

test("pagina vuota (nessun risultato per il filtro) mostra lo stato vuoto senza errori", async () => {
  mockApiState = mockApi({ leads: page([], { page: 1, page_size: 20, total: 0 }) });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("Hotel Nord Italia"));
  expect(await screen.findByText(/Nessun lead ancora importato/)).toBeInTheDocument();
});

test("campagne e file caricati usano la paginazione lato server (page/page_size), mai l'intero dataset", async () => {
  mockApiState = mockApi();
  renderPage();
  await screen.findByText("Hotel Nord Italia");
  await waitFor(() => {
    expect(mockApiState.get).toHaveBeenCalledWith("/leadgen/campaigns", { params: { page: 1, page_size: 10 } });
    expect(mockApiState.get).toHaveBeenCalledWith("/leadgen/files", { params: { page: 1, page_size: 10 } });
  });
});
