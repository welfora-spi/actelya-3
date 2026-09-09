"""Shared test configuration: repo-relative paths and admin credentials from env.

Never hardcode secrets or absolute paths in individual test files — import from here.
Portable across environments (no dependency on a fixed mount point like /app).
"""
import os
import time
import uuid
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_ENV = ROOT_DIR / "backend" / ".env"
FRONTEND_ENV = ROOT_DIR / "frontend" / ".env"


def read_env_file(path: Path, key: str, default: str = "") -> str:
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    except FileNotFoundError:
        pass
    return default


def load_base_url() -> str:
    url = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if not url:
        url = read_env_file(FRONTEND_ENV, "REACT_APP_BACKEND_URL")
    if not url:
        url = "http://localhost:8001"
    return url.rstrip("/")


BASE_URL = load_base_url()
API_URL = f"{BASE_URL}/api"

# Admin identity comes from backend/.env (never hardcoded); passwords come only from
# the environment so the repo never carries a working credential.
ADMIN_EMAIL = read_env_file(BACKEND_ENV, "ADMIN_EMAIL", "admin@example.com")
ADMIN_SEED_PASSWORD = os.environ.get("ADMIN_SEED_PASSWORD", "") or read_env_file(BACKEND_ENV, "ADMIN_PASSWORD", "")
ADMIN_TEST_PASSWORD = os.environ.get("ADMIN_TEST_PASSWORD", "") or ADMIN_SEED_PASSWORD


def register_tenant(company_name: str, *, password: str, sector: str = "Servizi",
                    website: str = "https://example.com", social_links=None, goal: str = "Crescere",
                    email: str | None = None) -> tuple[str, str]:
    """Registra un tenant di test contro il server live, con retry/backoff
    SOLO su 429 — il rate limit reale e condiviso su POST /tenant/register
    (deps.py::rate_limit, 10/60s per IP) non viene mai indebolito qui: tutti
    i test lo condividono dalla stessa macchina/IP, quindi una raffica di
    registrazioni provenienti da più file eseguiti in parallelo (pytest-
    xdist) può esaurirlo legittimamente. Questo è un problema di
    infrastruttura di test (contesa su una risorsa reale e volutamente
    severa, corretta in una fase precedente di questo stesso lavoro — mai
    un motivo per abbassarla), non un errore applicativo: si ritenta con
    backoff, non si allenta il limite né si cambia alcuna asserzione."""
    body = {
        "company_name": company_name, "sector": sector, "website": website,
        "social_links": social_links or [], "primary_goal": goal,
        "first_name": "Test", "last_name": "User",
        "email": email or f"test_{uuid.uuid4().hex[:12]}@example.com", "password": password,
    }
    ultima_risposta = None
    for tentativo in range(6):
        r = requests.post(f"{API_URL}/tenant/register", json=body, timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data["organization_id"], data["access_token"]
        if r.status_code != 429:
            raise AssertionError(f"Registrazione tenant fallita ({r.status_code}): {r.text}")
        ultima_risposta = r.text
        time.sleep(2 * (tentativo + 1))  # backoff crescente: 2s, 4s, 6s, 8s, 10s
    raise AssertionError(f"Registrazione tenant fallita: rate limit non liberato dopo i tentativi previsti ({ultima_risposta}).")


# ==================== Guardia: nessuna scrittura sul database reale dai test ====================
# app/audit.py importa un client Mongo GLOBALE ('from .db import db', legato
# a MONGO_URL/DB_NAME di backend/.env — oggi actelya3_dev, il database
# applicativo reale preservato), usato da tools/gateway.py::authorize/
# record_execution per ogni chiamata reale autorizzata da un agente. Un test
# Python che raggiunge quel percorso (es. content_creator/pipeline.py::
# generate_content_item) SENZA sostituire esplicitamente quella dipendenza
# scrive in silenzio nel database reale — accaduto davvero in questa
# sessione (9 record di audit rimossi a mano dopo la scoperta). Verificati
# tutti gli altri riferimenti globali raggiungibili dai test M2/Content
# Creator (tools/gateway.py, tools/cost_ledger.py, m2/engine.py::_audit,
# real_content_creator.py): ricevono tutti 'db' come parametro esplicito,
# nessun altro import globale in quei percorsi — solo app/audit.py::db resta
# esposto. Questa guardia lo rende impossibile per costruzione, non solo per
# disciplina di chi scrive il test: di default (autouse) 'app.audit.db' e'
# sostituito con una sentinella che fa fallire SUBITO qualunque accesso
# (prima di ogni scrittura reale) con un errore esplicito; un test che ha
# davvero bisogno di quel percorso deve ri-sostituirlo con il proprio
# database di test isolato via monkeypatch, dopo che questa fixture ha gia'
# girato (l'ordine di pytest applica prima gli autouse, poi il corpo del
# test puo' sovrascrivere).
import pytest  # noqa: E402  (import in fondo al file: le utility sopra restano invariate)
from app import audit as _audit_module


class _RealDatabaseForbidden:
    """Qualunque accesso (attributo o collezione) solleva subito un errore
    chiaro — mai una scrittura silenziosa sul database applicativo reale da
    un test che ha dimenticato di sostituire una dipendenza globale."""

    def __getattr__(self, name):
        raise RuntimeError(
            "Database applicativo reale raggiunto da un test senza una sostituzione esplicita "
            f"(attributo/collezione '{name}'). Usa monkeypatch.setattr(<modulo>, 'db', <db_di_test_isolato>) "
            "prima di eseguire un percorso che lo attraversa (vedi backend/tests/conftest.py)."
        )


@pytest.fixture(autouse=True)
def _forbid_real_database_in_tests(monkeypatch):
    monkeypatch.setattr(_audit_module, "db", _RealDatabaseForbidden())
