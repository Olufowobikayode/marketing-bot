from aiogram import Router, types, F
from aiogram.filters import Command
from pymongo import MongoClient
from bson import ObjectId
import os
import pandas as pd
from email_validator import validate_email, EmailNotValidError
import json
import httpx

MONGO_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB_NAME", "PulseMailerBot")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]

router = Router()

DATA_DIR = os.getenv("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ----------------- Email Lookup Helper -----------------
def lookup_name_by_email(email_address):
    provider = db.email_lookup_providers.find_one({})
    if not provider:
        return None, None
    try:
        if provider['type'] == "API":
            config = provider['config']
            response = httpx.get(
                config['endpoint'],
                params={"email": email_address, "api_key": config['api_key']},
                timeout=10
            )
            data = response.json()
            first_name = data.get("data", {}).get("first_name")
            last_name = data.get("data", {}).get("last_name")
            return first_name, last_name
    except Exception:
        return None, None
    return None, None

# ----------------- Add Contacts -----------------
@router.message(Command("add_contacts"))
async def add_contacts(message: types.Message):
    await message.answer(
        "Please upload a CSV, TXT, or Excel file containing contacts.\n"
        "Columns: first_name,last_name,email"
    )

@router.message(F.content_type.in_({"document"}))
async def handle_contacts_file(message: types.Message):
    file_id = message.document.file_id
    file = await message.bot.get_file(file_id)
    file_path = file.file_path
    file_ext = message.document.file_name.split(".")[-1].lower()
    download_path = os.path.join(DATA_DIR, message.document.file_name)
    await message.bot.download_file(file_path, download_path)

    try:
        if file_ext in ["csv","txt"]:
            df = pd.read_csv(download_path)
        elif file_ext in ["xlsx","xls"]:
            df = pd.read_excel(download_path)
        else:
            await message.answer("Unsupported file format.")
            return
    except Exception as e:
        await message.answer(f"Failed to read file: {e}")
        return

    added, skipped = 0, 0
    for _, row in df.iterrows():
        email_val = str(row.get("email","")).strip()
        first_name = str(row.get("first_name","")).strip()
        last_name = str(row.get("last_name","")).strip()

        try:
            valid = validate_email(email_val).email
            if db.contacts.find_one({"email": valid}):
                skipped += 1
                continue

            # Lookup missing names
            if not first_name or not last_name:
                fn, ln = lookup_name_by_email(valid)
                first_name = first_name or fn or "FirstName"
                last_name = last_name or ln or "LastName"

            db.contacts.insert_one({
                "first_name": first_name,
                "last_name": last_name,
                "email": valid,
                "groups": []
            })
            added += 1
        except EmailNotValidError:
            skipped += 1
            continue

    await message.answer(f"Contacts processed. Added: {added}, Skipped: {skipped}")

# ----------------- List Contacts -----------------
@router.message(Command("list_contacts"))
async def list_contacts(message: types.Message):
    contacts = list(db.contacts.find({}))
    if not contacts:
        await message.answer("No contacts found.")
        return
    text = "Contacts:\n"
    for idx, c in enumerate(contacts, start=1):
        text += f"{idx}. {c.get('first_name','')} {c.get('last_name','')} | {c.get('email','')}\n"
    await message.answer(text)

# ----------------- Group Management -----------------
@router.message(Command("add_group"))
async def add_group(message: types.Message):
    group_name = message.text.split(" ",1)[1] if len(message.text.split())>1 else None
    if not group_name:
        await message.answer("Usage: /add_group <group_name>")
        return
    if db.groups.find_one({"name": group_name}):
        await message.answer("Group already exists.")
        return
    db.groups.insert_one({"name": group_name})
    await message.answer(f"Group '{group_name}' added.")

@router.message(Command("list_groups"))
async def list_groups(message: types.Message):
    groups = list(db.groups.find({}))
    if not groups:
        await message.answer("No groups found.")
        return
    text = "Groups:\n"
    for g in groups:
        text += f"{g['_id']} | {g['name']}\n"
    await message.answer(text)

@router.message(Command("rename_group"))
async def rename_group(message: types.Message):
    try:
        _, group_id, new_name = message.text.split(" ",2)
        db.groups.update_one({"_id": ObjectId(group_id)}, {"$set":{"name":new_name}})
        await message.answer("Group renamed successfully.")
    except:
        await message.answer("Usage: /rename_group <group_id> <new_name>")

@router.message(Command("delete_group"))
async def delete_group(message: types.Message):
    try:
        group_id = message.text.split(" ",1)[1]
        db.groups.delete_one({"_id": ObjectId(group_id)})
        db.contacts.update_many({}, {"$pull":{"groups":ObjectId(group_id)}})
        await message.answer("Group deleted successfully.")
    except:
        await message.answer("Usage: /delete_group <group_id>")

# ----------------- Email Lookup Provider Management -----------------
@router.message(Command("add_lookup_provider"))
async def add_lookup_provider(message: types.Message):
    await message.answer(
        "Send email lookup provider JSON:\n"
        '{"name":"Hunter","type":"API","config":{"api_key":"your-api-key","endpoint":"https://api.hunter.io/v2/email-finder"}}'
    )

@router.message(Command("list_lookup_providers"))
async def list_lookup_providers(message: types.Message):
    providers = list(db.email_lookup_providers.find({}))
    if not providers:
        await message.answer("No email lookup providers found.")
        return
    text = "Email Lookup Providers:\n"
    for p in providers:
        text += f"{p['_id']} | {p['name']} | {p['type']}\n"
    await message.answer(text)

@router.message(Command("update_lookup_provider"))
async def update_lookup_provider(message: types.Message):
    try:
        parts = message.text.split(" ",2)
        if len(parts) < 3:
            await message.answer("Usage: /update_lookup_provider <provider_id> <JSON>")
            return
        provider_id = parts[1]
        data = json.loads(parts[2])
        db.email_lookup_providers.update_one({"_id": ObjectId(provider_id)}, {"$set": data})
        await message.answer("Email lookup provider updated successfully.")
    except Exception as e:
        await message.answer(f"Error updating provider: {e}")

@router.message(Command("delete_lookup_provider"))
async def delete_lookup_provider(message: types.Message):
    try:
        provider_id = message.text.split(" ",1)[1]
        result = db.email_lookup_providers.delete_one({"_id": ObjectId(provider_id)})
        if result.deleted_count:
            await message.answer("Email lookup provider deleted successfully.")
        else:
            await message.answer("Provider not found.")
    except Exception:
        await message.answer("Usage: /delete_lookup_provider <provider_id>")