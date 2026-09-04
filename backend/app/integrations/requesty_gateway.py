"""Gateway Requesty reale — porting minimale di gateways/requesty.py di ACTELYA v1.

API compatibile OpenAI (Requesty Router). Ogni eccezione della SDK viene rimappata
in un errore sanificato (codice stabile + messaggio senza mai un traceback grezzo,
una URL con query string o un frammento di credenziale): nessuna eccezione grezza
arriva mai al chiamante (router HTTP o agente reel).

Il modulo 'openai' viene importato SOLO dentro _client(), quindi non viene mai
caricato finche' non serve davvero costruire un client HTTP.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .requesty_secrets import leggi_api_key_requesty

BASE_URL = "https://router.requesty.ai/v1"
TIMEOUT_DEFAULT_SECONDI = 20.0

# Prompt fisso del test diagnostico manuale: mai testo inserito dall'utente, mai
# contenuto reale di un task.
PROMPT_TEST_DIAGNOSTICO = "Rispondi esclusivamente con: OK"
MAX_TOKENS_TEST_DIAGNOSTICO = 10
TIMEOUT_TEST_DIAGNOSTICO_SECONDI = 20.0


class RequestyNonConfigurato(Exception):
    """Nessuna credenziale presente nel Credential Manager."""


class RequestyErroreSanificato(Exception):
    """Errore di Requesty gia' sanificato per la UI: codice stabile
    ('autenticazione', 'modello_non_disponibile', 'timeout', 'rete',
    'limite_frequenza', 'permesso_negato', 'esito_incerto', 'errore_api',
    'errore_sconosciuto') + messaggio senza mai un traceback grezzo, una URL con
    query string o un frammento di credenziale."""

    def __init__(self, codice: str, messaggio: str):
        self.codice = codice
        self.messaggio = messaggio
        super().__init__(messaggio)


@dataclass
class RisultatoTestRequesty:
    esito: str  # "OK" | "ERRORE"
    codice_errore: Optional[str]
    messaggio: str
    modello_effettivo: Optional[str]
    latenza_ms: Optional[int]
    input_tokens: Optional[int]
    output_tokens: Optional[int]

    def come_dict(self) -> dict:
        return {
            "esito": self.esito,
            "codice_errore": self.codice_errore,
            "messaggio": self.messaggio,
            "modello_effettivo": self.modello_effettivo,
            "latenza_ms": self.latenza_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass
class RisultatoGenerazioneRequesty:
    testo: str
    modello_effettivo: Optional[str]
    latenza_ms: int
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    troncata: bool


@dataclass
class RisultatoImmagineRequesty:
    url: Optional[str]              # URL esterno, quando il modello lo fornisce (es. dall-e-3)
    b64_json: Optional[str]         # base64 grezzo, valore DI DEFAULT per gpt-image-1 (vedi genera_immagine)
    mime_type: str                  # dedotto da output_format, mai inventato: default 'image/png'
    modello_effettivo: Optional[str]
    latenza_ms: int
    input_tokens: Optional[int]     # openai.types.ImagesResponse.usage: reale, solo per gpt-image-1
    output_tokens: Optional[int]


def _client(timeout: float):
    api_key = leggi_api_key_requesty()
    if not api_key:
        raise RequestyNonConfigurato("Nessuna credenziale Requesty configurata nel Credential Manager.")

    import openai  # libreria compatibile OpenAI: importata solo qui, mai a livello di modulo

    client = openai.OpenAI(api_key=api_key, base_url=BASE_URL, timeout=timeout, max_retries=0)
    return client, openai


def _chiamata_sanificata(client, openai_mod, **kwargs):
    """UNA chiamata chat.completions.create, con ogni eccezione della SDK rimappata
    in RequestyErroreSanificato. max_retries=0 (impostato in _client): nessun retry
    automatico, in nessun caso."""
    try:
        return client.chat.completions.create(**kwargs)
    except openai_mod.AuthenticationError as exc:
        raise RequestyErroreSanificato("autenticazione", "Credenziale Requesty non valida o rifiutata.") from exc
    except openai_mod.NotFoundError as exc:
        raise RequestyErroreSanificato(
            "modello_non_disponibile", f"Il modello '{kwargs.get('model')}' non risulta disponibile su Requesty."
        ) from exc
    except openai_mod.APITimeoutError as exc:
        # httpx (usato dalla SDK OpenAI-compatibile) segnala con la STESSA eccezione
        # sia un timeout in fase di connessione (la richiesta NON e' mai partita:
        # sicuro segnalare "rete" e permettere un nuovo tentativo) sia un timeout in
        # attesa della risposta (la richiesta E' stata inviata, Requesty puo' averla
        # gia' elaborata e persino addebitata: l'esito resta IGNOTO finche' non
        # verificato). Distinzione fatta ispezionando la causa originale httpx, non
        # un'euristica sul testo.
        import httpx

        causa = getattr(exc, "__cause__", None)
        if isinstance(causa, httpx.ConnectTimeout):
            raise RequestyErroreSanificato(
                "rete", "Impossibile connettersi a Requesty entro il timeout previsto (richiesta mai inviata)."
            ) from exc
        raise RequestyErroreSanificato(
            "esito_incerto",
            "La richiesta e' stata inviata a Requesty ma nessuna risposta e' arrivata entro il timeout previsto: "
            "l'esito reale (eventuale risposta e relativo costo) non e' noto e va verificato prima di ripetere la chiamata.",
        ) from exc
    except openai_mod.APIConnectionError as exc:
        raise RequestyErroreSanificato("rete", "Impossibile raggiungere Requesty (errore di rete, richiesta mai inviata).") from exc
    except openai_mod.RateLimitError as exc:
        raise RequestyErroreSanificato("limite_frequenza", "Limite di frequenza Requesty raggiunto.") from exc
    except openai_mod.PermissionDeniedError as exc:
        raise RequestyErroreSanificato(
            "permesso_negato", "Permesso negato da Requesty (credito esaurito o accesso non consentito)."
        ) from exc
    except openai_mod.APIStatusError as exc:
        raise RequestyErroreSanificato("errore_api", f"Errore Requesty (status {exc.status_code}).") from exc
    except Exception as exc:  # difesa finale: mai un'eccezione grezza non mappata
        raise RequestyErroreSanificato("errore_sconosciuto", "Errore imprevisto durante la chiamata a Requesty.") from exc


def test_diagnostico(model_id_requesty: str) -> RisultatoTestRequesty:
    """Smoke test manuale, UNA sola chiamata, prompt fisso, costo minimo. Funziona
    solo se esplicitamente invocato da un endpoint che ha gia' richiesto conferma
    (vedi domains/connections.py -> test_real): non fa parte di alcuna
    orchestrazione automatica."""
    inizio = time.monotonic()
    try:
        client, openai_mod = _client(TIMEOUT_TEST_DIAGNOSTICO_SECONDI)
    except RequestyNonConfigurato as exc:
        return RisultatoTestRequesty(
            esito="ERRORE", codice_errore="credenziale_assente", messaggio=str(exc),
            modello_effettivo=None, latenza_ms=None, input_tokens=None, output_tokens=None,
        )

    try:
        risposta = _chiamata_sanificata(
            client, openai_mod,
            model=model_id_requesty, max_tokens=MAX_TOKENS_TEST_DIAGNOSTICO, temperature=0,
            messages=[{"role": "user", "content": PROMPT_TEST_DIAGNOSTICO}],
        )
    except RequestyErroreSanificato as exc:
        return RisultatoTestRequesty(
            esito="ERRORE", codice_errore=exc.codice, messaggio=exc.messaggio,
            modello_effettivo=None, latenza_ms=int((time.monotonic() - inizio) * 1000),
            input_tokens=None, output_tokens=None,
        )
    except Exception:  # difesa finale: mai un traceback grezzo verso la UI
        return RisultatoTestRequesty(
            esito="ERRORE", codice_errore="sconosciuto", messaggio="Errore imprevisto durante il test diagnostico.",
            modello_effettivo=None, latenza_ms=int((time.monotonic() - inizio) * 1000),
            input_tokens=None, output_tokens=None,
        )

    latenza_ms = int((time.monotonic() - inizio) * 1000)
    scelta = risposta.choices[0] if getattr(risposta, "choices", None) else None
    testo = scelta.message.content if scelta is not None and getattr(scelta, "message", None) else None
    if not testo:
        return RisultatoTestRequesty(
            esito="ERRORE", codice_errore="risposta_non_valida", messaggio="Risposta ricevuta ma priva di contenuto testuale.",
            modello_effettivo=getattr(risposta, "model", None), latenza_ms=latenza_ms,
            input_tokens=None, output_tokens=None,
        )

    uso = getattr(risposta, "usage", None)
    return RisultatoTestRequesty(
        esito="OK", codice_errore=None, messaggio="Connessione riuscita.",
        modello_effettivo=getattr(risposta, "model", None), latenza_ms=latenza_ms,
        input_tokens=getattr(uso, "prompt_tokens", None) if uso else None,
        output_tokens=getattr(uso, "completion_tokens", None) if uso else None,
    )


def genera_json(
    model_id_requesty: str,
    system: str,
    messaggio_utente: str,
    schema_json: dict,
    schema_nome: str,
    max_tokens: int,
    timeout: Optional[float] = None,
    temperature: Optional[float] = 0.7,
) -> RisultatoGenerazioneRequesty:
    """Chiamata reale singola per generare contenuto strutturato (JSON) via
    Requesty. Usata dall'agente reel (domains/reel.py): questa funzione non
    decide mai quale modello usare, si limita a trasportare la richiesta. Nessun
    retry automatico (max_retries=0 in _client): un esito incerto (timeout dopo
    l'invio) va sempre segnalato al chiamante, mai ritentato in automatico."""
    client, openai_mod = _client(timeout or TIMEOUT_DEFAULT_SECONDI)
    response_format = {"type": "json_schema", "json_schema": {"name": schema_nome, "schema": schema_json, "strict": False}}
    inizio = time.monotonic()
    risposta = _chiamata_sanificata(
        client, openai_mod,
        model=model_id_requesty, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": messaggio_utente}],
        temperature=temperature, response_format=response_format,
    )
    latenza_ms = int((time.monotonic() - inizio) * 1000)
    scelta = risposta.choices[0] if getattr(risposta, "choices", None) else None
    testo = scelta.message.content if scelta is not None and getattr(scelta, "message", None) else None
    troncata = getattr(scelta, "finish_reason", None) == "length" if scelta is not None else False
    if not testo:
        raise RequestyErroreSanificato("risposta_non_valida", "Risposta ricevuta ma priva di contenuto testuale.")
    uso = getattr(risposta, "usage", None)
    return RisultatoGenerazioneRequesty(
        testo=testo,
        modello_effettivo=getattr(risposta, "model", None),
        latenza_ms=latenza_ms,
        input_tokens=getattr(uso, "prompt_tokens", None) if uso else None,
        output_tokens=getattr(uso, "completion_tokens", None) if uso else None,
        troncata=troncata,
    )


_MIME_PER_FORMATO = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}


def genera_immagine(
    model_id_requesty: str, prompt: str, size: str = "1024x1536",
    quality: str = "auto", output_format: str = "png", timeout: Optional[float] = None,
) -> RisultatoImmagineRequesty:
    """Chiamata reale singola di generazione immagine (POST /v1/images/generations,
    confermato supportato da Requesty: docs.requesty.ai/api-reference/endpoint/
    images-generations-create). Stesso client OpenAI-compatibile gia' usato per
    il testo (base_url router.requesty.ai): nessun secondo gateway HTTP.

    NON richiede response_format='url': per gpt-image-1 il campo 'url' e'
    esplicitamente 'Unsupported' secondo lo schema ufficiale della SDK
    (openai.types.image.Image) -- il modello restituisce SEMPRE b64_json,
    indipendentemente da cosa si chiede. Fidarsi ciecamente di '.url' (come
    faceva una versione precedente di questa funzione) produce un
    RisultatoImmagineRequesty con url=None senza sollevare errore: e' la causa
    esatta di un bug osservato in prova reale (IMMAGINE_PRONTA dichiarata
    senza alcun asset visualizzabile). Qui SI VERIFICA sempre che almeno uno
    tra url/b64_json sia realmente presente E non vuoto prima di ritornare un
    risultato: mai un esito 'pronto' senza un asset utilizzabile."""
    client, openai_mod = _client(timeout or TIMEOUT_DEFAULT_SECONDI)
    inizio = time.monotonic()
    try:
        risposta = client.images.generate(
            model=model_id_requesty, prompt=prompt, size=size, quality=quality,
            output_format=output_format, n=1,
        )
    except openai_mod.OpenAIError as exc:
        raise _sanifica_openai(exc, openai_mod) from exc
    except Exception as exc:
        raise RequestyErroreSanificato("errore_sconosciuto", "Errore imprevisto durante la generazione immagine.") from exc
    latenza_ms = int((time.monotonic() - inizio) * 1000)

    dato = risposta.data[0] if getattr(risposta, "data", None) else None
    url = getattr(dato, "url", None) if dato else None
    b64 = getattr(dato, "b64_json", None) if dato else None
    # Asset realmente utilizzabile: una stringa non vuota, non solo whitespace.
    # Un b64_json vuoto ("") o None non e' MAI trattato come pronto.
    ha_asset = bool((url or "").strip()) or bool((b64 or "").strip())
    if not ha_asset:
        raise RequestyErroreSanificato("risposta_non_valida", "Risposta ricevuta ma priva di un'immagine utilizzabile.")

    formato_effettivo = getattr(risposta, "output_format", None) or output_format
    uso = getattr(risposta, "usage", None)  # solo per gpt-image-1, reale (mai stimato)
    return RisultatoImmagineRequesty(
        url=url, b64_json=b64, mime_type=_MIME_PER_FORMATO.get(formato_effettivo, "image/png"),
        modello_effettivo=model_id_requesty, latenza_ms=latenza_ms,
        input_tokens=getattr(uso, "input_tokens", None) if uso else None,
        output_tokens=getattr(uso, "output_tokens", None) if uso else None,
    )


def _sanifica_openai(exc, mod) -> RequestyErroreSanificato:
    """Stessa mappatura di _chiamata_sanificata, riusabile per chiamate SDK
    diverse da chat.completions (es. images.generate)."""
    if isinstance(exc, mod.AuthenticationError):
        return RequestyErroreSanificato("autenticazione", "Credenziale Requesty non valida o rifiutata.")
    if isinstance(exc, mod.NotFoundError):
        return RequestyErroreSanificato("modello_non_disponibile", "Modello non disponibile su Requesty.")
    if isinstance(exc, mod.RateLimitError):
        return RequestyErroreSanificato("limite_frequenza", "Limite di frequenza Requesty raggiunto.")
    if isinstance(exc, mod.PermissionDeniedError):
        return RequestyErroreSanificato("permesso_negato", "Permesso negato da Requesty (credito esaurito o accesso non consentito).")
    if isinstance(exc, mod.APITimeoutError):
        return RequestyErroreSanificato("esito_incerto", "Nessuna risposta entro il timeout: esito non noto, non ripetere automaticamente.")
    if isinstance(exc, mod.APIConnectionError):
        return RequestyErroreSanificato("rete", "Impossibile raggiungere Requesty (errore di rete, richiesta mai inviata).")
    if isinstance(exc, mod.APIStatusError):
        return RequestyErroreSanificato("errore_api", f"Errore Requesty (status {exc.status_code}).")
    return RequestyErroreSanificato("errore_sconosciuto", "Errore imprevisto durante la chiamata a Requesty.")
