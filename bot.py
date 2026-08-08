import os
import sqlite3
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
ADMIN_ID = int(os.environ["ADMIN_ID"])
PAYMENT_LINK = os.environ["PAYMENT_LINK"]

DB = "users.db"


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            expires_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_user(user_id, username):
    conn = sqlite3.connect(DB)
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (user_id, username)
    )
    conn.commit()
    conn.close()


def activate_user(user_id):
    expires = datetime.now(timezone.utc) + timedelta(days=30)

    conn = sqlite3.connect(DB)
    conn.execute(
        """
        INSERT INTO users (user_id, expires_at)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET expires_at = excluded.expires_at
        """,
        (user_id, expires.isoformat())
    )
    conn.commit()
    conn.close()

    return expires


def get_user(user_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id, username, expires_at FROM users WHERE user_id = ?",
        (user_id,)
    )

    result = cur.fetchone()
    conn.close()

    return result


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    save_user(
        user.id,
        user.username or user.first_name
    )

    keyboard = [
        [InlineKeyboardButton("💳 Πληρωμή 10€", url=PAYMENT_LINK)],
        [InlineKeyboardButton("📅 Η συνδρομή μου", callback_data="status")]
    ]

    await update.message.reply_text(
        "Καλώς ήρθες!\n\n"
        "Η πρόσβαση στο κανάλι κοστίζει 10€ για 30 ημέρες.\n\n"
        "1️⃣ Πλήρωσε 10€ από το παρακάτω link.\n"
        "2️⃣ Μετά την πληρωμή, περίμενε να επιβεβαιώσουμε την πληρωμή σου.\n"
        "3️⃣ Η πρόσβαση ενεργοποιείται χειροκίνητα.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = get_user(query.from_user.id)

    if not user or not user[2]:
        await query.message.reply_text(
            "❌ Δεν έχεις ενεργή συνδρομή."
        )
        return

    expires = datetime.fromisoformat(user[2])

    if expires <= datetime.now(timezone.utc):
        await query.message.reply_text(
            "❌ Η συνδρομή σου έχει λήξει."
        )
    else:
        await query.message.reply_text(
            f"✅ Η συνδρομή σου είναι ενεργή.\n\n"
            f"Λήγει: {expires.strftime('%d/%m/%Y %H:%M')}"
        )


async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "Χρήση:\n/activate USER_ID"
        )
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Μη έγκυρο User ID.")
        return

    user = get_user(user_id)

    if not user:
        await update.message.reply_text(
            "❌ Δεν βρέθηκε αυτός ο χρήστης."
        )
        return

    expires = activate_user(user_id)

    try:
        invite = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "✅ Η πληρωμή σου επιβεβαιώθηκε!\n\n"
                "Η συνδρομή σου ενεργοποιήθηκε για 30 ημέρες.\n\n"
                "👇 Πάτησε τον σύνδεσμο για να μπεις στο κανάλι:"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔐 ΕΙΣΟΔΟΣ ΣΤΟ ΚΑΝΑΛΙ",
                    url=invite.invite_link
                )]
            ])
        )

        await update.message.reply_text(
            f"✅ Ενεργοποιήθηκε ο χρήστης {user_id}.\n"
            f"Λήξη: {expires.strftime('%d/%m/%Y %H:%M')}"
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Έγινε ενεργοποίηση αλλά δεν μπόρεσα "
            f"να δημιουργήσω σύνδεσμο εισόδου.\n\n{e}"
        )


async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id, username, expires_at FROM users ORDER BY expires_at"
    )

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Δεν υπάρχουν χρήστες.")
        return

    text = "👥 ΧΡΗΣΤΕΣ\n\n"

    for user_id, username, expires in rows:
        text += (
            f"👤 {username or '-'}\n"
            f"ID: `{user_id}`\n"
            f"Λήξη: {expires or 'Μη ενεργός'}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


async def check_expired(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(timezone.utc)

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id, expires_at FROM users WHERE expires_at IS NOT NULL"
    )

    rows = cur.fetchall()

    for user_id, expires_at in rows:
        expires = datetime.fromisoformat(expires_at)

        if expires <= now:
            try:
                await context.bot.ban_chat_member(
                    chat_id=CHANNEL_ID,
                    user_id=user_id
                )

                await context.bot.unban_chat_member(
                    chat_id=CHANNEL_ID,
                    user_id=user_id,
                    only_if_banned=True
                )

                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "⏰ Η συνδρομή σου έληξε.\n\n"
                        "Για να συνεχίσεις την πρόσβαση, "
                        "χρειάζεται νέα πληρωμή 10€."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            "💳 ΠΛΗΡΩΜΗ 10€",
                            url=PAYMENT_LINK
                        )]
                    ])
                )

                cur.execute(
                    "UPDATE users SET expires_at = NULL WHERE user_id = ?",
                    (user_id,)
                )

            except Exception:
                pass

    conn.commit()
    conn.close()


def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CommandHandler("users", users))
    app.add_handler(CallbackQueryHandler(status, pattern="^status$"))

    app.job_queue.run_repeating(
        check_expired,
        interval=3600,
        first=60
    )

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
