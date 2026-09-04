import { render, screen } from "@testing-library/react";
import TasksList from "./TasksList";

describe("TasksList", () => {
  it("non renderizza nulla con una lista vuota o assente", () => {
    const { container: c1 } = render(<TasksList tasks={[]} />);
    expect(c1).toBeEmptyDOMElement();
    const { container: c2 } = render(<TasksList tasks={null} />);
    expect(c2).toBeEmptyDOMElement();
  });

  it("mostra nome, dipendenze, priorita' e scadenza dei task", () => {
    render(<TasksList tasks={[
      { id: "t1", name: "marketing_strategy", depends_on: [] },
      { id: "t2", name: "social_content", depends_on: ["t1"], llm_priority: "ALTA", llm_deadline: "2026-12-01" },
    ]} />);
    const list = screen.getByTestId("tasks-list");
    expect(list).toHaveTextContent("marketing_strategy");
    expect(list).toHaveTextContent("social_content");
    expect(list).toHaveTextContent("dipende da 1 task");
    expect(list).toHaveTextContent("ALTA");
    expect(list).toHaveTextContent("2026-12-01");
  });

  it("un task senza llm_priority/llm_deadline non mostra quei campi", () => {
    render(<TasksList tasks={[{ id: "t1", name: "marketing_strategy", depends_on: [] }]} />);
    const list = screen.getByTestId("tasks-list");
    expect(list.textContent).not.toMatch(/undefined|null/);
  });
});
