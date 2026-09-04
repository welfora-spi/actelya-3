import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Register from "@/pages/Register";
import { AuthProvider } from "@/context/AuthContext";
import { SystemProvider } from "@/context/SystemContext";
import api from "@/lib/api";

jest.mock("@/lib/api", () => {
  const get = jest.fn((url) => {
    if (url === "/auth/me") return Promise.resolve({ data: { user: null } });
    return Promise.resolve({ data: {} });
  });
  const post = jest.fn(() => Promise.resolve({ data: {} }));
  return { __esModule: true, default: { get, post }, formatApiError: (d) => d || "" };
});

const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({
  ...jest.requireActual("react-router-dom"),
  useNavigate: () => mockNavigate,
}));

function renderRegister() {
  return render(
    <MemoryRouter initialEntries={["/registrati"]}>
      <AuthProvider>
        <SystemProvider>
          <Register />
        </SystemProvider>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("Register", () => {
  beforeEach(() => jest.clearAllMocks());

  it("submits the onboarding fields and redirects to /onboarding", async () => {
    api.post.mockImplementation((url) => {
      if (url === "/tenant/register") {
        return Promise.resolve({
          data: {
            user: { id: "u1", email: "mario@panetteria.it", role: "ADMIN", organization_id: "org-1" },
            access_token: "tok", organization_id: "org-1",
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    renderRegister();
    const user = userEvent.setup();

    await user.type(screen.getByTestId("reg-company"), "Panetteria Rossi");
    await user.type(screen.getByTestId("reg-sector"), "Alimentare");
    await user.type(screen.getByTestId("reg-website"), "https://panetteria.it");
    await user.type(screen.getByTestId("reg-social"), "https://instagram.com/panetteria, https://facebook.com/panetteria");
    await user.type(screen.getByTestId("reg-goal"), "Vendere di più online");
    await user.type(screen.getByTestId("reg-firstname"), "Mario");
    await user.type(screen.getByTestId("reg-lastname"), "Rossi");
    await user.type(screen.getByTestId("reg-email"), "mario@panetteria.it");
    await user.type(screen.getByTestId("reg-password"), "PanettoneBuono!2026");
    await user.click(screen.getByTestId("reg-submit"));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/tenant/register", expect.objectContaining({
      company_name: "Panetteria Rossi",
      social_links: ["https://instagram.com/panetteria", "https://facebook.com/panetteria"],
      email: "mario@panetteria.it",
    })));
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/onboarding"));
  });

  it("shows the API error message when registration fails", async () => {
    api.post.mockImplementation((url) => {
      if (url === "/tenant/register") {
        return Promise.reject({ response: { data: { detail: "Email già registrata" } } });
      }
      return Promise.resolve({ data: {} });
    });

    renderRegister();
    const user = userEvent.setup();
    await user.type(screen.getByTestId("reg-company"), "Azienda");
    await user.type(screen.getByTestId("reg-firstname"), "A");
    await user.type(screen.getByTestId("reg-lastname"), "B");
    await user.type(screen.getByTestId("reg-email"), "a@b.it");
    await user.type(screen.getByTestId("reg-password"), "Password123!");
    await user.click(screen.getByTestId("reg-submit"));

    expect(await screen.findByTestId("reg-error")).toHaveTextContent("Email già registrata");
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
