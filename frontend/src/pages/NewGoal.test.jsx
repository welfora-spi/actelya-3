import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import NewGoal from "@/pages/NewGoal";
import { AuthProvider } from "@/context/AuthContext";
import api from "@/lib/api";

jest.mock("sonner", () => ({
  toast: { info: jest.fn(), warning: jest.fn(), success: jest.fn(), error: jest.fn() },
}));

jest.mock("@/lib/api", () => {
  const get = jest.fn((url) => {
    if (url === "/auth/me") {
      return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" } } });
    }
    return Promise.reject({ response: { status: 404 } });
  });
  const post = jest.fn(() => Promise.resolve({ data: {} }));
  return { __esModule: true, default: { get, post }, formatApiError: (d) => d || "" };
});

const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({
  ...jest.requireActual("react-router-dom"),
  useNavigate: () => mockNavigate,
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/nuovo-obiettivo"]}>
      <AuthProvider>
        <NewGoal />
      </AuthProvider>
    </MemoryRouter>
  );
}

const PIANO_READY_REALE = {
  status: "READY",
  session_id: "session-1",
  requires_clarification: false,
  activeAgentIds: ["resp-marketing", "social-media-manager"],
  selected_agents: [
    { agent_id: "resp-marketing", reason: "Serve una strategia di posizionamento" },
    { agent_id: "social-media-manager", reason: "Richiesta esplicita di post" },
  ],
  risk_flags: [],
  plan: { id: "plan-1", objective_type: "CAMPAGNA" },
  tasks: [
    { id: "t1", name: "marketing_strategy", deliverable_type: "marketing_strategy", depends_on: [],
      llm_priority: "ALTA", llm_deadline: "2026-12-01" },
    { id: "t2", name: "social_content", deliverable_type: "social_content", depends_on: ["t1"] },
  ],
  llm_understanding: {
    mode: "REALE", motivo: "Proposta ricevuta e validata.",
    provider_effettivo: "openai", modello_effettivo: "gpt-4o", providers_tried: [],
  },
  normalized_plan: {
    origine: "LLM", provider_effettivo: "openai", modello_effettivo: "gpt-4o",
    priorita: "ALTA", urgenza: "MEDIA", scadenza: "2026-12-01",
    budget_totale: 2000, budget_allocato: 1800,
    allocazioni_budget: [{ etichetta: "social", importo: 1000 }, { etichetta: "ads", importo: 800 }],
    budget_residuo_operativo: 45.5, budget_status: "OK", richiede_chiarimento_budget: false,
    pubblico: "famiglie e lavoratori della zona", canali: ["Instagram", "Facebook"],
    capability_validate: ["strategy", "social"], capability_extra_scartate: [],
    task_proposti_validati: [], kpi: ["engagement", "prenotazioni"],
    rischi_valutati: [{ categoria: "spesa", severita: "MEDIA", azione: "APPROVAL", motivo: "campagna a pagamento" }],
    azione_rischio_aggregata: "APPROVAL", domande_aggiuntive: [],
    assunzioni: ["pubblico gia' noto dal Fact Ledger"], approvazioni_necessarie: ["pubblicazione post"],
    strategia_proposta: "Campagna locale mirata a famiglie e lavoratori", confidence: 0.82,
    correzioni: [{ tipo: "capability_scartata", dettaglio: "'leadgen' proposta ma non pertinente: scartata." }],
  },
};

const PIANO_READY_DETERMINISTICO = {
  ...PIANO_READY_REALE,
  llm_understanding: { mode: "DETERMINISTICO", motivo: "Modalita' AI REALE non attiva per l'organizzazione.",
                       provider_effettivo: null, modello_effettivo: null, providers_tried: [] },
  normalized_plan: {
    ...PIANO_READY_REALE.normalized_plan, origine: "DETERMINISTICO", provider_effettivo: null, modello_effettivo: null,
    budget_totale: null, budget_allocato: null, allocazioni_budget: [], budget_residuo_operativo: null,
    budget_status: "NON_APPLICABILE", rischi_valutati: [], azione_rischio_aggregata: "NONE",
    assunzioni: [], approvazioni_necessarie: [], kpi: [], correzioni: [], strategia_proposta: "",
  },
};

describe("NewGoal", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") {
        return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" } } });
      }
      return Promise.reject({ response: { status: 404 } });
    });
  });

  it("mostra la modalita' LLM reale con provider e modello, e i campi del piano normalizzato", async () => {
    api.post.mockResolvedValue({ data: PIANO_READY_REALE });
    renderPage();
    const user = userEvent.setup();

    await user.type(screen.getByTestId("goal-input"), "Prepara una campagna per il Bakery & Coffee");
    await user.click(screen.getByTestId("goal-classify"));

    expect(await screen.findByTestId("goal-status")).toHaveTextContent("READY");

    const llmBadge = screen.getByTestId("llm-mode-badge");
    expect(llmBadge).toHaveTextContent("REALE");
    expect(llmBadge).toHaveTextContent("openai");
    expect(llmBadge).toHaveTextContent("gpt-4o");

    const insights = screen.getByTestId("plan-insights");
    expect(insights).toHaveTextContent("ALTA"); // priorita'
    expect(insights).toHaveTextContent("MEDIA"); // urgenza
    expect(insights).toHaveTextContent("2026-12-01"); // scadenza
    expect(insights).toHaveTextContent("2000"); // budget totale
    expect(insights).toHaveTextContent("allocato: 1800");
    expect(insights).toHaveTextContent("residuo operativo: 45.5");
    expect(insights).toHaveTextContent("social: 1000");
    expect(insights).toHaveTextContent("ads: 800");
    expect(insights).toHaveTextContent("famiglie e lavoratori della zona"); // pubblico
    expect(insights).toHaveTextContent("Instagram");
    expect(insights).toHaveTextContent("Facebook");
    expect(insights).toHaveTextContent("Campagna locale mirata a famiglie e lavoratori"); // strategia
    expect(insights).toHaveTextContent("spesa");
    expect(insights).toHaveTextContent("APPROVAL");
    expect(insights).toHaveTextContent("engagement");
    expect(insights).toHaveTextContent("prenotazioni");
    expect(insights).toHaveTextContent("pubblicazione post"); // approvazioni
    expect(insights).toHaveTextContent("pubblico gia' noto dal Fact Ledger"); // assunzioni
    expect(insights).toHaveTextContent("leadgen"); // correzioni

    const taskList = screen.getByTestId("tasks-list");
    expect(taskList).toHaveTextContent("marketing_strategy");
    expect(taskList).toHaveTextContent("social_content");
    expect(taskList).toHaveTextContent("ALTA");
    expect(taskList).toHaveTextContent("2026-12-01");
    expect(taskList).toHaveTextContent("dipende da 1 task");
  });

  it("mostra il fallback deterministico e il motivo quando l'LLM non e' disponibile", async () => {
    api.post.mockResolvedValue({ data: PIANO_READY_DETERMINISTICO });
    renderPage();
    const user = userEvent.setup();

    await user.type(screen.getByTestId("goal-input"), "Prepara una campagna");
    await user.click(screen.getByTestId("goal-classify"));

    await screen.findByTestId("goal-status");
    const llmBadge = screen.getByTestId("llm-mode-badge");
    expect(llmBadge).toHaveTextContent("deterministica");
    expect(llmBadge).toHaveTextContent("Modalita' AI REALE non attiva");

    // Budget NON_APPLICABILE: la sezione budget non deve comparire.
    const insights = screen.getByTestId("plan-insights");
    expect(insights).not.toHaveTextContent("NON_APPLICABILE");
  });

  it("non renderizza MAI JSON grezzo nel pannello di riepilogo", async () => {
    api.post.mockResolvedValue({ data: PIANO_READY_REALE });
    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId("goal-input"), "Prepara una campagna");
    await user.click(screen.getByTestId("goal-classify"));

    const result = await screen.findByTestId("goal-result");
    expect(result.textContent).not.toMatch(/[{[]"[a-z_]+":/);
  });

  it("gestisce campi opzionali assenti senza errori (nessun rischio, nessun budget, nessun task)", async () => {
    api.post.mockResolvedValue({
      data: {
        status: "READY", session_id: "s2", activeAgentIds: ["resp-marketing"], selected_agents: [],
        risk_flags: [], plan: { id: "plan-2", objective_type: "STRATEGIA" }, tasks: [],
        llm_understanding: { mode: "DETERMINISTICO", motivo: "Nessuna connessione AI verificata e attiva." },
        normalized_plan: { origine: "DETERMINISTICO", priorita: "MEDIA", urgenza: "MEDIA", budget_status: "NON_APPLICABILE",
                           canali: [], capability_validate: [], capability_extra_scartate: [], task_proposti_validati: [],
                           kpi: [], rischi_valutati: [], azione_rischio_aggregata: "NONE", domande_aggiuntive: [],
                           assunzioni: [], approvazioni_necessarie: [], correzioni: [], strategia_proposta: "" },
      },
    });
    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId("goal-input"), "Prepara una strategia");
    await user.click(screen.getByTestId("goal-classify"));

    expect(await screen.findByTestId("goal-status")).toHaveTextContent("READY");
    expect(screen.getByTestId("plan-insights")).toBeInTheDocument();
    expect(screen.queryByTestId("tasks-list")).not.toBeInTheDocument(); // nessun task -> componente non renderizzato
  });

  it("gestisce la risposta NEEDS_CLARIFICATION e invia le risposte", async () => {
    api.post.mockImplementation((url, body) => {
      if (!body.clarification) {
        return Promise.resolve({
          data: {
            status: "NEEDS_CLARIFICATION", session_id: "s3",
            questions: ["Qual e' il budget disponibile?"], clarifying_questions: ["Qual e' il budget disponibile?"],
            missing_information: ["budget"],
          },
        });
      }
      return Promise.resolve({ data: PIANO_READY_REALE });
    });
    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId("goal-input"), "Lancia una campagna ads");
    await user.click(screen.getByTestId("goal-classify"));

    expect(await screen.findByTestId("goal-clarify")).toBeInTheDocument();
    expect(screen.getByTestId("clarify-questions")).toHaveTextContent("Qual e' il budget disponibile?");

    await user.type(screen.getByTestId("clarify-answer-0"), "2000 euro");
    await user.click(screen.getByTestId("clarify-submit"));

    await waitFor(() => expect(api.post).toHaveBeenLastCalledWith("/brain/plans", expect.objectContaining({
      session_id: "s3", clarification: expect.objectContaining({ answers: ["2000 euro"] }),
    })));
    expect(await screen.findByTestId("goal-ready")).toBeInTheDocument();
  });

  it("blocca l'invio del chiarimento se una domanda resta senza risposta", async () => {
    api.post.mockResolvedValue({
      data: { status: "NEEDS_CLARIFICATION", session_id: "s4", questions: ["Domanda 1?", "Domanda 2?"] },
    });
    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId("goal-input"), "obiettivo vago");
    await user.click(screen.getByTestId("goal-classify"));

    await screen.findByTestId("goal-clarify");
    await user.type(screen.getByTestId("clarify-answer-0"), "risposta");
    await user.click(screen.getByTestId("clarify-submit"));

    expect(await screen.findByTestId("clarify-error")).toBeInTheDocument();
  });

  it("mostra BLOCKED_RISK con i rischi valutati dalla proposta LLM", async () => {
    api.post.mockResolvedValue({
      data: {
        status: "BLOCKED_RISK", session_id: "s5", risk_flags: ["irreversibile"],
        normalized_plan: {
          rischi_valutati: [{ categoria: "irreversibile", severita: "ALTA", azione: "BLOCK",
                             motivo: "Categoria 'irreversibile' (severita' ALTA) -> azione base 'BLOCK'." }],
        },
      },
    });
    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId("goal-input"), "richiesta rischiosa");
    await user.click(screen.getByTestId("goal-classify"));

    const blocked = await screen.findByTestId("goal-blocked");
    expect(blocked).toHaveTextContent("irreversibile");
    expect(blocked).toHaveTextContent("ALTA");
  });

  it("naviga in Sala Riunioni al click del bottone dedicato", async () => {
    api.post.mockResolvedValue({ data: PIANO_READY_REALE });
    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId("goal-input"), "Prepara una campagna");
    await user.click(screen.getByTestId("goal-classify"));

    await user.click(await screen.findByTestId("goal-go-to-room"));
    expect(mockNavigate).toHaveBeenCalledWith("/sala-riunioni?planId=plan-1");
  });

  it("ripristina una sessione NEEDS_CLARIFICATION interrotta da un refresh, senza regressioni", async () => {
    localStorage.setItem("actelya_brain_session_id", "session-resume-1");
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") {
        return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" } } });
      }
      if (url === "/brain/sessions/session-resume-1") {
        return Promise.resolve({
          data: {
            found: true, session_id: "session-resume-1",
            session: {
              status: "NEEDS_CLARIFICATION", original_request: "Prepara una campagna",
              clarifications: [{ question: "Qual e' il budget disponibile?", answer: null }],
            },
          },
        });
      }
      return Promise.reject({ response: { status: 404 } });
    });

    renderPage();
    expect(await screen.findByTestId("goal-clarify")).toBeInTheDocument();
    expect(screen.getByTestId("clarify-questions")).toHaveTextContent("Qual e' il budget disponibile?");
    expect(screen.getByTestId("goal-input")).toHaveValue("Prepara una campagna");
  });

  it("ripristina una sessione READY interrotta da un refresh e mostra il collegamento a Sala Riunioni", async () => {
    localStorage.setItem("actelya_brain_session_id", "session-resume-2");
    api.get.mockImplementation((url) => {
      if (url === "/auth/me") {
        return Promise.resolve({ data: { user: { id: "u1", email: "a@b.it", role: "ADMIN", organization_id: "org-1" } } });
      }
      if (url === "/brain/sessions/session-resume-2") {
        return Promise.resolve({
          data: { found: true, session_id: "session-resume-2", plan_id: "plan-resumed", activeAgentIds: ["resp-marketing"],
                  session: { status: "PLAN_CREATED", plan_id: "plan-resumed", activeAgentIds: ["resp-marketing"] } },
        });
      }
      return Promise.reject({ response: { status: 404 } });
    });

    renderPage();
    expect(await screen.findByTestId("goal-ready-resumed")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByTestId("goal-go-to-room"));
    expect(mockNavigate).toHaveBeenCalledWith("/sala-riunioni?planId=plan-resumed");
  });

  it("il pulsante 'Nuovo obiettivo' ripulisce la sessione locale e lo stato", async () => {
    api.post.mockResolvedValue({ data: PIANO_READY_REALE });
    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByTestId("goal-input"), "Prepara una campagna");
    await user.click(screen.getByTestId("goal-classify"));
    await screen.findByTestId("goal-status");

    await user.click(screen.getByTestId("goal-new"));
    expect(screen.queryByTestId("goal-result")).not.toBeInTheDocument();
    expect(screen.getByTestId("goal-input")).toHaveValue("");
    expect(localStorage.getItem("actelya_brain_session_id")).toBeNull();
  });
});
