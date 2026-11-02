"""Управление локальным ArchiSteamFarm. Пароли из конфигов никуда не пишутся."""

import json
import os
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse

SETTINGS_PATH = Path(__file__).parent / "settings.json"
DEFAULT_ASF = Path(r"C:\path\to\asf")
FALLBACK_ASF = Path(r"C:\path\to\asf-fallback")
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010


def _load_settings() -> dict:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_settings(updates: dict):
    data = _load_settings()
    data.update(updates)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_asf_dir() -> str:
    saved = str(_load_settings().get("asf_dir") or "").strip()
    if saved and (Path(saved) / "ArchiSteamFarm.exe").is_file():
        return saved
    for candidate in (DEFAULT_ASF, FALLBACK_ASF):
        if (candidate / "ArchiSteamFarm.exe").is_file():
            return str(candidate)
    return saved


def set_asf_dir(path: str):
    _save_settings({"asf_dir": path})


def asf_exe(folder: str | None = None) -> Path | None:
    root = Path(folder or get_asf_dir() or "")
    exe = root / "ArchiSteamFarm.exe"
    return exe if exe.is_file() else None


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _asf_config() -> dict:
    folder = get_asf_dir()
    if not folder:
        return {}
    return _read_json(Path(folder) / "config" / "ASF.json")


def ipc_password() -> str:
    cfg = _asf_config()
    value = cfg.get("IPCPassword") or cfg.get("s_IPCPassword") or ""
    return str(value).strip()


def ipc_base() -> str:
    cfg = _asf_config()
    kestrel = cfg.get("Kestrel") if isinstance(cfg.get("Kestrel"), dict) else {}
    endpoints = kestrel.get("Endpoints") if isinstance(kestrel.get("Endpoints"), dict) else {}
    for data in endpoints.values():
        if isinstance(data, dict) and data.get("Url"):
            return str(data["Url"]).rstrip("/")
    return "http://127.0.0.1:1242"


def _proxy_display(webproxy) -> str:
    if not webproxy:
        return ""
    text = str(webproxy).strip()
    raw = text if "://" in text else "http://" + text
    parsed = urlparse(raw)
    host = parsed.hostname or ""
    if not host:
        return ""
    return f"{host}:{parsed.port}" if parsed.port else host


def list_bots() -> list[dict]:
    folder = get_asf_dir()
    if not folder:
        return []
    config = Path(folder) / "config"
    if not config.is_dir():
        return []
    bots = []
    for path in sorted(config.glob("*.json")):
        if path.name.lower() == "asf.json":
            continue
        data = _read_json(path)
        if not data:
            continue
        bots.append({
            "name": path.stem,
            "login": str(data.get("SteamLogin") or data.get("s_SteamLogin") or ""),
            "enabled": bool(data.get("Enabled", True)),
            "proxy": _proxy_display(data.get("WebProxy")),
            "paused": bool(data.get("Paused")),
        })
    return bots


def process_exists() -> bool:
    """Одна быстрая проверка: запущен ли ArchiSteamFarm.exe."""
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq ArchiSteamFarm.exe", "/FO", "CSV", "/NH"],
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "ArchiSteamFarm.exe" in out


def asf_running(folder: str | None = None) -> bool:
    exe = asf_exe(folder)
    if not exe or not process_exists():
        return False
    target = exe.resolve()
    procs = _asf_processes()
    matched = [item for item in procs if item.get("path")]
    if not matched:
        return len(procs) == 1
    return any(Path(item["path"]).resolve() == target for item in matched)


def _asf_processes() -> list[dict]:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq ArchiSteamFarm.exe", "/FO", "CSV", "/NH"],
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        if "ArchiSteamFarm.exe" not in line:
            continue
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 2 and parts[1].isdigit():
            rows.append({"pid": int(parts[1]), "path": ""})
    if not rows:
        return []
    try:
        ps = subprocess.check_output(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='ArchiSteamFarm.exe'\" | "
                "Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress",
            ],
            text=True,
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return rows
    if not ps:
        return rows
    try:
        data = json.loads(ps)
    except json.JSONDecodeError:
        return rows
    if isinstance(data, dict):
        data = [data]
    detailed = []
    for item in data or []:
        detailed.append({
            "pid": int(item.get("ProcessId") or 0),
            "path": str(item.get("ExecutablePath") or ""),
        })
    return detailed or rows


def start_asf() -> str:
    exe = asf_exe()
    if not exe:
        raise RuntimeError("ArchiSteamFarm.exe не найден. Выбери папку ASF.")
    if asf_running():
        return "ASF уже запущен"
    subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        creationflags=CREATE_NEW_CONSOLE,
    )
    return "ASF запускается"


def stop_asf() -> str:
    exe = asf_exe()
    procs = _asf_processes()
    if not procs:
        return "ASF не запущен"
    target = str(exe.resolve()).lower() if exe else ""
    killed = 0
    for item in procs:
        path = str(item.get("path") or "").lower()
        pid = item.get("pid")
        if not pid:
            continue
        if path and target and Path(path).resolve().as_posix().lower() != Path(target).as_posix().lower():
            continue
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=8,
        )
        killed += 1
    if killed == 0 and procs:
        subprocess.run(
            ["taskkill", "/IM", "ArchiSteamFarm.exe", "/T"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=8,
        )
        killed = len(procs)
    return f"Остановлено процессов: {killed}"


def _ipc(method: str, path: str, body: dict | None = None, timeout: float = 2.5) -> dict:
    url = ipc_base() + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    password = ipc_password()
    if password:
        req.add_header("Authentication", password)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        message = payload.get("Message") or raw or str(exc)
        raise RuntimeError(f"IPC {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("IPC недоступен. Запусти ASF.") from exc
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"Result": raw}
    if payload.get("Success") is False:
        raise RuntimeError(payload.get("Message") or "IPC вернул ошибку")
    return payload


def ipc_port() -> int:
    parsed = urlparse(ipc_base())
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def ipc_open(timeout: float = 0.4) -> bool:
    parsed = urlparse(ipc_base())
    host = parsed.hostname or "127.0.0.1"
    try:
        with socket.create_connection((host, ipc_port()), timeout):
            return True
    except OSError:
        return False


def ipc_alive() -> bool:
    if not ipc_open():
        return False
    try:
        _ipc("GET", "/Api/ASF", timeout=1.2)
        return True
    except Exception:
        return False


def ipc_bots() -> dict:
    if not ipc_open():
        return {}
    try:
        payload = _ipc("GET", "/Api/Bot/ASF", timeout=3)
    except Exception:
        return {}
    result = payload.get("Result")
    return result if isinstance(result, dict) else {}


def bot_action(name: str, action: str) -> str:
    if not name:
        raise RuntimeError("Сначала выбери бота")
    path = f"/Api/Bot/{quote(name)}/{action}"
    body = None
    if action == "Pause":
        body = {"Permanent": False}
    payload = _ipc("POST", path, body)
    return str(payload.get("Message") or payload.get("Result") or "OK")


def send_command(command: str) -> str:
    text = (command or "").strip()
    if not text:
        raise RuntimeError("Введи команду ASF")
    payload = _ipc("POST", "/Api/Command", {"Command": text}, timeout=20)
    result = payload.get("Result")
    if result is None:
        return str(payload.get("Message") or "OK")
    return str(result)


def proxy_url(proxy: dict) -> str:
    protocol = (proxy.get("protocol") or "http").strip().lower() or "http"
    user = quote(str(proxy.get("username") or ""), safe="")
    password = quote(str(proxy.get("password") or ""), safe="")
    auth = f"{user}:{password}@" if user else ""
    return f"{protocol}://{auth}{proxy['host']}:{int(proxy['port'])}"


def write_bot_proxies(pairs: list[tuple[str, str]]) -> dict:
    """Пишет WebProxy в config бота, если SteamLogin совпал. Пароль прокси в ответ не попадает."""
    wanted = {login.strip().lower(): url for login, url in pairs if login and url}
    folder = get_asf_dir()
    if not folder:
        raise RuntimeError("Папка ASF не выбрана")
    config = Path(folder) / "config"
    if not config.is_dir():
        raise RuntimeError("В папке ASF нет каталога config")
    updated, skipped, missing = [], [], []
    seen = set()
    for path in config.glob("*.json"):
        if path.name.lower() == "asf.json":
            continue
        data = _read_json(path)
        login = str(data.get("SteamLogin") or data.get("s_SteamLogin") or "").strip().lower()
        if not login or login not in wanted:
            continue
        seen.add(login)
        url = wanted[login]
        if data.get("WebProxy") == url:
            skipped.append(path.stem)
            continue
        data["WebProxy"] = url
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated.append(path.stem)
    for login in wanted:
        if login not in seen:
            missing.append(login)
    reloaded = ""
    if updated and ipc_alive():
        reloaded = send_command("reload " + ",".join(updated))
    return {"updated": updated, "skipped": skipped, "missing": missing, "reloaded": bool(reloaded)}


def live_status(bot: dict, live: dict, running: bool = False) -> tuple[str, str]:
    info = live.get(bot["name"]) or {}
    if not live:
        if running:
            return "ASF без IPC", "—"
        return "ASF выключен", "—"
    if not info:
        return "нет в IPC", "—"
    cards = info.get("CardsRemaining")
    cards_text = "—" if cards is None else str(cards)
    if info.get("IsConnectedAndLoggedOn"):
        if info.get("Paused"):
            return "онлайн, пауза", cards_text
        return "онлайн", cards_text
    if info.get("KeepRunning"):
        return "запускается", cards_text
    return "остановлен", cards_text
