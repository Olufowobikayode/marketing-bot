# contacts.py
import os
import re
import csv
import json
import logging
import pandas as pd
from typing import List, Dict, Tuple, Optional, Any
from email_validator import validate_email, EmailNotValidError
from datetime import datetime
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
logger = logging.getLogger("contacts")
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
    def get_contacts_collection(cls):
        db = cls.get_db()
        return db.contacts
    
    @classmethod
    def close_connection(cls):
        if cls._client:
            cls._client.close()
            cls._client = None
            cls._db = None
            logger.info("MongoDB connection closed")

def get_contacts_collection():
    """Get the contacts collection with error handling."""
    return MongoDBManager.get_contacts_collection()

def init_db():
    """Initialize MongoDB indexes for contacts with robust error handling."""
    try:
        collection = get_contacts_collection()
        
        # Create indexes for performance
        collection.create_index([("group_name", pymongo.ASCENDING)], name="idx_contacts_group")
        collection.create_index([("email", pymongo.ASCENDING)], name="idx_contacts_email")
        collection.create_index([("valid", pymongo.ASCENDING)], name="idx_contacts_valid")
        
        # Create unique compound index for email+group_name constraint
        collection.create_index(
            [("email", pymongo.ASCENDING), ("group_name", pymongo.ASCENDING)],
            unique=True,
            name="idx_contacts_email_group_unique"
        )
        
        # Create TTL index for automatic cleanup if needed (optional)
        # collection.create_index([("created_at", pymongo.ASCENDING)], expireAfterSeconds=3600)
        
        logger.info("MongoDB indexes initialized successfully")
        
    except Exception as e:
        logger.error("Failed to initialize MongoDB indexes: %s", e)
        raise

# ========= VALIDATION =========
def validate_email_address(email: str) -> bool:
    """Check if an email address is valid using RFC checks with timeout."""
    if not email or not isinstance(email, str):
        return False
        
    # Basic format check first
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return False
        
    try:
        # Use timeout to prevent hanging on problematic emails
        import signal
        
        class TimeoutError(Exception):
            pass
            
        def timeout_handler(signum, frame):
            raise TimeoutError("Email validation timeout")
        
        # Set timeout for email validation (5 seconds)
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(5)
        
        try:
            validate_email(email, check_deliverability=False)
            signal.alarm(0)  # Cancel timeout
            return True
        except TimeoutError:
            logger.warning("Email validation timed out for: %s", email)
            return False
        except EmailNotValidError:
            return False
            
    except Exception as e:
        logger.warning("Email validation error for %s: %s", email, e)
        # Fallback to basic regex validation
        return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

def validate_group_name(group_name: str) -> bool:
    """Validate group name format."""
    if not group_name or not isinstance(group_name, str):
        return False
    if len(group_name) > 100:
        return False
    if not re.match(r'^[a-zA-Z0-9_\- ]+$', group_name):
        return False
    return True

# ========= CONTACTS MANAGEMENT =========
def save_contacts_from_file(file_path: str, group_name: str) -> Tuple[int, int, List[str]]:
    """
    Save contacts from a CSV/Excel file into a specific group with robust error handling.
    
    Returns:
        Tuple of (saved_count, invalid_count, error_messages)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    if not validate_group_name(group_name):
        raise ValueError(f"Invalid group name: {group_name}")

    file_size = os.path.getsize(file_path)
    if file_size > 50 * 1024 * 1024:  # 50MB limit
        raise ValueError("File too large (max 50MB)")
    
    if file_size == 0:
        raise ValueError("File is empty")

    ext = os.path.splitext(file_path)[1].lower()
    rows = []
    error_messages = []

    try:
        if ext in [".csv", ".txt"]:
            # Try different encodings
            encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'windows-1252']
            for encoding in encodings:
                try:
                    df = pd.read_csv(file_path, encoding=encoding)
                    rows = df.values.tolist()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError("Could not decode CSV file with any common encoding")
                
        elif ext in [".xls", ".xlsx"]:
            df = pd.read_excel(file_path)
            rows = df.values.tolist()
        else:
            raise ValueError(f"Unsupported file type: {ext}. Use CSV or Excel.")
            
    except Exception as e:
        logger.error("File parsing error: %s", e)
        raise ValueError(f"Failed to parse file: {str(e)}")

    saved, invalid = 0, 0
    bulk_operations = []
    
    try:
        collection = get_contacts_collection()
        
        for row_num, row in enumerate(rows, 1):
            try:
                email, name = None, None

                # Extract email and name from row cells
                for cell in row:
                    if pd.isna(cell):
                        continue
                    cell_str = str(cell).strip()
                    if not cell_str:
                        continue
                        
                    if "@" in cell_str and not email:
                        # Basic email format check
                        if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', cell_str):
                            email = cell_str
                    elif not name and cell_str:
                        name = cell_str[:100]  # Limit name length

                if not email:
                    invalid += 1
                    error_messages.append(f"Row {row_num}: No valid email found")
                    continue

                # Validate email
                is_valid = validate_email_address(email)
                
                # Prepare contact document
                contact_doc = {
                    "group_name": group_name,
                    "name": name,
                    "email": email,
                    "valid": is_valid,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
                
                # Create upsert operation
                bulk_operations.append(
                    UpdateOne(
                        {"email": email, "group_name": group_name},
                        {"$setOnInsert": contact_doc},
                        upsert=True
                    )
                )
                
            except Exception as e:
                error_messages.append(f"Row {row_num}: Processing error - {str(e)}")
                invalid += 1
                continue

        # Execute bulk operations
        if bulk_operations:
            result = collection.bulk_write(bulk_operations, ordered=False)
            saved = result.upserted_count
            # Note: MongoDB doesn't tell us about duplicates in bulk operations
            # We'll estimate duplicates as total rows - saved - invalid
            estimated_duplicates = len(rows) - saved - invalid
            logger.debug("Estimated duplicates: %d", estimated_duplicates)
            
    except PyMongoError as e:
        logger.error("MongoDB error during contact import: %s", e)
        raise
    except Exception as e:
        logger.error("Unexpected error during contact import: %s", e)
        raise
        
    logger.info(
        "Imported %d contacts from %s: %d saved, %d invalid",
        len(rows), file_path, saved, invalid
    )
    
    return saved, invalid, error_messages[:10]  # Return first 10 errors

def list_contacts(
    group_name: str, 
    limit: int = 50, 
    offset: int = 0,
    only_valid: bool = False
) -> List[Dict]:
    """Fetch contacts by group with pagination and filtering."""
    if not validate_group_name(group_name):
        raise ValueError(f"Invalid group name: {group_name}")
        
    limit = max(1, min(limit, 1000))  # Enforce reasonable limits
    offset = max(0, offset)
    
    try:
        collection = get_contacts_collection()
        
        query = {"group_name": group_name}
        if only_valid:
            query["valid"] = True
            
        cursor = collection.find(
            query,
            projection={"_id": 0, "id": {"$toString": "$_id"}, "name": 1, "email": 1, "valid": 1, "created_at": 1}
        ).sort("_id", pymongo.ASCENDING).skip(offset).limit(limit)
        
        contacts = []
        for doc in cursor:
            # Convert ObjectId to string for JSON serialization
            doc["id"] = str(doc["_id"])
            del doc["_id"]
            contacts.append(doc)
            
        return contacts
            
    except PyMongoError as e:
        logger.error("Error listing contacts for group %s: %s", group_name, e)
        raise

# ========= GROUP MANAGEMENT =========
def list_groups() -> List[str]:
    """List all contact groups with error handling."""
    try:
        collection = get_contacts_collection()
        groups = collection.distinct("group_name")
        return sorted(groups)
    except PyMongoError as e:
        logger.error("Error listing groups: %s", e)
        return []

def count_group_contacts(group_name: str) -> int:
    """Count contacts in a group with validation."""
    if not validate_group_name(group_name):
        return 0
        
    try:
        collection = get_contacts_collection()
        return collection.count_documents({"group_name": group_name})
    except PyMongoError as e:
        logger.error("Error counting contacts for group %s: %s", group_name, e)
        return 0

def group_stats(group_name: str) -> Dict[str, Any]:
    """Return comprehensive stats about a group."""
    if not validate_group_name(group_name):
        return {"error": "Invalid group name"}
        
    try:
        collection = get_contacts_collection()
        
        pipeline = [
            {"$match": {"group_name": group_name}},
            {"$group": {
                "_id": "$group_name",
                "total": {"$sum": 1},
                "valid_count": {"$sum": {"$cond": ["$valid", 1, 0]}},
                "invalid_count": {"$sum": {"$cond": ["$valid", 0, 1]}},
                "oldest_contact": {"$min": "$created_at"},
                "newest_contact": {"$max": "$created_at"}
            }}
        ]
        
        result = list(collection.aggregate(pipeline))
        if not result:
            return {"error": "Group not found"}
            
        stats = result[0]
        
        return {
            "group_name": group_name,
            "total": stats["total"],
            "valid": stats["valid_count"],
            "invalid": stats["invalid_count"],
            "oldest_contact": stats["oldest_contact"],
            "newest_contact": stats["newest_contact"],
            "valid_percentage": (stats["valid_count"] / stats["total"] * 100) if stats["total"] > 0 else 0
        }
        
    except PyMongoError as e:
        logger.error("Error getting stats for group %s: %s", group_name, e)
        return {"error": str(e)}

# ========= FILTERING AND SEARCH =========
def filter_contacts(
    new_group: str, 
    source_group: Optional[str] = None,
    domain: Optional[str] = None, 
    regex: Optional[str] = None, 
    only_valid: bool = True
) -> Tuple[int, List[str]]:
    """
    Filter contacts by domain, regex, or validity with comprehensive error handling.
    
    Returns:
        Tuple of (contacts_created_count, error_messages)
    """
    if not validate_group_name(new_group):
        raise ValueError(f"Invalid new group name: {new_group}")
        
    if regex:
        try:
            re.compile(regex)  # Test regex validity
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {str(e)}")

    error_messages = []
    created_count = 0
    
    try:
        collection = get_contacts_collection()
        
        # Build query
        query = {}
        if source_group:
            query["group_name"] = source_group
        if domain:
            query["email"] = {"$regex": f".*{domain}$", "$options": "i"}
        if regex:
            query["email"] = {"$regex": regex}
        if only_valid:
            query["valid"] = True
        
        # Find matching contacts
        matching_contacts = collection.find(query, projection={"name": 1, "email": 1, "valid": 1})
        
        # Prepare bulk insert operations
        bulk_operations = []
        for contact in matching_contacts:
            new_contact = {
                "group_name": new_group,
                "name": contact.get("name"),
                "email": contact["email"],
                "valid": contact["valid"],
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            bulk_operations.append(
                UpdateOne(
                    {"email": contact["email"], "group_name": new_group},
                    {"$setOnInsert": new_contact},
                    upsert=True
                )
            )
        
        # Execute bulk operations
        if bulk_operations:
            result = collection.bulk_write(bulk_operations, ordered=False)
            created_count = result.upserted_count
            
    except PyMongoError as e:
        logger.error("Error filtering contacts: %s", e)
        error_messages.append(f"Filtering error: {str(e)}")
    
    logger.info(
        "Filtered %d contacts into group %s (%d errors)",
        created_count, new_group, len(error_messages)
    )
    
    return created_count, error_messages

# ========= EXPORT FUNCTIONALITY =========
def export_group_to_csv(group_name: str, output_file: str) -> str:
    """Export group contacts to CSV with error handling."""
    if not validate_group_name(group_name):
        raise ValueError(f"Invalid group name: {group_name}")
        
    try:
        collection = get_contacts_collection()
        
        contacts = collection.find(
            {"group_name": group_name},
            projection={"name": 1, "email": 1, "valid": 1}
        ).sort("email", pymongo.ASCENDING)
        
        contacts_list = list(contacts)
        if not contacts_list:
            raise ValueError(f"No contacts found in group: {group_name}")
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
        
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "Email", "Valid"])
            for contact in contacts_list:
                writer.writerow([
                    contact.get("name", ""),
                    contact["email"],
                    "Yes" if contact.get("valid", False) else "No"
                ])
            
        logger.info("Exported %d contacts from %s to %s", len(contacts_list), group_name, output_file)
        return output_file
        
    except PyMongoError as e:
        logger.error("Error exporting group %s: %s", group_name, e)
        raise

# ========= HEALTH CHECK =========
def health_check() -> Dict[str, Any]:
    """Perform health check on contacts module."""
    health = {
        "module": "contacts",
        "status": "unknown",
        "database_accessible": False,
        "total_contacts": 0,
        "total_groups": 0,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        # Test database connection and basic operations
        collection = get_contacts_collection()
        
        # Test connection with a simple command
        collection.database.command('ping')
        health["database_accessible"] = True
        
        # Count total contacts
        health["total_contacts"] = collection.count_documents({})
        
        # Count distinct groups
        health["total_groups"] = len(collection.distinct("group_name"))
        
        # Get database stats
        db_stats = collection.database.command("dbstats")
        health["database_stats"] = {
            "collections": db_stats.get("collections", 0),
            "objects": db_stats.get("objects", 0),
            "data_size": db_stats.get("dataSize", 0)
        }
        
        if health["database_accessible"]:
            health["status"] = "healthy"
        else:
            health["status"] = "degraded"
            health["warning"] = "Database connection issue"
                
    except Exception as e:
        health["status"] = "error"
        health["error"] = str(e)
    
    return health

# ========= MODULE INITIALIZATION =========
def _initialize_module():
    """Initialize contacts module on import."""
    try:
        init_db()
        health = health_check()
        if health["status"] == "healthy":
            logger.info(
                "Contacts module initialized: %d contacts in %d groups",
                health["total_contacts"], health["total_groups"]
            )
        else:
            logger.warning("Contacts module initialized with issues: %s", health.get("error", "Unknown"))
    except Exception as e:
        logger.error("Failed to initialize contacts module: %s", e)

# Initialize on import
_initialize_module()

# ========= CLI TEST =========
if __name__ == "__main__":
    print("📇 Contacts Module Production Test")
    print("=" * 50)
    
    # Health check
    health = health_check()
    print(f"Health Status: {health['status']}")
    print(f"Database Accessible: {health['database_accessible']}")
    print(f"Total Contacts: {health['total_contacts']}")
    print(f"Total Groups: {health['total_groups']}")
    
    if health["status"] == "healthy":
        # List groups
        groups = list_groups()
        print(f"\n📁 Contact Groups ({len(groups)}):")
        for group in groups[:5]:  # Show first 5 groups
            stats = group_stats(group)
            print(f"  - {group}: {stats['total']} contacts ({stats['valid_percentage']:.1f}% valid)")
        
        if len(groups) > 5:
            print(f"  ... and {len(groups) - 5} more groups")
    
    print("\n" + "=" * 50)
    print("Contacts Module Test Complete")