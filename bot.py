import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from database import init_db
from handlers import router, send_weekly_digest


async def main():
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    await init_db()

    session = AiohttpSession(proxy=config.PROXY_URL) if config.PROXY_URL else None
    bot = Bot(
        token=config.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # ----------------------------------------------------------------
    # Планировщик:
    #   Каждое воскресенье в 21:00 (МСК, UTC+3) — еженедельный дайджест.
    #   Вместе с этим сбрасываются счётчики за неделю и обновляются стрики.
    # ----------------------------------------------------------------
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        send_weekly_digest,
        trigger=CronTrigger(day_of_week="sun", hour=21, minute=0),
        args=[bot],
        id="weekly_digest",
        replace_existing=True,
    )
    scheduler.start()

    print("🚀 IT БЕГОТНЯ 21 — бот запущен!")
    if config.GROUP_ID:
        print(f"   Группа: {config.GROUP_ID}")
    print(f"   Админы: {config.ADMIN_IDS}")
    print(f"   Дайджест: каждое воскресенье в 21:00 МСК")

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