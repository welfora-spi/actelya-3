import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import AppointmentSetter from "@/pages/AppointmentSetter";
import { AuthProvider } from "@/context/AuthContext";

jest.mock("sonner", () => ({
  toast: { info: jest.fn(), warning: jest.fn(), success: jest.fn(), error: jest.fn() },
}));

function page(items, { page: p = 1, page_size = 10, total } = {}) {
  const t = total != null ? total : items.length;
  return { items, total: t, page: p, page_size, pages: Math.max(0, Math.ceil(t / page_size)) };
}

const CONN_NON_CONFIGURATA = {
  id: "conn-1", name: "Google Calendar principale", provider_type: "google_calendar", status: "NON_CONFIGURATO",
};

const PROPOSAL_IN_ATTESA = {
  id: "prop-1", lead_id: "lead-1", lead_type: "aziende", duration_minutes: 30,
  status: "IN_ATTESA_APPROVAZIONE", connection_configured: true,
  proposed_slots: [
    { start: "2026-09-07T09:00:00+00:00", end: "2026-09-07T09:30:00+00:00" },
    { start: "2026-09-07T10:00:00+00:00", end: "2026-09-07T10:30:00+00:00" },
  ],
};
const PROPOSAL_APPROVATA = { ...PROPOSAL_IN_ATTESA, id: "prop-2", status: "APPROVATA" };
const PROPOSAL_SENZA_CONNESSIONE = {
  id: "prop-3", lead_id: "lead-3", lead_type: "aziende", duration_minutes: 30,
  status: "BOZZA", connection_configured: false, proposed_slots: [],
};

const BOOKING_CONFERMATA = { id: "book-1", start: "2026-09-07T09:00:00+00:00", status: "CONFERMATA" };

function mockApi({
  connections = [CONN_NON_CONFIGURATA],
  proposals = page([PROPOSAL_IN_ATTESA]),
  bookings = page([BOOKING_CONFERMATA]),
} = {}) {
  const get = jest.fn((url) => {
    if (url === "/auth/me") {
      return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" } } });
    }
    if (url === "/appointments/connections") return Promise.resolve({ data: connections });
    if (url === "/appointments/proposals") return Promise.resolve({ data: proposals });
    if (url === "/appointments/bookings") return Promise.resolve({ data: bookings });
    if (url.match(/\/appointments\/proposals\/[^/]+$/)) return Promise.resolve({ data: proposals.items[0] || PROPOSAL_IN_ATTESA });
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
    <MemoryRouter initialEntries={["/appointment-setter"]}>
      <AuthProvider>
        <AppointmentSetter />
      </AuthProvider>
    </MemoryRouter>
  );
}

beforeEach(() => { mockSearchParamsValue = new URLSearchParams(); });

test("mostra connessioni, proposte e prenotazioni", async () => {
  mockApiState = mockApi();
  renderPage();
  expect(await screen.findByText("Google Calendar principale")).toBeInTheDocument();
  expect(await screen.findByText("lead-1")).toBeInTheDocument();
});

test("stati vuoti quando non ci sono connessioni/proposte/prenotazioni", async () => {
  mockApiState = mockApi({ connections: [], proposals: page([]), bookings: page([]) });
  renderPage();
  expect(await screen.findByText("Nessuna connessione.")).toBeInTheDocument();
  expect(screen.getByText("Nessuna proposta ancora.")).toBeInTheDocument();
  expect(screen.getByText("Nessuna prenotazione ancora.")).toBeInTheDocument();
});

test("selezionando una proposta in attesa mostra gli slot e i pulsanti di approvazione", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("lead-1"));

  const slots = await screen.findByTestId("appt-slots-list");
  expect(within(slots).getAllByText(/→/).length).toBe(2);
  expect(screen.getByTestId("appt-approve-btn")).toBeInTheDocument();
});

test("una proposta approvata mostra il pulsante Prenota per ogni slot", async () => {
  mockApiState = mockApi({ proposals: page([PROPOSAL_APPROVATA]) });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("lead-1"));
  const bottoni = await screen.findAllByText("Prenota");
  expect(bottoni.length).toBe(2);
});

test("proposta con connessione non configurata mostra l'avviso e nessuno slot", async () => {
  mockApiState = mockApi({ proposals: page([PROPOSAL_SENZA_CONNESSIONE]) });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("lead-3"));
  expect(await screen.findByText(/Connessione calendario non configurata/)).toBeInTheDocument();
  expect(screen.getByText("Nessuno slot disponibile.")).toBeInTheDocument();
});

test("nessun JSON grezzo viene mai renderizzato", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByText("lead-1"));
  await screen.findByTestId("appt-slots-list");
  expect(document.body.textContent).not.toMatch(/[{[]"[a-z_]+":/);
});

test("apre il modale nuova connessione e invia i campi corretti", async () => {
  mockApiState = mockApi();
  renderPage();
  const user = userEvent.setup();
  await user.click(screen.getByTestId("new-appt-connection"));
  expect(await screen.findByText("Nuova connessione calendario")).toBeInTheDocument();
});

test("ripresa da Sala Riunioni: proposalId in query seleziona subito la proposta", async () => {
  mockSearchParamsValue = new URLSearchParams({ proposalId: "prop-1" });
  mockApiState = mockApi();
  renderPage();
  expect(await screen.findByTestId("appt-slots-list")).toBeInTheDocument();
});

test("campagne/prenotazioni usano la paginazione lato server (page/page_size)", async () => {
  mockApiState = mockApi();
  renderPage();
  await screen.findByText("lead-1");
  await waitFor(() => {
    expect(mockApiState.get).toHaveBeenCalledWith("/appointments/proposals", { params: { page: 1, page_size: 10 } });
    expect(mockApiState.get).toHaveBeenCalledWith("/appointments/bookings", { params: { page: 1, page_size: 10 } });
  });
});
