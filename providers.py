# providers.py
import os
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from bson import ObjectId
import pymongo
from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError, DuplicateKeyError

# ========= CONFIG =========
try:
    from config import MONGODB_URI, MONGODB_DB_NAME, DATA_DIR
except ImportError:
    from dotenv import load_dotenv
    load_dotenv()
    MONGODB_URI = os.getenv("MONGODB_URI")
    MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "marketing_bot")
    DATA_DIR = os.getenv("DATA_DIR", "data")

os.makedirs(DATA_DIR, exist_ok=True)

# ========= LOGGING =========
logger = logging.getLogger("providers")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)

# ========= MONGODB CONNECTION MANAGEMENT =========
class MongoDBManager:
    _client = None
    _db = None
    
    @classmethod
    def get_client(cls):
        if cls._client is None:
            try:
                cls._client = MongoClient(
                    MONGODB_URI,
                    maxPoolSize=50,
                    connectTimeoutMS=30000,
                    socketTimeoutMS=30000,
                    retryWrites=True
                )
                # Test connection
                cls._client.admin.command('ping')
                logger.info("MongoDB connection established successfully")
            except Exception as e:
                logger.error("Failed to connect to MongoDB: %s", e)
                raise
        return cls._client
    
    @classmethod
    def get_db(cls):
        if cls._db is None:
            client = cls.get_client()
            cls._db = client[MONGODB_DB_NAME]
        return cls._db
    
    @classmethod
    def get_providers_collection(cls):
        db = cls.get_db()
        return db.providers
    
    @classmethod
    def get_provider_stats_collection(cls):
        db = cls.get_db()
        return db.provider_stats
    
    @classmethod
    def close_connection(cls):
        if cls._client:
            cls._client.close()
            cls._client = None
            cls._db = None
            logger.info("MongoDB connection closed")

def get_providers_collection():
    """Get the providers collection with error handling."""
    return MongoDBManager.get_providers_collection()

def get_provider_stats_collection():
    """Get the provider_stats collection with error handling."""
    return MongoDBManager.get_provider_stats_collection()

# ========= DATABASE SETUP =========
def init_db():
    """Initialize MongoDB indexes for providers with robust error handling."""
    try:
        providers_collection = get_providers_collection()
        stats_collection = get_provider_stats_collection()
        
        # Create indexes for providers
        providers_collection.create_index([("name", pymongo.ASCENDING)], unique=True, name="idx_providers_name")
        providers_collection.create_index([("enabled", pymongo.ASCENDING)], name="idx_providers_enabled")
        providers_collection.create_index([("priority", pymongo.ASCENDING)], name="idx_providers_priority")
        providers_collection.create_index([("provider_type", pymongo.ASCENDING)], name="idx_providers_type")
        
        # Create indexes for provider_stats
        stats_collection.create_index([("provider_name", pymongo.ASCENDING), ("date", pymongo.ASCENDING)], 
                                    unique=True, name="idx_stats_provider_date")
        stats_collection.create_index([("date", pymongo.ASCENDING)], name="idx_stats_date")
        
        logger.info("MongoDB indexes initialized successfully")
        
    except Exception as e:
        logger.error("Failed to initialize MongoDB indexes: %s", e)
        raise

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
        collection = get_providers_collection()
        
        provider_data = {
            "name": name,
            "provider_type": provider_type,
            "credentials": credentials,
            "priority": priority,
            "enabled": True,
            "daily_limit": daily_limit,
            "used_today": 0,
            "success_count": 0,
            "failure_count": 0,
            "last_used": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        result = collection.insert_one(provider_data)
        
        if result.inserted_id:
            logger.info("Added provider: %s (%s)", name, provider_type)
            return True
        else:
            logger.error("Failed to add provider: %s", name)
            return False
        
    except DuplicateKeyError:
        logger.error("Provider with name '%s' already exists", name)
        return False
    except PyMongoError as e:
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
        collection = get_providers_collection()
        
        update_data = {"updated_at": datetime.utcnow()}
        
        if credentials is not None:
            update_data["credentials"] = credentials
        
        if priority is not None:
            update_data["priority"] = priority
            
        if enabled is not None:
            update_data["enabled"] = enabled
            
        if daily_limit is not None:
            update_data["daily_limit"] = daily_limit
            
        if len(update_data) == 1:  # Only updated_at was set
            return False
            
        result = collection.update_one(
            {"name": name},
            {"$set": update_data}
        )
        
        if result.modified_count > 0:
            logger.info("Updated provider: %s", name)
            return True
        else:
            logger.warning("Provider %s not found for update", name)
            return False
        
    except PyMongoError as e:
        logger.error("Failed to update provider %s: %s", name, e)
        return False

def remove_provider(name: str) -> bool:
    """Remove a provider."""
    try:
        providers_collection = get_providers_collection()
        stats_collection = get_provider_stats_collection()
        
        # Remove provider and its stats
        provider_result = providers_collection.delete_one({"name": name})
        stats_collection.delete_many({"provider_name": name})
        
        if provider_result.deleted_count > 0:
            logger.info("Removed provider: %s", name)
            return True
        else:
            logger.warning("Provider not found: %s", name)
            return False
        
    except PyMongoError as e:
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
        collection = get_providers_collection()
        
        provider = collection.find_one({"name": name})
        
        if provider:
            # Convert ObjectId to string and calculate success rate
            provider_dict = dict(provider)
            provider_dict["_id"] = str(provider_dict["_id"])
            
            total_attempts = provider_dict["success_count"] + provider_dict["failure_count"]
            provider_dict["success_rate"] = (
                provider_dict["success_count"] / total_attempts * 100 
                if total_attempts > 0 else 0
            )
            
            return provider_dict
        else:
            return None
        
    except PyMongoError as e:
        logger.error("Failed to get provider %s: %s", name, e)
        return None

def list_providers(enabled_only: bool = False) -> List[Dict[str, Any]]:
    """List all providers."""
    try:
        collection = get_providers_collection()
        
        query = {}
        if enabled_only:
            query["enabled"] = True
            
        providers_cursor = collection.find(query).sort([("priority", pymongo.ASCENDING), ("name", pymongo.ASCENDING)])
        
        providers = []
        for provider in providers_cursor:
            provider_dict = dict(provider)
            provider_dict["_id"] = str(provider_dict["_id"])
            
            # Calculate success rate
            total_attempts = provider_dict["success_count"] + provider_dict["failure_count"]
            provider_dict["success_rate"] = (
                provider_dict["success_count"] / total_attempts * 100 
                if total_attempts > 0 else 0
            )
            
            providers.append(provider_dict)
            
        return providers
        
    except PyMongoError as e:
        logger.error("Failed to list providers: %s", e)
        return []

def update_provider_stats(provider_name: str, success: bool):
    """Update provider usage statistics."""
    try:
        providers_collection = get_providers_collection()
        stats_collection = get_provider_stats_collection()
        
        today = datetime.utcnow().strftime("%Y-%m-%d")
        now = datetime.utcnow()
        
        # Update provider main stats
        update_data = {
            "last_used": now,
            "updated_at": now
        }
        
        if success:
            update_data["$inc"] = {
                "success_count": 1,
                "used_today": 1
            }
        else:
            update_data["$inc"] = {
                "failure_count": 1
            }
        
        providers_collection.update_one(
            {"name": provider_name},
            update_data
        )
        
        # Update daily stats
        stats_update = {
            "$setOnInsert": {
                "provider_name": provider_name,
                "date": today
            }
        }
        
        if success:
            stats_update["$inc"] = {"sent_count": 1}
        else:
            stats_update["$inc"] = {"failed_count": 1}
        
        stats_collection.update_one(
            {"provider_name": provider_name, "date": today},
            stats_update,
            upsert=True
        )
        
    except PyMongoError as e:
        logger.error("Failed to update stats for %s: %s", provider_name, e)

def reset_daily_limits():
    """Reset daily usage counters (call this daily via cron)."""
    try:
        collection = get_providers_collection()
        collection.update_many(
            {},
            {"$set": {"used_today": 0, "updated_at": datetime.utcnow()}}
        )
        logger.info("Daily limits reset")
    except PyMongoError as e:
        logger.error("Failed to reset daily limits: %s", e)

def get_provider_stats(provider_name: str) -> Dict[str, Any]:
    """Get detailed statistics for a provider."""
    provider = get_provider(provider_name)
    if not provider:
        return {"error": "Provider not found"}
    
    try:
        stats_collection = get_provider_stats_collection()
        
        # Get 30-day history
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        history_cursor = stats_collection.find(
            {
                "provider_name": provider_name,
                "date": {"$gte": thirty_days_ago}
            }
        ).sort("date", pymongo.DESCENDING).limit(30)
        
        history = []
        for stat in history_cursor:
            history.append({
                "date": stat["date"],
                "sent": stat.get("sent_count", 0),
                "failed": stat.get("failed_count", 0)
            })
        
        total_attempts = provider["success_count"] + provider["failure_count"]
        success_rate = (provider["success_count"] / total_attempts * 100) if total_attempts > 0 else 0
        
        return {
            "name": provider["name"],
            "type": provider["provider_type"],
            "enabled": provider["enabled"],
            "priority": provider["priority"],
            "daily_usage": f"{provider['used_today']}/{provider['daily_limit']}",
            "success_rate": f"{success_rate:.1f}%",
            "total_sent": provider["success_count"],
            "total_failed": provider["failure_count"],
            "last_used": provider["last_used"],
            "history": history
        }
        
    except PyMongoError as e:
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

# ========= HEALTH CHECK =========
def health_check() -> Dict[str, Any]:
    """Perform health check on providers module."""
    health = {
        "module": "providers",
        "status": "unknown",
        "database_accessible": False,
        "total_providers": 0,
        "enabled_providers": 0,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        # Test database connection and basic operations
        providers_collection = get_providers_collection()
        
        # Test connection with a simple command
        providers_collection.database.command('ping')
        health["database_accessible"] = True
        
        # Count providers
        health["total_providers"] = providers_collection.count_documents({})
        health["enabled_providers"] = providers_collection.count_documents({"enabled": True})
        
        # Get provider statistics
        providers = list_providers()
        total_success = sum(p["success_count"] for p in providers)
        total_failures = sum(p["failure_count"] for p in providers)
        total_attempts = total_success + total_failures
        
        health["total_emails_sent"] = total_success
        health["total_emails_failed"] = total_failures
        health["success_rate"] = (total_success / total_attempts * 100) if total_attempts > 0 else 0
        
        if health["database_accessible"]:
            health["status"] = "healthy"
        else:
            health["status"] = "degraded"
            health["warning"] = "Database connection issue"
                
    except Exception as e:
        health["status"] = "error"
        health["error"] = str(e)
    
    return health

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

# ========= CLI TEST =========
if __name__ == "__main__":
    print("📧 Providers Module Production Test")
    print("=" * 50)
    
    # Health check
    health = health_check()
    print(f"Health Status: {health['status']}")
    print(f"Database Accessible: {health['database_accessible']}")
    print(f"Total Providers: {health['total_providers']}")
    print(f"Enabled Providers: {health['enabled_providers']}")
    print(f"Success Rate: {health['success_rate']:.1f}%")
    
    if health["status"] == "healthy":
        # List providers
        providers = list_providers()
        print(f"\n📋 Email Providers ({len(providers)}):")
        for provider in providers:
            status = "🟢" if provider["enabled"] else "🔴"
            print(f"  {status} {provider['name']} ({provider['provider_type']}) - Priority: {provider['priority']}")