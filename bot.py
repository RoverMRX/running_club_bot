"""
bot.py — точка входа IT БЕГОТНЯ 21.

Запускает polling + APScheduler.
Планировщик работает в часовом поясе Asia/Omsk (UTC+6).
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from database import init_db


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    await init_db()

    # ── Бот ─────────────────────────────────────────────────────────
    session = AiohttpSession(proxy=config.PROXY_URL) if config.PROXY_URL else None
    bot = Bot(
        token=config.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # ── Роутеры ─────────────────────────────────────────────────────
    from handlers import router
    from services.scheduler import setup_scheduler

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # ── Планировщик (Asia/Omsk) ──────────────────────────────────────
    scheduler = AsyncIOScheduler(timezone="Asia/Omsk")
    setup_scheduler(scheduler, bot)
    scheduler.start()

    print("🚀 IT БЕГОТНЯ 21 — бот запущен!")
    if config.GROUP_ID:
        print(f"   Группа: {config.GROUP_ID}")
    print(f"   Админы: {config.ADMIN_IDS}")
    print(f"   Часовой пояс планировщика: Asia/Omsk")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass