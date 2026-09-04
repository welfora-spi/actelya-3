// Elenco leggibile dei task del piano appena creato, con priorita'/
// scadenza validate dalla proposta LLM quando presenti (llm_priority/
// llm_deadline: campi additivi sul task M2, mai un secondo DAG) e le
// dipendenze dichiarate — MAI JSON grezzo (item 14, CEO Agent 100% reale).
export default function TasksList({ tasks }) {
  if (!tasks?.length) return null;
  return (
    <div data-testid="tasks-list" className="space-y-1.5">
      <div className="label-caps">Attivita' del piano</div>
      {tasks.map((t) => (
        <div key={t.id} className="text-xs border border-border/60 rounded-sm px-2.5 py-2 flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-foreground font-medium">{t.name}</span>
            {t.depends_on?.length > 0 && (
              <span className="text-[10px] text-muted-foreground font-mono">dipende da {t.depends_on.length} task</span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            {t.llm_priority && (
              <span className="text-[10px] font-mono rounded-sm border border-border px-1.5 py-0.5">{t.llm_priority}</span>
            )}
            {t.llm_deadline && (
              <span className="text-[10px] font-mono text-muted-foreground">{t.llm_deadline}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
