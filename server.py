"""Steam Farm Manager: локальный веб-интерфейс.  Запуск: python server.py"""

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
from urllib.parse import parse_qs, urlparse

import asf_manager as asf
import browser_login
import database as db
import exchange as ex
import steam_guard as sg
import tgbot

WEB = Path(__file__).parent / "web"
PORT = int(os.environ.get("SFM_PORT", "8765"))
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
login_status = {"text": "", "kind": ""}
CARDS = Path(__file__).parent / "cards.json"
ACTIVITY = Path(__file__).parent / "activity.json"


def _status(text, kind=None):
    login_status.update(text=text, kind=kind or "info")


def state():
    return {
        "accounts": db.get_all_accounts(), "proxies": db.get_all_proxies(), "stats": db.get_stats(),
        "settings": {"mafiles_dir": sg.get_mafiles_dir(), "asf_dir": asf.get_asf_dir()},
    }


def asf_state():
    alive = asf.ipc_alive()
    live = asf.ipc_bots() if alive else {}
    running = alive or asf.process_exists()
    bots = []
    for bot in asf.list_bots():
        text, cards = asf.live_status(bot, live, running)
        bots.append({**bot, "state": text, "cards": cards})
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
        tg.shutdown()
        return tg_state()
    tg.username = tgbot.request(token, "getMe")["username"]
    c["token"] = token
    tgbot.save(c)
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


ROUTES = {
    ("GET", "/api/state"): lambda b, q: state(),
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
    ("POST", "/api/asf/run"): lambda b, q: asf_run(b),
    ("POST", "/api/main"): lambda b, q: db.set_main_account(int(b["id"])) or {"ok": True},
    ("POST", "/api/fields"): lambda b, q: db.update_account_fields(int(b["id"]), b.get("fields") or {}) or {"ok": True},
    ("POST", "/api/refresh"): lambda b, q: refresh_stats(b),
    ("POST", "/api/asf/command"): lambda b, q: {"result": asf.send_command(b.get("command", ""))},
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
        if self.headers.get("Host") not in HOSTS:
            return self._send(403, {"error": "forbidden"})
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self._static(url.path) if method == "GET" else self._send(405, {"error": "method"})
        if method != "GET" and self.headers.get("X-Requested-With") != "sfm":
            return self._send(403, {"error": "forbidden"})
        route = ROUTES.get((method, url.path))
        if not route:
            return self._send(404, {"error": "not found"})
        try:
            size = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(size) or b"{}") if size else {}
            result = route(body, parse_qs(url.query))
        except (ValueError, KeyError, RuntimeError, TypeError) as exc:
            return self._send(400, {"error": str(exc) or exc.__class__.__name__})
        except Exception as exc:
            return self._send(500, {"error": f"{exc.__class__.__name__}: {exc}"})
        if isinstance(result, tuple):
            data, ctype, name = result
            return self._send(200, data, ctype, {"Content-Disposition": f"attachment; filename={name}"})
        self._send(200, result)

    def _static(self, path):
        target = (WEB / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if WEB.resolve() not in target.parents or not target.is_file():
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") or "javascript" in ctype else ""))

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


def main():
    db.init_db()
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
