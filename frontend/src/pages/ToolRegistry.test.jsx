import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import ToolRegistry from "@/pages/ToolRegistry";
import { AuthProvider } from "@/context/AuthContext";

jest.mock("sonner", () => ({ toast: { info: jest.fn(), warning: jest.fn(), success: jest.fn(), error: jest.fn() } }));

const TOOLS = [
  { tool_id: "requesty_llm", category: "llm", provider: "Requesty", allowed_agents: ["coordinatore-actelya"],
    status: "VERIFICATO", code_complete: true, env_vars: [], note: "" },
  { tool_id: "apollo_prospect", category: "prospect_research", provider: "Apollo API",
    allowed_agents: ["lead-gen-specialist"], status: "NON_CONFIGURATO", code_complete: false,
    env_vars: ["APOLLO_API_KEY"], note: "" },
];

let mockApiState;
jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a) => mockApiState.get(...a), post: (...a) => mockApiState.post(...a) },
  formatApiError: (d) => d || "",
}));
jest.mock("react-router-dom", () => ({
  ...jest.requireActual("react-router-dom"),
  useSearchParams: () => [new URLSearchParams()],
}));

function mockApi(tools = TOOLS) {
  const get = jest.fn((url) => {
    if (url === "/auth/me") return Promise.resolve({ data: { user: { id: "u1", role: "ADMIN", organization_id: "org-1" } } });
    if (url === "/tool-registry") return Promise.resolve({ data: { tools, categories: [...new Set(tools.map((t) => t.category))] } });
    return Promise.reject({ response: { status: 404 } });
  });
  return { get, post: jest.fn(() => Promise.resolve({ data: {} })) };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/strumenti"]}>
      <AuthProvider><ToolRegistry /></AuthProvider>
    </MemoryRouter>
  );
}

test("mostra gli strumenti raggruppati per categoria con lo stato", async () => {
  mockApiState = mockApi();
  renderPage();
  expect(await screen.findByTestId("tool-requesty_llm")).toBeInTheDocument();
  expect(screen.getByTestId("tool-apollo_prospect")).toBeInTheDocument();
});

test("uno strumento non implementato mostra le variabili previste", async () => {
  mockApiState = mockApi();
  renderPage();
  const tool = await screen.findByTestId("tool-apollo_prospect");
  expect(tool.textContent).toMatch(/APOLLO_API_KEY/);
});

test("il filtro per categoria richiama l'API con il parametro corretto", async () => {
  mockApiState = mockApi();
  renderPage();
  await screen.findByTestId("tool-requesty_llm");
  const user = userEvent.setup();
  await user.selectOptions(screen.getByRole("combobox"), "prospect_research");
  await waitFor(() => {
    const called = mockApiState.get.mock.calls.some(
      ([url, cfg]) => url === "/tool-registry" && cfg?.params?.category === "prospect_research"
    );
    expect(called).toBe(true);
  });
});

test("nessun risultato mostra lo stato vuoto", async () => {
  mockApiState = mockApi([]);
  renderPage();
  expect(await screen.findByText(/Nessuno strumento corrisponde ai filtri/)).toBeInTheDocument();
});
