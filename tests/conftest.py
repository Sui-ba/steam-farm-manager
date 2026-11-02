"""Поднимает тестовый сервер. Живую базу не открывает."""

import threading

import pytest
from http.server import ThreadingHTTPServer

from tests.harness import db, server


@pytest.fixture(scope="session")
def app():
    if db.DB_PATH.resolve().name != "accounts.db" or "sfm-pytest-" not in str(db.DB_PATH):
        raise RuntimeError("тесты смотрят не в ту базу")
    db.init_db()
    db.add_account({
        "login": "demo",
        "password": "secret-pass",
        "email": "demo@example.com",
        "email_password": "mail-secret",
        "steam_id": "76561198000000000",
    })
    db.add_proxy({"protocol": "http", "host": "10.0.0.1", "port": 8080, "username": "u", "password": "proxy-secret"})
    httpd = ThreadingHTTPServer(("127.0.0.1", server.PORT), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
