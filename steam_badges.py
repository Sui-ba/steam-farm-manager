"""Прогресс значков с публичной страницы Steam Community.

Программа только читает HTML. Крафт, вход в аккаунт и куки сюда не входят.
Первый успешный снимок аккаунта молчит: старые значки не уходят в Telegram.
"""

import json
import re
import threading
import time
import urllib.request
from html import unescape
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlparse

_LOCK = threading.Lock()
_ID64 = re.compile(r"7656119\d{10}")
_VANITY = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,31}")
_PROFILE = re.compile(
    r"steamcommunity\.com/(?:profiles/(7656119\d{10})|id/([A-Za-z][A-Za-z0-9_-]{1,31}))",
    re.I,
)
_TICK = re.compile(r'badge_progress_tick"[^>]*style="[^"]*width:\s*([0-9]+(?:\.[0-9]+)?)%', re.I)
_RATIO = re.compile(r"(\d+)\s*(?:of|/)\s*(\d+)", re.I)
_LEVEL = re.compile(r'friendPlayerLevelNum">\s*(\d+)')
_TITLE = (
    re.compile(r'class="badge_info_title"[^>]*>(.*?)</div>', re.S | re.I),
    re.compile(r'class="badge_title_row"[^>]*>(.*?)</div>', re.S | re.I),
    re.compile(r'class="badge_title"[^>]*>(.*?)</div>', re.S | re.I),
)
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
_MAX = 1_500_000


def assert_steam(url: str) -> str:
    """Только https-страница steamcommunity.com, без чужого хоста."""
    parts = urlparse(str(url or ""))
    if parts.scheme != "https" or (parts.hostname or "").lower() != "steamcommunity.com":
        raise ValueError("Чужой адрес")
    return url


class _Stay(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_steam(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def badges_url(steam_id: str) -> str:
    """Ссылка на значки по SteamID64, короткому имени или уже вставленной ссылке профиля."""
    raw = str(steam_id or "").strip()
    found = _PROFILE.search(raw)
    if found:
        raw = found.group(1) or found.group(2)
    if _ID64.fullmatch(raw):
        return f"https://steamcommunity.com/profiles/{raw}/badges/?l=english"
    if _VANITY.fullmatch(raw):
        return f"https://steamcommunity.com/id/{quote(raw)}/badges/?l=english"
    return ""


def _plain(fragment: str) -> str:
    text = unescape(fragment or "")
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"(?i)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?i)\b(view details|view badge progress)\b", "", text).strip(" -")
    return text[:80]


def _level(page: str):
    found = _LEVEL.search(page or "")
    if not found:
        return None
    num = int(found.group(1))
    return num if 0 <= num <= 9999 else None


def _one(part: str):
    title = ""
    for pattern in _TITLE:
        found = pattern.search(part)
        if found:
            title = _plain(found.group(1))
            if title:
                break
    if not title:
        return None
    foil = "border=1" in part
    progress = None
    live = False
    detail = ""
    chunk = ""
    marker = re.search(r'class="badge_progress_info\b', part, re.I)
    if marker:
        chunk = part[marker.start():marker.start() + 900]
    tick = _TICK.search(chunk or part)
    ratio = _RATIO.search(_plain(chunk)) if chunk else None
    if tick:
        progress = int(float(tick.group(1)))
        live = True
    elif ratio:
        owned, total = int(ratio.group(1)), int(ratio.group(2))
        if total <= 0 or total > 500:
            return None
        progress = min(100, round(owned * 100 / total))
        live = True
    elif "badge_info_unlocked" in part:
        progress = 100
        live = False
    else:
        return None
    progress = max(0, min(100, int(progress)))
    if ratio and int(ratio.group(2)) > 0:
        detail = f"{int(ratio.group(1))} / {int(ratio.group(2))}"
    else:
        detail = f"{progress}%"
    if progress >= 100:
        state = "done"
    elif progress >= 80:
        state = "close"
    else:
        state = "far"
    key = ("foil:" if foil else "") + re.sub(r"\s+", " ", title).strip().lower()
    return {
        "key": key[:120],
        "title": title,
        "progress": progress,
        "detail": detail[:40],
        "state": state,
        "live": live,
    }


def parse_page(page: str) -> dict:
    """Один HTML страницы значков. Куки и посторонние ссылки не сохраняются."""
    text = str(page or "")
    low = text.lower()
    if re.search(r'class="profile_private_info"', text, re.I):
        return {"status": "private", "note": "профиль закрыт", "level": _level(text), "badges": []}
    if "badge_row" not in low and "profile_header" not in low and "profile_page" not in low:
        return {"status": "error", "note": "Steam не открыл страницу", "level": None, "badges": []}
    found, seen = [], set()
    for part in re.split(r'(?=<div class="badge_row[\s"])', text)[1:]:
        item = _one(part)
        if not item or item["key"] in seen:
            continue
        seen.add(item["key"])
        found.append(item)
    found.sort(key=lambda b: (b["state"] != "close", b["state"] != "done", -b["progress"], b["title"]))
    note = "показана первая страница" if re.search(r"[?&]p=2\b", text) else ""
    return {"status": "ok", "note": note, "level": _level(text), "badges": found[:40]}


def fetch_html(url: str, timeout: int = 12) -> str:
    assert_steam(url)
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "en"})
    opener = urllib.request.build_opener(_Stay)
    with opener.open(req, timeout=timeout) as resp:
        assert_steam(resp.geturl())
        raw = resp.read(_MAX + 1)
    if len(raw) > _MAX:
        raw = raw[:_MAX]
    return raw.decode("utf-8", "replace")


def _empty():
    return {"checked": "", "accounts": {}}


def read_cache(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    accounts = data.get("accounts") if isinstance(data.get("accounts"), dict) else {}
    return {"checked": str(data.get("checked") or "")[:20], "accounts": accounts}


def write_cache(path, data) -> None:
    clean_accounts = {}
    for key, row in (data.get("accounts") or {}).items():
        if isinstance(row, dict):
            clean_accounts[str(key)[:80]] = row
    payload = {"checked": str(data.get("checked") or "")[:20], "accounts": clean_accounts}
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def _summary(status: str, note: str, badges: list) -> str:
    if status == "missing":
        return "нет SteamID"
    if status == "private":
        return "профиль закрыт"
    if status == "error":
        return (note or "нет данных")[:80]
    close = sum(1 for b in badges if b.get("state") == "close")
    done = sum(1 for b in badges if b.get("state") == "done" and b.get("live"))
    parts = []
    if close:
        parts.append(f"{close} близко")
    if done:
        parts.append(f"{done} на 100%")
    if parts:
        return ", ".join(parts)
    if any(b.get("live") for b in badges):
        return "далеко от готовности"
    if badges:
        return "только уже открытые"
    return "нет значков с прогрессом"


def _notices(login: str, before: dict, badges: list, baseline: bool):
    """Переходы в «близко» и «готово». Первый снимок и старые открытые значки молчат."""
    seen = dict(before or {})
    lines = []
    safe = str(login or "").replace("\n", " ").strip()[:40] or "аккаунт"
    for badge in badges:
        prev = seen.get(badge["key"])
        seen[badge["key"]] = badge["state"]
        if not baseline:
            continue
        if badge["state"] == "done" and prev != "done" and (badge["live"] or prev in ("far", "close")):
            lines.append(f"Значок готов: {safe} — {badge['title']} ({badge['detail']})")
        elif badge["state"] == "close" and prev != "close" and badge["live"]:
            lines.append(f"Значок близко: {safe} — {badge['title']} ({badge['detail']})")
    return seen, lines


def _show(badges: list) -> list:
    live = [b for b in badges if b.get("live")]
    picked = live[:8] or []
    return [{k: b[k] for k in ("title", "progress", "detail", "state")} for b in picked]


def public_view(data: dict, running: bool = False) -> dict:
    rows = []
    for key, row in (data.get("accounts") or {}).items():
        if not isinstance(row, dict):
            continue
        status = row.get("status") if row.get("status") in ("ok", "private", "missing", "error") else "error"
        level = row.get("level") if isinstance(row.get("level"), int) else None
        badges = []
        for badge in (row.get("badges") or [])[:8]:
            if not isinstance(badge, dict):
                continue
            state = badge.get("state") if badge.get("state") in ("far", "close", "done") else "far"
            try:
                progress = int(badge.get("progress") or 0)
            except (TypeError, ValueError):
                progress = 0
            badges.append({
                "title": str(badge.get("title") or "")[:80],
                "progress": max(0, min(100, progress)),
                "detail": str(badge.get("detail") or "")[:40],
                "state": state,
            })
        rows.append({
            "login": str(row.get("login") or key)[:40],
            "status": status,
            "note": str(row.get("note") or "")[:80],
            "summary": str(row.get("summary") or "")[:80],
            "level": level,
            "close": int(row.get("close") or 0),
            "done": int(row.get("done") or 0),
            "badges": badges,
        })
    rows.sort(key=lambda item: (-item["close"], -item["done"], item["login"].lower()))
    return {"checked": str(data.get("checked") or "")[:20], "running": bool(running), "accounts": rows}


def summary_for(path, login: str) -> str:
    row = read_cache(path)["accounts"].get(str(login or "").strip().lower())
    if not isinstance(row, dict):
        return "ещё не проверяли"
    return str(row.get("summary") or "ещё не проверяли")[:80]


def refresh(path, accounts, notify=None, pause: float = 1.5, fetch=None) -> dict:
    """Обходит аккаунты. notify получает уже готовые строки, не больше восьми за проход."""
    fetch = fetch or fetch_html
    data = read_cache(path)
    notices = []
    stamp = time.strftime("%d.%m %H:%M")
    for acc in accounts:
            login = str((acc or {}).get("login") or "").strip()[:40]
            if not login:
                continue
            key = login.lower()
            prev = data["accounts"].get(key) if isinstance(data["accounts"].get(key), dict) else {}
            steam_id = str((acc or {}).get("steam_id") or "")
            url = badges_url(steam_id)
            if not url:
                row = _keep(prev, login, steam_id, "missing", "нет SteamID")
            else:
                try:
                    parsed = parse_page(fetch(url))
                except (OSError, URLError, ValueError, TimeoutError):
                    row = _keep(prev, login, steam_id, "error", "нет связи со Steam")
                else:
                    if parsed["status"] != "ok":
                        row = _keep(prev, login, steam_id, parsed["status"], parsed.get("note") or "")
                        if parsed.get("level") is not None:
                            row["level"] = parsed["level"]
                    else:
                        seen, lines = _notices(login, prev.get("seen") or {}, parsed["badges"], bool(prev.get("baseline")))
                        notices.extend(lines)
                        badges = parsed["badges"]
                        row = {
                            "login": login,
                            "steam_id": steam_id[:80],
                            "status": "ok",
                            "note": parsed.get("note") or "",
                            "level": parsed.get("level"),
                            "badges": _show(badges),
                            "close": sum(1 for b in badges if b["state"] == "close"),
                            "done": sum(1 for b in badges if b["state"] == "done" and b["live"]),
                            "summary": _summary("ok", parsed.get("note") or "", badges),
                            "seen": seen,
                            "baseline": True,
                        }
            data["accounts"][key] = row
            data["checked"] = stamp
            with _LOCK:
                write_cache(path, data)
            if pause:
                time.sleep(pause)
    if notices and notify:
        if len(notices) > 8:
            lines = notices[:7] + [f"и ещё {len(notices) - 7}"]
        else:
            lines = notices
        try:
            notify(lines[:8])
        except (OSError, RuntimeError, ValueError):
            pass
    return public_view(data)


def _keep(prev, login, steam_id, status, note):
    """Ошибка и закрытый профиль не сбрасывают уже снятую базу. Пустой SteamID — сбрасывают."""
    hold = status in ("error", "private")
    return {
        "login": login,
        "steam_id": str(steam_id or "")[:80],
        "status": status,
        "note": str(note or "")[:80],
        "summary": _summary(status, note, []),
        "level": prev.get("level") if isinstance(prev.get("level"), int) else None,
        "close": int(prev.get("close") or 0) if hold else 0,
        "done": int(prev.get("done") or 0) if hold else 0,
        "badges": prev.get("badges") if hold and isinstance(prev.get("badges"), list) else [],
        "seen": prev.get("seen") if isinstance(prev.get("seen"), dict) else {},
        "baseline": bool(prev.get("baseline")) if hold else False,
    }
