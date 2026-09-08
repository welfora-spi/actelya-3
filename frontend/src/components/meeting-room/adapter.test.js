import { renderHook, waitFor } from "@testing-library/react";
import { useMeetingRoomDataFromPlan } from "./adapter";
import api from "@/lib/api";

jest.mock("@/lib/api", () => ({ __esModule: true, default: { get: jest.fn() } }));

const AGENT_MAPPINGS = [
  { agent_id: "social-media-manager", role_name: "Social media manager", mappings: [
    { capability: "editorial", m2_agent_id: "content_social", deliverable_type: "editorial_plan" },
  ] },
  { agent_id: "copywriter", role_name: "Copywriter", mappings: [
    { capability: "social", m2_agent_id: "content_social", deliverable_type: "social_content" },
    { capability: "email", m2_agent_id: "content_social", deliverable_type: "email" },
  ] },
];

function mockPlan({ plan_status, tasks }) {
  api.get.mockImplementation((url) => {
    if (url === "/m2/plans/plan-1") {
      return Promise.resolve({
        data: {
          plan: {
            id: "plan-1", plan_status, created_at: "2026-09-06T13:10:35.079568+00:00",
            active_agent_ids: ["social-media-manager", "copywriter"],
          },
          tasks,
        },
      });
    }
    if (url === "/m2/plans/plan-1/deliverables") return Promise.resolve({ data: { deliverables: [] } });
    if (url === "/brain/agents") return Promise.resolve({ data: { agents: AGENT_MAPPINGS } });
    return Promise.reject(new Error("unexpected " + url));
  });
}

function coordinatorOf(result) {
  return result.current.data.seats.find((s) => s.kind === "coordinator");
}
function seatOf(result, agentId) {
  return result.current.data.seats.find((s) => s.id === agentId);
}

describe("useMeetingRoomDataFromPlan — Coordinatore da evidenza reale", () => {
  afterEach(() => jest.clearAllMocks());

  it("piano IN_ATTESA_APPROVAZIONE, zero task running, zero tentativi: il Coordinatore NON è AL_LAVORO", async () => {
    mockPlan({
      plan_status: "IN_ATTESA_APPROVAZIONE",
      tasks: [
        { id: "t1", agent_id: "content_social", deliverable_type: "editorial_plan", task_status: "IN_ATTESA_APPROVAZIONE", attempt: 0 },
        { id: "t2", agent_id: "content_social", deliverable_type: "social_content", task_status: "IN_ATTESA_APPROVAZIONE", attempt: 0 },
      ],
    });

    const { result } = renderHook(() => useMeetingRoomDataFromPlan("plan-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(coordinatorOf(result).status).not.toBe("AL_LAVORO");
    expect(coordinatorOf(result).status).toBe("IN_ATTESA");
  });

  it("un task realmente IN_ESECUZIONE: il Coordinatore risulta AL_LAVORO", async () => {
    mockPlan({
      plan_status: "IN_ESECUZIONE",
      tasks: [
        { id: "t1", agent_id: "content_social", deliverable_type: "editorial_plan", task_status: "IN_ESECUZIONE", attempt: 1 },
        { id: "t2", agent_id: "content_social", deliverable_type: "social_content", task_status: "IN_ATTESA_APPROVAZIONE", attempt: 0 },
      ],
    });

    const { result } = renderHook(() => useMeetingRoomDataFromPlan("plan-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(coordinatorOf(result).status).toBe("AL_LAVORO");
  });

  it("nessun piano (dati insufficienti): STATO_NON_DISPONIBILE, mai AL_LAVORO per difetto", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/m2/plans/plan-1") return Promise.resolve({ data: { plan: {}, tasks: [] } });
      if (url === "/m2/plans/plan-1/deliverables") return Promise.resolve({ data: { deliverables: [] } });
      if (url === "/brain/agents") return Promise.resolve({ data: { agents: [] } });
      return Promise.reject(new Error("unexpected " + url));
    });
    const { result } = renderHook(() => useMeetingRoomDataFromPlan("plan-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(coordinatorOf(result).status).toBe("STATO_NON_DISPONIBILE");
  });
});

describe("useMeetingRoomDataFromPlan — assegnazione uno-a-molti per m2_agent_id condiviso", () => {
  afterEach(() => jest.clearAllMocks());

  it("stesso m2_agent_id, due task/due ruoli frontend distinti: nessuna sovrascrittura", async () => {
    mockPlan({
      plan_status: "APPROVATO",
      tasks: [
        { id: "t1", agent_id: "content_social", deliverable_type: "editorial_plan", task_status: "IN_CODA", attempt: 0 },
        { id: "t2", agent_id: "content_social", deliverable_type: "social_content", task_status: "IN_CODA", attempt: 0 },
      ],
    });

    const { result } = renderHook(() => useMeetingRoomDataFromPlan("plan-1"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    const socialMediaManager = seatOf(result, "social-media-manager");
    const copywriter = seatOf(result, "copywriter");

    expect(socialMediaManager.taskId).toBe("t1");
    expect(copywriter.taskId).toBe("t2");
    // Nessuno dei due ruoli deve restare senza attività a causa di una
    // sovrascrittura silenziosa (il difetto confermato: entrambi i task
    // finivano assegnati a un unico ruolo).
    expect(socialMediaManager.taskId).not.toBe(copywriter.taskId);
  });
});
