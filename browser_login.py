"""Вход в Steam через Chrome/Edge (Selenium) и ввод кода Guard из maFile."""

import os

from steam_guard import enter_guard_code

_sessions = []  # держим драйверы живыми, пока открыто окно браузера


def _app_path(exe_name, fallbacks):
    """Путь к браузеру: реестр App Paths, потом типичные папки Windows."""
    if os.name == "nt":
        import winreg
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}") as key:
                    value, _ = winreg.QueryValueEx(key, None)
            except OSError:
                continue
            if value and os.path.isfile(value):
                return value
    for path in fallbacks:
        expanded = os.path.expandvars(path)
        if expanded and os.path.isfile(expanded):
            return expanded
    return None


def _find_chrome():
    return _app_path("chrome.exe", [
        r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ])


def _find_edge():
    return _app_path("msedge.exe", [
        r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
        r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
        r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
    ])


def login(acc: dict, status) -> None:
    """status(text, kind=None) — kind: None | "ok" | "warn" | "err"."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.edge.options import Options as EdgeOptions
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        chrome_path = _find_chrome()
        edge_path = _find_edge()
        if chrome_path:
            browser_name = "Chrome"
            options = ChromeOptions()
            options.binary_location = chrome_path
        elif edge_path:
            # На Windows 11 Chrome часто не установлен, Edge стоит из коробки.
            browser_name = "Edge"
            options = EdgeOptions()
            options.binary_location = edge_path
        else:
            raise RuntimeError(
                "Не найден ни Google Chrome, ни Microsoft Edge. Установи Chrome и попробуй снова."
            )

        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("detach", True)

        # Драйвер подбирает Selenium Manager. webdriver-manager на Windows 11
        # часто отдаёт не exe, а текстовый файл — из-за этого был WinError 193.
        if browser_name == "Chrome":
            driver = webdriver.Chrome(options=options)
        else:
            driver = webdriver.Edge(options=options)
        _sessions.append(driver)

        driver.get("https://store.steampowered.com/login/")
        wait = WebDriverWait(driver, 25)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")))

        password = None
        for el in driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
            if el.is_displayed():
                password = el
                break
        if password is None:
            raise RuntimeError("Поле пароля на странице Steam не найдено")

        form = password.find_element(By.XPATH, "./ancestor::form")
        login_input = None
        for el in form.find_elements(By.CSS_SELECTOR, "input[type='text']"):
            if el.is_displayed():
                login_input = el
                break
        if login_input is None:
            raise RuntimeError("Поле логина на странице Steam не найдено")

        login_input.click()
        login_input.clear()
        login_input.send_keys(acc["login"])
        password.click()
        password.clear()
        password.send_keys(acc["password"])

        try:
            btn = form.find_element(By.CSS_SELECTOR, "button[type='submit']")
            btn.click()
        except Exception:
            password.send_keys(Keys.ENTER)

        status(f"{browser_name}: вхожу как {acc['login']}…")
        try:
            enter_guard_code(driver, acc["login"], status)
        except Exception as exc:
            status(f"Браузер открыт, код не введён: {exc}", "warn")
    except Exception as exc:
        text = str(exc).strip() or exc.__class__.__name__
        status(f"Не удалось открыть браузер: {text[:300]}", "err")
