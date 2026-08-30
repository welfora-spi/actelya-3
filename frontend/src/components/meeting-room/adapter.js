// Sala Riunioni — adapter dati.
//
// Unisce la struttura statica (agentRegistry.js: chi esiste, dove sta, come
// si chiama) con i dati dinamici dell'obiettivo attivo (roomData.js: status,
// attività, documento, cronologia), filtrando per activeAgentIds — l'elenco
// dei ruoli davvero coinvolti in QUESTO obiettivo/piano.
//
// FASE 1 (attuale): activeAgentIds proviene da due array demo locali
// (roomData.js), nessuna chiamata di rete. Quando brain/M2 saranno
// collegati, activeAgentIds arriverà dai task del piano reale (agent_id di
// ciascun task) — lo swap richiede di cambiare solo questo file.
import { AGENT_REGISTRY, COORDINATOR_AGENT, getAgentById } from "./agentRegistry";
import {
  DEMO_OBJECTIVE, OWNER, COORDINATOR_DATA, OBJECTIVE_DATA_BY_AGENT,
  DEMO_ACTIVE_AGENT_IDS_RICHIESTA, DEMO_ACTIVE_AGENT_IDS_COMPLETA, TEAM_MODES,
} from "./roomData";

export { TEAM_MODES };

// Vocabolario "umano" per lo stato di un deliverable/collaboratore: nasconde
// il vocabolario tecnico del motore M2 (BOZZA/IN_ATTESA_APPROVAZIONE/...)
// dietro le 4 etichette richieste per i badge della Sala Riunioni.
export const DELIVERABLE_STATUS_META = {
  BOZZA: { label: "Bozza in lavorazione", tone: "blue" },
  AL_LAVORO: { label: "Al lavoro", tone: "emerald" },
  IN_APPROVAZIONE: { label: "In approvazione", tone: "amber" },
  COMPLETATO: { label: "Completato", tone: "emerald" },
  BLOCCATO: { label: "Bloccato", tone: "red" },
};

export const SEAT_STATUS_META = {
  CONVOCATO: { label: "Convocato", tone: "slate" },
  AL_LAVORO: { label: "Al lavoro", tone: "emerald" },
  IN_ATTESA: { label: "In attesa", tone: "amber" },
  COMPLETATO: { label: "Completato", tone: "emerald" },
};

// Un deliverable abilita le azioni (Approva / Chiedi una modifica) solo se
// esiste davvero un contenuto sostanziale su cui decidere: COMPLETATO (già
// pronto) o IN_APPROVAZIONE (pronto, in attesa di una decisione). BOZZA/
// AL_LAVORO restano disabilitate: non c'è ancora nulla di definito.
const STATI_AZIONABILI = ["COMPLETATO", "IN_APPROVAZIONE"];
export function isValidDeliverable(document) {
  return Boolean(document) && STATI_AZIONABILI.includes(document.status);
}

function defaultObjectiveData() {
  return {
    status: "CONVOCATO",
    activity: { title: "In attesa di assegnazione", detail: "Nessuna attività assegnata per questo obiettivo." },
    document: null,
    history: [],
  };
}

// Unisce struttura + dati dell'obiettivo, filtrando per activeAgentIds.
// Un agent_id sconosciuto (non nel registry) o duplicato viene scartato con
// un avviso in sviluppo — MAI un errore per l'utente (item 10).
function buildCollaboratorSeats(activeAgentIds) {
  const seen = new Set();
  const seats = [];
  for (const agentId of activeAgentIds || []) {
    if (seen.has(agentId)) {
      if (process.env.NODE_ENV === "development") {
        console.warn(`[adapter] agent_id duplicato in activeAgentIds, ignorato: ${agentId}`);
      }
      continue;
    }
    seen.add(agentId);
    const agent = getAgentById(agentId);
    if (!agent) {
      if (process.env.NODE_ENV === "development") {
        console.warn(`[adapter] agent_id sconosciuto in activeAgentIds, ignorato: ${agentId}`);
      }
      continue;
    }
    const data = OBJECTIVE_DATA_BY_AGENT[agentId] || defaultObjectiveData();
    seats.push({ ...agent, ...data, id: agent.agent_id, kind: "collaborator" });
  }
  return seats;
}

function buildCoordinatorSeat() {
  return { ...COORDINATOR_AGENT, ...COORDINATOR_DATA, id: COORDINATOR_AGENT.agent_id, kind: "coordinator" };
}

export function deliverablesFromSeats(seats) {
  return seats
    .filter((s) => (s.kind === "collaborator" || s.kind === "coordinator") && s.document)
    .map((s) => ({ ownerId: s.id, ownerName: s.role_name, ...s.document }));
}

export function useMeetingRoomData(teamMode = TEAM_MODES.RICHIESTA) {
  const activeAgentIds = teamMode === TEAM_MODES.COMPLETA ? DEMO_ACTIVE_AGENT_IDS_COMPLETA : DEMO_ACTIVE_AGENT_IDS_RICHIESTA;
  const collaboratorSeats = buildCollaboratorSeats(activeAgentIds);
  const coordinatorSeat = buildCoordinatorSeat();
  const seats = [OWNER, coordinatorSeat, ...collaboratorSeats];

  return {
    objective: DEMO_OBJECTIVE,
    seats,
    activeAgentIds,
    deliverables: deliverablesFromSeats(seats),
    loading: false,
    source: "demo",
  };
}

// ---------------------------------------------------------------------
// Punto di innesto futuro — NON invocata da nessun componente in questa
// fase. Quando la Sala Riunioni verrà collegata al backend: activeAgentIds
// arriverà dai task del piano reale (agent_id di ciascun task), lo status
// dal task_status/deliverable mappato sul vocabolario umano qui sopra.
export async function fetchMeetingRoomDataFromApi(api, planId) {
  const [{ data: planRes }, { data: delivRes }] = await Promise.all([
    api.get(`/m2/plans/${planId}`),
    api.get(`/m2/plans/${planId}/deliverables`),
  ]);
  const activeAgentIds = (planRes.tasks || []).map((t) => t.agent_id);
  return {
    objective: planRes.plan?.objective_type,
    activeAgentIds,
    seats: [], // TODO: unire AGENT_REGISTRY + planRes.tasks/delivRes per agent_id
    deliverables: delivRes.deliverables || [],
    loading: false,
    source: "api",
  };
}
