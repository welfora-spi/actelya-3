import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import ContentCreator from "@/pages/ContentCreator";
import { AuthProvider } from "@/context/AuthContext";

jest.mock("sonner", () => ({
  toast: { info: jest.fn(), warning: jest.fn(), success: jest.fn(), error: jest.fn() },
}));

function page(items, { page: p = 1, page_size = 10, total } = {}) {
  const t = total != null ? total : items.length;
  return { items, total: t, page: p, page_size, pages: Math.max(0, Math.ceil(t / page_size)) };
}

const ITEM_BOZZA = {
  id: "content-1", content_type: "post_social", objective: "Aumentare le richieste di preventivo",
  channel: "instagram", funnel_stage: "MOFU", status: "BOZZA", motivazione_tipo: "Canale 'instagram': formato standard.",
  content: null, generazione: {}, semantic_check: { status: "NON_VERIFICATO", affermazioni_contestate: [] },
};

const ITEM_IN_ATTESA_APPROVAZIONE = {
  ...ITEM_BOZZA, id: "content-2", status: "IN_ATTESA_APPROVAZIONE",
  content: { titolo: "", corpo: "Scopri la nostra offerta.", cta: "Scopri di più", hashtags: ["#acme"], varianti: ["Variante 1"] },
};

function mockApi({ items = page([ITEM_BOZZA]), detail = ITEM_BOZZA } = {}) {
  const get = jest.fn((url) => {
    if (url === "/auth/me") {
      return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" } } });
    }
    if (url === "/content-creator/items") return Promise.resolve({ data: items });
    if (url.match(/\/content-creator\/items\/[^/]+$/)) return Promise.resolve({ data: detail });
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
    <MemoryRouter initialEntries={["/content-creator"]}>
      <AuthProvider>
        <ContentCreator />
      </AuthProvider>
    </MemoryRouter>
  );
}

test("mostra la lista dei contenuti", async () => {
  mockApiState = mockApi();
  renderPage();
  expect(await screen.findByText("post_social")).toBeInTheDocument();
});

test("stato vuoto quando non ci sono contenuti", async () => {
  mockApiState = mockApi({ items: page([]) });
  renderPage();
  expect(await screen.findByText("Nessun contenuto ancora.")).toBeInTheDocument();
});

test("selezionando un contenuto in BOZZA mostra il pulsante Genera", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("post_social"));
  expect(await screen.findByTestId("content-generate-btn")).toBeInTheDocument();
});

test("un contenuto in attesa di approvazione mostra i pulsanti Approva/Rifiuta e il corpo generato", async () => {
  mockApiState = mockApi({ items: page([ITEM_IN_ATTESA_APPROVAZIONE]), detail: ITEM_IN_ATTESA_APPROVAZIONE });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("post_social"));
  expect(await screen.findByTestId("content-approve-btn")).toBeInTheDocument();
  expect(await screen.findByTestId("content-item-body")).toHaveTextContent("Scopri la nostra offerta.");
});

test("apre il modale di nuova richiesta", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(screen.getByTestId("new-content-item"));
  expect(await screen.findByText("Nuova richiesta di contenuto")).toBeInTheDocument();
});

test("nessun JSON grezzo viene mai renderizzato", async () => {
  mockApiState = mockApi({ items: page([ITEM_IN_ATTESA_APPROVAZIONE]), detail: ITEM_IN_ATTESA_APPROVAZIONE });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("post_social"));
  await screen.findByTestId("content-item-body");
  expect(document.body.textContent).not.toMatch(/[{[]"[a-z_]+":/);
});

test("la lista usa la paginazione lato server (page/page_size)", async () => {
  mockApiState = mockApi();
  renderPage();
  await screen.findByText("post_social");
  await waitFor(() => {
    expect(mockApiState.get).toHaveBeenCalledWith("/content-creator/items", { params: { page: 1, page_size: 10 } });
  });
});
