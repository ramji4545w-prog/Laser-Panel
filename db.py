"""
db.py — Database wrapper: PostgreSQL (Railway) or SQLite with GitHub backup.
Both admin.py and bot.py import `db` from here.

Persistence strategy:
  1. If DATABASE_URL env var is set → use PostgreSQL (permanent)
  2. Otherwise → SQLite + auto-backup to private GitHub Gist every 3 min
     On startup: restores from Gist so data survives Railway redeploys.
"""
import os
import base64
import sqlite3
import threading
import time
import requests as _req

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_GIST_FILE    = "laser_panel_db.sqlite.b64"


# ══════════════════════════════════════════════════════════════════════════════
#  Row helpers
# ══════════════════════════════════════════════════════════════════════════════

class _Row(dict):
    """Dict row that also supports integer index: row[0] → first value."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


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
        return _Row(dict(r)) if r else None
    def fetchall(self):
        return [_Row(dict(r)) for r in self._cur.fetchall()]
    def __iter__(self):
        for r in self._cur:
            yield _Row(dict(r))


# ══════════════════════════════════════════════════════════════════════════════
#  GitHub Gist backup (SQLite mode only)
# ══════════════════════════════════════════════════════════════════════════════

class _GistBackup:
    """Backs up SQLite DB to a private GitHub Gist — survives Railway redeploys."""

    def __init__(self, token: str, db_path: str):
        self._token   = token
        self._db_path = db_path
        self._gist_id = None
        self._headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

    # ── Gist discovery ───────────────────────────────────────────────────────

    def _find_gist(self) -> str:
        if self._gist_id:
            return self._gist_id
        try:
            r = _req.get("https://api.github.com/gists?per_page=100",
                         headers=self._headers, timeout=10)
            for g in r.json():
                if _GIST_FILE in g.get("files", {}):
                    self._gist_id = g["id"]
                    return self._gist_id
        except Exception:
            pass
        return ""

    def _create_gist(self, content: str) -> str:
        try:
            r = _req.post("https://api.github.com/gists",
                headers=self._headers, timeout=15,
                json={
                    "description": "Laser Panel DB Backup (auto — do not delete)",
                    "public": False,
                    "files": {_GIST_FILE: {"content": content}},
                })
            if r.status_code == 201:
                self._gist_id = r.json()["id"]
                return self._gist_id
        except Exception:
            pass
        return ""

    # ── Restore on startup ───────────────────────────────────────────────────

    def restore(self):
        """Download DB from Gist and write to disk (only if Gist exists)."""
        if not self._token:
            return
        gist_id = self._find_gist()
        if not gist_id:
            return
        try:
            r = _req.get(f"https://api.github.com/gists/{gist_id}",
                         headers=self._headers, timeout=15)
            if r.status_code != 200:
                return
            raw = r.json()["files"].get(_GIST_FILE, {}).get("content", "")
            if not raw or len(raw) < 100:
                return
            db_bytes = base64.b64decode(raw)
            with open(self._db_path, "wb") as f:
                f.write(db_bytes)
            print("✅ DB restored from GitHub backup")
        except Exception as e:
            print(f"⚠️  DB restore failed: {e}")

    # ── Backup ───────────────────────────────────────────────────────────────

    def backup(self):
        """Upload current SQLite DB to Gist."""
        if not self._token:
            return
        try:
            with open(self._db_path, "rb") as f:
                content = base64.b64encode(f.read()).decode()
            gist_id = self._find_gist()
            if gist_id:
                _req.patch(f"https://api.github.com/gists/{gist_id}",
                    headers=self._headers, timeout=15,
                    json={"files": {_GIST_FILE: {"content": content}}})
            else:
                self._create_gist(content)
            print("✅ DB backed up to GitHub")
        except Exception as e:
            print(f"⚠️  DB backup failed: {e}")

    def start_auto_backup(self, interval: int = 180):
        """Background thread: backup every `interval` seconds (default 3 min)."""
        def _loop():
            time.sleep(30)          # wait 30s after startup before first backup
            while True:
                self.backup()
                time.sleep(interval)
        t = threading.Thread(target=_loop, daemon=True)
        t.start()


# ══════════════════════════════════════════════════════════════════════════════
#  Main Database class
# ══════════════════════════════════════════════════════════════════════════════

class Database:
    """Unified DB wrapper: PostgreSQL preferred, SQLite+GitHub-backup fallback."""

    def __init__(self):
        self._pg     = None
        self._sq     = None
        self._sq_path = ""
        self._gist   = None
        self.is_pg   = False

        # ── Try PostgreSQL ───────────────────────────────────────────────────
        if _DATABASE_URL:
            try:
                import psycopg2, psycopg2.extras
                self._psycopg2 = psycopg2
                url = _DATABASE_URL
                if url.startswith("postgres://"):
                    url = "postgresql://" + url[11:]
                self._pg   = psycopg2.connect(url)
                self.is_pg = True
                print("✅ Database: PostgreSQL (persistent)")
            except Exception as e:
                print(f"⚠️  PostgreSQL failed ({e}) — using SQLite+GitHub backup")

        # ── SQLite fallback with GitHub Gist backup ──────────────────────────
        if not self.is_pg:
            BASE           = os.path.dirname(os.path.abspath(__file__))
            data_dir       = "/data" if os.path.isdir("/data") else BASE
            self._sq_path  = os.path.join(data_dir, "database.db")

            # Restore from GitHub before connecting (so we get latest data)
            if _GITHUB_TOKEN:
                self._gist = _GistBackup(_GITHUB_TOKEN, self._sq_path)
                self._gist.restore()

            self._sq = sqlite3.connect(
                self._sq_path, check_same_thread=False, timeout=10)
            self._sq.row_factory = sqlite3.Row
            for p in ["PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL",
                      "PRAGMA cache_size=-20000", "PRAGMA temp_store=MEMORY"]:
                self._sq.execute(p)
            print(f"✅ Database: SQLite ({self._sq_path})")

            # Start background auto-backup every 3 minutes
            if self._gist:
                self._gist.start_auto_backup(interval=180)

    # ── SQL adaptation ───────────────────────────────────────────────────────

    def _adapt(self, sql: str) -> str:
        if not self.is_pg:
            return sql
        sql = sql.replace("?", "%s")
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        if "ALTER TABLE" in sql and "ADD COLUMN" in sql and "IF NOT EXISTS" not in sql:
            sql = sql.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS")
        if "INSERT OR IGNORE INTO" in sql:
            sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if "ON CONFLICT" not in sql:
                sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return sql

    # ── Public interface ─────────────────────────────────────────────────────

    def execute(self, sql: str, params=()):
        adapted = self._adapt(sql)
        if self.is_pg:
            cur = self._pg.cursor(
                cursor_factory=self._psycopg2.extras.RealDictCursor)
            try:
                cur.execute(adapted, params or None)
            except self._psycopg2.Error as exc:
                self._pg.rollback()
                msg = str(exc).lower()
                if not any(k in msg for k in
                           ("already exists", "unique", "duplicate")):
                    raise
                cur = self._pg.cursor(
                    cursor_factory=self._psycopg2.extras.RealDictCursor)
            return _PgCursor(cur)
        else:
            return _SqCursor(self._sq.execute(adapted, params))

    def commit(self):
        """Commit transaction. In SQLite mode, also triggers GitHub backup."""
        if self.is_pg:
            self._pg.commit()
        else:
            self._sq.commit()

    def backup_now(self):
        """Immediate GitHub backup (call after important data changes)."""
        if self._gist:
            threading.Thread(target=self._gist.backup, daemon=True).start()


# ── Singleton ────────────────────────────────────────────────────────────────
db = Database()


# ══════════════════════════════════════════════════════════════════════════════
#  Schema bootstrap
# ══════════════════════════════════════════════════════════════════════════════

def _init_schema():
    _pg = db.is_pg
    db.execute(f"""CREATE TABLE IF NOT EXISTS users (
        {'id SERIAL PRIMARY KEY' if _pg else 'id INTEGER PRIMARY KEY AUTOINCREMENT'},
        telegram_id INTEGER,
        name TEXT, phone TEXT, site TEXT, id_type TEXT,
        amount TEXT, utr TEXT, screenshot_file_id TEXT,
        id_pass TEXT, status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY, upi TEXT)""")
    db.execute(f"""CREATE TABLE IF NOT EXISTS subadmins (
        {'id SERIAL PRIMARY KEY' if _pg else 'id INTEGER PRIMARY KEY AUTOINCREMENT'},
        name TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    db.execute(f"""CREATE TABLE IF NOT EXISTS chat_logs (
        {'id SERIAL PRIMARY KEY' if _pg else 'id INTEGER PRIMARY KEY AUTOINCREMENT'},
        telegram_id INTEGER, user_name TEXT,
        sender TEXT, message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

    for col in ["id_pass TEXT", "id_type TEXT", "utr TEXT",
                "phone TEXT", "site TEXT", "screenshot_file_id TEXT"]:
        try:
            db.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except Exception:
            pass

    for idx, tbl, col in [
        ("idx_users_status",  "users",     "status"),
        ("idx_users_created", "users",     "created_at"),
        ("idx_users_tgid",    "users",     "telegram_id"),
        ("idx_chat_tgid",     "chat_logs", "telegram_id"),
    ]:
        try:
            db.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON {tbl}({col})")
        except Exception:
            pass

    db.execute("INSERT OR IGNORE INTO settings (id,upi) VALUES (1,?)",
               (os.environ.get("UPI_ID", ""),))
    db.commit()


_init_schema()
