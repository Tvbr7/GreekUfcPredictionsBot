import os
import sqlite3
from datetime import datetime, timedelta, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ChatMemberHandler,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
PAYMENT_LINK = os.environ["PAYMENT_LINK"]

DB = "users.db"


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            expires_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def set_setting(key, value):
    conn = sqlite3.connect(DB)
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()


def get_setting(key):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    )

    result = cur.fetchone()
    conn.close()

    return result[0] if result else None


def save_user(user_id, username):
    conn = sqlite3.connect(DB)

    conn.execute("""
        INSERT INTO users (user_id, username)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET username = excluded.username
    """, (user_id, username))

    conn.commit()
    conn.close()


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


def activate_user(user_id):
    expires = datetime.now(timezone.utc) + timedelta(days=30)

    conn = sqlite3.connect(DB)

    conn.execute("""
        INSERT INTO users (user_id, expires_at)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET expires_at = excluded.expires_at
    """, (user_id, expires.isoformat()))

    conn.commit()
    conn.close()

    return expires


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    save_user(
        user.id,
        user.username or user.first_name
    )

    # Ο πρώτος χρήστης που κάνει /start μπορεί να γίνει admin
    admin_id = get_setting("admin_id")

    if not admin_id:
        set_setting("admin_id", str(user.id))

        await update.message.reply_text(
            "✅ Ο λογαριασμός σου ορίστηκε ως διαχειριστής του bot.\n\n"
            "Τώρα μπορείς να χρησιμοποιήσεις /admin."
        )

    keyboard = [
        [
            InlineKeyboardButton(
                "💳 Πληρωμή 10€",
                url=PAYMENT_LINK
            )
        ],
        [
            InlineKeyboardButton(
                "📅 Η συνδρομή μου",
                callback_data="status"
            )
        ]
    ]

    await update.message.reply_text(
        "👋 Καλώς ήρθες!\n\n"
        "Η πρόσβαση στο private κανάλι κοστίζει "
        "10€ για 30 ημέρες.\n\n"
        "1️⃣ Πάτησε «Πληρωμή 10€».\n"
        "2️⃣ Κάνε την πληρωμή μέσω Revolut.\n"
        "3️⃣ Μετά την πληρωμή περιμένεις "
        "τη χειροκίνητη επιβεβαίωση.",
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
            "❌ Η συνδρομή σου έχει λήξει.\n\n"
            "Πάτησε «Πληρωμή 10€» για ανανέωση."
        )

    else:

        await query.message.reply_text(
            "✅ Η συνδρομή σου είναι ενεργή.\n\n"
            f"📅 Λήγει: {expires.strftime('%d/%m/%Y %H:%M')}"
        )


def is_admin(user_id):

    admin_id = get_setting("admin_id")

    return admin_id and int(admin_id) == user_id


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        "🔐 Πίνακας διαχειριστή\n\n"
        "/activate USER_ID - Ενεργοποίηση 30 ημερών\n"
        "/users - Λίστα χρηστών\n"
        "/channel - Εμφάνιση ID καναλιού\n"
        "/myid - Εμφάνιση δικού σου ID"
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        f"Το Telegram ID σου είναι:\n\n"
        f"{update.effective_user.id}"
    )


async def channel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        return

    channel_id = get_setting("channel_id")

    if channel_id:

        await update.message.reply_text(
            f"📢 Το ID του καναλιού είναι:\n\n"
            f"`{channel_id}`",
            parse_mode="Markdown"
        )

    else:

        await update.message.reply_text(
            "❌ Δεν έχω καταγράψει ακόμα το ID του καναλιού.\n\n"
            "Στείλε ένα νέο μήνυμα στο κανάλι "
            "αφού το bot είναι διαχειριστής."
        )


async def bot_added_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    member_update = update.my_chat_member

    if not member_update:
        return

    chat = member_update.chat

    # Αποθηκεύουμε το ID του καναλιού
    if chat.type == "channel":

        set_setting(
            "channel_id",
            str(chat.id)
        )


async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        return

    if not context.args:

        await update.message.reply_text(
            "Χρήση:\n\n"
            "/activate USER_ID"
        )

        return

    try:

        user_id = int(context.args[0])

    except ValueError:

        await update.message.reply_text(
            "❌ Το User ID δεν είναι σωστό."
        )

        return

    user = get_user(user_id)

    if not user:

        await update.message.reply_text(
            "❌ Δεν βρέθηκε αυτός ο χρήστης."
        )

        return

    channel_id = get_setting("channel_id")

    if not channel_id:

        await update.message.reply_text(
            "❌ Δεν έχει καταχωρηθεί το ID του καναλιού."
        )

        return

    expires = activate_user(user_id)

    try:

        invite = await context.bot.create_chat_invite_link(
            chat_id=int(channel_id),
            member_limit=1
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "✅ Η πληρωμή σου επιβεβαιώθηκε!\n\n"
                "Η συνδρομή σου ενεργοποιήθηκε για 30 ημέρες.\n\n"
                "Πάτησε παρακάτω για να μπεις στο private κανάλι."
            ),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔐 ΕΙΣΟΔΟΣ ΣΤΟ ΚΑΝΑΛΙ",
                        url=invite.invite_link
                    )
                ]
            ])
        )

        await update.message.reply_text(
            "✅ Ο χρήστης ενεργοποιήθηκε.\n\n"
            f"👤 ID: {user_id}\n"
            f"📅 Λήξη: {expires.strftime('%d/%m/%Y %H:%M')}"
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ Παρουσιάστηκε σφάλμα:\n{e}"
        )


async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        return

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id, username, expires_at "
        "FROM users ORDER BY expires_at"
    )

    rows = cur.fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "Δεν υπάρχουν χρήστες."
        )

        return

    text = "👥 ΧΡΗΣΤΕΣ\n\n"

    for user_id, username, expires in rows:

        text += (
            f"👤 {username or '-'}\n"
            f"ID: {user_id}\n"
            f"Λήξη: {expires or '❌ Μη ενεργός'}\n\n"
        )

    await update.message.reply_text(text)


async def check_expired(context: ContextTypes.DEFAULT_TYPE):

    channel_id = get_setting("channel_id")

    if not channel_id:
        return

    now = datetime.now(timezone.utc)

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id, expires_at "
        "FROM users WHERE expires_at IS NOT NULL"
    )

    rows = cur.fetchall()

    for user_id, expires_at in rows:

        expires = datetime.fromisoformat(expires_at)

        if expires <= now:

            try:

                await context.bot.ban_chat_member(
                    chat_id=int(channel_id),
                    user_id=user_id
                )

                await context.bot.unban_chat_member(
                    chat_id=int(channel_id),
                    user_id=user_id
                )

                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "⏰ Η συνδρομή σου έληξε.\n\n"
                        "Για να συνεχίσεις την πρόσβαση, "
                        "χρειάζεται νέα πληρωμή 10€."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "💳 ΠΛΗΡΩΜΗ 10€",
                                url=PAYMENT_LINK
                            )
                        ]
                    ])
                )

                cur.execute(
                    "UPDATE users SET expires_at = NULL "
                    "WHERE user_id = ?",
                    (user_id,)
                )

            except Exception:
                pass

    conn.commit()
    conn.close()


def main():

    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("admin", admin)
    )

    app.add_handler(
        CommandHandler("myid", myid)
    )

    app.add_handler(
        CommandHandler("channel", channel)
    )

    app.add_handler(
        CommandHandler("activate", activate)
    )

    app.add_handler(
        CommandHandler("users", users)
    )

    app.add_handler(
        CallbackQueryHandler(
            status,
            pattern="^status$"
        )
    )

    app.add_handler(
        ChatMemberHandler(
            bot_added_to_channel,
            ChatMemberHandler.MY_CHAT_MEMBER
        )
    )

    app.job_queue.run_repeating(
        check_expired,
        interval=3600,
        first=60
    )

    print("Bot started.")

    app.run_polling()


if __name__ == "__main__":
    main()
