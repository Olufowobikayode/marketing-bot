# bot.py
import os
import logging
import tempfile
import pandas as pd
import re
import requests
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

# Import enhanced modules
from contacts_manager import ContactsManager
from template_manager import TemplateManager
from email_sender import EmailSender
from ai_helper import AIHelper

# ========= CONFIG =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN missing in .env file")

# ========= STATES =========
(UPLOAD_CONTACTS, UPLOAD_TEMPLATE, CHOOSE_GROUP, CHOOSE_TEMPLATE, 
 ENTER_SUBJECT, ENTER_BODY, SEND_CONFIRM, FILTER_CONTACTS, 
 AI_COPYWRITING, BATCH_SELECTION) = range(10)

# ========= MANAGERS =========
contacts_manager = ContactsManager()
template_manager = TemplateManager()
email_sender = EmailSender()
ai_helper = AIHelper()

# ========= LOGGING =========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========= MAIN MENU =========
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

# ========= BUTTON HANDLERS =========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "upload_contacts":
        await upload_contacts_start(query, context)
    elif data == "manage_contacts":
        await manage_contacts(query, context)
    elif data == "filter_contacts":
        await filter_contacts_start(query, context)
    elif data == "create_template":
        await create_template_start(query, context)
    elif data == "ai_copywriting":
        await ai_copywriting_start(query, context)
    elif data == "send_campaign":
        await send_campaign_start(query, context)
    elif data == "statistics":
        await show_statistics(query, context)
    elif data == "back_to_main":
        await main_menu(query, context)
    elif data.startswith("group_"):
        await handle_group_selection(query, context)
    elif data.startswith("template_"):
        await handle_template_selection(query, context)
    elif data.startswith("batch_"):
        await handle_batch_selection(query, context)
    elif data.startswith("ai_generate_"):
        await handle_ai_generation(query, context)

# ========= CONTACTS MANAGEMENT =========
async def upload_contacts_start(query, context):
    await query.edit_message_text(
        "📥 Upload Contacts\n\n"
        "Please send me a CSV or Excel file with contact data.\n"
        "Required columns: email, first_name, last_name\n"
        "Optional columns: phone, company, country, etc.\n\n"
        "I'll validate and enrich the data automatically."
    )
    return UPLOAD_CONTACTS

async def handle_contacts_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("❌ Please send a file (CSV or Excel)")
        return UPLOAD_CONTACTS
    
    file = await update.message.document.get_file()
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.file_path)[1])
    await file.download_to_drive(temp_file.name)
    
    try:
        group_name = f"group_{len(contacts_manager.groups) + 1}"
        result = contacts_manager.import_contacts(temp_file.name, group_name)
        
        # Clean up
        os.unlink(temp_file.name)
        
        message = f"✅ Contacts imported successfully!\n\n📊 Statistics:\n"
        message += f"• Total: {result['total']}\n"
        message += f"• Valid: {result['valid']}\n"
        message += f"• Invalid: {result['invalid']}\n"
        message += f"• Enriched: {result['enriched']}\n"
        message += f"• Group: {group_name}"
        
        if result['invalid_emails']:
            message += f"\n\n❌ Invalid emails:\n" + "\n".join(result['invalid_emails'][:5])
            if len(result['invalid_emails']) > 5:
                message += f"\n... and {len(result['invalid_emails']) - 5} more"
        
        await update.message.reply_text(message)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error importing contacts: {str(e)}")
    
    await main_menu_message(update.message)
    return ConversationHandler.END

async def manage_contacts(query, context):
    groups = contacts_manager.list_groups()
    
    if not groups:
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]]
        await query.edit_message_text(
            "📭 No contact groups found.\n\n"
            "Use 'Upload Contacts' to add your first contact list.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    keyboard = []
    for group in groups:
        stats = contacts_manager.get_group_stats(group)
        keyboard.append([InlineKeyboardButton(
            f"📁 {group} ({stats['total']} contacts, {stats['batches']} batches)", 
            callback_data=f"group_{group}"
        )])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")])
    
    await query.edit_message_text(
        "👥 Contact Groups\n\n"
        "Select a group to view details:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ========= CONTACT FILTERING =========
async def filter_contacts_start(query, context):
    groups = contacts_manager.list_groups()
    
    if not groups:
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]]
        await query.edit_message_text(
            "❌ No contact groups found to filter.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    keyboard = []
    for group in groups:
        keyboard.append([InlineKeyboardButton(
            f"🔍 Filter {group}", 
            callback_data=f"filter_group_{group}"
        )])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")])
    
    await query.edit_message_text(
        "🔍 Filter Contacts\n\n"
        "Select a group to filter and create a new mailing list:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return FILTER_CONTACTS

# ========= TEMPLATE MANAGEMENT =========
async def create_template_start(query, context):
    keyboard = [
        [InlineKeyboardButton("📝 HTML Template", callback_data="upload_html")],
        [InlineKeyboardButton("📄 Text Template", callback_data="create_text")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]
    ]
    
    await query.edit_message_text(
        "📝 Create Template\n\n"
        "Choose template type:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_template_choice(query, context):
    if query.data == "upload_html":
        await query.edit_message_text(
            "📝 Upload HTML Template\n\n"
            "Please send me an HTML file for your email template.\n"
            "You can use variables like:\n"
            "• {{first_name}} - Contact's first name\n"
            "• {{last_name}} - Contact's last name\n"  
            "• {{email}} - Contact's email\n"
            "• {{unsubscribe_link}} - Automatic unsubscribe link\n"
            "• {{company}} - Company name\n"
            "• Any other field from your contacts"
        )
        return UPLOAD_TEMPLATE
    else:
        context.user_data['creating_text_template'] = True
        await query.edit_message_text(
            "📄 Create Text Template\n\n"
            "Please enter your email template text.\n"
            "You can use variables like {{first_name}}, {{last_name}}, {{email}}, etc."
        )
        return UPLOAD_TEMPLATE

async def handle_template_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document and not context.user_data.get('creating_text_template'):
        await update.message.reply_text("❌ Please send an HTML file")
        return UPLOAD_TEMPLATE
    
    try:
        if context.user_data.get('creating_text_template'):
            # Text template from message
            template_content = update.message.text
            template_name = f"text_template_{len(template_manager.templates) + 1}"
            template_type = "text"
        else:
            # HTML template from file
            file = await update.message.document.get_file()
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.html')
            await file.download_to_drive(temp_file.name)
            
            with open(temp_file.name, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            template_name = f"html_template_{len(template_manager.templates) + 1}"
            template_type = "html"
            os.unlink(temp_file.name)
        
        # Add unsubscribe link to template
        if template_type == "html":
            if "{{unsubscribe_link}}" not in template_content:
                template_content += '\n<p><a href="{{unsubscribe_link}}">Unsubscribe</a></p>'
        else:
            if "{{unsubscribe_link}}" not in template_content:
                template_content += '\n\nUnsubscribe: {{unsubscribe_link}}'
        
        template_manager.save_template(template_name, template_content, template_type)
        
        await update.message.reply_text(f"✅ Template '{template_name}' saved successfully!")
        
        # Clear the flag
        context.user_data.pop('creating_text_template', None)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error saving template: {str(e)}")
    
    await main_menu_message(update.message)
    return ConversationHandler.END

# ========= AI COPYWRITING =========
async def ai_copywriting_start(query, context):
    await query.edit_message_text(
        "🤖 AI Copywriting\n\n"
        "Please describe what you want to promote:\n"
        "Examples:\n"
        "• 'Promote our new product launch'\n"  
        "• 'Welcome email for new subscribers'\n"
        "• 'Special discount announcement'"
    )
    return AI_COPYWRITING

async def handle_ai_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    
    try:
        await update.message.reply_text("🔄 AI is generating your copy...")
        
        # Get AI-generated copy
        copy_result = ai_helper.generate_copy(prompt)
        
        # Score the copy
        score = ai_helper.score_email(copy_result['subject'], copy_result['body'])
        
        keyboard = [
            [InlineKeyboardButton("✅ Use This Copy", callback_data="ai_use_copy")],
            [InlineKeyboardButton("🔄 Regenerate", callback_data="ai_regenerate")],
            [InlineKeyboardButton("📝 Save as Template", callback_data="ai_save_template")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]
        ]
        
        context.user_data['ai_copy'] = copy_result
        
        await update.message.reply_text(
            f"🤖 AI-Generated Copy\n\n"
            f"📌 Subject: {copy_result['subject']}\n"
            f"⭐ Score: {score}/10\n\n"
            f"📝 Body:\n{copy_result['body']}\n\n"
            f"Choose an option:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ AI error: {str(e)}")
        await main_menu_message(update.message)
        return ConversationHandler.END
    
    return AI_COPYWRITING

async def handle_ai_actions(query, context):
    ai_copy = context.user_data.get('ai_copy')
    
    if query.data == "ai_use_copy":
        context.user_data['campaign_data'] = {
            'subject': ai_copy['subject'],
            'body': ai_copy['body'],
            'template_type': 'text'
        }
        await send_campaign_start(query, context)
    elif query.data == "ai_save_template":
        template_name = f"ai_template_{len(template_manager.templates) + 1}"
        template_manager.save_template(template_name, ai_copy['body'], 'text')
        await query.edit_message_text(f"✅ Template '{template_name}' saved!")
        await main_menu(query, context)
    else:
        await ai_copywriting_start(query, context)
    
    return ConversationHandler.END

# ========= EMAIL CAMPAIGN =========
async def send_campaign_start(query, context):
    groups = contacts_manager.list_groups()
    templates = template_manager.list_templates()
    
    if not groups:
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]]
        await query.edit_message_text(
            "❌ No contact groups found.\nPlease upload contacts first.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Check if we have pre-filled data from AI
    campaign_data = context.user_data.get('campaign_data', {})
    
    if campaign_data.get('subject') and campaign_data.get('body'):
        # Skip template selection if we have AI copy
        context.user_data['campaign_data'] = campaign_data
        
        # Choose group
        keyboard = []
        for group in groups:
            stats = contacts_manager.get_group_stats(group)
            keyboard.append([InlineKeyboardButton(
                f"👥 {group} ({stats['valid']} valid emails)", 
                callback_data=f"group_{group}"
            )])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")])
        
        await query.edit_message_text(
            "📧 Send Campaign\n\n"
            "Step 1: Choose contact group:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSE_GROUP
    
    # Normal flow - choose template
    keyboard = []
    for template in templates:
        keyboard.append([InlineKeyboardButton(
            f"📝 {template}", 
            callback_data=f"template_{template}"
        )])
    
    keyboard.append([InlineKeyboardButton("📄 Use Text Only", callback_data="template_text")])
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")])
    
    await query.edit_message_text(
        "📧 Send Campaign\n\n"
        "Step 1: Choose template:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSE_TEMPLATE

async def handle_template_selection(query, context):
    template_name = query.data.replace("template_", "")
    
    if template_name == "text":
        context.user_data['campaign_data'] = {'template_type': 'text'}
        await query.edit_message_text("📧 Enter email subject:")
        return ENTER_SUBJECT
    else:
        context.user_data['campaign_data'] = {
            'template': template_name,
            'template_type': 'html'
        }
        
        groups = contacts_manager.list_groups()
        keyboard = []
        for group in groups:
            stats = contacts_manager.get_group_stats(group)
            keyboard.append([InlineKeyboardButton(
                f"👥 {group} ({stats['valid']} valid emails)", 
                callback_data=f"group_{group}"
            )])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="send_campaign")])
        
        await query.edit_message_text(
            f"📧 Send Campaign\n\n"
            f"Template: {template_name}\n"
            f"Step 2: Choose contact group:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSE_GROUP

async def handle_group_selection(query, context):
    group_name = query.data.replace("group_", "")
    context.user_data['campaign_data']['group'] = group_name
    
    campaign_data = context.user_data['campaign_data']
    
    if campaign_data.get('template_type') == 'text' and not campaign_data.get('subject'):
        await query.edit_message_text("📧 Enter email subject:")
        return ENTER_SUBJECT
    else:
        # Show batch selection
        batches = contacts_manager.get_batches(group_name)
        
        if not batches:
            await query.edit_message_text("❌ No valid batches found in this group.")
            await main_menu(query, context)
            return ConversationHandler.END
        
        keyboard = []
        for batch in batches:
            keyboard.append([InlineKeyboardButton(
                f"📦 Batch {batch['number']} ({batch['count']} contacts)", 
                callback_data=f"batch_{batch['number']}"
            )])
        
        keyboard.append([InlineKeyboardButton("🎯 Send to All Batches", callback_data="batch_all")])
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="send_campaign")])
        
        await query.edit_message_text(
            f"📧 Send Campaign\n\n"
            f"Group: {group_name}\n"
            f"Step 3: Choose batch to send:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return BATCH_SELECTION

async def handle_batch_selection(query, context):
    batch_data = query.data.replace("batch_", "")
    context.user_data['campaign_data']['batch'] = batch_data
    
    campaign_data = context.user_data['campaign_data']
    
    if campaign_data.get('template_type') == 'text' and not campaign_data.get('body'):
        await query.edit_message_text("📧 Enter email body:")
        return ENTER_BODY
    else:
        # Confirm send
        group_stats = contacts_manager.get_group_stats(campaign_data['group'])
        batch_info = f"Batch {batch_data}" if batch_data != "all" else "All batches"
        
        keyboard = [
            [InlineKeyboardButton("✅ Send Now", callback_data="confirm_send")],
            [InlineKeyboardButton("🤖 AI Score", callback_data="ai_score")],
            [InlineKeyboardButton("❌ Cancel", callback_data="back_to_main")]
        ]
        
        await query.edit_message_text(
            f"📧 Campaign Summary\n\n"
            f"• Group: {campaign_data['group']}\n"
            f"• {batch_info}\n"
            f"• Recipients: {group_stats['valid']} contacts\n"
            f"• Template: {campaign_data.get('template', 'Text')}\n"
            f"• Subject: {campaign_data.get('subject', 'Not set')}\n\n"
            f"Ready to send?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SEND_CONFIRM

async def handle_subject_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject = update.message.text
    context.user_data['campaign_data']['subject'] = subject
    
    await update.message.reply_text("📧 Enter email body:")
    return ENTER_BODY

async def handle_body_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    body = update.message.text
    context.user_data['campaign_data']['body'] = body
    
    # Add unsubscribe link to text body
    if "{{unsubscribe_link}}" not in body:
        body += '\n\nUnsubscribe: {{unsubscribe_link}}'
        context.user_data['campaign_data']['body'] = body
    
    # Show batch selection
    campaign_data = context.user_data['campaign_data']
    batches = contacts_manager.get_batches(campaign_data['group'])
    
    keyboard = []
    for batch in batches:
        keyboard.append([InlineKeyboardButton(
            f"📦 Batch {batch['number']} ({batch['count']} contacts)", 
            callback_data=f"batch_{batch['number']}"
        )])
    
    keyboard.append([InlineKeyboardButton("🎯 Send to All Batches", callback_data="batch_all")])
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="send_campaign")])
    
    await update.message.reply_text(
        f"📧 Send Campaign\n\n"
        f"Step 3: Choose batch to send:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BATCH_SELECTION

async def handle_send_confirmation(query, context: ContextTypes.DEFAULT_TYPE):
    if query.data == "ai_score":
        # Score the email
        campaign_data = context.user_data['campaign_data']
        subject = campaign_data.get('subject', '')
        body = campaign_data.get('body', '')
        
        if subject or body:
            score = ai_helper.score_email(subject, body)
            await query.edit_message_text(
                f"⭐ AI Email Score: {score}/10\n\n"
                f"Subject: {subject}\n\n"
                f"Continue with sending?"
            )
        return SEND_CONFIRM
    
    elif query.data == "confirm_send":
        campaign_data = context.user_data['campaign_data']
        
        await query.edit_message_text("🔄 Sending emails... This may take a while.")
        
        try:
            # Send campaign
            results = email_sender.send_campaign(campaign_data, contacts_manager)
            
            # Clear campaign data
            context.user_data.pop('campaign_data', None)
            
            await query.edit_message_text(
                f"✅ Campaign sent successfully!\n\n"
                f"📊 Results:\n"
                f"• Total: {results['total']}\n"
                f"• Successful: {results['successful']}\n"
                f"• Failed: {results['failed']}\n"
                f"• Unsubscribe links: {results['unsubscribes']}"
            )
            
        except Exception as e:
            await query.edit_message_text(f"❌ Error sending campaign: {str(e)}")
    
    await main_menu(query, context)
    return ConversationHandler.END

# ========= STATISTICS =========
async def show_statistics(query, context):
    groups = contacts_manager.list_groups()
    templates = template_manager.list_templates()
    
    stats_text = "📊 Statistics\n\n"
    
    stats_text += "👥 Contact Groups:\n"
    for group in groups:
        stats = contacts_manager.get_group_stats(group)
        stats_text += f"• {group}: {stats['total']} total, {stats['valid']} valid, {stats['batches']} batches\n"
    
    stats_text += f"\n📝 Templates: {len(templates)}\n"
    
    # Campaign stats
    campaign_stats = email_sender.get_stats()
    stats_text += f"\n📧 Campaign Stats:\n"
    stats_text += f"• Total Sent: {campaign_stats['total_sent']}\n"
    stats_text += f"• Successful: {campaign_stats['successful']}\n"
    stats_text += f"• Failed: {campaign_stats['failed']}\n"
    stats_text += f"• Unsubscribes: {campaign_stats['unsubscribes']}"
    
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]]
    
    await query.edit_message_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard))

# ========= MENU HELPERS =========
async def main_menu(query, context):
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
    
    await query.edit_message_text(
        "👋 Welcome to Advanced Email Marketing Bot!\n\n"
        "Choose an option below:",
        reply_markup=reply_markup
    )

async def main_menu_message(message):
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
    
    await message.reply_text("Choose an option below:", reply_markup=reply_markup)

# ========= MAIN APPLICATION =========
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Conversation handlers
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
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(campaign_conv)
    application.add_handler(template_conv)
    application.add_handler(contacts_conv)
    application.add_handler(ai_conv)
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("🤖 Advanced Bot started successfully!")
    application.run_polling()

if __name__ == "__main__":
    main()