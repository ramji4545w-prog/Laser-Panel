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
UPI_ID = os.environ["UPI_ID"]

SITES = ["Laser247", "Tiger399", "AllPanel", "Diamond"]

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    name TEXT,
    phone TEXT,
    site TEXT,
    amount TEXT,
    utr TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()


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

    if data.startswith("type:"):
        id_type = data.split(":")[1]
        context.user_data["type"] = id_type
        context.user_data.pop("site", None)
        context.user_data.pop("name", None)
        context.user_data.pop("phone", None)
        context.user_data.pop("amount", None)

        keyboard = [
            [InlineKeyboardButton(site, callback_data=f"site:{site}")]
            for site in SITES
        ]
        await query.message.reply_text(
            "📌 Sir, please select your site:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

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
        await update.message.reply_text(
            "Please use /start to begin."
        )
        return

    if "name" not in context.user_data:
        context.user_data["name"] = text
        await update.message.reply_text("📱 Sir, please enter your phone number:")

    elif "phone" not in context.user_data:
        context.user_data["phone"] = text
        await update.message.reply_text("💰 Sir, please enter the deposit amount (₹):")

    elif "amount" not in context.user_data:
        context.user_data["amount"] = text

        upi_url = f"upi://pay?pa={UPI_ID}&pn=Payment&am={text}&cu=INR"
        img = qrcode.make(upi_url)
        img.save("qr.png")

        await update.message.reply_photo(
            photo=open("qr.png", "rb"),
            caption=(
                f"💳 Sir, please complete the payment\n\n"
                f"UPI ID: `{UPI_ID}`\n"
                f"Amount: ₹{text}\n\n"
                f"📸 After payment, send the screenshot along with your UTR number."
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
    utr = context.user_data.get("utr", "N/A")
    name = context.user_data.get("name")
    phone = context.user_data.get("phone")
    site = context.user_data.get("site")
    amount = context.user_data.get("amount")

    if not all([name, phone, site, amount]):
        await update.message.reply_text("Please use /start to begin.")
        return

    cursor.execute(
        "INSERT INTO users (telegram_id, name, phone, site, amount, utr, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (update.effective_user.id, name, phone, site, amount, utr, "pending"),
    )
    conn.commit()

    await update.message.reply_text(
        "✅ Sir, your request has been submitted!\n⏳ Please wait 2-5 minutes for your ID to be activated."
    )

    photo_file = update.message.photo[-1].file_id
    await context.bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=photo_file,
        caption=(
            f"📥 *New Payment Request*\n\n"
            f"👤 Name: {name}\n"
            f"📱 Phone: {phone}\n"
            f"🌐 Site: {site}\n"
            f"🎮 Type: {context.user_data.get('type', 'N/A').upper()}\n"
            f"💰 Amount: ₹{amount}\n"
            f"🔢 UTR: {utr}\n"
            f"🆔 Telegram ID: {update.effective_user.id}"
        ),
        parse_mode="Markdown",
    )

    context.user_data.clear()


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(MessageHandler(filters.PHOTO, message_handler))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
