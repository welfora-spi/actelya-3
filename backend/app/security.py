import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet, InvalidToken
from .config import JWT_SECRET, JWT_ALGORITHM, ACCESS_TOKEN_MINUTES, REFRESH_TOKEN_DAYS, MASTER_KEY


# ---------- Password hashing ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------- JWT ----------
def _get_secret() -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET non configurato")
    return JWT_SECRET


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id, "email": email, "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])


# ---------- Secret encryption (API keys) ----------
class SecretVaultError(RuntimeError):
    pass


def _get_fernet() -> Fernet:
    if not MASTER_KEY:
        raise SecretVaultError("MASTER_KEY mancante: gestione credenziali bloccata in modo sicuro.")
    try:
        return Fernet(MASTER_KEY.encode("utf-8"))
    except Exception:
        raise SecretVaultError("MASTER_KEY non valida: gestione credenziali bloccata in modo sicuro.")


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise SecretVaultError("Impossibile decifrare il segreto con la master key corrente.")


def set_auth_cookies(response, access: str, refresh: str) -> None:
    response.set_cookie("access_token", access, httponly=True, secure=True,
                        samesite="none", max_age=ACCESS_TOKEN_MINUTES * 60, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True,
                        samesite="none", max_age=REFRESH_TOKEN_DAYS * 86400, path="/")


def mask_secret(plaintext: str) -> str:
    if not plaintext:
        return ""
    if len(plaintext) <= 4:
        return "••••"
    return "••••••••" + plaintext[-4:]


def vault_available() -> bool:
    try:
        _get_fernet()
        return True
    except SecretVaultError:
        return False
