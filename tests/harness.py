"""Общая настройка тестов. Импорт этого файла не открывает живую базу."""

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="sfm-pytest-"))
os.environ["SFM_PORT"] = "8833"
os.environ["SFM_API_TOKEN"] = "sfm-test-token"
os.environ["SFM_SETUP_DONE"] = "1"

from cryptography.fernet import Fernet

os.environ["SFM_SECRET_KEY"] = Fernet.generate_key().decode()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database as db
import vault

db.DB_PATH = TMP / "accounts.db"
vault.KEY_PATH = TMP / ".sfm-key"
vault.TOKEN_PATH = TMP / ".api-token"

import server

server.setup_needed = lambda: False
BASE = f"http://127.0.0.1:{server.PORT}"

if db.DB_PATH.resolve() == (ROOT / "accounts.db").resolve():
    raise RuntimeError("тесты смотрят в живую базу")
if server.PORT == 8765:
    raise RuntimeError("тесты заняли порт программы")


def call(method, path, body=None, token=None, extra=None):
    headers = dict(extra or {})
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("X-Requested-With", "sfm")
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
