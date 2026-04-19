import os
import sqlite3
import threading
import datetime
import qrcode
import requests as http_requests

from flask import (
    Flask, render_template_string, redirect, request, session, flash, url_for
)
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

# ═══════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════

TOKEN          = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID  = int(os.environ["ADMIN_CHAT_ID"])
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
SESSION_SECRET = os.environ.get("SESSION_SECRET", "laserweb2024")
DEFAULT_UPI    = os.environ.get("UPI_ID", "")

SITE_NAME = "Laser Web Panel"
SITES     = ["Laser247", "Tiger399", "AllPanel", "Diamond"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "database.db")

# ═══════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════

db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
db_conn.row_factory = sqlite3.Row


def init_db():
    db_conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            name        TEXT,
            phone       TEXT,
            site        TEXT,
            id_type     TEXT,
            amount      TEXT,
            utr         TEXT,
            id_pass     TEXT,
            status      TEXT DEFAULT 'pending',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db_conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id  INTEGER PRIMARY KEY,
            upi TEXT
        )
    """)
    db_conn.execute("""
        CREATE TABLE IF NOT EXISTS subadmins (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            password   TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db_conn.execute(
        "INSERT OR IGNORE INTO settings (id, upi) VALUES (1, ?)", (DEFAULT_UPI,)
    )
    for col in ["id_pass TEXT", "id_type TEXT", "utr TEXT", "phone TEXT", "site TEXT"]:
        try:
            db_conn.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except Exception:
            pass
    db_conn.commit()


init_db()


def get_upi():
    row = db_conn.execute("SELECT upi FROM settings WHERE id=1").fetchone()
    return row["upi"] if row else DEFAULT_UPI


def send_tg(chat_id, text):
    try:
        http_requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  FLASK ADMIN PANEL
# ═══════════════════════════════════════════════════════════

flask_app = Flask(__name__)
flask_app.secret_key = SESSION_SECRET


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated


def admin_only(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/admin/login")
        if session.get("role") != "admin":
            flash("Access denied.", "error")
            return redirect("/admin/payments")
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════
#  SHARED CSS / JS
# ══════════════════════════════════════════════════════════

SHARED_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:#080808;color:#fff;min-height:100vh}

/* ── Sidebar ── */
.sidebar{width:240px;background:linear-gradient(180deg,#0f0f0f 0%,#0a0a0a 100%);
  height:100vh;border-right:1px solid #1c1c1c;position:fixed;top:0;left:0;
  display:flex;flex-direction:column;z-index:100}
.sidebar-logo{padding:24px 20px 20px;border-bottom:1px solid #1c1c1c}
.sidebar-logo .brand{color:#ff2d2d;font-size:1.05rem;font-weight:800;
  letter-spacing:.5px;text-transform:uppercase}
.sidebar-logo .sub{color:#333;font-size:.7rem;margin-top:2px;letter-spacing:2px}
.nav-section{padding:16px 12px 4px;font-size:.6rem;color:#333;
  letter-spacing:2px;text-transform:uppercase;font-weight:600}
.sidebar a{display:flex;align-items:center;gap:12px;padding:11px 16px;
  color:#555;text-decoration:none;font-size:.85rem;font-weight:500;
  margin:2px 8px;border-radius:8px;transition:all .2s;border:1px solid transparent}
.sidebar a .icon{font-size:1rem;width:20px;text-align:center}
.sidebar a:hover{background:rgba(255,45,45,.08);color:#ff2d2d;border-color:rgba(255,45,45,.15)}
.sidebar a.active{background:rgba(255,45,45,.12);color:#ff2d2d;
  border-color:rgba(255,45,45,.2);font-weight:600}
.sidebar .spacer{flex:1}
.sidebar .logout-wrap{padding:12px;border-top:1px solid #1c1c1c}
.sidebar .logout-wrap a{margin:0;border-radius:8px;color:#444;justify-content:center;
  font-size:.82rem}
.sidebar .logout-wrap a:hover{background:rgba(255,45,45,.08);color:#ff2d2d}

/* ── Main content ── */
.main{margin-left:240px;min-height:100vh;background:#080808}
.top-bar{display:flex;justify-content:space-between;align-items:center;
  padding:20px 28px;border-bottom:1px solid #111;background:#0a0a0a;
  position:sticky;top:0;z-index:50}
.top-bar h2{font-size:1.1rem;font-weight:700;color:#fff}
.top-bar .badge{font-size:.72rem;color:#ff2d2d;background:rgba(255,45,45,.1);
  padding:5px 14px;border-radius:20px;border:1px solid rgba(255,45,45,.2);
  font-weight:600;letter-spacing:.5px}
.page-content{padding:24px 28px}

/* ── Flash ── */
.flash{display:flex;align-items:center;gap:10px;padding:12px 16px;
  border-radius:8px;margin-bottom:18px;font-size:.85rem;font-weight:500}
.flash.ok{background:rgba(39,174,96,.1);border:1px solid rgba(39,174,96,.2);color:#27ae60}
.flash.err{background:rgba(255,45,45,.1);border:1px solid rgba(255,45,45,.2);color:#ff6b6b}

/* ── Stat cards ── */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:16px;margin-bottom:24px}
.card{background:#0f0f0f;border:1px solid #1a1a1a;border-radius:12px;
  padding:20px;cursor:pointer;transition:all .25s;position:relative;overflow:hidden}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,#ff2d2d,#ff6b6b);opacity:0;transition:.25s}
.card:hover{border-color:rgba(255,45,45,.3);transform:translateY(-2px);
  box-shadow:0 8px 24px rgba(255,45,45,.1)}
.card:hover::before{opacity:1}
.card .c-lbl{font-size:.68rem;color:#444;text-transform:uppercase;
  letter-spacing:1.5px;font-weight:600;margin-bottom:10px}
.card .c-num{font-size:2rem;font-weight:800;color:#ff2d2d;line-height:1}
.card .c-sub{font-size:.72rem;color:#333;margin-top:6px}

/* ── Tables ── */
.tbl-wrap{background:#0f0f0f;border:1px solid #1a1a1a;border-radius:12px;overflow:hidden}
table{width:100%;border-collapse:collapse}
th{padding:12px 16px;text-align:left;font-size:.68rem;text-transform:uppercase;
  letter-spacing:1px;color:#444;font-weight:700;background:#0a0a0a;
  border-bottom:1px solid #1a1a1a}
td{padding:12px 16px;font-size:.85rem;color:#bbb;border-bottom:1px solid #111}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.02)}

/* ── Tabs ── */
.tabs{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.tab{padding:8px 18px;border:1px solid #1c1c1c;border-radius:20px;
  font-size:.8rem;color:#555;text-decoration:none;transition:all .2s;font-weight:500}
.tab:hover{border-color:rgba(255,45,45,.3);color:#ff2d2d}
.tab.active{background:rgba(255,45,45,.12);border-color:rgba(255,45,45,.25);
  color:#ff2d2d;font-weight:600}

/* ── Buttons ── */
.btn{border:none;padding:8px 18px;border-radius:8px;cursor:pointer;
  font-size:.83rem;font-weight:600;transition:all .2s;font-family:inherit}
.btn-red{background:linear-gradient(135deg,#ff2d2d,#cc0000);color:#fff;
  box-shadow:0 2px 12px rgba(255,45,45,.3)}
.btn-red:hover{background:linear-gradient(135deg,#ff5555,#ff2d2d);
  box-shadow:0 4px 20px rgba(255,45,45,.5);transform:translateY(-1px)}
.btn-green{background:rgba(39,174,96,.15);color:#27ae60;border:1px solid rgba(39,174,96,.25)}
.btn-green:hover{background:rgba(39,174,96,.25)}
.btn-gray{background:#1a1a1a;color:#555;border:1px solid #222}
.btn-gray:hover{background:#222;color:#888}
.btn-sm{padding:5px 12px;font-size:.78rem}

/* ── Inputs ── */
input[type=text],input[type=password],input[type=date],select{
  background:#0f0f0f;border:1px solid #222;color:#fff;border-radius:8px;
  padding:10px 14px;font-size:.875rem;outline:none;font-family:inherit;
  transition:border .2s}
input:focus,select:focus{border-color:rgba(255,45,45,.5);
  box-shadow:0 0 0 3px rgba(255,45,45,.08)}
select option{background:#0f0f0f}

/* ── Badges ── */
.badge{display:inline-block;padding:3px 10px;border-radius:20px;
  font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.badge-pending{background:rgba(245,166,35,.1);color:#f5a623;border:1px solid rgba(245,166,35,.2)}
.badge-accepted{background:rgba(39,174,96,.1);color:#27ae60;border:1px solid rgba(39,174,96,.2)}
.badge-declined{background:rgba(255,45,45,.1);color:#ff6b6b;border:1px solid rgba(255,45,45,.2)}

/* ── Payment cards ── */
.req{background:#0f0f0f;border:1px solid #1a1a1a;border-radius:12px;
  padding:20px;margin-bottom:12px;transition:all .25s}
.req:hover{border-color:rgba(255,45,45,.2);box-shadow:0 4px 20px rgba(255,45,45,.06)}
.req-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.req-id{font-size:.68rem;color:#333;background:#1a1a1a;padding:3px 9px;
  border-radius:4px;font-family:monospace}
.req-info{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
.req-info .item{font-size:.83rem;color:#888}
.req-info .item strong{color:#ccc;font-weight:500}
.req-info .amount{color:#27ae60;font-weight:700;font-size:.95rem}
.req-meta{font-size:.75rem;color:#333;padding-top:8px;border-top:1px solid #111}
.req-actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;align-items:center}
.req-actions form{display:flex;gap:6px;align-items:center}
.idpass-sent{background:rgba(74,144,226,.06);border:1px solid rgba(74,144,226,.15);
  border-radius:8px;padding:10px 14px;font-size:.82rem;color:#4a90e2;margin-bottom:8px}

/* ── Settings box ── */
.sbox{background:#0f0f0f;border:1px solid #1a1a1a;border-radius:12px;
  padding:22px;margin-bottom:16px;max-width:520px}
.sbox-title{color:#ff2d2d;font-weight:700;font-size:.9rem;margin-bottom:6px;
  text-transform:uppercase;letter-spacing:.5px}
.sbox-sub{color:#333;font-size:.78rem;margin-bottom:16px}

/* ── Empty ── */
.empty{text-align:center;padding:60px 20px;color:#2a2a2a}
.empty .empty-icon{font-size:2.5rem;margin-bottom:12px}
.empty .empty-txt{font-size:.9rem}

/* ── Date filter bar ── */
.filter-bar{display:flex;align-items:center;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.filter-bar label{font-size:.78rem;color:#444;text-transform:uppercase;
  letter-spacing:1px;font-weight:600}

@media(max-width:768px){.sidebar{transform:translateX(-100%)}.main{margin-left:0}
  .req-info{grid-template-columns:1fr}.cards{grid-template-columns:1fr 1fr}}
"""

# ── Login page ─────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ site_name }} — Login</title>
<style>
""" + SHARED_CSS + """
body{display:flex;align-items:center;justify-content:center;
  background:radial-gradient(ellipse at 50% 0%,rgba(255,45,45,.08) 0%,#080808 60%)}
.login-wrap{width:100%;max-width:400px;padding:20px}
.login-box{background:#0f0f0f;border:1px solid #1c1c1c;border-radius:16px;
  padding:36px 32px;position:relative;overflow:hidden}
.login-box::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;
  background:linear-gradient(90deg,#ff2d2d,#ff6b6b,#ff2d2d)}
.logo{text-align:center;margin-bottom:28px}
.logo .name{font-size:1.4rem;font-weight:800;color:#ff2d2d;letter-spacing:.5px}
.logo .tagline{font-size:.72rem;color:#333;margin-top:4px;letter-spacing:2px;text-transform:uppercase}
.field{margin-bottom:14px}
.field label{display:block;font-size:.7rem;color:#444;text-transform:uppercase;
  letter-spacing:1px;font-weight:600;margin-bottom:7px}
.field input{width:100%}
.login-btn{width:100%;padding:13px;background:linear-gradient(135deg,#ff2d2d,#cc0000);
  color:#fff;border:none;border-radius:10px;font-size:.95rem;font-weight:700;
  cursor:pointer;font-family:inherit;letter-spacing:.5px;margin-top:6px;
  box-shadow:0 4px 20px rgba(255,45,45,.3);transition:all .2s}
.login-btn:hover{box-shadow:0 6px 28px rgba(255,45,45,.5);transform:translateY(-1px)}
.err{background:rgba(255,45,45,.08);border:1px solid rgba(255,45,45,.2);
  color:#ff6b6b;border-radius:8px;padding:10px 14px;font-size:.83rem;margin-bottom:16px;
  display:flex;align-items:center;gap:8px}
.hint{text-align:center;color:#222;font-size:.72rem;margin-top:20px}
</style>
</head>
<body>
<div class="login-wrap">
  <div class="login-box">
    <div class="logo">
      <div class="name">🔥 {{ site_name }}</div>
      <div class="tagline">Admin Control Panel</div>
    </div>
    {% if error %}<div class="err">❌ {{ error }}</div>{% endif %}
    <form method="post">
      <div class="field">
        <label>Username</label>
        <input type="text" name="username" placeholder="Enter username" autocomplete="off" required>
      </div>
      <div class="field">
        <label>Password</label>
        <input type="password" name="password" placeholder="Enter password" required>
      </div>
      <button type="submit" class="login-btn">LOGIN →</button>
    </form>
    <div class="hint">Laser Web Panel • Authorized Access Only</div>
  </div>
</div>
</body>
</html>"""

# ── Base layout ────────────────────────────────────────────

BASE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ page_title }} — {{ site_name }}</title>
<style>
""" + SHARED_CSS + """
body{display:flex}
</style>
<script>function go(u){location.href=u}</script>
</head>
<body>

<div class="sidebar">
  <div class="sidebar-logo">
    <div class="brand">🔥 {{ site_name }}</div>
    <div class="sub">Admin Panel</div>
  </div>

  {% if role == 'admin' %}
  <div class="nav-section">Main</div>
  <a href="/admin/" class="{{ 'active' if active=='dashboard' else '' }}">
    <span class="icon">📊</span> Dashboard</a>
  <a href="/admin/today" class="{{ 'active' if active=='today' else '' }}">
    <span class="icon">📅</span> Today Overview</a>
  <div class="nav-section">Manage</div>
  <a href="/admin/payments" class="{{ 'active' if active=='payments' else '' }}">
    <span class="icon">💳</span> Payments</a>
  <a href="/admin/registrations" class="{{ 'active' if active=='regs' else '' }}">
    <span class="icon">👤</span> Registrations</a>
  <a href="/admin/deposits" class="{{ 'active' if active=='deposits' else '' }}">
    <span class="icon">💰</span> Deposits</a>
  <div class="nav-section">Admin</div>
  <a href="/admin/subusers" class="{{ 'active' if active=='subusers' else '' }}">
    <span class="icon">👥</span> Sub Users</a>
  <a href="/admin/settings" class="{{ 'active' if active=='settings' else '' }}">
    <span class="icon">⚙</span> Settings</a>
  {% else %}
  <div class="nav-section">Payments</div>
  <a href="/admin/payments" class="{{ 'active' if active=='payments' else '' }}">
    <span class="icon">💳</span> Payments</a>
  {% endif %}

  <div class="spacer"></div>
  <div class="logout-wrap">
    <a href="/admin/logout"><span class="icon">🚪</span> Logout ({{ username }})</a>
  </div>
</div>

<div class="main">
  <div class="top-bar">
    <h2>{{ page_title }}</h2>
    <div class="badge">{{ site_name }}</div>
  </div>
  <div class="page-content">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for cat, msg in messages %}
        <div class="flash {{ 'ok' if cat!='error' else 'err' }}">{{ msg }}</div>
      {% endfor %}
    {% endwith %}
    {{ content | safe }}
  </div>
</div>

</body>
</html>"""


def render(page_title, active, content):
    role = session.get("role", "admin")
    username = session.get("username", "Admin")
    return render_template_string(
        BASE_HTML,
        page_title=page_title, active=active, content=content,
        site_name=SITE_NAME, role=role, username=username
    )


# ── Auth ───────────────────────────────────────────────────

@flask_app.route("/admin/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect("/admin/")
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if username.lower() == "admin" and password == ADMIN_PASSWORD:
            session.update(logged_in=True, role="admin", username="Admin")
            return redirect("/admin/")
        sub = db_conn.execute(
            "SELECT * FROM subadmins WHERE name=? AND password=?", (username, password)
        ).fetchone()
        if sub:
            session.update(logged_in=True, role="subadmin", username=username)
            return redirect("/admin/payments")
        error = "Invalid username or password."
    return render_template_string(LOGIN_HTML, error=error, site_name=SITE_NAME)


@flask_app.route("/admin/logout")
def logout():
    session.clear()
    return redirect("/admin/login")


# ── Dashboard ──────────────────────────────────────────────

@flask_app.route("/admin/")
@flask_app.route("/admin")
@admin_only
def dashboard():
    date_filter = request.args.get("date", "")
    if date_filter:
        where_date = f"WHERE date(created_at)='{date_filter}'"
        where_date_acc = f"WHERE status='accepted' AND date(created_at)='{date_filter}'"
        heading = f"Stats for {date_filter}"
    else:
        where_date = ""
        where_date_acc = "WHERE status='accepted'"
        heading = "All Time Stats"

    today = datetime.date.today().isoformat()
    s = {
        "total_reg":    db_conn.execute(f"SELECT COUNT(*) FROM users {where_date}").fetchone()[0],
        "total_dep":    db_conn.execute(f"SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM users {where_date_acc}").fetchone()[0],
        "today_reg":    db_conn.execute(f"SELECT COUNT(*) FROM users WHERE date(created_at)='{today}'").fetchone()[0],
        "today_dep":    db_conn.execute(f"SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM users WHERE status='accepted' AND date(created_at)='{today}'").fetchone()[0],
        "pending":      db_conn.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0],
        "accepted":     db_conn.execute("SELECT COUNT(*) FROM users WHERE status='accepted'").fetchone()[0],
        "declined":     db_conn.execute("SELECT COUNT(*) FROM users WHERE status='declined'").fetchone()[0],
    }

    content = f"""
<div class="filter-bar">
  <label>📅 Filter by Date:</label>
  <form method="get" style="display:flex;gap:10px;align-items:center">
    <input type="date" name="date" value="{date_filter}" max="{today}">
    <button class="btn btn-red btn-sm">Filter</button>
    {'<a href="/admin/" class="btn btn-gray btn-sm">Clear</a>' if date_filter else ''}
  </form>
  <span style="color:#333;font-size:.78rem">{heading}</span>
</div>

<div style="color:#333;font-size:.7rem;text-transform:uppercase;letter-spacing:2px;margin-bottom:12px">
  {'Filtered Results' if date_filter else 'Today Summary'}
</div>
<div class="cards">
  <div class="card" onclick="go('/admin/today')">
    <div class="c-lbl">Today Registrations</div>
    <div class="c-num">{s['today_reg']}</div>
    <div class="c-sub">New IDs today</div>
  </div>
  <div class="card" onclick="go('/admin/today')">
    <div class="c-lbl">Today Deposit</div>
    <div class="c-num">₹{s['today_dep']}</div>
    <div class="c-sub">Accepted payments</div>
  </div>
</div>

<div style="color:#333;font-size:.7rem;text-transform:uppercase;letter-spacing:2px;margin-bottom:12px">
  {heading}
</div>
<div class="cards">
  <div class="card" onclick="go('/admin/registrations')">
    <div class="c-lbl">Total Registrations</div>
    <div class="c-num">{s['total_reg']}</div>
    <div class="c-sub">All users</div>
  </div>
  <div class="card" onclick="go('/admin/deposits')">
    <div class="c-lbl">Total Deposit</div>
    <div class="c-num">₹{s['total_dep']}</div>
    <div class="c-sub">Total collected</div>
  </div>
  <div class="card" onclick="go('/admin/payments?f=pending')">
    <div class="c-lbl">⏳ Pending</div>
    <div class="c-num" style="color:#f5a623">{s['pending']}</div>
    <div class="c-sub">Awaiting review</div>
  </div>
  <div class="card" onclick="go('/admin/payments?f=accepted')">
    <div class="c-lbl">✅ Accepted</div>
    <div class="c-num" style="color:#27ae60">{s['accepted']}</div>
    <div class="c-sub">Processed</div>
  </div>
  <div class="card" onclick="go('/admin/payments?f=declined')">
    <div class="c-lbl">❌ Declined</div>
    <div class="c-num" style="color:#ff6b6b">{s['declined']}</div>
    <div class="c-sub">Rejected</div>
  </div>
</div>
"""
    return render("Dashboard", "dashboard", content)


# ── Today Overview ─────────────────────────────────────────

@flask_app.route("/admin/today")
@admin_only
def today_overview():
    today = datetime.date.today().isoformat()

    today_regs = db_conn.execute(
        "SELECT name, phone, site, id_type, created_at FROM users WHERE date(created_at)=? ORDER BY id DESC",
        (today,)
    ).fetchall()

    today_deps = db_conn.execute(
        "SELECT name, phone, site, amount, created_at FROM users WHERE status='accepted' AND date(created_at)=? ORDER BY id DESC",
        (today,)
    ).fetchall()

    total_dep_today = sum(float(r["amount"] or 0) for r in today_deps)

    reg_trs = "".join([
        f"<tr><td><strong>{r['name']}</strong></td><td>{r['phone']}</td>"
        f"<td>{r['site']}</td>"
        f"<td><span class='badge badge-accepted'>{(r['id_type'] or 'N/A').upper()}</span></td>"
        f"<td style='color:#333'>{str(r['created_at'])[:16]}</td></tr>"
        for r in today_regs
    ]) or f"<tr><td colspan='5' style='text-align:center;color:#2a2a2a;padding:30px'>No registrations today</td></tr>"

    dep_trs = "".join([
        f"<tr><td><strong>{r['name']}</strong></td><td>{r['phone']}</td>"
        f"<td>{r['site']}</td>"
        f"<td style='color:#27ae60;font-weight:700'>₹{r['amount']}</td>"
        f"<td style='color:#333'>{str(r['created_at'])[:16]}</td></tr>"
        for r in today_deps
    ]) or f"<tr><td colspan='5' style='text-align:center;color:#2a2a2a;padding:30px'>No deposits today</td></tr>"

    content = f"""
<div class="cards" style="margin-bottom:24px">
  <div class="card">
    <div class="c-lbl">Today Registrations</div>
    <div class="c-num">{len(today_regs)}</div>
    <div class="c-sub">New IDs — {today}</div>
  </div>
  <div class="card">
    <div class="c-lbl">Today Deposits</div>
    <div class="c-num">₹{total_dep_today}</div>
    <div class="c-sub">Accepted payments</div>
  </div>
</div>

<div style="margin-bottom:24px">
  <div style="color:#ff2d2d;font-weight:700;font-size:.85rem;text-transform:uppercase;
    letter-spacing:1px;margin-bottom:12px">📋 Today Registrations ({len(today_regs)})</div>
  <div class="tbl-wrap">
    <table><tr><th>Name</th><th>Phone</th><th>Site</th><th>Type</th><th>Time</th></tr>
    {reg_trs}</table>
  </div>
</div>

<div>
  <div style="color:#27ae60;font-weight:700;font-size:.85rem;text-transform:uppercase;
    letter-spacing:1px;margin-bottom:12px">💰 Today Deposits — Total: ₹{total_dep_today}</div>
  <div class="tbl-wrap">
    <table><tr><th>Name</th><th>Phone</th><th>Site</th><th>Amount</th><th>Time</th></tr>
    {dep_trs}</table>
  </div>
</div>
"""
    return render("Today Overview", "today", content)


# ── Payments ───────────────────────────────────────────────

@flask_app.route("/admin/payments")
@login_required
def payments():
    f = request.args.get("f", "pending")
    if f == "all":
        rows = db_conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    else:
        rows = db_conn.execute(
            "SELECT * FROM users WHERE status=? ORDER BY id DESC", (f,)).fetchall()

    tabs = ""
    for label, key in [("⏳ Pending","pending"),("✅ Accepted","accepted"),("❌ Declined","declined"),("📋 All","all")]:
        cls = "active" if f == key else ""
        tabs += f'<a class="tab {cls}" href="/admin/payments?f={key}">{label}</a>'

    cards = ""
    for u in rows:
        idpass_html = (f'<div class="idpass-sent">✅ ID Sent: <strong>{u["id_pass"]}</strong></div>'
                       if u["id_pass"] else "")

        if u["status"] == "pending":
            action = f"""
<div class="req-actions">
  <form method="post" action="/admin/accept/{u['id']}">
    <button class="btn btn-green btn-sm">✅ Accept</button>
  </form>
  <form method="post" action="/admin/decline/{u['id']}">
    <button class="btn btn-gray btn-sm">❌ Decline</button>
  </form>
</div>"""
        elif u["status"] == "accepted" and not u["id_pass"]:
            action = f"""
<div class="req-actions" style="width:100%">
  <form method="post" action="/admin/sendid/{u['id']}"
    style="display:flex;gap:8px;align-items:center;flex:1;flex-wrap:wrap">
    <input type="text" name="idpass"
      placeholder="ID: laser123  Pass: abc@123" required
      style="flex:1;min-width:200px">
    <button class="btn btn-red btn-sm">🎯 Send ID</button>
  </form>
</div>"""
        else:
            action = ""

        cards += f"""
<div class="req">
  <div class="req-top">
    <strong style="font-size:.9rem">💳 Payment Request</strong>
    <div style="display:flex;gap:8px;align-items:center">
      <span class="req-id">#{u['id']}</span>
      <span class="badge badge-{u['status']}">{u['status']}</span>
    </div>
  </div>
  <div class="req-info">
    <div class="item">👤 <strong>{u['name']}</strong></div>
    <div class="item">📱 <strong>{u['phone']}</strong></div>
    <div class="item">🌐 {u['site']} <span style="color:#333;font-size:.75rem">({(u['id_type'] or 'N/A').upper()})</span></div>
    <div class="item amount">💰 ₹{u['amount']}</div>
  </div>
  <div class="req-meta">🔢 UTR: {u['utr'] or '—'} &nbsp;·&nbsp; 🕐 {str(u['created_at'])[:16] if u['created_at'] else '—'}</div>
  {idpass_html}{action}
</div>"""

    if not rows:
        cards = '<div class="empty"><div class="empty-icon">🔍</div><div class="empty-txt">No requests found</div></div>'

    count_info = f'<div style="font-size:.75rem;color:#333;text-transform:uppercase;letter-spacing:2px;margin-bottom:16px">{len(rows)} request(s)</div>'
    content = f'<div class="tabs">{tabs}</div>{count_info}{cards}'
    return render("Payments", "payments", content)


@flask_app.route("/admin/accept/<int:rid>", methods=["POST"])
@login_required
def accept(rid):
    row = db_conn.execute("SELECT * FROM users WHERE id=?", (rid,)).fetchone()
    if not row or row["status"] != "pending":
        flash("Not found or already processed.", "error")
        return redirect("/admin/payments")
    db_conn.execute("UPDATE users SET status='accepted' WHERE id=?", (rid,))
    db_conn.commit()
    send_tg(row["telegram_id"],
        "✅ *Sir, Payment Received!*\n\n"
        "Your payment has been verified. Please wait 2–5 minutes — we are processing your ID. 🙏")
    flash(f"✅ Request #{rid} accepted. Now enter and send the ID.")
    return redirect("/admin/payments?f=accepted")


@flask_app.route("/admin/sendid/<int:rid>", methods=["POST"])
@login_required
def sendid(rid):
    idpass = request.form.get("idpass", "").strip()
    if not idpass:
        flash("Please enter ID & Password.", "error")
        return redirect("/admin/payments?f=accepted")
    row = db_conn.execute("SELECT * FROM users WHERE id=?", (rid,)).fetchone()
    if not row:
        flash("Request not found.", "error")
        return redirect("/admin/payments?f=accepted")
    db_conn.execute("UPDATE users SET id_pass=? WHERE id=?", (idpass, rid))
    db_conn.commit()
    send_tg(row["telegram_id"],
        f"🎯 *Sir, your ID is ready!*\n\n"
        f"🌐 Site: *{row['site']}*\n"
        f"📋 Details:\n`{idpass}`\n\n"
        f"Please keep this safe. Do not share with anyone.")
    send_tg(row["telegram_id"],
        "🔴 *LASER WEB — OFFICIAL SERVICE* 🔴\n\n"
        "⚡ Fast Delivery • 🔒 100% Secure • ✅ Trusted\n\n"
        "Thank you for choosing us! For support, contact admin.")
    flash(f"🎯 ID sent successfully to user for request #{rid}.")
    return redirect("/admin/payments?f=accepted")


@flask_app.route("/admin/decline/<int:rid>", methods=["POST"])
@login_required
def decline(rid):
    row = db_conn.execute("SELECT * FROM users WHERE id=?", (rid,)).fetchone()
    if not row or row["status"] != "pending":
        flash("Not found or already processed.", "error")
        return redirect("/admin/payments")
    db_conn.execute("UPDATE users SET status='declined' WHERE id=?", (rid,))
    db_conn.commit()
    send_tg(row["telegram_id"],
        "❌ *Sir, Payment not verified.*\n\n"
        "We could not verify your payment. Please check your UTR number and try again.\n"
        "Type /start to submit again.")
    flash(f"❌ Request #{rid} declined.")
    return redirect("/admin/payments?f=pending")


# ── Registrations ──────────────────────────────────────────

@flask_app.route("/admin/registrations")
@admin_only
def registrations():
    date_filter = request.args.get("date", "")
    today = datetime.date.today().isoformat()
    if date_filter:
        rows = db_conn.execute(
            "SELECT name, phone, site, id_type, created_at FROM users WHERE date(created_at)=? ORDER BY id DESC",
            (date_filter,)).fetchall()
    else:
        rows = db_conn.execute(
            "SELECT name, phone, site, id_type, created_at FROM users ORDER BY id DESC").fetchall()

    trs = "".join([
        f"<tr><td><strong>{r['name']}</strong></td><td>{r['phone']}</td><td>{r['site']}</td>"
        f"<td><span class='badge badge-accepted'>{(r['id_type'] or 'N/A').upper()}</span></td>"
        f"<td style='color:#444'>{str(r['created_at'])[:16]}</td></tr>"
        for r in rows
    ]) or "<tr><td colspan='5' style='text-align:center;color:#2a2a2a;padding:40px'>No registrations found</td></tr>"

    content = f"""
<div class="filter-bar">
  <label>📅 Filter by Date:</label>
  <form method="get" style="display:flex;gap:10px;align-items:center">
    <input type="date" name="date" value="{date_filter}" max="{today}">
    <button class="btn btn-red btn-sm">Filter</button>
    {'<a href="/admin/registrations" class="btn btn-gray btn-sm">Clear</a>' if date_filter else ''}
  </form>
  <span style="color:#333;font-size:.78rem">{len(rows)} registration(s)</span>
</div>
<div class="tbl-wrap">
  <table><tr><th>Name</th><th>Phone</th><th>Site</th><th>Type</th><th>Date</th></tr>
  {trs}</table>
</div>"""
    return render("Registrations", "regs", content)


# ── Deposits ───────────────────────────────────────────────

@flask_app.route("/admin/deposits")
@admin_only
def deposits():
    date_filter = request.args.get("date", "")
    today = datetime.date.today().isoformat()
    if date_filter:
        rows = db_conn.execute(
            "SELECT name, phone, site, amount, created_at FROM users WHERE status='accepted' AND date(created_at)=? ORDER BY id DESC",
            (date_filter,)).fetchall()
    else:
        rows = db_conn.execute(
            "SELECT name, phone, site, amount, created_at FROM users WHERE status='accepted' ORDER BY id DESC"
        ).fetchall()

    total = sum(float(r["amount"] or 0) for r in rows)

    trs = "".join([
        f"<tr><td><strong>{r['name']}</strong></td><td>{r['phone']}</td><td>{r['site']}</td>"
        f"<td style='color:#27ae60;font-weight:700'>₹{r['amount']}</td>"
        f"<td style='color:#444'>{str(r['created_at'])[:16]}</td></tr>"
        for r in rows
    ]) or "<tr><td colspan='5' style='text-align:center;color:#2a2a2a;padding:40px'>No deposits found</td></tr>"

    content = f"""
<div class="filter-bar">
  <label>📅 Filter by Date:</label>
  <form method="get" style="display:flex;gap:10px;align-items:center">
    <input type="date" name="date" value="{date_filter}" max="{today}">
    <button class="btn btn-red btn-sm">Filter</button>
    {'<a href="/admin/deposits" class="btn btn-gray btn-sm">Clear</a>' if date_filter else ''}
  </form>
  <span style="color:#333;font-size:.78rem">{len(rows)} deposit(s)</span>
</div>
<div class="cards" style="margin-bottom:20px">
  <div class="card">
    <div class="c-lbl">Total Collected</div>
    <div class="c-num" style="color:#27ae60">₹{total}</div>
    <div class="c-sub">{'Date: ' + date_filter if date_filter else 'All time'}</div>
  </div>
  <div class="card">
    <div class="c-lbl">Transactions</div>
    <div class="c-num">{len(rows)}</div>
    <div class="c-sub">Accepted payments</div>
  </div>
</div>
<div class="tbl-wrap">
  <table><tr><th>Name</th><th>Phone</th><th>Site</th><th>Amount</th><th>Date</th></tr>
  {trs}</table>
</div>"""
    return render("Deposits", "deposits", content)


# ── Sub Users ──────────────────────────────────────────────

@flask_app.route("/admin/subusers", methods=["GET", "POST"])
@admin_only
def subusers():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name = request.form.get("name", "").strip()
            pwd  = request.form.get("password", "").strip()
            if name and pwd:
                try:
                    db_conn.execute(
                        "INSERT INTO subadmins (name, password) VALUES (?,?)", (name, pwd))
                    db_conn.commit()
                    flash(f"✅ Sub user '{name}' added successfully.")
                except Exception:
                    flash("Username already exists.", "error")
            else:
                flash("Both username and password are required.", "error")
        elif action == "delete":
            db_conn.execute("DELETE FROM subadmins WHERE id=?", (request.form.get("uid"),))
            db_conn.commit()
            flash("🗑️ Sub user removed.")
        return redirect("/admin/subusers")

    rows = db_conn.execute("SELECT * FROM subadmins ORDER BY id DESC").fetchall()
    trs = "".join([
        f"<tr><td>#{r['id']}</td><td><strong>{r['name']}</strong></td>"
        f"<td><span style='color:#4a90e2;font-family:monospace'>{r['password'] or '—'}</span></td>"
        f"<td style='color:#444'>{str(r['created_at'])[:16]}</td>"
        f"<td><form method='post' style='display:inline'>"
        f"<input type='hidden' name='action' value='delete'>"
        f"<input type='hidden' name='uid' value='{r['id']}'>"
        f"<button class='btn btn-gray btn-sm'>🗑️ Remove</button></form></td></tr>"
        for r in rows
    ]) or "<tr><td colspan='5' style='text-align:center;color:#2a2a2a;padding:40px'>No sub users added yet</td></tr>"

    content = f"""
<div class="sbox">
  <div class="sbox-title">➕ Add Sub User</div>
  <div class="sbox-sub">Sub users can only access Payments (accept, decline, send ID)</div>
  <form method="post" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <input type="hidden" name="action" value="add">
    <input type="text" name="name" placeholder="Username" required style="flex:1;min-width:140px">
    <input type="text" name="password" placeholder="Password" required style="flex:1;min-width:140px">
    <button class="btn btn-red">Add User</button>
  </form>
</div>
<div class="tbl-wrap">
  <table><tr><th>#</th><th>Username</th><th>Password</th><th>Added</th><th>Action</th></tr>
  {trs}</table>
</div>"""
    return render("Sub Users", "subusers", content)


# ── Settings ───────────────────────────────────────────────

@flask_app.route("/admin/settings", methods=["GET", "POST"])
@admin_only
def settings():
    if request.method == "POST":
        new_upi = request.form.get("upi", "").strip()
        if new_upi:
            db_conn.execute("UPDATE settings SET upi=? WHERE id=1", (new_upi,))
            db_conn.commit()
            flash(f"✅ UPI updated to: {new_upi}")
        else:
            flash("UPI ID cannot be empty.", "error")
        return redirect("/admin/settings")

    content = f"""
<div class="sbox">
  <div class="sbox-title">💳 UPI ID</div>
  <div class="sbox-sub">Change the UPI ID used for payment QR code. Takes effect immediately.</div>
  <div style="margin-bottom:14px;padding:12px;background:#0a0a0a;border-radius:8px;
    border:1px solid #1a1a1a;font-size:.85rem">
    <span style="color:#444">Current UPI:</span>
    <span style="color:#f5a623;font-weight:700;margin-left:8px;font-family:monospace">
      {get_upi() or 'Not set'}
    </span>
  </div>
  <form method="post" style="display:flex;gap:10px;align-items:center">
    <input type="text" name="upi" placeholder="yourname@upi" style="flex:1">
    <button class="btn btn-red">Update UPI</button>
  </form>
</div>

<div class="sbox">
  <div class="sbox-title">ℹ️ Panel Info</div>
  <div class="sbox-sub">System information</div>
  <div style="font-size:.83rem;color:#444;line-height:2">
    🔥 Site: <span style="color:#ff2d2d">{SITE_NAME}</span><br>
    📊 Total Users: <span style="color:#ccc">{db_conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]}</span><br>
    💰 Total Collected: <span style="color:#27ae60">₹{db_conn.execute("SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM users WHERE status='accepted'").fetchone()[0]}</span><br>
    👥 Sub Users: <span style="color:#ccc">{db_conn.execute("SELECT COUNT(*) FROM subadmins").fetchone()[0]}</span>
  </div>
</div>"""
    return render("Settings", "settings", content)


# ── Catch all ──────────────────────────────────────────────

@flask_app.errorhandler(404)
def not_found(e):
    return redirect("/admin/login")


@flask_app.route("/")
@flask_app.route("/<path:path>")
def catch_all(path=""):
    return redirect("/admin/login")


# ═══════════════════════════════════════════════════════════
#  TELEGRAM BOT
# ═══════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🆕 New ID",  callback_data="type_new")],
        [InlineKeyboardButton("🎁 Demo ID", callback_data="type_demo")],
    ]
    await update.message.reply_text(
        f"🙏 *Welcome to {SITE_NAME}!*\n\nPlease choose your ID type:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data in ("type_new", "type_demo"):
        context.user_data.clear()
        context.user_data["id_type"] = "new" if data == "type_new" else "demo"
        kb = [[InlineKeyboardButton(s, callback_data=f"site_{s}")] for s in SITES]
        await q.message.reply_text(
            "🌐 *Select Site:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )
    elif data.startswith("site_"):
        context.user_data["site"] = data[5:]
        context.user_data["step"] = "name"
        await q.message.reply_text(
            "👤 *Please enter your full name:*", parse_mode="Markdown")


async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    step = context.user_data.get("step")

    if not step:
        await update.message.reply_text("Please type /start to begin.")
        return

    if step == "name":
        context.user_data["name"] = text
        context.user_data["step"] = "phone"
        await update.message.reply_text(
            "📱 *Please enter your phone number:*", parse_mode="Markdown")

    elif step == "phone":
        context.user_data["phone"] = text
        context.user_data["step"] = "amount"
        await update.message.reply_text(
            "💰 *Enter deposit amount (₹):*", parse_mode="Markdown")

    elif step == "amount":
        context.user_data["amount"] = text
        context.user_data["step"] = "utr"
        upi = get_upi()
        upi_link = f"upi://pay?pa={upi}&pn=Payment&am={text}&cu=INR"
        qr_path = os.path.join(BASE_DIR, f"qr_{update.effective_chat.id}.png")
        qrcode.make(upi_link).save(qr_path)
        with open(qr_path, "rb") as f:
            await update.message.reply_photo(
                f,
                caption=(
                    f"💳 *Pay ₹{text} via UPI*\n\n"
                    f"📲 UPI ID: `{upi}`\n\n"
                    f"✅ After payment, send your *UTR number* or *screenshot*.\n\n"
                    f"_Payment will be verified within 5 minutes._"
                ),
                parse_mode="Markdown",
            )
        try:
            os.remove(qr_path)
        except Exception:
            pass

    elif step == "utr":
        ud = context.user_data
        db_conn.execute("""
            INSERT INTO users (telegram_id,name,phone,site,id_type,amount,utr,status)
            VALUES (?,?,?,?,?,?,?,'pending')
        """, (
            update.effective_chat.id,
            ud.get("name",""), ud.get("phone",""),
            ud.get("site",""), ud.get("id_type","new"),
            ud.get("amount",""), text,
        ))
        db_conn.commit()
        req_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        context.user_data["step"] = None

        await update.message.reply_text(
            "⏳ *Request Submitted Successfully!*\n\n"
            "Your payment is under review.\n"
            "Please wait 2–5 minutes — we will send your ID shortly. 🙏",
            parse_mode="Markdown",
        )
        send_tg(ADMIN_CHAT_ID,
            f"🔔 *New Payment Request #{req_id}*\n\n"
            f"👤 Name: {ud.get('name')}\n"
            f"📱 Phone: {ud.get('phone')}\n"
            f"🌐 Site: {ud.get('site')} ({ud.get('id_type','new').upper()})\n"
            f"💰 Amount: ₹{ud.get('amount')}\n"
            f"🔢 UTR: {text}\n\n"
            f"👉 Review on admin panel → Payments"
        )


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") == "utr":
        ud = context.user_data
        db_conn.execute("""
            INSERT INTO users (telegram_id,name,phone,site,id_type,amount,utr,status)
            VALUES (?,?,?,?,?,?,?,'pending')
        """, (
            update.effective_chat.id,
            ud.get("name",""), ud.get("phone",""),
            ud.get("site",""), ud.get("id_type","new"),
            ud.get("amount",""), "screenshot",
        ))
        db_conn.commit()
        req_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        context.user_data["step"] = None

        await update.message.reply_text(
            "⏳ *Screenshot Received!*\n\n"
            "Your payment is under review.\n"
            "Please wait 2–5 minutes — we will send your ID shortly. 🙏",
            parse_mode="Markdown",
        )
        send_tg(ADMIN_CHAT_ID,
            f"🔔 *New Payment Request #{req_id}* (Screenshot)\n\n"
            f"👤 Name: {ud.get('name')}\n"
            f"📱 Phone: {ud.get('phone')}\n"
            f"🌐 Site: {ud.get('site')} ({ud.get('id_type','new').upper()})\n"
            f"💰 Amount: ₹{ud.get('amount')}\n\n"
            f"👉 Review on admin panel → Payments"
        )
    else:
        await update.message.reply_text("Please type /start to begin.")


# ═══════════════════════════════════════════════════════════
#  START — Flask in thread, Bot in main thread
# ═══════════════════════════════════════════════════════════

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    print(f"✅ {SITE_NAME} admin panel started")

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CallbackQueryHandler(btn_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    print("✅ Telegram bot started — polling...")
    application.run_polling(drop_pending_updates=True)
