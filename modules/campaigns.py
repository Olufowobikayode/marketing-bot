from aiogram import Router, types, F
from aiogram.filters import Command
from pymongo import MongoClient
from bson import ObjectId
import os
import json
import time

MONGO_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB_NAME", "PulseMailerBot")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]

router = Router()
DATA_DIR = os.getenv("DATA_DIR", "data")

# ----------------- Create Campaign -----------------
@router.message(Command("create_campaign"))
async def create_campaign(message: types.Message):
    await message.answer(
        "Send campaign JSON:\n"
        '{"subject":"Your subject","body":"Email body with {firstname} and {unsubscribe_link}","group_id":"optional_group_id","attachments":[],"images":[]}'
    )

@router.message(F.text)
async def save_campaign(message: types.Message):
    try:
        data = json.loads(message.text)
        required_keys = ["subject","body"]
        if not all(k in data for k in required_keys):
            await message.answer("Invalid JSON. Must include 'subject' and 'body'.")
            return
        data["status"] = "draft"
        db.campaigns.insert_one(data)
        await message.answer(f"Campaign '{data['subject']}' saved as draft.")
    except Exception as e:
        await message.answer(f"Error creating campaign: {e}")

# ----------------- List Campaigns -----------------
@router.message(Command("list_campaigns"))
async def list_campaigns(message: types.Message):
    campaigns = list(db.campaigns.find({}))
    if not campaigns:
        await message.answer("No campaigns found.")
        return
    text = "Campaigns:\n"
    for c in campaigns:
        text += f"{c['_id']} | {c['subject']} | {c['status']}\n"
    await message.answer(text)

# ----------------- Delete Campaign -----------------
@router.message(Command("delete_campaign"))
async def delete_campaign(message: types.Message):
    try:
        campaign_id = message.text.split(" ",1)[1]
        result = db.campaigns.delete_one({"_id": ObjectId(campaign_id)})
        if result.deleted_count:
            await message.answer("Campaign deleted successfully.")
        else:
            await message.answer("Campaign not found.")
    except Exception:
        await message.answer("Usage: /delete_campaign <campaign_id>")

# ----------------- AI Generated Campaign (Optional) -----------------
@router.message(Command("generate_campaign_ai"))
async def generate_campaign_ai(message: types.Message):
    """
    Example integration with AI service (Gemini API key from env)
    Generates subject and body automatically.
    """
    try:
        import openai
        openai.api_key = os.getenv("GEMINI_API_KEY")

        prompt = "Generate a marketing email subject and body for my campaign. Respond JSON with 'subject' and 'body'."
        response = openai.Completion.create(
            model="gpt-4",
            prompt=prompt,
            max_tokens=300
        )
        text = response.choices[0].text.strip()
        await message.answer(f"AI Generated Campaign:\n{text}\nSend this JSON to /create_campaign to save.")
    except Exception as e:
        await message.answer(f"AI generation failed: {e}")