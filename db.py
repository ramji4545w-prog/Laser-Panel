"""
db.py — Database wrapper: PostgreSQL (Railway) or SQLite (local/fallback)
Both admin.py and bot.py import `db` from here.
"""
import os
import sqlite3

_DATABASE_URL = os.environ.get("DATABASE_URL", "")


class _Row(dict):
    """Dict row that also supports integer index access like sqlite3.Row."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def __contains__(self, key):
        return super().__contains__(key)


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        r = self._cur.fetchone()
        return _Row(r) if r else None

    def fetchall(self):
        return [_Row(r) for r in (self._cur.fetchall() or [])]

    def __iter__(self):
        for r in self._cur:
            yield _Row(r)


class _SqCursor:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        r = self._cur.fetchone()
        if r is None:
            return None
        return _Row(dict(r))

    def fetchall(self):
        return [_Row(dict(r)) for r in self._cur.fetchall()]

    def __iter__(self):
        for r in self._cur:
            yield _Row(dict(r))


class Database:
    """Unified database wrapper for SQLite and PostgreSQL."""

    def __init__(self):
        self._pg   = None
        self._sq   = None
        self.is_pg = False

        if _DATABASE_URL:
            try:
                import psycopg2
                import psycopg2.extras
                self._psycopg2 = psycopg2
                url = _DATABASE_URL
                if url.startswith("postgres://"):
                    url = "postgresql://" + url[11:]
                self._pg   = psycopg2.connect(url)
                self.is_pg = True
                print("✅ Database: PostgreSQL (persistent)")
            except Exception as e:
                print(f"⚠️  PostgreSQL failed ({e}) — falling back to SQLite")

        if not self.is_pg:
            BASE      = os.path.dirname(os.path.abspath(__file__))
            data_dir  = "/data" if os.path.isdir("/data") else BASE
            db_path   = os.path.join(data_dir, "database.db")
            self._sq  = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
            self._sq.row_factory = sqlite3.Row
            for pragma in [
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=NORMAL",
                "PRAGMA cache_size=-20000",
                "PRAGMA temp_store=MEMORY",
            ]:
                self._sq.execute(pragma)
            print(f"✅ Database: SQLite ({db_path})")

    # ── SQL adaptation ──────────────────────────────────────────────────────

    def _adapt(self, sql: str) -> str:
        """Convert SQLite SQL dialect to PostgreSQL where needed."""
        if not self.is_pg:
            return sql
        sql = sql.replace("?", "%s")
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        # ALTER TABLE: add IF NOT EXISTS so duplicate-column is a no-op
        if "ALTER TABLE" in sql and "ADD COLUMN" in sql and "IF NOT EXISTS" not in sql:
            sql = sql.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS")
        # INSERT OR IGNORE → INSERT … ON CONFLICT DO NOTHING
        if "INSERT OR IGNORE INTO" in sql:
            sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if "ON CONFLICT" not in sql:
                sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return sql

    # ── Public interface ────────────────────────────────────────────────────

    def execute(self, sql: str, params=()):
        adapted = self._adapt(sql)
        if self.is_pg:
            cur = self._pg.cursor(
                cursor_factory=self._psycopg2.extras.RealDictCursor
            )
            try:
                cur.execute(adapted, params or None)
            except self._psycopg2.Error as exc:
                self._pg.rollback()
                msg = str(exc).lower()
                # Swallow harmless errors (duplicate column / unique violation)
                if not any(k in msg for k in ("already exists", "unique", "duplicate")):
                    raise
                cur = self._pg.cursor(
                    cursor_factory=self._psycopg2.extras.RealDictCursor
                )
            return _PgCursor(cur)
        else:
            return _SqCursor(self._sq.execute(adapted, params))

    def commit(self):
        if self.is_pg:
            self._pg.commit()
        else:
            self._sq.commit()


# Module-level singleton — import this in admin.py and bot.py
db = Database()


# ── Schema bootstrap (runs once on import) ──────────────────────────────────

def _init_schema():
    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id         SERIAL PRIMARY KEY,
        telegram_id INTEGER,
        name       TEXT, phone TEXT, site TEXT, id_type TEXT,
        amount     TEXT, utr TEXT, screenshot_file_id TEXT,
        id_pass    TEXT, status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""" if db.is_pg else """CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        name TEXT, phone TEXT, site TEXT, id_type TEXT,
        amount TEXT, utr TEXT, screenshot_file_id TEXT,
        id_pass TEXT, status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS settings (
        id  INTEGER PRIMARY KEY,
        upi TEXT
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS subadmins (
        id         SERIAL PRIMARY KEY,
        name       TEXT NOT NULL UNIQUE,
        password   TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""" if db.is_pg else """CREATE TABLE IF NOT EXISTS subadmins (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL UNIQUE,
        password   TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS chat_logs (
        id          SERIAL PRIMARY KEY,
        telegram_id INTEGER,
        user_name   TEXT,
        sender      TEXT,
        message     TEXT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""" if db.is_pg else """CREATE TABLE IF NOT EXISTS chat_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        user_name   TEXT,
        sender      TEXT,
        message     TEXT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # Extra columns (safe to run every time)
    for col in ["id_pass TEXT", "id_type TEXT", "utr TEXT",
                "phone TEXT", "site TEXT", "screenshot_file_id TEXT"]:
        try:
            db.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except Exception:
            pass

    # Indexes (PostgreSQL IF NOT EXISTS supported)
    for idx, tbl, col in [
        ("idx_users_status",  "users",     "status"),
        ("idx_users_created", "users",     "created_at"),
        ("idx_users_tgid",    "users",     "telegram_id"),
        ("idx_chat_tgid",     "chat_logs", "telegram_id"),
    ]:
        try:
            db.execute(
                f"CREATE INDEX IF NOT EXISTS {idx} ON {tbl}({col})"
            )
        except Exception:
            pass

    # Seed UPI if not present
    default_upi = os.environ.get("UPI_ID", "")
    db.execute(
        "INSERT OR IGNORE INTO settings (id,upi) VALUES (1,?)",
        (default_upi,)
    )
    db.commit()


_init_schema()
