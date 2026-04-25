"""
main.py — Railway Deployment Entry Point

Runs both:
  - Flask admin panel (admin.py)
  - Telegram bot (bot.py)
"""

import os
import time
import threading
import requests as _req

PORT = int(os.environ.get("PORT", 5000))

# ── Start Flask admin panel in background thread ──────────────────────────
from admin import app as flask_app

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT, debug=False,
                  use_reloader=False, threaded=True)

t = threading.Thread(target=run_flask, daemon=True)
t.start()
print("✅ Admin panel started")


# ── Keep-alive ping — prevents Railway sleep, warms connection pool ────────
def keep_alive():
    time.sleep(30)   # wait for Flask to fully start
    while True:
        try:
            _req.get(f"http://localhost:{PORT}/ping", timeout=5)
        except Exception:
            pass
        time.sleep(5 * 60)   # ping every 5 minutes

threading.Thread(target=keep_alive, daemon=True).start()
print("✅ Keep-alive started")


# ── Start Telegram bot in main thread (blocking) ──────────────────────────
from bot import main as run_bot

if __name__ == "__main__":
    print("✅ Starting Telegram bot...")
    run_bot()
