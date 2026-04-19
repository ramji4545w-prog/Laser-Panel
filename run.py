import threading
import asyncio
import os

# ── Start Flask admin panel in background thread ──────────────────
def run_flask():
    from admin import app
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# ── Start Telegram bot in main thread (blocking) ─────────────────
import sqlite3
import qrcode
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])
DEFAULT_UPI = os.environ.get("UPI_ID", "")

SITES = ["Laser247", "Tiger399", "AllPanel", "Diamond"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
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
cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY,
    upi TEXT
)
""")
cursor.execute("INSERT OR IGNORE INTO settings (id, upi) VALUES (1, ?)", (DEFAULT_UPI,))
conn.commit()

for col in ["id_pass TEXT", "id_type TEXT", "utr TEXT", "phone TEXT", "site TEXT"]:
    try:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col}")
        conn.commit()
    except Exception:
        pass


def get_upi():
    row = cursor.execute("SELECT upi FROM settings WHERE id=1").fetchone()
    return row[0] if row else DEFAULT_UPI


# ── Bot handlers ──────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🆕 New ID", callback_data="type_new")],
        [InlineKeyboardButton("🎁 Demo ID", callback_data="type_demo")],
    ]
    await update.message.reply_text(
        "🙏 *Welcome Sir!*\n\nPlease choose your ID type:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data in ("type_new", "type_demo"):
        context.user_data.clear()
        context.user_data["id_type"] = "new" if data == "type_new" else "demo"
        kb = [[InlineKeyboardButton(s, callback_data=f"site_{s}")] for s in SITES]
        await query.message.reply_text(
            "🌐 *Select Site Sir:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif data.startswith("site_"):
        site = data[5:]
        context.user_data["site"] = site
        context.user_data["step"] = "name"
        await query.message.reply_text("👤 *Sir, please enter your full name:*", parse_mode="Markdown")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        qr_img = qrcode.make(upi_link)
        qr_path = os.path.join(BASE_DIR, f"qr_{update.effective_chat.id}.png")
        qr_img.save(qr_path)

        with open(qr_path, "rb") as f:
            await update.message.reply_photo(
                f,
                caption=(
                    f"💳 *Sir, please pay ₹{text}*\n\n"
                    f"UPI ID: `{upi}`\n\n"
                    f"After payment, please send your *UTR number* or *screenshot*."
                ),
                parse_mode="Markdown",
            )
        try:
            os.remove(qr_path)
        except Exception:
            pass

    elif step == "utr":
        utr = text
        user_data = context.user_data

        cursor.execute("""
            INSERT INTO users (telegram_id, name, phone, site, id_type, amount, utr, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (
            update.effective_chat.id,
            user_data.get("name", ""),
            user_data.get("phone", ""),
            user_data.get("site", ""),
            user_data.get("id_type", "new"),
            user_data.get("amount", ""),
            utr,
        ))
        conn.commit()
        req_id = cursor.lastrowid

        context.user_data["step"] = None

        await update.message.reply_text(
            "⏳ *Sir, your payment request has been submitted!*\n\nPlease wait 2-5 minutes. We will send your ID shortly.",
            parse_mode="Markdown",
        )

        try:
            from telegram import Bot
            bot = Bot(token=TOKEN)
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"🔔 *New Payment Request #{req_id}*\n\n"
                f"👤 Name: {user_data.get('name')}\n"
                f"📱 Phone: {user_data.get('phone')}\n"
                f"🌐 Site: {user_data.get('site')} ({user_data.get('id_type', 'new').upper()})\n"
                f"💰 Amount: ₹{user_data.get('amount')}\n"
                f"🔢 UTR: {utr}\n\n"
                f"Go to /admin/payments to accept.",
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    if step == "utr":
        user_data = context.user_data
        utr = "screenshot"

        cursor.execute("""
            INSERT INTO users (telegram_id, name, phone, site, id_type, amount, utr, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (
            update.effective_chat.id,
            user_data.get("name", ""),
            user_data.get("phone", ""),
            user_data.get("site", ""),
            user_data.get("id_type", "new"),
            user_data.get("amount", ""),
            utr,
        ))
        conn.commit()
        context.user_data["step"] = None

        await update.message.reply_text(
            "⏳ *Sir, screenshot received!*\n\nPlease wait 2-5 minutes. We will send your ID shortly.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("Please type /start to begin.")


if __name__ == "__main__":
    import asyncio

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("✅ Bot + Admin Panel starting...")
    application.run_polling(drop_pending_updates=True)
