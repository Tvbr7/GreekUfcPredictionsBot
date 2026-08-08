import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ChatMemberHandler,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
PAYMENT_LINK = os.environ["PAYMENT_LINK"]

ADMIN_ID = 8149217025

DB = "users.db"


# ==================================================
# RENDER WEB SERVER
# ==================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)
        self.send_header(
            "Content-type",
            "text/plain"
        )
        self.end_headers()

        self.wfile.write(
            b"Bot is running!"
        )

    def log_message(self, format, *args):
        return


def start_web_server():

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(
        f"Web server running on port {port}"
    )

    server.serve_forever()


# ==================================================
# DATABASE
# ==================================================

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
        """
        INSERT OR REPLACE INTO settings
        (key, value)
        VALUES (?, ?)
        """,
        (
            key,
            value
        )
    )

    conn.commit()

    conn.close()


def get_setting(key):

    conn = sqlite3.connect(DB)

    cur = conn.cursor()

    cur.execute(
        """
        SELECT value
        FROM settings
        WHERE key = ?
        """,
        (key,)
    )

    result = cur.fetchone()

    conn.close()

    if result:

        return result[0]

    return None


# ==================================================
# USERS
# ==================================================

def save_user(
    user_id,
    username
):

    conn = sqlite3.connect(DB)

    conn.execute(
        """
        INSERT INTO users
        (user_id, username)
        VALUES (?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
        username = excluded.username
        """,
        (
            user_id,
            username
        )
    )

    conn.commit()

    conn.close()


def get_user_by_username(username):

    username = (
        username
        .replace("@", "")
        .lower()
    )

    conn = sqlite3.connect(DB)

    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            user_id,
            username,
            expires_at

        FROM users

        WHERE LOWER(username) = ?
        """,
        (username,)
    )

    result = cur.fetchone()

    conn.close()

    return result


def activate_user(user_id):

    expires = (
        datetime.now(timezone.utc)
        + timedelta(days=30)
    )

    conn = sqlite3.connect(DB)

    conn.execute(
        """
        INSERT INTO users
        (user_id, expires_at)

        VALUES (?, ?)

        ON CONFLICT(user_id)

        DO UPDATE SET
        expires_at = excluded.expires_at
        """,
        (
            user_id,
            expires.isoformat()
        )
    )

    conn.commit()

    conn.close()

    return expires


# ==================================================
# ADMIN
# ==================================================

def is_admin(user_id):

    return user_id == ADMIN_ID


async def admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        return

    await update.message.reply_text(

        "🔐 ΠΙΝΑΚΑΣ ΔΙΑΧΕΙΡΙΣΤΗ\n\n"

        "/activate @username - "
        "Ενεργοποίηση 30 ημερών\n"

        "/users - Λίστα χρηστών\n"

        "/channel - ID καναλιού\n"

        "/myid - Το δικό σου ID"

    )


# ==================================================
# START
# ==================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    username = user.username

    if username:

        username = username.lower()

    else:

        username = user.first_name

    save_user(
        user.id,
        username
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

        "Η πρόσβαση στο private κανάλι "
        "κοστίζει 10€ για 30 ημέρες.\n\n"

        "1️⃣ Πάτησε «Πληρωμή 10€».\n"

        "2️⃣ Κάνε την πληρωμή μέσω Revolut.\n"

        "3️⃣ Γράψε το Telegram username σου "
        "στη σημείωση της πληρωμής.\n"

        "4️⃣ Μετά την επιβεβαίωση θα ενεργοποιηθεί "
        "χειροκίνητα η πρόσβασή σου.\n\n"

        "⚠️ Πρέπει να έχεις πατήσει START "
        "στο bot.",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )

    )


# ==================================================
# MY ID
# ==================================================

async def myid(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "Το Telegram ID σου είναι:\n\n"

        f"{update.effective_user.id}"

    )


# ==================================================
# STATUS
# ==================================================

async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    conn = sqlite3.connect(DB)

    cur = conn.cursor()

    cur.execute(
        """
        SELECT expires_at
        FROM users
        WHERE user_id = ?
        """,
        (
            query.from_user.id,
        )
    )

    result = cur.fetchone()

    conn.close()

    if not result or not result[0]:

        await query.message.reply_text(

            "❌ Δεν έχεις ενεργή συνδρομή."

        )

        return

    expires = datetime.fromisoformat(
        result[0]
    )

    if expires <= datetime.now(
        timezone.utc
    ):

        await query.message.reply_text(

            "❌ Η συνδρομή σου έχει λήξει.\n\n"
            "Πάτησε «Πληρωμή 10€» για ανανέωση.",

            reply_markup=InlineKeyboardMarkup([

                [

                    InlineKeyboardButton(
                        "💳 Πληρωμή 10€",
                        url=PAYMENT_LINK
                    )

                ]

            ])

        )

    else:

        await query.message.reply_text(

            "✅ Η συνδρομή σου είναι ενεργή.\n\n"

            f"📅 Λήγει: "
            f"{expires.strftime('%d/%m/%Y %H:%M')}"

        )


# ==================================================
# CHANNEL ID
# ==================================================

async def channel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        return

    channel_id = get_setting(
        "channel_id"
    )

    if channel_id:

        await update.message.reply_text(

            f"📢 ID καναλιού:\n\n"
            f"`{channel_id}`",

            parse_mode="Markdown"

        )

    else:

        await update.message.reply_text(

            "❌ Δεν έχω καταχωρήσει ακόμα "
            "το ID του καναλιού.\n\n"

            "Βεβαιώσου ότι το bot είναι "
            "διαχειριστής και στείλε ένα "
            "νέο μήνυμα στο κανάλι."

        )


# ==================================================
# BOT ADDED TO CHANNEL
# ==================================================

async def bot_added_to_channel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    member_update = (
        update.my_chat_member
    )

    if not member_update:

        return

    chat = member_update.chat

    if chat.type == "channel":

        set_setting(
            "channel_id",
            str(chat.id)
        )

        print(
            f"Channel ID saved: {chat.id}"
        )


# ==================================================
# CHANNEL MESSAGE
# ==================================================

async def channel_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.channel_post:

        return

    channel_chat = (
        update.channel_post.chat
    )

    if channel_chat.type != "channel":

        return

    set_setting(
        "channel_id",
        str(channel_chat.id)
    )

    print(
        f"Channel ID saved from message: "
        f"{channel_chat.id}"
    )


# ==================================================
# ACTIVATE USER
# ==================================================

async def activate(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        return

    if not context.args:

        await update.message.reply_text(

            "Χρήση:\n\n"
            "/activate @username"

        )

        return

    username = (
        context.args[0]
        .replace("@", "")
        .lower()
    )

    user = get_user_by_username(
        username
    )

    if not user:

        await update.message.reply_text(

            "❌ Δεν βρέθηκε αυτό το username.\n\n"

            "Ο χρήστης πρέπει πρώτα να έχει "
            "πατήσει START στο bot."

        )

        return

    user_id = user[0]

    channel_id = get_setting(
        "channel_id"
    )

    if not channel_id:

        await update.message.reply_text(

            "❌ Δεν έχω βρει το ID του καναλιού."

        )

        return

    expires = activate_user(
        user_id
    )

    try:

        invite = (
            await context.bot
            .create_chat_invite_link(

                chat_id=int(
                    channel_id
                ),

                member_limit=1

            )
        )

        await context.bot.send_message(

            chat_id=user_id,

            text=(

                "✅ Η πληρωμή σου "
                "επιβεβαιώθηκε!\n\n"

                "Η συνδρομή σου ενεργοποιήθηκε "
                "για 30 ημέρες.\n\n"

                "Πάτησε παρακάτω για να μπεις "
                "στο private κανάλι."

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

            "✅ ΕΝΕΡΓΟΠΟΙΗΘΗΚΕ\n\n"

            f"👤 @{username}\n"

            f"📅 Λήξη: "
            f"{expires.strftime('%d/%m/%Y %H:%M')}"

        )

    except Exception as e:

        await update.message.reply_text(

            f"❌ Παρουσιάστηκε σφάλμα:\n{e}"

        )


# ==================================================
# USERS LIST
# ==================================================

async def users(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        return

    conn = sqlite3.connect(DB)

    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            user_id,
            username,
            expires_at

        FROM users

        ORDER BY expires_at
        """
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

            f"👤 @{username}\n"

            f"ID: {user_id}\n"

            f"Λήξη: "
            f"{expires or '❌ Μη ενεργός'}\n\n"

        )

    await update.message.reply_text(
        text
    )


# ==================================================
# REMOVE EXPIRED USERS
# ==================================================

async def check_expired(
    context: ContextTypes.DEFAULT_TYPE
):

    channel_id = get_setting(
        "channel_id"
    )

    if not channel_id:

        return

    now = datetime.now(
        timezone.utc
    )

    conn = sqlite3.connect(DB)

    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            user_id,
            expires_at

        FROM users

        WHERE expires_at IS NOT NULL
        """
    )

    rows = cur.fetchall()

    for user_id, expires_at in rows:

        expires = datetime.fromisoformat(
            expires_at
        )

        if expires <= now:

            try:

                await context.bot.ban_chat_member(

                    chat_id=int(
                        channel_id
                    ),

                    user_id=user_id

                )

                await context.bot.unban_chat_member(

                    chat_id=int(
                        channel_id
                    ),

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

                    """
                    UPDATE users
                    SET expires_at = NULL
                    WHERE user_id = ?
                    """,

                    (user_id,)

                )

            except Exception as e:

                print(
                    f"Error removing user "
                    f"{user_id}: {e}"
                )

    conn.commit()

    conn.close()


# ==================================================
# MAIN
# ==================================================

def main():

    init_db()

    web_thread = threading.Thread(

        target=start_web_server,

        daemon=True

    )

    web_thread.start()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin
        )
    )

    app.add_handler(
        CommandHandler(
            "myid",
            myid
        )
    )

    app.add_handler(
        CommandHandler(
            "channel",
            channel
        )
    )

    app.add_handler(
        CommandHandler(
            "activate",
            activate
        )
    )

    app.add_handler(
        CommandHandler(
            "users",
            users
        )
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

    # Βλέπει τα νέα posts του καναλιού
    # και αποθηκεύει το Channel ID

    app.add_handler(

        MessageHandler(

            filters.ChatType.CHANNEL,

            channel_message

        )

    )

    app.job_queue.run_repeating(

        check_expired,

        interval=3600,

        first=60

    )

    print(
        "Bot started successfully."
    )

    app.run_polling()


if __name__ == "__main__":

    main()
