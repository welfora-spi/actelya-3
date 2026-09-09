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

describe("PlanDetail — deliverable 'content_item' leggibile, mai solo JSON grezzo", () => {
  const CONTENT_ITEM_DELIV = {
    id: "deliv-1", deliverable_type: "content_item", status: "COMPLETATO_CON_AVVISI",
    mode: "REALE", version: 1, is_current: true, valid: true, warnings: [],
    content: {
      content_item_ids: ["c1", "c2"], requested_quantity: 2, produced_count: 2, contested_ids: ["c1"],
      items: [
        { content_item_id: "c1", content_type: "post_social", status: "IN_ATTESA_APPROVAZIONE",
          content: { titolo: "Titolo 1", corpo: "Corpo del primo post", cta: "Vai", hashtags: ["#a"], varianti: ["Var A"] },
          semantic_check: { status: "CONTESTATO", affermazioni_contestate: [{ categoria: "x", campo: "corpo", frase: "affidabile", parola_chiave: "affidabile" }] } },
        { content_item_id: "c2", content_type: "post_social", status: "IN_ATTESA_APPROVAZIONE",
          content: { titolo: "Titolo 2", corpo: "Corpo del secondo post", cta: "Vai", hashtags: [], varianti: [] },
          semantic_check: { status: "OK", affermazioni_contestate: [] } },
      ],
    },
  };

  function mockPlanWithDeliverable() {
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") return Promise.resolve({ data: { user: ADMIN_USER } });
      if (url === "/m2/plans/plan-1") return Promise.resolve({ data: PLAN_DATA });
      if (url === "/m2/plans/plan-1/deliverables") return Promise.resolve({ data: { deliverables: [CONTENT_ITEM_DELIV] } });
      if (url === "/m2/plans/plan-1/reviews") return Promise.resolve({ data: { reviews: [] } });
      return Promise.reject({ response: { status: 404 } });
    });
  }

  it("mostra i due contenuti leggibili (titolo/corpo/CTA), la contestazione e mai JSON grezzo come vista principale", async () => {
    mockPlanWithDeliverable();
    const user = userEvent.setup();
    renderPlanDetail();

    await screen.findByTestId("plan-detail");
    await user.click(screen.getByTestId("deliv-toggle-content_item"));

    expect(await screen.findByTestId("content-item-c1")).toBeInTheDocument();
    expect(screen.getByTestId("content-item-c2")).toBeInTheDocument();
    expect(screen.getByText("Corpo del primo post")).toBeInTheDocument();
    expect(screen.getByText("Corpo del secondo post")).toBeInTheDocument();
    expect(screen.getByTestId("content-item-contested-notice")).toHaveTextContent("affidabile");
    // varianti separate, non un post aggiuntivo
    expect(screen.getByTestId("content-item-variants")).toBeInTheDocument();
    // il JSON resta collassato/opzionale, non la vista principale
    const details = document.querySelector("details");
    expect(details).toBeInTheDocument();
    expect(details.open).toBeFalsy();
  });

  it("dopo una nuova lettura (refresh), gli stessi due contenuti restano identici, nessuna duplicazione", async () => {
    mockPlanWithDeliverable();
    const user = userEvent.setup();
    renderPlanDetail();
    await screen.findByTestId("plan-detail");
    await user.click(screen.getByTestId("deliv-toggle-content_item"));
    await screen.findByTestId("content-item-c1");

    // Simula il refresh del polling: stessa risposta riletta di nuovo.
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/m2/plans/plan-1/deliverables"));
    expect(screen.getAllByTestId("content-item-c1")).toHaveLength(1);
    expect(screen.getAllByTestId("content-item-c2")).toHaveLength(1);
  });
});

describe("PlanDetail — preventivo visibile PRIMA dell'approvazione (mai solo dopo l'esecuzione)", () => {
  function mockPlanWithEstimate(estimate, approvedCap) {
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") return Promise.resolve({ data: { user: ADMIN_USER } });
      if (url === "/m2/plans/plan-1") return Promise.resolve({
        data: {
          plan: { id: "plan-1", objective_type: "CAMPAGNA", plan_status: "IN_ATTESA_APPROVAZIONE", version: 1,
                 active_agent_ids: [], estimate, approved_cap: approvedCap },
          tasks: [{ id: "task-1", seq: 1, name: "Content Creator — produzione contenuti", deliverable_type: "content_item",
                   agent_id: "content-creator", attempt: 0, task_status: "IN_ATTESA_APPROVAZIONE", approved: false,
                   depends_on: [], cost: 0, inputs: { cost: approvedCap, requested_quantity: 3 } }],
          execution: null, mode: { ai_real_mode: false, real_ready: false },
        },
      });
      if (url === "/m2/plans/plan-1/deliverables") return Promise.resolve({ data: { deliverables: [] } });
      if (url === "/m2/plans/plan-1/reviews") return Promise.resolve({ data: { reviews: [] } });
      return Promise.reject({ response: { status: 404 } });
    });
  }

  it("mostra stima e tetto reali (mai $0.00000 quando il piano ne ha uno) prima di qualunque esecuzione", async () => {
    mockPlanWithEstimate(
      { cost_min: 0.03, cost_probable: 0.03, cost_max: 0.03, approvable_cap: 0.03,
       calls_estimated: 3, external_tools_cost: 0.03, safety_margin: 0.2, currency: "USD" },
      0.03,
    );
    renderPlanDetail();
    await screen.findByTestId("plan-detail");
    const preventivo = await screen.findByTestId("plan-preventivo");
    expect(preventivo.querySelector('[data-testid="plan-estimate-probable"]')).toHaveTextContent("$0.03000");
    expect(preventivo.querySelector('[data-testid="plan-approved-cap"]')).toHaveTextContent("$0.03000");
    expect(screen.queryByTestId("plan-zero-cap-warning")).not.toBeInTheDocument();
    // quantita' e stima per-task leggibili accanto al task, non solo nel riepilogo
    expect(screen.getByTestId("task-cost-estimate-1")).toHaveTextContent("$0.03000");
    expect(screen.getByText(/quantità 3/)).toBeInTheDocument();
  });

  it("un tetto a $0 mostra un avviso esplicito invece di un preventivo silenzioso", async () => {
    mockPlanWithEstimate(
      { cost_min: 0, cost_probable: 0, cost_max: 0, approvable_cap: 0,
       calls_estimated: 0, external_tools_cost: 0, safety_margin: 0.2, currency: "USD" },
      0,
    );
    renderPlanDetail();
    await screen.findByTestId("plan-detail");
    await screen.findByTestId("plan-preventivo");
    expect(await screen.findByTestId("plan-zero-cap-warning")).toBeInTheDocument();
  });

  it("stima storica del piano ($0) non aggiornata: mostra spiegazione esplicita e stima ricostruita dai task, mai un $0.03/$0.03 silenzioso", async () => {
    // Stesso scenario reale di plan-7340ce4c511a406db485: estimate.cost_probable
    // rimasto a 0 dalla creazione del piano, approved_cap incrementato a 0.03
    // quando il task content_item e' stato collegato (brain/service.py) —
    // mai far apparire i due numeri come se coincidessero senza spiegazione.
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") return Promise.resolve({ data: { user: ADMIN_USER } });
      if (url === "/m2/plans/plan-1") return Promise.resolve({
        data: {
          plan: { id: "plan-1", objective_type: "CAMPAGNA", plan_status: "IN_ATTESA_APPROVAZIONE", version: 1,
                 active_agent_ids: [], approved_cap: 0.03,
                 estimate: { cost_min: 0, cost_probable: 0, cost_max: 0, approvable_cap: 0,
                            calls_estimated: 0, external_tools_cost: 0, safety_margin: 0.2, currency: "USD" } },
          tasks: [{ id: "task-1", seq: 1, name: "Content Creator — produzione contenuti", deliverable_type: "content_item",
                   agent_id: "content-creator", attempt: 0, task_status: "IN_ATTESA_APPROVAZIONE", approved: false,
                   depends_on: [], cost: 0, inputs: { cost: 0.03, requested_quantity: 3, deliverable_override: { mode: "REALE" } } }],
          execution: null, mode: { ai_real_mode: false, real_ready: false },
        },
      });
      if (url === "/m2/plans/plan-1/deliverables") return Promise.resolve({ data: { deliverables: [] } });
      if (url === "/m2/plans/plan-1/reviews") return Promise.resolve({ data: { reviews: [] } });
      return Promise.reject({ response: { status: 404 } });
    });
    renderPlanDetail();
    await screen.findByTestId("plan-detail");
    const preventivo = await screen.findByTestId("plan-preventivo");
    expect(preventivo.querySelector('[data-testid="plan-estimate-probable"]')).toHaveTextContent("$0.00000");
    expect(preventivo.querySelector('[data-testid="plan-approved-cap"]')).toHaveTextContent("$0.03000");
    const notice = await screen.findByTestId("plan-estimate-stale-notice");
    expect(notice).toHaveTextContent("non è stata aggiornata");
    expect(notice.querySelector('[data-testid="plan-estimate-reconstructed"]')).toHaveTextContent("$0.03000");
    // Modalità derivata dal task (deliverable_override.mode=REALE), mai "SIMULAZIONE" per difetto
    expect(screen.getByText(/modalità REALE/)).toBeInTheDocument();
  });
});

describe("PlanDetail — revisione editoriale sulle bozze 'social_content'", () => {
  const POST_0 = { hook: "Hook 1", body: "Corpo bozza 1", cta: "Scopri di più", hashtags: ["#a"], channel: "Facebook" };
  const POST_1 = { hook: "Hook 2", body: "Corpo bozza 2", cta: "Scopri di più", hashtags: ["#b"], channel: "Instagram" };
  const DECISIONE_VUOTA = { status: "IN_ATTESA_REVISIONE", decided_by: null, decided_at: null, reason: null };

  const SOCIAL_DELIV = {
    id: "deliv-social-1", deliverable_type: "social_content", status: "COMPLETATO",
    mode: "REALE", version: 1, is_current: true, valid: true,
    content: { platform: "Facebook e Instagram", posts: [POST_0, POST_1] },
    item_decisions: [
      { item_index: 0, current_version: 1, content: POST_0, source: "originale", edit_note: null, decision: DECISIONE_VUOTA, history: [] },
      { item_index: 1, current_version: 1, content: POST_1, source: "originale", edit_note: null, decision: DECISIONE_VUOTA, history: [] },
    ],
  };

  function mockPlanWithSocialDeliverable(deliv = SOCIAL_DELIV) {
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") return Promise.resolve({ data: { user: ADMIN_USER } });
      if (url === "/m2/plans/plan-1") return Promise.resolve({ data: PLAN_DATA });
      if (url === "/m2/plans/plan-1/deliverables") return Promise.resolve({ data: { deliverables: [deliv] } });
      if (url === "/m2/plans/plan-1/reviews") return Promise.resolve({ data: { reviews: [] } });
      if (url === "/m2/plans/plan-1/deliverables/deliv-social-1/items/0/edit-cost") {
        return Promise.resolve({ data: { item_index: 0, cost_probable: 0.0007, cost_max: 0.0012, currency: "USD", mode: "SIMULAZIONE" } });
      }
      return Promise.reject({ response: { status: 404 } });
    });
  }

  it("mostra le due bozze distinte (v1) con i tre pulsanti di decisione, mai JSON grezzo come vista principale", async () => {
    mockPlanWithSocialDeliverable();
    const user = userEvent.setup();
    renderPlanDetail();
    await screen.findByTestId("plan-detail");
    await user.click(screen.getByTestId("deliv-toggle-social_content"));

    expect(await screen.findByTestId("item-social_content-0")).toHaveTextContent("Corpo bozza 1");
    expect(screen.getByTestId("item-version-social_content-0")).toHaveTextContent("v1");
    expect(screen.getByTestId("item-social_content-1")).toHaveTextContent("Corpo bozza 2");
    expect(screen.getByTestId("item-approve-social_content-0")).toBeInTheDocument();
    expect(screen.getByTestId("item-reject-social_content-0")).toBeInTheDocument();
    expect(screen.getByTestId("item-request-changes-social_content-0")).toBeInTheDocument();
  });

  it("Approva invoca l'endpoint di decisione con l'indice corretto e aggiorna la vista senza rigenerare nulla", async () => {
    mockPlanWithSocialDeliverable();
    api.post.mockResolvedValue({ data: { status: "APPROVATO" } });
    const user = userEvent.setup();
    renderPlanDetail();
    await screen.findByTestId("plan-detail");
    await user.click(screen.getByTestId("deliv-toggle-social_content"));
    await screen.findByTestId("item-social_content-0");

    await user.click(screen.getByTestId("item-approve-social_content-0"));

    expect(api.post).toHaveBeenCalledWith(
      "/m2/plans/plan-1/deliverables/deliv-social-1/items/0/decision",
      { decision: "APPROVATO", reason: null }
    );
    // Nessuna chiamata di generazione/rigenerazione: solo la decisione + il ricaricamento dei dati.
    expect(api.post).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(api.get.mock.calls.filter(
      ([u]) => u === "/m2/plans/plan-1/deliverables").length).toBeGreaterThan(1));
  });

  it("Rifiuta e Richiedi modifica chiedono una motivazione obbligatoria (annullano senza motivo)", async () => {
    mockPlanWithSocialDeliverable();
    window.prompt = jest.fn();
    const user = userEvent.setup();
    renderPlanDetail();
    await screen.findByTestId("plan-detail");
    await user.click(screen.getByTestId("deliv-toggle-social_content"));
    await screen.findByTestId("item-social_content-0");

    window.prompt.mockReturnValueOnce("   "); // solo spazi: equivalente a nessun motivo
    await user.click(screen.getByTestId("item-reject-social_content-0"));
    expect(api.post).not.toHaveBeenCalled();

    window.prompt.mockReturnValueOnce("Tono non coerente con il brand.");
    await user.click(screen.getByTestId("item-reject-social_content-0"));
    expect(api.post).toHaveBeenCalledWith(
      "/m2/plans/plan-1/deliverables/deliv-social-1/items/0/decision",
      { decision: "RIFIUTATO", reason: "Tono non coerente con il brand." }
    );
  });

  it("una bozza già decisa mostra l'esito e la motivazione, senza più i pulsanti di decisione", async () => {
    const deliv = {
      ...SOCIAL_DELIV,
      item_decisions: [
        { item_index: 0, current_version: 1, content: POST_0, source: "originale", edit_note: null, history: [],
          decision: { status: "RIFIUTATO", decided_by: "revisore@spitool.it", decided_at: "2026-09-09T18:00:00+00:00",
                     reason: "Affermazione non supportata dalle fonti." } },
        SOCIAL_DELIV.item_decisions[1],
      ],
    };
    mockPlanWithSocialDeliverable(deliv);
    const user = userEvent.setup();
    renderPlanDetail();
    await screen.findByTestId("plan-detail");
    await user.click(screen.getByTestId("deliv-toggle-social_content"));

    expect(await screen.findByTestId("item-reason-social_content-0")).toHaveTextContent(
      "Affermazione non supportata dalle fonti.");
    expect(screen.getByTestId("item-status-social_content-0")).toHaveTextContent("RIFIUTATO");
    expect(screen.queryByTestId("item-approve-social_content-0")).not.toBeInTheDocument();
    expect(screen.queryByTestId("item-reject-social_content-0")).not.toBeInTheDocument();
    // La bozza NON decisa nello stesso deliverable resta invece decidibile.
    expect(screen.getByTestId("item-approve-social_content-1")).toBeInTheDocument();
  });

  it("una richiesta di modifica resta visibile come lavoro da svolgere, con stima costo prima della conferma", async () => {
    const deliv = {
      ...SOCIAL_DELIV,
      item_decisions: [
        { item_index: 0, current_version: 1, content: POST_0, source: "originale", edit_note: null, history: [],
          decision: { status: "MODIFICA_RICHIESTA", decided_by: "revisore@spitool.it", decided_at: "2026-09-09T18:00:00+00:00",
                     reason: "Rendere il tono più diretto." } },
        SOCIAL_DELIV.item_decisions[1],
      ],
    };
    mockPlanWithSocialDeliverable(deliv);
    const user = userEvent.setup();
    renderPlanDetail();
    await screen.findByTestId("plan-detail");
    await user.click(screen.getByTestId("deliv-toggle-social_content"));

    expect(await screen.findByTestId("item-edit-pending-social_content-0")).toHaveTextContent("Lavoro ancora da svolgere");
    expect(screen.queryByTestId("item-apply-edit-social_content-0")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("item-preview-edit-social_content-0"));
    expect(await screen.findByTestId("item-edit-cost-social_content-0")).toHaveTextContent("0.00120");
    expect(screen.getByTestId("item-apply-edit-social_content-0")).toBeInTheDocument();
  });

  it("Applica modifica chiede conferma esplicita e invia confirm:true, senza toccare le altre bozze", async () => {
    const deliv = {
      ...SOCIAL_DELIV,
      item_decisions: [
        { item_index: 0, current_version: 1, content: POST_0, source: "originale", edit_note: null, history: [],
          decision: { status: "MODIFICA_RICHIESTA", decided_by: "r@x.it", decided_at: "2026-09-09T18:00:00+00:00", reason: "Più diretto." } },
        SOCIAL_DELIV.item_decisions[1],
      ],
    };
    mockPlanWithSocialDeliverable(deliv);
    api.post.mockResolvedValue({ data: { version: 2, mode: "SIMULAZIONE" } });
    window.confirm = jest.fn(() => true);
    const user = userEvent.setup();
    renderPlanDetail();
    await screen.findByTestId("plan-detail");
    await user.click(screen.getByTestId("deliv-toggle-social_content"));
    await user.click(screen.getByTestId("item-preview-edit-social_content-0"));
    await screen.findByTestId("item-edit-cost-social_content-0");

    await user.click(screen.getByTestId("item-apply-edit-social_content-0"));

    expect(window.confirm).toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledWith(
      "/m2/plans/plan-1/deliverables/deliv-social-1/items/0/apply-edit", { confirm: true });
    // Nessuna azione sulla bozza 1 (non coinvolta).
    expect(api.post).not.toHaveBeenCalledWith(expect.stringContaining("items/1"), expect.anything());
  });

  it("lo storico mostra le versioni precedenti con la loro decisione, senza nasconderle", async () => {
    const deliv = {
      ...SOCIAL_DELIV,
      item_decisions: [
        {
          item_index: 0, current_version: 2, content: { ...POST_0, body: "Corpo bozza 1 (rivisto)" },
          source: "modifica_editoriale", edit_note: "Più diretto.",
          decision: { status: "IN_ATTESA_REVISIONE", decided_by: null, decided_at: null, reason: null },
          history: [{
            version: 1, content: POST_0, source: "originale", edit_note: null,
            decision: { status: "MODIFICA_RICHIESTA", decided_by: "r@x.it", decided_at: "2026-09-09T18:00:00+00:00", reason: "Più diretto." },
          }],
        },
        SOCIAL_DELIV.item_decisions[1],
      ],
    };
    mockPlanWithSocialDeliverable(deliv);
    const user = userEvent.setup();
    renderPlanDetail();
    await screen.findByTestId("plan-detail");
    await user.click(screen.getByTestId("deliv-toggle-social_content"));

    expect(await screen.findByTestId("item-social_content-0")).toHaveTextContent("Corpo bozza 1 (rivisto)");
    expect(screen.getByTestId("item-version-social_content-0")).toHaveTextContent("v2");
    await user.click(screen.getByTestId("item-history-toggle-social_content-0"));
    const storico = await screen.findByTestId("item-history-social_content-0");
    expect(storico).toHaveTextContent("Corpo bozza 1");
    expect(storico).toHaveTextContent("MODIFICA_RICHIESTA");
  });
});
