import os
import sqlite3
import requests
from functools import wraps
from flask import (
    Flask, render_template_string, redirect, url_for,
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
    background: #0a0a0a;
    color: #f0f0f0;
    font-family: 'Segoe UI', Arial, sans-serif;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .login-box {
    background: #111;
    border: 1px solid #222;
    border-top: 3px solid #cc0000;
    border-radius: 10px;
    padding: 40px 36px;
    width: 100%;
    max-width: 360px;
  }
  .login-box h1 {
    color: #ff4444;
    font-size: 1.4rem;
    margin-bottom: 6px;
    letter-spacing: 1px;
  }
  .login-box p {
    color: #555;
    font-size: 0.82rem;
    margin-bottom: 28px;
  }
  label {
    display: block;
    font-size: 0.78rem;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 6px;
  }
  input[type="password"] {
    width: 100%;
    background: #1a1a1a;
    border: 1px solid #333;
    border-radius: 6px;
    color: #f0f0f0;
    font-size: 0.95rem;
    padding: 11px 14px;
    margin-bottom: 20px;
    outline: none;
    transition: border-color 0.2s;
  }
  input[type="password"]:focus { border-color: #cc0000; }
  button {
    width: 100%;
    background: #cc0000;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 12px;
    font-size: 0.95rem;
    font-weight: bold;
    cursor: pointer;
    transition: background 0.15s;
  }
  button:hover { background: #ff2222; }
  .error {
    background: #2d0000;
    border: 1px solid #cc0000;
    color: #ff6666;
    border-radius: 6px;
    padding: 10px 14px;
    font-size: 0.82rem;
    margin-bottom: 18px;
  }
</style>
</head>
<body>
<div class="login-box">
  <h1>🔥 Admin Login</h1>
  <p>Payment Requests Dashboard</p>
  {% if error %}<div class="error">❌ {{ error }}</div>{% endif %}
  <form method="post" action="/admin/login">
    <label>Password</label>
    <input type="password" name="password" placeholder="Enter admin password" autofocus>
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
  body { background: #0a0a0a; color: #f0f0f0; font-family: 'Segoe UI', Arial, sans-serif; min-height: 100vh; }

  header {
    background: linear-gradient(135deg, #1a0000, #3d0000);
    border-bottom: 2px solid #cc0000;
    padding: 18px 30px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  header h1 { font-size: 1.5rem; color: #ff4444; letter-spacing: 1px; }
  .logout-btn {
    background: #1a1a1a;
    color: #888;
    border: 1px solid #333;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 0.78rem;
    cursor: pointer;
    text-decoration: none;
    transition: all 0.15s;
  }
  .logout-btn:hover { color: #ff4444; border-color: #cc0000; }

  .stats-bar { display: flex; gap: 15px; padding: 20px 30px; flex-wrap: wrap; }
  .stat {
    background: #111; border: 1px solid #222; border-radius: 8px;
    padding: 14px 22px; flex: 1; min-width: 120px; text-align: center;
  }
  .stat .num { font-size: 2rem; font-weight: bold; }
  .stat .label { font-size: 0.75rem; color: #777; margin-top: 4px; text-transform: uppercase; letter-spacing: 1px; }
  .stat.pending .num { color: #f5a623; }
  .stat.approved .num { color: #27ae60; }
  .stat.rejected .num { color: #cc0000; }
  .stat.total .num { color: #4a90e2; }

  .section-title {
    padding: 10px 30px; font-size: 0.85rem; color: #555;
    text-transform: uppercase; letter-spacing: 2px; border-bottom: 1px solid #1a1a1a;
  }

  .cards { padding: 20px 30px; display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
  .card {
    background: #111; border: 1px solid #222; border-left: 4px solid #cc0000;
    border-radius: 8px; padding: 18px; transition: border-color 0.2s;
  }
  .card:hover { border-left-color: #ff4444; }
  .card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
  .req-id { font-size: 0.75rem; color: #555; background: #1a1a1a; padding: 3px 8px; border-radius: 4px; }
  .badge { font-size: 0.7rem; padding: 3px 10px; border-radius: 12px; font-weight: bold; text-transform: uppercase; }
  .badge.pending { background: #2d1f00; color: #f5a623; }
  .badge.approved { background: #0d2d1a; color: #27ae60; }
  .badge.rejected { background: #2d0000; color: #cc0000; }
  .user-name { font-size: 1.1rem; font-weight: bold; margin-bottom: 10px; color: #fff; }
  .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 14px; }
  .info-item .key { color: #555; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.5px; }
  .info-item .val { color: #ccc; font-size: 0.82rem; margin-top: 1px; }
  .amount-val { color: #27ae60 !important; font-weight: bold; font-size: 1rem !important; }
  .actions { display: flex; gap: 8px; margin-top: 4px; }
  form { flex: 1; }
  button {
    width: 100%; padding: 9px; border: none; border-radius: 6px;
    font-size: 0.85rem; font-weight: bold; cursor: pointer; transition: opacity 0.15s;
  }
  button:hover { opacity: 0.85; }
  .btn-approve { background: #27ae60; color: white; }
  .btn-reject { background: #cc0000; color: white; }
  .empty { text-align: center; padding: 60px; color: #333; font-size: 1.1rem; }
  .flash { background: #1a3320; border: 1px solid #27ae60; color: #27ae60; padding: 10px 30px; font-size: 0.85rem; }
  .flash.err { background: #2d0000; border-color: #cc0000; color: #cc0000; }
  .tabs { display: flex; padding: 0 30px; border-bottom: 1px solid #1a1a1a; margin-top: 10px; }
  .tab {
    padding: 10px 20px; font-size: 0.82rem; text-decoration: none;
    color: #555; border-bottom: 2px solid transparent; transition: all 0.15s;
  }
  .tab.active { color: #ff4444; border-bottom-color: #cc0000; }
  .tab:hover { color: #ccc; }
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
  <div class="stat total"><div class="num">{{ stats.total }}</div><div class="label">Total</div></div>
  <div class="stat pending"><div class="num">{{ stats.pending }}</div><div class="label">Pending</div></div>
  <div class="stat approved"><div class="num">{{ stats.approved }}</div><div class="label">Approved</div></div>
  <div class="stat rejected"><div class="num">{{ stats.rejected }}</div><div class="label">Rejected</div></div>
</div>

<div class="tabs">
  <a class="tab {% if filter == 'pending' %}active{% endif %}" href="/admin/?f=pending">Pending</a>
  <a class="tab {% if filter == 'approved' %}active{% endif %}" href="/admin/?f=approved">Approved</a>
  <a class="tab {% if filter == 'rejected' %}active{% endif %}" href="/admin/?f=rejected">Rejected</a>
  <a class="tab {% if filter == 'all' %}active{% endif %}" href="/admin/?f=all">All</a>
</div>

<div class="section-title">{{ users|length }} request(s) shown</div>

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
    </div>
    {% if u['status'] == 'pending' %}
    <div class="actions">
      <form method="post" action="/admin/accept/{{ u['id'] }}">
        <button class="btn-approve">✅ Approve</button>
      </form>
      <form method="post" action="/admin/decline/{{ u['id'] }}">
        <button class="btn-reject">❌ Reject</button>
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


# ─── Login / Logout ───────────────────────────────────────────────

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


# ─── Main Panel ───────────────────────────────────────────────────

@app.route("/admin/")
@app.route("/admin")
@login_required
def home():
    f = request.args.get("f", "pending")
    db = get_db()
    where = "" if f == "all" else f"WHERE status='{f}'"
    users = db.execute(f"SELECT * FROM users {where} ORDER BY id DESC").fetchall()
    stats = {
        "total":    db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "pending":  db.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0],
        "approved": db.execute("SELECT COUNT(*) FROM users WHERE status='approved'").fetchone()[0],
        "rejected": db.execute("SELECT COUNT(*) FROM users WHERE status='rejected'").fetchone()[0],
    }
    return render_template_string(MAIN_HTML, users=users, stats=stats, filter=f)


@app.route("/admin/accept/<int:req_id>", methods=["POST"])
@login_required
def accept(req_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (req_id,)).fetchone()
    if not row:
        flash("Request not found.", "error")
        return redirect("/admin/")
    if row["status"] != "pending":
        flash(f"Request #{req_id} is already {row['status']}.", "error")
        return redirect("/admin/")
    db.execute("UPDATE users SET status='approved' WHERE id=?", (req_id,))
    db.commit()
    send_telegram(
        row["telegram_id"],
        f"🎉 *Congratulations {row['name']} Sir!*\n\n"
        f"Your payment of ₹{row['amount']} for *{row['site']}* has been *approved*!\n"
        f"Your ID will be activated shortly. 🚀"
    )
    flash(f"✅ Request #{req_id} approved and user notified on Telegram.")
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
    db.execute("UPDATE users SET status='rejected' WHERE id=?", (req_id,))
    db.commit()
    send_telegram(
        row["telegram_id"],
        f"❌ *Dear {row['name']} Sir,*\n\n"
        f"Your payment request of ₹{row['amount']} for *{row['site']}* has been *rejected*.\n\n"
        f"Please contact support or try again with /start."
    )
    flash(f"❌ Request #{req_id} rejected and user notified on Telegram.")
    return redirect("/admin/")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
