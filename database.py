import sqlite3
from datetime import datetime

import runtime
import vault

DB_PATH = runtime.data_dir() / "accounts.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            steam_id TEXT,
            login TEXT NOT NULL,
            password TEXT,
            rcode TEXT,
            configured INTEGER DEFAULT 0,
            restriction_lifted INTEGER DEFAULT 0,
            prime_bought INTEGER DEFAULT 0,
            friend_code TEXT,
            first_ko TEXT,
            email TEXT,
            email_password TEXT,
            spent REAL DEFAULT 0,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            protocol TEXT DEFAULT 'http',
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            username TEXT,
            password TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    _add_column(cur, "accounts", "proxy_id", "INTEGER")
    for col, typ in (
        ("balance", "TEXT"), ("level", "INTEGER"), ("is_main", "INTEGER DEFAULT 0"), ("warm", "TEXT"),
        ("rank", "TEXT"), ("xp", "INTEGER"), ("drops", "INTEGER DEFAULT 0"),
        ("income", "REAL DEFAULT 0"), ("sent_main", "INTEGER DEFAULT 0"), ("reinvest", "REAL DEFAULT 0"),
    ):
        _add_column(cur, "accounts", col, typ)
    conn.commit()
    _migrate_secrets(conn)
    conn.close()


def _migrate_secrets(conn):
    """Шифрует ещё открытые пароли, почты и прокси. Повторный запуск ничего не меняет."""
    cur = conn.cursor()
    for table, cols in (("accounts", vault.ACCOUNT_FIELDS), ("proxies", vault.PROXY_FIELDS)):
        cur.execute(f"SELECT id, {', '.join(cols)} FROM {table}")
        for row in cur.fetchall():
            sets, values = [], []
            for col in cols:
                val = row[col]
                if val and not vault.is_sealed(val):
                    sets.append(f"{col} = ?")
                    values.append(vault.encrypt(val))
            if sets:
                values.append(row["id"])
                cur.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id = ?", values)
    conn.commit()


def _add_column(cur, table: str, column: str, typedef: str):
    cur.execute(f"PRAGMA table_info({table})")
    names = {row[1] for row in cur.fetchall()}
    if column not in names:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")


def add_account(data: dict) -> int:
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    data = vault.seal_map(data, vault.ACCOUNT_FIELDS)
    cur.execute("""
        INSERT INTO accounts (
            steam_id, login, password, rcode, configured,
            restriction_lifted, prime_bought, friend_code, first_ko,
            email, email_password, spent, notes, proxy_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("steam_id", ""),
        data["login"],
        data.get("password", ""),
        data.get("rcode", ""),
        1 if data.get("configured") else 0,
        1 if data.get("restriction_lifted") else 0,
        1 if data.get("prime_bought") else 0,
        data.get("friend_code", ""),
        data.get("first_ko", ""),
        data.get("email", ""),
        data.get("email_password", ""),
        float(data.get("spent") or 0),
        data.get("notes", ""),
        data.get("proxy_id") or None,
        now, now
    ))
    account_id = cur.lastrowid
    conn.commit()
    conn.close()
    return account_id


def update_account(account_id: int, data: dict):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    data = vault.seal_map(data, vault.ACCOUNT_FIELDS)
    cur.execute("""
        UPDATE accounts SET
            steam_id = ?, login = ?, password = ?, rcode = ?,
            configured = ?, restriction_lifted = ?, prime_bought = ?,
            friend_code = ?, first_ko = ?, email = ?, email_password = ?,
            spent = ?, notes = ?, proxy_id = ?, updated_at = ?
        WHERE id = ?
    """, (
        data.get("steam_id", ""),
        data["login"],
        data.get("password", ""),
        data.get("rcode", ""),
        1 if data.get("configured") else 0,
        1 if data.get("restriction_lifted") else 0,
        1 if data.get("prime_bought") else 0,
        data.get("friend_code", ""),
        data.get("first_ko", ""),
        data.get("email", ""),
        data.get("email_password", ""),
        float(data.get("spent") or 0),
        data.get("notes", ""),
        data.get("proxy_id") or None,
        now,
        account_id
    ))
    conn.commit()
    conn.close()


def update_account_fields(account_id: int, fields: dict):
    allowed = {
        "steam_id", "login", "password", "rcode", "configured",
        "restriction_lifted", "prime_bought", "friend_code", "first_ko",
        "email", "email_password", "spent", "notes", "proxy_id",
        "balance", "level", "is_main", "warm",
        "rank", "xp", "drops", "income", "sent_main", "reinvest",
    }
    sets = []
    values = []
    fields = vault.seal_map(fields, vault.ACCOUNT_FIELDS)
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = ?")
        values.append(value)
    if not sets:
        return
    sets.append("updated_at = ?")
    values.append(datetime.now().isoformat(timespec="seconds"))
    values.append(account_id)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def find_account_by_login(login: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM accounts WHERE lower(login) = lower(?)", (login.strip(),))
    row = cur.fetchone()
    conn.close()
    return vault.open_row(dict(row), vault.ACCOUNT_FIELDS) if row else None


def delete_account(account_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()
    conn.close()


def get_all_accounts():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM accounts ORDER BY id DESC")
    rows = [vault.open_row(dict(row), vault.ACCOUNT_FIELDS) for row in cur.fetchall()]
    conn.close()
    return rows


def get_account(account_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
    row = cur.fetchone()
    conn.close()
    return vault.open_row(dict(row), vault.ACCOUNT_FIELDS) if row else None


def get_stats():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COUNT(*) as total,
            COALESCE(SUM(spent), 0) as total_spent,
            COALESCE(SUM(CASE WHEN configured = 1 THEN 1 ELSE 0 END), 0) as configured_count,
            COALESCE(SUM(CASE WHEN prime_bought = 1 THEN 1 ELSE 0 END), 0) as prime_count,
            COALESCE(SUM(CASE WHEN restriction_lifted = 1 THEN 1 ELSE 0 END), 0) as restriction_lifted_count
        FROM accounts
    """)
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {
        "total": 0, "total_spent": 0,
        "configured_count": 0, "prime_count": 0, "restriction_lifted_count": 0
    }


def add_proxy(data: dict) -> int:
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    data = vault.seal_map(data, vault.PROXY_FIELDS)
    cur.execute("""
        INSERT INTO proxies (
            protocol, host, port, username, password, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("protocol") or "http",
        data["host"],
        int(data["port"]),
        data.get("username", ""),
        data.get("password", ""),
        data.get("notes", ""),
        now, now
    ))
    proxy_id = cur.lastrowid
    conn.commit()
    conn.close()
    return proxy_id


def update_proxy(proxy_id: int, data: dict):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    data = vault.seal_map(data, vault.PROXY_FIELDS)
    cur.execute("""
        UPDATE proxies SET
            protocol = ?, host = ?, port = ?, username = ?,
            password = ?, notes = ?, updated_at = ?
        WHERE id = ?
    """, (
        data.get("protocol") or "http",
        data["host"],
        int(data["port"]),
        data.get("username", ""),
        data.get("password", ""),
        data.get("notes", ""),
        now,
        proxy_id
    ))
    conn.commit()
    conn.close()


def delete_proxy(proxy_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET proxy_id = NULL WHERE proxy_id = ?", (proxy_id,))
    cur.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
    conn.commit()
    conn.close()


def find_proxy(host: str, port: int, username: str = ""):
    """Хост и логин в базе зашифрованы, поэтому сравнение идёт после расшифровки."""
    want = username or ""
    for row in get_all_proxies():
        if row.get("host") == host and int(row["port"]) == int(port) and (row.get("username") or "") == want:
            return row
    return None


def assign_proxies_one_to_one() -> tuple[int, int]:
    """Первый добавленный аккаунт получает первый прокси, и так далее."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM accounts ORDER BY id ASC")
    account_ids = [row[0] for row in cur.fetchall()]
    cur.execute("SELECT id FROM proxies ORDER BY id ASC")
    proxy_ids = [row[0] for row in cur.fetchall()]
    now = datetime.now().isoformat(timespec="seconds")
    for index, account_id in enumerate(account_ids):
        proxy_id = proxy_ids[index] if index < len(proxy_ids) else None
        cur.execute(
            "UPDATE accounts SET proxy_id = ?, updated_at = ? WHERE id = ?",
            (proxy_id, now, account_id),
        )
    conn.commit()
    conn.close()
    assigned = min(len(account_ids), len(proxy_ids))
    return assigned, len(account_ids) - assigned


def get_all_proxies():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM proxies ORDER BY id DESC")
    rows = [vault.open_row(dict(row), vault.PROXY_FIELDS) for row in cur.fetchall()]
    conn.close()
    return rows


def get_proxy(proxy_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,))
    row = cur.fetchone()
    conn.close()
    return vault.open_row(dict(row), vault.PROXY_FIELDS) if row else None


def set_main_account(account_id: int):
    conn = get_connection()
    conn.execute("UPDATE accounts SET is_main = CASE WHEN id = ? THEN 1 ELSE 0 END", (account_id,))
    conn.commit()
    conn.close()
