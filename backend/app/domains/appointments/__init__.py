"""Appointment Setter — dominio specialistico per proporre e prenotare
appuntamenti reali su un calendario esterno (Google Calendar / Microsoft
Graph / Calendly), sempre a partire da lead già approvati (mai un contatto
inventato) e sempre dietro approvazione umana esplicita prima dell'invio o
della prenotazione. Nessuna prenotazione è mai dichiarata confermata senza
una conferma verificabile del provider (o del fake adapter nei test)."""
