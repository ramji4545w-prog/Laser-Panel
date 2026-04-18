import os
import sqlite3
import datetime
import requests
from functools import wraps
from flask import (
    Flask, render_template_string, redirect,
    flash, request, session, url_for
)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "changeme-set-session-secret")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            name TEXT,
            phone TEXT,
            site TEXT,
            id_type TEXT,
            amount TEXT,
            utr TEXT,
            id_pass TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            upi TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subadmins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN id_pass TEXT")
    except Exception:
        pass
    conn.commit()


init_db()


def get_upi():
    row = get_db().execute("SELECT upi FROM settings WHERE id=1").fetchone()
    return row["upi"] if row else os.environ.get("UPI_ID", "")


def send_telegram(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
    except Exception:
        pass


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated


# ─────────────────────── TEMPLATES ────────────────────────────────

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin Login</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #0b0b0b; color: #f0f0f0;
  font-family: 'Segoe UI', sans-serif;
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
}
.box {
  background: #111; border: 1px solid #222; border-top: 3px solid #ff3b3b;
  border-radius: 12px; padding: 40px 36px; width: 100%; max-width: 360px;
}
h1 { color: #ff3b3b; font-size: 1.4rem; margin-bottom: 6px; }
p { color: #555; font-size: 0.82rem; margin-bottom: 28px; }
label { display: block; font-size: 0.75rem; color: #666; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
input[type="password"] {
  width: 100%; background: #1a1a1a; border: 1px solid #333; border-radius: 8px;
  color: #f0f0f0; font-size: 0.95rem; padding: 11px 14px; margin-bottom: 20px; outline: none;
}
input:focus { border-color: #ff3b3b; }
button { width: 100%; background: #ff3b3b; color: white; border: none; border-radius: 8px; padding: 12px; font-size: 0.95rem; font-weight: bold; cursor: pointer; }
button:hover { background: #cc0000; }
.err { background: #2d0000; border: 1px solid #ff3b3b; color: #ff8888; border-radius: 8px; padding: 10px 14px; font-size: 0.82rem; margin-bottom: 18px; }
</style>
</head>
<body>
<div class="box">
  <h1>🔥 Admin Login</h1>
  <p>Payment Requests Dashboard</p>
  {% if error %}<div class="err">❌ {{ error }}</div>{% endif %}
  <form method="post" action="/admin/login">
    <label>Password</label>
    <input type="password" name="password" placeholder="Enter admin password" autocomplete="current-password" autofocus>
    <button type="submit">Login →</button>
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
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>🔥 {{ page_title }}</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { display: flex; font-family: 'Segoe UI', sans-serif; background: #0b0b0b; color: #fff; min-height: 100vh; }

.sidebar {
  width: 220px; background: #111; height: 100vh;
  border-right: 1px solid #1f1f1f; position: fixed; top: 0; left: 0;
  display: flex; flex-direction: column;
}
.sidebar-logo {
  color: #ff3b3b; text-align: center; font-size: 1.3rem; font-weight: bold;
  padding: 24px 16px 18px; border-bottom: 1px solid #1f1f1f; letter-spacing: 1px;
}
.sidebar a {
  display: flex; align-items: center; gap: 10px;
  padding: 13px 20px; color: #aaa; text-decoration: none;
  font-size: 0.9rem; transition: 0.2s; border-left: 3px solid transparent;
}
.sidebar a:hover { background: #1a1a1a; color: #fff; }
.sidebar a.active { background: #1a1a1a; color: #ff3b3b; border-left-color: #ff3b3b; }
.sidebar .spacer { flex: 1; }
.sidebar a.logout { color: #555; margin-top: 4px; border-top: 1px solid #1f1f1f; }
.sidebar a.logout:hover { color: #ff3b3b; }

.main { margin-left: 220px; flex: 1; padding: 28px; }

.top-bar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #1a1a1a;
}
.top-bar h2 { color: #ff3b3b; font-size: 1.3rem; }
.top-bar .badge { font-size: 0.78rem; color: #555; background: #1a1a1a; padding: 5px 12px; border-radius: 20px; }

.flash { background: #0d2d1a; border-left: 3px solid #27ae60; color: #27ae60; padding: 10px 16px; border-radius: 6px; margin-bottom: 18px; font-size: 0.85rem; }
.flash.err { background: #2d0000; border-left-color: #ff3b3b; color: #ff8888; }

.cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 24px;
}
.card {
  background: #111; padding: 18px 16px; border-radius: 10px;
  border: 1px solid #1f1f1f; text-align: center; cursor: pointer; transition: 0.25s;
}
.card:hover { border-color: #ff3b3b; transform: translateY(-3px); box-shadow: 0 0 14px rgba(255,59,59,0.25); }
.card .lbl { font-size: 0.75rem; color: #777; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; }
.card .num { font-size: 1.8rem; font-weight: bold; color: #ff3b3b; }

table { width: 100%; border-collapse: collapse; margin-top: 8px; }
th, td { padding: 11px 12px; border-bottom: 1px solid #1a1a1a; font-size: 0.88rem; text-align: left; }
th { color: #ff3b3b; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px; }
td { color: #ccc; }
tr:hover td { background: #111; }

.tabs { display: flex; gap: 8px; margin-bottom: 18px; flex-wrap: wrap; }
.tab {
  padding: 7px 16px; border: 1px solid #222; border-radius: 20px;
  cursor: pointer; font-size: 0.82rem; color: #777; text-decoration: none; transition: 0.2s;
}
.tab:hover { border-color: #ff3b3b; color: #fff; }
.tab.active { background: #ff3b3b; border-color: #ff3b3b; color: #fff; }

.btn { background: #ff3b3b; border: none; color: #fff; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 0.82rem; transition: 0.2s; }
.btn:hover { background: #cc0000; }
.btn.green { background: #27ae60; }
.btn.green:hover { background: #1e8449; }
.btn.gray { background: #333; }
.btn.gray:hover { background: #444; }

input[type="text"], input[type="password"] {
  background: #1a1a1a; border: 1px solid #2a2a2a; color: #fff;
  border-radius: 6px; padding: 8px 10px; font-size: 0.88rem; outline: none;
}
input:focus { border-color: #ff3b3b; }

.badge-status { font-size: 0.72rem; padding: 3px 9px; border-radius: 10px; font-weight: bold; text-transform: uppercase; }
.badge-status.pending { background: #2d1f00; color: #f5a623; }
.badge-status.accepted { background: #0d2d1a; color: #27ae60; }
.badge-status.declined { background: #2d0000; color: #ff8888; }

.upi-form { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.upi-form input { flex: 1; min-width: 200px; }

.req-card {
  background: #111; border: 1px solid #1f1f1f; border-radius: 10px;
  padding: 18px; margin-bottom: 14px; transition: 0.2s;
}
.req-card:hover { border-color: #ff3b3b; box-shadow: 0 0 10px rgba(255,59,59,0.15); }
.req-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.req-card-id { font-size: 0.72rem; color: #555; background: #1a1a1a; padding: 3px 8px; border-radius: 4px; }
.req-info { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; font-size: 0.88rem; color: #bbb; }
.req-info .amount { color: #27ae60; font-weight: bold; }
.req-actions { display: flex; gap: 8px; align-items: flex-start; flex-wrap: wrap; margin-top: 8px; }
.req-actions form { display: flex; gap: 6px; align-items: center; }
.idpass-sent { color: #4a90e2; font-size: 0.82rem; margin-bottom: 8px; }
.empty { text-align: center; padding: 60px; color: #333; }

@media(max-width: 700px) {
  .sidebar { display: none; }
  .main { margin-left: 0; }
  .req-info { grid-template-columns: 1fr; }
}
</style>
<script>
function go(u){ location.href = u; }
</script>
</head>
<body>

<div class="sidebar">
  <div class="sidebar-logo">🔥 ADMIN</div>
  <a href="/admin/" class="{{ 'active' if active == 'dashboard' else '' }}">📊 Dashboard</a>
  <a href="/admin/registrations" class="{{ 'active' if active == 'registrations' else '' }}">👤 Registrations</a>
  <a href="/admin/deposits" class="{{ 'active' if active == 'deposits' else '' }}">💰 Deposits</a>
  <a href="/admin/payments" class="{{ 'active' if active == 'payments' else '' }}">💳 Payments</a>
  <a href="/admin/subusers" class="{{ 'active' if active == 'subusers' else '' }}">👥 Sub Users</a>
  <a href="/admin/settings" class="{{ 'active' if active == 'settings' else '' }}">⚙ Settings</a>
  <div class="spacer"></div>
  <a href="/admin/logout" class="logout">🚪 Logout</a>
</div>

<div class="main">
  <div class="top-bar">
    <h2>{{ page_title }}</h2>
    <div class="badge">Admin</div>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="flash {% if cat == 'error' %}err{% endif %}">{{ msg }}</div>
    {% endfor %}
  {% endwith %}

  {{ content | safe }}
</div>

</body>
</html>
"""


# ─────────────────────── ROUTES ───────────────────────────────────

@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect("/admin/")
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect("/admin/")
        error = "Wrong password. Please try again."
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect("/admin/login")


@app.route("/admin/")
@app.route("/admin")
@login_required
def dashboard():
    db = get_db()
    today = datetime.date.today().isoformat()
    stats = {
        "today_reg": db.execute(
            "SELECT COUNT(*) FROM users WHERE date(created_at)=?", (today,)
        ).fetchone()[0],
        "today_dep": db.execute(
            "SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM users WHERE status='accepted' AND date(created_at)=?", (today,)
        ).fetchone()[0],
        "total_users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "total_dep": db.execute(
            "SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM users WHERE status='accepted'"
        ).fetchone()[0],
        "pending": db.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0],
        "accepted": db.execute("SELECT COUNT(*) FROM users WHERE status='accepted'").fetchone()[0],
        "declined": db.execute("SELECT COUNT(*) FROM users WHERE status='declined'").fetchone()[0],
    }

    content = f"""
<div class="cards">
  <div class="card" onclick="go('/admin/registrations')">
    <div class="lbl">Today Reg</div><div class="num">{stats['today_reg']}</div>
  </div>
  <div class="card" onclick="go('/admin/deposits')">
    <div class="lbl">Today Deposit</div><div class="num">₹{stats['today_dep']}</div>
  </div>
  <div class="card" onclick="go('/admin/registrations')">
    <div class="lbl">Total Users</div><div class="num">{stats['total_users']}</div>
  </div>
  <div class="card" onclick="go('/admin/deposits')">
    <div class="lbl">Total Deposit</div><div class="num">₹{stats['total_dep']}</div>
  </div>
</div>

<div class="cards" style="margin-top:0">
  <div class="card" onclick="go('/admin/payments?f=pending')">
    <div class="lbl">⏳ Pending</div><div class="num" style="color:#f5a623">{stats['pending']}</div>
  </div>
  <div class="card" onclick="go('/admin/payments?f=accepted')">
    <div class="lbl">✅ Accepted</div><div class="num" style="color:#27ae60">{stats['accepted']}</div>
  </div>
  <div class="card" onclick="go('/admin/payments?f=declined')">
    <div class="lbl">❌ Declined</div><div class="num" style="color:#ff8888">{stats['declined']}</div>
  </div>
</div>
"""
    return render_template_string(BASE_HTML, page_title="Dashboard", active="dashboard", content=content)


@app.route("/admin/registrations")
@login_required
def registrations():
    rows = get_db().execute(
        "SELECT name, phone, site, id_type, created_at FROM users ORDER BY id DESC"
    ).fetchall()

    rows_html = "".join([
        f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['site']}</td>"
        f"<td>{(r['id_type'] or 'N/A').upper()}</td><td>{str(r['created_at'])[:16]}</td></tr>"
        for r in rows
    ]) or "<tr><td colspan='5' style='color:#555;text-align:center'>No registrations yet</td></tr>"

    content = f"""
<table>
  <tr><th>Name</th><th>Phone</th><th>Site</th><th>Type</th><th>Registered</th></tr>
  {rows_html}
</table>
"""
    return render_template_string(BASE_HTML, page_title="Registrations", active="registrations", content=content)


@app.route("/admin/deposits")
@login_required
def deposits():
    rows = get_db().execute(
        "SELECT name, phone, site, amount, created_at FROM users WHERE status='accepted' ORDER BY id DESC"
    ).fetchall()

    rows_html = "".join([
        f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['site']}</td>"
        f"<td style='color:#27ae60;font-weight:bold'>₹{r['amount']}</td><td>{str(r['created_at'])[:16]}</td></tr>"
        for r in rows
    ]) or "<tr><td colspan='5' style='color:#555;text-align:center'>No accepted deposits yet</td></tr>"

    content = f"""
<table>
  <tr><th>Name</th><th>Phone</th><th>Site</th><th>Amount</th><th>Time</th></tr>
  {rows_html}
</table>
"""
    return render_template_string(BASE_HTML, page_title="Deposits", active="deposits", content=content)


@app.route("/admin/payments")
@login_required
def payments():
    f = request.args.get("f", "pending")
    db = get_db()

    if f == "all":
        users = db.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    else:
        users = db.execute("SELECT * FROM users WHERE status=? ORDER BY id DESC", (f,)).fetchall()

    tabs = ""
    for label, key in [("⏳ Pending", "pending"), ("✅ Accepted", "accepted"), ("❌ Declined", "declined"), ("All", "all")]:
        active_cls = "active" if f == key else ""
        tabs += f'<a class="tab {active_cls}" href="/admin/payments?f={key}">{label}</a>'

    cards = ""
    for u in users:
        idpass_html = f'<div class="idpass-sent">🎯 ID Sent: <strong>{u["id_pass"]}</strong></div>' if u["id_pass"] else ""

        if u["status"] == "pending":
            action_html = f"""
<div class="req-actions">
  <form method="post" action="/admin/accept/{u['id']}">
    <button type="submit" class="btn green">✅ Accept</button>
  </form>
  <form method="post" action="/admin/decline/{u['id']}">
    <button type="submit" class="btn gray">❌ Decline</button>
  </form>
</div>
"""
        elif u["status"] == "accepted" and not u["id_pass"]:
            action_html = f"""
<div class="req-actions" style="margin-top:10px">
  <form method="post" action="/admin/sendid/{u['id']}" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <input type="text" name="idpass" placeholder="Enter ID & Password to send" required autocomplete="off" style="flex:1;min-width:200px">
    <button type="submit" class="btn green">🎯 Send ID</button>
  </form>
</div>
"""
        else:
            action_html = ""

        cards += f"""
<div class="req-card">
  <div class="req-card-header">
    <strong>💰 Payment Request</strong>
    <div style="display:flex;gap:8px;align-items:center">
      <span class="req-card-id">#{u['id']}</span>
      <span class="badge-status {u['status']}">{u['status']}</span>
    </div>
  </div>
  <div class="req-info">
    <div>👤 {u['name']}</div>
    <div>📱 {u['phone']}</div>
    <div>🌐 {u['site']} ({(u['id_type'] or 'N/A').upper()})</div>
    <div class="amount">💰 ₹{u['amount']}</div>
    <div style="grid-column:1/-1;color:#555;font-size:0.82rem">🔢 UTR: {u['utr'] or 'N/A'} &nbsp;|&nbsp; 🕐 {str(u['created_at'])[:16] if u['created_at'] else ''}</div>
  </div>
  {idpass_html}
  {action_html}
</div>
"""

    if not users:
        cards = '<div class="empty">No requests found.</div>'

    content = f"""
<div class="tabs">{tabs}</div>
<div style="font-size:0.78rem;color:#444;text-transform:uppercase;letter-spacing:2px;margin-bottom:14px">{len(users)} request(s)</div>
{cards}
"""
    return render_template_string(BASE_HTML, page_title="Payments", active="payments", content=content)


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        new_upi = request.form.get("upi", "").strip()
        if not new_upi:
            flash("UPI ID cannot be empty.", "error")
        else:
            db = get_db()
            db.execute("DELETE FROM settings")
            db.execute("INSERT INTO settings (id, upi) VALUES (1, ?)", (new_upi,))
            db.commit()
            flash(f"✅ UPI ID updated to: {new_upi}")
        return redirect("/admin/settings")

    content = f"""
<div style="max-width:500px">
  <div style="background:#111;border:1px solid #1f1f1f;border-radius:10px;padding:24px;margin-bottom:16px">
    <div style="color:#ff3b3b;font-weight:bold;margin-bottom:14px">💳 UPI ID</div>
    <div style="color:#777;font-size:0.85rem;margin-bottom:12px">Current: <span style="color:#f5a623">{get_upi() or 'Not set'}</span></div>
    <form method="post" class="upi-form">
      <input type="text" name="upi" placeholder="Enter new UPI ID (e.g. name@upi)" autocomplete="off">
      <button class="btn">Update</button>
    </form>
  </div>
</div>
"""
    return render_template_string(BASE_HTML, page_title="Settings", active="settings", content=content)


@app.route("/admin/upi", methods=["POST"])
@login_required
def update_upi():
    new_upi = request.form.get("upi", "").strip()
    if not new_upi:
        flash("UPI ID cannot be empty.", "error")
        return redirect("/admin/settings")
    db = get_db()
    db.execute("DELETE FROM settings")
    db.execute("INSERT INTO settings (id, upi) VALUES (1, ?)", (new_upi,))
    db.commit()
    flash(f"✅ UPI ID updated to: {new_upi}")
    return redirect("/admin/settings")


@app.route("/admin/accept/<int:req_id>", methods=["POST"])
@login_required
def accept(req_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (req_id,)).fetchone()
    if not row:
        flash("Request not found.", "error")
        return redirect("/admin/payments")
    if row["status"] != "pending":
        flash(f"Request #{req_id} is already {row['status']}.", "error")
        return redirect("/admin/payments")

    db.execute("UPDATE users SET status='accepted' WHERE id=?", (req_id,))
    db.commit()

    send_telegram(row["telegram_id"], "✅ Sir, Payment Received!\nPlease wait 5 minutes for your ID.")

    flash(f"✅ Request #{req_id} accepted — now send the ID from the Accepted tab.")
    return redirect("/admin/payments?f=accepted")


@app.route("/admin/sendid/<int:req_id>", methods=["POST"])
@login_required
def sendid(req_id):
    idpass = request.form.get("idpass", "").strip()
    if not idpass:
        flash("Please enter the ID & Password.", "error")
        return redirect("/admin/payments?f=accepted")

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (req_id,)).fetchone()
    if not row:
        flash("Request not found.", "error")
        return redirect("/admin/payments?f=accepted")

    db.execute("UPDATE users SET id_pass=? WHERE id=?", (idpass, req_id))
    db.commit()

    chat_id = row["telegram_id"]
    send_telegram(chat_id, f"🎯 Sir, Your ID & Password:\n`{idpass}`")
    send_telegram(chat_id, "🔴 *LASER247 OFFICIAL SERVICE* 🔴")

    flash(f"🎯 ID sent to user for request #{req_id}.")
    return redirect("/admin/payments?f=accepted")


@app.route("/admin/decline/<int:req_id>", methods=["POST"])
@login_required
def decline(req_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (req_id,)).fetchone()
    if not row:
        flash("Request not found.", "error")
        return redirect("/admin/payments")
    if row["status"] != "pending":
        flash(f"Request #{req_id} is already {row['status']}.", "error")
        return redirect("/admin/payments")

    db.execute("UPDATE users SET status='declined' WHERE id=?", (req_id,))
    db.commit()

    send_telegram(
        row["telegram_id"],
        "❌ Sir, Payment not received.\nPlease contact support or try again with /start."
    )

    flash(f"❌ Request #{req_id} declined and user notified.")
    return redirect("/admin/payments?f=pending")


@app.route("/admin/subusers", methods=["GET", "POST"])
@login_required
def subusers():
    db = get_db()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name = request.form.get("name", "").strip()
            if name:
                db.execute("INSERT INTO subadmins (name) VALUES (?)", (name,))
                db.commit()
                flash(f"✅ Sub user '{name}' added.")
        elif action == "delete":
            uid = request.form.get("uid")
            db.execute("DELETE FROM subadmins WHERE id=?", (uid,))
            db.commit()
            flash("🗑️ Sub user removed.")
        return redirect("/admin/subusers")

    rows = db.execute("SELECT * FROM subadmins ORDER BY id DESC").fetchall()

    rows_html = "".join([
        f"""<tr>
          <td>#{r['id']}</td>
          <td>{r['name']}</td>
          <td style='color:#555;font-size:0.82rem'>{str(r['created_at'])[:16]}</td>
          <td>
            <form method='post' style='display:inline'>
              <input type='hidden' name='action' value='delete'>
              <input type='hidden' name='uid' value='{r["id"]}'>
              <button class='btn' style='font-size:0.78rem;padding:4px 10px'>🗑️ Remove</button>
            </form>
          </td>
        </tr>"""
        for r in rows
    ]) or "<tr><td colspan='4' style='color:#555;text-align:center'>No sub users added yet</td></tr>"

    content = f"""
<div style="max-width:600px">
  <div style="background:#111;border:1px solid #1f1f1f;border-radius:10px;padding:20px;margin-bottom:20px">
    <div style="color:#ff3b3b;font-weight:bold;margin-bottom:14px">➕ Add Sub User</div>
    <form method="post" style="display:flex;gap:10px;align-items:center">
      <input type="hidden" name="action" value="add">
      <input type="text" name="name" placeholder="Enter sub user name" required autocomplete="off" style="flex:1">
      <button class="btn">Add</button>
    </form>
  </div>

  <table>
    <tr><th>#</th><th>Name</th><th>Added</th><th>Action</th></tr>
    {rows_html}
  </table>
</div>
"""
    return render_template_string(BASE_HTML, page_title="Sub Users", active="subusers", content=content)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
