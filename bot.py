import os
import asyncio
import logging
from fastapi import FastAPI, Request, Path
import uvicorn

from aiogram import Bot, Dispatcher, types
from aiogram.client.bot import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from aiogram.filters import Command

# -------------------- HARD-CODED BOT --------------------
BOT_TOKEN = "8301662693:AAG22_FCPQzbliZKs75OvOS-bJTnhSJ499s"
PORT = int(os.getenv("PORT", 8000))
WEBHOOK_URL = f"https://marketing-bot-95x3.onrender.com/webhook/{BOT_TOKEN}"

# -------------------- BOT & DISPATCHER --------------------
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode="HTML",
        link_preview_is_disabled=True
    )
)
dp = Dispatcher(storage=MemoryStorage())

# -------------------- IMPORT ROUTERS --------------------
from modules.contacts import router as contacts_router
from modules.campaigns import router as campaigns_router
from modules.providers.manager import router as provider_router
from modules.providers.send_engine import router as send_router
from modules.templates import router as template_router
from modules.unsubscribe import app as unsubscribe_app

dp.include_router(contacts_router)
dp.include_router(campaigns_router)
dp.include_router(provider_router)
dp.include_router(send_router)
dp.include_router(template_router)

# -------------------- FASTAPI APP --------------------
fast_app = FastAPI()
fast_app.mount("/", unsubscribe_app)

# -------------------- WEBHOOK ENDPOINT --------------------
@fast_app.post("/webhook/{token}")
async def telegram_webhook(token: str = Path(...), request: Request = None):
    update_data = await request.json()
    logging.info(f"Received update for token: {token}: {update_data}")
    try:
        update = Update(**update_data)
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.error(f"Webhook update error: {e}")
    return {"ok": True}

# -------------------- /start COMMAND --------------------
@dp.message(Command("start"))
async def start_command(message: types.Message):
    text = (
        "👋 Welcome to Pulse Mailer Bot!\n\n"
        "Available commands:\n"
        "/start - Show this message\n"
        "/create_campaign - Create a new campaign\n"
        "/list_campaigns - List all campaigns\n"
        "/delete_campaign <id> - Delete a campaign\n"
        "/generate_campaign_ai - AI-generated campaign\n"
        "/list_contacts - List all contacts\n"
        "/add_contact - Add a new contact\n"
        "/import_contacts - Import contacts via file\n"
        "/list_providers - Show providers\n"
        "/add_provider - Add a provider\n"
        "/send_campaign - Send a campaign\n"
        "/templates - Show templates\n"
        "/upload_template - Upload a new template\n"
    )
    await message.answer(text)

# -------------------- STARTUP & SHUTDOWN --------------------
async def on_startup():
    logging.info("Starting bot with webhook...")
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set to {WEBHOOK_URL}")

async def on_shutdown():
    logging.info("Shutting down...")
    await bot.delete_webhook()
    await bot.session.close()

# -------------------- MAIN RUNNER --------------------
async def main():
    logging.basicConfig(level=logging.INFO)
    await on_startup()

    config = uvicorn.Config(fast_app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())