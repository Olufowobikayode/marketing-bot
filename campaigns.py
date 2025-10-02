# campaigns.py
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from bson import ObjectId
import pymongo
from pymongo import MongoClient
from pymongo.errors import PyMongoError

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
logger = logging.getLogger("campaigns")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
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
    def get_campaigns_collection(cls):
        db = cls.get_db()
        return db.campaigns
    
    @classmethod
    def close_connection(cls):
        if cls._client:
            cls._client.close()
            cls._client = None
            cls._db = None
            logger.info("MongoDB connection closed")

def get_campaigns_collection():
    """Get the campaigns collection with error handling."""
    return MongoDBManager.get_campaigns_collection()

# ========= DATABASE INITIALIZATION =========
def init_db():
    """Initialize MongoDB indexes for campaigns with robust error handling."""
    try:
        collection = get_campaigns_collection()
        
        # Create indexes for performance
        collection.create_index([("name", pymongo.ASCENDING)], unique=True, name="idx_campaigns_name")
        collection.create_index([("status", pymongo.ASCENDING)], name="idx_campaigns_status")
        collection.create_index([("created_at", pymongo.DESCENDING)], name="idx_campaigns_created")
        collection.create_index([("template_key", pymongo.ASCENDING)], name="idx_campaigns_template")
        collection.create_index([("contacts_group", pymongo.ASCENDING)], name="idx_campaigns_contacts")
        
        logger.info("MongoDB indexes initialized successfully")
        
    except Exception as e:
        logger.error("Failed to initialize MongoDB indexes: %s", e)
        raise

# ========= CORE FUNCTIONS =========
def list_campaigns() -> List[str]:
    """List all campaign names."""
    try:
        collection = get_campaigns_collection()
        campaigns = collection.find({}, {"name": 1}).sort("created_at", pymongo.DESCENDING)
        return [campaign["name"] for campaign in campaigns]
    except PyMongoError as e:
        logger.error("Failed to list campaigns: %s", e)
        return []

def create_campaign(name: str, template_key: str, contacts_group: str, 
                   subject: str = "", status: str = "draft") -> bool:
    """Create a new campaign."""
    try:
        collection = get_campaigns_collection()
        
        # Check if campaign already exists
        existing = collection.find_one({"name": name})
        if existing:
            logger.warning("Campaign %s already exists", name)
            return False
        
        campaign_data = {
            'name': name,
            'template_key': template_key,
            'contacts_group': contacts_group,
            'subject': subject,
            'status': status,
            'sent_count': 0,
            'total_recipients': 0,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        result = collection.insert_one(campaign_data)
        
        if result.inserted_id:
            logger.info("Created campaign: %s", name)
            return True
        else:
            logger.error("Failed to create campaign: %s", name)
            return False
            
    except PyMongoError as e:
        logger.error("Failed to create campaign %s: %s", name, e)
        return False

def get_campaign(name: str) -> Optional[Dict[str, Any]]:
    """Get campaign details."""
    try:
        collection = get_campaigns_collection()
        campaign = collection.find_one({"name": name})
        
        if campaign:
            # Convert ObjectId to string and remove MongoDB _id
            campaign_dict = dict(campaign)
            campaign_dict["_id"] = str(campaign_dict["_id"])
            return campaign_dict
        else:
            return None
            
    except PyMongoError as e:
        logger.error("Failed to get campaign %s: %s", name, e)
        return None

def update_campaign_status(name: str, status: str, sent_count: int = 0) -> bool:
    """Update campaign status and statistics."""
    try:
        collection = get_campaigns_collection()
        
        result = collection.update_one(
            {"name": name},
            {
                "$set": {
                    "status": status,
                    "sent_count": sent_count,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        if result.modified_count > 0:
            logger.info("Updated campaign %s status to %s", name, status)
            return True
        else:
            logger.warning("Campaign %s not found for update", name)
            return False
            
    except PyMongoError as e:
        logger.error("Failed to update campaign %s: %s", name, e)
        return False

def delete_campaign(name: str) -> bool:
    """Delete a campaign."""
    try:
        collection = get_campaigns_collection()
        
        result = collection.delete_one({"name": name})
        
        if result.deleted_count > 0:
            logger.info("Deleted campaign: %s", name)
            return True
        else:
            logger.warning("Campaign %s not found for deletion", name)
            return False
            
    except PyMongoError as e:
        logger.error("Failed to delete campaign %s: %s", name, e)
        return False

# ========= STATISTICS =========
def get_campaign_stats() -> Dict[str, Any]:
    """Get overall campaign statistics."""
    try:
        collection = get_campaigns_collection()
        
        # Total campaigns
        total_campaigns = collection.count_documents({})
        
        # Count by status using aggregation
        pipeline = [
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                    "total_sent": {"$sum": "$sent_count"}
                }
            }
        ]
        
        status_results = list(collection.aggregate(pipeline))
        
        # Convert to status_count dict
        status_count = {}
        total_emails_sent = 0
        
        for result in status_results:
            status = result["_id"]
            status_count[status] = result["count"]
            total_emails_sent += result["total_sent"]
        
        return {
            'total_campaigns': total_campaigns,
            'by_status': status_count,
            'total_emails_sent': total_emails_sent
        }
        
    except PyMongoError as e:
        logger.error("Failed to get campaign stats: %s", e)
        return {
            'total_campaigns': 0,
            'by_status': {},
            'total_emails_sent': 0
        }

# ========= ADDITIONAL CAMPAIGN OPERATIONS =========
def update_campaign_sent_count(name: str, additional_sent: int = 1) -> bool:
    """Increment the sent count for a campaign."""
    try:
        collection = get_campaigns_collection()
        
        result = collection.update_one(
            {"name": name},
            {
                "$inc": {"sent_count": additional_sent},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        
        return result.modified_count > 0
        
    except PyMongoError as e:
        logger.error("Failed to update campaign sent count for %s: %s", name, e)
        return False

def get_campaigns_by_status(status: str) -> List[Dict[str, Any]]:
    """Get all campaigns with a specific status."""
    try:
        collection = get_campaigns_collection()
        
        campaigns = collection.find(
            {"status": status},
            projection={"_id": 0}  # Exclude MongoDB _id
        ).sort("created_at", pymongo.DESCENDING)
        
        return list(campaigns)
        
    except PyMongoError as e:
        logger.error("Failed to get campaigns by status %s: %s", status, e)
        return []

def search_campaigns(
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    template_key: Optional[str] = None,
    contacts_group: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Search campaigns with various filters."""
    try:
        collection = get_campaigns_collection()
        
        # Build query
        query = {}
        if keyword:
            query["$or"] = [
                {"name": {"$regex": keyword, "$options": "i"}},
                {"subject": {"$regex": keyword, "$options": "i"}}
            ]
        if status:
            query["status"] = status
        if template_key:
            query["template_key"] = template_key
        if contacts_group:
            query["contacts_group"] = contacts_group
        
        campaigns = collection.find(
            query,
            projection={"_id": 0}
        ).sort("created_at", pymongo.DESCENDING).skip(offset).limit(limit)
        
        return list(campaigns)
        
    except PyMongoError as e:
        logger.error("Failed to search campaigns: %s", e)
        return []

# ========= HEALTH CHECK =========
def health_check() -> Dict[str, Any]:
    """Perform health check on campaigns module."""
    health = {
        "module": "campaigns",
        "status": "unknown",
        "database_accessible": False,
        "total_campaigns": 0,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        # Test database connection and basic operations
        collection = get_campaigns_collection()
        
        # Test connection with a simple command
        collection.database.command('ping')
        health["database_accessible"] = True
        
        # Count total campaigns
        health["total_campaigns"] = collection.count_documents({})
        
        # Get status distribution
        stats = get_campaign_stats()
        health["by_status"] = stats["by_status"]
        health["total_emails_sent"] = stats["total_emails_sent"]
        
        if health["database_accessible"]:
            health["status"] = "healthy"
        else:
            health["status"] = "degraded"
            health["warning"] = "Database connection issue"
                
    except Exception as e:
        health["status"] = "error"
        health["error"] = str(e)
    
    return health

# ========= MODULE INIT =========
def _initialize_campaigns_db():
    """Initialize campaigns database if empty."""
    try:
        init_db()
        
        # Check if we have any campaigns already
        collection = get_campaigns_collection()
        if collection.count_documents({}) == 0:
            # Create sample campaign
            sample_campaign = {
                'name': 'welcome_campaign',
                'template_key': 'welcome_email',
                'contacts_group': 'subscribers',
                'subject': 'Welcome to Our Service!',
                'status': 'draft',
                'sent_count': 0,
                'total_recipients': 0,
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }
            
            collection.insert_one(sample_campaign)
            logger.info("Initialized campaigns database with sample data")
        
        # Health check on startup
        health = health_check()
        if health["status"] == "healthy":
            logger.info("Campaigns module initialized: %d campaigns", health["total_campaigns"])
        else:
            logger.warning("Campaigns module initialized with issues: %s", health.get("error", "Unknown"))
            
    except Exception as e:
        logger.error("Failed to initialize campaigns module: %s", e)

# Initialize on import
_initialize_campaigns_db()

# ========= CLI TEST =========
if __name__ == "__main__":
    print("Campaigns Module Test")
    print("Existing campaigns:", list_campaigns())
    stats = get_campaign_stats()
    print("Stats:", stats)
    
    # Health check
    health = health_check()
    print("Health:", health["status"])
    print("Total campaigns:", health["total_campaigns"])