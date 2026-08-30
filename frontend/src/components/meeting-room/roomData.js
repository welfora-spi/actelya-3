// Sala Riunioni — dati DEMO, separati dalla logica dei componenti.
// Nessuna chiamata di rete: questo file esiste per essere sostituito da
// adapter.js::fetchMeetingRoomDataFromApi quando brain/M2 saranno collegati
// (vedi commento in fondo ad adapter.js).

export const DEMO_OBJECTIVE = "Pubblicizzare le focaccine artigianali del Bakery & Coffee di Merate";

// kind: "owner" (imprenditore, non selezionabile) | "collaborator" | "coordinator" | "empty"
// side: "near" (capotavola, imprenditore) | "far" (fondo, coordinatore) | "left" | "right"
// status (solo per collaborator/coordinator): CONVOCATO | AL_LAVORO | IN_ATTESA | COMPLETATO
export const DEMO_SEATS = [
  {
    id: "owner",
    kind: "owner",
    side: "near",
    name: "Tu",
    role: "Imprenditore",
  },
  {
    id: "coordinatore",
    kind: "coordinator",
    side: "far",
    name: "Coordinatore ACTELYA",
    role: "Coordinamento",
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
  },
  {
    id: "resp-marketing",
    kind: "collaborator",
    side: "left",
    name: "Responsabile marketing",
    role: "Strategia",
    status: "AL_LAVORO",
    activity: {
      title: "Definizione strategia di lancio",
      detail: "Analisi target, posizionamento e messaggi chiave.",
    },
    document: {
      id: "doc-strategia",
      title: "Strategia locale",
      type: "strategy",
      status: "BOZZA",
      version: 1,
    },
    history: [
      { label: "Brief ricevuto", time: "09:15", state: "done" },
      { label: "Ricerca e analisi", time: "09:20", state: "done" },
      { label: "Redazione strategia", time: "In corso", state: "active" },
      { label: "Revisione finale", time: "—", state: "pending" },
    ],
  },
  {
    id: "social-media-manager",
    kind: "collaborator",
    side: "left",
    name: "Social media manager",
    role: "Editoriale",
    status: "AL_LAVORO",
    activity: {
      title: "Costruzione del piano editoriale",
      detail: "Calendario contenuti su Instagram e Facebook per la campagna locale.",
    },
    document: {
      id: "doc-editoriale",
      title: "Piano editoriale",
      type: "editorial",
      status: "AL_LAVORO",
      version: 1,
    },
    history: [
      { label: "Strategia ricevuta", time: "09:25", state: "done" },
      { label: "Bozza calendario", time: "In corso", state: "active" },
    ],
  },
  {
    id: "empty-left",
    kind: "empty",
    side: "left",
  },
  {
    id: "copywriter",
    kind: "collaborator",
    side: "right",
    name: "Copywriter",
    role: "Contenuti",
    status: "COMPLETATO",
    activity: {
      title: "Scrittura dei post social",
      detail: "3 post per Instagram e Facebook, tono locale e diretto.",
    },
    document: {
      id: "doc-post",
      title: "3 post social",
      type: "social",
      status: "COMPLETATO",
      version: 2,
    },
    history: [
      { label: "Piano editoriale ricevuto", time: "09:40", state: "done" },
      { label: "Bozza post", time: "09:55", state: "done" },
      { label: "Revisione compliance superata", time: "10:05", state: "done" },
    ],
  },
  {
    id: "resp-compliance",
    kind: "collaborator",
    side: "right",
    name: "Responsabile compliance",
    role: "Conformità",
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
  {
    id: "empty-right",
    kind: "empty",
    side: "right",
  },
];
