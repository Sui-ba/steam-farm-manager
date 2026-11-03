"""Проверка прокси: внешний IP и доступ к Steam. Пароли прокси наружу не отдаются."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests

IP_URL = "https://api.ipify.org?format=json"
STEAM_URL = "https://api.steampowered.com/ISteamWebAPIUtil/GetServerInfo/v1/"
TIMEOUT = 10
WORKERS = 20

_lock = threading.Lock()
_last = {"checked": "", "results": {}}


def _proxy_map(proxy: dict) -> dict:
    scheme = (proxy.get("protocol") or "http").strip().lower() or "http"
    if scheme == "socks5":
        scheme = "socks5h"  # DNS тоже через прокси
    user = str(proxy.get("username") or "")
    password = str(proxy.get("password") or "")
    auth = f"{quote(user, safe='')}:{quote(password, safe='')}@" if user else ""
    url = f"{scheme}://{auth}{proxy['host']}:{int(proxy['port'])}"
    return {"http": url, "https": url}


def _clean_error(exc: Exception, proxy: dict) -> str:
    text = f"{exc.__class__.__name__}: {exc}"
    for secret in (proxy.get("password"), quote(str(proxy.get("password") or ""), safe="")):
        if secret:
            text = text.replace(str(secret), "***")
    return text[:200]


def check_one(proxy: dict, timeout: float = TIMEOUT) -> dict:
    res = {"id": proxy.get("id"), "host": proxy.get("host"), "port": proxy.get("port"),
           "ok": False, "ip": "", "steam_ok": False, "ms": None, "error": ""}
    proxies = _proxy_map(proxy)
    try:
        start = time.perf_counter()
        r = requests.get(IP_URL, proxies=proxies, timeout=timeout)
        res["ms"] = int((time.perf_counter() - start) * 1000)
        r.raise_for_status()
        res["ip"] = str(r.json().get("ip") or "")[:64]
        res["ok"] = bool(res["ip"])
    except Exception as exc:
        res["error"] = _clean_error(exc, proxy)
        return res
    try:
        start = time.perf_counter()
        r = requests.get(STEAM_URL, proxies=proxies, timeout=timeout)
        res["steam_ms"] = int((time.perf_counter() - start) * 1000)
        res["steam_ok"] = r.status_code == 200
        if not res["steam_ok"]:
            res["error"] = f"Steam: HTTP {r.status_code}"
    except Exception as exc:
        res["error"] = "Steam: " + _clean_error(exc, proxy)
    return res


def check_many(proxies: list[dict], workers: int = WORKERS, timeout: float = TIMEOUT) -> list[dict]:
    if not proxies:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(proxies)))) as pool:
        results = list(pool.map(lambda p: check_one(p, timeout), proxies))
    with _lock:
        _last["checked"] = time.strftime("%d.%m %H:%M:%S")
        for r in results:
            _last["results"][r["id"]] = {**r, "checked": _last["checked"]}
    return results


def last_results() -> dict:
    with _lock:
        return {"checked": _last["checked"], "results": list(_last["results"].values())}


def summary(results: list[dict]) -> dict:
    ok = [r for r in results if r["ok"]]
    steam = [r for r in results if r["steam_ok"]]
    ms = sorted(r["ms"] for r in ok if r.get("ms") is not None)
    return {"total": len(results), "ok": len(ok), "steam_ok": len(steam), "fail": len(results) - len(ok),
            "median_ms": ms[len(ms) // 2] if ms else None}
