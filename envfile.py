"""Чтение и запись .env. Секреты остаются в этом файле и не коммитятся."""

import os

import runtime

PATH = runtime.data_dir() / ".env"
_loaded = False


def load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not PATH.is_file():
        example = runtime.bundle_dir() / ".env.example"
        if example.is_file():
            PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    if not PATH.is_file():
        return
    for raw in PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = _unquote(value.strip())
        if key:
            os.environ.setdefault(key, value)


def get(key, default=""):
    load()
    return os.environ.get(key, default).strip()


def set(key, value):
    """Обновляет переменную в процессе и строку в .env."""
    load()
    value = "" if value is None else str(value)
    os.environ[key] = value
    lines = PATH.read_text(encoding="utf-8").splitlines() if PATH.is_file() else []
    found = False
    out = []
    for line in lines:
        stripped = line.strip()
        name = stripped[7:].strip() if stripped.startswith("export ") else stripped
        if name.startswith(f"{key}=") or name.startswith(f"{key} ="):
            out.append(f"{key}={_quote(value)}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={_quote(value)}")
    PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def _unquote(value):
    if len(value) < 2 or value[0] != value[-1] or value[0] not in "\"'":
        return value
    inner = value[1:-1]
    if value[0] == "'":
        return inner
    out = []
    i = 0
    while i < len(inner):
        if inner[i] == "\\" and i + 1 < len(inner):
            out.append(inner[i + 1])
            i += 2
        else:
            out.append(inner[i])
            i += 1
    return "".join(out)


def _quote(value):
    if value == "" or any(ch in value for ch in " #\t"):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value
