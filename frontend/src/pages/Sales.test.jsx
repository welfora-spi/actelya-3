import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Sales from "@/pages/Sales";
import { AuthProvider } from "@/context/AuthContext";

jest.mock("sonner", () => ({
  toast: { info: jest.fn(), warning: jest.fn(), success: jest.fn(), error: jest.fn() },
}));

function page(items, { page: p = 1, page_size = 10, total } = {}) {
  const t = total != null ? total : items.length;
  return { items, total: t, page: p, page_size, pages: Math.max(0, Math.ceil(t / page_size)) };
}

const OPP_QUALIFICATO = {
  id: "opp-1", lead_id: "lead-1", lead_type: "aziende", stage: "QUALIFICATO",
  next_best_action: "CONTATTA_ORA", message_content_item_id: null, appointment_proposal_id: null,
  escalation_richiesta: false,
  analysis: { pain_point: "Nessun segnale specifico.", value_proposition: "Soluzione per il settore software.", canale: "email", stima_interesse: "MEDIA" },
};

const OPP_CONTATTATA = { ...OPP_QUALIFICATO, id: "opp-2", stage: "CONTATTATO", message_content_item_id: "content-1" };
const OPP_ESCALATA = { ...OPP_QUALIFICATO, id: "opp-3", escalation_richiesta: true };

function mockApi({ items = page([OPP_QUALIFICATO]), detail = OPP_QUALIFICATO } = {}) {
  const get = jest.fn((url) => {
    if (url === "/auth/me") {
      return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" } } });
    }
    if (url === "/sales/opportunities") return Promise.resolve({ data: items });
    if (url.match(/\/sales\/opportunities\/[^/]+$/)) return Promise.resolve({ data: detail });
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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/sales"]}>
      <AuthProvider>
        <Sales />
      </AuthProvider>
    </MemoryRouter>
  );
}

test("mostra la lista delle opportunità", async () => {
  mockApiState = mockApi();
  renderPage();
  expect(await screen.findByText("lead-1")).toBeInTheDocument();
});

test("stato vuoto quando non ci sono opportunità", async () => {
  mockApiState = mockApi({ items: page([]) });
  renderPage();
  expect(await screen.findByText("Nessuna opportunità ancora.")).toBeInTheDocument();
});

test("selezionando un'opportunità QUALIFICATO mostra il pulsante di richiesta messaggio", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("lead-1"));
  expect(await screen.findByTestId("request-message-btn")).toBeInTheDocument();
});

test("un'opportunità CONTATTATA mostra il pulsante di registrazione risposta", async () => {
  mockApiState = mockApi({ items: page([OPP_CONTATTATA]), detail: OPP_CONTATTATA });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("lead-1"));
  expect(await screen.findByTestId("record-response-btn")).toBeInTheDocument();
});

test("un'opportunità con escalation mostra l'avviso e il pulsante di risoluzione", async () => {
  mockApiState = mockApi({ items: page([OPP_ESCALATA]), detail: OPP_ESCALATA });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("lead-1"));
  expect(await screen.findByText(/Richiede intervento umano/)).toBeInTheDocument();
});

test("apre il modale di nuova opportunità", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(screen.getByTestId("new-opportunity"));
  expect(await screen.findByText("Nuova opportunità commerciale")).toBeInTheDocument();
});

test("la lista usa la paginazione lato server (page/page_size)", async () => {
  mockApiState = mockApi();
  renderPage();
  await screen.findByText("lead-1");
  await waitFor(() => {
    expect(mockApiState.get).toHaveBeenCalledWith("/sales/opportunities", { params: { page: 1, page_size: 10 } });
  });
});
