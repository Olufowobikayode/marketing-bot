# config.py
import os
from dotenv import load_dotenv

# Load env file
load_dotenv()

# ========= REQUIRED CORE =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MJML_APP_ID = os.getenv("MJML_APP_ID")
MJML_SECRET = os.getenv("MJML_SECRET")
MONGODB_URI = os.getenv("MONGODB_URI")

# ========= OPTIONAL WITH DEFAULTS =========
TEST_EMAIL = os.getenv("TEST_EMAIL")
DEFAULT_SENDER_EMAIL = os.getenv("DEFAULT_SENDER_EMAIL", "noreply@example.com")
DEFAULT_SENDER_NAME = os.getenv("DEFAULT_SENDER_NAME", "Email Marketing Bot")

# Performance settings
REQUESTS_PER_SECOND = float(os.getenv("REQUESTS_PER_SECOND", "2.0"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# Directory paths (for file storage, not databases)
DATA_DIR = os.getenv("DATA_DIR", "data")
TEMPLATE_DIR = os.getenv("TEMPLATE_DIR", "templates")
BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")

# Derived paths (for file storage only)
TEMPLATE_DB = os.path.join(DATA_DIR, "templates.json")
CONTACTS_DB = os.path.join(DATA_DIR, "contacts.db")

# MongoDB database name
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "marketing_bot")

# ========= VALIDATION =========
# Check required environment variables
required_vars = {
    "BOT_TOKEN": BOT_TOKEN,
    "GEMINI_API_KEY": GEMINI_API_KEY, 
    "MJML_APP_ID": MJML_APP_ID,
    "MJML_SECRET": MJML_SECRET,
    "MONGODB_URI": MONGODB_URI
}

missing_vars = [name for name, value in required_vars.items() if not value]
if missing_vars:
    raise EnvironmentError(f"❌ Missing required environment variables: {', '.join(missing_vars)}")

# Ensure directories exist (for file storage)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(TEMPLATE_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

print("✅ Configuration loaded successfully")
print(f"   - Data directory: {DATA_DIR}")
print(f"   - Template directory: {TEMPLATE_DIR}")
print(f"   - MongoDB configured: {bool(MONGODB_URI)}")
print(f"   - MJML configured: {bool(MJML_APP_ID and MJML_SECRET)}")
print(f"   - AI configured: {bool(GEMINI_API_KEY)}")