"""Professional Tool Registry — fonte di verità canonica, lato backend, di
OGNI strumento/provider professionale che ACTELYA può usare. Il frontend non
duplica mai queste informazioni: le legge sempre da qui tramite API (vedi
router.py). Nessun agente deve mai chiamare un SDK/endpoint esterno
aggirando questo registro — la catena di esecuzione vincolante è:
Agente -> Skill -> Professional Tool Registry -> permessi -> connessione ->
consenso -> approvazione -> budget/costo -> adapter -> validazione ->
persistenza -> audit -> handoff/deliverable."""
