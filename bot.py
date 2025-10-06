import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
import json
from bson import ObjectId
from db import get_collection  # centralized DB connection

# -------------------- CONFIG --------------------
BOT_TOKEN = "8301662693:AAG22_FCPQzbliZKs75OvOS-bJTnhSJ499s"

# -------------------- LOGGING --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- DATABASE --------------------
campaigns_col = get_collection("campaigns")
contacts_col = get_collection("contacts")
providers_col = get_collection("providers")
templates_col = get_collection("templates")

# -------------------- STATES --------------------
CREATE_CAMPAIGN, ADD_CONTACT, UPLOAD_CONTACTS, ADD_PROVIDER, UPLOAD_TEMPLATE, SEND_CAMPAIGN = range(6)

# -------------------- /start --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Welcome to Pulse Mailer Bot!\n\n"
        "Available commands:\n"
        "/start - Show this message\n"
        "/create_campaign - Create a new campaign\n"
        "/list_campaigns - List all campaigns\n"
        "/delete_campaign <id> - Delete a campaign\n"
        "/generate_campaign_ai - AI-generated campaign\n"
        "/list_contacts - List all contacts\n"
        "/add_contact - Add a new contact\n"
        "/import_contacts - Import contacts via JSON\n"
        "/list_providers - Show providers\n"
        "/add_provider - Add a provider\n"
        "/send_campaign - Send a campaign\n"
        "/templates - Show templates\n"
        "/upload_template - Upload a new template\n"
    )
    await update.message.reply_text(text)

# -------------------- CAMPAIGN HANDLERS --------------------
async def create_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send campaign JSON:\n"
        '{"subject":"Your subject","body":"Email body with {firstname} and {unsubscribe_link}","group_id":"optional_group_id","attachments":[],"images":[]}'
    )
    return CREATE_CAMPAIGN

async def save_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.message.text)
        required_keys = ["subject", "body"]
        if not all(k in data for k in required_keys):
            await update.message.reply_text("❌ Invalid JSON. Must include 'subject' and 'body'.")
            return CREATE_CAMPAIGN
        data["status"] = "draft"
        campaigns_col.insert_one(data)
        await update.message.reply_text(f"✅ Campaign '{data['subject']}' saved as draft.")
    except json.JSONDecodeError:
        await update.message.reply_text("❌ Invalid JSON format. Send valid JSON.")
        return CREATE_CAMPAIGN
    return ConversationHandler.END

async def list_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    campaigns = list(campaigns_col.find({}))
    if not campaigns:
        await update.message.reply_text("No campaigns found.")
        return
    text = "Campaigns:\n"
    for c in campaigns:
        text += f"{c['_id']} | {c['subject']} | {c['status']}\n"
    await update.message.reply_text(text)

async def delete_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split(" ", 1)
        if len(parts) != 2:
            await update.message.reply_text("Usage: /delete_campaign <campaign_id>")
            return
        campaign_id = parts[1]
        result = campaigns_col.delete_one({"_id": ObjectId(campaign_id)})
        if result.deleted_count:
            await update.message.reply_text("Campaign deleted successfully.")
        else:
            await update.message.reply_text("Campaign not found.")
    except Exception as e:
        await update.message.reply_text(f"Error deleting campaign: {e}")

async def generate_campaign_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        import openai
        openai.api_key = os.getenv("GEMINI_API_KEY")
        prompt = "Generate a marketing email subject and body for my campaign. Respond JSON with 'subject' and 'body'."
        response = openai.Completion.create(
            model="gpt-4",
            prompt=prompt,
            max_tokens=300
        )
        text = response.choices[0].text.strip()
        await update.message.reply_text(
            f"AI Generated Campaign:\n{text}\nSend this JSON to /create_campaign to save."
        )
    except Exception as e:
        await update.message.reply_text(f"AI generation failed: {e}")

# -------------------- CONTACTS HANDLERS --------------------
async def list_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contacts = list(contacts_col.find({}))
    if not contacts:
        await update.message.reply_text("No contacts found.")
        return
    text = "Contacts:\n"
    for c in contacts:
        text += f"{c['_id']} | {c.get('name')} | {c.get('email')}\n"
    await update.message.reply_text(text)

async def add_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Send contact JSON: {"name": "John Doe", "email": "email@example.com"}')
    return ADD_CONTACT

async def save_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.message.text)
        required_keys = ["name", "email"]
        if not all(k in data for k in required_keys):
            await update.message.reply_text("❌ Invalid JSON. Must include 'name' and 'email'.")
            return ADD_CONTACT
        contacts_col.insert_one(data)
        await update.message.reply_text(f"✅ Contact '{data['name']}' added.")
    except json.JSONDecodeError:
        await update.message.reply_text("❌ Invalid JSON format. Send valid JSON.")
        return ADD_CONTACT
    return ConversationHandler.END

# -------------------- PROVIDERS HANDLERS --------------------
async def list_providers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    providers = list(providers_col.find({}))
    if not providers:
        await update.message.reply_text("No providers found.")
        return
    text = "Providers:\n"
    for p in providers:
        text += f"{p['_id']} | {p.get('name')} | {p.get('api_key')}\n"
    await update.message.reply_text(text)

async def add_provider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Send provider JSON: {"name": "Provider Name", "api_key": "XXXX"}')
    return ADD_PROVIDER

async def save_provider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.message.text)
        required_keys = ["name", "api_key"]
        if not all(k in data for k in required_keys):
            await update.message.reply_text("❌ Invalid JSON. Must include 'name' and 'api_key'.")
            return ADD_PROVIDER
        providers_col.insert_one(data)
        await update.message.reply_text(f"✅ Provider '{data['name']}' added.")
    except json.JSONDecodeError:
        await update.message.reply_text("❌ Invalid JSON format. Send valid JSON.")
        return ADD_PROVIDER
    return ConversationHandler.END

# -------------------- TEMPLATES HANDLERS --------------------
async def list_templates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    templates = list(templates_col.find({}))
    if not templates:
        await update.message.reply_text("No templates found.")
        return
    text = "Templates:\n"
    for t in templates:
        text += f"{t['_id']} | {t.get('name')}\n"
    await update.message.reply_text(text)

async def upload_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Send template JSON: {"name": "Template Name", "body": "Template body"}')
    return UPLOAD_TEMPLATE

async def save_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.message.text)
        required_keys = ["name", "body"]
        if not all(k in data for k in required_keys):
            await update.message.reply_text("❌ Invalid JSON. Must include 'name' and 'body'.")
            return UPLOAD_TEMPLATE
        templates_col.insert_one(data)
        await update.message.reply_text(f"✅ Template '{data['name']}' uploaded.")
    except json.JSONDecodeError:
        await update.message.reply_text("❌ Invalid JSON format. Send valid JSON.")
        return UPLOAD_TEMPLATE
    return ConversationHandler.END

# -------------------- SEND CAMPAIGN HANDLER --------------------
async def send_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sending campaign feature not implemented yet.")
    # Placeholder for sending campaign logic
    return ConversationHandler.END

# -------------------- MAIN --------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list_campaigns", list_campaigns))
    app.add_handler(CommandHandler("delete_campaign", delete_campaign))
    app.add_handler(CommandHandler("generate_campaign_ai", generate_campaign_ai))
    app.add_handler(CommandHandler("list_contacts", list_contacts))
    app.add_handler(CommandHandler("list_providers", list_providers))
    app.add_handler(CommandHandler("templates", list_templates))
    app.add_handler(CommandHandler("send_campaign", send_campaign))

    # Campaign Conversation
    campaign_conv = ConversationHandler(
        entry_points=[CommandHandler("create_campaign", create_campaign)],
        states={CREATE_CAMPAIGN: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_campaign)]},
        fallbacks=[]
    )
    app.add_handler(campaign_conv)

    # Contact Conversation
    contact_conv = ConversationHandler(
        entry_points=[CommandHandler("add_contact", add_contact)],
        states={ADD_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_contact)]},
        fallbacks=[]
    )
    app.add_handler(contact_conv)

    # Provider Conversation
    provider_conv = ConversationHandler(
        entry_points=[CommandHandler("add_provider", add_provider)],
        states={ADD_PROVIDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_provider)]},
        fallbacks=[]
    )
    app.add_handler(provider_conv)

    # Template Conversation
    template_conv = ConversationHandler(
        entry_points=[CommandHandler("upload_template", upload_template)],
        states={UPLOAD_TEMPLATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_template)]},
        fallbacks=[]
    )
    app.add_handler(template_conv)

    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()