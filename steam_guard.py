"""Код Steam Guard из maFile (Nebula / SDA). Секреты никуда не пишутся."""

import base64
import hashlib
import hmac
import json
import struct
import time
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / "settings.json"
DEFAULT_MAFILES = Path(r"C:\path\to\maFiles")
ALPHABET = "23456789BCDFGHJKMNPQRTVWXY"

# Короткие подписи кнопки на экране подтверждения входа.
ENTER_CODE_TEXTS = (
    "enter a code instead",
    "enter code instead",
    "ввести код вместо этого",
    "ввести код",
    "введите код",
)


def _load_settings() -> dict:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def get_mafiles_dir() -> str:
    saved = str(_load_settings().get("mafiles_dir") or "").strip()
    if saved and Path(saved).is_dir():
        return saved
    if DEFAULT_MAFILES.is_dir():
        return str(DEFAULT_MAFILES)
    return saved


def set_mafiles_dir(path: str):
    settings = _load_settings()
    settings["mafiles_dir"] = path
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def generate_code(shared_secret: str, timestamp: int | None = None) -> str:
    secret = base64.b64decode(shared_secret)
    if timestamp is None:
        timestamp = int(time.time())
    msg = struct.pack(">Q", int(timestamp) // 30)
    digest = hmac.new(secret, msg, hashlib.sha1).digest()
    start = digest[19] & 0x0F
    full = struct.unpack(">I", digest[start:start + 4])[0] & 0x7FFFFFFF
    chars = []
    for _ in range(5):
        chars.append(ALPHABET[full % len(ALPHABET)])
        full //= len(ALPHABET)
    return "".join(chars)


def fresh_code(shared_secret: str) -> str:
    """Если до смены кода меньше 5 секунд — ждём следующее окно."""
    left = 30 - (int(time.time()) % 30)
    if left < 5:
        time.sleep(left + 0.4)
    return generate_code(shared_secret)


def find_shared_secret(login: str) -> str | None:
    folder = get_mafiles_dir()
    if not folder or not login:
        return None
    root = Path(folder)
    if not root.is_dir():
        return None
    target = login.strip().lower()
    for path in root.iterdir():
        if path.suffix.lower() != ".mafile" or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("account_name") or path.stem).strip().lower()
        if name != target and path.stem.lower() != target:
            continue
        secret = data.get("shared_secret")
        if isinstance(secret, str) and secret.strip():
            return secret.strip()
    return None


def _guard_boxes(driver):
    return driver.execute_script(
        """
        return [...document.querySelectorAll('input')].filter(el => {
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) return false;
            const max = el.maxLength;
            const auto = (el.getAttribute('autocomplete') || '').toLowerCase();
            return max === 1 || auto === 'one-time-code';
        });
        """
    ) or []


def _click_enter_code(driver) -> bool:
    clicked = driver.execute_script(
        """
        const phrases = arguments[0];
        const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
        let best = null;
        let bestLen = 999;
        for (const n of document.querySelectorAll('button, a, [role="button"], div, span')) {
            const t = norm(n.innerText || n.textContent);
            if (!t || t.length > 48) continue;
            if (!phrases.some(p => t === p)) continue;
            if (t.length < bestLen) {
                best = n;
                bestLen = t.length;
            }
        }
        if (!best) return false;
        best.click();
        return true;
        """,
        list(ENTER_CODE_TEXTS),
    )
    return bool(clicked)


def _type_code(boxes, code: str):
    from selenium.webdriver.common.keys import Keys

    first = boxes[0]
    first.click()
    first.send_keys(code)
    time.sleep(0.35)
    typed = "".join((box.get_attribute("value") or "") for box in boxes)
    if code.lower() in typed.lower():
        return
    per_box = [box for box in boxes if box.get_attribute("maxlength") == "1"]
    targets = per_box[:5] if len(per_box) >= 5 else boxes[:5]
    if len(targets) < 5:
        first.send_keys(Keys.CONTROL, "a")
        first.send_keys(code)
        return
    for box, char in zip(targets, code):
        box.click()
        box.send_keys(char)


def enter_guard_code(driver, login: str, status) -> None:
    """После кнопки входа: «Ввести код» и подстановка кода из maFile.

    status(text, color=None) можно звать из фонового потока — его реализует UI.
    """
    secret = find_shared_secret(login)
    if not secret:
        folder = get_mafiles_dir() or "не выбрана"
        status(
            f"maFile для «{login}» не найден ({folder}). Код введи вручную.",
            "warn",
        )
        return

    status("Жду экран Steam Guard…", None)
    deadline = time.time() + 45
    switched = False
    while time.time() < deadline:
        boxes = _guard_boxes(driver)
        single = [b for b in boxes if (b.get_attribute("autocomplete") or "").lower() == "one-time-code"]
        digits = [b for b in boxes if b.get_attribute("maxlength") == "1"]
        ready = digits if len(digits) >= 5 else single
        if ready:
            code = fresh_code(secret)
            _type_code(ready, code)
            status(f"Код Guard введён для {login}", "ok")
            return
        if not switched and _click_enter_code(driver):
            switched = True
            status("Нажимаю «Ввести код»…", None)
            time.sleep(0.7)
            continue
        time.sleep(0.4)

    status(
        "Экран кода не появился. Если Steam просит подтверждение в приложении — нажми «Ввести код» сам.",
        "warn",
    )
