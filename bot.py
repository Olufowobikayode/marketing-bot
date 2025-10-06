import asyncio
import logging
from fastapi import FastAPI, Request
import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update

# -------------------- HARD-CODED --------------------
BOT_TOKEN = "8301662693:AAG22_FCPQzbliZKs75OvOS-bJTnhSJ499s"
WEBHOOK_URL = f"https://marketing-bot-95x3.onrender.com/webhook/{BOT_TOKEN}"
PORT = 8000  # Render will assign actual port automatically

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode="HTML",
        link_preview_is_disabled=True
    )
)
dp = Dispatcher(storage=MemoryStorage())

# -------------------- Import Routers --------------------
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

# -------------------- FASTAPI --------------------
fast_app = FastAPI()
fast_app.mount("/", unsubscribe_app)

# Webhook endpoint for Telegram
@fast_app.post(f"/webhook/{BOT_TOKEN}")
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
        update = Update(**update_data)
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.error(f"Webhook update error: {e}")
    return {"ok": True}

# -------------------- Startup / Shutdown --------------------
async def on_startup():
    logging.info("Starting bot with webhook...")
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set to {WEBHOOK_URL}")

async def on_shutdown():
    logging.info("Shutting down...")
    await bot.delete_webhook()
    await bot.session.close()

# -------------------- Main Runner --------------------
async def main():
    logging.basicConfig(level=logging.INFO)
    config = uvicorn.Config(fast_app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)

    await on_startup()
    try:
        await server.serve()
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())