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

SITES = [
    ("Laser247",  "https://www.laser247official.live"),
    ("Tiger399",  "https://tiger399.com"),
    ("AllPanel",  "https://allpanelexch9.co/"),
    ("Diamond",   "https://diamondexchenge.com"),
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "database.db")

# ── Database ──────────────────────────────────────────
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row

db.execute("""CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER, name TEXT, phone TEXT,
    site TEXT, id_type TEXT, amount TEXT, utr TEXT,
    screenshot_file_id TEXT,
    id_pass TEXT, status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
db.execute("""CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY, upi TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS subadmins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
db.execute("INSERT OR IGNORE INTO settings (id,upi) VALUES (1,?)", (DEFAULT_UPI,))
for col in ["id_pass TEXT","id_type TEXT","utr TEXT","phone TEXT",
            "site TEXT","screenshot_file_id TEXT"]:
    try: db.execute(f"ALTER TABLE users ADD COLUMN {col}")
    except: pass
db.commit()


def get_upi():
    r = db.execute("SELECT upi FROM settings WHERE id=1").fetchone()
    return r["upi"] if r else DEFAULT_UPI


# ═══════════════════════════════════════════════════════
#  /start
# ═══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🆕 New ID",  callback_data="type_new")],
        [InlineKeyboardButton("🎮 Demo ID", callback_data="type_demo")],
    ]
    await update.message.reply_text(
        "🙏 *Welcome to Laser Panel!*\n\nSir, please select an option:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


# ═══════════════════════════════════════════════════════
#  BUTTON HANDLER
# ═══════════════════════════════════════════════════════

async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    data = q.data

    # ── Type selection ──
    if data == "type_new":
        context.user_data.clear()
        context.user_data["id_type"] = "new"
        context.user_data["step"]    = "name"
        await q.message.reply_text(
            "✅ *New ID selected!*\n\nSir, please enter your *full name*:",
            parse_mode="Markdown",
        )

    elif data == "type_demo":
        context.user_data.clear()
        context.user_data["id_type"] = "demo"

        site_lines = "\n".join(
            [f"{i+1}. [{name}]({url})" for i, (name, url) in enumerate(SITES)]
        )
        kb = [[InlineKeyboardButton("✅ Yes, Create ID", callback_data="demo_create")]]
        await q.message.reply_text(
            f"🎮 *Demo ID — Available Sites:*\n\n{site_lines}\n\n"
            f"Sir, click on any site above to visit.\n\n"
            f"Kya aap ID banana chahte hain?",
            parse_mode="Markdown",
            disable_web_page_preview=False,
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif data == "demo_create":
        context.user_data["step"] = "name"
        await q.message.reply_text(
            "🙏 *Sir, please enter your full name:*",
            parse_mode="Markdown",
        )

    # ── Site selection (New ID) ──
    elif data.startswith("site_"):
        idx  = int(data.split("_")[1])
        name, url = SITES[idx]
        context.user_data["site"]     = name
        context.user_data["site_url"] = url
        context.user_data["step"]     = "amount"
        await q.message.reply_text(
            f"✅ *{name}* selected!\n\n"
            f"Sir, *kitne amount se ID create karni hai?*\n"
            f"_(Minimum deposit amount enter karein)_",
            parse_mode="Markdown",
        )


# ═══════════════════════════════════════════════════════
#  TEXT HANDLER
# ═══════════════════════════════════════════════════════

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    step = context.user_data.get("step")

    if not step:
        await update.message.reply_text(
            "Sir, please type /start to begin. 🙏"
        )
        return

    # ── Name ──
    if step == "name":
        context.user_data["name"] = text
        context.user_data["step"] = "phone"
        await update.message.reply_text(
            f"✅ Thank you *{text}* Sir!\n\n"
            f"📱 Sir, please enter your *mobile number*:",
            parse_mode="Markdown",
        )

    # ── Phone ──
    elif step == "phone":
        context.user_data["phone"] = text
        context.user_data["step"]  = "site"

        # Show site selection
        kb = [
            [InlineKeyboardButton(f"🌐 {name}", callback_data=f"site_{i}")]
            for i, (name, url) in enumerate(SITES)
        ]
        site_lines = "\n".join(
            [f"{i+1}. [{name}]({url})" for i, (name, url) in enumerate(SITES)]
        )
        await update.message.reply_text(
            f"✅ Mobile number saved!\n\n"
            f"🌐 *Sir, please select your site:*\n\n"
            f"{site_lines}",
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(kb),
        )

    # ── Amount → Generate QR ──
    elif step == "amount":
        context.user_data["amount"] = text
        context.user_data["step"]   = "screenshot"

        upi     = get_upi()
        upi_url = f"upi://pay?pa={upi}&pn=LaserPanel&am={text}&cu=INR"
        qr_path = os.path.join(BASE_DIR, f"qr_{update.effective_chat.id}.png")
        qrcode.make(upi_url).save(qr_path)

        with open(qr_path, "rb") as f:
            await update.message.reply_photo(
                f,
                caption=(
                    f"💳 *Payment Details*\n\n"
                    f"📲 UPI ID: `{upi}`\n"
                    f"💰 Amount: ₹*{text}*\n\n"
                    f"Sir, please complete the payment and then\n"
                    f"📸 *Send your payment screenshot*"
                ),
                parse_mode="Markdown",
            )
        try: os.remove(qr_path)
        except: pass

    else:
        await update.message.reply_text(
            "Sir, please follow the steps. Type /start to restart. 🙏"
        )


# ═══════════════════════════════════════════════════════
#  PHOTO HANDLER — Screenshot
# ═══════════════════════════════════════════════════════

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    # ── Step: Screenshot received → ask UTR ──
    if step == "screenshot":
        context.user_data["screenshot_file_id"] = update.message.photo[-1].file_id
        context.user_data["step"] = "utr"
        await update.message.reply_text(
            "✅ *Screenshot received!*\n\n"
            "🔢 Sir, ab please *UTR number* share karein\n"
            "_(UTR 12 digit ka transaction number hota hai)_",
            parse_mode="Markdown",
        )

    # ── Step: UTR step but photo sent again ──
    elif step == "utr":
        await update.message.reply_text(
            "Sir, please *UTR number* type karein (text mein). 🙏",
            parse_mode="Markdown",
        )

    else:
        await update.message.reply_text(
            "Sir, please type /start to begin. 🙏"
        )


# ═══════════════════════════════════════════════════════
#  UTR Handler (inside text_handler, step = utr)
# ═══════════════════════════════════════════════════════
# NOTE: UTR is handled in text_handler above — adding here as separate check

async def utr_in_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Called from text_handler when step == 'utr'"""
    pass  # handled inline


# Override text_handler to handle utr step too
_original_text_handler = text_handler

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    step = context.user_data.get("step")

    if not step:
        await update.message.reply_text("Sir, please type /start to begin. 🙏")
        return

    if step == "name":
        context.user_data["name"] = text
        context.user_data["step"] = "phone"
        await update.message.reply_text(
            f"✅ Thank you *{text}* Sir!\n\n📱 Sir, please enter your *mobile number*:",
            parse_mode="Markdown",
        )

    elif step == "phone":
        context.user_data["phone"] = text
        context.user_data["step"]  = "site"
        kb = [
            [InlineKeyboardButton(f"🌐 {name}", callback_data=f"site_{i}")]
            for i, (name, url) in enumerate(SITES)
        ]
        site_lines = "\n".join(
            [f"{i+1}. [{name}]({url})" for i, (name, url) in enumerate(SITES)]
        )
        await update.message.reply_text(
            f"✅ Mobile saved!\n\n🌐 *Sir, please select your site:*\n\n{site_lines}",
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif step == "amount":
        context.user_data["amount"] = text
        context.user_data["step"]   = "screenshot"
        upi     = get_upi()
        upi_url = f"upi://pay?pa={upi}&pn=LaserPanel&am={text}&cu=INR"
        qr_path = os.path.join(BASE_DIR, f"qr_{update.effective_chat.id}.png")
        qrcode.make(upi_url).save(qr_path)
        with open(qr_path, "rb") as f:
            await update.message.reply_photo(
                f,
                caption=(
                    f"💳 *Payment Details*\n\n"
                    f"📲 UPI ID: `{upi}`\n"
                    f"💰 Amount: ₹*{text}*\n\n"
                    f"Sir, payment complete karein aur\n"
                    f"📸 *Payment screenshot bhejein*"
                ),
                parse_mode="Markdown",
            )
        try: os.remove(qr_path)
        except: pass

    elif step == "utr":
        ud  = context.user_data
        utr = text

        # Save to DB
        db.execute("""INSERT INTO users
            (telegram_id,name,phone,site,id_type,amount,utr,screenshot_file_id,status)
            VALUES (?,?,?,?,?,?,?,?,'pending')""",
            (update.effective_chat.id, ud.get("name",""), ud.get("phone",""),
             ud.get("site",""), ud.get("id_type","new"),
             ud.get("amount",""), utr, ud.get("screenshot_file_id","")))
        db.commit()
        req_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        context.user_data["step"] = None

        # Tell user to wait
        await update.message.reply_text(
            f"✅ *Request Submitted Successfully!*\n\n"
            f"👤 Name: {ud.get('name')}\n"
            f"📱 Mobile: {ud.get('phone')}\n"
            f"🌐 Site: {ud.get('site')}\n"
            f"💰 Amount: ₹{ud.get('amount')}\n"
            f"🔢 UTR: `{utr}`\n\n"
            f"⏳ Sir, please wait *2-5 minutes*.\n"
            f"Aapki ID verify hote hi bhej di jayegi. 🙏",
            parse_mode="Markdown",
        )

        # Forward screenshot + info to admin Telegram
        screenshot_id = ud.get("screenshot_file_id", "")
        caption = (
            f"🔔 *New Payment Request #{req_id}*\n\n"
            f"👤 Name: {ud.get('name')}\n"
            f"📱 Phone: {ud.get('phone')}\n"
            f"🌐 Site: {ud.get('site')} ({ud.get('id_type','new').upper()})\n"
            f"💰 Amount: ₹{ud.get('amount')}\n"
            f"🔢 UTR: {utr}\n"
            f"🆔 Telegram ID: {update.effective_chat.id}\n\n"
            f"👉 *Admin Panel → Payments to Accept/Decline*"
        )
        try:
            if screenshot_id:
                await update.get_bot().send_photo(
                    chat_id=ADMIN_CHAT_ID,
                    photo=screenshot_id,
                    caption=caption,
                    parse_mode="Markdown",
                )
            else:
                await update.get_bot().send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=caption,
                    parse_mode="Markdown",
                )
        except Exception as e:
            print(f"Admin notify error: {e}")

    else:
        await update.message.reply_text(
            "Sir, please type /start to begin. 🙏"
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
