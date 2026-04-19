import os
import sqlite3
import threading
import datetime
import qrcode
import requests as http_requests

from flask import Flask, render_template_string, redirect, request, session, flash
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
SESSION_SECRET = os.environ.get("SESSION_SECRET", "changeme123")
DEFAULT_UPI    = os.environ.get("UPI_ID", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "database.db")

SITES = ["Laser247", "Tiger399", "AllPanel", "Diamond"]

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
            name       TEXT NOT NULL,
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


# ── Templates ────────────────────────────────────────────

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Login</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0b0b0b;color:#fff;font-family:'Segoe UI',sans-serif;
     min-height:100vh;display:flex;align-items:center;justify-content:center}
.box{background:#111;border:1px solid #222;border-top:3px solid #ff3b3b;
     border-radius:12px;padding:40px 36px;width:100%;max-width:360px}
h1{color:#ff3b3b;font-size:1.4rem;margin-bottom:6px}
p{color:#555;font-size:.82rem;margin-bottom:28px}
label{display:block;font-size:.75rem;color:#666;text-transform:uppercase;
      letter-spacing:1px;margin-bottom:6px}
input[type=password]{width:100%;background:#1a1a1a;border:1px solid #333;
  border-radius:8px;color:#fff;font-size:.95rem;padding:11px 14px;
  margin-bottom:20px;outline:none}
input:focus{border-color:#ff3b3b}
button{width:100%;background:#ff3b3b;color:#fff;border:none;
       border-radius:8px;padding:12px;font-size:.95rem;font-weight:bold;cursor:pointer}
button:hover{background:#cc0000}
.err{background:#2d0000;border:1px solid #ff3b3b;color:#ff8888;
     border-radius:8px;padding:10px 14px;font-size:.82rem;margin-bottom:18px}
</style>
</head>
<body>
<div class="box">
  <h1>🔥 Admin Login</h1>
  <p>Payment Requests Dashboard</p>
  {% if error %}<div class="err">❌ {{ error }}</div>{% endif %}
  <form method="post" action="/admin/login">
    <label>Password</label>
    <input type="password" name="password" placeholder="Enter admin password" autofocus>
    <button>Login →</button>
  </form>
</div>
</body>
</html>
"""

BASE_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🔥 {{ page_title }}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{display:flex;font-family:'Segoe UI',sans-serif;background:#0b0b0b;color:#fff;min-height:100vh}

.sidebar{width:220px;background:#111;height:100vh;border-right:1px solid #1a1a1a;
         position:fixed;top:0;left:0;display:flex;flex-direction:column}
.sidebar-logo{color:#ff3b3b;text-align:center;font-size:1.2rem;font-weight:bold;
              padding:22px 16px 18px;border-bottom:1px solid #1a1a1a;letter-spacing:1px}
.sidebar a{display:flex;align-items:center;gap:10px;padding:13px 20px;color:#aaa;
           text-decoration:none;font-size:.88rem;transition:.2s;border-left:3px solid transparent}
.sidebar a:hover{background:#1a1a1a;color:#ff3b3b;border-left-color:#ff3b3b}
.sidebar a.active{background:#1a1a1a;color:#ff3b3b;border-left-color:#ff3b3b}
.sidebar .spacer{flex:1}
.sidebar a.logout{color:#555;border-top:1px solid #1a1a1a}
.sidebar a.logout:hover{color:#ff3b3b}

.main{margin-left:220px;flex:1;padding:28px}
.top-bar{display:flex;justify-content:space-between;align-items:center;
         margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid #1a1a1a}
.top-bar h2{color:#ff3b3b;font-size:1.25rem}
.top-badge{font-size:.75rem;color:#555;background:#1a1a1a;padding:5px 12px;border-radius:20px}

.flash{background:#0d2d1a;border-left:3px solid #27ae60;color:#27ae60;
       padding:10px 16px;border-radius:6px;margin-bottom:18px;font-size:.85rem}
.flash.err{background:#2d0000;border-left-color:#ff3b3b;color:#ff8888}

.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:24px}
.card{background:#111;padding:18px 16px;border-radius:10px;border:1px solid #1a1a1a;
      text-align:center;cursor:pointer;transition:.25s}
.card:hover{border-color:#ff3b3b;transform:translateY(-3px);box-shadow:0 0 14px rgba(255,59,59,.2)}
.card .lbl{font-size:.72rem;color:#777;margin-bottom:8px;text-transform:uppercase;letter-spacing:1px}
.card .num{font-size:1.8rem;font-weight:bold;color:#ff3b3b}

table{width:100%;border-collapse:collapse;margin-top:8px}
th,td{padding:11px 12px;border-bottom:1px solid #1a1a1a;font-size:.87rem;text-align:left}
th{color:#ff3b3b;font-size:.78rem;text-transform:uppercase;letter-spacing:.5px}
td{color:#ccc}
tr:hover td{background:#111}

.tabs{display:flex;gap:8px;margin-bottom:18px;flex-wrap:wrap}
.tab{padding:7px 16px;border:1px solid #222;border-radius:20px;cursor:pointer;
     font-size:.82rem;color:#777;text-decoration:none;transition:.2s}
.tab:hover{border-color:#ff3b3b;color:#fff}
.tab.active{background:#ff3b3b;border-color:#ff3b3b;color:#fff}

.btn{background:#ff3b3b;border:none;color:#fff;padding:7px 14px;border-radius:6px;
     cursor:pointer;font-size:.83rem;font-weight:bold;transition:.2s}
.btn:hover{background:#cc0000}
.btn.green{background:#27ae60}.btn.green:hover{background:#1e8449}
.btn.gray{background:#333}.btn.gray:hover{background:#444}

input[type=text],input[type=password]{background:#1a1a1a;border:1px solid #2a2a2a;
  color:#fff;border-radius:6px;padding:8px 10px;font-size:.88rem;outline:none}
input:focus{border-color:#ff3b3b}

.badge-s{font-size:.7rem;padding:3px 9px;border-radius:10px;font-weight:bold;text-transform:uppercase}
.badge-s.pending{background:#2d1f00;color:#f5a623}
.badge-s.accepted{background:#0d2d1a;color:#27ae60}
.badge-s.declined{background:#2d0000;color:#ff8888}

.req{background:#111;border:1px solid #1a1a1a;border-radius:10px;padding:18px;
     margin-bottom:14px;transition:.2s}
.req:hover{border-color:#ff3b3b;box-shadow:0 0 10px rgba(255,59,59,.12)}
.req-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.req-id{font-size:.7rem;color:#555;background:#1a1a1a;padding:3px 8px;border-radius:4px}
.req-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;font-size:.87rem;color:#bbb}
.req-grid .amt{color:#27ae60;font-weight:bold}
.req-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px}
.req-actions form{display:flex;gap:6px;align-items:center}
.idpass-box{background:#0d1a2d;border:1px solid #1a3a5c;border-radius:6px;
            padding:8px 12px;font-size:.83rem;color:#4a90e2;margin-bottom:8px}
.empty{text-align:center;padding:60px;color:#333;font-size:1.1rem}

.setting-box{background:#111;border:1px solid #1a1a1a;border-radius:10px;
             padding:22px;margin-bottom:16px;max-width:500px}
.setting-box .stitle{color:#ff3b3b;font-weight:bold;margin-bottom:14px;font-size:.95rem}

@media(max-width:700px){.sidebar{display:none}.main{margin-left:0}.req-grid{grid-template-columns:1fr}}
</style>
<script>function go(u){location.href=u}</script>
</head>
<body>

<div class="sidebar">
  <div class="sidebar-logo">🔥 ADMIN PANEL</div>
  <a href="/admin/"              class="{{ 'active' if active=='dashboard' else '' }}">📊 Dashboard</a>
  <a href="/admin/payments"      class="{{ 'active' if active=='payments'  else '' }}">💳 Payments</a>
  <a href="/admin/registrations" class="{{ 'active' if active=='regs'      else '' }}">👤 Registrations</a>
  <a href="/admin/deposits"      class="{{ 'active' if active=='deposits'  else '' }}">💰 Deposits</a>
  <a href="/admin/subusers"      class="{{ 'active' if active=='subusers'  else '' }}">👥 Sub Users</a>
  <a href="/admin/settings"      class="{{ 'active' if active=='settings'  else '' }}">⚙ Settings</a>
  <div class="spacer"></div>
  <a href="/admin/logout" class="logout">🚪 Logout</a>
</div>

<div class="main">
  <div class="top-bar">
    <h2>{{ page_title }}</h2>
    <div class="top-badge">Admin Panel</div>
  </div>
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="flash {% if cat=='error' %}err{% endif %}">{{ msg }}</div>
    {% endfor %}
  {% endwith %}
  {{ content | safe }}
</div>
</body>
</html>
"""


# ── Auth routes ────────────────────────────────────────────

@flask_app.route("/admin/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect("/admin/")
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect("/admin/")
        error = "Wrong password. Try again."
    return render_template_string(LOGIN_HTML, error=error)


@flask_app.route("/admin/logout")
def logout():
    session.clear()
    return redirect("/admin/login")


# ── Dashboard ──────────────────────────────────────────────

@flask_app.route("/admin/")
@flask_app.route("/admin")
@login_required
def dashboard():
    today = datetime.date.today().isoformat()
    s = {
        "today_reg": db_conn.execute(
            "SELECT COUNT(*) FROM users WHERE date(created_at)=?", (today,)).fetchone()[0],
        "today_dep": db_conn.execute(
            "SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM users WHERE status='accepted' AND date(created_at)=?", (today,)).fetchone()[0],
        "total_users": db_conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "total_dep":   db_conn.execute(
            "SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM users WHERE status='accepted'").fetchone()[0],
        "pending":  db_conn.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0],
        "accepted": db_conn.execute("SELECT COUNT(*) FROM users WHERE status='accepted'").fetchone()[0],
        "declined": db_conn.execute("SELECT COUNT(*) FROM users WHERE status='declined'").fetchone()[0],
    }
    content = f"""
<div class="cards">
  <div class="card" onclick="go('/admin/registrations')">
    <div class="lbl">Today Registrations</div><div class="num">{s['today_reg']}</div></div>
  <div class="card" onclick="go('/admin/deposits')">
    <div class="lbl">Today Deposit</div><div class="num">₹{s['today_dep']}</div></div>
  <div class="card" onclick="go('/admin/registrations')">
    <div class="lbl">Total Users</div><div class="num">{s['total_users']}</div></div>
  <div class="card" onclick="go('/admin/deposits')">
    <div class="lbl">Total Deposit</div><div class="num">₹{s['total_dep']}</div></div>
</div>
<div class="cards">
  <div class="card" onclick="go('/admin/payments?f=pending')">
    <div class="lbl">⏳ Pending</div><div class="num" style="color:#f5a623">{s['pending']}</div></div>
  <div class="card" onclick="go('/admin/payments?f=accepted')">
    <div class="lbl">✅ Accepted</div><div class="num" style="color:#27ae60">{s['accepted']}</div></div>
  <div class="card" onclick="go('/admin/payments?f=declined')">
    <div class="lbl">❌ Declined</div><div class="num" style="color:#ff8888">{s['declined']}</div></div>
</div>
"""
    return render_template_string(BASE_HTML, page_title="Dashboard", active="dashboard", content=content)


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
        idpass_html = f'<div class="idpass-box">🎯 ID Sent: <strong>{u["id_pass"]}</strong></div>' if u["id_pass"] else ""

        if u["status"] == "pending":
            action = f"""
<div class="req-actions">
  <form method="post" action="/admin/accept/{u['id']}">
    <button class="btn green">✅ Accept</button>
  </form>
  <form method="post" action="/admin/decline/{u['id']}">
    <button class="btn gray">❌ Decline</button>
  </form>
</div>"""
        elif u["status"] == "accepted" and not u["id_pass"]:
            action = f"""
<div class="req-actions">
  <form method="post" action="/admin/sendid/{u['id']}" style="display:flex;gap:8px;flex-wrap:wrap;width:100%">
    <input type="text" name="idpass" placeholder="ID: xxx  Pass: xxx" required style="flex:1;min-width:180px">
    <button class="btn green">🎯 Send ID</button>
  </form>
</div>"""
        else:
            action = ""

        cards += f"""
<div class="req">
  <div class="req-hdr">
    <strong>💳 Payment Request</strong>
    <div style="display:flex;gap:8px;align-items:center">
      <span class="req-id">#{u['id']}</span>
      <span class="badge-s {u['status']}">{u['status']}</span>
    </div>
  </div>
  <div class="req-grid">
    <div>👤 <strong>{u['name']}</strong></div>
    <div>📱 {u['phone']}</div>
    <div>🌐 {u['site']} &nbsp;<span style="color:#555;font-size:.78rem">{(u['id_type'] or 'N/A').upper()}</span></div>
    <div class="amt">💰 ₹{u['amount']}</div>
    <div style="grid-column:1/-1;color:#555;font-size:.8rem">
      🔢 UTR: {u['utr'] or '—'} &nbsp;|&nbsp; 🕐 {str(u['created_at'])[:16] if u['created_at'] else '—'}
    </div>
  </div>
  {idpass_html}{action}
</div>"""

    if not rows:
        cards = '<div class="empty">No requests found 🙂</div>'

    content = f'<div class="tabs">{tabs}</div><div style="font-size:.75rem;color:#444;text-transform:uppercase;letter-spacing:2px;margin-bottom:14px">{len(rows)} request(s)</div>{cards}'
    return render_template_string(BASE_HTML, page_title="Payments", active="payments", content=content)


@flask_app.route("/admin/accept/<int:rid>", methods=["POST"])
@login_required
def accept(rid):
    row = db_conn.execute("SELECT * FROM users WHERE id=?", (rid,)).fetchone()
    if not row or row["status"] != "pending":
        flash("Not found or already processed.", "error")
        return redirect("/admin/payments")
    db_conn.execute("UPDATE users SET status='accepted' WHERE id=?", (rid,))
    db_conn.commit()
    send_tg(row["telegram_id"], "✅ *Sir, Payment Received!*\n\nPlease wait 2–5 minutes. We are processing your ID.")
    flash(f"✅ Request #{rid} accepted. Now send the ID from Accepted tab.")
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
        f"🎯 *Sir, your ID & Password:*\n\n`{idpass}`\n\n"
        f"🌐 Site: *{row['site']}*")
    send_tg(row["telegram_id"],
        "🔴 *LASER247 OFFICIAL SERVICE* 🔴\n\n⚡ Fast • Secure • Trusted\n\nFor support contact admin.")
    flash(f"🎯 ID sent to user for request #{rid}.")
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
        "❌ *Sir, Payment not received.*\n\nPlease check your UTR and try again with /start.")
    flash(f"❌ Request #{rid} declined.")
    return redirect("/admin/payments?f=pending")


# ── Registrations ──────────────────────────────────────────

@flask_app.route("/admin/registrations")
@login_required
def registrations():
    rows = db_conn.execute(
        "SELECT name, phone, site, id_type, created_at FROM users ORDER BY id DESC").fetchall()
    trs = "".join([
        f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['site']}</td>"
        f"<td>{(r['id_type'] or 'N/A').upper()}</td>"
        f"<td style='color:#555'>{str(r['created_at'])[:16]}</td></tr>"
        for r in rows
    ]) or "<tr><td colspan='5' style='color:#555;text-align:center;padding:40px'>No registrations yet</td></tr>"
    content = f"<table><tr><th>Name</th><th>Phone</th><th>Site</th><th>Type</th><th>Date</th></tr>{trs}</table>"
    return render_template_string(BASE_HTML, page_title="Registrations", active="regs", content=content)


# ── Deposits ───────────────────────────────────────────────

@flask_app.route("/admin/deposits")
@login_required
def deposits():
    rows = db_conn.execute(
        "SELECT name, phone, site, amount, created_at FROM users WHERE status='accepted' ORDER BY id DESC"
    ).fetchall()
    total = sum(float(r["amount"] or 0) for r in rows)
    trs = "".join([
        f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['site']}</td>"
        f"<td style='color:#27ae60;font-weight:bold'>₹{r['amount']}</td>"
        f"<td style='color:#555'>{str(r['created_at'])[:16]}</td></tr>"
        for r in rows
    ]) or "<tr><td colspan='5' style='color:#555;text-align:center;padding:40px'>No deposits yet</td></tr>"
    content = (
        f'<div style="color:#27ae60;font-size:1rem;margin-bottom:14px;font-weight:bold">Total: ₹{total}</div>'
        f"<table><tr><th>Name</th><th>Phone</th><th>Site</th><th>Amount</th><th>Date</th></tr>{trs}</table>"
    )
    return render_template_string(BASE_HTML, page_title="Deposits", active="deposits", content=content)


# ── Sub Users ──────────────────────────────────────────────

@flask_app.route("/admin/subusers", methods=["GET", "POST"])
@login_required
def subusers():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name = request.form.get("name", "").strip()
            pwd  = request.form.get("password", "").strip()
            if name:
                db_conn.execute(
                    "INSERT INTO subadmins (name, password) VALUES (?,?)", (name, pwd))
                db_conn.commit()
                flash(f"✅ Sub user '{name}' added.")
        elif action == "delete":
            db_conn.execute(
                "DELETE FROM subadmins WHERE id=?", (request.form.get("uid"),))
            db_conn.commit()
            flash("🗑️ Sub user removed.")
        return redirect("/admin/subusers")

    rows = db_conn.execute("SELECT * FROM subadmins ORDER BY id DESC").fetchall()
    trs = "".join([
        f"<tr><td>#{r['id']}</td><td><strong>{r['name']}</strong></td>"
        f"<td style='color:#4a90e2'>{r['password'] or '—'}</td>"
        f"<td style='color:#555'>{str(r['created_at'])[:16]}</td>"
        f"<td><form method='post' style='display:inline'>"
        f"<input type='hidden' name='action' value='delete'>"
        f"<input type='hidden' name='uid' value='{r['id']}'>"
        f"<button class='btn' style='font-size:.75rem;padding:4px 10px;background:#333'>🗑️</button></form></td></tr>"
        for r in rows
    ]) or "<tr><td colspan='5' style='color:#555;text-align:center;padding:40px'>No sub users added yet</td></tr>"

    content = f"""
<div style="max-width:640px">
  <div class="setting-box">
    <div class="stitle">➕ Add Sub User</div>
    <form method="post" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <input type="hidden" name="action" value="add">
      <input type="text" name="name" placeholder="Username" required style="flex:1;min-width:130px">
      <input type="text" name="password" placeholder="Password" style="flex:1;min-width:130px">
      <button class="btn">Add</button>
    </form>
  </div>
  <table>
    <tr><th>#</th><th>Username</th><th>Password</th><th>Added</th><th>Action</th></tr>
    {trs}
  </table>
</div>"""
    return render_template_string(BASE_HTML, page_title="Sub Users", active="subusers", content=content)


# ── Settings ───────────────────────────────────────────────

@flask_app.route("/admin/settings", methods=["GET", "POST"])
@login_required
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
<div class="setting-box">
  <div class="stitle">💳 UPI ID (Payment QR)</div>
  <div style="color:#777;font-size:.85rem;margin-bottom:14px">
    Current: <span style="color:#f5a623;font-weight:bold">{get_upi() or 'Not set'}</span>
  </div>
  <form method="post" style="display:flex;gap:10px;align-items:center">
    <input type="text" name="upi" placeholder="Enter new UPI ID (e.g. name@upi)" style="flex:1">
    <button class="btn">Update</button>
  </form>
</div>"""
    return render_template_string(BASE_HTML, page_title="Settings", active="settings", content=content)


# ── Catch all ──────────────────────────────────────────────

@flask_app.errorhandler(404)
def not_found(e):
    return redirect("/admin/login")


@flask_app.route("/")
@flask_app.route("/<path:path>")
def catch_all(path=""):
    return redirect("/admin/login")


# ═══════════════════════════════════════════════════════════
#  TELEGRAM BOT HANDLERS
# ═══════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🆕 New ID",  callback_data="type_new")],
        [InlineKeyboardButton("🎁 Demo ID", callback_data="type_demo")],
    ]
    await update.message.reply_text(
        "🙏 *Welcome Sir!*\n\nPlease choose your ID type:",
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
            "🌐 *Select Site Sir:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )
    elif data.startswith("site_"):
        context.user_data["site"] = data[5:]
        context.user_data["step"] = "name"
        await q.message.reply_text("👤 *Sir, please enter your full name:*", parse_mode="Markdown")


async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    step = context.user_data.get("step")

    if not step:
        await update.message.reply_text("Please type /start to begin.")
        return

    if step == "name":
        context.user_data["name"] = text
        context.user_data["step"] = "phone"
        await update.message.reply_text("📱 *Sir, enter your phone number:*", parse_mode="Markdown")

    elif step == "phone":
        context.user_data["phone"] = text
        context.user_data["step"] = "amount"
        await update.message.reply_text("💰 *Sir, enter deposit amount (₹):*", parse_mode="Markdown")

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
                    f"💳 *Sir, please pay ₹{text}*\n\n"
                    f"UPI ID: `{upi}`\n\n"
                    f"📸 After payment, send your *UTR number* or *screenshot*."
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
            "⏳ *Sir, your request is submitted!*\n\nPlease wait 2–5 minutes. We will send your ID shortly. 🙏",
            parse_mode="Markdown",
        )
        send_tg(ADMIN_CHAT_ID,
            f"🔔 *New Payment Request #{req_id}*\n\n"
            f"👤 Name: {ud.get('name')} | 📱 Phone: {ud.get('phone')}\n"
            f"🌐 Site: {ud.get('site')} ({ud.get('id_type','new').upper()})\n"
            f"💰 Amount: ₹{ud.get('amount')} | 🔢 UTR: {text}\n\n"
            f"👉 Go to admin panel → Payments to process."
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
            "⏳ *Sir, screenshot received!*\n\nPlease wait 2–5 minutes. We will send your ID shortly. 🙏",
            parse_mode="Markdown",
        )
        send_tg(ADMIN_CHAT_ID,
            f"🔔 *New Payment Request #{req_id}* (Screenshot)\n\n"
            f"👤 Name: {ud.get('name')} | 📱 Phone: {ud.get('phone')}\n"
            f"🌐 Site: {ud.get('site')} ({ud.get('id_type','new').upper()})\n"
            f"💰 Amount: ₹{ud.get('amount')}\n\n"
            f"👉 Go to admin panel → Payments to process."
        )
    else:
        await update.message.reply_text("Please type /start to begin.")


# ═══════════════════════════════════════════════════════════
#  MAIN — Flask in thread, Bot in main thread
# ═══════════════════════════════════════════════════════════

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    print("✅ Admin panel started")

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CallbackQueryHandler(btn_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    print("✅ Telegram bot started — polling...")
    application.run_polling(drop_pending_updates=True)
