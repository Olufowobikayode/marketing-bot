# main.py
import os
import logging
import tempfile
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Import local modules with explicit imports to avoid conflicts
# Import local modules with explicit imports to avoid conflicts
import templates
import contacts
import campaigns
import providers
from mailer import get_default_mailer, refresh_mailer_providers

# ========= LOAD CONFIG =========
try:
    from config import BOT_TOKEN
except ImportError:
    from dotenv import load_dotenv
    load_dotenv()
    BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN missing in .env file")

# ========= LOGGING =========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [main.py] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("main")

# ========= DATABASE HEALTH CHECK =========
def check_database_health():
    """Check health of all database modules on startup."""
    logger.info("🔍 Checking database health...")
    
    modules_health = {
        "contacts": contacts.health_check(),
        "templates": templates.health_check(),
        "campaigns": campaigns.health_check(),
        "providers": providers.health_check()
    }
    
    all_healthy = True
    for module_name, health in modules_health.items():
        status = health.get('status', 'unknown')
        if status != 'healthy':
            all_healthy = False
            logger.warning("❌ %s module: %s", module_name, health.get('error', 'Unknown issue'))
        else:
            logger.info("✅ %s module: healthy", module_name)
    
    return all_healthy

# ========= BOT COMMANDS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message with available commands."""
    await update.message.reply_text(
        "👋 Welcome to the Marketing Bot!\n\n"
        "📧 **Template Commands:**\n"
        "/newtemplate <title> | <brief> → AI-generate a new email template\n"
        "/uploadtemplate <name> → Upload MJML/HTML file\n"
        "/preview <name> → Show preview of template\n"
        "/copy <prompt> → Generate AI subject/body copy\n\n"
        
        "👥 **Contact Management:**\n"
        "/contacts → Show contact statistics\n"
        "/uploadcontacts <group> → Upload contacts CSV/Excel\n\n"
        
        "📧 **Email Provider Management:**\n"
        "/listproviders → Show all email providers\n"
        "/addprovider_start → Start adding a new provider\n"
        "/addprovider <type> <name> → Add specific provider\n"
        "/removeprovider <name> → Remove a provider\n"
        "/enableprovider <name> → Enable a provider\n"
        "/disableprovider <name> → Disable a provider\n"
        "/providerstats <name> → Show provider statistics\n"
        "/testprovider <name> [email] → Test a provider\n\n"
        
        "📢 **Campaign Management:**\n"
        "/campaigns → List campaigns\n"
        "/newcampaign <name> | <template> | <contacts> → Create campaign\n\n"
        
        "💡 **Tip**: Use /help for command details"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed help for commands."""
    await update.message.reply_text(
        "📖 **Detailed Help**\n\n"
        
        "🎨 **Template Examples:**\n"
        "• `/newtemplate Welcome Email | A friendly welcome email for new subscribers`\n"
        "• `/uploadtemplate newsletter` then send MJML/HTML file\n"
        "• `/preview welcome_email`\n"
        "• `/copy Promote our new product launch`\n\n"
        
        "📧 **Provider Examples:**\n"
        "• `/listproviders` - View all configured providers\n"
        "• `/addprovider Brevo my_brevo` - Add Brevo provider\n"
        "• `/testprovider my_brevo test@example.com` - Test provider\n"
        "• `/disableprovider my_brevo` - Temporarily disable\n\n"
        
        "👥 **Contact Examples:**\n"
        "• `/uploadcontacts subscribers` then send CSV file\n"
        "• `/contacts` - View contact statistics\n\n"
        
        "🚀 **Campaign Examples:**\n"
        "• `/newcampaign Welcome | welcome_template | subscribers`\n"
        "• `/campaigns` - List all campaigns"
    )

# ========= TEMPLATE COMMANDS =========
async def new_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a new template using AI."""
    try:
        if not context.args:
            await update.message.reply_text("⚠️ Usage: /newtemplate <title> | <brief>")
            return
            
        args = " ".join(context.args)
        if "|" not in args:
            await update.message.reply_text("⚠️ Usage: /newtemplate <title> | <brief>")
            return
            
        title, brief = [a.strip() for a in args.split("|", 1)]
        
        if not title or not brief:
            await update.message.reply_text("⚠️ Title and brief cannot be empty")
            return
            
        # Use the AI template generation
        template_key = ai_generate_template(title, brief)
        
        if not template_key:
            await update.message.reply_text("❌ Failed to generate template. Check AI configuration.")
            return
            
        await update.message.reply_text(
            f"✅ Template '{title}' generated and saved!\n"
            f"Key: {template_key}\n"
            f"Use /preview {template_key} to see it"
        )
        
    except Exception as e:
        logger.error(f"new_template error: {e}")
        await update.message.reply_text("⚠️ Error generating template. Check logs.")

async def upload_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file upload for MJML/HTML templates."""
    if not context.args:
        await update.message.reply_text("⚠️ Usage: /uploadtemplate <name>")
        return

    name = " ".join(context.args)
    await update.message.reply_text(
        f"📩 Now send the MJML/HTML file for template '{name}'\n\n"
        f"Supported formats: .mjml, .html, .txt"
    )

    context.user_data["awaiting_upload"] = {"name": name, "type": "template"}

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive uploaded files and process based on context."""
    if "awaiting_upload" not in context.user_data:
        # Check if this might be a contacts file upload
        if "awaiting_contacts_upload" in context.user_data:
            await handle_contacts_file(update, context)
        else:
            await update.message.reply_text("❌ No file upload expected. Use /uploadtemplate or /uploadcontacts first.")
        return

    upload_meta = context.user_data["awaiting_upload"]
    
    try:
        file = await update.message.document.get_file()
        file_bytes = await file.download_as_bytearray()
        content = file_bytes.decode("utf-8", errors="ignore")
        
        if upload_meta["type"] == "template":
            name = upload_meta["name"]
            is_html = file.file_path.endswith(".html") if file.file_path else False
            
            # Save the template
            filename = save_new_template(name, content, is_html=is_html)
            context.user_data.pop("awaiting_upload")
            
            await update.message.reply_text(
                f"✅ Template '{name}' uploaded and saved!\n"
                f"File: {filename}\n"
                f"Use /preview {name} to see it"
            )
            
    except Exception as e:
        logger.error(f"File handling error: {e}")
        await update.message.reply_text("❌ Error processing file. Check format and try again.")
        context.user_data.pop("awaiting_upload", None)

async def preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview a template by generating HTML file."""
    if not context.args:
        await update.message.reply_text("⚠️ Usage: /preview <template_name_or_key>")
        return
        
    name = " ".join(context.args)
    
    try:
        # Generate preview file
        preview_path = preview_template_to_file(name)
        
        if not preview_path or not os.path.exists(preview_path):
            await update.message.reply_text("❌ Template not found or preview generation failed")
            return
            
        # Send as document (Telegram has limits on file size)
        file_size = os.path.getsize(preview_path)
        
        if file_size > 50 * 1024 * 1024:  # 50MB limit
            # Get HTML snippet instead
            html_content = get_template_html(name)
            if html_content:
                snippet = html_content[:1000] + "..." if len(html_content) > 1000 else html_content
                await update.message.reply_text(f"📄 Preview snippet:\n\n```html\n{snippet}\n```", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Template found but HTML content is empty")
        else:
            with open(preview_path, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    filename=f"preview_{name}.html",
                    caption=f"Preview of template: {name}"
                )
            
        # Clean up temporary file
        try:
            os.remove(preview_path)
        except Exception:
            pass
            
    except Exception as e:
        logger.error(f"Preview error: {e}")
        await update.message.reply_text("❌ Error generating preview")

async def ai_copy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate marketing copy using AI."""
    try:
        if not context.args:
            await update.message.reply_text("⚠️ Usage: /copy <prompt>")
            return
            
        prompt = " ".join(context.args)
        copy_result = templates_ai_copywrite(prompt)
        
        if not copy_result:
            await update.message.reply_text("❌ Failed to generate copy")
            return
            
        await update.message.reply_text(
            f"✉️ AI-Generated Copy:\n\n"
            f"📌 **Subject**: {copy_result.get('subject', 'N/A')}\n\n"
            f"📝 **Body**:\n{copy_result.get('body', 'N/A')}"
        )
        
    except Exception as e:
        logger.error(f"ai_copy error: {e}")
        await update.message.reply_text("⚠️ Error generating copy")

# ========= CONTACTS & CAMPAIGNS =========
async def show_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show contact statistics."""
    try:
        groups = contacts.list_groups()
        if not groups:
            await update.message.reply_text("📭 No contact groups found")
            return
            
        stats_text = "👥 **Contact Groups**:\n\n"
        total_contacts = 0
        
        for group in groups:
            stats = contacts.group_stats(group)
            total_contacts += stats["total"]
            stats_text += f"📁 **{group}**: {stats['total']} contacts ({stats['valid']} valid, {stats['invalid']} invalid)\n"
            
        stats_text += f"\n📊 **Total**: {total_contacts} contacts across {len(groups)} groups"
        
        await update.message.reply_text(stats_text)
        
    except Exception as e:
        logger.error(f"show_contacts error: {e}")
        await update.message.reply_text("❌ Error retrieving contacts")

async def upload_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start contacts file upload process."""
    if not context.args:
        await update.message.reply_text("⚠️ Usage: /uploadcontacts <group_name>")
        return
        
    group_name = " ".join(context.args)
    
    # Validate group name
    if not contacts.validate_group_name(group_name):
        await update.message.reply_text(
            "❌ Invalid group name. Use only letters, numbers, spaces, hyphens, and underscores."
        )
        return
        
    context.user_data["awaiting_contacts_upload"] = {"group_name": group_name}
    
    await update.message.reply_text(
        f"📩 Now send the CSV or Excel file for contacts group '{group_name}'\n\n"
        f"File should contain columns with email addresses and optional names.\n"
        f"Supported formats: .csv, .xls, .xlsx"
    )

async def handle_contacts_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle contacts file upload."""
    if "awaiting_contacts_upload" not in context.user_data:
        await update.message.reply_text("❌ No contacts upload expected. Use /uploadcontacts first.")
        return
        
    upload_meta = context.user_data["awaiting_contacts_upload"]
    group_name = upload_meta["group_name"]
    
    try:
        # Download the file
        file = await update.message.document.get_file()
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.file_path)[1])
        await file.download_to_drive(temp_file.name)
        
        # Process the contacts file
        saved, invalid, errors = contacts.save_contacts_from_file(temp_file.name, group_name)
        
        # Clean up
        os.unlink(temp_file.name)
        context.user_data.pop("awaiting_contacts_upload", None)
        
        # Send results
        message = f"✅ Contacts imported to '{group_name}':\n\n"
        message += f"📥 Saved: {saved} contacts\n"
        message += f"❌ Invalid: {invalid} contacts\n"
        
        if errors:
            message += f"\n⚠️ Errors (first 10):\n" + "\n".join(errors[:10])
            
        await update.message.reply_text(message)
        
    except Exception as e:
        logger.error(f"Contacts file handling error: {e}")
        await update.message.reply_text(f"❌ Error processing contacts file: {str(e)}")
        context.user_data.pop("awaiting_contacts_upload", None)

async def show_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all campaigns."""
    try:
        campaign_list = campaigns.list_campaigns()
        if not campaign_list:
            await update.message.reply_text("📭 No campaigns found")
            return
            
        stats = campaigns.get_campaign_stats()
        
        msg = "📢 **Campaigns**:\n\n"
        for campaign_name in campaign_list:
            campaign = campaigns.get_campaign(campaign_name)
            if campaign:
                status_icon = "🟢" if campaign.get('status') == 'sent' else "🟡" if campaign.get('status') == 'sending' else "⚪"
                msg += f"{status_icon} **{campaign_name}** - {campaign.get('status', 'draft')} ({campaign.get('sent_count', 0)} sent)\n"
        
        msg += f"\n📊 **Stats**: {stats['total_campaigns']} total, {stats['total_emails_sent']} emails sent"
        
        await update.message.reply_text(msg)
        
    except Exception as e:
        logger.error(f"show_campaigns error: {e}")
        await update.message.reply_text("❌ Error retrieving campaigns")

async def new_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a new campaign."""
    try:
        if not context.args:
            await update.message.reply_text("⚠️ Usage: /newcampaign <name> | <template_key> | <contacts_group>")
            return
            
        args = " ".join(context.args)
        if "|" not in args:
            await update.message.reply_text("⚠️ Usage: /newcampaign <name> | <template_key> | <contacts_group>")
            return
            
        parts = [part.strip() for part in args.split("|", 2)]
        if len(parts) != 3:
            await update.message.reply_text("⚠️ Need exactly 3 parts: name | template_key | contacts_group")
            return
            
        name, template_key, contacts_group = parts
        
        # Validate template exists
        if not get_template_meta(template_key):
            await update.message.reply_text(f"❌ Template '{template_key}' not found")
            return
            
        # Validate contacts group exists
        if contacts_group not in contacts.list_groups():
            await update.message.reply_text(f"❌ Contacts group '{contacts_group}' not found")
            return
            
        # Create campaign
        success = campaigns.create_campaign(name, template_key, contacts_group)
        
        if success:
            await update.message.reply_text(
                f"✅ Campaign '{name}' created!\n"
                f"Template: {template_key}\n"
                f"Contacts: {contacts_group}\n"
                f"Status: Draft"
            )
        else:
            await update.message.reply_text("❌ Failed to create campaign (might already exist)")
            
    except Exception as e:
        logger.error(f"new_campaign error: {e}")
        await update.message.reply_text("⚠️ Error creating campaign")

# ========= PROVIDER MANAGEMENT COMMANDS =========
async def list_providers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all configured email providers."""
    try:
        provider_list = providers.list_providers()
        
        if not provider_list:
            await update.message.reply_text("📭 No email providers configured")
            return
        
        message = "📧 **Configured Email Providers**:\n\n"
        
        for provider in provider_list:
            status = "🟢" if provider["enabled"] else "🔴"
            success_rate = provider["success_rate"]
            usage = f"{provider['used_today']}/{provider['daily_limit']}"
            
            message += (
                f"{status} **{provider['name']}** ({provider['provider_type']})\n"
                f"   Priority: {provider['priority']} | Today: {usage}\n"
                f"   Success: {success_rate:.1f}% | Total: {provider['success_count']} sent\n"
                f"   Status: {'Enabled' if provider['enabled'] else 'Disabled'}\n\n"
            )
        
        await update.message.reply_text(message)
        
    except Exception as e:
        logger.error("list_providers error: %s", e)
        await update.message.reply_text("❌ Error listing providers")

async def add_provider_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the provider addition process."""
    supported = providers.get_supported_providers()
    message = (
        "🔧 **Add Email Provider**\n\n"
        "Supported provider types:\n" +
        "\n".join(f"• {p}" for p in supported) +
        "\n\nUse: /addprovider <type> <name>\n"
        "Example: `/addprovider Brevo my_brevo`\n\n"
        "After this, I'll guide you through entering the required credentials step by step."
    )
    
    await update.message.reply_text(message)

async def add_provider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new provider with step-by-step configuration."""
    try:
        if len(context.args) < 2:
            await update.message.reply_text(
                "⚠️ Usage: /addprovider <type> <name>\n"
                "Example: `/addprovider Brevo my_brevo`"
            )
            return
        
        provider_type = context.args[0]
        provider_name = context.args[1]
        
        # Check if provider type is supported
        template = providers.get_provider_template(provider_type)
        if not template:
            await update.message.reply_text(
                f"❌ Unsupported provider type: {provider_type}\n"
                f"Use /addprovider_start to see supported types."
            )
            return
        
        # Check if provider name already exists
        existing = providers.get_provider(provider_name)
        if existing:
            await update.message.reply_text(
                f"❌ Provider '{provider_name}' already exists"
            )
            return
        
        # Store provider configuration in user data
        context.user_data["adding_provider"] = {
            "name": provider_name,
            "type": provider_type,
            "template": template,
            "credentials": {},
            "current_field": 0
        }
        
        # Ask for first credential
        fields = template["credentials"]
        await update.message.reply_text(
            f"🔐 **Configuring {provider_name} ({provider_type})**\n\n"
            f"Please enter: **{fields[0]}**\n"
            f"Instructions: {template['instructions']}"
        )
        
    except Exception as e:
        logger.error("add_provider error: %s", e)
        await update.message.reply_text("❌ Error starting provider setup")

async def handle_provider_credentials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle provider credential input step by step."""
    if "adding_provider" not in context.user_data:
        return
    
    provider_data = context.user_data["adding_provider"]
    fields = provider_data["template"]["credentials"]
    current_field = provider_data["current_field"]
    
    # Store the credential
    field_name = fields[current_field]
    provider_data["credentials"][field_name] = update.message.text
    
    # Move to next field or complete setup
    if current_field + 1 < len(fields):
        provider_data["current_field"] += 1
        next_field = fields[current_field + 1]
        
        await update.message.reply_text(
            f"✅ {field_name} saved!\n\n"
            f"Now enter: **{next_field}**"
        )
    else:
        # All credentials collected, save provider
        success = providers.add_provider(
            name=provider_data["name"],
            provider_type=provider_data["type"],
            credentials=provider_data["credentials"],
            priority=50  # Default priority
        )
        
        if success:
            # Refresh mailer to include new provider
            refresh_mailer_providers()
            
            await update.message.reply_text(
                f"✅ **Provider '{provider_data['name']}' added successfully!**\n\n"
                f"Type: {provider_data['type']}\n"
                f"Status: Enabled\n"
                f"Use /testprovider {provider_data['name']} to test it.\n"
                f"Use /listproviders to see all providers."
            )
        else:
            await update.message.reply_text(
                "❌ Failed to add provider. Please try again."
            )
        
        # Clean up user data
        context.user_data.pop("adding_provider", None)

async def remove_provider_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a provider."""
    try:
        if not context.args:
            await update.message.reply_text(
                "⚠️ Usage: /removeprovider <name>\n"
                "Use /listproviders to see available providers."
            )
            return
        
        provider_name = " ".join(context.args)
        success = providers.remove_provider(provider_name)
        
        if success:
            refresh_mailer_providers()
            await update.message.reply_text(f"✅ Provider '{provider_name}' removed")
        else:
            await update.message.reply_text(f"❌ Provider '{provider_name}' not found")
            
    except Exception as e:
        logger.error("remove_provider error: %s", e)
        await update.message.reply_text("❌ Error removing provider")

async def enable_provider_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable a provider."""
    try:
        if not context.args:
            await update.message.reply_text(
                "⚠️ Usage: /enableprovider <name>"
            )
            return
        
        provider_name = " ".join(context.args)
        success = providers.enable_provider(provider_name)
        
        if success:
            refresh_mailer_providers()
            await update.message.reply_text(f"✅ Provider '{provider_name}' enabled")
        else:
            await update.message.reply_text(f"❌ Provider '{provider_name}' not found")
            
    except Exception as e:
        logger.error("enable_provider error: %s", e)
        await update.message.reply_text("❌ Error enabling provider")

async def disable_provider_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable a provider."""
    try:
        if not context.args:
            await update.message.reply_text(
                "⚠️ Usage: /disableprovider <name>"
            )
            return
        
        provider_name = " ".join(context.args)
        success = providers.disable_provider(provider_name)
        
        if success:
            refresh_mailer_providers()
            await update.message.reply_text(f"✅ Provider '{provider_name}' disabled")
        else:
            await update.message.reply_text(f"❌ Provider '{provider_name}' not found")
            
    except Exception as e:
        logger.error("disable_provider error: %s", e)
        await update.message.reply_text("❌ Error disabling provider")

async def provider_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed statistics for a provider."""
    try:
        if not context.args:
            await update.message.reply_text(
                "⚠️ Usage: /providerstats <name>"
            )
            return
        
        provider_name = " ".join(context.args)
        stats = providers.get_provider_stats(provider_name)
        
        if "error" in stats:
            await update.message.reply_text(f"❌ {stats['error']}")
            return
        
        message = (
            f"📊 **Statistics for {stats['name']}**\n\n"
            f"Type: {stats['type']}\n"
            f"Status: {'🟢 Enabled' if stats['enabled'] else '🔴 Disabled'}\n"
            f"Priority: {stats['priority']}\n"
            f"Daily Usage: {stats['daily_usage']}\n"
            f"Success Rate: {stats['success_rate']}\n"
            f"Total Sent: {stats['total_sent']}\n"
            f"Total Failed: {stats['total_failed']}\n"
            f"Last Used: {stats['last_used'] or 'Never'}\n"
        )
        
        # Add recent history if available
        if stats['history']:
            message += "\n**Recent Activity:**\n"
            for day in stats['history'][:7]:  # Last 7 days
                message += f"• {day['date']}: {day['sent']} sent, {day['failed']} failed\n"
        
        await update.message.reply_text(message)
        
    except Exception as e:
        logger.error("provider_stats error: %s", e)
        await update.message.reply_text("❌ Error getting provider statistics")

async def test_provider_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test a provider by sending a test email."""
    try:
        if not context.args:
            await update.message.reply_text(
                "⚠️ Usage: /testprovider <name> [test_email]\n"
                "Example: `/testprovider my_brevo test@example.com`"
            )
            return
        
        provider_name = context.args[0]
        test_email = context.args[1] if len(context.args) > 1 else os.getenv("TEST_EMAIL")
        
        if not test_email:
            await update.message.reply_text(
                "❌ No test email provided. Use: /testprovider <name> <email>"
            )
            return
        
        # Get the provider to check if it exists
        provider = providers.get_provider(provider_name)
        if not provider:
            await update.message.reply_text(f"❌ Provider '{provider_name}' not found")
            return
            
        if not provider["enabled"]:
            await update.message.reply_text(
                f"❌ Provider '{provider_name}' is disabled. Use /enableprovider {provider_name} first."
            )
            return
        
        # Get the mailer and send test email
        mailer = get_default_mailer()
        
        await update.message.reply_text(
            f"🧪 Testing provider '{provider_name}' with email: {test_email}"
        )
        
        result = await mailer.send_single(
            to_email=test_email,
            subject="✅ Provider Test - Email Marketing Bot",
            html="""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                    .header { background: #4F46E5; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }
                    .content { background: #f9f9f9; padding: 20px; border-radius: 0 0 10px 10px; }
                    .success { color: #10B981; font-weight: bold; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>✅ Test Successful!</h1>
                    </div>
                    <div class="content">
                        <p>Hello!</p>
                        <p>This is a test email from your <strong>Email Marketing Bot</strong>.</p>
                        <p class="success">✓ Provider <strong>{provider_name}</strong> is working correctly!</p>
                        <p>You can now use this provider to send marketing campaigns.</p>
                        <hr>
                        <p><small>Sent via Email Marketing Bot Telegram Integration</small></p>
                    </div>
                </div>
            </body>
            </html>
            """.replace("{provider_name}", provider_name),
            preferred_provider=provider_name
        )
        
        if result.success:
            await update.message.reply_text(
                f"✅ **Test Successful!**\n\n"
                f"Provider: {result.provider}\n"
                f"Response: {result.info}\n"
                f"Time: {result.response_time:.2f}s\n\n"
                f"The test email was sent successfully to {test_email}"
            )
        else:
            await update.message.reply_text(
                f"❌ **Test Failed**\n\n"
                f"Provider: {provider_name}\n"
                f"Error: {result.info}\n\n"
                f"Check your credentials and try again."
            )
            
    except Exception as e:
        logger.error("test_provider error: %s", e)
        await update.message.reply_text(f"❌ Error testing provider: {str(e)}")

# ========= SYSTEM COMMANDS =========
async def system_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show overall system status."""
    try:
        status_message = "🖥️ **System Status**\n\n"
        
        # Templates status
        templates_status = templates.health_check()
        status_message += f"📧 Templates: {templates_status['status'].upper()}\n"
        status_message += f"   Count: {templates_status['templates_count']}\n"
        status_message += f"   MJML: {'✅' if templates_status['mjml_configured'] else '❌'}\n\n"
        
        # Contacts status
        contacts_status = contacts.health_check()
        status_message += f"👥 Contacts: {contacts_status['status'].upper()}\n"
        status_message += f"   Total: {contacts_status['total_contacts']}\n"
        status_message += f"   Groups: {contacts_status['total_groups']}\n\n"
        
        # Providers status
        provider_list = providers.list_providers(enabled_only=True)
        status_message += f"📨 Email Providers: {len(provider_list)} enabled\n"
        
        for provider in provider_list[:3]:  # Show first 3
            status_message += f"   • {provider['name']} ({provider['success_rate']:.1f}%)\n"
        
        if len(provider_list) > 3:
            status_message += f"   ... and {len(provider_list) - 3} more\n\n"
        
        # Campaigns status
        campaigns_stats = campaigns.get_campaign_stats()
        status_message += f"📢 Campaigns: {campaigns_stats['total_campaigns']} total\n"
        status_message += f"   Sent: {campaigns_stats['total_emails_sent']} emails\n"
        
        await update.message.reply_text(status_message)
        
    except Exception as e:
        logger.error("system_status error: %s", e)
        await update.message.reply_text("❌ Error getting system status")

# ========= MESSAGE HANDLER =========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all incoming messages and route them appropriately."""
    # Check if we're in the middle of adding a provider
    if "adding_provider" in context.user_data:
        await handle_provider_credentials(update, context)
        return
    
    # Check if we're expecting a file upload
    if "awaiting_upload" in context.user_data or "awaiting_contacts_upload" in context.user_data:
        await handle_file(update, context)
        return
    
    # Default response for unrecognized messages
    await update.message.reply_text(
        "🤖 I'm your Email Marketing Bot!\n\n"
        "Use /start to see all available commands\n"
        "Use /help for detailed examples\n"
        "Use /status to check system health"
    )

# ========= MAIN APPLICATION SETUP =========
def main():
    """Start the bot."""
    try:
        # Check database health before starting
        if not check_database_health():
            logger.warning("Some database modules are not healthy, but continuing...")
        
        app = ApplicationBuilder().token(BOT_TOKEN).build()

        # ========= REGISTER COMMAND HANDLERS =========
        
        # Basic commands
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("status", system_status))
        
        # Template commands
        app.add_handler(CommandHandler("newtemplate", new_template))
        app.add_handler(CommandHandler("uploadtemplate", upload_template))
        app.add_handler(CommandHandler("preview", preview))
        app.add_handler(CommandHandler("copy", ai_copy))
        
        # Contact commands
        app.add_handler(CommandHandler("contacts", show_contacts))
        app.add_handler(CommandHandler("uploadcontacts", upload_contacts))
        
        # Campaign commands
        app.add_handler(CommandHandler("campaigns", show_campaigns))
        app.add_handler(CommandHandler("newcampaign", new_campaign))
        
        # Provider management commands
        app.add_handler(CommandHandler("listproviders", list_providers_cmd))
        app.add_handler(CommandHandler("addprovider_start", add_provider_start))
        app.add_handler(CommandHandler("addprovider", add_provider))
        app.add_handler(CommandHandler("removeprovider", remove_provider_cmd))
        app.add_handler(CommandHandler("enableprovider", enable_provider_cmd))
        app.add_handler(CommandHandler("disableprovider", disable_provider_cmd))
        app.add_handler(CommandHandler("providerstats", provider_stats_cmd))
        app.add_handler(CommandHandler("testprovider", test_provider_cmd))
        
        # Message handlers (must be last)
        app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("🚀 Bot starting...")
        logger.info("✅ Modules loaded: templates, contacts, campaigns, providers")
        
        # Test module availability
        try:
            groups = contacts.list_groups()
            logger.info("📋 Available contact groups: %s", groups)
            
            provider_list = providers.list_providers()
            logger.info("📧 Available providers: %s", [p["name"] for p in provider_list])
            
            campaign_list = campaigns.list_campaigns()
            logger.info("📢 Available campaigns: %s", campaign_list)
            
        except Exception as e:
            logger.warning("Module test failed: %s", e)

        app.run_polling()
        
    except Exception as e:
        logger.error("❌ Failed to start bot: %s", e)
        raise

if __name__ == "__main__":
    main()