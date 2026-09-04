"""Shared test configuration: repo-relative paths and admin credentials from env.

Never hardcode secrets or absolute paths in individual test files — import from here.
Portable across environments (no dependency on a fixed mount point like /app).
"""
import os
from pathlib import Path

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
