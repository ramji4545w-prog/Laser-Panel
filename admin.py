import os
import time
import requests
from datetime import date
from functools import wraps
from flask import (Flask, render_template_string, request,
                   redirect, url_for, session, jsonify, flash)
from flask_compress import Compress

from db import (db, CHAT_CACHE, cache_log, _CACHE_LOCK,      # chat cache
                PAYMENT_CACHE, _PAY_LOCK, cache_payment, update_payment_cache)  # payment cache

app = Flask(__name__)

# ── Gzip compression — reduces page size ~70% ─────────────────────────────
Compress(app)


def fmt_dt(val, fmt="datetime"):
    """Convert SQLite string or PostgreSQL datetime object → formatted string."""
    if val is None:
        return ""
    s = str(val).replace("T", " ")
    if fmt == "datetime":
        return s[:16]
    if fmt == "time":
        return s[11:16]
    if fmt == "date":
        return s[:10]
    return s[:16]


app.secret_key = os.environ.get("SESSION_SECRET", "laser-panel-secret-2024")

TOKEN         = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")
DEFAULT_UPI   = os.environ.get("UPI_ID", "")
ADMIN_PASS    = os.environ.get("ADMIN_PASSWORD") or "Laser@2024"
SITE_NAME     = "Laser Panel"


def get_upi():
    r = db.execute("SELECT upi FROM settings WHERE id=1").fetchone()
    return r["upi"] if r else DEFAULT_UPI


def save_upi_permanent(new_upi: str) -> bool:
    """DB update + Railway env var update (survives redeploy).
    Railway auto-provides PROJECT_ID, ENVIRONMENT_ID, SERVICE_ID.
    User only needs to add RAILWAY_TOKEN in Railway Variables."""
    # 1. Update local DB immediately
    db.execute("UPDATE settings SET upi=? WHERE id=1", (new_upi,))
    db.commit()

    # 2. Update Railway env var — only RAILWAY_TOKEN needed from user
    token   = os.environ.get("RAILWAY_TOKEN", "")
    proj_id = os.environ.get("RAILWAY_PROJECT_ID", "")
    env_id  = os.environ.get("RAILWAY_ENVIRONMENT_ID", "")
    svc_id  = os.environ.get("RAILWAY_SERVICE_ID", "")

    if not token:
        return False  # No token — DB only

    if not all([proj_id, env_id, svc_id]):
        return False  # Not running on Railway

    query = """
    mutation variableUpsert($input: VariableUpsertInput!) {
      variableUpsert(input: $input)
    }
    """
    try:
        resp = requests.post(
            "https://backboard.railway.app/graphql/v2",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"query": query, "variables": {"input": {
                "projectId": proj_id,
                "environmentId": env_id,
                "serviceId": svc_id,
                "name": "UPI_ID",
                "value": new_upi
            }}},
            timeout=10
        )
        data = resp.json()
        return resp.status_code == 200 and "errors" not in data
    except:
        return False


def send_tg(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=8)
    except: pass


# ── Auth decorators ───────────────────────────────────
def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get("logged_in") or not session.get("role"):
            session.clear()
            return redirect(url_for("login"))
        return f(*a, **kw)
    return dec


def admin_only(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get("logged_in") or session.get("role") != "admin":
            session.clear()
            return redirect(url_for("login"))
        return f(*a, **kw)
    return dec


# ══════════════════════════════════════════════════════
#  CSS
# ══════════════════════════════════════════════════════

BASE_CSS = """
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root {
  --bg:       #060912;
  --sidebar:  #080d1a;
  --card:     #0d1424;
  --border:   #162040;
  --blue:     #3b82f6;
  --blue2:    #2563eb;
  --blue-glow:rgba(59,130,246,.15);
  --text:     #e2e8f0;
  --muted:    #4a6080;
  --green:    #22c55e;
  --red:      #ef4444;
  --yellow:   #f59e0b;
}
body { background:var(--bg); color:var(--text);
       font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif; min-height:100vh; }
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}

.layout { display:flex; min-height:100vh; }

/* SIDEBAR */
.sidebar {
  width:240px; min-height:100vh; background:var(--sidebar);
  border-right:1px solid var(--border); position:fixed;
  display:flex; flex-direction:column; z-index:100;
}
.main { margin-left:240px; flex:1; padding:30px; }

.logo { padding:24px 20px 20px; border-bottom:1px solid var(--border); }
.logo h1 {
  font-size:1.25rem; font-weight:800;
  background:linear-gradient(135deg,#3b82f6,#93c5fd);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent;
}
.logo span { font-size:.7rem; color:var(--muted); display:block; margin-top:3px; letter-spacing:.5px; }

nav { flex:1; padding:12px 10px; }
.nav-section { font-size:.65rem; font-weight:700; letter-spacing:1.5px;
               color:var(--muted); padding:14px 14px 6px; text-transform:uppercase; }
.nav-item {
  display:flex; align-items:center; gap:11px;
  padding:10px 14px; border-radius:9px; margin-bottom:3px;
  color:var(--muted); text-decoration:none; font-size:.86rem;
  font-weight:500; transition:all .15s;
}
.nav-item:hover  { background:var(--blue-glow); color:var(--blue); }
.nav-item.active { background:var(--blue-glow); color:var(--blue);
                   border:1px solid rgba(59,130,246,.2); }
.nav-item svg { width:17px; height:17px; flex-shrink:0; }

/* CARDS */
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(185px,1fr)); gap:16px; margin-bottom:26px; }
.card {
  background:var(--card); border:1px solid var(--border);
  border-radius:14px; padding:22px 20px;
  position:relative; overflow:hidden;
}
.card::before {
  content:''; position:absolute; top:0; left:0; right:0; height:2px;
  background:linear-gradient(90deg,#2563eb,#3b82f6);
}
.card-icon { font-size:1.5rem; margin-bottom:10px; }
.card-label { font-size:.72rem; color:var(--muted); font-weight:600;
              letter-spacing:.8px; text-transform:uppercase; margin-bottom:8px; }
.card-val { font-size:1.9rem; font-weight:800; }
.card-val.blue   { color:var(--blue); }
.card-val.green  { color:var(--green); }
.card-val.yellow { color:var(--yellow); }
.card-val.red    { color:var(--red); }
.card-sub { font-size:.73rem; color:var(--muted); margin-top:5px; }

/* TABLE */
.page-title { font-size:1.35rem; font-weight:700; margin-bottom:22px; }
.page-title span { color:var(--blue); }

.table-wrap { background:var(--card); border:1px solid var(--border);
              border-radius:14px; overflow:auto; }
table { width:100%; border-collapse:collapse; min-width:700px; }
thead th { background:rgba(0,0,0,.3); color:var(--muted); font-size:.72rem;
           font-weight:700; letter-spacing:.8px; text-transform:uppercase;
           padding:12px 16px; text-align:left; border-bottom:1px solid var(--border); }
tbody tr { border-bottom:1px solid var(--border); transition:background .12s; }
tbody tr:hover { background:rgba(59,130,246,.04); }
tbody td { padding:12px 16px; font-size:.85rem; vertical-align:middle; }
tbody tr:last-child { border-bottom:none; }

/* BADGE */
.badge { display:inline-block; padding:3px 9px; border-radius:20px;
         font-size:.7rem; font-weight:700; letter-spacing:.3px; }
.badge-pending  { background:rgba(245,158,11,.12); color:var(--yellow); }
.badge-accepted { background:rgba(34,197,94,.12);  color:var(--green); }
.badge-declined { background:rgba(239,68,68,.12);  color:var(--red); }
.badge-new      { background:rgba(59,130,246,.12); color:var(--blue); }

/* BUTTONS */
.btn {
  display:inline-flex; align-items:center; gap:6px;
  padding:9px 18px; border-radius:8px; font-size:.83rem;
  font-weight:600; border:none; cursor:pointer;
  transition:all .15s; text-decoration:none;
}
.btn-primary {
  background:linear-gradient(135deg,#2563eb,#3b82f6);
  color:#fff; box-shadow:0 4px 14px rgba(37,99,235,.3);
}
.btn-primary:hover { transform:translateY(-1px); box-shadow:0 6px 18px rgba(37,99,235,.45); }
.btn-success {
  background:linear-gradient(135deg,#15803d,#22c55e);
  color:#fff; box-shadow:0 4px 12px rgba(34,197,94,.2);
}
.btn-success:hover { transform:translateY(-1px); }
.btn-danger {
  background:linear-gradient(135deg,#b91c1c,#ef4444);
  color:#fff; box-shadow:0 4px 12px rgba(239,68,68,.2);
}
.btn-danger:hover { transform:translateY(-1px); }
.btn-ghost { background:var(--border); color:var(--muted); }
.btn-ghost:hover { background:var(--blue-glow); color:var(--blue); }
.btn-sm { padding:6px 12px; font-size:.78rem; border-radius:7px; }

/* FORM */
.form-group { margin-bottom:18px; }
.form-label { display:block; font-size:.8rem; font-weight:600;
              color:var(--muted); margin-bottom:7px; }
.form-input {
  width:100%; background:#08101f; border:1px solid var(--border);
  border-radius:9px; padding:11px 14px; color:var(--text);
  font-size:.88rem; transition:border .15s; outline:none;
}
.form-input:focus { border-color:var(--blue); box-shadow:0 0 0 3px rgba(59,130,246,.12); }
.form-input::placeholder { color:var(--muted); }

/* MODAL */
.modal-overlay {
  display:none; position:fixed; inset:0;
  background:rgba(0,0,0,.75); backdrop-filter:blur(5px);
  z-index:999; align-items:center; justify-content:center;
}
.modal-overlay.open { display:flex; }
.modal {
  background:var(--card); border:1px solid var(--border);
  border-radius:16px; padding:30px; width:420px; max-width:92vw;
}
.modal h3 { font-size:1.1rem; font-weight:700; margin-bottom:20px; }

/* ALERT */
.alert { padding:12px 16px; border-radius:8px; margin-bottom:18px;
         font-size:.84rem; font-weight:500; }
.alert-success { background:rgba(34,197,94,.08); border:1px solid rgba(34,197,94,.2); color:#4ade80; }
.alert-error   { background:rgba(239,68,68,.08); border:1px solid rgba(239,68,68,.2); color:#f87171; }

/* SIDEBAR FOOTER */
.sidebar-footer { padding:14px; border-top:1px solid var(--border); }
.user-info { display:flex; align-items:center; gap:10px; margin-bottom:10px; }
.avatar { width:32px; height:32px; background:linear-gradient(135deg,#2563eb,#3b82f6);
          border-radius:50%; display:flex; align-items:center; justify-content:center;
          font-weight:800; font-size:.9rem; color:#fff; flex-shrink:0; }
.uname { font-size:.83rem; font-weight:600; }
.urole { font-size:.7rem; color:var(--muted); }

.topbar { display:flex; align-items:center; justify-content:space-between; margin-bottom:22px; }
.topbar-right { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.pill { background:var(--card); border:1px solid var(--border);
        border-radius:20px; padding:5px 13px; font-size:.76rem; color:var(--muted); }
.pill span { color:var(--blue); font-weight:600; }

.empty { text-align:center; padding:48px; color:var(--muted); font-size:.88rem; }

/* LOGIN */
.login-page {
  min-height:100vh; display:flex; align-items:center; justify-content:center;
  background:var(--bg);
  background-image:
    radial-gradient(ellipse at 15% 60%, rgba(37,99,235,.07) 0%, transparent 55%),
    radial-gradient(ellipse at 85% 20%, rgba(59,130,246,.05) 0%, transparent 50%);
}
.login-box {
  background:var(--card); border:1px solid var(--border);
  border-radius:20px; padding:42px 36px; width:380px; max-width:92vw;
  box-shadow:0 30px 70px rgba(0,0,0,.6);
}
.login-logo { text-align:center; margin-bottom:34px; }
.login-logo .icon { font-size:2.5rem; margin-bottom:10px; }
.login-logo h1 {
  font-size:1.7rem; font-weight:800;
  background:linear-gradient(135deg,#3b82f6,#93c5fd);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent;
}
.login-logo p { color:var(--muted); font-size:.82rem; margin-top:5px; }
.login-btn {
  width:100%; padding:13px; border-radius:10px; border:none;
  background:linear-gradient(135deg,#2563eb,#3b82f6); color:#fff;
  font-size:.95rem; font-weight:700; cursor:pointer;
  box-shadow:0 6px 20px rgba(37,99,235,.4); transition:all .15s;
}
.login-btn:hover { transform:translateY(-1px); box-shadow:0 8px 28px rgba(37,99,235,.55); }

/* ID SEND FORM */
.id-form { display:flex; gap:7px; align-items:center; margin-top:6px; }
.id-form input {
  flex:1; background:#08101f; border:1px solid var(--border);
  border-radius:7px; padding:7px 10px; color:var(--text);
  font-size:.8rem; outline:none; min-width:0;
}
.id-form input:focus { border-color:var(--blue); }
</style>
"""

SIDEBAR_TMPL = """
<div class="sidebar">
  <div class="logo">
    <h1>⚡ Laser Panel</h1>
    <span>ADMIN DASHBOARD</span>
  </div>
  <nav>
    {nav_items}
  </nav>
  <div class="sidebar-footer">
    <div class="user-info">
      <div class="avatar">{avatar}</div>
      <div>
        <div class="uname">{username}</div>
        <div class="urole">{role_label}</div>
      </div>
    </div>
    <a href="/admin/logout" class="btn btn-ghost btn-sm" style="width:100%;justify-content:center">
      ↩ Logout
    </a>
  </div>
</div>
"""

ICONS = {
    "grid":        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>',
    "sun":         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/></svg>',
    "card":        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="1" y="4" width="22" height="16" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>',
    "users":       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    "user-plus":   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>',
    "settings":    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
    "chat":        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
}


def make_nav(active, role):
    items = []
    def nav(href, icon, label, key):
        cls = "active" if active == key else ""
        items.append(
            f'<a href="{href}" class="nav-item {cls}">{ICONS[icon]}<span>{label}</span></a>'
        )
    if role == "admin":
        items.append('<div class="nav-section">Overview</div>')
        nav("/admin/dashboard", "grid",     "Dashboard",      "dashboard")
        nav("/admin/today",     "sun",      "Today",          "today")
        items.append('<div class="nav-section">Manage</div>')
        nav("/admin/payments",      "card",      "Payments",       "payments")
        nav("/admin/registrations", "users",     "Registrations",  "registrations")
        nav("/admin/chats",         "chat",      "Chats",          "chats")
        items.append('<div class="nav-section">Settings</div>')
        nav("/admin/subusers",  "user-plus", "Sub Users",      "subusers")
        nav("/admin/settings",  "settings",  "Settings",       "settings")
    else:
        items.append('<div class="nav-section">Manage</div>')
        nav("/admin/payments", "card", "Payments", "payments")
    return "\n".join(items)


def page(title, content, active):
    role  = session.get("role", "subadmin")
    uname = session.get("username", "User")
    sidebar = SIDEBAR_TMPL.format(
        nav_items  = make_nav(active, role),
        avatar     = uname[0].upper(),
        username   = uname,
        role_label = "Administrator" if role == "admin" else "Sub User",
    )
    return render_template_string(f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — {SITE_NAME}</title>
{BASE_CSS}
</head><body>
<div class="layout">
  {sidebar}
  <div class="main">{content}</div>
</div>
</body></html>""")


def get_flashes():
    msgs = ""
    for cat, msg in session.get("_flashes", []):
        cls = "alert-success" if cat == "success" else "alert-error"
        msgs += f'<div class="alert {cls}">{msg}</div>'
    session.pop("_flashes", None)
    return msgs


# ══════════════════════════════════════════════════════
#  LOGIN / LOGOUT
# ══════════════════════════════════════════════════════

@app.route("/ping")
def ping():
    """Health check — keeps Railway app alive, responds instantly."""
    return "ok", 200


@app.route("/admin/db_status")
@login_required
def db_status():
    """Railway debug — shows DB type, record counts, env vars."""
    import os
    db_type = "PostgreSQL ✅" if db.is_pg else "SQLite ⚠️"
    try:
        pay_count  = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        chat_count = db.execute("SELECT COUNT(*) FROM chat_logs").fetchone()[0]
        last_pay   = db.execute("SELECT name,utr,status,created_at FROM users ORDER BY id DESC LIMIT 5").fetchall()
    except Exception as e:
        pay_count = chat_count = 0
        last_pay = []
    
    has_db_url  = "✅ SET" if os.environ.get("DATABASE_URL") else "❌ NOT SET"
    has_tg_tok  = "✅ SET" if os.environ.get("TELEGRAM_BOT_TOKEN") else "❌ NOT SET"
    has_gh_tok  = "✅ SET" if os.environ.get("GITHUB_TOKEN") else "❌ NOT SET"
    
    rows = "".join(f"<tr><td>{r['name']}</td><td>{r['utr']}</td><td>{r['status']}</td><td>{fmt_dt(r['created_at'])}</td></tr>"
                   for r in last_pay)
    
    content = f"""
<div class="topbar"><div class="page-title">DB <span>Status</span></div></div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:24px">
  <div class="card" style="padding:16px">
    <div style="color:var(--muted);font-size:11px">DATABASE</div>
    <div style="font-size:16px;font-weight:700;margin-top:6px">{db_type}</div>
  </div>
  <div class="card" style="padding:16px">
    <div style="color:var(--muted);font-size:11px">DATABASE_URL</div>
    <div style="font-size:15px;font-weight:700;margin-top:6px">{has_db_url}</div>
  </div>
  <div class="card" style="padding:16px">
    <div style="color:var(--muted);font-size:11px">TELEGRAM_BOT_TOKEN</div>
    <div style="font-size:15px;font-weight:700;margin-top:6px">{has_tg_tok}</div>
  </div>
  <div class="card" style="padding:16px">
    <div style="color:var(--muted);font-size:11px">GITHUB_TOKEN</div>
    <div style="font-size:15px;font-weight:700;margin-top:6px">{has_gh_tok}</div>
  </div>
  <div class="card" style="padding:16px">
    <div style="color:var(--muted);font-size:11px">PAYMENTS in DB</div>
    <div style="font-size:28px;font-weight:700;margin-top:6px;color:var(--green)">{pay_count}</div>
  </div>
  <div class="card" style="padding:16px">
    <div style="color:var(--muted);font-size:11px">CHATS in DB</div>
    <div style="font-size:28px;font-weight:700;margin-top:6px;color:var(--blue2)">{chat_count}</div>
  </div>
</div>
<div class="card" style="padding:16px">
  <div style="font-weight:600;margin-bottom:12px">Last 5 Payments in DB</div>
  <table style="width:100%">
    <thead><tr><th>Name</th><th>UTR</th><th>Status</th><th>Time</th></tr></thead>
    <tbody>{rows if rows else '<tr><td colspan="4" class="empty">No records in DB yet</td></tr>'}</tbody>
  </table>
</div>
<div style="margin-top:16px;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px">
  <div style="font-weight:600;margin-bottom:8px">⚠️ Agar DATABASE_URL ❌ NOT SET dikhe toh Railway mein set karo:</div>
  <code style="color:var(--green);font-size:13px">DATABASE_URL = $&#123;&#123;Postgres.DATABASE_URL&#125;&#125;</code>
</div>"""
    return page("DB Status", content, "dashboard")


@app.route("/")
def root():
    if session.get("logged_in") and session.get("role") == "admin":
        return redirect(url_for("dashboard"))
    if session.get("logged_in"):
        return redirect(url_for("payments"))
    return redirect(url_for("login"))


@app.route("/admin/login", methods=["GET","POST"])
def login():
    error = ""
    if request.method == "POST":
        uname = request.form.get("username","").strip()
        pwd   = request.form.get("password","").strip()

        if uname == "admin" and pwd == ADMIN_PASS:
            session.clear()
            session.update(logged_in=True, role="admin", username="admin")
            return redirect(url_for("dashboard"))

        sub = db.execute(
            "SELECT * FROM subadmins WHERE name=? AND password=?", (uname, pwd)
        ).fetchone()
        if sub:
            session.clear()
            session.update(logged_in=True, role="subadmin", username=uname)
            return redirect(url_for("payments"))

        error = "❌ Invalid username or password."

    return render_template_string(f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login — {SITE_NAME}</title>
{BASE_CSS}
</head><body>
<div class="login-page">
  <div class="login-box">
    <div class="login-logo">
      <div class="icon">⚡</div>
      <h1>Laser Panel</h1>
      <p>Secure Admin Access</p>
    </div>
    {"<div class='alert alert-error'>" + error + "</div>" if error else ""}
    <form method="POST">
      <div class="form-group">
        <label class="form-label">USERNAME</label>
        <input class="form-input" name="username" placeholder="Enter your username" required autofocus>
      </div>
      <div class="form-group" style="margin-bottom:24px">
        <label class="form-label">PASSWORD</label>
        <input class="form-input" type="password" name="password" placeholder="Enter your password" required>
      </div>
      <button type="submit" class="login-btn">Login to Panel →</button>
    </form>
    <p style="text-align:center;color:var(--muted);font-size:.75rem;margin-top:20px">
      🔒 Laser Panel · Secure Admin System
    </p>
  </div>
</div>
</body></html>""")


@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ══════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════

@app.route("/admin/dashboard")
@admin_only
def dashboard():
    today_str = date.today().isoformat()  # "2026-04-25"

    # ── Stats from PAYMENT_CACHE (always accurate — warmed from DB on startup) ─
    with _PAY_LOCK:
        cache_vals = list(PAYMENT_CACHE.values())

    total_users  = len(cache_vals)
    total_amount = sum(
        float(p.get("amount") or 0)
        for p in cache_vals if p.get("status") == "accepted"
    )
    # ts format in cache = "DD/MM HH:MM", e.g. "25/04 17:30"
    today_prefix = today_str[8:10] + "/" + today_str[5:7]   # e.g. "25/04"
    today_dep = sum(
        float(p.get("amount") or 0)
        for p in cache_vals
        if p.get("status") == "accepted" and str(p.get("ts","")).startswith(today_prefix)
    )
    today_reg_cache = sum(1 for p in cache_vals if str(p.get("ts","")).startswith(today_prefix))
    pending_cnt = sum(1 for p in cache_vals if p.get("status") == "pending")

    # Today's registrations — try DB first, fallback to cache count
    try:
        t_reg = db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE DATE(created_at)=?", (today_str,)
        ).fetchone()
        today_reg = max(t_reg["c"] if t_reg else 0, today_reg_cache)
    except Exception:
        today_reg = today_reg_cache

    # If DB has more records than cache (shouldn't happen normally), use DB count
    try:
        db_total = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        if db_total and db_total["c"] > total_users:
            total_users = db_total["c"]
        db_amt = db.execute(
            "SELECT COALESCE(SUM(CASE WHEN status='accepted' THEN CAST(amount AS REAL) ELSE 0 END),0) AS s FROM users"
        ).fetchone()
        if db_amt and float(db_amt["s"] or 0) > total_amount:
            total_amount = float(db_amt["s"])
        db_pend = db.execute("SELECT COUNT(*) AS c FROM users WHERE status='pending'").fetchone()
        if db_pend and db_pend["c"] > pending_cnt:
            pending_cnt = db_pend["c"]
    except Exception:
        pass

    # ── Recent Activity — last 10 from cache (sorted newest first) ─────────────
    recent = sorted(cache_vals, key=lambda x: x.get("cache_id",""), reverse=True)[:10]

    rows_html = ""
    for r in recent:
        badge = {"pending":"badge-pending","accepted":"badge-accepted","declined":"badge-declined"}.get(r.get("status","pending"),"badge-pending")
        rows_html += f"""<tr>
          <td style="color:var(--muted)">#{r.get("cache_id","—")}</td>
          <td style="font-weight:600">{r.get("name","—")}</td>
          <td>{r.get("site","—")}</td>
          <td><span class="badge badge-new">{(r.get("id_type","new")).upper()}</span></td>
          <td style="color:var(--green);font-weight:700">₹{r.get("amount",0)}</td>
          <td><span class="badge {badge}">{r.get("status","pending").upper()}</span></td>
          <td style="color:var(--muted);font-size:.77rem">{r.get("ts","—")}</td>
        </tr>"""

    content = f"""
<div class="topbar">
  <div class="page-title">Dashboard <span>Overview</span></div>
  <div class="topbar-right">
    <div class="pill">📅 <span>{today_str}</span></div>
    {"<a href='/admin/payments' class='btn btn-danger btn-sm'>🔴 " + str(pending_cnt) + " Pending</a>" if pending_cnt else ""}
  </div>
</div>

<div class="cards">
  <div class="card">
    <div class="card-icon">👥</div>
    <div class="card-label">Total Users</div>
    <div class="card-val blue">{total_users}</div>
    <div class="card-sub">All registrations</div>
  </div>
  <div class="card">
    <div class="card-icon">💰</div>
    <div class="card-label">Total Collected</div>
    <div class="card-val green">₹{total_amount:,.0f}</div>
    <div class="card-sub">All accepted payments</div>
  </div>
  <div class="card">
    <div class="card-icon">📅</div>
    <div class="card-label">Today's Deposit</div>
    <div class="card-val yellow">₹{today_dep:,.0f}</div>
    <div class="card-sub">Accepted today</div>
  </div>
  <div class="card">
    <div class="card-icon">🆕</div>
    <div class="card-label">Today's Registrations</div>
    <div class="card-val">{today_reg}</div>
    <div class="card-sub">New users today</div>
  </div>
  <div class="card">
    <div class="card-icon">⏳</div>
    <div class="card-label">Pending Payments</div>
    <div class="card-val red">{pending_cnt}</div>
    <div class="card-sub">Awaiting review</div>
  </div>
</div>

<div class="page-title" style="font-size:1rem;margin-bottom:14px">🕐 Recent Activity</div>
<div class="table-wrap">
<table>
  <thead><tr><th>#</th><th>Name</th><th>Site</th><th>Type</th><th>Amount</th><th>Status</th><th>Date</th></tr></thead>
  <tbody>
    {rows_html if rows_html else '<tr><td colspan="7" class="empty">No requests yet</td></tr>'}
  </tbody>
</table>
</div>"""
    return page("Dashboard", content, "dashboard")


# ══════════════════════════════════════════════════════
#  TODAY
# ══════════════════════════════════════════════════════

@app.route("/admin/today")
@admin_only
def today():
    today_str = date.today().isoformat()
    rows = db.execute(
        "SELECT * FROM users WHERE DATE(created_at)=? ORDER BY id DESC", (today_str,)
    ).fetchall()

    total_dep = sum(float(r["amount"] or 0) for r in rows if r["status"] == "accepted")
    total_cnt = len(rows)
    acc_cnt   = sum(1 for r in rows if r["status"] == "accepted")
    pend_cnt  = sum(1 for r in rows if r["status"] == "pending")
    dec_cnt   = sum(1 for r in rows if r["status"] == "declined")

    rows_html = ""
    for r in rows:
        badge = {"pending":"badge-pending","accepted":"badge-accepted","declined":"badge-declined"}.get(r["status"],"badge-pending")
        rows_html += f"""<tr>
          <td style="color:var(--muted)">#{r["id"]}</td>
          <td style="font-weight:600">{r["name"] or "—"}</td>
          <td style="color:var(--muted)">{r["phone"] or "—"}</td>
          <td>{r["site"] or "—"}</td>
          <td style="color:var(--green);font-weight:700">₹{r["amount"] or 0}</td>
          <td style="color:var(--muted);font-size:.8rem">{r["utr"] or "—"}</td>
          <td><span class="badge {badge}">{r["status"].upper()}</span></td>
          <td style="color:var(--muted);font-size:.77rem">{fmt_dt(r["created_at"], "time")}</td>
        </tr>"""

    content = f"""
<div class="topbar">
  <div class="page-title">Today <span>— {today_str}</span></div>
</div>
<div class="cards">
  <div class="card"><div class="card-icon">📊</div>
    <div class="card-label">Total Requests</div>
    <div class="card-val blue">{total_cnt}</div></div>
  <div class="card"><div class="card-icon">✅</div>
    <div class="card-label">Accepted</div>
    <div class="card-val green">{acc_cnt}</div></div>
  <div class="card"><div class="card-icon">⏳</div>
    <div class="card-label">Pending</div>
    <div class="card-val yellow">{pend_cnt}</div></div>
  <div class="card"><div class="card-icon">❌</div>
    <div class="card-label">Declined</div>
    <div class="card-val red">{dec_cnt}</div></div>
  <div class="card"><div class="card-icon">💵</div>
    <div class="card-label">Total Deposit</div>
    <div class="card-val green">₹{total_dep:,.0f}</div></div>
</div>
<div class="table-wrap"><table>
  <thead><tr><th>#</th><th>Name</th><th>Phone</th><th>Site</th>
    <th>Amount</th><th>UTR</th><th>Status</th><th>Time</th></tr></thead>
  <tbody>
    {rows_html if rows_html else f'<tr><td colspan="8" class="empty">No activity today</td></tr>'}
  </tbody>
</table></div>"""
    return page("Today", content, "today")


# ══════════════════════════════════════════════════════
#  PAYMENTS
# ══════════════════════════════════════════════════════

def _merged_payments(status_filter="all"):
    """
    Merge PAYMENT_CACHE (primary) + DB (fallback).
    Returns list of dicts sorted newest-first.
    DB-backed IDs = numeric str; cache-only IDs = 'c_...'
    """
    merged = {}  # cache_id_str → entry dict

    # 1. In-memory cache first (bot saves here on every payment submit)
    with _PAY_LOCK:
        for cid, entry in PAYMENT_CACHE.items():
            merged[cid] = dict(entry)

    # 2. DB entries — add those NOT already in cache
    try:
        for r in db.execute("SELECT * FROM users ORDER BY id DESC LIMIT 500").fetchall():
            cid = str(r["id"])
            if cid not in merged:
                merged[cid] = {
                    "cache_id":    cid,
                    "telegram_id": r["telegram_id"],
                    "name":        r["name"] or "Unknown",
                    "phone":       r["phone"] or "",
                    "site":        r["site"] or "",
                    "id_type":     r["id_type"] or "new",
                    "amount":      str(r["amount"] or ""),
                    "utr":         r["utr"] or "",
                    "status":      r["status"] or "pending",
                    "id_pass":     r["id_pass"] or "",
                    "ts":          fmt_dt(r["created_at"]),
                }
            else:
                # sync accept/decline from DB into cache
                merged[cid]["status"]  = r["status"] or merged[cid].get("status","pending")
                merged[cid]["id_pass"] = r["id_pass"] or merged[cid].get("id_pass","")
    except Exception:
        pass

    rows = list(merged.values())
    if status_filter != "all":
        rows = [r for r in rows if r.get("status") == status_filter]

    def _sort_key(e):
        cid = e.get("cache_id","")
        if cid.startswith("c_"):
            return (0, e.get("ts",""))
        try: return (0, str(-int(cid)).zfill(12))
        except: return (0, e.get("ts",""))
    rows.sort(key=_sort_key, reverse=True)
    return rows


def _payment_actions_html(r):
    cid    = r["cache_id"]
    status = r.get("status","pending")
    if status == "pending":
        return f"""
<form method="POST" action="/admin/payment/action" style="display:inline">
  <input type="hidden" name="req_id" value="{cid}">
  <input type="hidden" name="action" value="accept">
  <button type="submit" class="btn btn-success btn-sm">✓ Accept</button>
</form>
<form method="POST" action="/admin/payment/action" style="display:inline;margin-left:5px">
  <input type="hidden" name="req_id" value="{cid}">
  <input type="hidden" name="action" value="decline">
  <button type="submit" class="btn btn-danger btn-sm">✗ Decline</button>
</form>"""
    elif status == "accepted":
        sent = (f'<div style="color:var(--green);font-size:.77rem;margin-bottom:4px">✓ ID Sent: {r["id_pass"]}</div>'
                if r.get("id_pass") else "")
        return f"""{sent}
<form method="POST" action="/admin/payment/send_id"
  style="display:flex;gap:6px;align-items:center;margin-top:4px">
  <input type="hidden" name="req_id" value="{cid}">
  <input name="id_pass" placeholder="ID:Password" value="{r.get('id_pass','')}"
    style="background:var(--bg);border:1px solid var(--border);color:var(--text);
    border-radius:6px;padding:5px 10px;font-size:12px;width:130px">
  <button type="submit" class="btn btn-primary btn-sm">📤 Send</button>
</form>"""
    else:
        return '<span style="color:var(--muted);font-size:.8rem">—</span>'


@app.route("/admin/payments")
@login_required
def payments():
    status_filter = request.args.get("status", "all")
    flashes = get_flashes()

    filter_btns = ""
    all_rows = _merged_payments(status_filter)
    total    = len(all_rows)

    per_page = 30
    cur_page = max(1, int(request.args.get("page", 1)))
    total_pages = max(1, (total + per_page - 1) // per_page)
    rows = all_rows[(cur_page-1)*per_page : cur_page*per_page]

    filter_btns = ""
    for val, label, ico in [("all","All","📋"),("pending","Pending","⏳"),
                              ("accepted","Accepted","✅"),("declined","Declined","❌")]:
        cls = "btn-primary" if status_filter == val else "btn-ghost"
        cnt = len(_merged_payments(val)) if val != "all" else total
        badge_s = (f' <span style="background:#1e40af;color:#fff;border-radius:10px;'
                   f'padding:1px 7px;font-size:11px">{cnt}</span>') if cnt else ""
        filter_btns += f'<a href="?status={val}" class="btn {cls} btn-sm">{ico} {label}{badge_s}</a> '

    badge_cls = {"pending":"badge-pending","accepted":"badge-accepted","declined":"badge-declined"}
    rows_html = ""
    for r in rows:
        badge   = badge_cls.get(r.get("status","pending"), "badge-pending")
        actions = _payment_actions_html(r)
        cid     = r["cache_id"]
        src     = "🟢" if cid.startswith("c_") else f"#{cid}"
        rows_html += f"""<tr>
  <td style="color:var(--muted);font-size:12px">{src}</td>
  <td style="font-weight:600">{r['name']}</td>
  <td style="color:var(--muted);font-size:.82rem">{r.get('phone') or '—'}</td>
  <td>{r.get('site') or '—'}</td>
  <td><span class="badge badge-new">{(r.get('id_type') or 'new').upper()}</span></td>
  <td style="color:var(--green);font-weight:700">₹{r.get('amount') or 0}</td>
  <td style="color:var(--muted);font-size:.79rem">{r.get('utr') or '—'}</td>
  <td><span class="badge {badge}">{(r.get('status','pending')).upper()}</span></td>
  <td style="min-width:230px">{actions}</td>
</tr>"""

    page_btns = ""
    for p in range(1, total_pages+1):
        cls = "btn-primary" if p == cur_page else "btn-ghost"
        page_btns += f'<a href="?status={status_filter}&page={p}" class="btn {cls} btn-sm">{p}</a> '

    manual_form = """
<details style="margin-bottom:18px">
  <summary style="cursor:pointer;background:var(--card);border:1px solid var(--border);
    border-radius:10px;padding:12px 18px;font-weight:600;font-size:14px;list-style:none;
    display:flex;align-items:center;gap:8px">
    ➕ Manual Payment Entry
    <span style="font-size:11px;color:var(--muted);font-weight:400;margin-left:4px">
      (Telegram notification se data daalo)
    </span>
  </summary>
  <div style="background:var(--card);border:1px solid var(--border);border-top:none;
    border-radius:0 0 10px 10px;padding:18px">
    <form method="POST" action="/admin/payment/manual_add">
      <div style="display:flex;flex-wrap:wrap;gap:10px">
        <input name="name" placeholder="Customer Name *" required
          style="flex:1;min-width:140px;background:var(--bg);border:1px solid var(--border);
          color:var(--text);border-radius:8px;padding:8px 12px;font-size:13px">
        <input name="phone" placeholder="Phone Number"
          style="flex:1;min-width:140px;background:var(--bg);border:1px solid var(--border);
          color:var(--text);border-radius:8px;padding:8px 12px;font-size:13px">
        <input name="telegram_id" placeholder="Telegram Chat ID *" required
          style="flex:1;min-width:140px;background:var(--bg);border:1px solid var(--border);
          color:var(--text);border-radius:8px;padding:8px 12px;font-size:13px">
        <select name="site"
          style="flex:1;min-width:140px;background:var(--bg);border:1px solid var(--border);
          color:var(--text);border-radius:8px;padding:8px 12px;font-size:13px">
          <option value="Laser247">Laser247</option>
          <option value="Tiger399">Tiger399</option>
          <option value="AllPanel">AllPanel</option>
          <option value="Diamond">Diamond</option>
        </select>
        <select name="id_type"
          style="flex:1;min-width:100px;background:var(--bg);border:1px solid var(--border);
          color:var(--text);border-radius:8px;padding:8px 12px;font-size:13px">
          <option value="new">New ID</option>
          <option value="demo">Demo ID</option>
        </select>
        <input name="amount" placeholder="Amount ₹ *" required
          style="flex:1;min-width:100px;background:var(--bg);border:1px solid var(--border);
          color:var(--text);border-radius:8px;padding:8px 12px;font-size:13px">
        <input name="utr" placeholder="UTR (12 digits) *" required
          style="flex:1;min-width:140px;background:var(--bg);border:1px solid var(--border);
          color:var(--text);border-radius:8px;padding:8px 12px;font-size:13px">
        <button type="submit" class="btn btn-primary btn-sm" style="height:37px;padding:0 20px">
          ✅ Add Payment
        </button>
      </div>
    </form>
  </div>
</details>"""

    content = f"""
<div class="topbar">
  <div class="page-title">Payments <span>Management</span></div>
  <div class="topbar-right">{filter_btns}</div>
</div>
{flashes}
{manual_form}
<div class="table-wrap"><table>
  <thead><tr>
    <th>#</th><th>Name</th><th>Phone</th><th>Site</th>
    <th>Type</th><th>Amount</th><th>UTR</th><th>Status</th>
    <th style="min-width:230px">Actions</th>
  </tr></thead>
  <tbody>
    {rows_html if rows_html else
     '<tr><td colspan="9" class="empty">No payments found — jab customer UTR bhejega yahan turant dikhega ⏳</td></tr>'}
  </tbody>
</table></div>
<div style="display:flex;gap:8px;justify-content:center;margin-top:20px;flex-wrap:wrap;">{page_btns}</div>
<p style="text-align:center;color:var(--muted);margin-top:8px;font-size:13px;">
  Showing {len(rows)} of {total} records | Page {cur_page}/{total_pages}
  &nbsp;|&nbsp; <span style="color:var(--green)">🟢 live cache</span>
</p>
<script>setTimeout(function(){{location.reload()}},30000);</script>"""
    return page("Payments", content, "payments")


@app.route("/admin/payment/action", methods=["POST"])
@login_required
def payment_action():
    req_id = request.form.get("req_id","").strip()
    action = request.form.get("action","")
    is_cache_only = req_id.startswith("c_")

    # Get the payment entry (from cache or DB)
    entry = None
    with _PAY_LOCK:
        entry = dict(PAYMENT_CACHE.get(req_id, {}))

    if not entry and not is_cache_only:
        # Try DB
        try:
            row = db.execute("SELECT * FROM users WHERE id=?", (int(req_id),)).fetchone()
            if row:
                entry = {"telegram_id": row["telegram_id"], "name": row["name"],
                         "amount": row["amount"], "site": row["site"],
                         "status": row["status"], "cache_id": req_id}
        except Exception: pass

    if not entry:
        flash("⚠️ Payment request nahi mila.", "error")
        return redirect(url_for("payments"))

    if entry.get("status") != "pending":
        flash(f"Already {entry.get('status','?')}.", "error")
        return redirect(url_for("payments"))

    tid  = entry["telegram_id"]
    name = entry.get("name","Sir")
    amt  = entry.get("amount","?")
    site = entry.get("site","?")

    if action == "accept":
        # Update cache
        update_payment_cache(req_id, status="accepted")
        # Update DB (if DB-backed)
        if not is_cache_only:
            try:
                db.execute("UPDATE users SET status='accepted' WHERE id=?", (int(req_id),))
                db.commit(); db.backup_now()
            except Exception: pass
        # Notify customer
        send_tg(tid,
            f"✅ *Payment Accepted!*\n\n"
            f"Dear *{name}* Sir,\n"
            f"Aapka ₹{amt} ka deposit *{site}* ke liye verify ho gaya!\n\n"
            f"⏳ Aapki ID abhi bhej di jayegi. Thoda wait karein 🙏")
        flash(f"✅ Accepted! Ab ID daalo aur 📤 Send karo.", "success")

    elif action == "decline":
        update_payment_cache(req_id, status="declined")
        if not is_cache_only:
            try:
                db.execute("UPDATE users SET status='declined' WHERE id=?", (int(req_id),))
                db.commit(); db.backup_now()
            except Exception: pass
        send_tg(tid,
            f"❌ *Payment Nahi Mili Sir*\n\n"
            f"Dear *{name}* Sir,\n\n"
            f"Zyada jaankari ke liye yahan contact karein:\n"
            f"👉 https://wa.me/919520668248\n\n"
            f"Dobara try karne ke liye /start karein 🙏")
        flash(f"❌ Declined. Customer notify kar diya.", "success")

    return redirect(url_for("payments"))


@app.route("/admin/payment/manual_add", methods=["POST"])
@login_required
def payment_manual_add():
    name        = request.form.get("name","").strip()
    phone       = request.form.get("phone","").strip()
    telegram_id = request.form.get("telegram_id","").strip()
    site        = request.form.get("site","Laser247")
    id_type     = request.form.get("id_type","new")
    amount      = request.form.get("amount","").strip()
    utr         = request.form.get("utr","").strip()
    if not all([name, telegram_id, amount, utr]):
        flash("⚠️ Name, Telegram ID, Amount aur UTR zaroori hain.", "error")
        return redirect(url_for("payments"))
    try:
        tid = int(telegram_id)
    except ValueError:
        flash("⚠️ Sahi Telegram ID daalo (sirf numbers).", "error")
        return redirect(url_for("payments"))
    try:
        db.execute(
            "INSERT INTO users (telegram_id,name,phone,site,id_type,amount,utr,status) VALUES (?,?,?,?,?,?,?,?)",
            (tid, name, phone, site, id_type, amount, utr, "pending")
        )
        db.commit()
        db.backup_now()
        # Cache with DB id
        try:
            if db.is_pg:
                row = db.execute("SELECT id FROM users WHERE telegram_id=%s AND utr=%s ORDER BY id DESC LIMIT 1",(tid,utr)).fetchone()
            else:
                row = db.execute("SELECT last_insert_rowid() AS id").fetchone()
            cid = str(row["id"]) if row else f"c_{tid}_{int(time.time()*1000)}"
        except Exception:
            cid = f"c_{tid}_{int(time.time()*1000)}"
    except Exception:
        cid = f"c_{tid}_{int(time.time()*1000)}"
    cache_payment(cid, tid, name, phone, site, id_type, amount, utr)
    flash(f"✅ Payment manually add hua — {name} | ₹{amount} | UTR: {utr}", "success")
    return redirect(url_for("payments"))


@app.route("/admin/payment/send_id", methods=["POST"])
@login_required
def send_id():
    req_id  = request.form.get("req_id", "").strip()
    id_pass = request.form.get("id_pass", "").strip()
    if not id_pass:
        flash("⚠️ Pehle ID:Password daalo.", "error")
        return redirect(url_for("payments"))

    is_cache_only = req_id.startswith("c_")

    # Get entry from cache first
    entry = None
    with _PAY_LOCK:
        entry = dict(PAYMENT_CACHE.get(req_id, {}))

    if not entry and not is_cache_only:
        try:
            row = db.execute("SELECT * FROM users WHERE id=?", (int(req_id),)).fetchone()
            if row:
                entry = {"telegram_id": row["telegram_id"], "name": row["name"],
                         "site": row["site"], "cache_id": req_id}
        except Exception: pass

    if not entry:
        flash("⚠️ Payment request nahi mila.", "error")
        return redirect(url_for("payments"))

    tid  = entry["telegram_id"]
    name = entry.get("name", "Sir")
    site = entry.get("site", "?")

    # Update cache + DB
    update_payment_cache(req_id, id_pass=id_pass, status="accepted")
    if not is_cache_only:
        try:
            db.execute("UPDATE users SET id_pass=?,status='accepted' WHERE id=?",
                       (id_pass, int(req_id)))
            db.commit(); db.backup_now()
        except Exception: pass

    # Message 1 — ID details
    send_tg(tid,
        f"🎉 *Aapki ID Ready Hai Sir!*\n\n"
        f"🌐 Site: *{site}*\n"
        f"🔑 *ID / Password:* `{id_pass}`\n\n"
        f"Thank you for choosing Laser Panel 🙏")

    # Message 2 — Deposit info
    send_tg(tid,
        "🔴✨ LASER247 OFFICIAL SERVICE ✨🔴\n\n"
        "⚡ Fast • Secure • Trusted | तेज • सुरक्षित • भरोसेमंद ⚡\n\n"
        "💰 💎 LASER247 Deposit Zone 💎\n\n"
        "To make a deposit, click below:\n"
        "जमा करने के लिए नीचे क्लिक करें:\n"
        "👉 +91 63675 88380\n\n"
        "🚀 Instant Response | तुरंत जवाब | 24×7 Active\n\n"
        "💸 ⚡ LASER247 Withdrawal Desk ⚡\n\n"
        "To request a withdrawal, click below:\n"
        "पैसे निकालने के लिए नीचे क्लिक करें:\n"
        "👉 https://wa.me/message/L3W6KCQNVSMTP1\n\n"
        "🔐 Safe & Secure Transactions | सुरक्षित लेन-देन की गारंटी")

    # Message 3 — Customer Support
    send_tg(tid,
        "🔴✨ LASER247 CUSTOMER SUPPORT ✨🔴\n\n"
        "📞 🎧 24×7 Customer Care Service 🎧\n"
        "For any help or support, contact below:\n"
        "किसी भी सहायता या जानकारी के लिए नीचे संपर्क करें:\n\n"
        "👉 https://wa.me/919520668248\n\n"
        "⚡ Quick Response | तेज जवाब | हमेशा उपलब्ध\n\n"
        "🛡️ Trusted Support | भरोसेमंद सेवा")

    flash(f"✅ ID bhej diya — {name} ko!", "success")
    return redirect(url_for("payments"))


# ══════════════════════════════════════════════════════
#  REGISTRATIONS
# ══════════════════════════════════════════════════════

@app.route("/admin/registrations")
@admin_only
def registrations():
    date_filter = request.args.get("date", date.today().isoformat())
    rows = db.execute(
        "SELECT * FROM users WHERE DATE(created_at)=? ORDER BY id DESC", (date_filter,)
    ).fetchall()

    rows_html = ""
    for r in rows:
        badge = {"pending":"badge-pending","accepted":"badge-accepted","declined":"badge-declined"}.get(r["status"],"badge-pending")
        rows_html += f"""<tr>
          <td style="color:var(--muted)">#{r["id"]}</td>
          <td style="font-weight:600">{r["name"] or "—"}</td>
          <td style="color:var(--muted)">{r["phone"] or "—"}</td>
          <td>{r["site"] or "—"}</td>
          <td><span class="badge badge-new">{(r["id_type"] or "new").upper()}</span></td>
          <td style="color:var(--green);font-weight:700">₹{r["amount"] or 0}</td>
          <td><span class="badge {badge}">{r["status"].upper()}</span></td>
          <td style="color:var(--muted);font-size:.77rem">{fmt_dt(r["created_at"], "time")}</td>
        </tr>"""

    content = f"""
<div class="topbar">
  <div class="page-title">Registrations</div>
  <div class="topbar-right">
    <form method="GET" style="display:flex;gap:8px">
      <input type="date" name="date" value="{date_filter}"
             class="form-input" style="width:155px;padding:8px 12px">
      <button type="submit" class="btn btn-primary btn-sm">Filter</button>
    </form>
  </div>
</div>
<div style="margin-bottom:14px;color:var(--muted);font-size:.84rem">
  <strong style="color:var(--text)">{len(rows)}</strong> registrations on {date_filter}
</div>
<div class="table-wrap"><table>
  <thead><tr><th>#</th><th>Name</th><th>Phone</th><th>Site</th>
    <th>Type</th><th>Amount</th><th>Status</th><th>Time</th></tr></thead>
  <tbody>
    {rows_html if rows_html else f'<tr><td colspan="8" class="empty">No registrations on {date_filter}</td></tr>'}
  </tbody>
</table></div>"""
    return page("Registrations", content, "registrations")


# ══════════════════════════════════════════════════════
#  CHATS — Customer chat history + manual message
#  Primary source: in-memory CHAT_CACHE (always works)
#  Fallback: DB chat_logs + users table
# ══════════════════════════════════════════════════════

def _build_chat_list():
    """Merge CHAT_CACHE + DB + users table → unified list sorted by last activity."""
    merged = {}   # {str(tid): {user_name, msg_count, last_msg, last_time, from_cache}}

    # 1. In-memory cache (most fresh, always available)
    with _CACHE_LOCK:
        cache_copy = dict(CHAT_CACHE)
    for tid_s, data in cache_copy.items():
        msgs = data.get("messages", [])
        cust_msgs = [m["message"] for m in msgs if m["sender"] == "customer"]
        merged[tid_s] = {
            "user_name":  data.get("user_name", "Unknown"),
            "msg_count":  len(msgs),
            "last_msg":   cust_msgs[-1][:60] if cust_msgs else (msgs[-1]["message"][:60] if msgs else ""),
            "last_time":  msgs[-1]["ts"] if msgs else "",
            "from_cache": True,
        }

    # 2. DB chat_logs (may have older history)
    try:
        db_rows = db.execute("""
            SELECT telegram_id, MAX(user_name) AS uname, COUNT(*) AS cnt,
                   MAX(CASE WHEN sender='customer' THEN message END) AS last_cust
            FROM chat_logs GROUP BY telegram_id ORDER BY MAX(created_at) DESC LIMIT 200
        """).fetchall()
        for r in db_rows:
            tid_s = str(r["telegram_id"])
            if tid_s not in merged:
                merged[tid_s] = {
                    "user_name": r["uname"] or "Unknown",
                    "msg_count": r["cnt"],
                    "last_msg":  (r["last_cust"] or "")[:60],
                    "last_time": "",
                    "from_cache": False,
                }
    except Exception:
        pass

    # 3. Payment users (customers who talked to bot)
    try:
        pay_rows = db.execute(
            "SELECT telegram_id, name FROM users ORDER BY id DESC LIMIT 200"
        ).fetchall()
        for r in pay_rows:
            tid_s = str(r["telegram_id"])
            if tid_s not in merged:
                merged[tid_s] = {
                    "user_name": r["name"] or "Unknown",
                    "msg_count": 0,
                    "last_msg":  "💰 Payment request",
                    "last_time": "",
                    "from_cache": False,
                }
            elif not merged[tid_s]["user_name"] or merged[tid_s]["user_name"] == "Unknown":
                merged[tid_s]["user_name"] = r["name"] or merged[tid_s]["user_name"]
    except Exception:
        pass

    return merged


@app.route("/admin/chats")
@admin_only
def chats():
    merged = _build_chat_list()

    rows_html = ""
    for tid_s, data in merged.items():
        name  = data["user_name"] or "Unknown"
        cnt   = data["msg_count"]
        last  = data["last_msg"] or "—"
        t     = data["last_time"]
        live  = "🟢 " if data["from_cache"] else ""
        rows_html += f"""
<a href="/admin/chats/{tid_s}" style="text-decoration:none">
<div class="chat-row">
  <div class="chat-avatar">{name[0].upper() if name else "?"}</div>
  <div class="chat-info">
    <div class="chat-name">{live}{name}
      <span style="font-size:11px;color:var(--muted);margin-left:6px">ID: {tid_s}</span>
    </div>
    <div class="chat-last">{last}</div>
  </div>
  <div class="chat-meta">
    <div class="chat-time">{t}</div>
    <div class="chat-badge">{cnt} msgs</div>
  </div>
</div></a>"""

    dm_form = """
<div style="background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:18px;margin-bottom:22px">
  <div style="font-weight:700;font-size:15px;margin-bottom:12px">
    📤 Kisi bhi Customer ko Direct Message Bhejo
  </div>
  <form method="POST" action="/admin/chats/send_direct"
    style="display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end">
    <input name="chat_id" placeholder="Telegram ID (jaise: 123456789)"
      style="background:var(--bg);border:1px solid var(--border);color:var(--text);
        border-radius:8px;padding:9px 14px;font-size:14px;width:210px">
    <textarea name="msg" rows="2" placeholder="Message likhein..."
      style="flex:1;min-width:200px;background:var(--bg);border:1px solid var(--border);
        color:var(--text);border-radius:8px;padding:9px 14px;font-size:14px;
        resize:none;font-family:inherit"></textarea>
    <button type="submit" class="btn btn-primary" style="height:44px;padding:0 22px;white-space:nowrap">
      ✉️ Send
    </button>
  </form>
</div>"""

    empty = """<div style="text-align:center;color:var(--muted);padding:60px 20px">
<div style="font-size:40px;margin-bottom:12px">💬</div>
<div>Abhi koi chat nahi hai.<br>
<span style="font-size:13px">Jab customer bot pe /start karega, yahan turant dikhega.</span>
</div></div>"""

    total = len(merged)
    live_cnt = sum(1 for d in merged.values() if d["from_cache"])

    content = f"""
<style>
.chat-row{{display:flex;align-items:center;gap:14px;padding:14px 16px;background:var(--card);
  border:1px solid var(--border);border-radius:10px;margin-bottom:8px;cursor:pointer;transition:.2s}}
.chat-row:hover{{border-color:var(--blue);background:#0f1830}}
.chat-avatar{{width:46px;height:46px;border-radius:50%;background:var(--blue2);
  display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;
  color:#fff;flex-shrink:0;text-transform:uppercase}}
.chat-info{{flex:1;min-width:0}}
.chat-name{{font-weight:600;font-size:15px;color:var(--text)}}
.chat-last{{font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;margin-top:3px;max-width:300px}}
.chat-meta{{text-align:right;flex-shrink:0}}
.chat-time{{font-size:12px;color:var(--muted)}}
.chat-badge{{background:var(--blue);color:#fff;border-radius:12px;font-size:11px;
  padding:2px 8px;margin-top:4px;display:inline-block}}
</style>
<div class="topbar">
  <div class="page-title">Chats <span>— Customer Messages</span></div>
  <div class="topbar-right" style="display:flex;gap:10px;align-items:center">
    <span style="color:var(--green);font-size:13px">🟢 {live_cnt} live</span>
    <span style="color:var(--muted);font-size:13px">{total} total</span>
  </div>
</div>
{dm_form}
{rows_html if rows_html else empty}
<script>setTimeout(function(){{location.reload()}}, 15000);</script>"""
    return page("Chats", content, "chats")


@app.route("/admin/chats/send_direct", methods=["POST"])
@admin_only
def chats_send_direct():
    chat_id_raw = request.form.get("chat_id","").strip()
    msg         = request.form.get("msg","").strip()
    if not chat_id_raw or not msg:
        flash("⚠️ Telegram ID aur message dono bharo.", "error")
        return redirect(url_for("chats"))
    try:
        cid = int(chat_id_raw)
    except ValueError:
        flash("⚠️ Sahi Telegram ID daalo (sirf numbers).", "error")
        return redirect(url_for("chats"))
    send_tg(cid, msg)
    cache_log(cid, "Direct", "bot", f"[Admin] {msg}")
    try:
        db.execute("INSERT INTO chat_logs (telegram_id,user_name,sender,message) VALUES (?,?,?,?)",
                   (cid, "Direct", "bot", f"[Admin] {msg}"))
        db.commit()
    except Exception: pass
    flash(f"✅ Message bhej diya — ID: {cid}", "success")
    return redirect(url_for("chats"))


@app.route("/admin/chats/<tid>")
@admin_only
def chat_detail(tid):
    try:
        tid_int = int(tid)
    except ValueError:
        return redirect(url_for("chats"))

    # ── Messages: cache first, then DB ──────────────────────────────────────
    messages = []
    user_name = "Unknown"

    with _CACHE_LOCK:
        cached = CHAT_CACHE.get(str(tid_int), {})
    if cached:
        user_name = cached.get("user_name", "Unknown")
        for m in cached.get("messages", []):
            messages.append({"sender": m["sender"], "message": m["message"], "ts": m["ts"]})

    if not messages:
        try:
            db_logs = db.execute(
                "SELECT sender,message,created_at FROM chat_logs WHERE telegram_id=? ORDER BY id ASC",
                (tid_int,)).fetchall()
            for r in db_logs:
                messages.append({"sender": r["sender"], "message": r["message"],
                                  "ts": fmt_dt(r["created_at"], "time")})
            if db_logs:
                first = db.execute("SELECT user_name FROM chat_logs WHERE telegram_id=? LIMIT 1",
                                    (tid_int,)).fetchone()
                user_name = (first["user_name"] if first else None) or "Unknown"
        except Exception: pass

    # ── Payment info from users table ────────────────────────────────────────
    phone = site = amount = status = utr = "—"
    try:
        row = db.execute(
            "SELECT name,phone,site,amount,status,utr FROM users WHERE telegram_id=? ORDER BY id DESC LIMIT 1",
            (tid_int,)).fetchone()
        if row:
            if row["name"] and user_name == "Unknown": user_name = row["name"]
            phone  = row["phone"]  or "—"
            site   = row["site"]   or "—"
            amount = row["amount"] or "—"
            status = row["status"] or "—"
            utr    = row["utr"]    or "—"
    except Exception: pass

    info_card = f"""
<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px">
  <div class="card" style="flex:1;min-width:100px;padding:12px">
    <div style="color:var(--muted);font-size:10px">📱 PHONE</div>
    <div style="font-weight:700;font-size:14px;margin-top:4px">{phone}</div>
  </div>
  <div class="card" style="flex:1;min-width:100px;padding:12px">
    <div style="color:var(--muted);font-size:10px">🌐 SITE</div>
    <div style="font-weight:700;font-size:14px;margin-top:4px">{site}</div>
  </div>
  <div class="card" style="flex:1;min-width:100px;padding:12px">
    <div style="color:var(--muted);font-size:10px">💰 AMOUNT</div>
    <div style="font-weight:700;font-size:14px;margin-top:4px;color:var(--green)">₹{amount}</div>
  </div>
  <div class="card" style="flex:1;min-width:100px;padding:12px">
    <div style="color:var(--muted);font-size:10px">📊 STATUS</div>
    <div style="font-weight:700;font-size:14px;margin-top:4px">{(status or "—").upper()}</div>
  </div>
  <div class="card" style="flex:1;min-width:120px;padding:12px">
    <div style="color:var(--muted);font-size:10px">🔢 UTR</div>
    <div style="font-size:12px;margin-top:4px">{utr}</div>
  </div>
</div>"""

    def _bubble(sender, msg, ts):
        msg = str(msg or "").replace("<","&lt;").replace(">","&gt;")
        if sender == "customer":
            return f"""<div style="display:flex;justify-content:flex-end;margin-bottom:8px">
  <div style="max-width:75%;background:#1e40af;color:#fff;padding:10px 14px;
    border-radius:16px 16px 4px 16px;font-size:14px;word-break:break-word">
    {msg}<div style="font-size:10px;color:rgba(255,255,255,.5);margin-top:4px;text-align:right">{ts}</div>
  </div></div>"""
        else:
            label = "👤 Admin" if msg.startswith("[Admin]") else "🤖 Bot"
            clean = msg.replace("[Admin] ","")
            return f"""<div style="display:flex;justify-content:flex-start;margin-bottom:8px">
  <div style="max-width:75%;background:var(--card);border:1px solid var(--border);
    color:var(--text);padding:10px 14px;border-radius:16px 16px 16px 4px;font-size:14px;word-break:break-word">
    <span style="font-size:11px;color:var(--muted)">{label}</span><br>{clean}
    <div style="font-size:10px;color:var(--muted);margin-top:4px">{ts}</div>
  </div></div>"""

    bubbles = "".join(_bubble(m["sender"], m["message"], m["ts"]) for m in messages)
    empty   = '<div style="text-align:center;color:var(--muted);padding:40px">Koi message nahi — abhi shuru hoga</div>'

    content = f"""
<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
  <a href="/admin/chats" class="btn btn-ghost btn-sm">← Back</a>
  <div class="page-title" style="margin:0">{user_name}
    <span style="font-size:13px;color:var(--muted);margin-left:6px">ID: {tid_int}</span>
  </div>
</div>
{info_card}
<div style="max-width:740px;margin:0 auto">
  <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;
    padding:16px 20px;max-height:520px;overflow-y:auto" id="cb">
    {bubbles if bubbles else empty}
  </div>
  <form method="POST" action="/admin/chats/{tid_int}/reply"
    style="display:flex;gap:10px;margin-top:14px;align-items:flex-end">
    <textarea name="msg" rows="2" id="reply-box"
      placeholder="Customer ko reply likhein... (Enter = Send, Shift+Enter = new line)"
      style="flex:1;background:var(--card);border:1px solid var(--border);color:var(--text);
        border-radius:10px;padding:10px 14px;font-size:14px;resize:none;font-family:inherit"></textarea>
    <button type="submit" class="btn btn-primary" style="height:44px;padding:0 22px">
      ✉️ Send
    </button>
  </form>
</div>
<script>
  var cb=document.getElementById('cb');
  if(cb)cb.scrollTop=cb.scrollHeight;
  document.getElementById('reply-box').addEventListener('keydown',function(e){{
    if(e.key==='Enter'&&!e.shiftKey){{e.preventDefault();this.form.submit();}}
  }});
  setTimeout(function(){{location.reload()}},15000);
</script>"""
    return page(f"Chat — {user_name}", content, "chats")


@app.route("/admin/chats/<int:tid>/reply", methods=["POST"])
@admin_only
def chat_reply(tid):
    msg = request.form.get("msg","").strip()
    if not msg:
        flash("⚠️ Kuch likhein pehle!", "error")
        return redirect(f"/admin/chats/{tid}")
    send_tg(tid, f"💬 *Admin:* {msg}")
    cache_log(tid, "Admin", "bot", f"[Admin] {msg}")
    try:
        db.execute("INSERT INTO chat_logs (telegram_id,user_name,sender,message) VALUES (?,?,?,?)",
                   (tid, "Admin", "bot", f"[Admin] {msg}"))
        db.commit()
    except Exception: pass
    flash("✅ Message bhej diya!", "success")
    return redirect(f"/admin/chats/{tid}")


# ══════════════════════════════════════════════════════
#  SUB USERS
# ══════════════════════════════════════════════════════

@app.route("/admin/subusers")
@admin_only
def subusers():
    rows     = db.execute("SELECT * FROM subadmins ORDER BY id DESC").fetchall()
    flashes  = get_flashes()

    rows_html = ""
    for r in rows:
        rows_html += f"""<tr>
          <td>#{r["id"]}</td>
          <td style="font-weight:600">{r["name"]}</td>
          <td style="color:var(--muted)">••••••••</td>
          <td><span class="badge badge-new">Payments Only</span></td>
          <td style="color:var(--muted);font-size:.77rem">{fmt_dt(r["created_at"], "date")}</td>
          <td>
            <form method="POST" action="/admin/subusers/delete" style="display:inline">
              <input type="hidden" name="sub_id" value="{r['id']}">
              <button type="submit" class="btn btn-danger btn-sm"
                onclick="return confirm('Delete {r['name']}?')">🗑 Delete</button>
            </form>
          </td>
        </tr>"""

    content = f"""
<div class="topbar">
  <div class="page-title">Sub Users</div>
  <div class="topbar-right">
    <button class="btn btn-primary"
      onclick="document.getElementById('addModal').classList.add('open')">
      + Add Sub User
    </button>
  </div>
</div>
{flashes}
<div style="margin-bottom:14px;color:var(--muted);font-size:.83rem">
  Sub users can only access the <strong style="color:var(--blue)">Payments</strong> section.
</div>
<div class="table-wrap"><table>
  <thead><tr><th>#</th><th>Username</th><th>Password</th>
    <th>Access Level</th><th>Created</th><th>Action</th></tr></thead>
  <tbody>
    {rows_html if rows_html else '<tr><td colspan="6" class="empty">No sub users yet</td></tr>'}
  </tbody>
</table></div>

<!-- ADD MODAL -->
<div class="modal-overlay" id="addModal">
  <div class="modal">
    <h3>➕ Create Sub User</h3>
    <form method="POST" action="/admin/subusers/add">
      <div class="form-group">
        <label class="form-label">USERNAME</label>
        <input class="form-input" name="name" placeholder="Choose a username" required autofocus>
      </div>
      <div class="form-group">
        <label class="form-label">PASSWORD</label>
        <input class="form-input" name="password" placeholder="Choose a password" required>
      </div>
      <div style="display:flex;gap:10px;margin-top:4px">
        <button type="submit" class="btn btn-primary" style="flex:1">✓ Create</button>
        <button type="button" class="btn btn-ghost" style="flex:1"
          onclick="document.getElementById('addModal').classList.remove('open')">Cancel</button>
      </div>
    </form>
  </div>
</div>"""
    return page("Sub Users", content, "subusers")


@app.route("/admin/subusers/add", methods=["POST"])
@admin_only
def add_subuser():
    name = request.form.get("name","").strip()
    pwd  = request.form.get("password","").strip()
    if not name or not pwd:
        flash("Username and password required.", "error")
    else:
        try:
            db.execute("INSERT INTO subadmins (name,password) VALUES (?,?)", (name, pwd))
            db.commit()
            flash(f"✅ Sub user '{name}' created successfully.", "success")
        except Exception:
            flash("Username already exists.", "error")
    return redirect(url_for("subusers"))


@app.route("/admin/subusers/delete", methods=["POST"])
@admin_only
def delete_subuser():
    db.execute("DELETE FROM subadmins WHERE id=?", (request.form.get("sub_id"),))
    db.commit()
    flash("Sub user deleted.", "success")
    return redirect(url_for("subusers"))


# ══════════════════════════════════════════════════════
#  SETTINGS
# ══════════════════════════════════════════════════════

@app.route("/admin/settings", methods=["GET","POST"])
@admin_only
def settings():
    flashes = get_flashes()
    current_upi = get_upi()

    github_ready = bool(os.environ.get("GITHUB_TOKEN"))

    if request.method == "POST":
        new_upi = request.form.get("upi","").strip()
        if new_upi:
            db.execute("UPDATE settings SET upi=? WHERE id=1", (new_upi,))
            db.commit()
            db.backup_now()
            save_upi_permanent(new_upi)
            flash(f"✅ UPI ID saved: {new_upi} — backup ho gaya!", "success")
            return redirect(url_for("settings"))
        flash("UPI ID cannot be empty.", "error")

    railway_badge = (
        '<span style="color:#22c55e;font-size:.8rem">✅ Permanent save enabled (GitHub backup active)</span>'
        if github_ready else
        '<span style="color:#f59e0b;font-size:.8rem">⚠️ GITHUB_TOKEN set karo Railway mein — data permanent hoga</span>'
    )

    content = f"""
<div class="page-title">Settings</div>
{flashes}
<div class="card" style="max-width:500px">
  <div class="card-label" style="margin-bottom:18px">💳 UPI Payment Settings</div>
  <div class="form-group">
    <label class="form-label">CURRENT UPI ID</label>
    <div style="background:#08101f;border:1px solid var(--border);border-radius:9px;
                padding:12px 16px;color:var(--blue);font-family:monospace;font-size:.92rem">
      {current_upi or "Not configured"}
    </div>
  </div>
  <form method="POST">
    <div class="form-group">
      <label class="form-label">UPDATE UPI ID</label>
      <input class="form-input" name="upi" placeholder="yourname@upi" value="{current_upi}">
    </div>
    <div style="margin-bottom:14px">{railway_badge}</div>
    <button type="submit" class="btn btn-primary">💾 Save UPI ID</button>
  </form>
</div>"""
    return page("Settings", content, "settings")


# ══════════════════════════════════════════════════════
#  API
# ══════════════════════════════════════════════════════

@app.route("/api/send_message", methods=["POST"])
def api_send_message():
    data = request.json or {}
    chat_id = data.get("chat_id")
    text    = data.get("text")
    if not chat_id or not text:
        return jsonify({"ok": False}), 400
    send_tg(chat_id, text)
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
