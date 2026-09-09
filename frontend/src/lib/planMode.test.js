import { derivePlanMode } from "./planMode";

describe("derivePlanMode — modalità del piano derivata dai task, mai dalla sola impostazione dell'organizzazione", () => {
  it("un task con deliverable_override.mode REALE (pre-approvazione) determina la modalità", () => {
    const tasks = [{ id: "t1", inputs: { deliverable_override: { mode: "REALE" } } }];
    expect(derivePlanMode(tasks)).toEqual({ label: "REALE", certain: true, reason: null });
  });

  it("approved_mode (post-approvazione) ha priorità ed è affidabile", () => {
    const tasks = [{ id: "t1", approved_mode: "SIMULAZIONE", inputs: { deliverable_override: { mode: "REALE" } } }];
    expect(derivePlanMode(tasks).label).toBe("SIMULAZIONE");
  });

  it("task in modalità diverse tra loro risultano MISTA", () => {
    const tasks = [
      { id: "t1", approved_mode: "REALE" },
      { id: "t2", approved_mode: "SIMULAZIONE" },
    ];
    const r = derivePlanMode(tasks);
    expect(r.label).toBe("MISTA");
    expect(r.certain).toBe(true);
  });

  it("nessun task con segnale di modalità: SIMULAZIONE per difetto, dichiarata incerta", () => {
    const r = derivePlanMode([{ id: "t1", inputs: {} }]);
    expect(r.label).toBe("SIMULAZIONE");
    expect(r.certain).toBe(false);
  });

  it("nessun task (piano vuoto): SIMULAZIONE per difetto", () => {
    expect(derivePlanMode([]).label).toBe("SIMULAZIONE");
    expect(derivePlanMode(undefined).label).toBe("SIMULAZIONE");
  });
});
