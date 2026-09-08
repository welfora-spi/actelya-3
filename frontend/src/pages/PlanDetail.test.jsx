import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import PlanDetail from "@/pages/PlanDetail";
import { AuthProvider } from "@/context/AuthContext";
import api from "@/lib/api";

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

jest.mock("@/lib/api", () => {
  const get = jest.fn();
  const post = jest.fn(() => Promise.resolve({ data: {} }));
  return { __esModule: true, default: { get, post }, formatApiError: (d) => d || "" };
});

const ADMIN_USER = { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" };

const PLAN_DATA = {
  plan: { id: "plan-1", objective_type: "CAMPAGNA", plan_status: "IN_ATTESA_APPROVAZIONE", version: 1, active_agent_ids: [] },
  tasks: [],
  execution: null,
  mode: { ai_real_mode: false, real_ready: false },
};

function renderPlanDetail(planId = "plan-1") {
  return render(
    <MemoryRouter initialEntries={[`/piani/${planId}`]}>
      <AuthProvider>
        <Routes>
          <Route path="/piani/:id" element={<PlanDetail />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

function mockAlways(status) {
  api.get.mockImplementation((url) => {
    if (url === "/auth/me") return Promise.resolve({ data: { user: ADMIN_USER } });
    return Promise.reject({ response: status != null ? { status } : undefined, message: "Network Error" });
  });
}

beforeEach(() => {
  api.get.mockReset();
  api.post.mockClear();
});

describe("PlanDetail — stati espliciti di caricamento", () => {
  it("404: mostra 'piano inesistente', mai un Caricamento... infinito, e ferma il polling", async () => {
    mockAlways(404);
    const clearIntervalSpy = jest.spyOn(global, "clearInterval");
    renderPlanDetail();

    expect(await screen.findByTestId("plan-not-found")).toBeInTheDocument();
    expect(screen.queryByTestId("plan-state-loading")).not.toBeInTheDocument();
    expect(screen.getByTestId("plan-state-back")).toBeInTheDocument();
    expect(screen.queryByTestId("plan-state-retry")).not.toBeInTheDocument(); // non riprovabile
    expect(clearIntervalSpy).toHaveBeenCalled();

    clearIntervalSpy.mockRestore();
  });

  it("403: mostra 'permessi negati' e ferma il polling, nessun Riprova", async () => {
    mockAlways(403);
    const clearIntervalSpy = jest.spyOn(global, "clearInterval");
    renderPlanDetail();

    expect(await screen.findByTestId("plan-forbidden")).toBeInTheDocument();
    expect(screen.getByTestId("plan-state-back")).toBeInTheDocument();
    expect(screen.queryByTestId("plan-state-retry")).not.toBeInTheDocument();
    expect(clearIntervalSpy).toHaveBeenCalled();

    clearIntervalSpy.mockRestore();
  });

  it("errore temporaneo di rete sul primo caricamento: mostra Riprova, mai bloccato su Caricamento...", async () => {
    mockAlways(undefined); // nessun response.status -> errore di rete/transitorio
    renderPlanDetail();

    expect(await screen.findByTestId("plan-transient-error")).toBeInTheDocument();
    expect(screen.getByTestId("plan-state-retry")).toBeInTheDocument();
  });

  it("errore server definitivo (422) diverso da 401/403/404: nessun retry automatico, Riprova disponibile", async () => {
    mockAlways(422);
    const clearIntervalSpy = jest.spyOn(global, "clearInterval");
    renderPlanDetail();

    expect(await screen.findByTestId("plan-fatal-error")).toBeInTheDocument();
    expect(screen.getByTestId("plan-state-retry")).toBeInTheDocument();
    expect(clearIntervalSpy).toHaveBeenCalled();

    clearIntervalSpy.mockRestore();
  });

  it("successo dopo Riprova: da errore transitorio a piano caricato", async () => {
    let attempt = 0;
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") return Promise.resolve({ data: { user: ADMIN_USER } });
      if (url === "/m2/plans/plan-1") attempt += 1;
      if (attempt === 1) return Promise.reject({ response: undefined, message: "Network Error" });
      if (url === "/m2/plans/plan-1") return Promise.resolve({ data: PLAN_DATA });
      if (url === "/m2/plans/plan-1/deliverables") return Promise.resolve({ data: { deliverables: [] } });
      if (url === "/m2/plans/plan-1/reviews") return Promise.resolve({ data: { reviews: [] } });
      return Promise.reject({ response: { status: 404 } });
    });

    const user = userEvent.setup();
    renderPlanDetail();

    await screen.findByTestId("plan-transient-error");
    await user.click(screen.getByTestId("plan-state-retry"));

    expect(await screen.findByTestId("plan-detail")).toBeInTheDocument();
    expect(screen.getByTestId("plan-detail-status")).toBeInTheDocument();
  });

  it("piano valido: nessuno stato di errore, dati mostrati normalmente", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") return Promise.resolve({ data: { user: ADMIN_USER } });
      if (url === "/m2/plans/plan-1") return Promise.resolve({ data: PLAN_DATA });
      if (url === "/m2/plans/plan-1/deliverables") return Promise.resolve({ data: { deliverables: [] } });
      if (url === "/m2/plans/plan-1/reviews") return Promise.resolve({ data: { reviews: [] } });
      return Promise.reject({ response: { status: 404 } });
    });
    renderPlanDetail();

    expect(await screen.findByTestId("plan-detail")).toBeInTheDocument();
    expect(screen.queryByTestId("plan-not-found")).not.toBeInTheDocument();
    expect(screen.queryByTestId("plan-session-expired")).not.toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/m2/plans/plan-1"));
  });
});
