from aiogram import Router, types
from pymongo import MongoClient
from bson import ObjectId
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import time
import httpx
import asyncio

MONGO_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB_NAME", "PulseMailerBot")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]

router = Router()
DATA_DIR = os.getenv("DATA_DIR", "data")

# ----------------- Helper: Personalize Body -----------------
def personalize_body(body, contact_id, first_name="", last_name=""):
    unsubscribe_link = f"http://yourdomain.com/unsubscribe/{contact_id}"
    return body.replace("{firstname}", first_name)\
               .replace("{lastname}", last_name)\
               .replace("{unsubscribe_link}", unsubscribe_link)

# ----------------- Advanced Filtering -----------------
def build_recipient_query(campaign):
    query = {}
    if "group_id" in campaign and campaign["group_id"]:
        query["groups"] = ObjectId(campaign["group_id"])
    filters = campaign.get("filters", {})
    if "first_name_contains" in filters:
        query["first_name"] = {"$regex": filters["first_name_contains"], "$options":"i"}
    if "last_name_contains" in filters:
        query["last_name"] = {"$regex": filters["last_name_contains"], "$options":"i"}
    if "email_domain" in filters:
        query["email"] = {"$regex": filters["email_domain"] + "$", "$options":"i"}
    if "status" in filters:
        query["status"] = filters["status"]
    return query

# ----------------- Send Campaign -----------------
@router.message()
async def send_campaign(message: types.Message):
    """
    Usage: /send_campaign <campaign_id> <provider_id> <number_of_recipients(optional)>
    """
    try:
        parts = message.text.split(" ")
        if len(parts) < 3:
            await message.answer("Usage: /send_campaign <campaign_id> <provider_id> <number_of_recipients(optional)>")
            return

        campaign_id = parts[1]
        provider_id = parts[2]
        limit = int(parts[3]) if len(parts) > 3 else None

        campaign = db.campaigns.find_one({"_id": ObjectId(campaign_id)})
        provider = db.providers.find_one({"_id": ObjectId(provider_id)})

        if not campaign:
            await message.answer("Campaign not found.")
            return
        if not provider:
            await message.answer("Provider not found.")
            return

        # Fetch recipients with advanced filtering
        recipients = list(db.contacts.find(build_recipient_query(campaign)))
        if limit:
            recipients = recipients[:limit]

        sent_count = 0

        for contact in recipients:
            body = personalize_body(campaign["body"], contact["_id"], contact.get("first_name",""), contact.get("last_name",""))
            subject = campaign["subject"]

            # ----------------- SMTP Provider -----------------
            if provider["type"].upper() == "SMTP":
                msg = MIMEMultipart()
                msg["From"] = provider["config"]["user"]
                msg["To"] = contact["email"]
                msg["Subject"] = subject
                msg.attach(MIMEText(body, "html"))

                # Attach files
                for file_path in campaign.get("attachments", []):
                    try:
                        full_path = os.path.join(DATA_DIR, file_path)
                        with open(full_path, "rb") as f:
                            part = MIMEApplication(f.read(), Name=os.path.basename(full_path))
                            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(full_path)}"'
                            msg.attach(part)
                    except Exception:
                        continue

                # Send via SMTP
                try:
                    with smtplib.SMTP(provider["config"]["host"], int(provider["config"]["port"])) as server:
                        server.starttls()
                        server.login(provider["config"]["user"], provider["config"]["pass"])
                        server.send_message(msg)
                    sent_count += 1
                    await asyncio.sleep(1)  # simple rate limiting
                except Exception as e:
                    await message.answer(f"Failed to send to {contact['email']}: {e}")

            # ----------------- API Provider -----------------
            elif provider["type"].upper() == "API":
                api_config = provider["config"]
                async with httpx.AsyncClient() as client_api:
                    payload = {
                        "to": contact["email"],
                        "subject": subject,
                        "html": body
                    }
                    try:
                        resp = await client_api.post(api_config["endpoint"], json=payload, headers={"Authorization": f"Bearer {api_config['api_key']}"})
                        if resp.status_code == 200:
                            sent_count += 1
                    except Exception as e:
                        await message.answer(f"Failed API send to {contact['email']}: {e}")

        await message.answer(f"Campaign '{campaign['subject']}' sent to {sent_count} recipients.")
        db.campaigns.update_one({"_id": ObjectId(campaign_id)}, {"$set": {"status": "sent"}})

    except Exception as e:
        await message.answer(f"Error sending campaign: {e}")