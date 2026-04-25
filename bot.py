import os
import re
import io
import sqlite3
import qrcode

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

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
db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, upi TEXT)")
db.execute("""CREATE TABLE IF NOT EXISTS subadmins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
db.execute("INSERT OR IGNORE INTO settings (id,upi) VALUES (1,?)", (DEFAULT_UPI,))
db.execute("""CREATE TABLE IF NOT EXISTS chat_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    user_name TEXT,
    sender TEXT,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
for col in ["id_pass TEXT","id_type TEXT","utr TEXT","phone TEXT",
            "site TEXT","screenshot_file_id TEXT"]:
    try: db.execute(f"ALTER TABLE users ADD COLUMN {col}")
    except: pass
db.commit()


def get_upi():
    r = db.execute("SELECT upi FROM settings WHERE id=1").fetchone()
    return r["upi"] if r else DEFAULT_UPI


def log_chat(telegram_id: int, user_name: str, sender: str, message: str):
    """Chat message database mein save karo"""
    try:
        db.execute(
            "INSERT INTO chat_logs (telegram_id, user_name, sender, message) VALUES (?,?,?,?)",
            (telegram_id, user_name, sender, message)
        )
        db.commit()
    except Exception:
        pass


def is_valid_phone(phone: str) -> bool:
    """10 digit Indian ya international (+...) number accept karo"""
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        # International: + ke baad 8-15 digits
        return re.fullmatch(r'\+\d{8,15}', phone) is not None
    # Indian: exactly 10 digits
    return re.fullmatch(r'\d{10}', phone) is not None


def is_valid_utr(utr: str) -> bool:
    """Exactly 12 digits"""
    return re.fullmatch(r'\d{12}', utr.strip()) is not None


def names_match(name1: str, name2: str) -> bool:
    """Case-insensitive partial name match"""
    n1 = name1.strip().lower()
    n2 = name2.strip().lower()
    words1 = set(n1.split())
    words2 = set(n2.split())
    return bool(words1 & words2) or n1 in n2 or n2 in n1


# ─── QR pe jo naam set hai usse screenshot mein dhundo ───
PAYEE_NAME = "LaserPanel"   # pn= parameter in QR URL

async def verify_screenshot_ocr(file_id: str, bot) -> bool:
    """
    Screenshot download karke OCR karo.
    Return True agar payment valid lagti hai (PAYEE_NAME ya UPI ID mila),
    False agar fake slip lag rahi hai.
    OCR available nahi hai toh True return karo (block mat karo).
    """
    if not OCR_AVAILABLE:
        return True  # OCR nahi hai — screenshot valid maano

    try:
        file   = await bot.get_file(file_id)
        buf    = io.BytesIO()
        await file.download_to_memory(out=buf)
        buf.seek(0)
        img    = Image.open(buf)
        text   = pytesseract.image_to_string(img).lower()

        upi       = get_upi()
        upi_local = upi.split("@")[0].lower() if "@" in upi else upi.lower()
        payee_lower = PAYEE_NAME.lower()

        if payee_lower in text or upi_local in text:
            return True
        if len(upi_local) >= 4 and upi_local[:4] in text:
            return True
        return False
    except Exception:
        return True


async def auto_decline(telegram_id: int, name: str, site: str, amount: str,
                       screenshot_id: str, phone: str, id_type: str, bot):
    """Name mismatch par auto-decline karo"""
    db.execute("""INSERT INTO users
        (telegram_id,name,phone,site,id_type,amount,utr,screenshot_file_id,status)
        VALUES (?,?,?,?,?,?,?,?,'declined')""",
        (telegram_id, name, phone, site, id_type, amount, "NAME_MISMATCH", screenshot_id))
    db.commit()

    await bot.send_message(
        chat_id=telegram_id,
        text=(
            f"❌ *Payment Decline Ho Gayi Sir*\n\n"
            f"Dear *{name}* Sir,\n"
            f"Aapke payment mein diya gaya naam aapke account se match nahi karta.\n\n"
            f"For more information contact here 👉 https://wa.me/919520668248\n\n"
            f"Dobara try karne ke liye /start karein 🙏"
        ),
        parse_mode="Markdown",
    )


# ════════════════════════════════════════
#  /start
# ════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    tid  = update.effective_chat.id
    uname = user.full_name or "Unknown"
    log_chat(tid, uname, "customer", "/start")
    kb = [
        [InlineKeyboardButton("🆕 New ID",  callback_data="type_new")],
        [InlineKeyboardButton("🎮 Demo ID", callback_data="type_demo")],
    ]
    bot_msg = "🙏 Laser Panel mein aapka swagat hai Sir! — ID type select karein"
    await update.message.reply_text(
        "🙏 *Laser Panel mein aapka swagat hai Sir!*\n\n"
        "Sir, aap kaun si ID lena chahenge?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    log_chat(tid, uname, "bot", bot_msg)


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

    # ── Step 1: Naam ──
    if step == "name":
        context.user_data["name"] = text
        context.user_data["step"] = "phone"
        await forward_to_admin(update, context, f"Step: Naam diya → {text}")
        await update.message.reply_text(
            f"✅ Shukriya *{text}* Sir!\n\n"
            f"📱 Sir, aapka *mobile number* kya hai?",
            parse_mode="Markdown",
        )

    # ── Step 2: Phone (validate) ──
    elif step == "phone":
        if not is_valid_phone(text):
            await update.message.reply_text(
                "⚠️ Sir, *sahi mobile number* bhejein.\n\n"
                "📱 Indian number: 10 digit (jaise: 9876543210)\n"
                "🌍 International: + ke saath (jaise: +919876543210)",
                parse_mode="Markdown",
            )
            return

        context.user_data["phone"] = text
        context.user_data["step"]  = "site"
        await forward_to_admin(update, context, f"Step: Phone diya → {text}")
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

    # ── Step 3: Amount → QR ──
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

    # ── Step 4: UTR (validate 12 digits) ──
    elif step == "utr":
        if not is_valid_utr(text):
            await update.message.reply_text(
                "⚠️ Sir, *sahi UTR number* bhejein.\n\n"
                "🔢 UTR exactly *12 digit* ka hona chahiye.\n"
                "_(Jaise: 123456789012)_\n\n"
                "Bank app mein payment details mein milega Sir.",
                parse_mode="Markdown",
            )
            return

        name          = context.user_data.get("name", "")
        phone         = context.user_data.get("phone", "")
        site          = context.user_data.get("site", "")
        id_type       = context.user_data.get("id_type", "new")
        amount        = context.user_data.get("amount", "")
        screenshot_id = context.user_data.get("screenshot_file_id", "")
        utr           = text

        db.execute("""INSERT INTO users
            (telegram_id,name,phone,site,id_type,amount,utr,screenshot_file_id,status)
            VALUES (?,?,?,?,?,?,?,?,'pending')""",
            (update.effective_chat.id, name, phone, site, id_type, amount, utr, screenshot_id))
        db.commit()
        await forward_to_admin(update, context, f"✅ UTR Submit kiya → {utr} | Amount: ₹{amount} | Site: {site}")
        context.user_data.clear()

        await update.message.reply_text(
            f"✅ *Shukriya {name} Sir!*\n\n"
            f"⏳ Sir, please *2-5 minute wait karein.*\n"
            f"Aapki ID verify hote hi bhej di jayegi. 🙏",
            parse_mode="Markdown",
        )

    else:
        await update.message.reply_text(
            "🙏 Sir, /start type karein aur shuru karein."
        )


# ════════════════════════════════════════
#  PHOTO HANDLER — Screenshot
# ════════════════════════════════════════

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "screenshot":
        file_id = update.message.photo[-1].file_id

        # ── OCR: screenshot check karo ──
        checking_msg = await update.message.reply_text(
            "🔍 *Screenshot verify ho rahi hai Sir...*",
            parse_mode="Markdown",
        )

        is_valid = await verify_screenshot_ocr(file_id, context.bot)

        await checking_msg.delete()

        if not is_valid:
            await update.message.reply_text(
                "❌ *Payment Received Nahi Hua Sir!*\n\n"
                "Aapki screenshot mein payment details match nahi kar rahi.\n"
                "*(Fake slip detect hui)*\n\n"
                "✅ Sahi payment karein aur real screenshot bhejein Sir.\n\n"
                "Koi problem ho to contact karein 👉 https://wa.me/919520668248\n\n"
                "_Dobara try karne ke liye /start karein_ 🙏",
                parse_mode="Markdown",
            )
            context.user_data.clear()
            return

        context.user_data["screenshot_file_id"] = file_id
        context.user_data["step"] = "utr"
        await update.message.reply_text(
            "✅ *Screenshot verify ho gayi Sir!*\n\n"
            "🔢 Sir, ab apna *UTR number* type karein.\n"
            "_(Payment ke baad milne wala 12 digit ka number)_",
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
#  ADMIN KO FORWARD KARO
# ════════════════════════════════════════

async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, extra: str = ""):
    """Customer ka message admin ko forward karo"""
    try:
        user     = update.effective_user
        chat_id  = update.effective_chat.id
        name     = user.full_name or "Unknown"
        username = f"@{user.username}" if user.username else "no username"

        header = (
            f"👤 *Customer Message*\n"
            f"Name: {name} ({username})\n"
            f"Chat ID: `{chat_id}`\n"
            f"_{extra}_\n"
            f"{'─'*25}"
        )
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=header,
            parse_mode="Markdown"
        )
        # Original message forward
        await update.message.forward(chat_id=ADMIN_CHAT_ID)
    except Exception:
        pass  # Admin forward fail hua to customer flow mat rokho


# ════════════════════════════════════════
#  /reply COMMAND — Admin customer ko reply de
# ════════════════════════════════════════

async def cmd_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sirf admin use kar sakta hai: /reply <chat_id> <message>"""
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚠️ Format: `/reply <chat_id> <message>`\n\n"
            "Example: `/reply 123456789 Aapki ID ready hai Sir!`",
            parse_mode="Markdown"
        )
        return

    target_id = args[0]
    message   = " ".join(args[1:])

    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=f"💬 {message}"
        )
        await update.message.reply_text(f"✅ Message bhej diya `{target_id}` ko!", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reply", cmd_reply))
    app.add_handler(CallbackQueryHandler(btn_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("✅ Laser Panel Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
