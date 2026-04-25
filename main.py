"""
main.py — Railway Deployment Entry Point

Runs both:
  - Flask admin panel (admin.py)
  - Telegram bot (bot.py)

For Replit dev: admin.py and bot.py run separately.
For Railway 24/7: only this file runs.
"""

import os
import threading

# ── Start Flask admin panel in background thread ──
from admin import app as flask_app

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port, debug=False,
                  use_reloader=False, threaded=True)

t = threading.Thread(target=run_flask, daemon=True)
t.start()
print("✅ Admin panel started")

# ── Start Telegram bot in main thread (blocking) ──
from bot import main as run_bot

if __name__ == "__main__":
    print("✅ Starting Telegram bot...")
    run_bot()
