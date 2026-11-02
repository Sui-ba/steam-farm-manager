"""Токен окна, скрытые пароли и клик по аккаунту."""

import json
import os

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from tests.harness import BASE, TMP, call, db


def test_api_requires_token(app):
    code, raw = call("GET", "/api/state")
    assert code == 401
    assert b"secret-pass" not in raw
    code, raw = call("GET", "/api/state", token="wrong-token")
    assert code == 401
    assert b"secret-pass" not in raw
    code, raw = call("GET", "/api/state", token=os.environ["SFM_API_TOKEN"])
    assert code == 200
    code, raw = call("GET", "/api/mini/state")
    assert code != 401
    code, raw = call("POST", "/api/telegram/webhook", body={})
    assert code == 404


def test_index_injects_token(app):
    code, raw = call("GET", "/")
    text = raw.decode("utf-8", "replace")
    assert code == 200
    assert "window.SFM_TOKEN=" in text and os.environ["SFM_API_TOKEN"] in text, "index did not inject the api token"


def test_passwords_hidden(app):
    code, raw = call("GET", "/api/state", token=os.environ["SFM_API_TOKEN"])
    assert code == 200
    body = json.loads(raw)
    account = body["accounts"][0]
    proxy = body["proxies"][0]
    assert "password" not in account and "email_password" not in account
    assert account["has_password"] is True and account["has_email_password"] is True
    assert account["email"] == "demo@example.com"
    assert "password" not in proxy and proxy["host"] == "10.0.0.1" and proxy["has_password"] is True
    blob = json.dumps(body)
    assert "secret-pass" not in blob and "mail-secret" not in blob and "proxy-secret" not in blob
    stored = db.DB_PATH.read_bytes()
    assert b"secret-pass" not in stored and b"mail-secret" not in stored and b"proxy-secret" not in stored
    code, raw = call("POST", "/api/reveal", body={"kind": "account", "id": account["id"]})
    assert code == 401
    code, raw = call("POST", "/api/reveal", body={"kind": "account", "id": account["id"]}, token=os.environ["SFM_API_TOKEN"])
    assert code == 200
    revealed = json.loads(raw)
    assert revealed["password"] == "secret-pass" and revealed["email_password"] == "mail-secret"


def test_account_click_opens_menu(app):
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--user-data-dir=" + str(TMP / "edge"))
    driver = webdriver.Edge(options=opts)
    driver.set_window_size(1280, 840)
    try:
        driver.get(BASE + "/")
        wait = WebDriverWait(driver, 20)
        wait.until(lambda d: d.find_elements(By.XPATH, "//button[normalize-space()='Аккаунты']"))
        driver.find_element(By.XPATH, "//button[normalize-space()='Аккаунты']").click()
        wait.until(lambda d: "demo" in d.find_element(By.ID, "view").text)
        driver.find_element(By.XPATH, "//td[normalize-space()='demo']").click()
        wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, "#dlg[open] h2"))
        title = driver.find_element(By.CSS_SELECTOR, "#dlg h2").text.strip()
        labels = [b.text.strip() for b in driver.find_elements(By.CSS_SELECTOR, "#dlg button")]
        body = driver.find_element(By.TAG_NAME, "body").text
        assert title == "Аккаунт · demo"
        assert labels == ["Изменить", "Удалить", "Команды", "Закрыть"]
        assert "Редактировать" not in title
        assert "Показать" in body and "••••••" in body
        assert "secret-pass" not in body and "mail-secret" not in body
    finally:
        driver.quit()
