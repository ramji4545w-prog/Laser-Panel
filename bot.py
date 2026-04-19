import os
import sqlite3
import qrcode

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

TOKEN         = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])
DEFAULT_UPI   = os.environ.get("UPI_ID", "")

SITES    = ["Laser247", "Tiger399", "AllPanel", "Diamond"]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "database.db")

# ── Database ──────────────────────────────────────────
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row

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


def get_upi():
    r = db.execute("SELECT upi FROM settings WHERE id=1").fetchone()
    return r["upi"] if r else DEFAULT_UPI


def notify_admin(text):
    """Send plain notification to admin Telegram."""
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=5)
    except: pass


def save_request(telegram_id, ud, utr):
    db.execute("""INSERT INTO users
        (telegram_id,name,phone,site,id_type,amount,utr,status)
        VALUES (?,?,?,?,?,?,?,'pending')""",
        (telegram_id, ud.get("name",""), ud.get("phone",""),
         ud.get("site",""), ud.get("id_type","new"),
         ud.get("amount",""), utr))
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


# ═══════════════════════════════════════════════════════
#  USER FLOW
#  /start → New/Demo → Site → Name → Phone → Amount → QR
#  → User sends UTR (text) or Screenshot → wait 2 min
#  Admin reviews on web panel → Accept/Decline
#  Accept → Admin enters ID on panel → Bot sends ID to user
# ═══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🆕 New ID",  callback_data="type_new")],
        [InlineKeyboardButton("🎁 Demo ID", callback_data="type_demo")],
    ]
    await update.message.reply_text(
        "🙏 *Welcome to Laser Panel!*\n\nPlease select ID type:",
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
            "🌐 *Select your site:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif data.startswith("site_"):
        context.user_data["site"] = data[5:]
        context.user_data["step"] = "name"
        await q.message.reply_text(
            "👤 *Please enter your full name:*",
            parse_mode="Markdown",
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    step = context.user_data.get("step")

    if not step:
        await update.message.reply_text("Please type /start to begin.")
        return

    # ── Step 1: Name ──
    if step == "name":
        context.user_data["name"] = text
        context.user_data["step"] = "phone"
        await update.message.reply_text(
            "📱 *Please enter your phone number:*",
            parse_mode="Markdown",
        )

    # ── Step 2: Phone ──
    elif step == "phone":
        context.user_data["phone"] = text
        context.user_data["step"] = "amount"
        await update.message.reply_text(
            "💰 *Enter deposit amount (₹):*",
            parse_mode="Markdown",
        )

    # ── Step 3: Amount → Show QR ──
    elif step == "amount":
        context.user_data["amount"] = text
        context.user_data["step"] = "utr"

        upi = get_upi()
        upi_link = f"upi://pay?pa={upi}&pn=LaserPanel&am={text}&cu=INR"
        qr_path = os.path.join(BASE_DIR, f"qr_{update.effective_chat.id}.png")
        qrcode.make(upi_link).save(qr_path)

        with open(qr_path, "rb") as f:
            await update.message.reply_photo(
                f,
                caption=(
                    f"💳 *Pay ₹{text} via UPI*\n\n"
                    f"📲 UPI ID: `{upi}`\n\n"
                    f"✅ After payment, send your *UTR number* or *screenshot*."
                ),
                parse_mode="Markdown",
            )
        try: os.remove(qr_path)
        except: pass

    # ── Step 4: UTR received → Save & Notify ──
    elif step == "utr":
        ud = context.user_data
        req_id = save_request(update.effective_chat.id, ud, text)
        context.user_data["step"] = None

        # Tell user to wait
        await update.message.reply_text(
            f"✅ *Request Submitted!*\n\n"
            f"🔢 UTR: `{text}`\n"
            f"💰 Amount: ₹{ud.get('amount')}\n"
            f"🌐 Site: {ud.get('site')}\n\n"
            f"⏳ Please wait *2–5 minutes*.\n"
            f"We will send your ID once payment is verified. 🙏",
            parse_mode="Markdown",
        )

        # Notify admin on Telegram
        notify_admin(
            f"🔔 *New Payment Request #{req_id}*\n\n"
            f"👤 Name: {ud.get('name')}\n"
            f"📱 Phone: {ud.get('phone')}\n"
            f"🌐 Site: {ud.get('site')} ({ud.get('id_type','new').upper()})\n"
            f"💰 Amount: ₹{ud.get('amount')}\n"
            f"🔢 UTR: {text}\n\n"
            f"👉 *Go to Admin Panel → Payments to Accept/Decline*"
        )


# ── Screenshot as UTR proof ──────────────────────────
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step != "utr":
        await update.message.reply_text("Please type /start to begin.")
        return

    ud = context.user_data
    req_id = save_request(update.effective_chat.id, ud, "screenshot")
    context.user_data["step"] = None

    # Tell user to wait
    await update.message.reply_text(
        f"✅ *Screenshot Received!*\n\n"
        f"💰 Amount: ₹{ud.get('amount')}\n"
        f"🌐 Site: {ud.get('site')}\n\n"
        f"⏳ Please wait *2–5 minutes*.\n"
        f"We will send your ID once payment is verified. 🙏",
        parse_mode="Markdown",
    )

    # Forward screenshot to admin with request info
    try:
        photo_file_id = update.message.photo[-1].file_id
        await update.get_bot().send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=photo_file_id,
            caption=(
                f"🔔 *New Request #{req_id}* (Screenshot)\n\n"
                f"👤 {ud.get('name')} | 📱 {ud.get('phone')}\n"
                f"🌐 {ud.get('site')} ({ud.get('id_type','new').upper()})\n"
                f"💰 ₹{ud.get('amount')}\n\n"
                f"👉 *Admin Panel → Payments to Accept/Decline*"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        notify_admin(
            f"🔔 *New Request #{req_id}* (Screenshot)\n\n"
            f"👤 {ud.get('name')} | 📱 {ud.get('phone')}\n"
            f"🌐 {ud.get('site')} ({ud.get('id_type','new').upper()})\n"
            f"💰 ₹{ud.get('amount')}\n\n"
            f"👉 *Admin Panel → Payments to Accept/Decline*"
        )


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CallbackQueryHandler(btn_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("✅ Laser Panel Bot running...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
