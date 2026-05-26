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
from aiogram.types import MenuButtonWebApp, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from database import init_db

WEBAPP_URL = "https://run.archer-srv.ru"


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

    # ── Кнопка меню — открывает Mini App прямо из личного чата ──────
    # Устанавливается один раз при старте, сохраняется в Telegram.
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="🏃 Открыть",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        )
        logging.getLogger(__name__).info("Menu button (WebApp) set successfully")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Could not set menu button: {e}")

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
    print(f"   Mini App: {WEBAPP_URL}")

    # Retry delete_webhook — прокси может быть временно недоступен
    import asyncio as _asyncio
    for attempt in range(10):
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            break
        except Exception as e:
            if attempt < 9:
                wait = 5 * (attempt + 1)
                logging.getLogger("__main__").warning(
                    "delete_webhook failed (%s), retry in %ds...", e, wait
                )
                await _asyncio.sleep(wait)
            else:
                logging.getLogger("__main__").error("delete_webhook failed after 10 attempts: %s", e)

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
