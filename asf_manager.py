"""Управление локальным ArchiSteamFarm. Пароли из конфигов никуда не пишутся."""

import json
import os
import socket

import envfile

envfile.load()
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import runtime

SETTINGS_PATH = runtime.data_dir() / "settings.json"
# Папка ASF по умолчанию — рядом с программой. Свою папку укажи в .env (ASF_DIR) или в настройках.
DEFAULT_ASF = runtime.data_dir() / "asf"
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
    saved = str(_load_settings().get("asf_dir") or envfile.get("ASF_DIR") or "").strip()
    if saved and (Path(saved) / "ArchiSteamFarm.exe").is_file():
        return saved
    if (DEFAULT_ASF / "ArchiSteamFarm.exe").is_file():
        return str(DEFAULT_ASF)
    return saved


def set_asf_dir(path: str):
    _save_settings({"asf_dir": path})
    envfile.set("ASF_DIR", path)


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


def bot_password(name: str) -> str:
    """Пароль из конфига бота. В ответы API и в Telegram его не класть."""
    folder = get_asf_dir()
    if not folder or not name or any(ch in name for ch in "/\\"):
        return ""
    data = _read_json(Path(folder) / "config" / f"{name}.json")
    return str(data.get("SteamPassword") or data.get("s_SteamPassword") or "")


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


def _output_text(args, timeout: float) -> str:
    """Вывод консольной команды. tasklist на русской Windows пишет не в UTF-8."""
    try:
        raw = subprocess.check_output(args, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return ""
    if isinstance(raw, str):
        return raw
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp866", errors="replace")


def process_exists() -> bool:
    """Одна быстрая проверка: запущен ли ArchiSteamFarm.exe."""
    try:
        text = _output_text(
            ["tasklist", "/FI", "IMAGENAME eq ArchiSteamFarm.exe", "/FO", "CSV", "/NH"],
            5,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return False
    return "ArchiSteamFarm.exe" in text


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
        out = _output_text(
            ["tasklist", "/FI", "IMAGENAME eq ArchiSteamFarm.exe", "/FO", "CSV", "/NH"],
            5,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
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
        ps = _output_text(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='ArchiSteamFarm.exe'\" | "
                "Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress",
            ],
            8,
        ).strip()
    except (OSError, subprocess.SubprocessError, UnicodeError):
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
    """Адрес прокси для ASF: scheme://host:port без логина и пароля (ASF 6.3 не понимает их в URL)."""
    protocol = (proxy.get("protocol") or "http").strip().lower() or "http"
    return f"{protocol}://{proxy['host']}:{int(proxy['port'])}"


def proxy_fields(proxy: dict) -> dict:
    """Поля конфига бота ASF для прокси. Как в addproxy.py: адрес, логин и пароль отдельно."""
    return {
        "WebProxy": proxy_url(proxy),
        "WebProxyUsername": str(proxy.get("username") or "") or None,
        "WebProxyPassword": str(proxy.get("password") or "") or None,
        "SteamProtocols": 4,
    }


def _fields_from_url(url: str) -> dict:
    """Старый формат scheme://user:pass@host:port раскладывается на поля ASF."""
    raw = url if "://" in url else "http://" + url
    parsed = urlparse(raw)
    return {
        "WebProxy": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}" if parsed.port else f"{parsed.scheme}://{parsed.hostname}",
        "WebProxyUsername": unquote(parsed.username) if parsed.username else None,
        "WebProxyPassword": unquote(parsed.password) if parsed.password else None,
        "SteamProtocols": 4,
    }


PROXY_KEYS = ("WebProxy", "WebProxyUsername", "WebProxyPassword", "SteamProtocols")


def write_bot_proxies(pairs: list[tuple[str, dict]]) -> dict:
    """Пишет прокси в config бота, если SteamLogin совпал.

    pairs: (логин, proxy_fields(...)). Строка-URL тоже принимается и раскладывается на поля.
    Пароль прокси в ответ и в лог не попадает.
    """
    wanted = {}
    for login, fields in pairs:
        if not login or not fields:
            continue
        if isinstance(fields, str):
            fields = _fields_from_url(fields)
        wanted[login.strip().lower()] = {k: fields.get(k) for k in PROXY_KEYS}
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
        fields = wanted[login]
        if all(data.get(k) == fields[k] for k in PROXY_KEYS):
            skipped.append(path.stem)
            continue
        for key in PROXY_KEYS:
            if fields[key] is None:
                data.pop(key, None)
            else:
                data[key] = fields[key]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        updated.append(path.stem)
    for login in wanted:
        if login not in seen:
            missing.append(login)
    reloaded = ""
    if updated and ipc_alive():
        reloaded = send_command("reload " + ",".join(updated))
    return {"updated": updated, "skipped": skipped, "missing": missing, "reloaded": bool(reloaded)}


def farm_view(info: dict) -> dict:
    """Очередь фарма карточек из IPC. Имена игр и числа, без секретов."""
    empty = {"queue": [], "current": [], "eta": ""}
    farmer = info.get("CardsFarmer") if isinstance(info, dict) else None
    if not isinstance(farmer, dict):
        return empty

    def row(game):
        if not isinstance(game, dict):
            return None
        hours = game.get("HoursPlayed")
        if isinstance(hours, (int, float)):
            hours = round(float(hours), 1)
        else:
            hours = None
        cards = game.get("CardsRemaining")
        return {
            "appid": game.get("AppID") or game.get("AppId") or "",
            "name": str(game.get("GameName") or game.get("Name") or "—")[:80],
            "cards": cards if isinstance(cards, int) else None,
            "hours": hours,
        }

    def rows(key):
        out = []
        for game in farmer.get(key) or []:
            item = row(game)
            if item:
                out.append(item)
            if len(out) >= 40:
                break
        return out

    eta = str(farmer.get("TimeRemaining") or "").strip()
    if eta in ("00:00:00", "0:00:00"):
        eta = ""
    return {"queue": rows("GamesToFarm"), "current": rows("CurrentGamesFarming"), "eta": eta[:40]}


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
