# db.py
import os
from pymongo import MongoClient, errors
from functools import lru_cache

# -------------------- ENV --------------------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "marketing_bot")

# -------------------- MongoDB Connection --------------------
@lru_cache(maxsize=None)
def get_db():
    """
    Returns a MongoDB database instance.
    Uses caching to ensure only one client instance is created.
    """
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Trigger connection to check if MongoDB is reachable
        client.admin.command("ping")
        db = client[MONGO_DB_NAME]
        return db
    except errors.ServerSelectionTimeoutError as e:
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
    col = get_collection(collection_name)
    result = col.insert_one(doc)
    return result.inserted_id

def safe_find(collection_name: str, query: dict = {}, projection: dict = None):
    col = get_collection(collection_name)
    return list(col.find(query, projection))

def safe_update(collection_name: str, query: dict, update: dict):
    col = get_collection(collection_name)
    return col.update_many(query, {"$set": update})

def safe_delete(collection_name: str, query: dict):
    col = get_collection(collection_name)
    return col.delete_many(query)