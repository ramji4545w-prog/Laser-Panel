import os
import re
import io
import time
import threading
import traceback
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

from db import db

TOKEN         = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])
DEFAULT_UPI   = os.environ.get("UPI_ID", "")

SITES = [
    ("Laser247", "https://www.laser247official.live"),
    ("Tiger399", "https://tiger399.com"),
    ("AllPanel", "https://allpanelexch9.co/"),
    ("Diamond",  "https://diamondexchenge.com"),
]


def get_upi():
    try:
        r = db.execute("SELECT upi FROM settings WHERE id=1").fetchone()
        return r["upi"] if r and r["upi"] else DEFAULT_UPI
    except Exception:
        return DEFAULT_UPI


def log_chat(telegram_id: int, user_name: str, sender: str, message: str):
    def _save():
        try:
            db.execute(
                "INSERT INTO chat_logs (telegram_id, user_name, sender, message) VALUES (?,?,?,?)",
                (telegram_id, user_name, sender, message)
            )
            db.commit()
        except Exception as e:
            print(f"⚠️ log_chat failed tid={telegram_id} sender={sender}: {e}")
    threading.Thread(target=_save, daemon=True).start()


def is_valid_phone(phone: str) -> bool:
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        return re.fullmatch(r'\+\d{8,15}', phone) is not None
    return re.fullmatch(r'\d{10}', phone) is not None


def is_valid_utr(utr: str) -> bool:
    return re.fullmatch(r'\d{12}', utr.strip()) is not None


def names_match(name1: str, name2: str) -> bool:
    n1 = name1.strip().lower()
    n2 = name2.strip().lower()
    words1 = set(n1.split())
    words2 = set(n2.split())
    return bool(words1 & words2) or n1 in n2 or n2 in n1


PAYEE_NAME = "LaserPanel"


async def verify_screenshot_ocr(file_id: str, bot) -> bool:
    if not OCR_AVAILABLE:
        return True
    try:
        file = await bot.get_file(file_id)
        buf  = io.BytesIO()
        await file.download_to_memory(out=buf)
        buf.seek(0)
        img  = Image.open(buf)
        text = pytesseract.image_to_string(img).lower()
        upi        = get_upi()
        upi_local  = upi.split("@")[0].lower() if "@" in upi else upi.lower()
        if PAYEE_NAME.lower() in text or upi_local in text:
            return True
        if len(upi_local) >= 4 and upi_local[:4] in text:
            return True
        return False
    except Exception:
        return True


def db_insert_user(tid, name, phone, site, id_type, amount, utr, screenshot_id):
    """DB mein payment request save karo — 3 baar retry."""
    for attempt in range(3):
        try:
            db.execute(
                """INSERT INTO users
                   (telegram_id,name,phone,site,id_type,amount,utr,screenshot_file_id,status)
                   VALUES (?,?,?,?,?,?,?,?,'pending')""",
                (tid, name, phone, site, id_type, amount, utr, screenshot_id)
            )
            db.commit()
            db.backup_now()
            print(f"✅ DB insert OK — tid={tid} utr={utr} site={site} amount={amount}")
            return True
        except Exception as e:
            print(f"❌ DB insert attempt {attempt+1}/3 FAILED: {type(e).__name__}: {e}")
            print(traceback.format_exc())
            if attempt < 2:
                time.sleep(1)
    print(f"❌ DB insert GAVE UP after 3 attempts — tid={tid} utr={utr}")
    return False


async def auto_decline(telegram_id: int, name: str, site: str, amount: str,
                       screenshot_id: str, phone: str, id_type: str, bot):
    try:
        db.execute(
            """INSERT INTO users
               (telegram_id,name,phone,site,id_type,amount,utr,screenshot_file_id,status)
               VALUES (?,?,?,?,?,?,?,?,'declined')""",
            (telegram_id, name, phone, site, id_type, amount, "NAME_MISMATCH", screenshot_id)
        )
        db.commit()
        db.backup_now()
    except Exception as e:
        print(f"auto_decline DB error: {e}")

    try:
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
    except Exception as e:
        print(f"auto_decline message error: {e}")


# ════════════════════════════════════════
#  /start
# ════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user  = update.effective_user
    tid   = update.effective_chat.id
    uname = user.full_name or "Unknown"
    log_chat(tid, uname, "customer", "/start")

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
    log_chat(tid, uname, "bot", "Welcome — ID type select karein")


# ════════════════════════════════════════
#  BUTTON HANDLER
# ════════════════════════════════════════

async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    data = q.data
    tid  = q.message.chat.id

    if data == "type_new":
        context.user_data.clear()
        context.user_data["id_type"] = "new"
        context.user_data["step"]    = "name"
        await q.message.reply_text(
            "✅ *New ID select ki!*\n\n"
            "Sir, aapka *poora naam* kya hai?\n"
            "_(Jaise aapke bank account mein hai)_",
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
            f"_(₹ mein amount type karein, jaise: 500)_\n"
            f"_(Minimum ₹100)_",
            parse_mode="Markdown",
        )


# ════════════════════════════════════════
#  TEXT HANDLER
# ════════════════════════════════════════

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text  = update.message.text.strip()
    step  = context.user_data.get("step")
    tid   = update.effective_chat.id
    uname = context.user_data.get("name") or (update.effective_user.full_name or "Unknown")

    log_chat(tid, uname, "customer", text)

    if not step:
        bot_msg = "🙏 Sir, /start type karein aur shuru karein."
        await update.message.reply_text(bot_msg)
        log_chat(tid, uname, "bot", bot_msg)
        return

    # ── Step 1: Naam ──────────────────────────────────────────────────────────
    if step == "name":
        context.user_data["name"] = text
        context.user_data["step"] = "phone"
        await forward_to_admin(update, context, f"Step: Naam → {text}")
        bot_msg = f"✅ Shukriya {text} Sir! — Mobile number kya hai?"
        await update.message.reply_text(
            f"✅ Shukriya *{text}* Sir!\n\n"
            f"📱 Sir, aapka *mobile number* kya hai?\n"
            f"_(10 digit Indian number ya +91 se shuru karein)_",
            parse_mode="Markdown",
        )
        log_chat(tid, text, "bot", bot_msg)

    # ── Step 2: Phone ─────────────────────────────────────────────────────────
    elif step == "phone":
        if not is_valid_phone(text):
            bot_msg = "⚠️ Sahi mobile number chahiye"
            await update.message.reply_text(
                "⚠️ Sir, *sahi mobile number* bhejein.\n\n"
                "📱 Indian number: 10 digit (jaise: 9876543210)\n"
                "🌍 International: + ke saath (jaise: +919876543210)",
                parse_mode="Markdown",
            )
            log_chat(tid, uname, "bot", bot_msg)
            return

        context.user_data["phone"] = text
        context.user_data["step"]  = "site"
        await forward_to_admin(update, context, f"Step: Phone → {text}")
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
        log_chat(tid, uname, "bot", "Site selection bheja")

    # ── Step 3: Amount → QR ───────────────────────────────────────────────────
    elif step == "amount":
        if not text.isdigit() or int(text) < 100:
            bot_msg = "⚠️ Minimum ₹100 amount chahiye"
            await update.message.reply_text(
                "⚠️ Sir, *minimum ₹100* amount hona chahiye.\n\n"
                "Sahi amount type karein (jaise: 500)",
                parse_mode="Markdown",
            )
            log_chat(tid, uname, "bot", bot_msg)
            return

        context.user_data["amount"] = text
        context.user_data["step"]   = "screenshot"
        upi     = get_upi()
        upi_url = f"upi://pay?pa={upi}&pn=LaserPanel&am={text}&cu=INR"
        caption = (
            f"💳 *Payment Details Sir*\n\n"
            f"📲 UPI ID: `{upi}`\n"
            f"💰 Amount: ₹*{text}*\n\n"
            f"👉 QR scan karein ya UPI ID pe seedha payment karein.\n\n"
            f"✅ *Payment karne ke baad screenshot bhejein Sir.*"
        )
        qr_sent = False
        try:
            buf = io.BytesIO()
            qrcode.make(upi_url).save(buf, format="PNG")
            buf.seek(0)
            await update.message.reply_photo(buf, caption=caption, parse_mode="Markdown")
            qr_sent = True
        except Exception as e:
            print(f"QR error: {e}")
        if not qr_sent:
            await update.message.reply_text(caption, parse_mode="Markdown")

        log_chat(tid, uname, "bot", f"QR bheja — UPI: {upi} | Amount: ₹{text}")

    # ── Step 4: UTR ───────────────────────────────────────────────────────────
    elif step == "utr":
        if not is_valid_utr(text):
            bot_msg = "⚠️ UTR exactly 12 digit hona chahiye"
            await update.message.reply_text(
                "⚠️ Sir, *sahi UTR number* bhejein.\n\n"
                "🔢 UTR exactly *12 digit* ka hona chahiye.\n"
                "_(Jaise: 123456789012)_\n\n"
                "💡 Bank app → Payment History → Transaction ID",
                parse_mode="Markdown",
            )
            log_chat(tid, uname, "bot", bot_msg)
            return

        name          = context.user_data.get("name", "")
        phone         = context.user_data.get("phone", "")
        site          = context.user_data.get("site", "")
        id_type       = context.user_data.get("id_type", "new")
        amount        = context.user_data.get("amount", "")
        screenshot_id = context.user_data.get("screenshot_file_id", "")
        utr           = text

        context.user_data.clear()

        # ── STEP 1: Customer ko message bhejo — DB se pehle ─────────────────
        await update.message.reply_text(
            f"✅ *UTR Receive Ho Gaya Sir!*\n\n"
            f"Dear *{name}* Sir,\n\n"
            f"🔍 Aapka payment check ho raha hai.\n"
            f"⏳ Okay Sir, *5 minute wait karein.*\n\n"
            f"Payment verify hote hi turant ID bhej di jayegi. 🙏",
            parse_mode="Markdown",
        )

        # ── STEP 2: Admin ko notify karo via Telegram ───────────────────────
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    f"🆕 *NEW PAYMENT REQUEST*\n"
                    f"{'─'*28}\n"
                    f"👤 Name: *{name}*\n"
                    f"📱 Phone: {phone}\n"
                    f"🌐 Site: *{site}*\n"
                    f"💰 Amount: ₹*{amount}*\n"
                    f"🔢 UTR: `{utr}`\n"
                    f"🆔 Type: {id_type.upper()}\n"
                    f"🤖 Chat ID: `{tid}`\n"
                    f"{'─'*28}\n"
                    f"Panel → Payments mein Accept/Decline karein"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"Admin notify error: {e}")

        # ── STEP 3: DB mein save karo background mein ───────────────────────
        def _bg_save():
            ok = db_insert_user(tid, name, phone, site, id_type, amount, utr, screenshot_id)
            if not ok:
                print(f"⚠️ BG save failed — tid={tid} utr={utr}. Manual check needed.")
        threading.Thread(target=_bg_save, daemon=True).start()

        log_chat(tid, name, "bot", f"✅ UTR {utr} submit — {site} ₹{amount}")

    # ── Screenshot step pe text aaya ──────────────────────────────────────────
    elif step == "screenshot":
        bot_msg = "📸 Sir, payment ka *screenshot bhejein* (photo) — text nahi."
        await update.message.reply_text(bot_msg, parse_mode="Markdown")
        log_chat(tid, uname, "bot", bot_msg)

    else:
        bot_msg = "🙏 Sir, /start type karein aur shuru karein."
        await update.message.reply_text(bot_msg)
        log_chat(tid, uname, "bot", bot_msg)


# ════════════════════════════════════════
#  PHOTO HANDLER — Screenshot
# ════════════════════════════════════════

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step  = context.user_data.get("step")
    tid   = update.effective_chat.id
    uname = context.user_data.get("name") or (update.effective_user.full_name or "Unknown")

    if step == "screenshot":
        file_id = update.message.photo[-1].file_id

        checking_msg = None
        try:
            checking_msg = await update.message.reply_text(
                "🔍 *Screenshot verify ho rahi hai Sir...*",
                parse_mode="Markdown",
            )
        except Exception:
            pass

        try:
            is_valid = await verify_screenshot_ocr(file_id, context.bot)
        except Exception:
            is_valid = True

        try:
            if checking_msg:
                await checking_msg.delete()
        except Exception:
            pass

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
            "_(Payment ke baad milne wala 12 digit ka number)_\n\n"
            "💡 Bank app → Payment History → Transaction ID",
            parse_mode="Markdown",
        )
        log_chat(tid, uname, "bot", "Screenshot OK — UTR maanga")

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
    try:
        user     = update.effective_user
        chat_id  = update.effective_chat.id
        name     = user.full_name or "Unknown"
        username = f"@{user.username}" if user.username else "no username"
        header   = (
            f"👤 *Customer:* {name} ({username})\n"
            f"🆔 Chat ID: `{chat_id}`\n"
            f"_{extra}_\n"
            f"{'─'*25}"
        )
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=header, parse_mode="Markdown"
        )
        await update.message.forward(chat_id=ADMIN_CHAT_ID)
    except Exception as e:
        print(f"forward_to_admin error: {e}")


# ════════════════════════════════════════
#  /reply COMMAND — Admin reply
# ════════════════════════════════════════

async def cmd_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await context.bot.send_message(chat_id=int(target_id), text=f"💬 {message}")
        await update.message.reply_text(f"✅ Message bhej diya `{target_id}` ko!", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ════════════════════════════════════════
#  GLOBAL ERROR HANDLER
# ════════════════════════════════════════

async def error_handler(update, context):
    print(f"Bot error: {context.error}")
    try:
        if update and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ *Kuch error aa gaya Sir.* /start karke dobara try karein.\n\n"
                     "Problem ho toh: 👉 https://wa.me/919520668248",
                parse_mode="Markdown"
            )
    except Exception:
        pass


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
    app.add_error_handler(error_handler)
    print("✅ Laser Panel Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
