# db.py
import os
from pymongo import MongoClient, errors
from functools import lru_cache
import logging

# -------------------- ENV --------------------
MONGO_URI = os.getenv(
    "MONGODB_URI",
    "mongodb+srv://pulsemailerbot:swagame4life@pulsemailerbot.5p3xa5j.mongodb.net/?retryWrites=true&w=majority&appName=PulseMailerBot"
)
MONGO_DB_NAME = os.getenv("MONGODB_DB_NAME", "PulseMailerBot")

# -------------------- Logging --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db")

# -------------------- MongoDB Connection --------------------
@lru_cache(maxsize=None)
def get_db():
    """
    Returns a MongoDB database instance.
    Uses caching to ensure only one client instance is created.
    """
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        # Trigger connection to check if MongoDB is reachable
        client.admin.command("ping")
        db = client[MONGO_DB_NAME]
        logger.info(f"Connected to MongoDB database: {MONGO_DB_NAME}")
        return db
    except errors.ServerSelectionTimeoutError as e:
        logger.error(f"Could not connect to MongoDB: {e}")
        raise RuntimeError(f"Could not connect to MongoDB: {e}")

def get_collection(name: str):
    """
    Returns a MongoDB collection instance.
    Usage:
        templates_col = get_collection("templates")
    """
    db = get_db()
    return db[name]

# -------------------- Optional Helpers --------------------
def safe_insert(collection_name: str, doc: dict):
    try:
        col = get_collection(collection_name)
        result = col.insert_one(doc)
        return result.inserted_id
    except Exception as e:
        logger.error(f"Insert failed for collection {collection_name}: {e}")
        return None

def safe_find(collection_name: str, query: dict = {}, projection: dict = None):
    try:
        col = get_collection(collection_name)
        return list(col.find(query, projection))
    except Exception as e:
        logger.error(f"Find failed for collection {collection_name}: {e}")
        return []

def safe_update(collection_name: str, query: dict, update: dict):
    try:
        col = get_collection(collection_name)
        return col.update_many(query, {"$set": update})
    except Exception as e:
        logger.error(f"Update failed for collection {collection_name}: {e}")
        return None

def safe_delete(collection_name: str, query: dict):
    try:
        col = get_collection(collection_name)
        return col.delete_many(query)
    except Exception as e:
        logger.error(f"Delete failed for collection {collection_name}: {e}")
        return None