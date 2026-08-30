// Sala Riunioni — dati DINAMICI per l'obiettivo attivo (demo).
// Nessuna chiamata di rete. La struttura (chi esiste, dove sta, come si
// chiama) è in agentRegistry.js: qui SOLO ciò che dipende dal piano/obiettivo
// corrente — status, attività, documento, cronologia — collegato al
// registry tramite agent_id (vedi adapter.js, che unisce le due fonti).

export const DEMO_OBJECTIVE = "Pubblicizzare le focaccine artigianali del Bakery & Coffee di Merate";

export const TEAM_MODES = {
  RICHIESTA: "richiesta",
  COMPLETA: "completa",
};

// L'imprenditore è parte del livello base (fotografia), non un agente del
// registry: nessun layer-persona, nessuna targhetta, non selezionabile.
export const OWNER = {
  id: "owner",
  kind: "owner",
  name: "Tu",
  role: "Imprenditore",
};

// Dati dinamici del Coordinatore per l'obiettivo attivo (struttura fissa in
// agentRegistry.js::COORDINATOR_AGENT).
export const COORDINATOR_DATA = {
  status: "AL_LAVORO",
  activity: {
    title: "Coordinamento del team e sintesi per l'imprenditore",
    detail: "Raccoglie il lavoro dei collaboratori e prepara la sintesi per la decisione finale.",
  },
  document: null,
  history: [
    { label: "Obiettivo ricevuto", time: "09:10", state: "done" },
    { label: "Squadra convocata", time: "09:12", state: "done" },
    { label: "In attesa dei deliverable", time: "In corso", state: "active" },
  ],
};

function nonAssegnato() {
  return {
    status: "CONVOCATO",
    activity: {
      title: "In attesa di assegnazione",
      detail: "Non ancora coinvolto/a in questo obiettivo specifico.",
    },
    document: null,
    history: [{ label: "Squadra convocata", time: "09:12", state: "done" }],
  };
}

// Dati dinamici per agent_id, legati a QUESTO obiettivo (focaccine). Un
// agent_id presente in activeAgentIds ma assente da questa mappa riceve un
// default prudente equivalente (vedi adapter.js::defaultObjectiveData).
export const OBJECTIVE_DATA_BY_AGENT = {
  "resp-marketing": {
    status: "AL_LAVORO",
    activity: {
      title: "Definizione strategia di lancio",
      detail: "Analisi target, posizionamento e messaggi chiave.",
    },
    document: { id: "doc-strategia", title: "Strategia locale", type: "strategy", status: "BOZZA", version: 1 },
    history: [
      { label: "Brief ricevuto", time: "09:15", state: "done" },
      { label: "Ricerca e analisi", time: "09:20", state: "done" },
      { label: "Redazione strategia", time: "In corso", state: "active" },
      { label: "Revisione finale", time: "—", state: "pending" },
    ],
  },
  "social-media-manager": {
    status: "AL_LAVORO",
    activity: {
      title: "Costruzione del piano editoriale",
      detail: "Calendario contenuti su Instagram e Facebook per la campagna locale.",
    },
    document: { id: "doc-editoriale", title: "Piano editoriale", type: "editorial", status: "IN_APPROVAZIONE", version: 1 },
    history: [
      { label: "Strategia ricevuta", time: "09:25", state: "done" },
      { label: "Bozza calendario completata", time: "09:50", state: "done" },
      { label: "Inviato in approvazione", time: "In corso", state: "active" },
    ],
  },
  copywriter: {
    status: "COMPLETATO",
    activity: {
      title: "Scrittura dei post social",
      detail: "3 post per Instagram e Facebook, tono locale e diretto.",
    },
    document: { id: "doc-post", title: "3 post social", type: "social", status: "COMPLETATO", version: 2 },
    history: [
      { label: "Piano editoriale ricevuto", time: "09:40", state: "done" },
      { label: "Bozza post", time: "09:55", state: "done" },
      { label: "Revisione compliance superata", time: "10:05", state: "done" },
    ],
  },
  "resp-compliance": {
    status: "IN_ATTESA",
    activity: {
      title: "In attesa dei contenuti da revisionare",
      detail: "Nessun contenuto ancora pronto per la verifica di conformità.",
    },
    document: null,
    history: [
      { label: "Squadra convocata", time: "09:12", state: "done" },
      { label: "In attesa di materiale", time: "In corso", state: "active" },
    ],
  },
  "resp-advertising": nonAssegnato(),
  "lead-gen-specialist": nonAssegnato(),
  "analista-performance": nonAssegnato(),
  "appointment-setter": nonAssegnato(),
  "specialista-nurturing": nonAssegnato(),
};

// Il Coordinatore non compare mai in questi array (gestito separatamente,
// sempre attivo — vedi adapter.js).
export const DEMO_ACTIVE_AGENT_IDS_RICHIESTA = ["resp-marketing", "social-media-manager", "copywriter", "resp-compliance"];

export const DEMO_ACTIVE_AGENT_IDS_COMPLETA = [
  "resp-marketing", "social-media-manager", "resp-advertising", "lead-gen-specialist",
  "specialista-nurturing", "analista-performance", "appointment-setter", "copywriter", "resp-compliance",
];
