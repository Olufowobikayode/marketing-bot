# providers.py
import os
import json
import logging
import sqlite3
from typing import Dict, List, Optional, Any
from datetime import datetime

# ========= CONFIG =========
try:
    from config import DATA_DIR
except ImportError:
    from dotenv import load_dotenv
    load_dotenv()
    DATA_DIR = os.getenv("DATA_DIR", "data")

os.makedirs(DATA_DIR, exist_ok=True)
PROVIDERS_DB = os.path.join(DATA_DIR, "providers.db")

# ========= LOGGING =========
logger = logging.getLogger("providers")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)

# ========= DATABASE SETUP =========
def init_db():
    """Initialize providers database."""
    conn = sqlite3.connect(PROVIDERS_DB)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS email_providers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        provider_type TEXT NOT NULL,
        credentials TEXT NOT NULL,
        priority INTEGER DEFAULT 99,
        enabled BOOLEAN DEFAULT 1,
        daily_limit INTEGER DEFAULT 1000,
        used_today INTEGER DEFAULT 0,
        success_count INTEGER DEFAULT 0,
        failure_count INTEGER DEFAULT 0,
        last_used TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS provider_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id INTEGER,
        date TEXT NOT NULL,
        sent_count INTEGER DEFAULT 0,
        failed_count INTEGER DEFAULT 0,
        FOREIGN KEY (provider_id) REFERENCES email_providers (id)
    )
    """)
    
    # Create trigger for updated_at
    cur.execute("""
    CREATE TRIGGER IF NOT EXISTS update_provider_timestamp 
    AFTER UPDATE ON email_providers
    FOR EACH ROW
    BEGIN
        UPDATE email_providers SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END
    """)
    
    conn.commit()
    conn.close()
    logger.info("Providers database initialized")

# ========= PROVIDER MANAGEMENT =========
def add_provider(
    name: str,
    provider_type: str,
    credentials: Dict[str, Any],
    priority: int = 99,
    daily_limit: int = 1000
) -> bool:
    """
    Add a new email provider.
    
    Args:
        name: Unique name for the provider
        provider_type: Type of provider (api, smtp)
        credentials: Dictionary of provider credentials
        priority: Lower number = higher priority
        daily_limit: Maximum emails per day
    
    Returns:
        Success status
    """
    try:
        conn = sqlite3.connect(PROVIDERS_DB)
        cur = conn.cursor()
        
        cur.execute(
            """
            INSERT INTO email_providers 
            (name, provider_type, credentials, priority, daily_limit)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, provider_type, json.dumps(credentials), priority, daily_limit)
        )
        
        conn.commit()
        conn.close()
        
        logger.info("Added provider: %s (%s)", name, provider_type)
        return True
        
    except sqlite3.IntegrityError:
        logger.error("Provider with name '%s' already exists", name)
        return False
    except Exception as e:
        logger.error("Failed to add provider %s: %s", name, e)
        return False

def update_provider(
    name: str,
    credentials: Optional[Dict[str, Any]] = None,
    priority: Optional[int] = None,
    enabled: Optional[bool] = None,
    daily_limit: Optional[int] = None
) -> bool:
    """Update provider configuration."""
    try:
        conn = sqlite3.connect(PROVIDERS_DB)
        cur = conn.cursor()
        
        updates = []
        params = []
        
        if credentials is not None:
            updates.append("credentials = ?")
            params.append(json.dumps(credentials))
        
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
            
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(enabled)
            
        if daily_limit is not None:
            updates.append("daily_limit = ?")
            params.append(daily_limit)
            
        if not updates:
            return False
            
        params.append(name)
        
        query = f"UPDATE email_providers SET {', '.join(updates)} WHERE name = ?"
        cur.execute(query, params)
        
        conn.commit()
        conn.close()
        
        logger.info("Updated provider: %s", name)
        return cur.rowcount > 0
        
    except Exception as e:
        logger.error("Failed to update provider %s: %s", name, e)
        return False

def remove_provider(name: str) -> bool:
    """Remove a provider."""
    try:
        conn = sqlite3.connect(PROVIDERS_DB)
        cur = conn.cursor()
        
        cur.execute("DELETE FROM email_providers WHERE name = ?", (name,))
        success = cur.rowcount > 0
        
        conn.commit()
        conn.close()
        
        if success:
            logger.info("Removed provider: %s", name)
        else:
            logger.warning("Provider not found: %s", name)
            
        return success
        
    except Exception as e:
        logger.error("Failed to remove provider %s: %s", name, e)
        return False

def enable_provider(name: str) -> bool:
    """Enable a provider."""
    return update_provider(name, enabled=True)

def disable_provider(name: str) -> bool:
    """Disable a provider."""
    return update_provider(name, enabled=False)

def get_provider(name: str) -> Optional[Dict[str, Any]]:
    """Get provider details."""
    try:
        conn = sqlite3.connect(PROVIDERS_DB)
        cur = conn.cursor()
        
        cur.execute("SELECT * FROM email_providers WHERE name = ?", (name,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return None
            
        return {
            "id": row[0],
            "name": row[1],
            "type": row[2],
            "credentials": json.loads(row[3]),
            "priority": row[4],
            "enabled": bool(row[5]),
            "daily_limit": row[6],
            "used_today": row[7],
            "success_count": row[8],
            "failure_count": row[9],
            "last_used": row[10],
            "created_at": row[11],
            "updated_at": row[12]
        }
        
    except Exception as e:
        logger.error("Failed to get provider %s: %s", name, e)
        return None

def list_providers(enabled_only: bool = False) -> List[Dict[str, Any]]:
    """List all providers."""
    try:
        conn = sqlite3.connect(PROVIDERS_DB)
        cur = conn.cursor()
        
        if enabled_only:
            cur.execute("SELECT * FROM email_providers WHERE enabled = 1 ORDER BY priority, name")
        else:
            cur.execute("SELECT * FROM email_providers ORDER BY priority, name")
            
        rows = cur.fetchall()
        conn.close()
        
        providers = []
        for row in rows:
            providers.append({
                "id": row[0],
                "name": row[1],
                "type": row[2],
                "credentials": json.loads(row[3]),
                "priority": row[4],
                "enabled": bool(row[5]),
                "daily_limit": row[6],
                "used_today": row[7],
                "success_count": row[8],
                "failure_count": row[9],
                "last_used": row[10],
                "created_at": row[11],
                "updated_at": row[12],
                "success_rate": row[8] / (row[8] + row[9]) if (row[8] + row[9]) > 0 else 0
            })
            
        return providers
        
    except Exception as e:
        logger.error("Failed to list providers: %s", e)
        return []

def update_provider_stats(provider_name: str, success: bool):
    """Update provider usage statistics."""
    try:
        conn = sqlite3.connect(PROVIDERS_DB)
        cur = conn.cursor()
        
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Update daily usage
        if success:
            cur.execute(
                "UPDATE email_providers SET success_count = success_count + 1, used_today = used_today + 1, last_used = CURRENT_TIMESTAMP WHERE name = ?",
                (provider_name,)
            )
        else:
            cur.execute(
                "UPDATE email_providers SET failure_count = failure_count + 1, last_used = CURRENT_TIMESTAMP WHERE name = ?",
                (provider_name,)
            )
        
        # Update daily stats
        cur.execute(
            "SELECT id FROM provider_stats WHERE provider_id = (SELECT id FROM email_providers WHERE name = ?) AND date = ?",
            (provider_name, today)
        )
        
        if cur.fetchone():
            if success:
                cur.execute(
                    "UPDATE provider_stats SET sent_count = sent_count + 1 WHERE provider_id = (SELECT id FROM email_providers WHERE name = ?) AND date = ?",
                    (provider_name, today)
                )
            else:
                cur.execute(
                    "UPDATE provider_stats SET failed_count = failed_count + 1 WHERE provider_id = (SELECT id FROM email_providers WHERE name = ?) AND date = ?",
                    (provider_name, today)
                )
        else:
            cur.execute(
                "INSERT INTO provider_stats (provider_id, date, sent_count, failed_count) VALUES ((SELECT id FROM email_providers WHERE name = ?), ?, ?, ?)",
                (provider_name, today, 1 if success else 0, 0 if success else 1)
            )
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error("Failed to update stats for %s: %s", provider_name, e)

def reset_daily_limits():
    """Reset daily usage counters (call this daily via cron)."""
    try:
        conn = sqlite3.connect(PROVIDERS_DB)
        cur = conn.cursor()
        cur.execute("UPDATE email_providers SET used_today = 0")
        conn.commit()
        conn.close()
        logger.info("Daily limits reset")
    except Exception as e:
        logger.error("Failed to reset daily limits: %s", e)

def get_provider_stats(provider_name: str) -> Dict[str, Any]:
    """Get detailed statistics for a provider."""
    provider = get_provider(provider_name)
    if not provider:
        return {"error": "Provider not found"}
    
    try:
        conn = sqlite3.connect(PROVIDERS_DB)
        cur = conn.cursor()
        
        # Get 30-day history
        cur.execute("""
            SELECT date, sent_count, failed_count 
            FROM provider_stats 
            WHERE provider_id = ? 
            ORDER BY date DESC 
            LIMIT 30
        """, (provider["id"],))
        
        history = []
        for row in cur.fetchall():
            history.append({
                "date": row[0],
                "sent": row[1],
                "failed": row[2]
            })
        
        conn.close()
        
        total_attempts = provider["success_count"] + provider["failure_count"]
        success_rate = (provider["success_count"] / total_attempts * 100) if total_attempts > 0 else 0
        
        return {
            "name": provider["name"],
            "type": provider["type"],
            "enabled": provider["enabled"],
            "priority": provider["priority"],
            "daily_usage": f"{provider['used_today']}/{provider['daily_limit']}",
            "success_rate": f"{success_rate:.1f}%",
            "total_sent": provider["success_count"],
            "total_failed": provider["failure_count"],
            "last_used": provider["last_used"],
            "history": history
        }
        
    except Exception as e:
        logger.error("Failed to get stats for %s: %s", provider_name, e)
        return {"error": str(e)}

# ========= PROVIDER TEMPLATES =========
PROVIDER_TEMPLATES = {
    "Brevo": {
        "type": "api",
        "credentials": ["api_key"],
        "instructions": "Get your API key from Brevo dashboard"
    },
    "SendGrid": {
        "type": "api", 
        "credentials": ["api_key"],
        "instructions": "Create API key in SendGrid settings"
    },
    "Mailgun": {
        "type": "api",
        "credentials": ["api_key", "domain"],
        "instructions": "Get API key and domain from Mailgun control panel"
    },
    "Mailjet": {
        "type": "api",
        "credentials": ["api_key", "api_secret"],
        "instructions": "Get API key and secret from Mailjet account"
    },
    "Gmail-SMTP": {
        "type": "smtp",
        "credentials": ["host", "port", "user", "password"],
        "instructions": "Use Gmail SMTP with app password"
    },
    "Outlook-SMTP": {
        "type": "smtp", 
        "credentials": ["host", "port", "user", "password"],
        "instructions": "Use Outlook SMTP settings"
    }
}

def get_supported_providers() -> List[str]:
    """Get list of supported provider types."""
    return list(PROVIDER_TEMPLATES.keys())

def get_provider_template(provider_type: str) -> Optional[Dict[str, Any]]:
    """Get template for a provider type."""
    return PROVIDER_TEMPLATES.get(provider_type)

# ========= INITIALIZATION =========
def initialize_default_providers():
    """Initialize with any providers from environment variables."""
    try:
        # Check if we have any providers already
        existing = list_providers()
        if existing:
            logger.info("Found %d existing providers", len(existing))
            return
            
        # Add providers from environment variables if they exist
        env_providers = []
        
        # Brevo
        if os.getenv("BREVO_API_KEY"):
            env_providers.append(("Brevo", "api", {"api_key": os.getenv("BREVO_API_KEY")}))
            
        # SendGrid
        if os.getenv("SENDGRID_API_KEY"):
            env_providers.append(("SendGrid", "api", {"api_key": os.getenv("SENDGRID_API_KEY")}))
            
        # Mailgun
        if os.getenv("MAILGUN_API_KEY") and os.getenv("MAILGUN_DOMAIN"):
            env_providers.append(("Mailgun", "api", {
                "api_key": os.getenv("MAILGUN_API_KEY"),
                "domain": os.getenv("MAILGUN_DOMAIN")
            }))
            
        # Gmail SMTP
        if all(os.getenv(var) for var in ["SMTP_GMAIL_HOST", "SMTP_GMAIL_USER", "SMTP_GMAIL_PASS"]):
            env_providers.append(("Gmail-SMTP", "smtp", {
                "host": os.getenv("SMTP_GMAIL_HOST"),
                "port": int(os.getenv("SMTP_GMAIL_PORT", "587")),
                "user": os.getenv("SMTP_GMAIL_USER"),
                "password": os.getenv("SMTP_GMAIL_PASS")
            }))
        
        for name, p_type, creds in env_providers:
            add_provider(name, p_type, creds, priority=1)
            logger.info("Added environment provider: %s", name)
            
    except Exception as e:
        logger.error("Failed to initialize default providers: %s", e)

# Initialize on import
init_db()
initialize_default_providers()