"""Brain — integrazione verticale minima (Fase 1) del "cervello" selettivo
importato da ACTELYA originale sul corpo operativo M2 di ACTELYA 2.

Nessun modulo di m2/ viene modificato: questo pacchetto aggiunge SOLO
classificazione dell'obiettivo con contesto ricco, triage, selezione dinamica
delle capacita' di produzione e un gateway astratto (mock) per il contenuto,
collegati al planner/motore M2 esistente tramite il meccanismo gia' presente
di deliverable_override (m2/engine.py)."""
