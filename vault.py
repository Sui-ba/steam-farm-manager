"""Шифрование паролей, почт и прокси и токен локального API.

Ключ Fernet: переменная SFM_SECRET_KEY или файл .sfm-key.
Токен окна: SFM_API_TOKEN или файл .api-token. Оба файла не коммитятся.
"""

import os
import secrets

import envfile
import runtime

KEY_PATH = runtime.data_dir() / ".sfm-key"
TOKEN_PATH = runtime.data_dir() / ".api-token"
PREFIX = "enc:v1:"
ACCOUNT_FIELDS = ("password", "email", "email_password")
PROXY_FIELDS = ("host", "username", "password")


def _fernet():
    from cryptography.fernet import Fernet

    raw = (envfile.get("SFM_SECRET_KEY") or "").strip()
    if not raw and KEY_PATH.is_file():
        raw = KEY_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        raw = Fernet.generate_key().decode("ascii")
        KEY_PATH.write_text(raw + "\n", encoding="utf-8")
    try:
        return Fernet(raw.encode("ascii"))
    except (TypeError, ValueError) as exc:
        raise ValueError("SFM_SECRET_KEY или .sfm-key — не ключ Fernet") from exc


def is_sealed(value) -> bool:
    return str(value or "").startswith(PREFIX)


def encrypt(value) -> str:
    text = "" if value is None else str(value)
    if text == "" or is_sealed(text):
        return text
    token = _fernet().encrypt(text.encode("utf-8")).decode("ascii")
    return PREFIX + token


def decrypt(value) -> str:
    text = "" if value is None else str(value)
    if text == "" or not is_sealed(text):
        return text
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(text[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise ValueError("Не удалось расшифровать данные. Ключ .sfm-key не совпадает.") from exc


def seal_map(fields: dict, keys) -> dict:
    out = dict(fields)
    for key in keys:
        if key in out:
            out[key] = encrypt(out.get(key))
    return out


def open_row(row: dict, keys) -> dict:
    out = dict(row)
    for key in keys:
        if out.get(key):
            out[key] = decrypt(out.get(key))
    return out


def ensure_api_token() -> tuple[str, bool]:
    """Возвращает токен и флаг «только что создан»."""
    got = (os.environ.get("SFM_API_TOKEN") or envfile.get("SFM_API_TOKEN") or "").strip()
    if got:
        return got, False
    if TOKEN_PATH.is_file():
        saved = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if saved:
            return saved, False
    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token + "\n", encoding="utf-8")
    return token, True


def token_matches(header) -> bool:
    got = str(header or "").strip()
    if got.lower().startswith("bearer "):
        got = got[7:].strip()
    if not got:
        return False
    expected, _ = ensure_api_token()
    if len(got) != len(expected):
        return False
    return secrets.compare_digest(got, expected)


def announce_api_token():
    """Печатает токен один раз, в момент создания файла."""
    _token, created = ensure_api_token()
    if not created:
        return
    print("Токен API (показывается один раз): " + _token)
    print("Он записан в .api-token. Окно программы подставляет его само. Никому не отправляй этот файл.")
