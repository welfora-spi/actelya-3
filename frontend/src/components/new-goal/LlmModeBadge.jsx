// Mostra in forma leggibile (mai JSON grezzo) se la comprensione del CEO
// Agent per questo obiettivo e' passata da un provider LLM reale o dal
// planner deterministico, e perche' (item 14, CEO Agent 100% reale).
export default function LlmModeBadge({ llmUnderstanding }) {
  if (!llmUnderstanding) return null;
  const reale = llmUnderstanding.mode === "REALE";

  return (
    <div
      data-testid="llm-mode-badge"
      className={
        "text-xs rounded-sm border px-2.5 py-1.5 flex items-center gap-2 flex-wrap " +
        (reale
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
          : "border-border bg-muted/30 text-muted-foreground")
      }
    >
      <span className="font-mono font-medium">{reale ? "Comprensione: REALE" : "Comprensione: deterministica"}</span>
      {reale && llmUnderstanding.provider_effettivo && (
        <span>
          via <b>{llmUnderstanding.provider_effettivo}</b>
          {llmUnderstanding.modello_effettivo ? ` (${llmUnderstanding.modello_effettivo})` : ""}
        </span>
      )}
      {!reale && <span>{llmUnderstanding.motivo}</span>}
    </div>
  );
}
