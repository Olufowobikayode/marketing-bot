import os
import imaplib
import email
from email.header import decode_header
from pymongo import MongoClient
from aiogram import Bot
import time
import traceback

# Env variables
IMAP_HOST = os.getenv("IMAP_HOST", "imap.example.com")
IMAP_USER = os.getenv("IMAP_USER", "contact@example.com")
IMAP_PASS = os.getenv("IMAP_PASS", "yourpassword")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "123456789"))  # Telegram chat to receive replies
POLL_INTERVAL = int(os.getenv("REPLIES_POLL_INTERVAL", 60))  # seconds

# Telegram bot
bot = Bot(token=BOT_TOKEN)

# MongoDB
MONGO_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB_NAME", "PulseMailerBot")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]

def clean_subject(subj):
    decoded, charset = decode_header(subj)[0]
    if isinstance(decoded, bytes):
        return decoded.decode(charset or "utf-8", errors="ignore")
    return decoded

def fetch_replies():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select("inbox")

        status, messages = mail.search(None, '(UNSEEN)')
        mail_ids = messages[0].split()

        for mail_id in mail_ids:
            res, msg_data = mail.fetch(mail_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject = clean_subject(msg["subject"])
                    from_email = email.utils.parseaddr(msg.get("From"))[1]
                    body = ""

                    if msg.is_multipart():
                        for part in msg.walk():
                            ctype = part.get_content_type()
                            cdisp = str(part.get("Content-Disposition"))
                            if ctype == "text/plain" and "attachment" not in cdisp:
                                body = part.get_payload(decode=True).decode(errors="ignore")
                                break
                    else:
                        body = msg.get_payload(decode=True).decode(errors="ignore")

                    # Save to MongoDB
                    db.replies.insert_one({
                        "from": from_email,
                        "subject": subject,
                        "body": body,
                        "read": False,
                        "timestamp": email.utils.parsedate_to_datetime(msg["Date"])
                    })

                    # Notify admin in Telegram
                    bot.loop.create_task(
                        bot.send_message(
                            ADMIN_CHAT_ID,
                            f"📩 New reply from {from_email}\nSubject: {subject}\n\n{body[:500]}"
                        )
                    )

        mail.logout()
    except Exception as e:
        print("Error fetching replies:", traceback.format_exc())

# --- Polling loop ---
def start_polling():
    while True:
        fetch_replies()
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    start_polling()