// Sala Riunioni — registry statico dei 9 ruoli collaboratore ("agenti").
//
// SOLO struttura: nessuno stato legato all'obiettivo qui (status/attività/
// documento/cronologia dipendono dal piano attivo — vedi roomData.js e
// adapter.js, che uniscono questo registry ai dati dell'obiettivo per
// agent_id).
//
// person_asset: quando l'immagine reale esisterà in
// frontend/src/assets/meeting-room/layers/, sostituire `null` con l'import
// (commento pronto sopra ogni voce). L'asset DEVE avere esattamente le
// stesse dimensioni della base (1680×945, 16:9, sfondo trasparente, persona
// già collocata nella propria posizione dentro l'immagine): PersonLayer lo
// renderizza sempre a piena tela (position:absolute, inset:0) — MAI
// top/left/scale individuali, per evitare nuovi disallineamenti.
//
// label_position: coordinate percentuali della targhetta sullo stage 16:9,
// lette pixel per pixel da design/actelya3-full-team-final-labeled-reference.png
// (disposizione approvata) — condivise da entrambe le modalità demo.
//
// seat_id: postazione fisica fissa (mai riassegnata). z_index: ordine di
// sovrapposizione dei layer-persona (i più vicini alla camera sopra).

export const AGENT_REGISTRY = [
  {
    agent_id: "resp-marketing",
    role_name: "Responsabile marketing",
    short_label: "Marketing",
    person_asset: null, // import personMarketing from "@/assets/meeting-room/layers/person-marketing.webp"
    label_position: { top: "52.96%", left: "10.11%" },
    seat_id: "left-1",
    z_index: 9,
  },
  {
    agent_id: "social-media-manager",
    role_name: "Social media manager",
    short_label: "Social media",
    person_asset: null, // import personSocialMedia from "@/assets/meeting-room/layers/person-social-media.webp"
    label_position: { top: "39.39%", left: "16.45%" },
    seat_id: "left-2",
    z_index: 7,
  },
  {
    agent_id: "resp-advertising",
    role_name: "Specialista advertising",
    short_label: "Advertising",
    person_asset: null, // import personAdvertising from "@/assets/meeting-room/layers/person-advertising.webp"
    label_position: { top: "33.12%", left: "25.52%" },
    seat_id: "left-3",
    z_index: 4,
  },
  {
    agent_id: "lead-gen-specialist",
    role_name: "Lead generation specialist",
    short_label: "Lead generation",
    person_asset: null, // import personLeadGeneration from "@/assets/meeting-room/layers/person-lead-generation.webp"
    label_position: { top: "28.01%", left: "31.24%" },
    seat_id: "left-4",
    z_index: 3,
  },
  {
    agent_id: "specialista-nurturing",
    role_name: "Specialista nurturing",
    short_label: "Nurturing",
    person_asset: null, // import personNurturing from "@/assets/meeting-room/layers/person-nurturing.webp"
    label_position: { top: "25.14%", left: "38.44%" },
    seat_id: "left-5",
    z_index: 1,
  },
  {
    agent_id: "analista-performance",
    role_name: "Analista performance",
    short_label: "Performance",
    person_asset: null, // import personPerformance from "@/assets/meeting-room/layers/person-performance.webp"
    label_position: { top: "25.81%", left: "62.42%" },
    seat_id: "right-1",
    z_index: 2,
  },
  {
    agent_id: "appointment-setter",
    role_name: "Appointment setter",
    short_label: "Appointment setter",
    person_asset: null, // import personAppointmentSetter from "@/assets/meeting-room/layers/person-appointment-setter.webp"
    label_position: { top: "33.84%", left: "70.86%" },
    seat_id: "right-2",
    z_index: 5,
  },
  {
    agent_id: "copywriter",
    role_name: "Copywriter",
    short_label: "Copywriter",
    person_asset: null, // import personCopywriter from "@/assets/meeting-room/layers/person-copywriter.webp"
    label_position: { top: "38.05%", left: "78.82%" },
    seat_id: "right-3",
    z_index: 6,
  },
  {
    agent_id: "resp-compliance",
    role_name: "Responsabile compliance",
    short_label: "Compliance",
    person_asset: null, // import personCompliance from "@/assets/meeting-room/layers/person-compliance.webp"
    label_position: { top: "49.81%", left: "86.77%" },
    seat_id: "right-4",
    z_index: 8,
  },
];

// Coordinatore ACTELYA: presenza digitale sullo schermo, separata, sempre
// visibile — non fa mai parte di activeAgentIds (vedi adapter.js).
export const COORDINATOR_AGENT = {
  agent_id: "coordinatore-actelya",
  role_name: "Coordinatore ACTELYA",
  short_label: "Coordinatore",
  label_position: { top: "14%", left: "50%" },
  seat_id: "screen",
};

export function getAgentById(agentId) {
  return AGENT_REGISTRY.find((a) => a.agent_id === agentId) || null;
}

// ---------------- Validazioni di sviluppo ----------------
// Nessun accesso a rete, nessun effetto in produzione: solo controlli di
// coerenza del registry statico, eseguiti una volta al caricamento.
function validateRegistry() {
  const ids = AGENT_REGISTRY.map((a) => a.agent_id);
  const duplicates = [...new Set(ids.filter((id, i) => ids.indexOf(id) !== i))];
  if (duplicates.length > 0) {
    console.error(`[agentRegistry] agent_id duplicati nel registry: ${duplicates.join(", ")}`);
  }
  for (const agent of AGENT_REGISTRY) {
    if (!agent.label_position?.top || !agent.label_position?.left || !agent.seat_id) {
      console.error(`[agentRegistry] voce incompleta per agent_id "${agent.agent_id}"`);
    }
  }
}

if (process.env.NODE_ENV === "development") {
  validateRegistry();
}
