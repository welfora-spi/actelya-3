// Sala Riunioni — adapter dati.
//
// FASE 1 (attuale): useMeetingRoomData() restituisce SOLO dati demo locali
// (roomData.js), nessuna chiamata di rete. La forma restituita
// { objective, seats, deliverables } è però già quella che un domani
// arriverà da brain/M2, così lo swap richiede di cambiare solo questo file,
// non i componenti che lo consumano.
import { DEMO_OBJECTIVE, DEMO_SEATS } from "./roomData";

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

// Un deliverable è "valido" (approvabile) solo se COMPLETATO — stesso
// criterio del campo `valid` calcolato da m2/deliverables.py sul backend
// (COMPLETATO o COMPLETATO_CON_AVVISI): qui, in assenza di quel secondo
// stato lato demo, si usa il solo COMPLETATO.
export function isValidDeliverable(document) {
  return Boolean(document) && document.status === "COMPLETATO";
}

export function collaboratorSeats(seats) {
  return seats.filter((s) => s.kind === "collaborator" || s.kind === "coordinator");
}

export function deliverablesFromSeats(seats) {
  return collaboratorSeats(seats)
    .filter((s) => s.document)
    .map((s) => ({ ownerId: s.id, ownerName: s.name, ...s.document }));
}

export function useMeetingRoomData() {
  return {
    objective: DEMO_OBJECTIVE,
    seats: DEMO_SEATS,
    deliverables: deliverablesFromSeats(DEMO_SEATS),
    loading: false,
    source: "demo",
  };
}

// ---------------------------------------------------------------------
// Punto di innesto futuro — NON invocata da nessun componente in questa
// fase. Quando la Sala Riunioni verrà collegata al backend, questa funzione
// (o una sua evoluzione) sostituirà useMeetingRoomData(): usa gli endpoint
// già esistenti e verificati (/brain/plans per creare il piano con
// contesto, /m2/plans/:id e /m2/plans/:id/deliverables per leggerlo), senza
// introdurre nuove rotte backend. Resta da definire SOLO la mappatura
// agent_id -> ruolo/postazione umana (oggi implicita nei dati demo).
export async function fetchMeetingRoomDataFromApi(api, planId) {
  const [{ data: planRes }, { data: delivRes }] = await Promise.all([
    api.get(`/m2/plans/${planId}`),
    api.get(`/m2/plans/${planId}/deliverables`),
  ]);
  return {
    objective: planRes.plan?.objective_type,
    seats: [], // TODO: mappare planRes.tasks (agent_id) sulle postazioni della sala
    deliverables: delivRes.deliverables || [],
    loading: false,
    source: "api",
  };
}
