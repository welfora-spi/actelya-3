import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Layout from "@/components/Layout";
import { AuthProvider } from "@/context/AuthContext";
import { SystemProvider } from "@/context/SystemContext";

// Correzione regressione (vs ACTELYA 2): "Piani (M2)" deve restare
// raggiungibile in navigazione per APPROVATORE/OPERATORE (non solo ADMIN),
// mentre le pagine di sola supervisione tecnica (es. Operatori AI) restano
// riservate ad ADMIN.

function mockApiFor(role) {
  const get = jest.fn((url) => {
    if (url === "/auth/me") {
      return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role, organization_id: "org-1" } } });
    }
    if (url === "/settings") return Promise.resolve({ data: {} });
    if (url === "/budget") return Promise.resolve({ data: { general_limit: 100, residual: 80 } });
    return Promise.reject({ response: { status: 404 } });
  });
  const post = jest.fn(() => Promise.resolve({ data: {} }));
  return { get, post };
}

let mockApiState = mockApiFor("ADMIN");
jest.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a) => mockApiState.get(...a), post: (...a) => mockApiState.post(...a) },
  formatApiError: (d) => d || "",
}));

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <AuthProvider>
        <SystemProvider>
          <Layout><div>contenuto</div></Layout>
        </SystemProvider>
      </AuthProvider>
    </MemoryRouter>
  );
}

test("ADMIN vede sia 'Piani (M2)' sia le pagine di sola supervisione tecnica", async () => {
  mockApiState = mockApiFor("ADMIN");
  renderLayout();
  expect(await screen.findByTestId("nav-piani")).toBeInTheDocument();
  expect(screen.getByTestId("nav-operatori")).toBeInTheDocument();
});

test("APPROVATORE vede 'Piani (M2)' ma non le pagine di sola supervisione tecnica", async () => {
  mockApiState = mockApiFor("APPROVATORE");
  renderLayout();
  expect(await screen.findByTestId("nav-piani")).toBeInTheDocument();
  expect(screen.queryByTestId("nav-operatori")).not.toBeInTheDocument();
  expect(screen.queryByTestId("nav-lead-generation")).not.toBeInTheDocument();
});

test("OPERATORE vede 'Piani (M2)' ma non le pagine di sola supervisione tecnica", async () => {
  mockApiState = mockApiFor("OPERATORE");
  renderLayout();
  expect(await screen.findByTestId("nav-piani")).toBeInTheDocument();
  expect(screen.queryByTestId("nav-operatori")).not.toBeInTheDocument();
  expect(screen.queryByTestId("nav-reel")).not.toBeInTheDocument();
});

test("SOLA_LETTURA non vede 'Piani (M2)' (ruolo non operativo)", async () => {
  mockApiState = mockApiFor("SOLA_LETTURA");
  renderLayout();
  await waitFor(() => expect(screen.getByText("a@b.it")).toBeInTheDocument());
  expect(screen.queryByTestId("nav-piani")).not.toBeInTheDocument();
});
