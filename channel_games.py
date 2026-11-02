"""Публичная лента t.me/s: только ссылки Steam app/sub.

Чужие сайты получения, ключи и пароли не сохраняются и не открываются.
"""

import html
import re
from urllib.error import URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")
_BOT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_STEAM = re.compile(r"(?:https?:)?//store\.steampowered\.com/(app|sub)/(\d{1,10})\b", re.I)
_KEY = re.compile(r"\b[A-Z0-9]{5}(?:-[A-Z0-9]{5}){2,}\b", re.I)
_PASS = re.compile(r"(?i)(?:парол\w*|password|\bpass)\s*[:=]\s*(\S+)")
_LOGIN = re.compile(r"(?i)(?:логин|login|user(?:name)?)\s*[:=]\s*(\S+)")
_PAIR = re.compile(r"(?<![\w./])(?!https?:)[A-Za-z0-9._-]{3,24}:[A-Za-z0-9._@!$%^*+=?-]{4,32}(?![\w./])")
_NEG = {"не", "нет", "no", "none", "без", "n/a", "-", "—"}


def channel_name(raw) -> str:
    """Публичное имя канала. Ссылка-приглашение и чужой сайт не проходят."""
    text = str(raw or "").strip()
    text = re.sub(r"^https?://", "", text, flags=re.I)
    text = re.sub(r"^(?:t\.me|telegram\.me)/", "", text, flags=re.I)
    if text.lower().startswith("s/"):
        text = text[2:]
    text = text.split("?")[0].split("/")[0].strip()
    if text.startswith("@"):
        text = text[1:]
    if not _NAME.fullmatch(text):
        raise ValueError("Нужно публичное имя канала: @name")
    return text


def _plain(fragment: str) -> str:
    text = unquote(html.unescape(fragment))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<[^>]+>", " ", text)
    return text


def _secret(plain: str) -> bool:
    if _KEY.search(plain) or _PAIR.search(plain):
        return True
    if re.search(r"(?i)shared_secret|identity_secret|mafile", plain):
        return True
    found = _PASS.search(plain)
    if found and found.group(1).lower().strip(".,") not in _NEG:
        return True
    if _LOGIN.search(plain) and re.search(r"(?i)парол|password|\bpass\b", plain):
        return True
    return False


def _title(plain: str, kind: str, gid: str) -> str:
    for line in plain.splitlines():
        line = re.sub(r"https?://\S+", " ", line)
        line = re.sub(r"\s+", " ", line).strip(" -–—|")
        if line:
            return line[:80]
    return ("Игра " if kind == "app" else "Пакет ") + gid


def parse_preview(page: str) -> dict:
    """Один HTML предпросмотра. Возвращает игры, число секретных постов и id для «ещё»."""
    ids = [int(x) for x in re.findall(r'data-post="[^"]+/(\d+)"', page)]
    posts = len(re.findall(r'data-post="[^"]+"', page))
    items, skipped, seen = [], 0, set()
    parts = re.split(r'(?=<div class="tgme_widget_message_wrap\b)', page)
    for part in parts:
        if "tgme_widget_message_wrap" not in part:
            continue
        raw = unquote(html.unescape(part))
        text = re.search(r'class="tgme_widget_message_text\b[^>]*>(.*?)</div>', raw, re.S)
        plain = _plain(text.group(1)) if text else ""
        if plain and _secret(plain):
            skipped += 1
            continue
        when = ""
        stamp = re.search(r'datetime="(\d{4})-(\d{2})-(\d{2})', part)
        if stamp:
            when = f"{stamp.group(3)}.{stamp.group(2)}.{stamp.group(1)}"
        for kind, gid in _STEAM.findall(raw):
            num = int(gid)
            if not 1 <= num <= 2_000_000_000:
                continue
            kind = kind.lower()
            token = (kind, str(num))
            if token in seen:
                continue
            seen.add(token)
            items.append({
                "kind": kind,
                "id": str(num),
                "title": _title(plain, kind, str(num)),
                "when": when,
            })
    return {"items": items, "skipped": skipped, "posts": posts, "before": min(ids) if ids else None}


def _get(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host not in {"t.me", "telegram.me"}:
        raise ValueError("Читаю только открытую ленту t.me")
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ru,en;q=0.8",
    })
    try:
        with urlopen(req, timeout=15) as resp:
            final = (urlparse(resp.geturl()).hostname or "").lower()
            if final not in {"t.me", "telegram.me"}:
                raise ValueError("Ответ пришёл не с t.me")
            raw = resp.read(2_000_000)
    except ValueError:
        raise
    except (URLError, TimeoutError, OSError):
        raise ValueError("Не открылся t.me. С этого компьютера Telegram может быть недоступен.") from None
    return raw.decode("utf-8", "replace")


def fetch_preview(name: str, before: int | None = None, pages: int = 4) -> dict:
    """Несколько страниц открытой ленты. Каждая страница — отдельный заход только на t.me/s."""
    name = channel_name(name)
    cursor = int(before) if before else None
    if cursor is not None and cursor < 1:
        raise ValueError("Некуда листать")
    items, seen = [], set()
    skipped = posts = 0
    oldest = cursor
    for _ in range(max(1, min(int(pages), 6))):
        url = f"https://t.me/s/{quote(name)}"
        if cursor:
            url += f"?before={cursor}"
        parsed = parse_preview(_get(url))
        posts += parsed["posts"]
        skipped += parsed["skipped"]
        for item in parsed["items"]:
            key = (item["kind"], item["id"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
        nxt = parsed["before"]
        if not parsed["posts"] or not nxt or nxt == cursor:
            break
        oldest = nxt
        cursor = nxt
    if posts == 0:
        raise ValueError("Канал не открыт без входа или такого имени нет")
    return {"channel": name, "items": items[:120], "skipped": skipped, "posts": posts, "before": oldest}


def license_commands(bot_names, items) -> list[str]:
    """Команды addlicense. Имена ботов и номера игр проверяются до отправки в ASF."""
    bots = []
    for name in bot_names or []:
        name = str(name)
        if name in bots:
            continue
        if not _BOT.fullmatch(name):
            raise ValueError("Имя бота не подходит для этой команды")
        bots.append(name)
    if not bots:
        raise ValueError("Отметь ботов ASF")
    if len(bots) > 30:
        raise ValueError("Не больше 30 ботов за раз")
    licenses = []
    for item in items or []:
        if not isinstance(item, dict):
            raise ValueError("В списке есть неверная игра")
        kind = str(item.get("kind") or "")
        raw = str(item.get("id") or "")
        if kind not in ("app", "sub") or not raw.isdigit():
            raise ValueError("В списке есть неверная игра")
        num = int(raw)
        if not 1 <= num <= 2_000_000_000:
            raise ValueError("В списке есть неверная игра")
        token = f"{kind}/{num}"
        if token not in licenses:
            licenses.append(token)
    if not licenses:
        raise ValueError("Отметь игры")
    if len(licenses) > 40:
        raise ValueError("Не больше 40 игр за раз")
    joined = ",".join(bots)
    return [f"addlicense {joined} {','.join(licenses[i:i + 15])}" for i in range(0, len(licenses), 15)]
