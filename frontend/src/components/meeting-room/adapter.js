// Sala Riunioni — adapter dati.
//
// Unisce la struttura statica (agentRegistry.js: chi esiste, dove sta, come
// si chiama) con i dati dinamici dell'obiettivo attivo, filtrando per
// activeAgentIds — l'elenco dei ruoli davvero coinvolti in QUESTO
// obiettivo/piano.
//
// Due sorgenti dati:
// - useMeetingRoomData(teamMode): demo locale (roomData.js), nessuna
//   chiamata di rete — usata quando non c'è un piano reale da mostrare.
// - useMeetingRoomDataFromPlan(planId): dati REALI da GET /m2/plans/:id,
//   activeAgentIds = plan.active_agent_ids (persistito da
//   brain/service.py::create_plan_with_brain — mai da task.agent_id M2
//   grezzo, che è un id diverso, lato motore, non lato frontend).
import { useEffect, useState } from "react";
import api from "@/lib/api";
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
  IN_ATTESA: { label: "In attesa", tone: "amber" },
  AL_LAVORO: { label: "Al lavoro", tone: "emerald" },
  IN_REVISIONE: { label: "In revisione", tone: "amber" },
  COMPLETATO: { label: "Completato", tone: "emerald" },
  BLOCCATO: { label: "Bloccato", tone: "red" },
  // Nessuna evidenza sufficiente nei dati ricevuti per determinare lo stato
  // (mai un default operativo inventato — vedi coordinatorStatusFromPlan).
  STATO_NON_DISPONIBILE: { label: "Stato non disponibile", tone: "slate" },
};

// task_status M2 (m2/engine.py) -> stato "umano" del collaboratore. Un
// deliverable BLOCCATO su un task tecnicamente COMPLETATA resta BLOCCATO
// (il tecnico ha finito, il risultato no) — mai mostrato come pronto.
function seatStatusFromTask(task, deliverable) {
  if (!task) return "CONVOCATO";
  if (["FALLITA", "BLOCCATA", "SALTATA", "ARRESTATA"].includes(task.task_status)) return "BLOCCATO";
  if (task.task_status === "IN_ESECUZIONE") return "AL_LAVORO";
  if (task.task_status === "IN_CODA") return "IN_ATTESA";
  if (task.task_status === "COMPLETATA") {
    if (deliverable && deliverable.status === "BLOCCATO") return "BLOCCATO";
    return "COMPLETATO";
  }
  return "CONVOCATO"; // IN_ATTESA_APPROVAZIONE | PIANIFICATA
}

const DELIVERABLE_TYPE_LABEL = {
  marketing_strategy: "Strategia di marketing", editorial_plan: "Piano editoriale",
  social_content: "Post social", ad_campaign_draft: "Bozza campagna", lead_gen_plan: "Piano lead generation",
  kpi_report: "Report KPI", email: "Email", video_reel_project: "Progetto reel",
  flyer_project: "Progetto flyer", lead_gen_campaign: "Campagna lead generation",
  appointment_setter_task: "Appointment Setter",
  content_item: "Contenuto",
  sales_opportunity: "Opportunità commerciale",
  analyst_report: "Report KPI",
};

// deliverable_type -> kind per MultimodalProjectPanel (video/immagine reali,
// mai una card che rimanda a una pagina laboratorio separata).
export const MULTIMODAL_PANEL_KIND = { video_reel_project: "reel", flyer_project: "flyer" };

// deliverable_type -> laboratorio dedicato (tabelle/duplicati/approvazione o
// proposte/prenotazioni, non generazione multimediale in linea): il
// pannello collaboratore rimanda a una pagina laboratorio separata, stesso
// principio di "un solo piano, un solo percorso reale" di reel/flyer.
// 'idField' e' opzionale: 'appointment_setter_task' non ha un id specifico
// da propagare (nessuna proposta creata automaticamente alla creazione del
// piano — richiede la scelta di un lead, azione dell'utente nel
// laboratorio), quindi il link naviga alla pagina senza query string.
export const LAB_LINK_BY_DELIVERABLE_TYPE = {
  lead_gen_campaign: { kind: "leadgen", path: "/lead-generation", idParam: "campaignId", idField: "lead_campaign_id", label: "Lead Generation" },
  appointment_setter_task: { kind: "appointments", path: "/appointment-setter", idParam: null, idField: null, label: "Appointment Setter" },
  // Come 'appointment_setter_task': il task puo' collegare PIU' content_item
  // (content_item_ids, una lista) invece di un singolo id, quindi nessun
  // deep-link a un elemento specifico — si va alla lista del laboratorio.
  content_item: { kind: "content_creator", path: "/content-creator", idParam: null, idField: null, label: "Content Creator" },
  sales_opportunity: { kind: "sales", path: "/sales", idParam: null, idField: null, label: "Sales" },
  // A differenza degli altri, qui l'id ESISTE davvero (il report e' creato
  // subito da brain/service.py): deep-link diretto al report generato.
  analyst_report: { kind: "analyst", path: "/analyst", idParam: "reportId", idField: "analyst_report_id", label: "Analyst" },
};

function activityFromTask(task, deliverable) {
  const label = DELIVERABLE_TYPE_LABEL[task?.deliverable_type] || task?.name || "Attività";
  if (!task) return { title: "In attesa di assegnazione", detail: "Nessuna attività assegnata per questo obiettivo." };
  if (task.task_status === "IN_ATTESA_APPROVAZIONE" || task.task_status === "PIANIFICATA") {
    return { title: `${label}: in attesa di approvazione`, detail: "Il task è pronto ma deve ancora essere approvato prima di partire." };
  }
  if (task.task_status === "IN_CODA") return { title: `${label}: in coda`, detail: "Approvato, in attesa che il motore lo elabori." };
  if (task.task_status === "IN_ESECUZIONE") return { title: `${label}: al lavoro`, detail: "Elaborazione in corso." };
  if (["FALLITA", "BLOCCATA", "SALTATA", "ARRESTATA"].includes(task.task_status)) {
    return { title: `${label}: bloccato`, detail: (task.warnings || []).join(" ") || task.motivo || "Impossibile completare questo task." };
  }
  if (deliverable?.status === "BLOCCATO") {
    return { title: `${label}: risultato bloccato`, detail: (deliverable.errors || []).join(" ") || "Il risultato non ha superato la validazione." };
  }
  if (task.deliverable_type === "video_reel_project" || task.deliverable_type === "flyer_project") {
    return { title: `${label}: pronto per la generazione reale`, detail: "Genera e approva il contenuto reale qui sotto (Requesty/Runway)." };
  }
  return { title: `${label}: completato`, detail: (deliverable?.warnings || []).join(" ") || "Bozza pronta per la revisione." };
}

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

function buildCoordinatorSeat(overrides = null) {
  return { ...COORDINATOR_AGENT, ...COORDINATOR_DATA, ...(overrides || {}), id: COORDINATOR_AGENT.agent_id, kind: "coordinator" };
}

// Stato del Coordinatore derivato SOLO da evidenza reale del piano/task
// ricevuti dal backend — mai lo stato demo statico (COORDINATOR_DATA,
// status: "AL_LAVORO") quando esistono dati API reali. Vedi principio
// generale del modulo: nessun agente/coordinatore mostrato al lavoro senza
// un'attività realmente in esecuzione.
function coordinatorStatusFromPlan(plan, tasks) {
  if (!plan || !plan.plan_status) return "STATO_NON_DISPONIBILE";
  if ((tasks || []).some((t) => t.task_status === "IN_ESECUZIONE")) return "AL_LAVORO";
  if (plan.plan_status === "COMPLETATO") return "COMPLETATO";
  if (["BLOCCATO", "ANNULLATO"].includes(plan.plan_status)) return "BLOCCATO";
  // BOZZA / IN_ATTESA_APPROVAZIONE / APPROVATO_PARZIALE / APPROVATO /
  // IN_ESECUZIONE (nessun task realmente IN_ESECUZIONE ancora osservato):
  // il piano esiste ma non c'e' lavoro in corso da mostrare come "al lavoro".
  return "IN_ATTESA";
}

function coordinatorActivityFromPlan(status) {
  switch (status) {
    case "AL_LAVORO":
      return { title: "Coordinamento del team in corso", detail: "Sta seguendo l'avanzamento delle attività attualmente in esecuzione." };
    case "COMPLETATO":
      return { title: "Piano completato", detail: "Tutte le attività rilevanti risultano concluse." };
    case "BLOCCATO":
      return { title: "Piano bloccato o annullato", detail: "Una o più attività sono bloccate, oppure il piano è stato annullato." };
    case "STATO_NON_DISPONIBILE":
      return { title: "Stato non disponibile", detail: "Dati insufficienti per determinare lo stato del coordinatore." };
    default:
      return { title: "In attesa", detail: "Il piano non ha ancora attività realmente in esecuzione." };
  }
}

// Cronologia SOLO da timestamp reali (plan.created_at) — mai orari fissi
// inventati (a differenza di COORDINATOR_DATA.history, che resta solo dato
// demo, mai usato quando c'e' un piano reale).
function coordinatorHistoryFromPlan(plan, status) {
  const entries = [];
  if (plan?.created_at) {
    const t = new Date(plan.created_at);
    if (!Number.isNaN(t.getTime())) entries.push({ label: "Piano creato", time: t.toLocaleTimeString().slice(0, 5), state: "done" });
  }
  const { title } = coordinatorActivityFromPlan(status);
  entries.push({ label: title, time: status === "AL_LAVORO" ? "In corso" : "—", state: status === "AL_LAVORO" ? "active" : "done" });
  return entries;
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
// Dati REALI da un piano creato tramite il brain. activeAgentIds viene
// SEMPRE da plan.active_agent_ids (il contratto ufficiale, mai dai
// task.agent_id M2 grezzi, che sono id di un'altra tassonomia — vedi
// brain/agents/agent_map.py). Gli agenti selezionati che non hanno ancora
// un'attività/documento dinamico noto ricadono su defaultObjectiveData(),
// stesso comportamento della modalità demo: nessun dato inventato.
function objectiveTitleFromPlan(plan) {
  const ctx = plan?.goal_context;
  if (ctx?.azienda) return [ctx.azienda, ctx.prodotto].filter(Boolean).join(" — ");
  return plan?.objective_type || "Obiettivo";
}

// Un m2_agent_id puo' essere condiviso da PIU' ruoli frontend (es.
// "content_social" -> sia "social-media-manager" [capability 'editorial']
// sia "copywriter" [capability 'social']): una relazione m2_agent_id ->
// singolo frontend_agent_id perde uno dei due ogni volta che coincidono
// sullo stesso piano. Fonte canonica SOLO da GET /brain/agents
// (agents/agent_map.py) — mai una tabella duplicata qui, mai un mapping
// hard-coded specifico per un piano.
async function fetchAgentMappings() {
  try {
    const { data } = await api.get("/brain/agents");
    return data.agents || [];
  } catch {
    return [];
  }
}

// deliverable_type -> frontend_agent_id: ogni mapping del backend porta già
// il proprio deliverable_type (agent_map.py::AgentMapping.deliverable_type),
// quindi disambigua correttamente anche quando più ruoli condividono lo
// stesso m2_agent_id — è il task stesso (il suo deliverable_type) a dire
// quale ruolo frontend lo possiede, non l'ordine di un dizionario.
function buildDeliverableTypeToFrontendAgent(agents) {
  const map = {};
  for (const agent of agents) {
    for (const m of agent.mappings || []) {
      if (m.deliverable_type) map[m.deliverable_type] = agent.agent_id;
    }
  }
  return map;
}

// Fallback SOLO per un task senza deliverable_type risolvibile: se il
// m2_agent_id corrisponde a un unico ruolo frontend possibile lo si usa,
// altrimenti si lascia il task non assegnato piuttosto che indovinare (mai
// una sovrascrittura silenziosa tra ruoli che condividono lo stesso agente).
function buildM2AgentToFrontendAgents(agents) {
  const map = {};
  for (const agent of agents) {
    for (const m of agent.mappings || []) {
      if (!m.m2_agent_id) continue;
      (map[m.m2_agent_id] = map[m.m2_agent_id] || []).push(agent.agent_id);
    }
  }
  return map;
}

function resolveFrontendAgentId(task, deliverableTypeToFrontend, m2AgentToFrontendIds) {
  if (task.deliverable_type && deliverableTypeToFrontend[task.deliverable_type]) {
    return deliverableTypeToFrontend[task.deliverable_type];
  }
  const candidates = m2AgentToFrontendIds[task.agent_id] || [];
  return candidates.length === 1 ? candidates[0] : null;
}

export function useMeetingRoomDataFromPlan(planId, refetchToken = 0) {
  const [state, setState] = useState({ loading: Boolean(planId), error: null, data: null });

  useEffect(() => {
    if (!planId) { setState({ loading: false, error: null, data: null }); return; }
    let cancelled = false;
    setState({ loading: true, error: null, data: null });
    Promise.all([
      api.get(`/m2/plans/${planId}`),
      // Solo un guasto genuinamente secondario del sotto-fetch deliverable
      // diventa "nessun deliverable": un 401 (sessione scaduta) deve restare
      // un errore vero, altrimenti la Sala Riunioni mostrerebbe una stanza
      // vuota invece di segnalare che occorre accedere di nuovo.
      api.get(`/m2/plans/${planId}/deliverables`).catch((e) => {
        if (e.response?.status === 401) throw e;
        return { data: { deliverables: [] } };
      }),
      fetchAgentMappings(),
    ])
      .then(([planRes, delivRes, agentMappings]) => {
        if (cancelled) return;
        const plan = planRes.data.plan || {};
        const tasks = planRes.data.tasks || [];
        const deliverables = delivRes.data.deliverables || [];
        const currentDeliverableByTask = {};
        for (const d of deliverables) {
          if (d.is_current) currentDeliverableByTask[d.task_id] = d;
        }
        const activeAgentIds = plan.active_agent_ids || [];

        const deliverableTypeToFrontend = buildDeliverableTypeToFrontendAgent(agentMappings);
        const m2AgentToFrontendIds = buildM2AgentToFrontendAgents(agentMappings);

        // Un agent_id puo' avere piu' task (es. copywriter: 'social' + 'email'):
        // il task piu' "significativo" (non terminale > terminale, piu' recente)
        // guida lo stato del collaboratore in sala riunioni. La risoluzione
        // ruolo-frontend e' uno-a-molti (vedi resolveFrontendAgentId sopra):
        // ogni task risolve al proprio ruolo tramite il proprio
        // deliverable_type, quindi due task sullo stesso m2_agent_id ma con
        // deliverable_type diverso (es. editorial_plan/social_content su
        // "content_social") popolano DUE slot frontend distinti, non uno solo.
        const taskByFrontendAgent = {};
        for (const task of tasks) {
          const frontendId = resolveFrontendAgentId(task, deliverableTypeToFrontend, m2AgentToFrontendIds);
          if (!frontendId) continue;
          const existing = taskByFrontendAgent[frontendId];
          if (!existing || (existing.task_status === "COMPLETATA" && task.task_status !== "COMPLETATA")) {
            taskByFrontendAgent[frontendId] = task;
          }
        }

        const collaboratorSeats = buildCollaboratorSeats(activeAgentIds).map((seat) => {
          const task = taskByFrontendAgent[seat.id];
          const deliverable = task ? currentDeliverableByTask[task.id] : null;
          const status = seatStatusFromTask(task, deliverable);
          return {
            ...seat,
            status,
            taskId: task?.id || null,
            taskStatus: task?.task_status || null,
            activity: activityFromTask(task, deliverable),
            document: deliverable ? (() => {
              const lab = LAB_LINK_BY_DELIVERABLE_TYPE[deliverable.deliverable_type];
              return {
                id: deliverable.id, title: DELIVERABLE_TYPE_LABEL[deliverable.deliverable_type] || deliverable.deliverable_type,
                type: deliverable.deliverable_type, status: deliverable.status, version: deliverable.version,
                projectKind: MULTIMODAL_PANEL_KIND[deliverable.deliverable_type] || (lab ? lab.kind : null),
                projectId: deliverable.content?.reel_project_id || deliverable.content?.flyer_project_id || null,
                labPath: lab?.path || null,
                labId: lab?.idField ? deliverable.content?.[lab.idField] : null,
                labIdParam: lab?.idParam || null,
                labLabel: lab?.label || null,
              };
            })() : null,
            history: task ? [
              { label: "Task creato", time: task.created_at ? new Date(task.created_at).toLocaleTimeString().slice(0, 5) : "—", state: "done" },
              ...(task.started_at ? [{ label: "Avviato", time: new Date(task.started_at).toLocaleTimeString().slice(0, 5), state: "done" }] : []),
              ...(task.finished_at ? [{ label: "Concluso", time: new Date(task.finished_at).toLocaleTimeString().slice(0, 5), state: "done" }]
                : [{ label: status === "AL_LAVORO" ? "Al lavoro" : "In attesa", time: "In corso", state: "active" }]),
            ] : [{ label: "Squadra convocata", time: "—", state: "done" }],
          };
        });
        const coordinatorStatus = coordinatorStatusFromPlan(plan, tasks);
        const coordinatorSeat = buildCoordinatorSeat({
          status: coordinatorStatus,
          activity: coordinatorActivityFromPlan(coordinatorStatus),
          document: null,
          history: coordinatorHistoryFromPlan(plan, coordinatorStatus),
        });
        const seats = [OWNER, coordinatorSeat, ...collaboratorSeats];
        setState({
          loading: false, error: null,
          data: {
            objective: objectiveTitleFromPlan(plan),
            seats, activeAgentIds,
            deliverables: deliverablesFromSeats(seats),
            planId, planStatus: plan.plan_status, estimate: plan.estimate || null,
            tasksCount: tasks.length, source: "api",
          },
        });
      })
      .catch((err) => { if (!cancelled) setState({ loading: false, error: err, data: null }); });
    return () => { cancelled = true; };
  }, [planId, refetchToken]);

  return state;
}
