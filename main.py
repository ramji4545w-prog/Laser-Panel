"""
main.py — Railway Deployment Entry Point
Runs Flask admin panel (from admin.py) + Telegram bot together.

For Replit development:
  - Admin Panel runs separately via `python admin.py`
  - Bot runs separately via `python bot.py`

For Railway (24/7):
  - Only this file runs: `python main.py`
"""

import os
import threading
import qrcode

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

# Import flask app and DB from admin.py
from admin import app as flask_app, db, get_upi, send_tg, SITE_NAME

TOKEN         = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SITES = ["Laser247", "Tiger399", "AllPanel", "Diamond"]


# ═══════════════════════════════════════════════════════
#  BOT HANDLERS
# ═══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🆕 New ID",  callback_data="type_new")],
        [InlineKeyboardButton("🎁 Demo ID", callback_data="type_demo")],
    ]
    await update.message.reply_text(
        f"🙏 *Welcome to {SITE_NAME}!*\n\nPlease choose your ID type:",
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
            "🌐 *Select Site:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )
    elif data.startswith("site_"):
        context.user_data["site"] = data[5:]
        context.user_data["step"] = "name"
        await q.message.reply_text(
            "👤 *Please enter your full name:*", parse_mode="Markdown")


async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    step = context.user_data.get("step")

    if not step:
        await update.message.reply_text("Please type /start to begin.")
        return

    if step == "name":
        context.user_data["name"] = text
        context.user_data["step"] = "phone"
        await update.message.reply_text(
            "📱 *Please enter your phone number:*", parse_mode="Markdown")

    elif step == "phone":
        context.user_data["phone"] = text
        context.user_data["step"] = "amount"
        await update.message.reply_text(
            "💰 *Enter deposit amount (₹):*", parse_mode="Markdown")

    elif step == "amount":
        context.user_data["amount"] = text
        context.user_data["step"] = "utr"
        upi = get_upi()
        upi_link = f"upi://pay?pa={upi}&pn=Payment&am={text}&cu=INR"
        qr_path = os.path.join(BASE_DIR, f"qr_{update.effective_chat.id}.png")
        qrcode.make(upi_link).save(qr_path)
        with open(qr_path, "rb") as f:
            await update.message.reply_photo(
                f,
                caption=(
                    f"💳 *Pay ₹{text} via UPI*\n\n"
                    f"📲 UPI ID: `{upi}`\n\n"
                    f"✅ After payment, send your *UTR number* or *screenshot*.\n\n"
                    f"_Payment verified within 5 minutes._"
                ),
                parse_mode="Markdown",
            )
        try: os.remove(qr_path)
        except: pass

    elif step == "utr":
        ud = context.user_data
        db.execute("""
            INSERT INTO users (telegram_id,name,phone,site,id_type,amount,utr,status)
            VALUES (?,?,?,?,?,?,?,'pending')
        """, (update.effective_chat.id,
              ud.get("name",""), ud.get("phone",""),
              ud.get("site",""), ud.get("id_type","new"),
              ud.get("amount",""), text))
        db.commit()
        req_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        context.user_data["step"] = None

        await update.message.reply_text(
            "⏳ *Request Submitted Successfully!*\n\n"
            "Your payment is under review.\n"
            "Please wait 2–5 minutes — we will send your ID shortly. 🙏",
            parse_mode="Markdown",
        )
        send_tg(ADMIN_CHAT_ID,
            f"🔔 *New Payment Request #{req_id}*\n\n"
            f"👤 Name: {ud.get('name')}\n"
            f"📱 Phone: {ud.get('phone')}\n"
            f"🌐 Site: {ud.get('site')} ({ud.get('id_type','new').upper()})\n"
            f"💰 Amount: ₹{ud.get('amount')}\n"
            f"🔢 UTR: {text}\n\n"
            f"👉 Review in Admin Panel → Payments"
        )


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") == "utr":
        ud = context.user_data
        db.execute("""
            INSERT INTO users (telegram_id,name,phone,site,id_type,amount,utr,status)
            VALUES (?,?,?,?,?,?,?,'pending')
        """, (update.effective_chat.id,
              ud.get("name",""), ud.get("phone",""),
              ud.get("site",""), ud.get("id_type","new"),
              ud.get("amount",""), "screenshot"))
        db.commit()
        req_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        context.user_data["step"] = None

        await update.message.reply_text(
            "⏳ *Screenshot Received!*\n\n"
            "Your payment is under review.\n"
            "Please wait 2–5 minutes — we will send your ID shortly. 🙏",
            parse_mode="Markdown",
        )
        send_tg(ADMIN_CHAT_ID,
            f"🔔 *New Payment Request #{req_id}* (Screenshot)\n\n"
            f"👤 Name: {ud.get('name')}\n"
            f"📱 Phone: {ud.get('phone')}\n"
            f"🌐 Site: {ud.get('site')} ({ud.get('id_type','new').upper()})\n"
            f"💰 Amount: ₹{ud.get('amount')}\n\n"
            f"👉 Review in Admin Panel → Payments"
        )
    else:
        await update.message.reply_text("Please type /start to begin.")


# ═══════════════════════════════════════════════════════
#  MAIN — Flask thread + Bot main thread
# ═══════════════════════════════════════════════════════

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    print(f"✅ {SITE_NAME} admin panel started")

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CallbackQueryHandler(btn_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    print("✅ Telegram bot started — polling...")
    application.run_polling(drop_pending_updates=True)
