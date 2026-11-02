"""Импорт и экспорт аккаунтов и прокси. Секреты остаются в локальном файле."""

import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from database import (
    add_account,
    add_proxy,
    find_account_by_login,
    find_proxy,
    update_account_fields,
    update_proxy,
)

_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

ACCOUNT_TEMPLATES = [
    ("Логин:пароль", "{login}:{password}"),
    ("Логин:пароль:почта:пароль почты", "{login}:{password}:{email}:{email_password}"),
    ("Логин:пароль:почта:пароль почты:rcode", "{login}:{password}:{email}:{email_password}:{rcode}"),
    ("Почта:пароль почты:логин:пароль", "{email}:{email_password}:{login}:{password}"),
    ("Свой формат", ""),
]

PROXY_TEMPLATES = [
    ("host:port", "{host}:{port}"),
    ("host:port:логин:пароль", "{host}:{port}:{username}:{password}"),
    ("логин:пароль@host:port", "{username}:{password}@{host}:{port}"),
    ("protocol://host:port", "{protocol}://{host}:{port}"),
    ("protocol://логин:пароль@host:port", "{protocol}://{username}:{password}@{host}:{port}"),
    ("Свой формат", ""),
]

ACCOUNT_KEYS = {
    "login", "password", "email", "email_password", "rcode", "steam_id",
    "friend_code", "first_ko", "spent", "notes",
    "configured", "restriction_lifted", "prime_bought",
    "rank", "xp", "drops", "income", "sent_main", "reinvest",
}
_INTS = {"xp", "drops", "sent_main"}
_FLOATS = {"spent", "income", "reinvest"}
PROXY_KEYS = {"protocol", "host", "port", "username", "password", "notes"}
_FLAGS = {"configured", "restriction_lifted", "prime_bought"}


def parse_line(fmt: str, line: str) -> dict | None:
    """Разбирает строку по шаблону вида {login}:{password}."""
    fmt = (fmt or "").strip()
    line = (line or "").strip()
    if not fmt or not line or not _TOKEN.search(fmt):
        return None
    parts = _TOKEN.split(fmt)
    pos = 0
    out = {}
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if not part:
                continue
            if not line.startswith(part, pos):
                return None
            pos += len(part)
            continue
        nxt = parts[i + 1] if i + 1 < len(parts) else ""
        if nxt:
            idx = line.find(nxt, pos)
            if idx < 0:
                return None
            out[part] = line[pos:idx]
            pos = idx
        else:
            out[part] = line[pos:]
            pos = len(line)
    if pos != len(line):
        return None
    return out


def format_line(fmt: str, data: dict) -> str:
    def repl(match):
        value = data.get(match.group(1), "")
        return "" if value is None else str(value)
    return _TOKEN.sub(repl, fmt)


def _flag(value: str) -> int:
    return 1 if str(value).strip().lower() in {"1", "true", "yes", "да", "y", "+"} else 0


def _normalize_account(parsed: dict) -> dict:
    out = {}
    for key, value in parsed.items():
        if key not in ACCOUNT_KEYS:
            continue
        value = value.strip()
        if key in _FLOATS:
            out[key] = float(value or 0)
        elif key in _INTS:
            out[key] = int(float(value or 0))
        elif key in _FLAGS:
            out[key] = _flag(value)
        else:
            out[key] = value
    return out


def _normalize_proxy(parsed: dict) -> dict:
    out = {}
    for key, value in parsed.items():
        if key not in PROXY_KEYS:
            continue
        value = value.strip()
        if key == "port":
            port = int(value)
            if not 1 <= port <= 65535:
                raise ValueError("порт")
            out[key] = port
        elif key == "protocol":
            out[key] = value.lower() or "http"
        else:
            out[key] = value
    return out


def import_accounts(text: str, fmt: str) -> dict:
    added = updated = skipped = 0
    errors = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = parse_line(fmt, line)
        if not parsed:
            skipped += 1
            errors.append(f"строка {number}: не совпала с форматом")
            continue
        try:
            data = _normalize_account(parsed)
        except ValueError:
            skipped += 1
            errors.append(f"строка {number}: число в ранге, опыте, дропе или доходе не разобралось")
            continue
        login = (data.get("login") or "").strip()
        if not login:
            skipped += 1
            errors.append(f"строка {number}: нет логина")
            continue
        data["login"] = login
        existing = find_account_by_login(login)
        if existing:
            update_account_fields(existing["id"], data)
            updated += 1
        else:
            add_account(data)
            added += 1
    return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}


def import_proxies(text: str, fmt: str) -> dict:
    added = updated = skipped = 0
    errors = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = parse_line(fmt, line)
        if not parsed:
            skipped += 1
            errors.append(f"строка {number}: не совпала с форматом")
            continue
        try:
            data = _normalize_proxy(parsed)
        except ValueError:
            skipped += 1
            errors.append(f"строка {number}: порт должен быть от 1 до 65535")
            continue
        host = (data.get("host") or "").strip()
        if not host or "port" not in data:
            skipped += 1
            errors.append(f"строка {number}: нужны хост и порт")
            continue
        data["host"] = host
        existing = find_proxy(host, data["port"], data.get("username", ""))
        if existing:
            update_proxy(existing["id"], {**existing, **data})
            updated += 1
        else:
            add_proxy(data)
            added += 1
    return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}


def result_text(title: str, result: dict) -> str:
    lines = [
        title,
        f"Добавлено: {result['added']}",
        f"Обновлено: {result['updated']}",
        f"Пропущено: {result['skipped']}",
    ]
    if result["errors"]:
        lines.append("")
        lines.extend(result["errors"][:8])
        extra = len(result["errors"]) - 8
        if extra > 0:
            lines.append(f"…ещё {extra}")
    return "\n".join(lines)


def account_row(account: dict, proxy: dict | None) -> dict:
    row = {key: account.get(key) if account.get(key) is not None else "" for key in ACCOUNT_KEYS}
    for key in _FLAGS:
        row[key] = 1 if account.get(key) else 0
    row["id"] = account.get("id", "")
    if proxy:
        user = proxy.get("username") or ""
        auth = f"{user}:{proxy.get('password') or ''}@" if user else ""
        row["proxy"] = f"{proxy.get('protocol') or 'http'}://{auth}{proxy.get('host')}:{proxy.get('port')}"
    else:
        row["proxy"] = ""
    return row


def proxy_row(proxy: dict) -> dict:
    return {key: proxy.get(key) if proxy.get(key) is not None else "" for key in ("id", *PROXY_KEYS)}


ACCOUNT_XLSX = [
    "id", "login", "password", "steam_id", "email", "email_password", "rcode",
    "friend_code", "first_ko", "spent", "notes", "rank", "xp", "drops", "income",
    "sent_main", "reinvest", "configured", "restriction_lifted", "prime_bought", "proxy",
]
PROXY_XLSX = ["id", "protocol", "host", "port", "username", "password", "notes"]


def table_rows(records: list[dict], columns: list[str]) -> tuple[list[str], list[list]]:
    rows = [[record.get(col, "") for col in columns] for record in records]
    return columns, rows


def write_xlsx(path: str, sheet_name: str, headers: list[str], rows: list[list]):
    safe_name = "".join(ch for ch in sheet_name if ch not in '[]:*?/\\')[:31] or "Sheet1"

    def xml_text(value) -> str:
        text = "" if value is None else str(value)
        text = "".join(ch for ch in text if ch in "\t\n\r" or ord(ch) >= 32)
        return escape(text)

    def col_name(index: int) -> str:
        name = ""
        while index:
            index, rem = divmod(index - 1, 26)
            name = chr(65 + rem) + name
        return name

    def cell(ref: str, value) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t>{xml_text(value)}</t></is></c>'

    body = []
    for r_index, row in enumerate([headers, *rows], 1):
        cells = "".join(cell(f"{col_name(c)}{r_index}", value) for c, value in enumerate(row, 1))
        body.append(f'<row r="{r_index}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(body)}</sheetData></worksheet>'
    )
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="{escape(safe_name)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""

    target = Path(path)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as book:
        book.writestr("[Content_Types].xml", content_types)
        book.writestr("_rels/.rels", root_rels)
        book.writestr("xl/workbook.xml", workbook)
        book.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        book.writestr("xl/worksheets/sheet1.xml", sheet)
