import os
import sqlite3
import datetime
import requests
from functools import wraps
from flask import (
    Flask, render_template_string, redirect,
    flash, request, session
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
    # Add id_pass column if it doesn't exist (migration)
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


# ─────────────────────── HTML TEMPLATES ───────────────────────────

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin Login</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0a0a0a; color: #f0f0f0;
    font-family: 'Segoe UI', Arial, sans-serif;
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
  }
  .login-box {
    background: #111; border: 1px solid #222; border-top: 3px solid #cc0000;
    border-radius: 10px; padding: 40px 36px; width: 100%; max-width: 360px;
  }
  .login-box h1 { color: #ff4444; font-size: 1.4rem; margin-bottom: 6px; letter-spacing: 1px; }
  .login-box p { color: #555; font-size: 0.82rem; margin-bottom: 28px; }
  label { display: block; font-size: 0.78rem; color: #666; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
  input[type="password"] {
    width: 100%; background: #1a1a1a; border: 1px solid #333; border-radius: 6px;
    color: #f0f0f0; font-size: 0.95rem; padding: 11px 14px; margin-bottom: 20px; outline: none;
  }
  input[type="password"]:focus { border-color: #cc0000; }
  button { width: 100%; background: #cc0000; color: white; border: none; border-radius: 6px; padding: 12px; font-size: 0.95rem; font-weight: bold; cursor: pointer; }
  button:hover { background: #ff2222; }
  .error { background: #2d0000; border: 1px solid #cc0000; color: #ff6666; border-radius: 6px; padding: 10px 14px; font-size: 0.82rem; margin-bottom: 18px; }
</style>
</head>
<body>
<div class="login-box">
  <h1>🔥 Admin Login</h1>
  <p>Payment Requests Dashboard</p>
  {% if error %}<div class="error">❌ {{ error }}</div>{% endif %}
  <form method="post" action="/admin/login">
    <label>Password</label>
    <input type="password" name="password" placeholder="Enter admin password" autocomplete="current-password" autofocus>
    <button type="submit">Login →</button>
  </form>
</div>
</body>
</html>
"""

MAIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🔥 Admin Panel</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    background: #0a0a0a;
    color: white;
    font-family: 'Segoe UI', sans-serif;
}

.header {
    padding: 18px 20px;
    font-size: 26px;
    color: red;
    border-bottom: 1px solid #222;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.logout-btn {
    font-size: 13px;
    color: #888;
    background: #1a1a1a;
    border: 1px solid #333;
    border-radius: 6px;
    padding: 6px 14px;
    text-decoration: none;
    transition: 0.2s;
}
.logout-btn:hover { color: red; border-color: red; }

.flash { background: #0d2d1a; border-left: 3px solid #27ae60; color: #27ae60; padding: 10px 20px; font-size: 0.85rem; }
.flash.err { background: #2d0000; border-left-color: red; color: #ff6666; }

.cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 15px;
    padding: 20px;
}
.card {
    background: #111;
    padding: 20px;
    border-radius: 12px;
    border: 1px solid #222;
    text-align: center;
    transition: 0.3s;
}
.card:hover {
    transform: translateY(-5px);
    border-color: red;
    box-shadow: 0 0 15px red;
}
.card .label { font-size: 0.82rem; color: #888; margin-bottom: 6px; }
.card h2 { color: red; font-size: 1.8rem; margin: 6px 0; }

.container { padding: 0 20px 30px; }

.box {
    background: #111;
    padding: 20px;
    margin-bottom: 18px;
    border-radius: 12px;
    border: 1px solid #222;
    transition: 0.3s;
}
.box:hover {
    border-color: red;
    box-shadow: 0 0 10px red;
}

.title { color: red; margin-bottom: 12px; font-size: 1rem; font-weight: bold; }

.tabs {
    display: flex;
    gap: 0;
    padding: 0 20px;
    border-bottom: 1px solid #1a1a1a;
    margin-bottom: 18px;
}
.tab {
    padding: 10px 18px;
    font-size: 0.82rem;
    text-decoration: none;
    color: #555;
    border-bottom: 2px solid transparent;
    transition: 0.15s;
}
.tab.active { color: red; border-bottom-color: red; }
.tab:hover { color: #ccc; }

.section-label { padding: 0 20px 10px; font-size: 0.78rem; color: #444; text-transform: uppercase; letter-spacing: 2px; }

button {
    background: linear-gradient(45deg, red, darkred);
    color: white;
    border: none;
    padding: 10px 15px;
    margin-top: 8px;
    border-radius: 8px;
    cursor: pointer;
    transition: 0.3s;
    font-size: 0.9rem;
    font-weight: bold;
}
button:hover {
    transform: scale(1.05);
    box-shadow: 0 0 10px red;
}
button.btn-approve {
    background: linear-gradient(45deg, #27ae60, #1e8449);
    width: 100%;
}
button.btn-approve:hover { box-shadow: 0 0 10px #27ae60; }
button.btn-reject { width: 100%; }

input[type="text"], input[type="password"] {
    width: 100%;
    padding: 10px;
    margin-top: 8px;
    border-radius: 8px;
    border: 1px solid #333;
    background: #222;
    color: white;
    font-size: 0.9rem;
    outline: none;
    transition: 0.2s;
}
input:focus { border-color: red; }

.user-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-bottom: 10px;
    font-size: 0.9rem;
    color: #ccc;
}
.user-grid .amount { color: #27ae60; font-weight: bold; }

.badge { font-size: 0.7rem; padding: 3px 10px; border-radius: 10px; font-weight: bold; text-transform: uppercase; }
.badge.pending { background: #2d1f00; color: #f5a623; }
.badge.accepted { background: #0d2d1a; color: #27ae60; }
.badge.declined { background: #2d0000; color: #ff6666; }
.badge.approved { background: #0d2d1a; color: #27ae60; }
.badge.rejected { background: #2d0000; color: #ff6666; }

.req-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.req-id { font-size: 0.72rem; color: #555; background: #1a1a1a; padding: 3px 8px; border-radius: 4px; }

.idpass-sent { color: #4a90e2; font-size: 0.85rem; margin: 6px 0; }

.actions { display: flex; gap: 8px; }
.actions form { flex: 1; }

.empty { text-align: center; padding: 60px; color: #333; font-size: 1rem; }

@media(max-width: 600px) {
    .user-grid { grid-template-columns: 1fr; }
    .cards { grid-template-columns: 1fr 1fr; }
}
</style>
</head>
<body>

<div class="header">
  🔥 ADMIN DASHBOARD
  <a class="logout-btn" href="/admin/logout">Logout</a>
</div>

{% with messages = get_flashed_messages(with_categories=true) %}
  {% for cat, msg in messages %}
    <div class="flash {% if cat == 'error' %}err{% endif %}">{{ msg }}</div>
  {% endfor %}
{% endwith %}

<div class="cards">
  <div class="card"><div class="label">Today Registration</div><h2>{{ stats.today_reg }}</h2></div>
  <div class="card"><div class="label">Today Deposit</div><h2>₹{{ stats.today_dep }}</h2></div>
  <div class="card"><div class="label">Total Users</div><h2>{{ stats.total_users }}</h2></div>
  <div class="card"><div class="label">Total Deposit</div><h2>₹{{ stats.total_dep }}</h2></div>
</div>

<div class="container">

  <div class="box">
    <div class="title">💳 Change UPI &nbsp;<small style="color:#555;font-weight:normal;font-size:0.8rem">Current: {{ current_upi or 'Not set' }}</small></div>
    <form method="post" action="/admin/upi" style="display:flex;gap:10px;align-items:flex-end">
      <div style="flex:1">
        <input type="text" name="upi" placeholder="Enter new UPI ID (e.g. name@upi)" autocomplete="off" style="margin-top:0">
      </div>
      <button type="submit" style="margin-top:0;white-space:nowrap">Update UPI</button>
    </form>
  </div>

  <div class="tabs">
    <a class="tab {% if filter == 'pending' %}active{% endif %}" href="/admin/?f=pending">⏳ Pending</a>
    <a class="tab {% if filter == 'accepted' %}active{% endif %}" href="/admin/?f=accepted">✅ Accepted</a>
    <a class="tab {% if filter == 'declined' %}active{% endif %}" href="/admin/?f=declined">❌ Declined</a>
    <a class="tab {% if filter == 'all' %}active{% endif %}" href="/admin/?f=all">All</a>
  </div>

  <div class="section-label">{{ users|length }} request(s)</div>

  {% if users %}
    {% for u in users %}
    <div class="box">
      <div class="req-header">
        <div class="title" style="margin-bottom:0">💰 Payment Request</div>
        <div style="display:flex;align-items:center;gap:8px">
          <span class="req-id">#{{ u['id'] }}</span>
          <span class="badge {{ u['status'] }}">{{ u['status'] }}</span>
        </div>
      </div>

      <div class="user-grid">
        <div>👤 {{ u['name'] }}</div>
        <div>📱 {{ u['phone'] }}</div>
        <div>🌐 {{ u['site'] }} ({{ (u['id_type'] or 'N/A')|upper }})</div>
        <div class="amount">💰 ₹{{ u['amount'] }}</div>
      </div>

      <p style="color:#888;font-size:0.85rem;margin-bottom:8px">🔢 UTR: {{ u['utr'] or 'N/A' }} &nbsp;|&nbsp; 🕐 {{ u['created_at'][:16] if u['created_at'] else '' }}</p>

      {% if u['id_pass'] %}
      <p class="idpass-sent">🎯 ID Sent: <strong>{{ u['id_pass'] }}</strong></p>
      {% endif %}

      {% if u['status'] == 'pending' %}
      <form method="post" action="/admin/accept/{{ u['id'] }}">
        <input type="text" name="idpass" placeholder="Enter ID & Password to send to user" required autocomplete="off">
        <div class="actions" style="margin-top:8px">
          <button class="btn-approve" type="submit">✅ Accept & Send ID</button>
        </div>
      </form>
      <div class="actions" style="margin-top:8px">
        <form method="post" action="/admin/decline/{{ u['id'] }}">
          <button class="btn-reject" type="submit">❌ Decline</button>
        </form>
      </div>
      {% endif %}
    </div>
    {% endfor %}
  {% else %}
  <div class="empty">No requests found.</div>
  {% endif %}

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
def home():
    f = request.args.get("f", "pending")
    db = get_db()
    today = datetime.date.today().isoformat()

    where = "" if f == "all" else f"WHERE status='{f}'"
    users = db.execute(f"SELECT * FROM users {where} ORDER BY id DESC").fetchall()

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
    }

    return render_template_string(MAIN_HTML, users=users, stats=stats, filter=f, current_upi=get_upi())


@app.route("/admin/accept/<int:req_id>", methods=["POST"])
@login_required
def accept(req_id):
    idpass = request.form.get("idpass", "").strip()
    if not idpass:
        flash("Please enter the ID & Password before accepting.", "error")
        return redirect("/admin/")

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (req_id,)).fetchone()
    if not row:
        flash("Request not found.", "error")
        return redirect("/admin/")
    if row["status"] != "pending":
        flash(f"Request #{req_id} is already {row['status']}.", "error")
        return redirect("/admin/")

    db.execute("UPDATE users SET status='accepted', id_pass=? WHERE id=?", (idpass, req_id))
    db.commit()

    chat_id = row["telegram_id"]
    send_telegram(chat_id, "✅ Sir, Payment Received!\nPlease wait 5 minutes.")
    send_telegram(chat_id, f"🎯 Sir, Your ID & Password:\n`{idpass}`")
    send_telegram(chat_id, "🔴 *LASER247 OFFICIAL SERVICE* 🔴")

    flash(f"✅ Request #{req_id} accepted — ID sent to user on Telegram.")
    return redirect("/admin/")


@app.route("/admin/decline/<int:req_id>", methods=["POST"])
@login_required
def decline(req_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (req_id,)).fetchone()
    if not row:
        flash("Request not found.", "error")
        return redirect("/admin/")
    if row["status"] != "pending":
        flash(f"Request #{req_id} is already {row['status']}.", "error")
        return redirect("/admin/")

    db.execute("UPDATE users SET status='declined' WHERE id=?", (req_id,))
    db.commit()

    send_telegram(
        row["telegram_id"],
        f"❌ Sir, Payment not received.\nPlease contact support or try again with /start."
    )

    flash(f"❌ Request #{req_id} declined and user notified.")
    return redirect("/admin/")


@app.route("/admin/upi", methods=["POST"])
@login_required
def update_upi():
    new_upi = request.form.get("upi", "").strip()
    if not new_upi:
        flash("UPI ID cannot be empty.", "error")
        return redirect("/admin/")

    db = get_db()
    db.execute("DELETE FROM settings")
    db.execute("INSERT INTO settings (id, upi) VALUES (1, ?)", (new_upi,))
    db.commit()

    flash(f"✅ UPI ID updated to: {new_upi}")
    return redirect("/admin/")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
