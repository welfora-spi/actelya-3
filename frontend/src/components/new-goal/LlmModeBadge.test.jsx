import { render, screen } from "@testing-library/react";
import LlmModeBadge from "./LlmModeBadge";

describe("LlmModeBadge", () => {
  it("non renderizza nulla quando llmUnderstanding e' assente", () => {
    const { container } = render(<LlmModeBadge llmUnderstanding={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("mostra provider e modello in modalita' REALE", () => {
    render(<LlmModeBadge llmUnderstanding={{ mode: "REALE", provider_effettivo: "anthropic", modello_effettivo: "claude-x" }} />);
    const badge = screen.getByTestId("llm-mode-badge");
    expect(badge).toHaveTextContent("REALE");
    expect(badge).toHaveTextContent("anthropic");
    expect(badge).toHaveTextContent("claude-x");
  });

  it("mostra il motivo del fallback in modalita' DETERMINISTICO", () => {
    render(<LlmModeBadge llmUnderstanding={{ mode: "DETERMINISTICO", motivo: "Nessuna connessione AI verificata e attiva." }} />);
    const badge = screen.getByTestId("llm-mode-badge");
    expect(badge).toHaveTextContent("deterministica");
    expect(badge).toHaveTextContent("Nessuna connessione AI verificata e attiva.");
    expect(badge).not.toHaveTextContent("REALE");
  });

  it("modalita' REALE senza provider_effettivo non mostra 'via undefined'", () => {
    render(<LlmModeBadge llmUnderstanding={{ mode: "REALE" }} />);
    const badge = screen.getByTestId("llm-mode-badge");
    expect(badge.textContent).not.toMatch(/undefined/);
  });
});
