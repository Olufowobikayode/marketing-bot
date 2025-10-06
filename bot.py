import os
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI
import uvicorn

# -------------------- ENV --------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8000))

# -------------------- TELEGRAM BOT --------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
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

# -------------------- Main Async Runner --------------------
async def main():
    # Run Aiogram bot
    from aiogram import F
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    import logging

    logging.basicConfig(level=logging.INFO)

    async def start_bot():
        try:
            async with AiohttpSession():  # ensure proper session usage
                await dp.start_polling(bot)
        except Exception as e:
            logging.error(f"Bot polling error: {e}")

    async def start_fastapi():
        config = uvicorn.Config(fast_app, host="0.0.0.0", port=PORT, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    # Run both concurrently
    await asyncio.gather(
        start_bot(),
        start_fastapi()
    )

if __name__ == "__main__":
    asyncio.run(main())