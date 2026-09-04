// Un limite generale non ancora configurato vale 0 sia in domains/budget.py
// che in domains/stats.py (stessa convenzione usata da m2/engine.py::budget_check
// per NON bloccare la spesa quando il limite e' 0/assente). Mostrare in quel
// caso "$-0.00xxx" come residuo farebbe credere che il budget sia stato
// sforato: non e' vero, semplicemente nessuno l'ha ancora impostato.
export function formatBudgetLine(limit, residual) {
  if (!limit) return "Nessun limite impostato";
  return `$${(residual ?? 0).toFixed(4)} / $${limit.toFixed(2)}`;
}

export function isBudgetConfigured(limit) {
  return Boolean(limit);
}
