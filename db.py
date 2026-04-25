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
        self._lock   = threading.Lock()   # SQLite thread-safety

        # ── Try PostgreSQL ───────────────────────────────────────────────────
        if _DATABASE_URL:
            try:
                import psycopg2, psycopg2.extras
                self._psycopg2 = psycopg2
                url = _DATABASE_URL
                if url.startswith("postgres://"):
                    url = "postgresql://" + url[11:]
                self._pg            = psycopg2.connect(url)
                self._pg.autocommit = True   # each stmt is its own tx — no failed-tx state ever
                self.is_pg          = True
                print("✅ Database: PostgreSQL (persistent, autocommit)")
            except Exception as e:
                print(f"⚠️  PostgreSQL failed ({e}) — using SQLite+GitHub backup")

        # ── SQLite fallback with GitHub Gist backup ──────────────────────────
        if not self.is_pg:
            BASE           = os.path.dirname(os.path.abspath(__file__))
            data_dir       = "/data" if os.path.isdir("/data") else BASE
            self._sq_path  = os.path.join(data_dir, "database.db")

            # ── Try restoring from GitHub Gist before opening SQLite ────────
            if _GITHUB_TOKEN:
                self._gist = _GistBackup(_GITHUB_TOKEN, self._sq_path)
                self._gist.restore()   # restore saved DB from Gist (survives redeploys)

            self._sq = sqlite3.connect(
                self._sq_path,
                check_same_thread=False,
                timeout=20,
                isolation_level=None)   # autocommit — no locking issues across threads
            self._sq.row_factory = sqlite3.Row
            for p in ["PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL",
                      "PRAGMA cache_size=-20000", "PRAGMA temp_store=MEMORY"]:
                self._sq.execute(p)
            print(f"✅ Database: SQLite ({self._sq_path}, autocommit)")

            # ── Start auto-backup every 3 min ────────────────────────────────
            if self._gist:
                self._gist.start_auto_backup(180)

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

    # ── PostgreSQL reconnect ─────────────────────────────────────────────────

    def _pg_connect(self):
        url = _DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[11:]
        self._pg            = self._psycopg2.connect(url)
        self._pg.autocommit = True
        print("✅ PostgreSQL (re)connected, autocommit=True")

    def _pg_cursor(self):
        """Return a fresh cursor, auto-reconnecting if connection is dead."""
        for attempt in range(3):
            try:
                if self._pg.closed:
                    self._pg_connect()
                return self._pg.cursor(
                    cursor_factory=self._psycopg2.extras.RealDictCursor)
            except Exception as e:
                print(f"PG cursor error (attempt {attempt+1}): {e}")
                try:
                    self._pg_connect()
                except Exception:
                    pass
        raise RuntimeError("PostgreSQL: could not reconnect after 3 attempts")

    # ── Public interface ─────────────────────────────────────────────────────

    def execute(self, sql: str, params=()):
        adapted = self._adapt(sql)
        if self.is_pg:
            for attempt in range(3):
                try:
                    cur = self._pg_cursor()
                    cur.execute(adapted, params or None)
                    return _PgCursor(cur)
                except self._psycopg2.Error as exc:
                    msg = str(exc).lower()
                    # already-exists errors are harmless (schema setup)
                    if any(k in msg for k in ("already exists","unique","duplicate")):
                        cur2 = self._pg_cursor()
                        return _PgCursor(cur2)
                    print(f"PG execute error (attempt {attempt+1}): {exc}")
                    if attempt == 2:
                        raise
                    time.sleep(0.5)
                    try: self._pg_connect()
                    except Exception: pass
        else:
            with self._lock:
                return _SqCursor(self._sq.execute(adapted, params))

    def commit(self):
        """Commit — no-op for PostgreSQL (autocommit=True). Commits SQLite."""
        if not self.is_pg:
            with self._lock:
                self._sq.commit()

    def backup_now(self):
        """Immediate GitHub backup (call after important data changes)."""
        if self._gist:
            threading.Thread(target=self._gist.backup, daemon=True).start()


# ── Singleton ────────────────────────────────────────────────────────────────
db = Database()


# ── In-memory caches (shared between bot + admin — no DB needed) ─────────────
import datetime as _dt

# ── Chat cache ────────────────────────────────────────────────────────────────
# {str(telegram_id): {"user_name": str, "messages": [{"sender","message","ts"}]}}
CHAT_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
MAX_MSG_PER_USER = 200


def cache_log(telegram_id: int, user_name: str, sender: str, message: str):
    """Save a message to in-memory chat cache — always works, no DB needed."""
    tid = str(telegram_id)
    ts  = _dt.datetime.now().strftime("%H:%M")
    with _CACHE_LOCK:
        if tid not in CHAT_CACHE:
            CHAT_CACHE[tid] = {"user_name": user_name, "messages": []}
        if user_name and user_name != "Unknown":
            CHAT_CACHE[tid]["user_name"] = user_name
        CHAT_CACHE[tid]["messages"].append(
            {"sender": sender, "message": message, "ts": ts}
        )
        if len(CHAT_CACHE[tid]["messages"]) > MAX_MSG_PER_USER:
            CHAT_CACHE[tid]["messages"] = CHAT_CACHE[tid]["messages"][-MAX_MSG_PER_USER:]


# ── Payment cache ─────────────────────────────────────────────────────────────
# {cache_id_str: {cache_id, telegram_id, name, phone, site, id_type,
#                 amount, utr, status, id_pass, ts}}
# cache_id = str(db_row_id) when DB worked, else "c_<tid>_<epoch_ms>"
PAYMENT_CACHE: dict = {}
_PAY_LOCK = threading.Lock()


def cache_payment(cache_id, telegram_id, name, phone, site, id_type,
                  amount, utr, status="pending", id_pass="", screenshot_id=""):
    """Add or overwrite a payment entry in the in-memory cache."""
    ts = _dt.datetime.now().strftime("%d/%m %H:%M")
    entry = {
        "cache_id":     str(cache_id),
        "telegram_id":  int(telegram_id),
        "name":         name or "Unknown",
        "phone":        phone or "",
        "site":         site or "",
        "id_type":      id_type or "new",
        "amount":       str(amount or ""),
        "utr":          utr or "",
        "status":       status,
        "id_pass":      id_pass or "",
        "screenshot_id": screenshot_id or "",
        "ts":           ts,
    }
    with _PAY_LOCK:
        PAYMENT_CACHE[str(cache_id)] = entry


def update_payment_cache(cache_id, **kwargs):
    """Update specific fields of a cached payment entry."""
    with _PAY_LOCK:
        cid = str(cache_id)
        if cid in PAYMENT_CACHE:
            PAYMENT_CACHE[cid].update(kwargs)


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


# ══════════════════════════════════════════════════════════════════════════════
#  Startup cache warm-up — DB se data RAM mein load karo (har restart ke baad)
#  KEY FIX: Refresh karne par bhi chats & payments gayb nahi honge
# ══════════════════════════════════════════════════════════════════════════════

def _warm_chat_cache():
    """DB ke saare chat_logs → CHAT_CACHE mein load karo on startup."""
    try:
        rows = db.execute(
            "SELECT telegram_id, user_name, sender, message, created_at "
            "FROM chat_logs ORDER BY id ASC"
        ).fetchall()
        with _CACHE_LOCK:
            for r in rows:
                tid   = str(r["telegram_id"])
                uname = r["user_name"] or "Unknown"
                # Parse timestamp to HH:MM
                try:
                    raw = str(r["created_at"] or "")
                    ts  = raw[11:16] if (len(raw) >= 16 and (" " in raw or "T" in raw)) else raw[-5:]
                except Exception:
                    ts = ""
                if tid not in CHAT_CACHE:
                    CHAT_CACHE[tid] = {"user_name": uname, "messages": []}
                if uname and uname != "Unknown":
                    CHAT_CACHE[tid]["user_name"] = uname
                CHAT_CACHE[tid]["messages"].append(
                    {"sender": r["sender"], "message": r["message"], "ts": ts}
                )
            # Trim to last MAX_MSG_PER_USER per user
            for tid in CHAT_CACHE:
                msgs = CHAT_CACHE[tid]["messages"]
                if len(msgs) > MAX_MSG_PER_USER:
                    CHAT_CACHE[tid]["messages"] = msgs[-MAX_MSG_PER_USER:]
        n_users = len(CHAT_CACHE)
        n_msgs  = sum(len(v["messages"]) for v in CHAT_CACHE.values())
        if n_msgs:
            print(f"✅ Chat cache warmed: {n_msgs} msgs | {n_users} users")
    except Exception as e:
        print(f"⚠️  Chat cache warm-up failed: {e}")


def _warm_payment_cache():
    """DB ke saare users (payments) → PAYMENT_CACHE mein load karo on startup."""
    try:
        rows = db.execute(
            "SELECT id, telegram_id, name, phone, site, id_type, "
            "amount, utr, status, id_pass, screenshot_file_id, created_at "
            "FROM users ORDER BY id ASC"
        ).fetchall()
        loaded = 0
        with _PAY_LOCK:
            for r in rows:
                cid = str(r["id"])
                if cid not in PAYMENT_CACHE:
                    try:
                        raw = str(r["created_at"] or "")
                        ts  = raw[:16].replace("T", " ") if len(raw) >= 16 else raw
                    except Exception:
                        ts = ""
                    PAYMENT_CACHE[cid] = {
                        "cache_id":      cid,
                        "telegram_id":   r["telegram_id"],
                        "name":          r["name"]   or "Unknown",
                        "phone":         r["phone"]  or "",
                        "site":          r["site"]   or "",
                        "id_type":       r["id_type"] or "new",
                        "amount":        str(r["amount"] or ""),
                        "utr":           r["utr"]    or "",
                        "status":        r["status"] or "pending",
                        "id_pass":       r["id_pass"] or "",
                        "screenshot_id": r["screenshot_file_id"] or "",
                        "ts":            ts,
                    }
                    loaded += 1
        if loaded:
            print(f"✅ Payment cache warmed: {loaded} payments")
    except Exception as e:
        print(f"⚠️  Payment cache warm-up failed: {e}")


# Startup pe dono caches warm karo — DB → RAM
_warm_chat_cache()
_warm_payment_cache()
