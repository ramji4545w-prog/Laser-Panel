import os
import sqlite3
import datetime
import requests as http_req
from functools import wraps
from flask import Flask, render_template_string, redirect, request, session, flash

# ═══════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "laser_panel_2024_secret")

TOKEN          = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID  = int(os.environ.get("ADMIN_CHAT_ID", "0"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DEFAULT_UPI    = os.environ.get("UPI_ID", "")
SITE_NAME      = "Laser Panel"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "database.db")

# ═══════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row

def init_db():
    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER, name TEXT, phone TEXT,
        site TEXT, id_type TEXT, amount TEXT, utr TEXT,
        id_pass TEXT, status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    db.execute("""CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY, upi TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS subadmins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE, password TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    db.execute("INSERT OR IGNORE INTO settings (id,upi) VALUES (1,?)", (DEFAULT_UPI,))
    for col in ["id_pass TEXT","id_type TEXT","utr TEXT","phone TEXT","site TEXT"]:
        try: db.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except: pass
    db.commit()

init_db()

def get_upi():
    r = db.execute("SELECT upi FROM settings WHERE id=1").fetchone()
    return r["upi"] if r else DEFAULT_UPI

def send_tg(chat_id, text):
    try:
        http_req.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5)
    except: pass

# ═══════════════════════════════════════════════════════
#  AUTH DECORATORS
# ═══════════════════════════════════════════════════════

def login_required(f):
    @wraps(f)
    def d(*a, **kw):
        if not session.get("logged_in"):
            return redirect("/admin/login")
        if not session.get("role"):          # old session without role → re-login
            session.clear()
            return redirect("/admin/login")
        return f(*a, **kw)
    return d

def admin_only(f):
    @wraps(f)
    def d(*a, **kw):
        if not session.get("logged_in"):
            return redirect("/admin/login")
        if not session.get("role"):
            session.clear()
            return redirect("/admin/login")
        if session.get("role") != "admin":
            flash("⛔ Access denied. Admin only.", "err")
            return redirect("/admin/payments")
        return f(*a, **kw)
    return d

# ═══════════════════════════════════════════════════════
#  DESIGN — CSS
# ═══════════════════════════════════════════════════════

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
:root{--red:#e63946;--red2:#c1121f;--red-glow:rgba(230,57,70,.25);--bg:#080808;
  --bg2:#0e0e0e;--bg3:#141414;--border:#1e1e1e;--text:#e0e0e0;--muted:#555}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}

/* ── SIDEBAR ── */
.sb{width:230px;background:var(--bg2);height:100vh;border-right:1px solid var(--border);
  position:fixed;top:0;left:0;display:flex;flex-direction:column;z-index:100}
.sb-logo{padding:22px 18px 18px;border-bottom:1px solid var(--border)}
.sb-logo .brand{font-size:1.1rem;font-weight:900;letter-spacing:-.5px;
  background:linear-gradient(135deg,var(--red),#ff6b6b);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.sb-logo .sub{font-size:.62rem;color:#333;letter-spacing:2px;text-transform:uppercase;margin-top:3px}
.nav-label{padding:14px 18px 4px;font-size:.58rem;color:#2a2a2a;
  letter-spacing:2.5px;text-transform:uppercase;font-weight:700}
.sb a{display:flex;align-items:center;gap:10px;padding:10px 14px;margin:1px 8px;
  color:#444;text-decoration:none;font-size:.82rem;font-weight:500;
  border-radius:8px;transition:all .18s;border:1px solid transparent;position:relative}
.sb a .ic{font-size:.95rem;width:18px;text-align:center;flex-shrink:0}
.sb a:hover{background:rgba(230,57,70,.07);color:var(--red);border-color:rgba(230,57,70,.12)}
.sb a.on{background:rgba(230,57,70,.1);color:var(--red);border-color:rgba(230,57,70,.18);font-weight:600}
.sb a.on::before{content:'';position:absolute;left:-8px;top:50%;transform:translateY(-50%);
  width:3px;height:22px;background:var(--red);border-radius:0 3px 3px 0}
.sb .sp{flex:1}
.sb .out{padding:10px;border-top:1px solid var(--border)}
.sb .out a{color:#2a2a2a;font-size:.8rem;justify-content:center;margin:0;border-radius:8px}
.sb .out a:hover{color:var(--red);background:rgba(230,57,70,.07)}

/* ── MAIN ── */
.main{margin-left:230px;min-height:100vh}
.topbar{display:flex;justify-content:space-between;align-items:center;
  padding:18px 26px;border-bottom:1px solid var(--border);background:var(--bg2);
  position:sticky;top:0;z-index:50;backdrop-filter:blur(10px)}
.topbar h2{font-size:1rem;font-weight:700;color:#fff}
.topbar .pill{font-size:.68rem;font-weight:700;color:var(--red);letter-spacing:1px;
  background:rgba(230,57,70,.08);border:1px solid rgba(230,57,70,.15);
  padding:4px 12px;border-radius:20px;text-transform:uppercase}
.body{padding:22px 26px}

/* ── ALERTS ── */
.alert{display:flex;align-items:center;gap:8px;padding:10px 14px;border-radius:8px;
  margin-bottom:16px;font-size:.82rem;font-weight:500}
.alert.ok{background:rgba(39,174,96,.08);border:1px solid rgba(39,174,96,.15);color:#27ae60}
.alert.err{background:rgba(230,57,70,.08);border:1px solid rgba(230,57,70,.15);color:#e63946}

/* ── STAT CARDS ── */
.grid{display:grid;gap:14px;margin-bottom:22px}
.g4{grid-template-columns:repeat(auto-fit,minmax(165px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
  padding:18px;cursor:pointer;transition:all .22s;position:relative;overflow:hidden}
.card::after{content:'';position:absolute;bottom:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,var(--red),transparent);opacity:0;transition:.22s}
.card:hover{border-color:rgba(230,57,70,.25);transform:translateY(-2px);
  box-shadow:0 6px 24px rgba(230,57,70,.08)}
.card:hover::after{opacity:1}
.card .cl{font-size:.62rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:1.5px;font-weight:700;margin-bottom:10px}
.card .cn{font-size:1.9rem;font-weight:900;color:var(--red);line-height:1;letter-spacing:-1px}
.card .cs{font-size:.68rem;color:#2a2a2a;margin-top:5px}

/* ── TABLES ── */
.tbl-box{background:var(--bg2);border:1px solid var(--border);border-radius:12px;overflow:hidden}
table{width:100%;border-collapse:collapse}
th{padding:11px 14px;text-align:left;font-size:.62rem;text-transform:uppercase;
  letter-spacing:1.2px;color:var(--muted);font-weight:700;
  background:var(--bg3);border-bottom:1px solid var(--border)}
td{padding:11px 14px;font-size:.83rem;color:#aaa;border-bottom:1px solid #111}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.015)}

/* ── TABS ── */
.tabs{display:flex;gap:6px;margin-bottom:18px;flex-wrap:wrap}
.tab{padding:7px 16px;border:1px solid var(--border);border-radius:20px;
  font-size:.78rem;color:var(--muted);text-decoration:none;transition:all .18s;font-weight:500}
.tab:hover{border-color:rgba(230,57,70,.3);color:var(--red)}
.tab.on{background:rgba(230,57,70,.1);border-color:rgba(230,57,70,.25);
  color:var(--red);font-weight:700}

/* ── BUTTONS ── */
.btn{display:inline-flex;align-items:center;gap:6px;border:none;padding:9px 18px;
  border-radius:9px;cursor:pointer;font-size:.8rem;font-weight:700;
  transition:all .2s;font-family:inherit;letter-spacing:.3px;text-decoration:none}
.btn-primary{background:linear-gradient(135deg,var(--red),var(--red2));color:#fff;
  box-shadow:0 2px 14px var(--red-glow)}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 6px 22px rgba(230,57,70,.45)}
.btn-success{background:rgba(39,174,96,.1);color:#27ae60;border:1px solid rgba(39,174,96,.2)}
.btn-success:hover{background:rgba(39,174,96,.18);transform:translateY(-1px)}
.btn-ghost{background:var(--bg3);color:#444;border:1px solid var(--border)}
.btn-ghost:hover{color:#888;border-color:#333}
.btn-danger{background:rgba(230,57,70,.08);color:var(--red);border:1px solid rgba(230,57,70,.15)}
.btn-danger:hover{background:rgba(230,57,70,.15)}
.btn-xs{padding:5px 11px;font-size:.73rem;border-radius:7px}

/* ── INPUTS ── */
input[type=text],input[type=password],input[type=date]{
  background:var(--bg3);border:1px solid var(--border);color:#fff;
  border-radius:8px;padding:9px 13px;font-size:.85rem;outline:none;
  font-family:inherit;transition:all .18s;width:100%}
input:focus{border-color:rgba(230,57,70,.4);box-shadow:0 0 0 3px rgba(230,57,70,.06)}

/* ── BADGES ── */
.bge{display:inline-block;padding:3px 9px;border-radius:20px;
  font-size:.64rem;font-weight:800;text-transform:uppercase;letter-spacing:.8px}
.bge-p{background:rgba(245,166,35,.1);color:#f5a623;border:1px solid rgba(245,166,35,.2)}
.bge-a{background:rgba(39,174,96,.1);color:#27ae60;border:1px solid rgba(39,174,96,.2)}
.bge-d{background:rgba(230,57,70,.1);color:var(--red);border:1px solid rgba(230,57,70,.2)}

/* ── PAYMENT CARDS ── */
.pcard{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
  padding:18px;margin-bottom:10px;transition:all .2s}
.pcard:hover{border-color:rgba(230,57,70,.18);box-shadow:0 4px 18px rgba(230,57,70,.05)}
.pcard-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.pid{font-size:.65rem;color:#333;background:var(--bg3);border:1px solid var(--border);
  padding:2px 8px;border-radius:4px;font-family:monospace}
.pinfo{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px}
.pinfo .pi{font-size:.82rem;color:#777}
.pinfo .pi b{color:#ccc;font-weight:500}
.pinfo .amt{color:#27ae60;font-weight:800;font-size:.9rem}
.pmeta{font-size:.72rem;color:#333;border-top:1px solid #111;padding-top:8px;margin-top:2px}
.pacts{display:flex;gap:8px;margin-top:12px;align-items:center;flex-wrap:wrap}
.pacts form{display:flex;gap:6px;align-items:center}
.idsent{background:rgba(74,144,226,.05);border:1px solid rgba(74,144,226,.12);
  border-radius:8px;padding:8px 12px;font-size:.78rem;color:#4a90e2;margin-bottom:6px}

/* ── SETTINGS BOX ── */
.sbox{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
  padding:20px;margin-bottom:14px;max-width:500px}
.sbox h3{font-size:.78rem;font-weight:800;text-transform:uppercase;letter-spacing:1.2px;
  color:var(--red);margin-bottom:4px}
.sbox p{font-size:.75rem;color:#333;margin-bottom:14px}

/* ── FILTER BAR ── */
.fbar{display:flex;align-items:center;gap:10px;margin-bottom:18px;flex-wrap:wrap;
  background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:12px 16px}
.fbar label{font-size:.65rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:1.5px;font-weight:700;white-space:nowrap}
.fbar input[type=date]{width:auto;padding:7px 10px}

/* ── EMPTY ── */
.empty{text-align:center;padding:50px;color:#222}
.empty .ei{font-size:2.8rem;margin-bottom:10px;filter:grayscale(1)}
.empty .et{font-size:.88rem}

@media(max-width:700px){.sb{display:none}.main{margin-left:0}.pinfo{grid-template-columns:1fr}}
"""

# ═══════════════════════════════════════════════════════
#  LAYOUT
# ═══════════════════════════════════════════════════════

def sidebar_links(active, role):
    links = ""
    if role == "admin":
        links += nav("📊", "Dashboard",    "/admin/",              active=="dash")
        links += nav("📅", "Today",        "/admin/today",         active=="today")
        links += '<div class="nav-label">Manage</div>'
        links += nav("💳", "Payments",     "/admin/payments",      active=="pay")
        links += nav("👤", "Registrations","/admin/registrations", active=="reg")
        links += nav("💰", "Deposits",     "/admin/deposits",      active=="dep")
        links += '<div class="nav-label">Admin</div>'
        links += nav("👥", "Sub Users",    "/admin/subusers",      active=="sub")
        links += nav("⚙️", "Settings",     "/admin/settings",      active=="set")
    else:
        links += '<div class="nav-label">Access</div>'
        links += nav("💳", "Payments", "/admin/payments", True)
    return links

def nav(ic, label, href, is_on):
    return f'<a href="{href}" class="{"on" if is_on else ""}"><span class="ic">{ic}</span> {label}</a>'

def page(title, active, body):
    role     = session.get("role","admin")
    username = session.get("username","Admin")
    flashes  = ""
    for cat, msg in session.get("_flashes", []):
        flashes += f'<div class="alert {cat}">{msg}</div>'

    return render_template_string(f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · {SITE_NAME}</title>
<style>{CSS}</style>
<script>function go(u){{location.href=u}}</script>
</head>
<body style="display:flex">
<div class="sb">
  <div class="sb-logo">
    <div class="brand">🔥 {SITE_NAME}</div>
    <div class="sub">Control Panel</div>
  </div>
  {sidebar_links(active, role)}
  <div class="sp"></div>
  <div class="out">
    <a href="/admin/logout">🚪 Logout &nbsp;<small style="color:#222">({username})</small></a>
  </div>
</div>
<div class="main">
  <div class="topbar">
    <h2>{title}</h2>
    <div class="pill">{SITE_NAME}</div>
  </div>
  <div class="body">
    {{% with messages = get_flashed_messages(with_categories=true) %}}
      {{% for cat,msg in messages %}}
        <div class="alert {{{{cat}}}}">{{{{msg}}}}</div>
      {{% endfor %}}
    {{% endwith %}}
    {body}
  </div>
</div>
</body>
</html>""")


# ═══════════════════════════════════════════════════════
#  LOGIN PAGE
# ═══════════════════════════════════════════════════════

LOGIN_HTML = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login · {SITE_NAME}</title>
<style>
{CSS}
body{{display:flex;align-items:center;justify-content:center;min-height:100vh;
  background:radial-gradient(ellipse 80% 60% at 50% 0%,rgba(230,57,70,.1) 0%,var(--bg) 65%)}}
.wrap{{width:100%;max-width:380px;padding:16px}}
.box{{background:var(--bg2);border:1px solid var(--border);border-radius:16px;
  padding:36px 30px;position:relative;overflow:hidden}}
.box::before{{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent,var(--red),transparent)}}
.logo{{text-align:center;margin-bottom:30px}}
.logo .name{{font-size:1.6rem;font-weight:900;letter-spacing:-1px;
  background:linear-gradient(135deg,var(--red),#ff6b6b 60%,var(--red));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
.logo .tag{{font-size:.65rem;color:#2a2a2a;letter-spacing:3px;text-transform:uppercase;margin-top:5px}}
.lbl{{display:block;font-size:.65rem;color:#333;text-transform:uppercase;
  letter-spacing:1.5px;font-weight:700;margin-bottom:7px}}
.fi{{margin-bottom:14px}}
.fi input{{background:#0a0a0a;border:1px solid #1a1a1a}}
.fi input:focus{{border-color:rgba(230,57,70,.5)}}
.login-btn{{width:100%;padding:13px;margin-top:6px;font-size:.9rem;font-weight:800;
  background:linear-gradient(135deg,var(--red),var(--red2));color:#fff;border:none;
  border-radius:10px;cursor:pointer;font-family:inherit;letter-spacing:.5px;
  box-shadow:0 4px 24px rgba(230,57,70,.35);transition:all .2s}}
.login-btn:hover{{transform:translateY(-2px);box-shadow:0 8px 32px rgba(230,57,70,.5)}}
.err-box{{background:rgba(230,57,70,.06);border:1px solid rgba(230,57,70,.15);
  color:#e63946;border-radius:8px;padding:10px 14px;font-size:.8rem;margin-bottom:16px}}
.foot{{text-align:center;color:#1a1a1a;font-size:.68rem;margin-top:22px;letter-spacing:1px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="box">
    <div class="logo">
      <div class="name">🔥 {SITE_NAME}</div>
      <div class="tag">Authorized Access Only</div>
    </div>
    {{% if error %}}<div class="err-box">❌ {{{{ error }}}}</div>{{% endif %}}
    <form method="post">
      <div class="fi"><label class="lbl">Username</label>
        <input type="text" name="username" placeholder="Enter username" autocomplete="off" required></div>
      <div class="fi"><label class="lbl">Password</label>
        <input type="password" name="password" placeholder="Enter password" required></div>
      <button type="submit" class="login-btn">⚡ LOGIN</button>
    </form>
    <div class="foot">© {SITE_NAME} · Secure Panel</div>
  </div>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════

@app.route("/admin/login", methods=["GET","POST"])
def login():
    if session.get("logged_in") and session.get("role"):
        return redirect("/admin/")
    error = None
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","").strip()
        if u.lower() == "admin" and p == ADMIN_PASSWORD:
            session.clear()
            session.update(logged_in=True, role="admin", username="Admin")
            return redirect("/admin/")
        sub = db.execute("SELECT * FROM subadmins WHERE name=? AND password=?", (u,p)).fetchone()
        if sub:
            session.clear()
            session.update(logged_in=True, role="subadmin", username=u)
            return redirect("/admin/payments")
        error = "Invalid username or password."
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect("/admin/login")


# ── Dashboard ──────────────────────────────────────────

@app.route("/admin/")
@app.route("/admin")
@admin_only
def dashboard():
    today = datetime.date.today().isoformat()
    df = request.args.get("date","")
    wd  = f"WHERE date(created_at)='{df}'" if df else ""
    wda = f"WHERE status='accepted' AND date(created_at)='{df}'" if df else "WHERE status='accepted'"

    s = {
        "treg": db.execute(f"SELECT COUNT(*) FROM users {wd}").fetchone()[0],
        "tdep": db.execute(f"SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM users {wda}").fetchone()[0],
        "dreg": db.execute(f"SELECT COUNT(*) FROM users WHERE date(created_at)='{today}'").fetchone()[0],
        "ddep": db.execute(f"SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM users WHERE status='accepted' AND date(created_at)='{today}'").fetchone()[0],
        "pen":  db.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0],
        "acc":  db.execute("SELECT COUNT(*) FROM users WHERE status='accepted'").fetchone()[0],
        "dec":  db.execute("SELECT COUNT(*) FROM users WHERE status='declined'").fetchone()[0],
    }
    heading = f"Showing: {df}" if df else "All Time"
    body = f"""
<div class="fbar">
  <label>📅 Date Filter</label>
  <form method="get" style="display:flex;gap:8px;align-items:center">
    <input type="date" name="date" value="{df}" max="{today}" style="width:auto">
    <button class="btn btn-primary btn-xs">Filter</button>
    {'<a href="/admin/" class="btn btn-ghost btn-xs">Clear</a>' if df else ""}
  </form>
  <span style="font-size:.72rem;color:#2a2a2a">{heading}</span>
</div>

<div style="font-size:.62rem;color:#2a2a2a;text-transform:uppercase;letter-spacing:2px;margin-bottom:10px">Today</div>
<div class="grid g4" style="margin-bottom:20px">
  <div class="card" onclick="go('/admin/today')">
    <div class="cl">Today Registrations</div><div class="cn">{s['dreg']}</div>
    <div class="cs">New IDs today</div></div>
  <div class="card" onclick="go('/admin/today')">
    <div class="cl">Today Deposits</div><div class="cn" style="color:#27ae60">₹{s['ddep']}</div>
    <div class="cs">Collected today</div></div>
  <div class="card" onclick="go('/admin/payments?f=pending')">
    <div class="cl">Pending</div><div class="cn" style="color:#f5a623">{s['pen']}</div>
    <div class="cs">Awaiting review</div></div>
</div>

<div style="font-size:.62rem;color:#2a2a2a;text-transform:uppercase;letter-spacing:2px;margin-bottom:10px">{heading}</div>
<div class="grid g4">
  <div class="card" onclick="go('/admin/registrations')">
    <div class="cl">Total Registrations</div><div class="cn">{s['treg']}</div>
    <div class="cs">All users</div></div>
  <div class="card" onclick="go('/admin/deposits')">
    <div class="cl">Total Deposits</div><div class="cn" style="color:#27ae60">₹{s['tdep']}</div>
    <div class="cs">Total collected</div></div>
  <div class="card" onclick="go('/admin/payments?f=accepted')">
    <div class="cl">Accepted</div><div class="cn" style="color:#27ae60">{s['acc']}</div>
    <div class="cs">Processed</div></div>
  <div class="card" onclick="go('/admin/payments?f=declined')">
    <div class="cl">Declined</div><div class="cn" style="color:#e63946">{s['dec']}</div>
    <div class="cs">Rejected</div></div>
</div>
"""
    return page("Dashboard","dash",body)


# ── Today ──────────────────────────────────────────────

@app.route("/admin/today")
@admin_only
def today():
    t = datetime.date.today().isoformat()
    regs = db.execute(
        "SELECT name,phone,site,id_type,created_at FROM users WHERE date(created_at)=? ORDER BY id DESC",(t,)).fetchall()
    deps = db.execute(
        "SELECT name,phone,site,amount,created_at FROM users WHERE status='accepted' AND date(created_at)=? ORDER BY id DESC",(t,)).fetchall()
    tot = sum(float(r["amount"] or 0) for r in deps)

    def rows_html(rs, cols, fns):
        if not rs:
            return f"<tr><td colspan='{len(cols)}' style='text-align:center;color:#222;padding:30px'>No data for today</td></tr>"
        return "".join(f"<tr>" + "".join(f"<td>{fn(r)}</td>" for fn in fns) + "</tr>" for r in rs)

    reg_trs = rows_html(regs, 5, [
        lambda r: f"<b>{r['name']}</b>", lambda r: r['phone'],
        lambda r: r['site'], lambda r: f"<span class='bge bge-a'>{(r['id_type'] or 'N/A').upper()}</span>",
        lambda r: str(r['created_at'])[:16]])
    dep_trs = rows_html(deps, 5, [
        lambda r: f"<b>{r['name']}</b>", lambda r: r['phone'],
        lambda r: r['site'], lambda r: f"<b style='color:#27ae60'>₹{r['amount']}</b>",
        lambda r: str(r['created_at'])[:16]])

    body = f"""
<div class="grid g3" style="margin-bottom:22px">
  <div class="card"><div class="cl">Today Registrations</div>
    <div class="cn">{len(regs)}</div><div class="cs">{t}</div></div>
  <div class="card"><div class="cl">Today Deposits</div>
    <div class="cn" style="color:#27ae60">₹{tot}</div><div class="cs">Accepted only</div></div>
</div>

<div style="margin-bottom:22px">
  <div style="font-size:.7rem;font-weight:800;text-transform:uppercase;letter-spacing:1.5px;
    color:#e63946;margin-bottom:10px">📋 Registrations Today ({len(regs)})</div>
  <div class="tbl-box">
    <table><tr><th>Name</th><th>Phone</th><th>Site</th><th>Type</th><th>Time</th></tr>
    {reg_trs}</table>
  </div>
</div>

<div>
  <div style="font-size:.7rem;font-weight:800;text-transform:uppercase;letter-spacing:1.5px;
    color:#27ae60;margin-bottom:10px">💰 Deposits Today — ₹{tot}</div>
  <div class="tbl-box">
    <table><tr><th>Name</th><th>Phone</th><th>Site</th><th>Amount</th><th>Time</th></tr>
    {dep_trs}</table>
  </div>
</div>
"""
    return page("Today Overview","today",body)


# ── Payments ───────────────────────────────────────────

@app.route("/admin/payments")
@login_required
def payments():
    f = request.args.get("f","pending")
    rows = (db.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
            if f=="all" else
            db.execute("SELECT * FROM users WHERE status=? ORDER BY id DESC",(f,)).fetchall())

    tabs = "".join(
        f'<a class="tab {"on" if f==k else ""}" href="/admin/payments?f={k}">{l}</a>'
        for l,k in [("⏳ Pending","pending"),("✅ Accepted","accepted"),("❌ Declined","declined"),("All","all")])

    cards = ""
    for u in rows:
        idsent = f'<div class="idsent">✅ ID Sent: <code>{u["id_pass"]}</code></div>' if u["id_pass"] else ""
        if u["status"]=="pending":
            act = f"""<div class="pacts">
  <form method="post" action="/admin/accept/{u['id']}">
    <button class="btn btn-success btn-xs">✅ Accept</button></form>
  <form method="post" action="/admin/decline/{u['id']}">
    <button class="btn btn-ghost btn-xs">❌ Decline</button></form>
</div>"""
        elif u["status"]=="accepted" and not u["id_pass"]:
            act = f"""<div class="pacts" style="width:100%">
  <form method="post" action="/admin/sendid/{u['id']}"
    style="display:flex;gap:8px;align-items:center;flex:1;flex-wrap:wrap">
    <input type="text" name="idpass" placeholder="ID: user123   Pass: pass@123" required style="flex:1;min-width:200px">
    <button class="btn btn-primary btn-xs">🎯 Send ID</button>
  </form>
</div>"""
        else:
            act = ""

        bge_cls = {"pending":"bge-p","accepted":"bge-a","declined":"bge-d"}.get(u["status"],"")
        cards += f"""<div class="pcard">
  <div class="pcard-head">
    <span style="font-weight:700;font-size:.88rem">💳 Request</span>
    <div style="display:flex;gap:8px;align-items:center">
      <span class="pid">#{u['id']}</span>
      <span class="bge {bge_cls}">{u['status']}</span>
    </div>
  </div>
  <div class="pinfo">
    <div class="pi">👤 <b>{u['name']}</b></div>
    <div class="pi">📱 <b>{u['phone']}</b></div>
    <div class="pi">🌐 {u['site']} <span style="color:#2a2a2a;font-size:.72rem">({(u['id_type'] or 'N/A').upper()})</span></div>
    <div class="pi amt">💰 ₹{u['amount']}</div>
  </div>
  <div class="pmeta">🔢 UTR: {u['utr'] or '—'} &nbsp;·&nbsp; 🕐 {str(u['created_at'])[:16] if u['created_at'] else '—'}</div>
  {idsent}{act}
</div>"""

    if not rows:
        cards = '<div class="empty"><div class="ei">🔍</div><div class="et">No requests here</div></div>'

    body = f"""
<div class="tabs">{tabs}</div>
<div style="font-size:.62rem;color:#2a2a2a;text-transform:uppercase;letter-spacing:2px;margin-bottom:14px">{len(rows)} request(s)</div>
{cards}"""
    return page("Payments","pay",body)


@app.route("/admin/accept/<int:rid>", methods=["POST"])
@login_required
def accept(rid):
    r = db.execute("SELECT * FROM users WHERE id=?",(rid,)).fetchone()
    if not r or r["status"]!="pending":
        flash("Not found or already processed.","err")
        return redirect("/admin/payments")
    db.execute("UPDATE users SET status='accepted' WHERE id=?",(rid,))
    db.commit()
    send_tg(r["telegram_id"],
        "✅ *Payment Received Sir!*\n\nYour payment has been verified ✔\nPlease wait 2–5 minutes — your ID is being processed. 🙏")
    flash(f"✅ #{rid} accepted — now send the ID from Accepted tab.","ok")
    return redirect("/admin/payments?f=accepted")


@app.route("/admin/sendid/<int:rid>", methods=["POST"])
@login_required
def sendid(rid):
    idpass = request.form.get("idpass","").strip()
    if not idpass:
        flash("Please enter ID & Password.","err")
        return redirect("/admin/payments?f=accepted")
    r = db.execute("SELECT * FROM users WHERE id=?",(rid,)).fetchone()
    if not r:
        flash("Request not found.","err")
        return redirect("/admin/payments?f=accepted")
    db.execute("UPDATE users SET id_pass=? WHERE id=?",(idpass,rid))
    db.commit()
    send_tg(r["telegram_id"],
        f"🎯 *Sir, Your ID is Ready!*\n\n"
        f"🌐 Site: *{r['site']}*\n\n"
        f"📋 Login Details:\n`{idpass}`\n\n"
        f"⚠️ Do NOT share this with anyone.")
    send_tg(r["telegram_id"],
        f"🔴 *LASER PANEL — OFFICIAL* 🔴\n\n"
        f"⚡ Instant • 🔒 Secure • ✅ Trusted\n\n"
        f"Thank you Sir! For support contact admin. 🙏")
    flash(f"🎯 ID sent to user for request #{rid}.","ok")
    return redirect("/admin/payments?f=accepted")


@app.route("/admin/decline/<int:rid>", methods=["POST"])
@login_required
def decline(rid):
    r = db.execute("SELECT * FROM users WHERE id=?",(rid,)).fetchone()
    if not r or r["status"]!="pending":
        flash("Not found or already processed.","err")
        return redirect("/admin/payments")
    db.execute("UPDATE users SET status='declined' WHERE id=?",(rid,))
    db.commit()
    send_tg(r["telegram_id"],
        "❌ *Payment Not Verified Sir.*\n\n"
        "We could not verify your payment.\n"
        "Please check your UTR number and try again with /start.")
    flash(f"❌ Request #{rid} declined.","ok")
    return redirect("/admin/payments?f=pending")


# ── Registrations ──────────────────────────────────────

@app.route("/admin/registrations")
@admin_only
def registrations():
    today = datetime.date.today().isoformat()
    df = request.args.get("date","")
    rows = (db.execute("SELECT name,phone,site,id_type,created_at FROM users WHERE date(created_at)=? ORDER BY id DESC",(df,)).fetchall()
            if df else
            db.execute("SELECT name,phone,site,id_type,created_at FROM users ORDER BY id DESC").fetchall())
    trs = "".join(
        f"<tr><td><b>{r['name']}</b></td><td>{r['phone']}</td><td>{r['site']}</td>"
        f"<td><span class='bge bge-a'>{(r['id_type'] or 'N/A').upper()}</span></td>"
        f"<td style='color:#333'>{str(r['created_at'])[:16]}</td></tr>"
        for r in rows) or "<tr><td colspan='5' style='text-align:center;color:#222;padding:30px'>No data</td></tr>"
    body = f"""
<div class="fbar">
  <label>📅 Date Filter</label>
  <form method="get" style="display:flex;gap:8px;align-items:center">
    <input type="date" name="date" value="{df}" max="{today}" style="width:auto">
    <button class="btn btn-primary btn-xs">Filter</button>
    {'<a href="/admin/registrations" class="btn btn-ghost btn-xs">Clear</a>' if df else ''}
  </form>
  <span style="font-size:.72rem;color:#2a2a2a">{len(rows)} record(s)</span>
</div>
<div class="tbl-box">
  <table><tr><th>Name</th><th>Phone</th><th>Site</th><th>Type</th><th>Date</th></tr>
  {trs}</table>
</div>"""
    return page("Registrations","reg",body)


# ── Deposits ───────────────────────────────────────────

@app.route("/admin/deposits")
@admin_only
def deposits():
    today = datetime.date.today().isoformat()
    df = request.args.get("date","")
    rows = (db.execute("SELECT name,phone,site,amount,created_at FROM users WHERE status='accepted' AND date(created_at)=? ORDER BY id DESC",(df,)).fetchall()
            if df else
            db.execute("SELECT name,phone,site,amount,created_at FROM users WHERE status='accepted' ORDER BY id DESC").fetchall())
    total = sum(float(r["amount"] or 0) for r in rows)
    trs = "".join(
        f"<tr><td><b>{r['name']}</b></td><td>{r['phone']}</td><td>{r['site']}</td>"
        f"<td style='color:#27ae60;font-weight:700'>₹{r['amount']}</td>"
        f"<td style='color:#333'>{str(r['created_at'])[:16]}</td></tr>"
        for r in rows) or "<tr><td colspan='5' style='text-align:center;color:#222;padding:30px'>No deposits found</td></tr>"
    body = f"""
<div class="fbar">
  <label>📅 Date Filter</label>
  <form method="get" style="display:flex;gap:8px;align-items:center">
    <input type="date" name="date" value="{df}" max="{today}" style="width:auto">
    <button class="btn btn-primary btn-xs">Filter</button>
    {'<a href="/admin/deposits" class="btn btn-ghost btn-xs">Clear</a>' if df else ''}
  </form>
  <span style="font-size:.72rem;color:#2a2a2a">{len(rows)} transaction(s)</span>
</div>
<div class="grid g3" style="margin-bottom:18px">
  <div class="card"><div class="cl">Total Collected</div>
    <div class="cn" style="color:#27ae60">₹{total}</div>
    <div class="cs">{'Date: '+df if df else 'All time'}</div></div>
  <div class="card"><div class="cl">Transactions</div>
    <div class="cn">{len(rows)}</div><div class="cs">Accepted payments</div></div>
</div>
<div class="tbl-box">
  <table><tr><th>Name</th><th>Phone</th><th>Site</th><th>Amount</th><th>Date</th></tr>
  {trs}</table>
</div>"""
    return page("Deposits","dep",body)


# ── Sub Users ──────────────────────────────────────────

@app.route("/admin/subusers", methods=["GET","POST"])
@admin_only
def subusers():
    if request.method == "POST":
        action = request.form.get("action")
        if action=="add":
            n = request.form.get("name","").strip()
            p = request.form.get("password","").strip()
            if n and p:
                try:
                    db.execute("INSERT INTO subadmins (name,password) VALUES (?,?)",(n,p))
                    db.commit()
                    flash(f"✅ Sub user '{n}' added.","ok")
                except: flash("Username already exists.","err")
            else: flash("Both fields required.","err")
        elif action=="delete":
            db.execute("DELETE FROM subadmins WHERE id=?",(request.form.get("uid"),))
            db.commit()
            flash("🗑️ Sub user removed.","ok")
        return redirect("/admin/subusers")

    rows = db.execute("SELECT * FROM subadmins ORDER BY id DESC").fetchall()
    trs = "".join(
        f"<tr><td>#{r['id']}</td><td><b>{r['name']}</b></td>"
        f"<td><code style='color:#4a90e2'>{r['password'] or '—'}</code></td>"
        f"<td style='color:#2a2a2a'>{str(r['created_at'])[:16]}</td>"
        f"<td><form method='post' style='display:inline'>"
        f"<input type='hidden' name='action' value='delete'>"
        f"<input type='hidden' name='uid' value='{r['id']}'>"
        f"<button class='btn btn-danger btn-xs'>🗑️ Remove</button></form></td></tr>"
        for r in rows) or "<tr><td colspan='5' style='text-align:center;color:#222;padding:30px'>No sub users</td></tr>"

    body = f"""
<div class="sbox">
  <h3>➕ Add Sub User</h3>
  <p>Sub users can only access Payments — Accept, Decline & Send ID.</p>
  <form method="post" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
    <input type="hidden" name="action" value="add">
    <div style="flex:1;min-width:140px"><label class="lbl" style="font-size:.62rem;color:#333;display:block;margin-bottom:6px;letter-spacing:1.5px;text-transform:uppercase">Username</label>
      <input type="text" name="name" placeholder="subadmin1" required></div>
    <div style="flex:1;min-width:140px"><label class="lbl" style="font-size:.62rem;color:#333;display:block;margin-bottom:6px;letter-spacing:1.5px;text-transform:uppercase">Password</label>
      <input type="text" name="password" placeholder="pass@123" required></div>
    <button class="btn btn-primary">Add User</button>
  </form>
</div>
<div class="tbl-box">
  <table><tr><th>#</th><th>Username</th><th>Password</th><th>Added</th><th>Action</th></tr>
  {trs}</table>
</div>"""
    return page("Sub Users","sub",body)


# ── Settings ───────────────────────────────────────────

@app.route("/admin/settings", methods=["GET","POST"])
@admin_only
def settings():
    if request.method=="POST":
        upi = request.form.get("upi","").strip()
        if upi:
            db.execute("UPDATE settings SET upi=? WHERE id=1",(upi,))
            db.commit()
            flash(f"✅ UPI updated: {upi}","ok")
        else: flash("UPI cannot be empty.","err")
        return redirect("/admin/settings")

    body = f"""
<div class="sbox">
  <h3>💳 UPI ID</h3>
  <p>Change anytime — takes effect immediately for all new QR codes.</p>
  <div style="background:#0a0a0a;border:1px solid #1a1a1a;border-radius:8px;
    padding:10px 14px;margin-bottom:16px;font-size:.83rem">
    <span style="color:#333">Current:</span>
    <span style="color:#f5a623;font-weight:700;margin-left:8px;font-family:monospace">{get_upi() or 'Not set'}</span>
  </div>
  <form method="post" style="display:flex;gap:10px;align-items:center">
    <input type="text" name="upi" placeholder="yourname@upi" style="flex:1">
    <button class="btn btn-primary">Update →</button>
  </form>
</div>

<div class="sbox">
  <h3>ℹ️ Panel Info</h3>
  <p>System overview</p>
  <div style="font-size:.82rem;line-height:2.2;color:#444">
    🔥 Site: <span style="color:#e63946">{SITE_NAME}</span><br>
    👤 Users: <span style="color:#ccc">{db.execute("SELECT COUNT(*) FROM users").fetchone()[0]}</span><br>
    💰 Total: <span style="color:#27ae60">₹{db.execute("SELECT COALESCE(SUM(CAST(amount AS REAL)),0) FROM users WHERE status='accepted'").fetchone()[0]}</span><br>
    👥 Sub Users: <span style="color:#ccc">{db.execute("SELECT COUNT(*) FROM subadmins").fetchone()[0]}</span>
  </div>
</div>"""
    return page("Settings","set",body)


# ── Catch all ──────────────────────────────────────────

@app.errorhandler(404)
def not_found(e): return redirect("/admin/login")

@app.route("/")
@app.route("/<path:p>")
def catch_all(p=""): return redirect("/admin/login")


# ═══════════════════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"✅ {SITE_NAME} starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
