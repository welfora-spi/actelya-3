import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Analyst from "@/pages/Analyst";
import { AuthProvider } from "@/context/AuthContext";

jest.mock("sonner", () => ({
  toast: { info: jest.fn(), warning: jest.fn(), success: jest.fn(), error: jest.fn() },
}));

const REPORT = {
  id: "report-1", generated_at: "2026-09-06T10:00:00Z", time_range_days: 30,
  kpis: {
    conversion_rate: { value: 25.0, formula: "100 * lead_qualificati / lead_totali", reliability: "MEDIA", missing_data: false, note: "" },
    roas: { value: null, formula: "", reliability: "NON_DISPONIBILE", missing_data: true, note: "Nessuna integrazione advertising collegata." },
  },
  insights: [
    { titolo: "Lead Generation produce lead sufficienti ma Sales converte poco", spiegazione: "Dettaglio.", target_agent: "sales-agent", kpi_correlati: [] },
  ],
};

function mockApi({ reports = [REPORT], detail = REPORT } = {}) {
  const get = jest.fn((url) => {
    if (url === "/auth/me") {
      return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" } } });
    }
    if (url === "/analyst/reports") return Promise.resolve({ data: reports });
    if (url.match(/\/analyst\/reports\/[^/]+$/)) return Promise.resolve({ data: detail });
    return Promise.reject({ response: { status: 404 } });
  });
  const post = jest.fn(() => Promise.resolve({ data: REPORT }));
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
    <MemoryRouter initialEntries={["/analyst"]}>
      <AuthProvider>
        <Analyst />
      </AuthProvider>
    </MemoryRouter>
  );
}

beforeEach(() => { mockSearchParamsValue = new URLSearchParams(); });

test("mostra la lista dei report", async () => {
  mockApiState = mockApi();
  renderPage();
  expect(await screen.findByTestId("reports-list")).toBeInTheDocument();
});

test("stato vuoto quando non ci sono report", async () => {
  mockApiState = mockApi({ reports: [] });
  renderPage();
  expect(await screen.findByText("Nessun report ancora.")).toBeInTheDocument();
});

test("selezionando un report mostra i KPI e gli insight", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click((await screen.findAllByText(/2026/))[0]);
  expect(await screen.findByTestId("kpi-grid")).toBeInTheDocument();
  expect(await screen.findByText(/Sales converte poco/)).toBeInTheDocument();
});

test("un KPI NON_DISPONIBILE mostra un trattino, mai un valore inventato", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click((await screen.findAllByText(/2026/))[0]);
  const griglia = await screen.findByTestId("kpi-grid");
  expect(griglia.textContent).toContain("—");
});

test("ripresa da Sala Riunioni: reportId in query seleziona subito il report", async () => {
  mockSearchParamsValue = new URLSearchParams({ reportId: "report-1" });
  mockApiState = mockApi();
  renderPage();
  expect(await screen.findByTestId("kpi-grid")).toBeInTheDocument();
});

test("genera un nuovo report con il pulsante dedicato", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(screen.getByTestId("generate-report-btn"));
  expect(await screen.findByTestId("kpi-grid")).toBeInTheDocument();
});
