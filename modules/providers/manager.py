from aiogram import Router, types, F
from aiogram.filters import Command
from pymongo import MongoClient
from bson import ObjectId
import os
import json

MONGO_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB_NAME", "PulseMailerBot")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]

router = Router()

# --- Add provider ---
@router.message(Command("add_provider"))
async def add_provider(message: types.Message):
    await message.answer(
        "Send provider info in JSON format.\n"
        "Example for SMTP:\n"
        '{"name":"My SMTP","type":"SMTP","config":{"host":"smtp.example.com","port":587,"user":"email@example.com","password":"pass"},"imap_config":{"host":"imap.example.com","user":"email@example.com","pass":"pass"}}\n\n'
        "Example for API:\n"
        '{"name":"HubSpot","type":"API","config":{"api_key":"your-api-key","from_email":"email@example.com","from_name":"Company"}}'
    )

@router.message(F.text)
async def save_provider(message: types.Message):
    try:
        data = json.loads(message.text)
        required_keys = ["name", "type", "config"]
        if not all(k in data for k in required_keys):
            await message.answer("Invalid JSON. Must include 'name', 'type', 'config'.")
            return
        data["type"] = data["type"].upper()
        db.providers.insert_one(data)
        await message.answer(f"Provider '{data['name']}' added successfully.")
    except Exception as e:
        await message.answer(f"Error adding provider: {e}")

# --- List providers ---
@router.message(Command("list_providers"))
async def list_providers(message: types.Message):
    providers = list(db.providers.find({}))
    if not providers:
        await message.answer("No providers found.")
        return
    text = "Providers:\n"
    for p in providers:
        text += f"{p['_id']} | {p['name']} | {p['type']}\n"
    await message.answer(text)

# --- Remove provider ---
@router.message(Command("remove_provider"))
async def remove_provider(message: types.Message):
    try:
        provider_id = message.text.split(" ", 1)[1]
        result = db.providers.delete_one({"_id": ObjectId(provider_id)})
        if result.deleted_count:
            await message.answer("Provider removed successfully.")
        else:
            await message.answer("Provider not found.")
    except Exception as e:
        await message.answer(f"Error removing provider: {e}")