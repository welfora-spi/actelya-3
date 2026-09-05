"""Correzione regressione (vs ACTELYA 2): rate limit GENERALE per IP su
POST /auth/login, ridotto a 10 tentativi/minuto (di default) e reso
configurabile via LOGIN_RATE_LIMIT_PER_MINUTE — distinto e più severo del
lockout per-credenziale esistente (MAX_FAILED/LOCK_MINUTES in auth.py,
invariato: blocca uno specifico IP+email dopo tentativi falliti ripetuti,
indipendentemente da questo rate limit generale).

Due livelli di test:
- diretto sul meccanismo condiviso deps.rate_limit() con una chiave dedicata
  (mai la stessa chiave usata dal server live in esecuzione: eviterebbe di
  esaurire il budget condiviso per gli altri test che effettuano un login
  reale in questa stessa suite);
- HTTP live sull'endpoint reale, per verificare che la costante sia
  effettivamente cablata in POST /auth/login (non solo che il meccanismo
  generico funzioni)."""
import importlib
import uuid

import pytest
import requests
from fastapi import HTTPException

from app.deps import rate_limit
from conftest import API_URL as API


# ==================== Meccanismo generico (deps.rate_limit) ====================
def test_rate_limit_consente_fino_al_massimo_configurato():
    key = f"test-rate-limit-{uuid.uuid4().hex[:12]}"
    for _ in range(5):
        rate_limit(key, max_calls=5, window_seconds=60)  # non deve sollevare


def test_rate_limit_blocca_oltre_il_massimo_configurato():
    key = f"test-rate-limit-{uuid.uuid4().hex[:12]}"
    for _ in range(5):
        rate_limit(key, max_calls=5, window_seconds=60)
    with pytest.raises(HTTPException) as exc:
        rate_limit(key, max_calls=5, window_seconds=60)
    assert exc.value.status_code == 429


def test_rate_limit_e_indipendente_per_chiave():
    key_a = f"test-rate-limit-a-{uuid.uuid4().hex[:12]}"
    key_b = f"test-rate-limit-b-{uuid.uuid4().hex[:12]}"
    for _ in range(10):
        rate_limit(key_a, max_calls=10, window_seconds=60)
    # key_b non ha consumato nulla del budget di key_a: la prima chiamata resta consentita.
    rate_limit(key_b, max_calls=10, window_seconds=60)


# ==================== Configurabilità della costante (auth.py) ====================
def test_login_rate_limit_default_e_dieci_al_minuto(monkeypatch):
    monkeypatch.delenv("LOGIN_RATE_LIMIT_PER_MINUTE", raising=False)
    from app.domains import auth as auth_module
    reloaded = importlib.reload(auth_module)
    try:
        assert reloaded.LOGIN_RATE_LIMIT_PER_MINUTE == 10
    finally:
        importlib.reload(auth_module)  # ripristina lo stato del modulo per gli altri test


def test_login_rate_limit_configurabile_via_env(monkeypatch):
    monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_MINUTE", "3")
    from app.domains import auth as auth_module
    reloaded = importlib.reload(auth_module)
    try:
        assert reloaded.LOGIN_RATE_LIMIT_PER_MINUTE == 3
    finally:
        monkeypatch.delenv("LOGIN_RATE_LIMIT_PER_MINUTE", raising=False)
        importlib.reload(auth_module)  # ripristina il default per gli altri test/il processo server


# ==================== HTTP live: la costante è davvero cablata in /auth/login ====================
def test_http_login_oltre_il_limite_generale_risponde_429():
    """Consuma deliberatamente l'intero budget generale PER IP (credenziali
    errate, nessuno stato utente modificato) e verifica che la richiesta
    successiva riceva 429 — non 401. Ogni tentativo usa un'email DIVERSA:
    il lockout per-credenziale (MAX_FAILED=5 tentativi sulla stessa coppia
    ip+email) e' un meccanismo distinto e non deve mascherare il rate limit
    generale che questo test verifica. Nota: il rate limit generale e' per
    IP e condiviso dal processo server con l'intera suite; questo test e'
    l'unico in tutta la suite a consumarlo deliberatamente fino al limite."""
    def _tentativo():
        body = {"email": f"non-esiste-{uuid.uuid4().hex[:10]}@example.com", "password": "sbagliata"}
        return requests.post(f"{API}/auth/login", json=body, timeout=15)

    ultima = None
    for _ in range(10):
        ultima = _tentativo()
        if ultima.status_code == 429:
            break  # limite già raggiunto da chiamate precedenti nella stessa finestra: comunque verificato
    else:
        ultima = _tentativo()
    assert ultima.status_code == 429, ultima.text
    assert "Troppe richieste" in ultima.json()["detail"]
