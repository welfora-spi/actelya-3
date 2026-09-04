"""Gateway Runway (video generativo) reale -- SDK ufficiale 'runwayml' (Stainless,
stessa famiglia di client di 'openai': stessa gerarchia di eccezioni, stesso
stile). Nessuna implementazione HTTP grezza: usiamo SOLO endpoint documentati
dall'SDK ufficiale (text_to_video, tasks, organization).

Ogni eccezione della SDK viene rimappata in un errore sanificato (stesso
principio di requesty_gateway.py): nessuna eccezione grezza, nessun frammento
di credenziale, mai un traceback verso il chiamante.

La chiave NON vive nel Credential Manager di Windows (a differenza di
Requesty, portato 1:1 da ACTELYA v1): vive cifrata lato server nella
collezione 'video_connections' (Fernet + MASTER_KEY, vedi app/security.py),
come richiesto esplicitamente per questo provider. Questo modulo non legge mai
Mongo direttamente: riceve la chiave in chiaro SOLO dal chiamante autorizzato
(domains/reel.py), al momento di un'azione gia' confermata."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

TIMEOUT_TEST_DIAGNOSTICO_SECONDI = 20.0
TIMEOUT_DEFAULT_SECONDI = 30.0

# Stati Runway (SDK ufficiale, discriminante 'status' di TaskRetrieveResponse):
# PENDING | THROTTLED | RUNNING | CANCELLED | FAILED | SUCCEEDED.
STATI_TERMINALI = frozenset({"CANCELLED", "FAILED", "SUCCEEDED"})


class RunwayNonConfigurato(Exception):
    pass


class RunwayErroreSanificato(Exception):
    """Stesso principio di RequestyErroreSanificato: codice stabile + messaggio
    mai contenente un frammento di credenziale o un traceback grezzo."""

    def __init__(self, codice: str, messaggio: str):
        self.codice = codice
        self.messaggio = messaggio
        super().__init__(messaggio)


@dataclass
class RisultatoTestRunway:
    esito: str  # "OK" | "ERRORE"
    codice_errore: Optional[str]
    messaggio: str
    credit_balance: Optional[int]
    latenza_ms: Optional[int]

    def come_dict(self) -> dict:
        return {
            "esito": self.esito, "codice_errore": self.codice_errore, "messaggio": self.messaggio,
            "credit_balance": self.credit_balance, "latenza_ms": self.latenza_ms,
        }


@dataclass
class TaskAvviato:
    task_id: str
    stima_costo_credits: Optional[float]


@dataclass
class StatoTask:
    task_id: str
    status: str  # PENDING | THROTTLED | RUNNING | CANCELLED | FAILED | SUCCEEDED
    output_urls: list[str]
    costo_credits: Optional[float]  # valorizzato solo sugli stati terminali (SDK: cost.credits)
    progress: Optional[float]
    errore_messaggio: Optional[str]
    errore_codice: Optional[str]


def _client(api_key: str, timeout: float):
    if not api_key:
        raise RunwayNonConfigurato("Nessuna credenziale Runway configurata su questa connessione.")
    import runwayml  # importata solo qui: mai caricata finche' non serve davvero una chiamata

    return runwayml.RunwayML(api_key=api_key, timeout=timeout, max_retries=0), runwayml


def _sanifica(exc, mod) -> RunwayErroreSanificato:
    if isinstance(exc, mod.AuthenticationError):
        return RunwayErroreSanificato("autenticazione", "Credenziale Runway non valida o rifiutata.")
    if isinstance(exc, mod.PermissionDeniedError):
        return RunwayErroreSanificato("permesso_negato", "Permesso negato da Runway (credito esaurito o accesso non consentito).")
    if isinstance(exc, mod.RateLimitError):
        return RunwayErroreSanificato("limite_frequenza", "Limite di frequenza Runway raggiunto.")
    if isinstance(exc, (mod.BadRequestError, mod.UnprocessableEntityError)):
        return RunwayErroreSanificato("parametri_non_validi", "Parametri non validi per Runway (modello, durata o formato non supportati).")
    if isinstance(exc, mod.NotFoundError):
        return RunwayErroreSanificato("non_trovato", "Risorsa Runway non trovata (task o modello inesistente).")
    if isinstance(exc, mod.APITimeoutError):
        import httpx

        causa = getattr(exc, "__cause__", None)
        if isinstance(causa, httpx.ConnectTimeout):
            return RunwayErroreSanificato("rete", "Impossibile connettersi a Runway entro il timeout previsto (richiesta mai inviata).")
        return RunwayErroreSanificato(
            "esito_incerto",
            "La richiesta e' stata inviata a Runway ma nessuna risposta e' arrivata entro il timeout previsto: "
            "l'esito reale (ed eventuale addebito) non e' noto e va verificato prima di ripetere la chiamata.",
        )
    if isinstance(exc, mod.APIConnectionError):
        return RunwayErroreSanificato("rete", "Impossibile raggiungere Runway (errore di rete, richiesta mai inviata).")
    if isinstance(exc, mod.APIStatusError):
        return RunwayErroreSanificato("errore_api", f"Errore Runway (status {exc.status_code}).")
    return RunwayErroreSanificato("errore_sconosciuto", "Errore imprevisto durante la chiamata a Runway.")


def test_diagnostico(api_key: str) -> RisultatoTestRunway:
    """Test diagnostico a costo ZERO: organization.retrieve() e' un endpoint
    informativo (saldo crediti), non una generazione -- a differenza del test
    Requesty non ha nemmeno un costo minimo, ma resta comunque un'eccezione
    dichiarata raggiungibile SOLO dopo conferma esplicita (vedi
    domains/video_connections.py), per coerenza con ogni altra chiamata reale
    dell'app: nessuna chiamata esterna parte mai senza un comando esplicito."""
    inizio = time.monotonic()
    try:
        client, mod = _client(api_key, TIMEOUT_TEST_DIAGNOSTICO_SECONDI)
    except RunwayNonConfigurato as exc:
        return RisultatoTestRunway(esito="ERRORE", codice_errore="credenziale_assente", messaggio=str(exc),
                                   credit_balance=None, latenza_ms=None)
    try:
        org = client.organization.retrieve()
    except mod.RunwayMLError as exc:
        sanificato = _sanifica(exc, mod)
        return RisultatoTestRunway(esito="ERRORE", codice_errore=sanificato.codice, messaggio=sanificato.messaggio,
                                   credit_balance=None, latenza_ms=int((time.monotonic() - inizio) * 1000))
    except Exception:  # difesa finale: mai un traceback grezzo verso la UI
        return RisultatoTestRunway(esito="ERRORE", codice_errore="errore_sconosciuto", messaggio="Errore imprevisto durante il test diagnostico.",
                                   credit_balance=None, latenza_ms=int((time.monotonic() - inizio) * 1000))
    return RisultatoTestRunway(esito="OK", codice_errore=None, messaggio="Connessione riuscita.",
                               credit_balance=org.credit_balance, latenza_ms=int((time.monotonic() - inizio) * 1000))


def avvia_generazione_video(
    api_key: str, model: str, prompt_text: str, duration: int, ratio: str, timeout: Optional[float] = None,
) -> TaskAvviato:
    """UNA sola chiamata reale (text_to_video.create): avvia un task Runway
    asincrono, mai bloccante fino al risultato. Ritorna SOLO l'id del task e il
    costo massimo stimato: il video vero arriva in seguito via polling
    (recupera_stato_task), mai da questa funzione."""
    client, mod = _client(api_key, timeout or TIMEOUT_DEFAULT_SECONDI)
    try:
        risposta = client.text_to_video.create(model=model, prompt_text=prompt_text, duration=duration, ratio=ratio)
    except mod.RunwayMLError as exc:
        raise _sanifica(exc, mod) from exc
    except Exception as exc:
        raise RunwayErroreSanificato("errore_sconosciuto", "Errore imprevisto durante l'avvio della generazione video.") from exc
    return TaskAvviato(task_id=risposta.id, stima_costo_credits=getattr(risposta.estimated_cost, "credits", None))


def annulla_task(api_key: str, task_id: str, timeout: Optional[float] = None) -> bool:
    """Tentativo best-effort di annullamento (es. stima costo oltre il tetto
    configurato, task ancora PENDING): mai fatale se fallisce, il chiamante
    deve comunque registrare/mostrare l'accaduto."""
    try:
        client, mod = _client(api_key, timeout or TIMEOUT_TEST_DIAGNOSTICO_SECONDI)
        client.tasks.delete(task_id)
        return True
    except Exception:
        return False


def recupera_stato_task(api_key: str, task_id: str, timeout: Optional[float] = None) -> StatoTask:
    """Sola lettura (GET), MAI a pagamento: puo' essere interrogata quante
    volte serve senza alcun costo aggiuntivo."""
    client, mod = _client(api_key, timeout or TIMEOUT_TEST_DIAGNOSTICO_SECONDI)
    try:
        t = client.tasks.retrieve(task_id)
    except mod.RunwayMLError as exc:
        raise _sanifica(exc, mod) from exc
    except Exception as exc:
        raise RunwayErroreSanificato("errore_sconosciuto", "Errore imprevisto durante la verifica dello stato del task.") from exc

    status = t.status
    if status == "SUCCEEDED":
        return StatoTask(task_id=task_id, status=status, output_urls=list(t.output),
                         costo_credits=float(t.cost.credits), progress=1.0, errore_messaggio=None, errore_codice=None)
    if status == "FAILED":
        return StatoTask(task_id=task_id, status=status, output_urls=[], costo_credits=float(t.cost.credits),
                         progress=None, errore_messaggio=t.failure, errore_codice=getattr(t, "failure_code", None))
    if status == "CANCELLED":
        return StatoTask(task_id=task_id, status=status, output_urls=[], costo_credits=float(t.cost.credits),
                         progress=None, errore_messaggio="Task annullato.", errore_codice=None)
    if status == "RUNNING":
        return StatoTask(task_id=task_id, status=status, output_urls=[], costo_credits=None,
                         progress=t.progress, errore_messaggio=None, errore_codice=None)
    # PENDING | THROTTLED
    return StatoTask(task_id=task_id, status=status, output_urls=[], costo_credits=None,
                     progress=None, errore_messaggio=None, errore_codice=None)
