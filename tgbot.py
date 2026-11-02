"""Telegram-бот: владелец и сотрудники с ограниченными правами.
Через бота доступны только статус, баланс, уровень, инвентарь и безопасные действия.
Пароли, почты и maFiles в Telegram не отправляются."""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import envfile
import runtime

envfile.load()

CFG = runtime.data_dir() / "telegram.json"
PERMS = {"view": "Статус и инвентарь", "balance": "Баланс и уровень", "manage": "Пауза, старт, стоп", "transfer": "Передача предметов"}
ACTIONS = {"Pause": ("manage", "Пауза"), "Resume": ("manage", "Продолжить"), "Start": ("manage", "Старт"), "Stop": ("manage", "Стоп"),
           "Inv": ("view", "Инвентарь"), "Transfer": ("transfer", "Передать главному")}
LOCK = threading.Lock()
BACK = [[("« Меню", "m")]]


def _btn(item):
    if isinstance(item, dict):
        return item
    title, data = item
    return {"text": title, "callback_data": data}


def panel_url():
    """Кнопка Mini App только для публичного HTTPS. HTTP и пустое значение не отправляются."""
    url = envfile.get("MINIAPP_URL")
    return url if url.lower().startswith("https://") else ""


def request(token, method, **params):
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=params.get("timeout", 0) + 15) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read() or b"{}")
        except ValueError:
            data = {}
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"Нет связи с Telegram: {exc}")
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or "Ошибка Telegram")
    return data["result"]


def load():
    try:
        c = json.loads(CFG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    for key, default in (("token", ""), ("owner", None), ("employees", []), ("invites", {})):
        c.setdefault(key, default)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        c["token"] = token
    owner_id = os.environ.get("TELEGRAM_OWNER_ID", "").strip()
    if owner_id.isdigit():
        name = os.environ.get("TELEGRAM_OWNER_NAME", "").strip()
        if not name and isinstance(c.get("owner"), dict):
            name = str(c["owner"].get("name") or "")
        c["owner"] = {"id": int(owner_id), "name": name or "Владелец"}
    return c


def save(c):
    CFG.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")


def who(uid):
    c = load()
    if c["owner"] and c["owner"]["id"] == uid:
        return {"role": "owner", "name": c["owner"]["name"], "perms": set(PERMS), "accounts": "*"}
    for e in c["employees"]:
        if e.get("id") == uid:
            return {"role": "employee", "name": e["name"], "perms": {k for k, v in e["perms"].items() if v and k in PERMS}, "accounts": e["accounts"]}
    return None


class Bot:
    def __init__(self, ctx):
        self.ctx, self.thread, self.username, self.offset, self.error = ctx, None, "", 0, ""
        self.stop = threading.Event()

    def call(self, method, **params):
        return request(load()["token"], method, **params)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop.clear()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def shutdown(self):
        self.stop.set()
        self.username = ""

    def loop(self):
        while not self.stop.is_set() and load()["token"]:
            try:
                if not self.username:
                    self.username = self.call("getMe")["username"]
                for u in self.call("getUpdates", offset=self.offset, timeout=25, allowed_updates=["message", "callback_query"]):
                    self.offset = u["update_id"] + 1
                    self.handle(u)
                self.error = ""
            except Exception as exc:
                self.error = str(exc)
                time.sleep(5)

    def send(self, chat, text, rows=None):
        chunks = [text[i:i + 3500] for i in range(0, max(len(text), 1), 3500)]
        for index, chunk in enumerate(chunks):
            p = {"chat_id": chat, "text": chunk}
            if rows and index == len(chunks) - 1:
                p["reply_markup"] = {"inline_keyboard": [[_btn(item) for item in row] for row in rows]}
            try:
                self.call("sendMessage", **p)
            except RuntimeError:
                pass

    def handle(self, u):
        m, q = u.get("message"), u.get("callback_query")
        if m and m["chat"].get("type") == "private":
            text = (m.get("text") or "").strip()
            if text.startswith("/start ") and text[7:].strip():
                return self.link(m, text[7:].strip())
            w = who(m["from"]["id"])
            if not w:
                return self.send(m["chat"]["id"], "Нет доступа. Попроси у владельца ссылку-приглашение.")
            cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
            if cmd in ("/status", "/s"):
                return self.callback(m["chat"]["id"], w, "v:status")
            if cmd in ("/balance", "/bal"):
                return self.callback(m["chat"]["id"], w, "v:bal")
            if cmd in ("/cycle", "/c"):
                return self.callback(m["chat"]["id"], w, "v:cycle")
            return self.menu(m["chat"]["id"], w)
        if q and q["message"]["chat"].get("type") == "private":
            try:
                self.call("answerCallbackQuery", callback_query_id=q["id"])
            except RuntimeError:
                pass
            w = who(q["from"]["id"])
            chat = q["message"]["chat"]["id"]
            return self.callback(chat, w, q.get("data") or "") if w else self.send(chat, "Нет доступа.")

    def link(self, m, code):
        uid, chat = m["from"]["id"], m["chat"]["id"]
        name = m["from"].get("first_name") or m["from"].get("username") or str(uid)
        with LOCK:
            c = load()
            inv = c["invites"].pop(code, None)
            ok = bool(inv) and inv["exp"] > time.time()
            if ok and inv["role"] == "owner":
                c["owner"] = {"id": uid, "name": name}
            elif ok:
                e = next((x for x in c["employees"] if x["key"] == inv.get("emp")), None)
                if e:
                    e["id"], e["tg"] = uid, m["from"].get("username") or ""
                else:
                    ok = False
            save(c)
        self.menu(chat, who(uid)) if ok else self.send(chat, "Приглашение недействительно или уже использовано.")

    def mine(self, w):
        items = self.ctx.roster()
        if w["accounts"] == "*":
            return items
        allow = {str(x).lower() for x in w["accounts"]}
        return [a for a in items if a["login"].lower() in allow or str(a.get("bot") or "").lower() in allow]

    def menu(self, chat, w):
        accs, p = self.mine(w), w["perms"]
        on = sum(1 for a in accs if str(a.get("state") or "").startswith("онлайн"))
        asf_n = sum(1 for a in accs if a.get("bot"))
        rows = []
        if "view" in p:
            rows.append([("Статус", "v:status"), ("Инвентарь", "a:Inv")])
        if "balance" in p:
            rows.append([("Сводка", "v:cycle"), ("Баланс и лвл", "v:bal")])
        if "manage" in p:
            rows += [[("Пауза", "a:Pause"), ("Продолжить", "a:Resume")], [("Старт", "a:Start"), ("Стоп", "a:Stop")]]
        if "transfer" in p:
            rows.append([("Передать главному", "a:Transfer")])
        role = "владелец" if w["role"] == "owner" else "сотрудник"
        url = panel_url()
        if url:
            rows.insert(0, [{"text": "Открыть панель", "web_app": {"url": url}}])
        self.send(chat, f"Steam Farm Manager\n{w['name']} · {role}\nБотов ASF: {asf_n}, онлайн: {on}", rows)

    def callback(self, chat, w, data):
        kind, _, rest = data.partition(":")
        accs = self.mine(w)
        if kind == "m":
            return self.menu(chat, w)
        if kind == "v":
            if rest == "status" and "view" in w["perms"]:
                lines = []
                for a in accs:
                    title = a.get("bot") or a["login"]
                    if a.get("bot") and a.get("login") and a["bot"].lower() != a["login"].lower():
                        title = f"{a['bot']} · {a['login']}"
                    cards = f" · карточек: {a['cards']}" if a.get("cards") not in (None, "", "—") else ""
                    proxy = f" · {a['proxy']}" if a.get("proxy") else ""
                    lines.append(f"{title} — {a.get('state') or 'нет бота'}{cards}{proxy}")
                return self.send(chat, "\n".join(lines) or "Нет ботов ASF", BACK)
            if rest == "bal" and "balance" in w["perms"]:
                lines = [f"{a['login']}: {a.get('balance') or '—'} · ур. {a['level'] if a.get('level') is not None else '—'}" for a in accs]
                return self.send(chat, "\n".join(lines) or "Нет ботов ASF", BACK)
            if rest == "cycle" and "balance" in w["perms"]:
                income = sum(float(a.get("income") or 0) for a in accs)
                drops = sum(int(a.get("drops") or 0) for a in accs)
                on = sum(1 for a in accs if str(a.get("state") or "").startswith("онлайн"))
                lines = [f"Онлайн: {on} из {len(accs)}", f"Доход: ${income:.2f}", f"Дроп: {drops} шт."]
                for a in sorted(accs, key=lambda x: float(x.get("income") or 0), reverse=True)[:15]:
                    lines.append(f"{a['login']}: {a.get('rank') or '—'} · дроп {a.get('drops') or 0} · ${float(a.get('income') or 0):.2f}")
                return self.send(chat, "\n".join(lines), BACK)
            return self.send(chat, "Нет прав на это действие.")
        act, _, target = rest.partition(":")
        need = ACTIONS.get(act)
        if kind not in ("a", "r") or not need or need[0] not in w["perms"]:
            return self.send(chat, "Нет прав на это действие.")
        if kind == "a":
            rows = [[(f"Все мои ({len(accs)})", f"r:{act}:all")]] + [[(a.get("bot") or a["login"], f"r:{act}:{a['key']}")] for a in accs[:40]] + BACK
            return self.send(chat, f"{need[1]}: выбери аккаунты", rows)
        self.run(chat, w, act, target, accs)

    def run(self, chat, w, act, target, accs):
        sel = accs if target == "all" else [a for a in accs if a.get("key") == target or str(a.get("id")) == target]
        if not sel:
            return self.send(chat, "Аккаунт недоступен.", BACK)
        main = next((a for a in self.ctx.roster() if a.get("is_main")), None)
        mb = {"name": main["bot"]} if main and main.get("bot") else None
        if act == "Transfer":
            if not mb:
                return self.send(chat, "Главный аккаунт не выбран или его нет в ASF.", BACK)
            sel = [a for a in sel if a.get("id") != main.get("id")]
        pairs = [(a, a["bot"]) for a in sel if a.get("bot")]
        if not pairs:
            return self.send(chat, "У выбранных аккаунтов нет ботов в ASF.", BACK)
        try:
            out = self.ctx.run(act, [n for _, n in pairs], mb["name"] if mb else None)
        except Exception as exc:
            out = f"Ошибка: {exc}"
        who_ = ", ".join(a["login"] for a, _ in pairs[:3]) + ("…" if len(pairs) > 3 else "")
        line = f"{w['name']} (TG): {ACTIONS[act][1]} · {who_} ({len(pairs)})"
        self.ctx.log(line)
        self.send(chat, f"{ACTIONS[act][1]}: {len(pairs)} акк.\n{out}", BACK)
        owner = load()["owner"]
        if w["role"] != "owner" and owner:
            self.send(owner["id"], line)
