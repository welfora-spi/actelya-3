"""Brain — sottopacchetto audit (Blocco C).

memory_audit.py: registro append-only, in-memory, delle decisioni del
brain (triage, selezione agenti, chiarimenti, blocchi, handoff, esiti). Da
non confondere con la collezione MongoDB `audit_logs` già usata da
m2/engine.py e m2/reviews.py (invariate, non toccate qui): questo è un
audit separato, in-memory, specifico del brain, con un'interfaccia
(AuditSink) pensata per poter in futuro scrivere anche sull'audit M2 senza
cambiare i chiamanti."""
