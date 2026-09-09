// Modalità (REALE/SIMULAZIONE/MISTA) di un piano — derivata SEMPRE dai task
// del piano stesso, mai dalla sola impostazione ai_real_mode CORRENTE
// dell'organizzazione (quella puo' essere cambiata dopo la creazione del
// piano: dice cosa l'organizzazione farebbe ORA, non cosa questo piano
// specifico e' configurato a fare). Stessa funzione usata sia dal dettaglio
// piano (PlanDetail.jsx) sia da Sala Riunioni (adapter.js) — mai due
// logiche diverse che possono mostrare etichette discordanti per lo stesso
// piano.
//
// Segnale per task, in ordine di affidabilità:
// - task.approved_mode: impostato SOLO al momento dell'approvazione
//   (m2/engine.py), congelato per sempre da li' in poi — il piu' affidabile
//   quando presente (il piano e' gia' stato approvato).
// - task.inputs.deliverable_override.mode: impostato alla CREAZIONE per i
//   task 'content_item' (brain/service.py) — l'unico segnale disponibile
//   prima dell'approvazione per questo tipo di task.
// Un task senza nessuno dei due non da' alcun segnale (non e' ne' REALE ne'
// SIMULATO in modo verificabile dai dati disponibili).
export function derivePlanMode(tasks) {
  const perTask = (tasks || []).map(
    (t) => t.approved_mode || t.inputs?.deliverable_override?.mode || null
  );
  const known = perTask.filter(Boolean);
  if (known.length === 0) {
    return { label: "SIMULAZIONE", certain: false, reason: "nessun task del piano dichiara una modalità: assunta SIMULAZIONE per difetto" };
  }
  const unique = [...new Set(known)];
  if (unique.length > 1) {
    return { label: "MISTA", certain: true, reason: "i task del piano non sono tutti nella stessa modalità" };
  }
  const certain = known.length === perTask.length;
  return {
    label: unique[0],
    certain,
    reason: certain ? null : "alcuni task non dichiarano ancora una modalità propria",
  };
}
