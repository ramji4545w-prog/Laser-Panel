import os
import sqlite3
import qrcode
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
# Migration: add id_pass if missing
try:
    cursor.execute("ALTER TABLE users ADD COLUMN id_pass TEXT")
except Exception:
    pass
conn.commit()


def get_upi():
    row = cursor.execute("SELECT upi FROM settings WHERE id=1").fetchone()
    return row[0] if row else DEFAULT_UPI


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_CHAT_ID:
            await update.message.reply_text("⛔ You are not authorized to use this command.")
            return
        return await func(update, context)
    return wrapper


# ─────────────────────────── USER COMMANDS ───────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("🔥 New ID", callback_data="type:new")],
        [InlineKeyboardButton("🎮 Demo ID", callback_data="type:demo")],
    ]
    await update.message.reply_text(
        "🙏 Welcome Sir!\nPlease select an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── Admin: approve/reject buttons ──
    if data.startswith("approve:") or data.startswith("reject:"):
        if update.effective_user.id != ADMIN_CHAT_ID:
            await query.answer("⛔ Not authorized.", show_alert=True)
            return
        action, req_id = data.split(":")
        await handle_admin_action(query, context, action, int(req_id))
        return

    # ── User: select type ──
    if data.startswith("type:"):
        id_type = data.split(":")[1]
        context.user_data.clear()
        context.user_data["type"] = id_type
        keyboard = [
            [InlineKeyboardButton(site, callback_data=f"site:{site}")]
            for site in SITES
        ]
        await query.message.reply_text(
            "📌 Sir, please select your site:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ── User: select site ──
    elif data.startswith("site:"):
        site = data.split(":", 1)[1]
        context.user_data["site"] = site
        await query.message.reply_text("👤 Sir, please enter your full name:")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        await handle_screenshot(update, context)
        return

    text = update.message.text.strip()

    if "site" not in context.user_data:
        await update.message.reply_text("Please use /start to begin.")
        return

    if "name" not in context.user_data:
        context.user_data["name"] = text
        await update.message.reply_text("📱 Sir, please enter your phone number:")

    elif "phone" not in context.user_data:
        context.user_data["phone"] = text
        await update.message.reply_text("💰 Sir, please enter the deposit amount (₹):")

    elif "amount" not in context.user_data:
        context.user_data["amount"] = text

        upi_id = get_upi()
        upi_url = f"upi://pay?pa={upi_id}&pn=Payment&am={text}&cu=INR"
        img = qrcode.make(upi_url)
        img.save("qr.png")

        await update.message.reply_photo(
            photo=open("qr.png", "rb"),
            caption=(
                f"💳 Sir, please complete the payment\n\n"
                f"UPI ID: `{upi_id}`\n"
                f"Amount: ₹{text}\n\n"
                f"📸 After payment, first send your *UTR number*, then send the screenshot."
            ),
            parse_mode="Markdown",
        )

    elif "utr" not in context.user_data:
        context.user_data["utr"] = text
        await update.message.reply_text(
            "📸 Sir, now please send your payment screenshot:"
        )

    else:
        await update.message.reply_text(
            "Please send your payment screenshot (image) now."
        )


async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("name")
    phone = context.user_data.get("phone")
    site = context.user_data.get("site")
    amount = context.user_data.get("amount")
    utr = context.user_data.get("utr", "N/A")
    id_type = context.user_data.get("type", "N/A")

    if not all([name, phone, site, amount]):
        await update.message.reply_text("Please use /start to begin.")
        return

    cursor.execute(
        "INSERT INTO users (telegram_id, name, phone, site, id_type, amount, utr, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (update.effective_user.id, name, phone, site, id_type, amount, utr, "pending"),
    )
    conn.commit()
    req_id = cursor.lastrowid

    await update.message.reply_text(
        f"✅ Sir, your request has been submitted! (Request #{req_id})\n"
        f"⏳ Please wait 2-5 minutes for your ID to be activated."
    )

    # Send to admin with approve/reject buttons
    photo_file = update.message.photo[-1].file_id
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ Approve #{req_id}", callback_data=f"approve:{req_id}"),
            InlineKeyboardButton(f"❌ Reject #{req_id}", callback_data=f"reject:{req_id}"),
        ]
    ])

    await context.bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=photo_file,
        caption=(
            f"📥 *New Payment Request #{req_id}*\n\n"
            f"👤 Name: {name}\n"
            f"📱 Phone: {phone}\n"
            f"🌐 Site: {site}\n"
            f"🎮 Type: {id_type.upper()}\n"
            f"💰 Amount: ₹{amount}\n"
            f"🔢 UTR: {utr}\n"
            f"🆔 Telegram ID: {update.effective_user.id}"
        ),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

    context.user_data.clear()


# ─────────────────────────── ADMIN ACTION ───────────────────────────

async def handle_admin_action(query, context, action, req_id):
    row = cursor.execute(
        "SELECT telegram_id, name, site, amount, status FROM users WHERE id = ?", (req_id,)
    ).fetchone()

    if not row:
        await query.edit_message_caption(
            caption=query.message.caption + f"\n\n⚠️ Request #{req_id} not found.",
            parse_mode="Markdown",
        )
        return

    telegram_id, name, site, amount, current_status = row

    if current_status != "pending":
        await query.answer(f"Already {current_status}.", show_alert=True)
        return

    if action == "approve":
        cursor.execute("UPDATE users SET status = 'approved' WHERE id = ?", (req_id,))
        conn.commit()

        # Notify user
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                f"🎉 *Congratulations {name} Sir!*\n\n"
                f"Your payment of ₹{amount} for *{site}* has been *approved*!\n"
                f"Your ID will be activated shortly. 🚀"
            ),
            parse_mode="Markdown",
        )

        # Update admin message
        new_caption = query.message.caption + f"\n\n✅ *APPROVED* by admin."
        await query.edit_message_caption(caption=new_caption, parse_mode="Markdown")
        await query.answer("✅ Approved and user notified!", show_alert=True)

    elif action == "reject":
        cursor.execute("UPDATE users SET status = 'rejected' WHERE id = ?", (req_id,))
        conn.commit()

        # Notify user
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                f"❌ *Dear {name} Sir,*\n\n"
                f"Your payment request of ₹{amount} for *{site}* has been *rejected*.\n\n"
                f"Please contact support or try again with /start."
            ),
            parse_mode="Markdown",
        )

        # Update admin message
        new_caption = query.message.caption + f"\n\n❌ *REJECTED* by admin."
        await query.edit_message_caption(caption=new_caption, parse_mode="Markdown")
        await query.answer("❌ Rejected and user notified!", show_alert=True)


# ─────────────────────────── ADMIN COMMANDS ───────────────────────────

@admin_only
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = cursor.execute(
        "SELECT id, name, site, amount, status, created_at FROM users ORDER BY id DESC LIMIT 15"
    ).fetchall()

    if not rows:
        await update.message.reply_text("No requests yet.")
        return

    lines = ["📋 *Recent Requests (last 15)*\n"]
    for r in rows:
        req_id, name, site, amount, status, created_at = r
        emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(status, "❓")
        lines.append(f"{emoji} *#{req_id}* — {name} | {site} | ₹{amount} | {status}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = cursor.execute(
        "SELECT id, name, phone, site, id_type, amount, utr FROM users WHERE status = 'pending' ORDER BY id DESC"
    ).fetchall()

    if not rows:
        await update.message.reply_text("✅ No pending requests.")
        return

    lines = [f"⏳ *{len(rows)} Pending Request(s)*\n"]
    for r in rows:
        req_id, name, phone, site, id_type, amount, utr = r
        lines.append(
            f"*#{req_id}* — {name} | {phone}\n"
            f"  🌐 {site} | 🎮 {(id_type or 'N/A').upper()} | ₹{amount} | UTR: {utr}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /approve <request_id>")
        return
    req_id = int(context.args[0])

    row = cursor.execute(
        "SELECT telegram_id, name, site, amount, status FROM users WHERE id = ?", (req_id,)
    ).fetchone()

    if not row:
        await update.message.reply_text(f"❌ Request #{req_id} not found.")
        return

    telegram_id, name, site, amount, status = row
    if status != "pending":
        await update.message.reply_text(f"Request #{req_id} is already {status}.")
        return

    cursor.execute("UPDATE users SET status = 'approved' WHERE id = ?", (req_id,))
    conn.commit()

    await context.bot.send_message(
        chat_id=telegram_id,
        text=(
            f"🎉 *Congratulations {name} Sir!*\n\n"
            f"Your payment of ₹{amount} for *{site}* has been *approved*!\n"
            f"Your ID will be activated shortly. 🚀"
        ),
        parse_mode="Markdown",
    )
    await update.message.reply_text(f"✅ Request #{req_id} approved and user notified.")


@admin_only
async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /reject <request_id>")
        return
    req_id = int(context.args[0])

    row = cursor.execute(
        "SELECT telegram_id, name, site, amount, status FROM users WHERE id = ?", (req_id,)
    ).fetchone()

    if not row:
        await update.message.reply_text(f"❌ Request #{req_id} not found.")
        return

    telegram_id, name, site, amount, status = row
    if status != "pending":
        await update.message.reply_text(f"Request #{req_id} is already {status}.")
        return

    cursor.execute("UPDATE users SET status = 'rejected' WHERE id = ?", (req_id,))
    conn.commit()

    await context.bot.send_message(
        chat_id=telegram_id,
        text=(
            f"❌ *Dear {name} Sir,*\n\n"
            f"Your payment request of ₹{amount} for *{site}* has been *rejected*.\n\n"
            f"Please contact support or try again with /start."
        ),
        parse_mode="Markdown",
    )
    await update.message.reply_text(f"❌ Request #{req_id} rejected and user notified.")


@admin_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    pending = cursor.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0]
    approved = cursor.execute("SELECT COUNT(*) FROM users WHERE status='approved'").fetchone()[0]
    rejected = cursor.execute("SELECT COUNT(*) FROM users WHERE status='rejected'").fetchone()[0]
    total_amount = cursor.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) FROM users WHERE status='approved'"
    ).fetchone()[0]

    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"📋 Total Requests: {total}\n"
        f"⏳ Pending: {pending}\n"
        f"✅ Approved: {approved}\n"
        f"❌ Rejected: {rejected}\n"
        f"💰 Total Approved Amount: ₹{total_amount:,.0f}",
        parse_mode="Markdown",
    )


# ─────────────────────────── MAIN ───────────────────────────

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # User
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(MessageHandler(filters.PHOTO, message_handler))

    # Buttons (user + admin inline)
    app.add_handler(CallbackQueryHandler(button))

    # Admin commands
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject", cmd_reject))
    app.add_handler(CommandHandler("stats", cmd_stats))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
