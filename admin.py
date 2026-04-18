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
<title>Admin Panel</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d0d0d; color: #f0f0f0; font-family: 'Segoe UI', Arial, sans-serif; min-height: 100vh; }

  header {
    background: linear-gradient(135deg, #1a0000, #3d0000);
    border-bottom: 2px solid #cc0000;
    padding: 16px 24px; display: flex; align-items: center; justify-content: space-between;
  }
  header h1 { font-size: 1.4rem; color: #ff4444; letter-spacing: 1px; }
  .logout-btn {
    background: #1a1a1a; color: #888; border: 1px solid #333;
    border-radius: 6px; padding: 6px 14px; font-size: 0.78rem; cursor: pointer;
    text-decoration: none; transition: all 0.15s;
  }
  .logout-btn:hover { color: #ff4444; border-color: #cc0000; }

  .stats-bar { display: flex; gap: 12px; padding: 18px 24px; flex-wrap: wrap; }
  .stat {
    background: #111; border: 1px solid #222; border-radius: 8px;
    padding: 14px 18px; flex: 1; min-width: 110px; text-align: center;
  }
  .stat .num { font-size: 1.7rem; font-weight: bold; }
  .stat .label { font-size: 0.72rem; color: #777; margin-top: 3px; text-transform: uppercase; letter-spacing: 1px; }
  .stat.today-reg .num { color: #4a90e2; }
  .stat.today-dep .num { color: #27ae60; }
  .stat.total-u .num { color: #f5a623; }
  .stat.total-dep .num { color: #cc0000; }

  .upi-bar {
    background: #111; border: 1px solid #333; border-radius: 8px;
    margin: 0 24px 18px; padding: 14px 18px; display: flex; align-items: center; gap: 12px;
  }
  .upi-bar label { font-size: 0.78rem; color: #666; text-transform: uppercase; letter-spacing: 1px; white-space: nowrap; }
  .upi-bar input {
    flex: 1; background: #1a1a1a; border: 1px solid #333; border-radius: 6px;
    color: #f0f0f0; font-size: 0.9rem; padding: 8px 12px; outline: none;
  }
  .upi-bar input:focus { border-color: #cc0000; }
  .upi-bar button { background: #cc0000; color: white; border: none; border-radius: 6px; padding: 8px 18px; font-size: 0.85rem; font-weight: bold; cursor: pointer; white-space: nowrap; }
  .upi-bar .current-upi { font-size: 0.8rem; color: #555; }
  .upi-bar .current-upi span { color: #f5a623; }

  .tabs { display: flex; padding: 0 24px; border-bottom: 1px solid #1a1a1a; }
  .tab { padding: 10px 18px; font-size: 0.82rem; text-decoration: none; color: #555; border-bottom: 2px solid transparent; transition: all 0.15s; }
  .tab.active { color: #ff4444; border-bottom-color: #cc0000; }
  .tab:hover { color: #ccc; }

  .section-title { padding: 10px 24px; font-size: 0.8rem; color: #444; text-transform: uppercase; letter-spacing: 2px; border-bottom: 1px solid #1a1a1a; }

  .flash { background: #1a3320; border: 1px solid #27ae60; color: #27ae60; padding: 10px 24px; font-size: 0.85rem; }
  .flash.err { background: #2d0000; border-color: #cc0000; color: #cc0000; }

  .cards { padding: 18px 24px; display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
  .card {
    background: #111; border: 1px solid #222; border-left: 4px solid #cc0000;
    border-radius: 8px; padding: 16px; transition: border-color 0.2s;
  }
  .card:hover { border-left-color: #ff4444; }
  .card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
  .req-id { font-size: 0.72rem; color: #555; background: #1a1a1a; padding: 3px 8px; border-radius: 4px; }
  .badge { font-size: 0.68rem; padding: 3px 10px; border-radius: 12px; font-weight: bold; text-transform: uppercase; }
  .badge.pending { background: #2d1f00; color: #f5a623; }
  .badge.approved { background: #0d2d1a; color: #27ae60; }
  .badge.rejected { background: #2d0000; color: #cc0000; }
  .badge.accepted { background: #0d2d1a; color: #27ae60; }
  .badge.declined { background: #2d0000; color: #cc0000; }
  .user-name { font-size: 1rem; font-weight: bold; margin-bottom: 8px; color: #fff; }
  .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; margin-bottom: 12px; }
  .info-item .key { color: #555; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.5px; }
  .info-item .val { color: #ccc; font-size: 0.82rem; margin-top: 1px; }
  .amount-val { color: #27ae60 !important; font-weight: bold; }
  .idpass-val { color: #4a90e2 !important; font-weight: bold; }

  .accept-form { margin-bottom: 8px; }
  .accept-form input[type="text"] {
    width: 100%; background: #1a1a1a; border: 1px solid #333; border-radius: 6px;
    color: #f0f0f0; font-size: 0.85rem; padding: 8px 10px; margin-bottom: 6px; outline: none;
  }
  .accept-form input:focus { border-color: #27ae60; }
  .actions { display: flex; gap: 8px; }
  .actions form { flex: 1; }
  button.btn-approve { width: 100%; background: #27ae60; color: white; border: none; border-radius: 6px; padding: 9px; font-size: 0.85rem; font-weight: bold; cursor: pointer; }
  button.btn-reject { width: 100%; background: #cc0000; color: white; border: none; border-radius: 6px; padding: 9px; font-size: 0.85rem; font-weight: bold; cursor: pointer; }
  button:hover { opacity: 0.85; }
  .empty { text-align: center; padding: 60px; color: #333; font-size: 1.1rem; }
</style>
</head>
<body>

<header>
  <h1>🔥 Admin Panel</h1>
  <a class="logout-btn" href="/admin/logout">Logout</a>
</header>

{% with messages = get_flashed_messages(with_categories=true) %}
  {% for cat, msg in messages %}
    <div class="flash {% if cat == 'error' %}err{% endif %}">{{ msg }}</div>
  {% endfor %}
{% endwith %}

<div class="stats-bar">
  <div class="stat today-reg"><div class="num">{{ stats.today_reg }}</div><div class="label">Today Reg</div></div>
  <div class="stat today-dep"><div class="num">₹{{ stats.today_dep }}</div><div class="label">Today Deposit</div></div>
  <div class="stat total-u"><div class="num">{{ stats.total_users }}</div><div class="label">Total Users</div></div>
  <div class="stat total-dep"><div class="num">₹{{ stats.total_dep }}</div><div class="label">Total Deposit</div></div>
</div>

<div class="upi-bar">
  <label>💳 UPI ID</label>
  <span class="current-upi">Current: <span>{{ current_upi or 'Not set' }}</span></span>
  <form method="post" action="/admin/upi" style="display:flex;gap:8px;flex:1">
    <input type="text" name="upi" placeholder="Enter new UPI ID (e.g. name@upi)" autocomplete="off">
    <button type="submit">Update</button>
  </form>
</div>

<div class="tabs">
  <a class="tab {% if filter == 'pending' %}active{% endif %}" href="/admin/?f=pending">⏳ Pending</a>
  <a class="tab {% if filter == 'accepted' %}active{% endif %}" href="/admin/?f=accepted">✅ Accepted</a>
  <a class="tab {% if filter == 'declined' %}active{% endif %}" href="/admin/?f=declined">❌ Declined</a>
  <a class="tab {% if filter == 'all' %}active{% endif %}" href="/admin/?f=all">All</a>
</div>

<div class="section-title">{{ users|length }} request(s)</div>

{% if users %}
<div class="cards">
  {% for u in users %}
  <div class="card">
    <div class="card-header">
      <span class="req-id">#{{ u['id'] }}</span>
      <span class="badge {{ u['status'] }}">{{ u['status'] }}</span>
    </div>
    <div class="user-name">{{ u['name'] }}</div>
    <div class="info-grid">
      <div class="info-item"><div class="key">Phone</div><div class="val">{{ u['phone'] }}</div></div>
      <div class="info-item"><div class="key">Site</div><div class="val">{{ u['site'] }}</div></div>
      <div class="info-item"><div class="key">Type</div><div class="val">{{ (u['id_type'] or 'N/A')|upper }}</div></div>
      <div class="info-item"><div class="key">UTR</div><div class="val">{{ u['utr'] or 'N/A' }}</div></div>
      <div class="info-item"><div class="key">Amount</div><div class="val amount-val">₹{{ u['amount'] }}</div></div>
      <div class="info-item"><div class="key">Date</div><div class="val">{{ u['created_at'][:16] if u['created_at'] else 'N/A' }}</div></div>
      {% if u['id_pass'] %}
      <div class="info-item" style="grid-column:1/-1"><div class="key">ID & Password Sent</div><div class="val idpass-val">{{ u['id_pass'] }}</div></div>
      {% endif %}
    </div>

    {% if u['status'] == 'pending' %}
    <div class="accept-form">
      <form method="post" action="/admin/accept/{{ u['id'] }}">
        <input type="text" name="idpass" placeholder="Enter ID & Password to send user" required autocomplete="off">
        <div class="actions">
          <button class="btn-approve" type="submit">✅ Accept & Send ID</button>
        </div>
      </form>
    </div>
    <div class="actions">
      <form method="post" action="/admin/decline/{{ u['id'] }}">
        <button class="btn-reject" type="submit">❌ Decline</button>
      </form>
    </div>
    {% endif %}
  </div>
  {% endfor %}
</div>
{% else %}
<div class="empty">No requests found.</div>
{% endif %}

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
