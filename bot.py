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
    ("Laser247", "https://www.laser247official.live"),
    ("Tiger399", "https://tiger399.com"),
    ("AllPanel", "https://allpanelexch9.co/"),
    ("Diamond",  "https://diamondexchenge.com"),
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "database.db")

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row

db.execute("""CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER, name TEXT, phone TEXT,
    site TEXT, id_type TEXT, amount TEXT, utr TEXT,
    screenshot_file_id TEXT, id_pass TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
db.execute("""CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, upi TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS subadmins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
db.execute("INSERT OR IGNORE INTO settings (id,upi) VALUES (1,?)", (DEFAULT_UPI,))
for col in ["id_pass TEXT", "id_type TEXT", "utr TEXT", "phone TEXT",
            "site TEXT", "screenshot_file_id TEXT"]:
    try: db.execute(f"ALTER TABLE users ADD COLUMN {col}")
    except: pass
db.commit()


def get_upi():
    r = db.execute("SELECT upi FROM settings WHERE id=1").fetchone()
    return r["upi"] if r else DEFAULT_UPI


# ════════════════════════════════════════
#  /start
# ════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("🆕 New ID",  callback_data="type_new")],
        [InlineKeyboardButton("🎮 Demo ID", callback_data="type_demo")],
    ]
    await update.message.reply_text(
        "🙏 *Laser Panel mein aapka swagat hai Sir!*\n\n"
        "Sir, aap kaun si ID lena chahenge?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


# ════════════════════════════════════════
#  BUTTON HANDLER
# ════════════════════════════════════════

async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    data = q.data

    if data == "type_new":
        context.user_data.clear()
        context.user_data["id_type"] = "new"
        context.user_data["step"]    = "name"
        await q.message.reply_text(
            "✅ *New ID select ki!*\n\n"
            "Sir, aapka *poora naam* kya hai?",
            parse_mode="Markdown",
        )

    elif data == "type_demo":
        context.user_data.clear()
        context.user_data["id_type"] = "demo"
        site_lines = "\n".join(
            [f"{i+1}. [{n}]({u})" for i, (n, u) in enumerate(SITES)]
        )
        kb = [[InlineKeyboardButton("✅ Haan, ID Banana Hai", callback_data="demo_create")]]
        await q.message.reply_text(
            f"🎮 *Demo ID — Available Sites:*\n\n"
            f"{site_lines}\n\n"
            f"Sir, kisi bhi site par click karke dekh sakte hain.\n\n"
            f"Sir, kya aap ID banana chahte hain?",
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif data == "demo_create":
        context.user_data["step"] = "name"
        await q.message.reply_text(
            "🙏 Sir, aapka *poora naam* kya hai?",
            parse_mode="Markdown",
        )

    elif data.startswith("site_"):
        idx       = int(data.split("_")[1])
        name, url = SITES[idx]
        context.user_data["site"] = name
        context.user_data["step"] = "amount"
        await q.message.reply_text(
            f"✅ *{name}* select ki!\n\n"
            f"Sir, aap *kitne amount se ID banana chahte hain?*\n"
            f"_(₹ mein amount type karein, jaise: 500)_",
            parse_mode="Markdown",
        )


# ════════════════════════════════════════
#  TEXT HANDLER
# ════════════════════════════════════════

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    step = context.user_data.get("step")

    if not step:
        await update.message.reply_text(
            "🙏 Sir, /start type karein aur shuru karein."
        )
        return

    # Step 1 — Naam
    if step == "name":
        context.user_data["name"] = text
        context.user_data["step"] = "phone"
        await update.message.reply_text(
            f"✅ Shukriya *{text}* Sir!\n\n"
            f"📱 Sir, aapka *mobile number* kya hai?",
            parse_mode="Markdown",
        )

    # Step 2 — Mobile
    elif step == "phone":
        context.user_data["phone"] = text
        context.user_data["step"]  = "site"
        site_lines = "\n".join(
            [f"{i+1}. [{n}]({u})" for i, (n, u) in enumerate(SITES)]
        )
        kb = [
            [InlineKeyboardButton(f"🌐 {n}", callback_data=f"site_{i}")]
            for i, (n, u) in enumerate(SITES)
        ]
        await update.message.reply_text(
            f"✅ Mobile number save ho gaya!\n\n"
            f"🌐 *Sir, aap konsi site pe ID banana chahte hain?*\n\n"
            f"{site_lines}\n\n"
            f"_Neeche se site select karein Sir:_",
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(kb),
        )

    # Step 3 — Amount → QR
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
                    f"💳 *Payment Details Sir*\n\n"
                    f"📲 UPI ID: `{upi}`\n"
                    f"💰 Amount: ₹*{text}*\n\n"
                    f"Sir, QR scan karke ya UPI ID se payment karein.\n\n"
                    f"✅ Payment hone ke baad *screenshot bhejein Sir.*"
                ),
                parse_mode="Markdown",
            )
        try: os.remove(qr_path)
        except: pass

    # Step 4 — UTR → Save & Notify
    elif step == "utr":
        # Pehle saara data local variables mein save karo
        name          = context.user_data.get("name", "")
        phone         = context.user_data.get("phone", "")
        site          = context.user_data.get("site", "")
        id_type       = context.user_data.get("id_type", "new")
        amount        = context.user_data.get("amount", "")
        screenshot_id = context.user_data.get("screenshot_file_id", "")
        utr           = text

        # DB mein save karo
        db.execute("""INSERT INTO users
            (telegram_id,name,phone,site,id_type,amount,utr,screenshot_file_id,status)
            VALUES (?,?,?,?,?,?,?,?,'pending')""",
            (update.effective_chat.id, name, phone, site, id_type, amount, utr, screenshot_id))
        db.commit()
        req_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Ab clear karo
        context.user_data.clear()

        # User ko sirf wait karne ka message
        await update.message.reply_text(
            f"✅ *Shukriya {name} Sir!*\n\n"
            f"⏳ Sir, please *2-5 minute wait karein.*\n"
            f"Aapki ID verify hote hi bhej di jayegi. 🙏",
            parse_mode="Markdown",
        )

        # Data DB mein save ho gaya — admin web panel se dekhega

    else:
        await update.message.reply_text(
            "🙏 Sir, /start type karein aur shuru karein."
        )


# ════════════════════════════════════════
#  PHOTO HANDLER
# ════════════════════════════════════════

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "screenshot":
        context.user_data["screenshot_file_id"] = update.message.photo[-1].file_id
        context.user_data["step"] = "utr"
        await update.message.reply_text(
            "✅ *Screenshot mil gayi Sir!*\n\n"
            "🔢 Sir, ab apna *UTR number* type karein.\n"
            "_(Transaction ke baad milne wala 12 digit ka number)_",
            parse_mode="Markdown",
        )
    elif step == "utr":
        await update.message.reply_text(
            "🙏 Sir, UTR number *text mein type karein* — photo nahi.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "🙏 Sir, /start type karein aur shuru karein."
        )


# ════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(btn_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("✅ Laser Panel Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
