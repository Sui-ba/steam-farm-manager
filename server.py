"""Steam Farm Manager: локальный веб-интерфейс.  Запуск: python server.py"""

import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import envfile
import runtime

envfile.load()

import asf_manager as asf
import browser_login
import channel_games
import database as db
import exchange as ex
import steam_badges
import steam_guard as sg
import tgbot
import vault

WEB = runtime.bundle_dir() / "web"
PORT = int(envfile.get("SFM_PORT", "8765") or "8765")
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
login_status = {"text": "", "kind": ""}
CARDS = runtime.data_dir() / "cards.json"
ACTIVITY = runtime.data_dir() / "activity.json"
BOARD = runtime.data_dir() / "board.json"
GAMES = runtime.data_dir() / "games.json"
BADGES = runtime.data_dir() / "badge_live.json"
_board_lock = threading.Lock()
_games_lock = threading.Lock()
_badge_lock = threading.Lock()
_badge_running = False


def _status(text, kind=None):
    login_status.update(text=text, kind=kind or "info")


def setup_needed():
    """Первый запуск: в .env ещё нет своих путей и Telegram."""
    if envfile.get("SFM_SETUP_DONE") == "1":
        return False
    filled = any(envfile.get(key) for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_ID", "ASF_DIR", "MAFILES_DIR"))
    if filled:
        envfile.set("SFM_SETUP_DONE", "1")
        return False
    return True


def setup_info():
    info = {"needed": setup_needed()}
    if not info["needed"]:
        return info
    return {
        **info,
        "port": str(PORT),
        "asf_dir": asf.get_asf_dir(),
        "mafiles_dir": sg.get_mafiles_dir(),
        "owner_id": envfile.get("TELEGRAM_OWNER_ID"),
        "owner_name": envfile.get("TELEGRAM_OWNER_NAME"),
    }


def _public_rows(rows, secret_keys):
    """Список для /api/state: секреты не уходят, остаётся только признак «поле заполнено»."""
    out = []
    for row in rows:
        item = dict(row)
        for key in secret_keys:
            item[f"has_{key}"] = bool(item.get(key))
            item.pop(key, None)
        out.append(item)
    return out


def state():
    return {
        "accounts": _public_rows(db.get_all_accounts(), ("password", "email_password")),
        "proxies": _public_rows(db.get_all_proxies(), ("password",)),
        "stats": db.get_stats(),
        "settings": {"mafiles_dir": sg.get_mafiles_dir(), "asf_dir": asf.get_asf_dir()},
        "setup": setup_info(),
    }


def reveal(b):
    """Один пароль по кнопке «Показать». В общий список он не входит."""
    kind = str(b.get("kind") or "")
    row_id = int(b.get("id"))
    if kind == "account":
        acc = db.get_account(row_id)
        if not acc:
            raise ValueError("Аккаунт не найден")
        return {"password": acc.get("password") or "", "email_password": acc.get("email_password") or ""}
    if kind == "proxy":
        proxy = db.get_proxy(row_id)
        if not proxy:
            raise ValueError("Прокси не найден")
        return {"password": proxy.get("password") or ""}
    raise ValueError("Нечего показывать")


def asf_state():
    alive = asf.ipc_alive()
    live = asf.ipc_bots() if alive else {}
    running = alive or asf.process_exists()
    bots = []
    for bot in asf.list_bots():
        text, cards = asf.live_status(bot, live, running)
        bots.append({**bot, "state": text, "cards": cards, "farm": asf.farm_view(live.get(bot["name"]) or {})})
    return {"running": running, "ipc": alive, "base": asf.ipc_base(),
            "dir": asf.get_asf_dir(), "bots": bots}


def push_proxies():
    proxies = {p["id"]: p for p in db.get_all_proxies()}
    pairs = []
    for account in db.get_all_accounts():
        proxy = proxies.get(account.get("proxy_id"))
        if proxy:
            pairs.append((account["login"], asf.proxy_url(proxy)))
    if not pairs:
        raise ValueError("Нет аккаунтов с назначенным прокси")
    result = asf.write_bot_proxies(pairs)
    log_act(f"Прокси записаны в ASF: {len(result['updated'])}, без изменений: {len(result['skipped'])}")
    owner = tgbot.load().get("owner")
    if owner and tg.thread and tg.thread.is_alive():
        tg.send(owner["id"], f"Прокси в конфигах ASF: обновлено {len(result['updated'])}, уже было {len(result['skipped'])}.")
    return result


def import_asf_accounts():
    """Создаёт аккаунты из ботов ASF. Совпадение логина без учёта регистра — пропуск."""
    existing = {str(a.get("login") or "").strip().lower() for a in db.get_all_accounts()}
    added = skipped = 0
    for bot in asf.list_bots():
        login = str(bot.get("login") or "").strip()
        if not login or login.lower() in existing:
            skipped += 1
            continue
        db.add_account({
            "login": login,
            "password": asf.bot_password(bot["name"]),
            "notes": "ASF " + bot["name"],
        })
        existing.add(login.lower())
        added += 1
    log_act(f"Импорт из ASF: добавлено {added}, уже были {skipped}")
    return {"added": added, "skipped": skipped}


def save_account(b):
    login = str(b.get("login") or "").strip()
    if not login:
        raise ValueError("Логин обязателен")
    try:
        b["spent"] = float(b.get("spent") or 0)
    except ValueError:
        raise ValueError("«Потрачено» должно быть числом")
    b["login"] = login
    if b.get("id"):
        aid = int(b["id"])
        db.update_account(aid, b)
    else:
        aid = db.add_account(b)
    def whole(key):
        raw = str(b.get(key) if b.get(key) is not None else "").strip()
        if not raw:
            return 0
        num = int(float(raw))
        if num < 0:
            raise ValueError
        return num

    def money_field(key):
        raw = str(b.get(key) if b.get(key) is not None else "").strip()
        if not raw:
            return 0
        num = float(raw)
        if num < 0:
            raise ValueError
        return num

    try:
        extra = {
            "balance": str(b.get("balance") or "").strip(),
            "level": int(float(lvl)) if (lvl := str(b.get("level") if b.get("level") is not None else "").strip()) else None,
            "rank": str(b.get("rank") or "").strip()[:40],
            "xp": whole("xp"),
            "drops": whole("drops"),
            "sent_main": whole("sent_main"),
            "income": money_field("income"),
            "reinvest": money_field("reinvest"),
        }
    except (TypeError, ValueError):
        raise ValueError("Ранг, опыт, дроп, доход и реинвест должны быть числами от нуля")
    db.update_account_fields(aid, extra)
    return {"ok": True}


def save_proxy(b):
    try:
        port = int(b.get("port"))
        if not 1 <= port <= 65535 or not str(b.get("host") or "").strip():
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Нужны хост и порт (1–65535)")
    b.update(port=port, host=b["host"].strip())
    if b.get("id"):
        db.update_proxy(int(b["id"]), b)
    else:
        db.add_proxy(b)
    return {"ok": True}


def export(q):
    kind, typ, fmt = q["kind"][0], q["type"][0], (q.get("fmt") or [""])[0]
    if kind == "accounts":
        px = {p["id"]: p for p in db.get_all_proxies()}
        recs = [ex.account_row(a, px.get(a.get("proxy_id"))) for a in sorted(db.get_all_accounts(), key=lambda a: a["id"])]
        cols, sheet = ex.ACCOUNT_XLSX, "Аккаунты"
    else:
        recs = [ex.proxy_row(p) for p in sorted(db.get_all_proxies(), key=lambda p: p["id"])]
        cols, sheet = ex.PROXY_XLSX, "Прокси"
    if not recs:
        raise ValueError("Нечего экспортировать")
    if typ == "xlsx":
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.xlsx"
            ex.write_xlsx(str(path), sheet, *ex.table_rows(recs, cols))
            data = path.read_bytes()
        return data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{kind}.xlsx"
    if "{" not in fmt:
        raise ValueError("Для TXT нужен формат строки")
    return ("\n".join(ex.format_line(fmt, r) for r in recs) + "\n").encode(), "text/plain; charset=utf-8", f"{kind}.txt"


def start_login(b):
    acc = db.get_account(int(b["id"]))
    if not acc or not acc.get("login") or not acc.get("password"):
        raise ValueError("У аккаунта нет логина или пароля")
    _status(f"Открываю браузер для {acc['login']}…")
    threading.Thread(target=browser_login.login, args=(acc, _status), daemon=True).start()
    return {"ok": True}


def set_settings(b):
    for key, setter in (("mafiles_dir", sg.set_mafiles_dir), ("asf_dir", asf.set_asf_dir)):
        value = str(b.get(key) or "").strip()
        if value:
            if not Path(value).is_dir():
                raise ValueError(f"Папки нет: {value}")
            setter(value)
    return {"ok": True}


_browse_lock = threading.Lock()


def browse_folder(b):
    """Системное окно выбора папки. Путь не нужно копировать из проводника."""
    if os.name != "nt":
        raise ValueError("Кнопка «Обзор» работает в Windows. Вставь путь вручную.")
    if not _browse_lock.acquire(blocking=False):
        raise ValueError("Окно выбора папки уже открыто")
    out = script = None
    try:
        out = Path(tempfile.gettempdir()) / f"sfm-browse-{secrets.token_hex(4)}.txt"
        script = Path(tempfile.gettempdir()) / f"sfm-browse-{secrets.token_hex(4)}.ps1"
        script.write_text(
            "Add-Type -AssemblyName System.Windows.Forms\n"
            "$form = New-Object System.Windows.Forms.Form\n"
            "$form.TopMost = $true\n"
            "$form.ShowInTaskbar = $false\n"
            "$form.Opacity = 0\n"
            "$form.Show()\n"
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog\n"
            "$d.Description = $env:SFM_BROWSE_TITLE\n"
            "$d.ShowNewFolderButton = $false\n"
            "if ($d.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {\n"
            "  [IO.File]::WriteAllText($env:SFM_BROWSE_OUT, $d.SelectedPath, (New-Object System.Text.UTF8Encoding $false))\n"
            "}\n"
            "$form.Close()\n",
            encoding="utf-8-sig",
        )
        env = os.environ.copy()
        env["SFM_BROWSE_TITLE"] = str(b.get("title") or "Выбери папку")[:80]
        env["SFM_BROWSE_OUT"] = str(out)
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                env=env, timeout=180, check=False, creationflags=0x08000000,
            )
        except subprocess.TimeoutExpired:
            raise ValueError("Окно выбора папки закрыто по таймауту")
        path = out.read_text(encoding="utf-8-sig").strip() if out.is_file() else ""
        return {"path": path}
    finally:
        _browse_lock.release()
        for path in (out, script):
            if path is not None:
                path.unlink(missing_ok=True)


def save_setup(b):
    """Первый запуск: пути, Telegram и порт пишутся в .env из окна программы."""
    if b.get("skip"):
        envfile.set("SFM_SETUP_DONE", "1")
        return {"ok": True, "needed": False, "message": "Можно заполнить позже: кнопка «Пути» и вкладка Telegram."}

    asf_dir = str(b.get("asf_dir") or "").strip().strip('"')
    ma_dir = str(b.get("mafiles_dir") or "").strip().strip('"')
    token = str(b.get("token") or "").strip()
    owner_id = str(b.get("owner_id") or "").strip()
    owner_name = str(b.get("owner_name") or "").strip()[:40]
    port = str(b.get("port") or "").strip() or "8765"

    if asf_dir and not (Path(asf_dir) / "ArchiSteamFarm.exe").is_file():
        raise ValueError("В этой папке нет ArchiSteamFarm.exe")
    if ma_dir and not Path(ma_dir).is_dir():
        raise ValueError("Папка maFiles не найдена")
    if owner_id and not owner_id.isdigit():
        raise ValueError("Telegram id владельца должен быть числом. Его пишет @userinfobot.")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("Порт — число от 1 до 65535")
    username = tgbot.request(token, "getMe")["username"] if token else ""

    if asf_dir:
        asf.set_asf_dir(asf_dir)
    if ma_dir:
        sg.set_mafiles_dir(ma_dir)
    envfile.set("SFM_PORT", port)
    if owner_id:
        envfile.set("TELEGRAM_OWNER_ID", owner_id)
        envfile.set("TELEGRAM_OWNER_NAME", owner_name or "Владелец")
        cfg = tgbot.load()
        cfg["owner"] = {"id": int(owner_id), "name": owner_name or "Владелец"}
        tgbot.save(cfg)
    if token:
        tg_token({"token": token})
    envfile.set("SFM_SETUP_DONE", "1")
    parts = ["Настройки сохранены."]
    if username:
        parts.append(f"Бот @{username} подключён.")
    if port != str(PORT):
        parts.append("Новый порт включится после перезапуска start.bat.")
    return {"ok": True, "needed": False, "message": " ".join(parts)}


def import_(b):
    run = ex.import_accounts if b["kind"] == "accounts" else ex.import_proxies
    result = run(b.get("text", ""), b.get("fmt", ""))
    return {**result, "text": ex.result_text("Готово.", result)}


def log_act(text):
    try:
        data = json.loads(ACTIVITY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = []
    data.insert(0, {"t": time.strftime("%d.%m %H:%M"), "text": text})
    ACTIVITY.write_text(json.dumps(data[:50], ensure_ascii=False), encoding="utf-8")


def get_activity():
    try:
        return {"items": json.loads(ACTIVITY.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return {"items": []}


class Ctx:
    @staticmethod
    def accounts():
        proxies = {p["id"]: p for p in db.get_all_proxies()}
        rows = []
        for a in db.get_all_accounts():
            proxy = proxies.get(a.get("proxy_id"))
            rows.append({
                "id": a["id"], "login": a["login"], "balance": a.get("balance"), "level": a.get("level"),
                "is_main": a.get("is_main"), "drops": a.get("drops") or 0, "income": a.get("income") or 0,
                "rank": a.get("rank") or "", "proxy": f"{proxy['host']}:{proxy['port']}" if proxy else "",
            })
        return rows

    @staticmethod
    def bots():
        alive = asf.ipc_alive()
        live = asf.ipc_bots() if alive else {}
        running = alive or asf.process_exists()
        out = {}
        for x in asf.list_bots():
            if x["login"]:
                text, cards = asf.live_status(x, live, running)
                out[x["login"].lower()] = {"name": x["name"], "state": text, "cards": cards}
        return out

    @staticmethod
    def roster():
        """Боты из конфигов ASF. Поля базы подмешиваются, если логин совпал."""
        db_rows = {a["login"].lower(): a for a in Ctx.accounts() if a.get("login")}
        alive = asf.ipc_alive()
        live = asf.ipc_bots() if alive else {}
        try:
            running = alive or asf.process_exists()
        except (OSError, UnicodeError, RuntimeError):
            running = bool(alive)
        items, seen_logins = [], set()
        for bot in asf.list_bots():
            login = str(bot.get("login") or "").strip()
            key = login.lower()
            if key:
                seen_logins.add(key)
            text, cards = asf.live_status(bot, live, running)
            acc = db_rows.get(key, {}) if key else {}
            items.append({
                "id": acc.get("id"),
                "key": f"bot:{bot['name']}",
                "login": acc.get("login") or login or bot["name"],
                "bot": bot["name"],
                "state": text,
                "cards": cards,
                "balance": acc.get("balance"),
                "level": acc.get("level"),
                "is_main": acc.get("is_main"),
                "drops": acc.get("drops") or 0,
                "income": acc.get("income") or 0,
                "rank": acc.get("rank") or "",
                "proxy": acc.get("proxy") or bot.get("proxy") or "",
            })
        for acc in Ctx.accounts():
            login = str(acc.get("login") or "").strip()
            if not login or login.lower() in seen_logins:
                continue
            items.append({
                "id": acc.get("id"),
                "key": f"id:{acc['id']}",
                "login": login,
                "bot": "",
                "state": "",
                "cards": "",
                "balance": acc.get("balance"),
                "level": acc.get("level"),
                "is_main": acc.get("is_main"),
                "drops": acc.get("drops") or 0,
                "income": acc.get("income") or 0,
                "rank": acc.get("rank") or "",
                "proxy": acc.get("proxy") or "",
            })
        return items

    @staticmethod
    def run(act, names, main):
        if act in ("Pause", "Resume", "Start", "Stop"):
            res = []
            for n in names:
                try:
                    res.append(f"{n}: {asf.bot_action(n, act)}")
                except RuntimeError as exc:
                    res.append(f"{n}: ошибка — {exc}")
            return "\n".join(res)
        if act == "Inv":
            return asf.send_command("inventory " + ",".join(names))
        if act == "Transfer":
            return asf.send_command(f"transfer {','.join(names)} {main}")
        raise ValueError("Неизвестное действие")

    log = staticmethod(lambda text: log_act(text))


tg = tgbot.Bot(Ctx)


def tg_state():
    c = tgbot.load()
    now = time.time()
    return {"token_set": bool(c["token"]), "username": tg.username, "running": bool(tg.thread and tg.thread.is_alive()), "error": tg.error,
            "owner": c["owner"], "employees": c["employees"], "perms": tgbot.PERMS, "logins": [a["login"] for a in db.get_all_accounts()],
            "invites": [{"code": k, "role": v["role"], "emp": v.get("emp")} for k, v in c["invites"].items() if v["exp"] > now]}


def tg_token(b):
    token = str(b.get("token") or "").strip()
    c = tgbot.load()
    if not token:
        c["token"] = ""
        tgbot.save(c)
        envfile.set("TELEGRAM_BOT_TOKEN", "")
        tg.shutdown()
        return tg_state()
    tg.username = tgbot.request(token, "getMe")["username"]
    c["token"] = token
    tgbot.save(c)
    envfile.set("TELEGRAM_BOT_TOKEN", token)
    tg.start()
    return tg_state()


def tg_invite(b):
    if not tg.username:
        raise ValueError("Сначала подключи бота (токен)")
    c = tgbot.load()
    if b.get("role") == "employee" and not any(e["key"] == b.get("emp") for e in c["employees"]):
        raise ValueError("Сотрудник не найден")
    code = secrets.token_urlsafe(8)
    c["invites"] = {k: v for k, v in c["invites"].items() if v["exp"] > time.time()}
    c["invites"][code] = {"role": "owner" if b.get("role") == "owner" else "employee", "emp": b.get("emp"), "exp": time.time() + 86400}
    tgbot.save(c)
    return {"code": code, "link": f"https://t.me/{tg.username}?start={code}"}


def tg_employee(b):
    name = str(b.get("name") or "").strip()[:40]
    if not name:
        raise ValueError("Укажи имя сотрудника")
    logins = {a["login"] for a in db.get_all_accounts()}
    accounts = "*" if b.get("accounts") == "*" else [x for x in (b.get("accounts") or []) if x in logins]
    perms = {k: bool((b.get("perms") or {}).get(k)) for k in tgbot.PERMS}
    c = tgbot.load()
    e = next((x for x in c["employees"] if x["key"] == b.get("key")), None)
    if e:
        e.update(name=name, perms=perms, accounts=accounts)
    else:
        e = {"key": secrets.token_hex(4), "id": None, "tg": "", "name": name, "perms": perms, "accounts": accounts}
        c["employees"].append(e)
    tgbot.save(c)
    return {"key": e["key"]}


def tg_delete(b):
    c = tgbot.load()
    c["employees"] = [e for e in c["employees"] if e["key"] != b.get("key")]
    c["invites"] = {k: v for k, v in c["invites"].items() if v.get("emp") != b.get("key")}
    tgbot.save(c)
    return {"ok": True}


def tg_unlink(b):
    c = tgbot.load()
    c["owner"] = None
    tgbot.save(c)
    return {"ok": True}


def tg_test(b):
    owner = tgbot.load()["owner"]
    if not owner:
        raise ValueError("Владелец не привязан")
    tg.send(owner["id"], "Проверка связи: бот работает.")
    return {"ok": True}


def get_cards():
    try:
        data = json.loads(CARDS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = []
    return {"cards": data if isinstance(data, list) else []}


def set_cards(b):
    out = []
    for c in (b.get("cards") or [])[:40]:
        name, cmd, color = str(c.get("name") or "").strip()[:40], str(c.get("command") or "").strip()[:300], str(c.get("color") or "")
        if name and cmd:
            out.append({"id": str(c.get("id") or len(out))[:20], "name": name, "command": cmd, "confirm": bool(c.get("confirm")),
                        "color": color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#0a84ff"})
    CARDS.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


def asf_run(b):
    """Действие или команда для нескольких ботов: {bots, action | command}."""
    known = {x["name"] for x in asf.list_bots()}
    bots = [n for n in b.get("bots") or [] if n in known]
    if not bots:
        raise ValueError("Не выбраны аккаунты")
    out = []
    if b.get("action"):
        if b["action"] not in ("Pause", "Resume", "Start", "Stop"):
            raise ValueError("Неизвестное действие")
        for name in bots:
            try:
                out.append(f"{name}: {asf.bot_action(name, b['action'])}")
            except RuntimeError as exc:
                out.append(f"{name}: ошибка — {exc}")
    else:
        tpl = str(b.get("command") or "").strip()
        if not tpl:
            raise ValueError("Пустая команда")
        for cmd in ([tpl.replace("{bot}", n) for n in bots] if "{bot}" in tpl else [tpl.replace("{bots}", ",".join(bots))]):
            out.append(asf.send_command(cmd))
    who = ", ".join(bots[:3]) + ("…" if len(bots) > 3 else "")
    log_act(f"{b.get('action') or str(b.get('command')).split()[0]}: {who} ({len(bots)})")
    return {"result": "\n".join(out)}


def _by_bot(text):
    out = {}
    for line in str(text).splitlines():
        m = re.match(r"\s*<([^>]+)>\s*(.*)", line)
        if m:
            out[m[1]] = m[2]
    return out


def refresh_stats(b):
    """Баланс и уровень через команды ASF `balance` и `level` (бот ↔ аккаунт по логину)."""
    bots = [x for x in asf.list_bots() if x["login"] and (not b.get("bots") or x["name"] in b["bots"])]
    pairs = [(db.find_account_by_login(x["login"]), x["name"]) for x in bots]
    pairs = [(a, n) for a, n in pairs if a]
    if not pairs:
        raise ValueError("Не нашёл аккаунтов в ASF: логин должен совпадать с SteamLogin бота")
    joined = ",".join(n for _, n in pairs)
    raw_b, raw_l = asf.send_command("balance " + joined), asf.send_command("level " + joined)
    bal, lvl, updated = _by_bot(raw_b), _by_bot(raw_l), 0
    for acc, name in pairs:
        f = {}
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*([A-Za-z]{3})\b", bal.get(name, ""))
        if m:
            f["balance"] = f"{m[1].replace(',', '.')} {m[2].upper()}"
        m = re.search(r"(\d+)\D*$", lvl.get(name, ""))
        if m:
            f["level"] = int(m[1])
        if f:
            db.update_account_fields(acc["id"], f)
            updated += 1
    log_act(f"Баланс и лвл обновлены: {updated} из {len(pairs)}")
    return {"updated": updated, "bots": len(pairs), "raw": (str(raw_b) + "\n" + str(raw_l))[:600]}


_mini_user = threading.local()


def miniapp_url():
    url = envfile.get("MINIAPP_URL")
    return url if url.lower().startswith("https://") else ""


def _host_ok(host, path):
    """Чужой HTTPS-хост из MINIAPP_URL видит только панель, не весь локальный API."""
    if host in HOSTS:
        return True
    url = miniapp_url()
    if not url or urlparse(url).netloc != (host or ""):
        return False
    clean = (path or "").split("?", 1)[0]
    return clean == "/miniapp" or clean.startswith("/miniapp/") or clean.startswith("/api/mini/")


def _dash(value):
    if value is None:
        return "—"
    text = str(value).strip()
    return text if text else "—"


def verify_webapp(init_data):
    """Проверяет подпись Telegram.WebApp.initData и права человека в боте."""
    raw = str(init_data or "").strip()
    if not raw or len(raw) > 32768:
        raise ValueError("Открой панель кнопкой в боте")
    token = envfile.get("TELEGRAM_BOT_TOKEN") or str(tgbot.load().get("token") or "")
    if not token:
        raise ValueError("Бот не подключён")
    pairs = []
    for part in raw.split("&"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        pairs.append((unquote(key), unquote(value)))
    data = dict(pairs)
    their = data.pop("hash", "")
    if not their:
        raise ValueError("Нет подписи Telegram")
    check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, their):
        raise ValueError("Подпись Telegram не сошлась")
    try:
        auth_date = int(data.get("auth_date") or 0)
    except ValueError:
        raise ValueError("Подпись Telegram не сошлась") from None
    if auth_date <= 0 or time.time() - auth_date > 86400 or auth_date > time.time() + 30:
        raise ValueError("Сессия Telegram устарела. Открой панель снова.")
    try:
        user = json.loads(data.get("user") or "{}")
    except json.JSONDecodeError:
        raise ValueError("Подпись Telegram не сошлась") from None
    uid = user.get("id")
    if not isinstance(uid, int):
        raise ValueError("Нет доступа")
    person = tgbot.who(uid)
    if not person:
        raise ValueError("Нет доступа. Попроси у владельца ссылку.")
    person["tg_name"] = str(user.get("first_name") or person.get("name") or "")
    person["username"] = str(user.get("username") or "")
    return person


def _mini_person():
    person = getattr(_mini_user, "who", None)
    if not person:
        raise ValueError("Нет доступа")
    return person


def _mini_items(person):
    items = Ctx.roster()
    if person.get("accounts") == "*":
        return items
    allow = {str(x).lower() for x in person.get("accounts") or []}
    return [a for a in items if a["login"].lower() in allow or str(a.get("bot") or "").lower() in allow]


def _can(person, perm):
    return person.get("role") == "owner" or perm in person.get("perms", ())


def _kind(state, cards):
    text = str(state or "")
    if "ошиб" in text.lower():
        return "error"
    if text == "онлайн" and str(cards).strip() in ("0",):
        return "online"
    if text == "онлайн":
        return "farm"
    if text.startswith("онлайн"):
        return "online"
    return "off"


def _cards_num(value):
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _asf_version():
    try:
        if not asf.ipc_alive():
            return "—"
        payload = asf._ipc("GET", "/Api/ASF", timeout=1.2)
    except (OSError, RuntimeError, ValueError, TypeError):
        return "—"
    result = payload.get("Result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return "—"
    return _dash(result.get("Version") or result.get("version"))


def _bot_settings(name):
    empty = {"enabled": "—", "farming": "—", "trades": "—", "file": "—"}
    if not name or any(ch in name for ch in "/\\"):
        return empty
    folder = asf.get_asf_dir()
    if not folder:
        return empty
    path = Path(folder) / "config" / f"{name}.json"
    if not path.is_file():
        return empty
    data = asf._read_json(path)
    if not data:
        return empty
    enabled = data.get("Enabled", True)
    farming = data.get("FarmingOrders") or data.get("FarmingPreferences")
    if isinstance(farming, (list, tuple)):
        farming = ", ".join(str(x) for x in farming if str(x).strip())
    elif isinstance(farming, dict):
        farming = ""
    return {
        "enabled": "да" if enabled else "нет",
        "farming": _dash(farming),
        "trades": "—",
        "file": path.name,
    }


def _mafile_label(login):
    if not login or not sg.get_mafiles_dir():
        return "—"
    try:
        return "есть" if sg.find_shared_secret(login) else "нет"
    except (OSError, ValueError):
        return "—"


def mini_state(b, q):
    person = _mini_person()
    if not _can(person, "view") and not _can(person, "manage") and not _can(person, "balance"):
        raise ValueError("Нет прав на просмотр")
    items = _mini_items(person)
    online = sum(1 for a in items if str(a.get("state") or "").startswith("онлайн"))
    cards = [_cards_num(a.get("cards")) for a in items]
    cards = [n for n in cards if n is not None]
    levels = [a.get("level") for a in items if isinstance(a.get("level"), int)]
    drops = sum(int(a.get("drops") or 0) for a in items)
    income = sum(float(a.get("income") or 0) for a in items)
    fresh = "—"
    proxies = None
    if person.get("role") == "owner":
        have = {str(a.get("login") or "").strip().lower() for a in db.get_all_accounts()}
        fresh = sum(1 for bot in asf.list_bots() if str(bot.get("login") or "").strip().lower() not in have and str(bot.get("login") or "").strip())
        used = len({a.get("proxy_id") for a in db.get_all_accounts() if a.get("proxy_id")})
        proxies = {"total": len(db.get_all_proxies()), "used": used}
    try:
        running = asf.ipc_alive() or asf.process_exists()
    except (OSError, UnicodeError, RuntimeError):
        running = False
    bots = []
    for a in items:
        bots.append({
            "key": a.get("key") or "",
            "bot": a.get("bot") or "",
            "login": a.get("login") or "",
            "level": a.get("level") if isinstance(a.get("level"), int) else None,
            "state": a.get("state") or "—",
            "cards": _dash(a.get("cards")) if str(a.get("cards") or "").strip() not in ("", "—") else "—",
            "kind": _kind(a.get("state"), a.get("cards")),
            "proxy": a.get("proxy") or "",
            "drops": int(a.get("drops") or 0),
            "income": float(a.get("income") or 0),
        })
    return {
        "me": {
            "name": person.get("tg_name") or person.get("name") or "—",
            "role": "владелец" if person.get("role") == "owner" else "сотрудник",
            "username": person.get("username") or "",
            "owner": person.get("role") == "owner",
            "manage": _can(person, "manage"),
            "card": _can(person, "view") or _can(person, "manage"),
        },
        "asf": {"running": bool(running), "version": _asf_version(), "updated": time.strftime("%H:%M:%S")},
        "online": online,
        "total": len(items),
        "farm_progress": "—",
        "cards_left": sum(cards) if cards else "—",
        "cards_bots": len(cards) if cards else "—",
        "level_avg": str(round(sum(levels) / len(levels), 1)).replace(".", ",") if levels else "—",
        "level_delta": "—",
        "drops": drops,
        "drops_delta": "—",
        "income": f"{income:.2f}" if items else "—",
        "inventory": "—",
        "import_new": fresh,
        "proxies": proxies,
        "bots": bots,
        "bot_username": tg.username or "—",
    }


def mini_account(b, q):
    person = _mini_person()
    if not _can(person, "view") and not _can(person, "manage"):
        raise ValueError("Нет прав на просмотр")
    key = str((q.get("key") or [""])[0]).strip()
    name = str((q.get("bot") or [""])[0]).strip()
    items = _mini_items(person)
    found = None
    if key:
        found = next((a for a in items if a.get("key") == key), None)
    elif name:
        found = next((a for a in items if a.get("bot") == name), None)
    if not found:
        raise ValueError("Нет доступа к этому боту")
    name = str(found.get("bot") or "")
    login = found.get("login") or ""
    acc = db.find_account_by_login(login) if login else None
    settings = _bot_settings(name)
    index = next((i for i, a in enumerate(items, 1) if a.get("key") == found.get("key")), 0)
    ipc = asf.ipc_base()
    host = urlparse(ipc).hostname or ""
    detail = {
        "key": found.get("key") or "",
        "bot": name,
        "login": login or "—",
        "index": index,
        "total": len(items),
        "state": found.get("state") or "—",
        "kind": _kind(found.get("state"), found.get("cards")),
        "level": found.get("level") if isinstance(found.get("level"), int) else None,
        "steam_id": _dash((acc or {}).get("steam_id")),
        "proxy": found.get("proxy") or "—",
        "mafile": _mafile_label(login),
        "enabled": settings["enabled"],
        "farming": settings["farming"],
        "trades": settings["trades"],
        "cards": _dash(found.get("cards")) if str(found.get("cards") or "").strip() not in ("", "—") else "—",
        "file": settings["file"],
        "manage": _can(person, "manage"),
        "ipc_local": host in ("127.0.0.1", "localhost", "::1", ""),
        "badges": steam_badges.summary_for(BADGES, login),
    }
    if person.get("role") == "owner":
        detail["password"] = str((acc or {}).get("password") or "")
    else:
        detail["password_locked"] = True
    return detail


def mini_action(b, q):
    person = _mini_person()
    act = str(b.get("action") or "")
    items = _mini_items(person)
    if act == "import":
        if person.get("role") != "owner":
            raise ValueError("Импорт доступен только владельцу")
        result = import_asf_accounts()
        return {"message": f"Добавлено: {result['added']}. Уже были: {result['skipped']}."}
    if act in ("start_all", "pause_all"):
        if not _can(person, "manage"):
            raise ValueError("Нет прав на управление")
        names = [a["bot"] for a in items if a.get("bot")]
        note = ""
        if act == "start_all" and person.get("role") == "owner":
            try:
                note = asf.start_asf()
            except RuntimeError as exc:
                note = str(exc)
        if not names:
            return {"message": note or "Нет ботов ASF"}
        text = Ctx.run("Start" if act == "start_all" else "Pause", names, None)
        return {"message": (note + "\n" + text).strip()}
    if act in ("start", "pause"):
        if not _can(person, "manage"):
            raise ValueError("Нет прав на управление")
        name = str(b.get("bot") or "").strip()
        if not name or any(ch in name for ch in "/\\"):
            raise ValueError("Нет такого бота")
        if not any(a.get("bot") == name for a in items):
            raise ValueError("Нет доступа к этому боту")
        return {"message": asf.bot_action(name, "Start" if act == "start" else "Pause")}
    raise ValueError("Неизвестное действие")


def _read_board():
    try:
        data = json.loads(BOARD.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    badges = data.get("badges") if isinstance(data.get("badges"), list) else []
    return {"tasks": tasks[-400:], "badges": badges[-300:]}


def _write_board(data):
    BOARD.write_text(json.dumps({"tasks": data["tasks"][-400:], "badges": data["badges"][-300:]}, ensure_ascii=False, indent=2), encoding="utf-8")


def _bot_names():
    return {x["name"] for x in asf.list_bots()}


def _task_command(kind, bot, params):
    if kind == "play":
        return f"play {bot} {params['appid']}"
    if kind == "nick":
        return f"nickname {bot} {params['text']}"
    if kind == "privacy":
        return f"privacy {bot} {params['text']}"
    if kind == "points":
        return f"points {bot}"
    if kind == "inv":
        return f"inventory {bot}"
    if kind == "level":
        return f"level {bot}"
    if kind == "custom":
        return params["command"].replace("{bot}", bot)
    return ""


def _task_params(kind, body):
    if kind == "play":
        appid = str(body.get("appid") or "").strip()
        if not appid.isdigit() or not 1 <= len(appid) <= 10:
            raise ValueError("Нужен AppID игры, которая уже есть на аккаунте")
        try:
            minutes = int(body.get("minutes") or 0)
        except (TypeError, ValueError):
            raise ValueError("Минуты — число") from None
        if not 1 <= minutes <= 360:
            raise ValueError("Минуты: от 1 до 360")
        return {"appid": appid, "minutes": minutes}, f"Часы · {appid} · {minutes} мин"
    if kind == "nick":
        text = str(body.get("text") or "").strip()
        if not text or len(text) > 32 or any(ch in text for ch in "\n\r\""):
            raise ValueError("Ник: до 32 символов, без кавычек и переноса")
        return {"text": text}, f"Ник · {text}"
    if kind == "privacy":
        text = str(body.get("text") or "").strip()
        if not re.fullmatch(r"[0-9A-Za-z, ]{1,40}", text):
            raise ValueError("Приватность: цифры и запятые, как в команде ASF")
        return {"text": text}, "Приватность"
    if kind in ("points", "inv", "level", "pause", "resume"):
        titles = {"points": "Поинты", "inv": "Инвентарь", "level": "Уровень", "pause": "Пауза фарма", "resume": "Продолжить фарм"}
        return {}, titles[kind]
    if kind == "manual":
        title = str(body.get("title") or "").strip()
        if not title or len(title) > 80:
            raise ValueError("Нужно название отметки")
        return {}, title
    if kind == "custom":
        command = str(body.get("command") or "").replace("\r", "").strip()
        if not command or len(command) > 200 or "\n" in command or "{ask:" in command:
            raise ValueError("Команда ASF: одна строка до 200 символов, с {bot}")
        if "{bot}" not in command:
            raise ValueError("В команде нужен {bot}")
        title = str(body.get("title") or "").strip()[:40] or command[:40]
        return {"command": command}, title
    raise ValueError("Неизвестный тип задачи")


def board_state():
    with _board_lock:
        return _read_board()


def board_task(b, q):
    op = str(b.get("op") or "add")
    with _board_lock:
        data = _read_board()
        if op == "add":
            kind = str(b.get("kind") or "")
            params, title = _task_params(kind, b)
            names = [n for n in b.get("bots") or [] if n in _bot_names()]
            if not names:
                raise ValueError("Отметь ботов ASF")
            now = time.strftime("%d.%m %H:%M")
            known = {x["name"]: x.get("login") or "" for x in asf.list_bots()}
            for name in names[:40]:
                data["tasks"].append({
                    "id": secrets.token_hex(4),
                    "bot": name,
                    "login": known.get(name) or "",
                    "kind": kind,
                    "title": title,
                    "params": params,
                    "status": "queue",
                    "note": "",
                    "created": now,
                    "finished": "",
                })
            _write_board(data)
            log_act(f"Задачи прогрева: {title} × {min(len(names), 40)}")
            return {"tasks": data["tasks"], "added": min(len(names), 40)}
        ids = {str(x) for x in b.get("ids") or []}
        if op == "delete":
            data["tasks"] = [t for t in data["tasks"] if t.get("id") not in ids]
        elif op == "clear":
            data["tasks"] = [t for t in data["tasks"] if t.get("status") not in ("done", "error")]
        elif op == "done":
            for task in data["tasks"]:
                if task.get("id") in ids and task.get("kind") == "manual":
                    task["status"] = "done"
                    task["finished"] = time.strftime("%d.%m %H:%M")
        else:
            raise ValueError("Неизвестное действие")
        _write_board(data)
        return {"tasks": data["tasks"]}


def _run_one(task):
    kind = task.get("kind")
    bot = task.get("bot") or ""
    if bot not in _bot_names():
        raise RuntimeError("Бота уже нет в ASF")
    if kind == "manual":
        raise RuntimeError("Отметку закрывают кнопкой «Готово»")
    if kind == "pause":
        return asf.bot_action(bot, "Pause")
    if kind == "resume":
        return asf.bot_action(bot, "Resume")
    command = _task_command(kind, bot, task.get("params") or {})
    if not command:
        raise RuntimeError("У задачи нет команды")
    return asf.send_command(command)


def board_run(b, q):
    ids = [str(x) for x in b.get("ids") or []]
    if not ids:
        raise ValueError("Нет задач")
    if len(ids) > 30:
        raise ValueError("За раз не больше 30 задач")
    with _board_lock:
        data = _read_board()
        todo = [dict(t) for t in data["tasks"] if t.get("id") in ids and t.get("status") == "queue"]
        playing = {t.get("bot") for t in data["tasks"] if t.get("status") == "run" and t.get("kind") == "play"}
    now = time.time()
    stamp = time.strftime("%d.%m %H:%M")
    updates = {}
    for task in todo:
        if task.get("kind") == "play" and task.get("bot") in playing:
            updates[task["id"]] = {"status": "error", "note": "На этом боте уже идут часы", "finished": stamp}
            continue
        try:
            note = _run_one(task)
        except (RuntimeError, ValueError, OSError) as exc:
            updates[task["id"]] = {"status": "error", "note": str(exc)[:200], "finished": stamp}
            continue
        if task.get("kind") == "play":
            minutes = int((task.get("params") or {}).get("minutes") or 0)
            updates[task["id"]] = {"status": "run", "note": str(note or "")[:200], "until": now + minutes * 60}
            playing.add(task.get("bot"))
        else:
            updates[task["id"]] = {"status": "done", "note": str(note or "")[:200], "finished": stamp}
    with _board_lock:
        data = _read_board()
        for task in data["tasks"]:
            patch = updates.get(task.get("id"))
            if patch and task.get("status") == "queue":
                task.update(patch)
        _write_board(data)
    if updates:
        log_act(f"Прогрев: обработано {len(updates)}")
    return {"tasks": data["tasks"], "started": len(updates)}


def _finish_due_tasks():
    now = time.time()
    stamp = time.strftime("%d.%m %H:%M")
    with _board_lock:
        data = _read_board()
        changed = False
        for task in data["tasks"]:
            if task.get("status") != "run" or task.get("kind") != "play":
                continue
            try:
                due = float(task.get("until") or 0)
            except (TypeError, ValueError):
                due = 0
            if not due or due > now:
                continue
            bot = str(task.get("bot") or "")
            try:
                if bot in _bot_names():
                    asf.send_command("reset " + bot)
                task["status"] = "done"
                task["note"] = "Время вышло, ASF снова фармит карты"
                task["finished"] = stamp
                changed = True
            except (RuntimeError, OSError) as exc:
                task["note"] = str(exc)[:200]
                changed = True
        if changed:
            _write_board(data)


def _watch_tasks():
    while True:
        time.sleep(20)
        try:
            _finish_due_tasks()
        except Exception:
            pass


def _watch_badges():
    """Редкая проверка публичных значков. Первый проход не сразу после старта."""
    time.sleep(60)
    while True:
        try:
            badges_check()
        except Exception:
            pass
        time.sleep(1800)


def badges_public():
    with _badge_lock:
        running = _badge_running
    return steam_badges.public_view(steam_badges.read_cache(BADGES), running)


def _badge_notify(lines):
    owner = tgbot.load().get("owner")
    if not owner or not (tg.thread and tg.thread.is_alive()):
        return
    tg.send(owner["id"], "Значки Steam:\n" + "\n".join(lines))


def _badge_job():
    global _badge_running
    try:
        rows = []
        for acc in db.get_all_accounts():
            login = str(acc.get("login") or "").strip()
            if login:
                rows.append({"login": login, "steam_id": str(acc.get("steam_id") or "")})
        steam_badges.refresh(BADGES, rows, notify=_badge_notify, pause=1.5)
        log_act("Проверка значков Steam")
    except Exception:
        pass
    finally:
        with _badge_lock:
            _badge_running = False


def badges_check():
    """Фоновая проверка. Один запрос не ждёт все профили."""
    global _badge_running
    with _badge_lock:
        if _badge_running:
            return {"started": False, "running": True}
        _badge_running = True
    threading.Thread(target=_badge_job, name="sfm-badges", daemon=True).start()
    return {"started": True, "running": True}


def board_badge(b, q):
    op = str(b.get("op") or "add")
    with _board_lock:
        data = _read_board()
        if op == "delete":
            ids = {str(x) for x in b.get("ids") or []}
            data["badges"] = [x for x in data["badges"] if x.get("id") not in ids]
        else:
            name = str(b.get("name") or "").strip()[:60]
            if not name:
                raise ValueError("Нужно название бейджа")
            kind = str(b.get("kind") or "game")
            if kind not in ("game", "community", "event"):
                raise ValueError("Тип бейджа: игра, сообщество или ивент")
            appid = str(b.get("appid") or "").strip()
            if appid and not appid.isdigit():
                raise ValueError("AppID — число")
            def num(key, limit):
                try:
                    value = int(b.get(key) or 0)
                except (TypeError, ValueError):
                    raise ValueError("Уровень и карты — числа") from None
                if not 0 <= value <= limit:
                    raise ValueError("Слишком большое число")
                return value
            level, target, cards = num("level", 5), num("target", 5), num("cards", 99)
            if target < 1:
                target = 5
            item = {
                "id": str(b.get("id") or "")[:16] or secrets.token_hex(4),
                "login": str(b.get("login") or "").strip()[:40],
                "kind": kind,
                "name": name,
                "appid": appid[:10],
                "level": level,
                "target": target,
                "cards": cards,
                "note": str(b.get("note") or "").strip()[:120],
            }
            if not item["login"]:
                raise ValueError("Выбери аккаунт")
            found = False
            for i, old in enumerate(data["badges"]):
                if old.get("id") == item["id"]:
                    data["badges"][i] = item
                    found = True
                    break
            if not found:
                data["badges"].append(item)
        _write_board(data)
        return {"badges": data["badges"]}


def _read_games():
    with _games_lock:
        try:
            data = json.loads(GAMES.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    items = []
    for it in (data.get("items") or [])[:120]:
        if not isinstance(it, dict):
            continue
        kind, gid = str(it.get("kind") or ""), str(it.get("id") or "")
        if kind not in ("app", "sub") or not gid.isdigit():
            continue
        num = int(gid)
        if not 1 <= num <= 2_000_000_000:
            continue
        title = str(it.get("title") or "")
        if "http" in title.lower() or "://" in title:
            title = ""
        items.append({"kind": kind, "id": str(num), "title": title[:80], "when": str(it.get("when") or "")[:20]})
    channel = str(data.get("channel") or "")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", channel):
        channel = ""
    raw_before = data.get("before")
    before = int(raw_before) if str(raw_before or "").isdigit() and int(raw_before) > 0 else None
    def num(key):
        raw = data.get(key) or 0
        return int(raw) if str(raw).isdigit() else 0
    return {
        "channel": channel, "fetched": str(data.get("fetched") or "")[:20],
        "items": items, "skipped": num("skipped"), "posts": num("posts"), "before": before,
    }


def _write_games(data):
    clean = {
        "channel": data.get("channel") or "",
        "fetched": data.get("fetched") or "",
        "skipped": int(data.get("skipped") or 0),
        "posts": int(data.get("posts") or 0),
        "before": data.get("before"),
        "items": data.get("items") or [],
    }
    with _games_lock:
        GAMES.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def games_state():
    return _read_games()


def _merge_games(old, new):
    seen = {(it["kind"], it["id"]) for it in old}
    out = list(old)
    for it in new:
        key = (it["kind"], it["id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:120]


def games_fetch(b):
    """Обновляет список или листает старше. Сама в ASF ничего не отправляет."""
    current = _read_games()
    more = bool(b.get("more"))
    name = channel_games.channel_name(b.get("channel") or current["channel"])
    if more and (not current["before"] or current["channel"] != name):
        raise ValueError("Сначала обнови канал")
    found = channel_games.fetch_preview(name, before=current["before"] if more else None, pages=3 if more else 4)
    if more:
        found["items"] = _merge_games(current["items"], found["items"])
        found["skipped"] += current["skipped"]
        found["posts"] += current["posts"]
    found["fetched"] = time.strftime("%d.%m %H:%M")
    _write_games(found)
    return _read_games()


def games_add(b):
    known = {x["name"] for x in asf.list_bots()}
    bots = []
    for name in b.get("bots") or []:
        if name in known and name not in bots:
            bots.append(name)
    commands = channel_games.license_commands(bots, b.get("items") or [])
    out = [asf.send_command(cmd) for cmd in commands]
    count = sum(len(cmd.split(" ", 2)[2].split(",")) for cmd in commands)
    log_act(f"addlicense: {count} игр → {len(bots)} бот.")
    return {"result": "\n".join(out), "count": count}


ROUTES = {
    ("GET", "/api/state"): lambda b, q: state(),
    ("POST", "/api/reveal"): lambda b, q: reveal(b),
    ("GET", "/api/asf"): lambda b, q: asf_state(),
    ("GET", "/api/login-status"): lambda b, q: login_status,
    ("GET", "/api/templates"): lambda b, q: {"accounts": ex.ACCOUNT_TEMPLATES, "proxies": ex.PROXY_TEMPLATES},
    ("GET", "/api/export"): lambda b, q: export(q),
    ("POST", "/api/account"): lambda b, q: save_account(b),
    ("POST", "/api/account/delete"): lambda b, q: db.delete_account(int(b["id"])) or {"ok": True},
    ("POST", "/api/proxy"): lambda b, q: save_proxy(b),
    ("POST", "/api/proxy/delete"): lambda b, q: db.delete_proxy(int(b["id"])) or {"ok": True},
    ("POST", "/api/assign"): lambda b, q: dict(zip(("assigned", "left"), db.assign_proxies_one_to_one())),
    ("POST", "/api/proxies/push"): lambda b, q: push_proxies(),
    ("POST", "/api/import"): lambda b, q: import_(b),
    ("POST", "/api/login"): lambda b, q: start_login(b),
    ("POST", "/api/settings"): lambda b, q: set_settings(b),
    ("POST", "/api/setup"): lambda b, q: save_setup(b),
    ("POST", "/api/browse"): lambda b, q: browse_folder(b),
    ("POST", "/api/asf/import"): lambda b, q: import_asf_accounts(),
    ("POST", "/api/asf/start"): lambda b, q: {"message": asf.start_asf()},
    ("POST", "/api/asf/stop"): lambda b, q: {"message": asf.stop_asf()},
    ("POST", "/api/asf/bot"): lambda b, q: {"message": asf.bot_action(b.get("name", ""), b.get("action", ""))},
    ("GET", "/api/activity"): lambda b, q: get_activity(),
    ("GET", "/api/tg"): lambda b, q: tg_state(),
    ("POST", "/api/tg/token"): lambda b, q: tg_token(b),
    ("POST", "/api/tg/invite"): lambda b, q: tg_invite(b),
    ("POST", "/api/tg/employee"): lambda b, q: tg_employee(b),
    ("POST", "/api/tg/employee/delete"): lambda b, q: tg_delete(b),
    ("POST", "/api/tg/unlink"): lambda b, q: tg_unlink(b),
    ("POST", "/api/tg/test"): lambda b, q: tg_test(b),
    ("GET", "/api/cards"): lambda b, q: get_cards(),
    ("POST", "/api/cards"): lambda b, q: set_cards(b),
    ("GET", "/api/board"): lambda b, q: board_state(),
    ("POST", "/api/board/task"): lambda b, q: board_task(b, q),
    ("POST", "/api/board/run"): lambda b, q: board_run(b, q),
    ("POST", "/api/board/badge"): lambda b, q: board_badge(b, q),
    ("GET", "/api/games"): lambda b, q: games_state(),
    ("POST", "/api/games/fetch"): lambda b, q: games_fetch(b),
    ("POST", "/api/games/add"): lambda b, q: games_add(b),
    ("GET", "/api/badges/live"): lambda b, q: badges_public(),
    ("POST", "/api/badges/check"): lambda b, q: badges_check(),
    ("POST", "/api/asf/run"): lambda b, q: asf_run(b),
    ("POST", "/api/main"): lambda b, q: db.set_main_account(int(b["id"])) or {"ok": True},
    ("POST", "/api/fields"): lambda b, q: db.update_account_fields(int(b["id"]), b.get("fields") or {}) or {"ok": True},
    ("POST", "/api/refresh"): lambda b, q: refresh_stats(b),
    ("POST", "/api/asf/command"): lambda b, q: {"result": asf.send_command(b.get("command", ""))},
    ("GET", "/api/mini/state"): lambda b, q: mini_state(b, q),
    ("GET", "/api/mini/account"): lambda b, q: mini_account(b, q),
    ("POST", "/api/mini/action"): lambda b, q: mini_action(b, q),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method):
        # Защита от чужих сайтов: только наш Host и свой заголовок для записи.
        url = urlparse(self.path)
        if not _host_ok(self.headers.get("Host"), url.path):
            return self._send(403, {"error": "forbidden"})
        if not url.path.startswith("/api/"):
            return self._static(url.path) if method == "GET" else self._send(405, {"error": "method"})
        size = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(size) if size else b""
        if _panel_token_required(url.path) and not vault.token_matches(self.headers.get("Authorization")):
            return self._send(401, {"error": "unauthorized"})
        if method != "GET" and self.headers.get("X-Requested-With") != "sfm":
            return self._send(403, {"error": "forbidden"})
        route = ROUTES.get((method, url.path))
        if not route:
            return self._send(404, {"error": "not found"})
        try:
            if url.path.startswith("/api/mini"):
                _mini_user.who = verify_webapp(self.headers.get("X-Telegram-Init-Data"))
            body = json.loads(raw or b"{}") if raw else {}
            result = route(body, parse_qs(url.query))
        except (ValueError, KeyError, RuntimeError, TypeError) as exc:
            return self._send(400, {"error": str(exc) or exc.__class__.__name__})
        except Exception as exc:
            return self._send(500, {"error": f"{exc.__class__.__name__}: {exc}"})
        finally:
            _mini_user.who = None
        if isinstance(result, tuple):
            data, ctype, name = result
            return self._send(200, data, ctype, {"Content-Disposition": f"attachment; filename={name}"})
        self._send(200, result)

    def _static(self, path):
        clean = path.rstrip("/") or "/"
        if clean == "/miniapp":
            path = "/miniapp/index.html"
        target = (WEB / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if WEB.resolve() not in target.parents or not target.is_file():
            return self._send(404, {"error": "not found"})
        extra = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml"}
        ctype = mimetypes.guess_type(target.name)[0] or extra.get(target.suffix.lower(), "application/octet-stream")
        if ctype.startswith("text") or "javascript" in ctype or ctype.endswith("+xml"):
            ctype += "; charset=utf-8"
        data = target.read_bytes()
        if target == (WEB / "index.html").resolve():
            token = json.dumps(vault.ensure_api_token()[0])
            needle = b'<script src="app.js"></script>'
            data = data.replace(needle, f"<script>window.SFM_TOKEN={token};</script>{needle.decode()}".encode(), 1)
        headers = {"Cache-Control": "no-store"} if path.startswith("/miniapp") else None
        self._send(200, data, ctype, headers)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def _edge_path():
    for path in (
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ):
        if path and os.path.isfile(path):
            return path
    return None


def open_app_window(url):
    """Окно без вкладок и адресной строки. Отдельный профиль, чтобы не трогать обычный Edge."""
    edge = _edge_path()
    if not edge:
        webbrowser.open(url)
        return None
    profile = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "SteamFarmManager" / "window"
    profile.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([
        edge,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--window-size=1280,840",
        "--no-first-run",
        "--disable-features=Translate",
    ])


def _panel_token_required(path: str) -> bool:
    """Токен окна нужен всему /api, кроме Mini App и вебхука Telegram.

    Mini App доказывает личность подписью initData. Вебхука в программе нет:
    путь оставлен открытым, чтобы проверка не отвергала его заранее.
    """
    clean = (path or "").split("?", 1)[0]
    if clean.startswith("/api/mini/"):
        return False
    if clean in ("/api/telegram/webhook", "/api/tg/webhook"):
        return False
    return True


def main():
    db.init_db()
    vault.announce_api_token()
    threading.Thread(target=_watch_tasks, daemon=True).start()
    threading.Thread(target=_watch_badges, daemon=True).start()
    if tgbot.load()["token"]:
        tg.start()
    url = f"http://127.0.0.1:{PORT}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"Уже запущено: {url}")
        if "--no-browser" not in sys.argv:
            open_app_window(url)
        return
    print(f"Steam Farm Manager: {url}")
    if "--no-browser" in sys.argv:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    window = open_app_window(url)
    if window is None:
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return
    try:
        window.wait()
    except KeyboardInterrupt:
        window.terminate()
    server.shutdown()


if __name__ == "__main__":
    main()
