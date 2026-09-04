"""Meta Graph API — tassonomia degli errori (item 16, DECISIONE UFFICIALE
"100% REALE"). Stesso principio di RequestyErroreSanificato/
RunwayErroreSanificato: ogni eccezione della libreria HTTP o della risposta
Graph API viene rimappata qui, MAI un traceback grezzo o un frammento di
token verso il chiamante/l'audit/i log."""
from __future__ import annotations


class MetaConnectorError(Exception):
    """Base di tutti gli errori del connector Meta."""

    def __init__(self, codice: str, messaggio: str):
        self.codice = codice
        self.messaggio = messaggio
        super().__init__(messaggio)


class MetaNotConfigured(MetaConnectorError):
    """Nessuna credenziale/connessione Meta configurata per questa
    organizzazione (o mancano campi obbligatori: page_id, token, ...)."""

    def __init__(self, messaggio: str = "Nessuna connessione Meta configurata per questa organizzazione."):
        super().__init__("non_configurato", messaggio)


class MetaAuthError(MetaConnectorError):
    """Token assente, scaduto o rifiutato da Meta (OAuthException, codice 190)."""

    def __init__(self, messaggio: str = "Credenziale Meta non valida, scaduta o rifiutata."):
        super().__init__("autenticazione", messaggio)


class MetaPermissionError(MetaConnectorError):
    """Permesso/scope mancante per l'azione richiesta (es. pages_manage_posts,
    instagram_content_publish)."""

    def __init__(self, messaggio: str = "Permesso Meta mancante per questa azione."):
        super().__init__("permesso_negato", messaggio)


class MetaRateLimitError(MetaConnectorError):
    """Limite di frequenza Meta raggiunto (codici 4/17/32/613, o HTTP 429)."""

    def __init__(self, messaggio: str = "Limite di frequenza Meta raggiunto.", retry_after: float | None = None):
        super().__init__("limite_frequenza", messaggio)
        self.retry_after = retry_after


class MetaMediaProcessingError(MetaConnectorError):
    """Il container media Instagram e' terminato in ERROR durante il
    processing (media non valido, formato non supportato, url irraggiungibile)."""

    def __init__(self, messaggio: str = "Elaborazione del media Meta fallita."):
        super().__init__("media_non_valido", messaggio)


class MetaPublishError(MetaConnectorError):
    """Errore generico durante la pubblicazione (risposta Graph API di errore
    non riconducibile alle categorie sopra)."""

    def __init__(self, messaggio: str = "Errore durante la pubblicazione su Meta."):
        super().__init__("errore_pubblicazione", messaggio)


class MetaTimeout(MetaConnectorError):
    """La richiesta e' stata inviata ma nessuna risposta e' arrivata entro il
    timeout previsto: l'esito reale (pubblicato o no) NON e' noto — mai
    trattato come un fallimento certo, mai riprovato alla cieca (vedi
    domains/social_publishing.py, stato PUBLISH_UNCERTAIN)."""

    def __init__(self, messaggio: str = "Nessuna risposta da Meta entro il timeout: esito non verificabile."):
        super().__init__("esito_incerto", messaggio)


class MetaInvalidAccount(MetaConnectorError):
    """Page ID / Instagram Business Account ID non valido, non collegato
    all'utente/token, o non trovato."""

    def __init__(self, messaggio: str = "Account Facebook/Instagram non valido o non raggiungibile con questo token."):
        super().__init__("account_non_valido", messaggio)
