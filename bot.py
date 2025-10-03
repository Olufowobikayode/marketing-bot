# bot.py
import os
import logging
import tempfile
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# Import your custom modules
from contacts_manager import ContactsManager
from template_manager import TemplateManager
from email_sender import EmailSender
from ai_helper import AIHelper

# ========= CONFIG =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN missing in .env file")

# ========= FLASK APP =========
app = Flask(__name__)

# ========= MANAGERS =========
contacts_manager = ContactsManager()
template_manager = TemplateManager()
email_sender = EmailSender()
ai_helper = AIHelper()

# ========= STATES =========
(UPLOAD_CONTACTS, UPLOAD_TEMPLATE, CHOOSE_GROUP, CHOOSE_TEMPLATE, 
 ENTER_SUBJECT, ENTER_BODY, SEND_CONFIRM, FILTER_CONTACTS, 
 AI_COPYWRITING, BATCH_SELECTION) = range(10)

# ========= LOGGING =========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========= TELEGRAM BOT SETUP =========
def setup_bot_application():
    """Initialize the Telegram bot application"""
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # ========= YOUR EXISTING HANDLER FUNCTIONS =========
    # (Include ALL your handler functions here - start, button_handler, etc.)
    # For example:
    
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("📥 Upload Contacts", callback_data="upload_contacts")],
            [InlineKeyboardButton("👥 Manage Contacts", callback_data="manage_contacts")],
            [InlineKeyboardButton("🔍 Filter Contacts", callback_data="filter_contacts")],
            [InlineKeyboardButton("📝 Create Template", callback_data="create_template")],
            [InlineKeyboardButton("🤖 AI Copywriting", callback_data="ai_copywriting")],
            [InlineKeyboardButton("📧 Send Campaign", callback_data="send_campaign")],
            [InlineKeyboardButton("📊 Statistics", callback_data="statistics")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "👋 Welcome to Advanced Email Marketing Bot!\n\n"
            "Choose an option below:",
            reply_markup=reply_markup
        )

    async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        
        if data == "upload_contacts":
            await upload_contacts_start(query, context)
        elif data == "manage_contacts":
            await manage_contacts(query, context)
        # ... include all your other button handlers

    # ========= CONVERSATION HANDLERS =========
    campaign_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(send_campaign_start, pattern="^send_campaign$")],
        states={
            CHOOSE_TEMPLATE: [CallbackQueryHandler(handle_template_selection, pattern="^template_")],
            CHOOSE_GROUP: [CallbackQueryHandler(handle_group_selection, pattern="^group_")],
            ENTER_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_subject_input)],
            ENTER_BODY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_body_input)],
            BATCH_SELECTION: [CallbackQueryHandler(handle_batch_selection, pattern="^batch_")],
            SEND_CONFIRM: [CallbackQueryHandler(handle_send_confirmation, pattern="^(confirm_send|ai_score|back_to_main)$")]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    template_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_template_start, pattern="^create_template$")],
        states={
            UPLOAD_TEMPLATE: [
                CallbackQueryHandler(handle_template_choice, pattern="^(upload_html|create_text)$"),
                MessageHandler(filters.TEXT | filters.Document.ALL, handle_template_file)
            ]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    contacts_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(upload_contacts_start, pattern="^upload_contacts$")],
        states={
            UPLOAD_CONTACTS: [MessageHandler(filters.Document.ALL, handle_contacts_file)]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    ai_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ai_copywriting_start, pattern="^ai_copywriting$")],
        states={
            AI_COPYWRITING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_prompt),
                CallbackQueryHandler(handle_ai_actions, pattern="^ai_(use_copy|regenerate|save_template)$")
            ]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    # Add all handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(campaign_conv)
    application.add_handler(template_conv)
    application.add_handler(contacts_conv)
    application.add_handler(ai_conv)
    application.add_handler(CallbackQueryHandler(button_handler))
    
    return application

# Initialize bot application
bot_application = setup_bot_application()

# ========= WEBHOOK ROUTES =========
@app.route('/')
def health_check():
    """Health check endpoint for deployment services"""
    return "🤖 PulseMailerBot is running!", 200

@app.route('/webhook', methods=['POST'])
async def webhook():
    """Telegram webhook endpoint"""
    try:
        data = request.get_json()
        update = Update.de_json(data, bot_application.bot)
        await bot_application.process_update(update)
        return 'OK', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'Error', 500

@app.route('/set_webhook', methods=['GET'])
async def set_webhook():
    """Manually set webhook URL (call this once after deployment)"""
    webhook_url = os.getenv('WEBHOOK_URL')
    if not webhook_url:
        return "❌ WEBHOOK_URL not set in environment variables", 400
    
    try:
        await bot_application.bot.set_webhook(webhook_url)
        return f"✅ Webhook set to: {webhook_url}", 200
    except Exception as e:
        return f"❌ Failed to set webhook: {e}", 500

# ========= POLLING MODE (Development) =========
async def run_polling():
    """Run the bot in polling mode (for development)"""
    logger.info("🤖 Starting bot in polling mode...")
    await bot_application.run_polling()

# ========= DUAL MODE EXECUTION =========
def main():
    """Run in appropriate mode based on environment"""
    port = int(os.environ.get('PORT', 5000))
    
    if port == 5000:
        # Development mode - use polling
        asyncio.run(run_polling())
    else:
        # Production mode - start Flask app
        app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == "__main__":
    main()