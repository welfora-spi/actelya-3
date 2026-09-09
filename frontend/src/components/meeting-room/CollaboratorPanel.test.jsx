import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import api from "@/lib/api";
import CollaboratorPanel from "@/components/meeting-room/CollaboratorPanel";

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("@/lib/api", () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() }, formatApiError: (d) => d || "" }));

function renderAsRole(role, summary) {
  api.get.mockImplementation((url) => {
    if (url === "/auth/me") return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role, organization_id: "org-1" } } });
    return Promise.reject({ response: { status: 404 } });
  });
  return render(
    <MemoryRouter>
      <AuthProvider>
        <CollaboratorPanel collaborator={null} summary={summary} planId="plan-1" />
      </AuthProvider>
    </MemoryRouter>
  );
}

const SUMMARY_BASE = { collaboratorsCount: 3, activeCount: 1, pendingApprovalCount: 0, tasksCount: 1, planStatus: "IN_ATTESA_APPROVAZIONE" };

describe("CollaboratorPanel — tetto di spesa visibile prima dell'approvazione", () => {
  it("mostra il tetto reale (mai solo la stima) accanto al pulsante di approvazione", async () => {
    renderAsRole("ADMIN", { ...SUMMARY_BASE, estimatedCost: 0.03, approvedCap: 0.03 });
    const panel = await screen.findByTestId("collaborator-panel-empty");
    expect(panel).toHaveTextContent("Costo stimato");
    expect(panel).toHaveTextContent("$0.03000");
    expect(panel).toHaveTextContent("Tetto che autorizzi");
    expect(screen.queryByTestId("zero-cap-warning")).not.toBeInTheDocument();
    expect(await screen.findByTestId("approve-and-start-plan")).toBeInTheDocument();
  });

  it("un tetto a $0 mostra un avviso esplicito accanto al pulsante di approvazione", async () => {
    renderAsRole("ADMIN", { ...SUMMARY_BASE, estimatedCost: 0, approvedCap: 0 });
    await screen.findByTestId("collaborator-panel-empty");
    expect(await screen.findByTestId("zero-cap-warning")).toBeInTheDocument();
    expect(await screen.findByTestId("approve-and-start-plan")).toBeInTheDocument();
  });

  it("un OPERATORE vede il tetto ma non il pulsante di approvazione (mai un 403 silenzioso)", async () => {
    renderAsRole("OPERATORE", { ...SUMMARY_BASE, estimatedCost: 0.03, approvedCap: 0.03 });
    const panel = await screen.findByTestId("collaborator-panel-empty");
    expect(panel).toHaveTextContent("Tetto che autorizzi");
    expect(screen.queryByTestId("approve-and-start-plan")).not.toBeInTheDocument();
    expect(panel).toHaveTextContent("in attesa di approvazione");
  });
});
